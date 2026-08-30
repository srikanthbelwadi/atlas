"""
OKF catalog loader.

Reads the git-versioned `okf-catalog/` bundle (markdown + YAML frontmatter,
OKF v0.2) into memory: Dataset / Table / Attested Computation documents. This
is the source of truth for ARD discovery — the crawler (backend/crawler/)
regenerates the BigQuery-derived subset of these on a schedule; hand-authored
docs (e.g. curated Attested Computation SQL templates) live here permanently.

Kept deliberately dependency-light (python-frontmatter + pyyaml) so both the
orchestrator and the crawler can import it without pulling in BigQuery/Vertex
clients.
"""
import glob
import os
from dataclasses import dataclass, field

import frontmatter

CATALOG_ROOT = os.environ.get(
    "ATLAS_OKF_CATALOG_ROOT",
    os.path.join(os.path.dirname(__file__), "..", "..", "okf-catalog"),
)


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


def _load_one(path: str) -> OKFDocument:
    post = frontmatter.load(path)
    meta = post.metadata
    return OKFDocument(
        id=meta.get("id") or os.path.splitext(os.path.basename(path))[0],
        type=meta.get("type", "Dataset"),
        title=meta.get("title", ""),
        description=meta.get("description", ""),
        trust=meta.get("trust", "unverified"),
        source=meta.get("source", {}),
        tags=meta.get("tags", []) or [],
        computation=meta.get("computation"),
        body=post.content,
        path=path,
    )


def load_all(root: str | None = None) -> list[OKFDocument]:
    root = root or CATALOG_ROOT
    docs = []
    for path in sorted(glob.glob(os.path.join(root, "**", "*.md"), recursive=True)):
        try:
            docs.append(_load_one(path))
        except Exception as exc:  # noqa: BLE001 — one bad doc shouldn't break discovery
            print(f"[okf_loader] skipping {path}: {exc}")
    return docs


def load_by_id(doc_id: str, root: str | None = None) -> OKFDocument | None:
    for doc in load_all(root):
        if doc.id == doc_id:
            return doc
    return None
