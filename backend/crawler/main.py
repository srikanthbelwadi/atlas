"""
Atlas crawler (Cloud Run Job, run on a weekly Cloud Scheduler trigger).

For each dataset in `targets.CRAWL_TARGETS`: enumerates its tables via
INFORMATION_SCHEMA, builds a deterministic (non-model-generated — see the
trust note below) description from the live schema, embeds it, and upserts
one row per table into `ard_catalog.embeddings` in our own project. That
table is what `backend/orchestrator/discovery.py` runs BigQuery
`VECTOR_SEARCH` against at query time.

Trust model note (OKF): these rows get `trust: machine-confirmed`, not
`human-reviewed` — the description text is templated straight from schema
metadata (table/column names, types, row/byte counts), never invented by a
model, so it can't hallucinate a table's contents, but nobody has read it and
vouched for its correctness the way the hand-authored `okf-catalog/` docs
have. Attested Computation templates always outrank these when the planner
has a choice.

Idempotent: re-running is a MERGE keyed on doc_id, so a weekly schedule just
refreshes row/byte counts and re-embeds only if the description text changed
enough to matter (we re-embed unconditionally for now — it's a handful of
tables and embedding calls are cheap; revisit if the target list grows).
"""
import argparse
import json
import os
import sys

from google.cloud import bigquery

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # allow `backend.*` imports when run standalone

from backend.orchestrator import llm  # noqa: E402
from backend.crawler.targets import CRAWL_TARGETS, LARGE_TABLE_THRESHOLD_GB  # noqa: E402

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "atlas-ard-okf")
ARD_CATALOG_DATASET = os.environ.get("ATLAS_ARD_CATALOG_DATASET", "ard_catalog")
EMBEDDING_DIM = 768  # text-embedding-005 default output size

_client = None


def client() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client(project=PROJECT_ID)
    return _client


def ensure_catalog_table() -> None:
    """Creates the ard_catalog dataset/table if this is the first run.
    Normally provisioned once via infra/setup.sql; kept here too so a fresh
    environment can bootstrap itself from just the crawler."""
    client().create_dataset(bigquery.Dataset(f"{PROJECT_ID}.{ARD_CATALOG_DATASET}"), exists_ok=True)
    ddl = f"""
        CREATE TABLE IF NOT EXISTS `{PROJECT_ID}.{ARD_CATALOG_DATASET}.embeddings` (
            doc_id STRING NOT NULL,
            embedding ARRAY<FLOAT64>,
            metadata JSON NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )
    """
    client().query(ddl).result()


def _describe_table(project: str, dataset: str, table_row) -> tuple[str, dict]:
    """Returns (embedding_text, metadata_dict) for one INFORMATION_SCHEMA.TABLES row."""
    table_name = table_row.table_name
    full_ref = f"{project}.{dataset}.{table_name}"

    cols_sql = f"""
        SELECT column_name, data_type, description
        FROM `{project}.{dataset}`.INFORMATION_SCHEMA.COLUMNS
        WHERE table_name = @table_name
        ORDER BY ordinal_position
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("table_name", "STRING", table_name)]
    )
    columns = list(client().query(cols_sql, job_config=job_config).result(timeout=30))
    column_lines = [f"  - {c.column_name} ({c.data_type})" + (f": {c.description}" if c.description else "") for c in columns]

    size_gb = (table_row.total_logical_bytes or table_row.total_bytes or 0) / (1024**3) if hasattr(table_row, "total_logical_bytes") else None
    title = f"{dataset}.{table_name}"
    description = (
        f"BigQuery public table `{full_ref}`. "
        f"{table_row.row_count or 'unknown'} rows"
        + (f", ~{size_gb:.1f} GB." if size_gb else ".")
        + " Columns:\n" + "\n".join(column_lines[:60])  # cap prompt/embedding size for very wide tables
    )

    metadata = {
        "title": title,
        "description": description[:4000],
        "trust": "machine-confirmed",
        "type": "Table",
        "source": {"kind": "bigquery", "project": project, "dataset": dataset, "table": table_name},
        "row_count": table_row.row_count,
        "size_gb": round(size_gb, 2) if size_gb else None,
        "large_table": bool(size_gb and size_gb > LARGE_TABLE_THRESHOLD_GB),
    }
    return description, metadata


def crawl_dataset(project: str, dataset: str) -> int:
    tables_sql = f"""
        SELECT table_name, row_count, total_logical_bytes
        FROM `{project}.{dataset}`.INFORMATION_SCHEMA.TABLE_STORAGE
    """
    try:
        tables = list(client().query(tables_sql).result(timeout=30))
    except Exception as exc:  # noqa: BLE001 — TABLE_STORAGE needs extra IAM in some projects; fall back to TABLES
        print(f"[crawler] TABLE_STORAGE unavailable for {dataset} ({exc}); falling back to TABLES (no size info)")
        fallback_sql = f"SELECT table_name, NULL AS row_count, NULL AS total_logical_bytes FROM `{project}.{dataset}`.INFORMATION_SCHEMA.TABLES"
        tables = list(client().query(fallback_sql).result(timeout=30))

    rows_to_upsert = []
    for t in tables:
        try:
            text, metadata = _describe_table(project, dataset, t)
        except Exception as exc:  # noqa: BLE001 — one bad table shouldn't fail the whole dataset
            print(f"[crawler] skipping {project}.{dataset}.{t.table_name}: {exc}")
            continue
        embedding = llm.embed(text)
        doc_id = f"bq.{project}.{dataset}.{t.table_name}"
        rows_to_upsert.append((doc_id, embedding, metadata))

    _upsert(rows_to_upsert)
    print(f"[crawler] {project}.{dataset}: catalogued {len(rows_to_upsert)}/{len(tables)} tables")
    return len(rows_to_upsert)


def _upsert(rows: list[tuple[str, list[float], dict]]) -> None:
    if not rows:
        return
    table_ref = f"{PROJECT_ID}.{ARD_CATALOG_DATASET}.embeddings"
    staging_rows = [
        {"doc_id": doc_id, "embedding": embedding, "metadata": json.dumps(metadata)}
        for doc_id, embedding, metadata in rows
    ]
    # Small batches (a few thousand rows at most across the whole curated
    # list) — a straight load-then-MERGE is simpler and plenty fast here.
    tmp_table = f"{PROJECT_ID}.{ARD_CATALOG_DATASET}._staging_embeddings"
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("doc_id", "STRING"),
            bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
            bigquery.SchemaField("metadata", "JSON"),
        ],
        write_disposition="WRITE_TRUNCATE",
    )
    client().load_table_from_json(staging_rows, tmp_table, job_config=job_config).result()

    client().query(f"""
        MERGE `{table_ref}` T
        USING `{tmp_table}` S
        ON T.doc_id = S.doc_id
        WHEN MATCHED THEN UPDATE SET embedding = S.embedding, metadata = S.metadata, updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (doc_id, embedding, metadata, updated_at)
        VALUES (S.doc_id, S.embedding, S.metadata, CURRENT_TIMESTAMP())
    """).result()
    client().delete_table(tmp_table, not_found_ok=True)


def prune(active_targets: list[tuple[str, str]]) -> None:
    """Removes ard_catalog.embeddings rows for datasets no longer in
    CRAWL_TARGETS. Run explicitly with --prune; not part of the normal
    scheduled crawl, so removing a dataset from targets.py doesn't silently
    drop discovery coverage until someone means it to."""
    keep_prefixes = [f"bq.{p}.{d}." for p, d in active_targets]
    conditions = " AND ".join([f"doc_id NOT LIKE '{prefix}%'" for prefix in keep_prefixes]) or "TRUE"
    sql = f"DELETE FROM `{PROJECT_ID}.{ARD_CATALOG_DATASET}.embeddings` WHERE doc_id LIKE 'bq.%' AND {conditions}"
    result = client().query(sql).result()
    print(f"[crawler] pruned rows outside current target list")


def main():
    parser = argparse.ArgumentParser(description="Atlas BigQuery public-dataset crawler")
    parser.add_argument("--prune", action="store_true", help="also delete embeddings rows for datasets no longer in targets.py")
    args = parser.parse_args()

    ensure_catalog_table()
    total = 0
    for project, dataset in CRAWL_TARGETS:
        total += crawl_dataset(project, dataset)
    if args.prune:
        prune(CRAWL_TARGETS)
    print(f"[crawler] done — {total} tables catalogued across {len(CRAWL_TARGETS)} datasets")


if __name__ == "__main__":
    main()
