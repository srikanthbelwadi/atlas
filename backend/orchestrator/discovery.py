"""
Discover stage — ARD-style candidate resolution.

Two sources of candidates, merged:

  1. BigQuery public datasets, via the crawler-maintained `ard_catalog`
     dataset in our own project: `ard_catalog.embeddings` holds one row per
     crawled Table/AttestedComputation OKF doc (doc_id, embedding, metadata
     JSON). We embed the question once (llm.embed) and rank candidates with
     BigQuery's native VECTOR_SEARCH — no separate vector DB to run.

  2. Hand-authored OKF docs living in `okf-catalog/` (curated Attested
     Computations, and Resource Raiser's original non-BQ sources ported to
     OKF) — small enough to embed and rank in-process without a round trip.

Both paths return the same shape so `pipeline.py` doesn't care which kind of
source it ends up planning against.
"""
import json
import math
import os

from google.cloud import bigquery

from . import llm
from ..accessor import okf_loader

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "atlas-ard-okf")
ARD_CATALOG_DATASET = os.environ.get("ATLAS_ARD_CATALOG_DATASET", "ard_catalog")
TOP_K = int(os.environ.get("ATLAS_DISCOVERY_TOP_K", 6))

_bq_client = None


def _bq() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _search_bq_catalog(question_embedding: list[float], top_k: int) -> list[dict]:
    """VECTOR_SEARCH over the crawler-maintained embeddings table. Returns []
    gracefully if the table doesn't exist yet (fresh deploy, crawler hasn't
    run) rather than failing discovery entirely."""
    table = f"`{PROJECT_ID}.{ARD_CATALOG_DATASET}.embeddings`"
    sql = f"""
        SELECT base.doc_id, base.metadata, distance
        FROM VECTOR_SEARCH(
            TABLE {table},
            'embedding',
            (SELECT @question_embedding AS embedding),
            top_k => @top_k,
            distance_type => 'COSINE'
        )
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("question_embedding", "FLOAT64", question_embedding),
            bigquery.ScalarQueryParameter("top_k", "INT64", top_k),
        ]
    )
    try:
        rows = list(_bq().query(sql, job_config=job_config).result(timeout=15))
    except Exception as exc:  # noqa: BLE001 — missing table/dataset on a fresh env is expected pre-crawl
        print(f"[discovery] ard_catalog VECTOR_SEARCH unavailable, skipping: {exc}")
        return []

    out = []
    for row in rows:
        meta = json.loads(row.metadata) if isinstance(row.metadata, str) else (row.metadata or {})
        out.append({
            "source_id": row.doc_id,
            "kind": "bigquery",
            "title": meta.get("title", row.doc_id),
            "description": meta.get("description", ""),
            "trust": meta.get("trust", "machine-confirmed"),
            "type": meta.get("type", "Table"),
            "score": 1 - float(row.distance),
        })
    return out


def _search_okf_catalog(question_embedding: list[float], top_k: int) -> list[dict]:
    """In-process cosine ranking over hand-authored okf-catalog/ docs. Small
    corpus (curated templates + ported non-BQ sources) — no need for a
    vector index; embeddings are cheap to recompute per request for now and
    can be cached once the catalog grows."""
    candidates = []
    for doc in okf_loader.load_all():
        text = f"{doc.title}\n{doc.description}\n{' '.join(doc.tags)}"
        emb = llm.embed(text)
        score = _cosine(question_embedding, emb)
        candidates.append({
            "source_id": doc.id,
            "kind": doc.source.get("kind", "okf"),
            "title": doc.title,
            "description": doc.description,
            "trust": doc.trust,
            "type": doc.type,
            "score": score,
        })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:top_k]


def discover(question: str) -> list[dict]:
    """Returns merged, score-sorted candidates from BigQuery public-dataset
    coverage and the hand-authored OKF catalog, deduplicated by source_id."""
    question_embedding = llm.embed(question)
    candidates = _search_bq_catalog(question_embedding, TOP_K) + _search_okf_catalog(question_embedding, TOP_K)

    seen = {}
    for c in candidates:
        existing = seen.get(c["source_id"])
        if existing is None or c["score"] > existing["score"]:
            seen[c["source_id"]] = c

    ranked = sorted(seen.values(), key=lambda c: c["score"], reverse=True)
    return ranked[:TOP_K]
