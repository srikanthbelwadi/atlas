"""
Access: which catalog documents a user may be offered and may query.

Two layers, deliberately distinct:

  BigQuery IAM   decides what the orchestrator's service account can READ.
                 The private `finance_demo` dataset has no public binding,
                 so nothing outside this project can read it at all.
  Entitlements   decide which Atlas USERS may be offered a private source.
                 `users/{uid}.entitlements` in Firestore is a list of
                 strings; a private document names the entitlement it
                 needs (`access.entitlement` in OKF frontmatter, or the
                 `entitlement` key in a crawled row's metadata).

A public document (no `visibility`, or `visibility: public`) needs nothing.
A private document is *withheld* from discovery for a user without its
entitlement — it never reaches the planner, so the planner cannot route to
it, and the trace says how many sources were withheld and why. Should a
private document reach the fetch stage anyway (a composite step, a stale
plan, a bug), `assert_may_query` refuses it there too; and ad-hoc SQL is
scanned for references to private datasets before it runs, because a
planner that has seen a table name once could repeat it from memory.

Enforcement is by entitlement, not by trying to recreate IAM in Python:
the receipt records the entitlement that unlocked a private answer, which
is the artefact a reviewer asks for.
"""
from __future__ import annotations

import re

from ..accessor import okf_loader

PRIVATE = "private"


def is_private(meta_or_doc) -> bool:
    if isinstance(meta_or_doc, dict):
        return (meta_or_doc.get("visibility") or "public") == PRIVATE
    return (getattr(meta_or_doc, "visibility", None) or "public") == PRIVATE


def required_entitlement(meta_or_doc) -> str | None:
    """The entitlement a document needs, or None for a public document."""
    if not is_private(meta_or_doc):
        return None
    if isinstance(meta_or_doc, dict):
        return meta_or_doc.get("entitlement") or (meta_or_doc.get("access") or {}).get("entitlement")
    return (getattr(meta_or_doc, "access", None) or {}).get("entitlement")


def may_see(meta_or_doc, entitlements: set[str] | list[str] | None) -> bool:
    need = required_entitlement(meta_or_doc)
    if need is None:
        return True
    return need in set(entitlements or ())


def split_candidates(candidates: list[dict], entitlements) -> tuple[list[dict], list[dict]]:
    """(visible, withheld). Withheld entries keep only what the trace shows:
    id, title, the entitlement they need, and the score — never the
    description, which for a private source is itself restricted."""
    visible, withheld = [], []
    for c in candidates:
        if may_see(c, entitlements):
            visible.append(c)
        else:
            withheld.append({"source_id": c["source_id"], "title": c.get("title", c["source_id"]),
                             "entitlement": required_entitlement(c), "score": round(float(c.get("score", 0)), 3)})
    return visible, withheld


class AccessDenied(Exception):
    def __init__(self, doc_id: str, entitlement: str | None):
        self.doc_id, self.entitlement = doc_id, entitlement
        super().__init__(f"{doc_id} is private and needs the '{entitlement}' entitlement")


def assert_may_query(doc, entitlements) -> None:
    """Fetch-stage check for an OKF document (template or table doc)."""
    if doc is not None and not may_see(doc, entitlements):
        raise AccessDenied(doc.id, required_entitlement(doc))


_private_datasets_cache: dict[str, str] | None = None


def private_datasets() -> dict[str, str]:
    """{'project.dataset': entitlement} for every private dataset the catalog
    knows about — from the hand-authored docs' `source` blocks and the
    crawler's target list. Computed once per process."""
    global _private_datasets_cache
    if _private_datasets_cache is None:
        found: dict[str, str] = {}
        for doc in okf_loader.load_all():
            if is_private(doc):
                for src in (doc.sources or [doc.source]):
                    if src and src.get("project") and src.get("dataset"):
                        found[f"{src['project']}.{src['dataset']}"] = required_entitlement(doc) or ""
        try:
            from ..crawler.targets import CRAWL_TARGETS
            for entry in CRAWL_TARGETS:
                access = entry[3] if len(entry) > 3 else {}
                if access.get("visibility") == PRIVATE:
                    found[f"{entry[0]}.{entry[1]}"] = access.get("entitlement") or ""
        except Exception:  # noqa: BLE001 — the crawler package isn't shipped in every image
            pass
        _private_datasets_cache = found
    return _private_datasets_cache


def check_sql_references(sql: str, entitlements) -> None:
    """Refuse ad-hoc SQL that touches a private dataset the user isn't
    entitled to. Matches `project.dataset.` with or without backticks."""
    ents = set(entitlements or ())
    plain = re.sub(r"\s+", "", (sql or "").lower().replace("`", ""))
    for ds, need in private_datasets().items():
        if need in ents:
            continue
        if ds.lower() + "." in plain:
            raise AccessDenied(ds, need)
