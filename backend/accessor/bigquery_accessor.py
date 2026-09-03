"""
Guarded BigQuery executor.

Every query — whether it's a curated Attested Computation template filled
with parameters, or free-form SQL Gemini drafted for an ad-hoc question —
goes through the same two-step path:

  1. dry run (query_and_wait with dry_run=True, zero cost) to get
     `total_bytes_processed`, checked against the caller-supplied byte cap
  2. the real run, with `maximum_bytes_billed` set to that same cap as a
     hard server-side backstop (BigQuery aborts the job itself if the
     planner was wrong) and a wall-clock timeout matching the plan's
     ~10-minute (600s) query budget

Never runs a query without a preceding dry run. Never trusts a byte estimate
without also setting `maximum_bytes_billed` on the real job — the dry run and
the actual scan can differ (partitioned/clustered tables, cached results),
and the hard cap is what actually protects the budget.
"""
import concurrent.futures
import os

from google.cloud import bigquery

from . import okf_loader
from ..orchestrator.guardrails import GuardrailError, check_byte_estimate

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "atlas-ard-okf")

_client = None


def client() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client(project=PROJECT_ID)
    return _client


def dry_run(sql: str, params: list[bigquery.ScalarQueryParameter] | None = None) -> int:
    """Returns estimated total_bytes_processed without scanning any data."""
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, query_parameters=params or [])
    job = client().query(sql, job_config=job_config)
    return job.total_bytes_processed or 0


def run(
    sql: str,
    params: list[bigquery.ScalarQueryParameter] | None = None,
    byte_cap: int = 0,
    timeout_seconds: int = 570,
) -> list[dict]:
    """Dry-runs `sql`, checks against `byte_cap`, then executes for real with
    `maximum_bytes_billed` set to the same cap and a hard wall-clock timeout.
    Raises GuardrailError (byte cap) or TimeoutError (wall clock)."""
    estimated = dry_run(sql, params)
    check_byte_estimate(estimated, byte_cap)

    job_config = bigquery.QueryJobConfig(
        query_parameters=params or [],
        maximum_bytes_billed=byte_cap,
        use_query_cache=True,
    )

    def _execute():
        job = client().query(sql, job_config=job_config)
        return [dict(row) for row in job.result(timeout=timeout_seconds)], job.total_bytes_billed or estimated

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_execute)
        try:
            rows, bytes_billed = future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError(f"Query exceeded the {timeout_seconds}s budget.") from exc

    return rows, bytes_billed


def run_attested_computation(doc_id: str, param_values: dict, byte_cap: int, timeout_seconds: int = 570):
    """Loads an OKF AttestedComputation doc by id, binds `param_values` into
    its declared `computation.runtime.parameters`, and runs it through the
    same guarded path as ad-hoc SQL. This is the trusted, human-reviewed
    path — SQL text comes from the git-versioned catalog, never from the
    model, only the parameter *values* are model- or user-supplied.

    Returns (rows, bytes_billed, doc, sql, bound_params) — the last two exist
    so pipeline.py can put the actual query text and the values that were
    bound into it in the per-request walkthrough ("queries executed"),
    rather than only a row count."""
    doc = okf_loader.load_by_id(doc_id)
    if doc is None or doc.type != "AttestedComputation" or not doc.computation:
        raise ValueError(f"Unknown or malformed Attested Computation: {doc_id}")

    sql = doc.computation["runtime"]["sql"]
    declared_params = doc.computation["runtime"].get("parameters", [])
    query_params = []
    bound_params = {}
    for p in declared_params:
        name = p["name"]
        ptype = p.get("type", "STRING")
        if name in param_values and param_values[name] not in (None, ""):
            value = _coerce(param_values[name], ptype)
        elif "default" in p:
            value = _coerce(p["default"], ptype)
        elif not p.get("required", True):
            # Optional with no default binds NULL so the template can say
            # `(@product IS NULL OR product = @product)` — the planner never
            # has to invent a value to satisfy the binding.
            value = None
        else:
            raise ValueError(f"Missing required parameter '{name}' for {doc_id}")
        query_params.append(bigquery.ScalarQueryParameter(name, ptype, value))
        bound_params[name] = value

    rows, bytes_billed = run(sql, query_params, byte_cap=byte_cap, timeout_seconds=timeout_seconds)
    return rows, bytes_billed, doc, sql, bound_params


def _coerce(value, ptype: str):
    """The planner returns parameter values as JSON — an INT64 parameter may
    arrive as "2025" or 2025.0. Coerce to the declared BigQuery type so the
    query parameter binds cleanly; leave anything unrecognised alone."""
    try:
        if ptype in ("INT64", "INTEGER"):
            return int(float(value))
        if ptype in ("FLOAT64", "NUMERIC", "FLOAT"):
            return float(value)
        if ptype == "BOOL":
            return str(value).lower() in ("true", "1", "yes")
        if ptype == "DATE":
            return str(value)[:10]
    except (TypeError, ValueError):
        return value
    return value
