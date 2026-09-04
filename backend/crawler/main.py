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
from backend.crawler.targets import DATASET_ALIASES, LARGE_TABLE_THRESHOLD_GB, targets_for  # noqa: E402

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


def _describe_table(project: str, dataset: str, table_row, pack: str = "public", access: dict | None = None) -> tuple[str, dict]:
    """Returns (embedding_text, metadata_dict) for one INFORMATION_SCHEMA.TABLES row."""
    table_name = table_row.table_name
    full_ref = f"{project}.{dataset}.{table_name}"

    # No `description` column here on purpose: INFORMATION_SCHEMA.COLUMNS has no
    # such field (that only exists on COLUMN_FIELD_PATHS, a different view, and
    # only cleanly for top-level fields — nested STRUCT columns get one row per
    # leaf field there). Selecting it threw "Unrecognized name: description" on
    # every single table in the crawler's first real run, which the per-table
    # try/except in crawl_dataset() swallowed silently — the job exited 0 having
    # catalogued nothing. Keep this query to columns INFORMATION_SCHEMA.COLUMNS
    # actually has so a schema surprise can't zero out the whole crawl again.
    cols_sql = f"""
        SELECT column_name, data_type
        FROM `{project}.{dataset}`.INFORMATION_SCHEMA.COLUMNS
        WHERE table_name = @table_name
        ORDER BY ordinal_position
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("table_name", "STRING", table_name)]
    )
    columns = list(client().query(cols_sql, job_config=job_config).result(timeout=30))
    column_lines = [f"  - {c.column_name} ({c.data_type})" for c in columns]

    # NOTE: only total_logical_bytes is ever selected (by both the TABLE_STORAGE
    # query and its TABLES fallback below) -- there is no total_bytes column to
    # fall back to. An earlier version referenced table_row.total_bytes here,
    # which raised "no row field 'total_bytes'" on every fallback-path row
    # (total_logical_bytes is NULL there) once the `description`-column bug
    # above stopped masking it.
    size_gb = (table_row.total_logical_bytes or 0) / (1024**3) if getattr(table_row, "total_logical_bytes", None) else None
    title = f"{dataset}.{table_name}"
    description = (
        f"BigQuery table `{full_ref}`. "
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
        "pack": pack,
    }
    if access and access.get("visibility") == "private":
        # A private table is catalogued like any other, but discovery only
        # offers it to users holding the entitlement, and the embedded text
        # says so — "PRIVATE" in the title is what makes "our own data"
        # questions land here rather than on a public stand-in.
        metadata["visibility"] = "private"
        metadata["entitlement"] = access.get("entitlement")
        metadata["title"] = f"{title} (private)"
        description = f"PRIVATE table (internal data; entitlement {access.get('entitlement')}). " + description
        metadata["description"] = description[:4000]
    else:
        metadata["visibility"] = "public"
    return description, metadata


def _list_tables(project: str, dataset: str):
    tables_sql = f"""
        SELECT table_name, row_count, total_logical_bytes
        FROM `{project}.{dataset}`.INFORMATION_SCHEMA.TABLE_STORAGE
    """
    try:
        return list(client().query(tables_sql).result(timeout=30))
    except Exception as exc:  # noqa: BLE001 — TABLE_STORAGE needs extra IAM in some projects; fall back to TABLES
        print(f"[crawler] TABLE_STORAGE unavailable for {dataset} ({exc}); falling back to TABLES (no size info)")
        fallback_sql = f"SELECT table_name, NULL AS row_count, NULL AS total_logical_bytes FROM `{project}.{dataset}`.INFORMATION_SCHEMA.TABLES"
        return list(client().query(fallback_sql).result(timeout=30))


def crawl_dataset(project: str, dataset: str, pack: str = "public", access: dict | None = None) -> int:
    """Catalogues one dataset into one pack. A dataset that can't be read
    under its listed name is retried under each DATASET_ALIASES entry (the
    `fdic_banks` / `fdic` naming question), and the name that resolved is
    printed so the crawl log answers it for good."""
    names_to_try = (dataset,) + DATASET_ALIASES.get(dataset, ())
    tables, resolved = [], dataset
    last_exc = None
    for name in names_to_try:
        try:
            tables = _list_tables(project, name)
            resolved = name
            break
        except Exception as exc:  # noqa: BLE001 — try the next alias
            last_exc = exc
            print(f"[crawler] {project}.{name}: INFORMATION_SCHEMA unreadable ({exc})")
    if not tables:
        print(f"[crawler] {project}.{dataset}: no tables found under any name {names_to_try} — last error: {last_exc!r}")
        return 0
    if resolved != dataset:
        print(f"[crawler] {project}.{dataset}: resolved under alias `{resolved}`")

    rows_to_upsert = []
    for t in tables:
        try:
            text, metadata = _describe_table(project, resolved, t, pack, access)
        except Exception as exc:  # noqa: BLE001 — one bad table shouldn't fail the whole dataset
            print(f"[crawler] skipping {project}.{resolved}.{t.table_name}: {exc}")
            continue
        embedding = llm.embed(text)
        # Public-pack ids keep their original, un-suffixed form so nothing
        # about the existing catalog rows changes; every other pack gets a
        # suffix so a dataset shared across packs is indexed once per pack.
        doc_id = f"bq.{project}.{resolved}.{t.table_name}" + ("" if pack == "public" else f"#{pack}")
        rows_to_upsert.append((doc_id, embedding, metadata))

    _upsert(rows_to_upsert)
    print(f"[crawler] {project}.{resolved} [{pack}]: catalogued {len(rows_to_upsert)}/{len(tables)} tables")
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
    # Staging `metadata` is a plain STRING that the MERGE parses with
    # PARSE_JSON. Loading a json.dumps() string straight into a JSON column
    # stored it as a JSON *string* scalar rather than an object, which made
    # `JSON_VALUE(metadata, '$.pack')` NULL on every row — found when the first
    # finance crawl's rows were invisible to the pack filter. discovery.py
    # and main.py read both encodings, so rows written the old way still
    # work; new/updated rows are written as real objects from here on.
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("doc_id", "STRING"),
            bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
            bigquery.SchemaField("metadata", "STRING"),
        ],
        write_disposition="WRITE_TRUNCATE",
    )
    client().load_table_from_json(staging_rows, tmp_table, job_config=job_config).result()

    client().query(f"""
        MERGE `{table_ref}` T
        USING (SELECT doc_id, embedding, PARSE_JSON(metadata) AS metadata FROM `{tmp_table}`) S
        ON T.doc_id = S.doc_id
        WHEN MATCHED THEN UPDATE SET embedding = S.embedding, metadata = S.metadata, updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (doc_id, embedding, metadata, updated_at)
        VALUES (S.doc_id, S.embedding, S.metadata, CURRENT_TIMESTAMP())
    """).result()
    client().delete_table(tmp_table, not_found_ok=True)


def prune(active_targets: list[tuple[str, str, str, dict]]) -> None:
    """Removes ard_catalog.embeddings rows for datasets no longer in
    CRAWL_TARGETS (per pack). Run explicitly with --prune; not part of the
    normal scheduled crawl, so removing a dataset from targets.py doesn't
    silently drop discovery coverage until someone means it to."""
    keep = []
    for p, d, pack, _access in active_targets:
        names = (d,) + DATASET_ALIASES.get(d, ())
        for n in names:
            suffix = "" if pack == "public" else f"#{pack}"
            keep.append(f"(doc_id LIKE 'bq.{p}.{n}.%' AND doc_id LIKE '%{suffix}')" if suffix else f"(doc_id LIKE 'bq.{p}.{n}.%' AND doc_id NOT LIKE '%#%')")
    conditions = " OR ".join(keep) or "FALSE"
    sql = f"DELETE FROM `{PROJECT_ID}.{ARD_CATALOG_DATASET}.embeddings` WHERE doc_id LIKE 'bq.%' AND NOT ({conditions})"
    client().query(sql).result()
    print("[crawler] pruned rows outside current target list")


def main():
    parser = argparse.ArgumentParser(description="Atlas BigQuery dataset crawler (works against any project/dataset the service account can read)")
    parser.add_argument("--prune", action="store_true", help="also delete embeddings rows for datasets no longer in targets.py")
    parser.add_argument("--pack", default=os.environ.get("ATLAS_CRAWL_PACK") or None,
                        help="crawl only this pack's datasets (default: every pack)")
    args = parser.parse_args()

    ensure_catalog_table()
    targets = targets_for(args.pack)
    total = 0
    for project, dataset, pack, access in targets:
        total += crawl_dataset(project, dataset, pack, access)
    if args.prune:
        prune(targets_for(None))
    print(f"[crawler] done — {total} tables catalogued across {len(targets)} dataset/pack targets" + (f" (pack={args.pack})" if args.pack else ""))


if __name__ == "__main__":
    main()
