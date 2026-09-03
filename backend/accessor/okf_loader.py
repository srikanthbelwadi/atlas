"""
OKF catalog loader.

Reads the git-versioned `okf-catalog/` bundle (markdown + YAML frontmatter,
OKF v0.2) into memory: Dataset / Table / Attested Computation documents. This
is the source of truth for ARD discovery — the crawler (backend/crawler/)
regenerates the BigQuery-derived subset of these on a schedule; hand-authored
docs (e.g. curated Attested Computation SQL templates) live here permanently.

Packs (added with the finance section): every document belongs to exactly
one pack, declared as `pack:` in its frontmatter. A document that doesn't
declare one is the original public demo's — `DEFAULT_PACK` — so nothing
about the existing catalog changed when packs were introduced. Discovery
filters by pack, which is what keeps the finance catalog and the public
catalog from ever seeing each other's sources.

OKF v0.2 governance fields (reviewer, reviewed_on, stale_after, lifecycle,
version, cost_profile, citation_template, sources) are read when present
and default to None/empty so the two original documents need no edits.

Kept deliberately dependency-light (python-frontmatter + pyyaml) so both the
orchestrator and the crawler can import it without pulling in BigQuery/Vertex
clients.
"""
import datetime as dt
import glob
import os
from dataclasses import dataclass, field

import frontmatter

CATALOG_ROOT = os.environ.get(
    "ATLAS_OKF_CATALOG_ROOT",
    os.path.join(os.path.dirname(__file__), "..", "..", "okf-catalog"),
)

DEFAULT_PACK = "public"


@dataclass
class OKFDocument:
    id: str
    type: str                      # "Dataset" | "Table" | "AttestedComputation"
    title: str
    description: str
    trust: str                     # "unverified" | "machine-confirmed" | "human-reviewed"
    source: dict                   # e.g. {"kind": "bigquery", "project": ..., "dataset": ..., "table": ...}
    body: str                      # markdown body (human-readable description / usage notes)
    path: str
    tags: list = field(default_factory=list)
    computation: dict | None = None  # present only for AttestedComputation docs
    pack: str = DEFAULT_PACK          # primary pack (first of `packs`)
    packs: list = field(default_factory=lambda: [DEFAULT_PACK])  # a doc may belong to several packs
    # --- OKF v0.2 governance fields (all optional) ---
    version: str | None = None
    reviewer: str | None = None
    reviewed_on: str | None = None     # ISO date
    stale_after: str | None = None     # ISO date; answers still run past it, but are flagged
    lifecycle: str = "active"          # "draft" | "active" | "deprecated"
    cost_profile: dict = field(default_factory=dict)   # {"expected_bytes": int, "cap_bytes": int}
    citation_template: str | None = None
    sources: list = field(default_factory=list)        # multi-source computations list every source here

    @property
    def is_stale(self) -> bool:
        if not self.stale_after:
            return False
        try:
            return dt.date.fromisoformat(str(self.stale_after)) < dt.date.today()
        except ValueError:
            return False

    @property
    def executor(self) -> str | None:
        """`computation.runtime.executor` for AttestedComputation docs, else None."""
        if not self.computation:
            return None
        return (self.computation.get("runtime") or {}).get("executor")

    def governance(self) -> dict:
        """The subset of fields the frontend's receipt and catalog show."""
        return {
            "version": self.version,
            "reviewer": self.reviewer,
            "reviewed_on": _iso(self.reviewed_on),
            "stale_after": _iso(self.stale_after),
            "stale": self.is_stale,
            "lifecycle": self.lifecycle,
            "trust": self.trust,
            "pack": self.pack,
        }


def _iso(value) -> str | None:
    """YAML parses bare dates into datetime.date; keep them as ISO strings."""
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return str(value)


def _packs(meta: dict) -> list[str]:
    """`packs: [public, finance]` for a document shared across packs, or a
    single `pack: finance`; neither means the public pack."""
    raw = meta.get("packs") or meta.get("pack") or DEFAULT_PACK
    if isinstance(raw, str):
        raw = [raw]
    out = [str(x).strip() for x in raw if str(x).strip()]
    return out or [DEFAULT_PACK]


def _load_one(path: str) -> OKFDocument:
    post = frontmatter.load(path)
    meta = post.metadata
    return OKFDocument(
        id=meta.get("id") or os.path.splitext(os.path.basename(path))[0],
        type=meta.get("type", "Dataset"),
        title=meta.get("title", ""),
        description=meta.get("description", ""),
        trust=meta.get("trust", "unverified"),
        source=meta.get("source", {}) or {},
        tags=meta.get("tags", []) or [],
        computation=meta.get("computation"),
        body=post.content,
        path=path,
        pack=_packs(meta)[0],
        packs=_packs(meta),
        version=_iso(meta.get("version")),
        reviewer=meta.get("reviewer"),
        reviewed_on=_iso(meta.get("reviewed_on")),
        stale_after=_iso(meta.get("stale_after")),
        lifecycle=str(meta.get("lifecycle") or "active"),
        cost_profile=meta.get("cost_profile") or {},
        citation_template=meta.get("citation_template"),
        sources=meta.get("sources") or [],
    )


def load_all(root: str | None = None, pack: str | None = None) -> list[OKFDocument]:
    """All documents in the catalog, or only those in `pack` when given.
    Deprecated documents are loaded (so a receipt can still name them) but
    discovery skips them — see discovery.py."""
    root = root or CATALOG_ROOT
    docs = []
    for path in sorted(glob.glob(os.path.join(root, "**", "*.md"), recursive=True)):
        try:
            doc = _load_one(path)
        except Exception as exc:  # noqa: BLE001 — one bad doc shouldn't break discovery
            print(f"[okf_loader] skipping {path}: {exc}")
            continue
        if pack is None or pack in doc.packs:
            docs.append(doc)
    return docs


def load_by_id(doc_id: str, root: str | None = None) -> OKFDocument | None:
    for doc in load_all(root):
        if doc.id == doc_id:
            return doc
    return None
