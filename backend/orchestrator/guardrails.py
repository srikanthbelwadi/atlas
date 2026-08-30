"""
Budget and safety guardrails.

Two independent limits, both enforced server-side (never trust the client):

  1. Per-query byte cap — a BigQuery *dry run* estimates bytes scanned before
     any real query runs; if the estimate exceeds the cap, the query is
     rejected before it can cost anything. Two tiers, per the plan's §00/§10
     cost math: templated Attested Computations (trusted, parameterized SQL
     written by us) get a higher cap than free-form SQL Gemini drafts for
     ad-hoc questions.

  2. Per-user monthly cost ceiling ($100/logged-in user, plan §08) — tracked
     in Firestore as a running estimated-cost counter per user per calendar
     month, incremented after every query using BigQuery's on-demand price
     ($6.25/TiB) plus a small fixed estimate for the two Gemini calls. A user
     over the ceiling is blocked before the discover stage even starts.

Both checks raise GuardrailError, which the pipeline turns into a
`guardrail.blocked` trace event and an early exit — never a silent downgrade.
"""
import datetime as dt
import os

from google.cloud import firestore

TEMPLATE_BYTE_CAP = int(os.environ.get("ATLAS_TEMPLATE_BYTE_CAP", 20 * 1024**3))   # 20 GB
ADHOC_BYTE_CAP = int(os.environ.get("ATLAS_ADHOC_BYTE_CAP", 10 * 1024**3))          # 10 GB
QUERY_TIMEOUT_SECONDS = int(os.environ.get("ATLAS_QUERY_TIMEOUT_SECONDS", 45))      # leaves headroom inside the 60s budget

MONTHLY_COST_CEILING_USD = float(os.environ.get("ATLAS_MONTHLY_COST_CEILING_USD", 100.0))
BQ_PRICE_PER_TIB_USD = 6.25

# Gemini per-million-token prices, input/output separately since the two
# tiers price very differently. THESE ARE PLACEHOLDERS, not verified current
# pricing — set them via env vars to whatever Vertex AI actually charges for
# ATLAS_PLAN_MODEL / ATLAS_SYNTHESIS_MODEL today:
# https://cloud.google.com/vertex-ai/generative-ai/pricing
# Getting this env var wrong doesn't break anything — it only skews the
# estimated-cost number shown in the walkthrough and used for the monthly
# budget ceiling, so it's worth checking against current pricing before
# relying on the budget guardrail for real spend control.
PLAN_MODEL_INPUT_PRICE_PER_MTOK = float(os.environ.get("ATLAS_PLAN_INPUT_PRICE_PER_MTOK", 0.30))
PLAN_MODEL_OUTPUT_PRICE_PER_MTOK = float(os.environ.get("ATLAS_PLAN_OUTPUT_PRICE_PER_MTOK", 2.50))
SYNTH_MODEL_INPUT_PRICE_PER_MTOK = float(os.environ.get("ATLAS_SYNTH_INPUT_PRICE_PER_MTOK", 1.25))
SYNTH_MODEL_OUTPUT_PRICE_PER_MTOK = float(os.environ.get("ATLAS_SYNTH_OUTPUT_PRICE_PER_MTOK", 10.00))

_db = None


def db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client()
    return _db


class GuardrailError(Exception):
    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def byte_cap_for(needs_sql: bool, is_template: bool) -> int:
    if not needs_sql:
        return 0
    return TEMPLATE_BYTE_CAP if is_template else ADHOC_BYTE_CAP


def check_byte_estimate(estimated_bytes: int, cap: int) -> None:
    if estimated_bytes > cap:
        raise GuardrailError(
            "byte_cap_exceeded",
            f"This query would scan {estimated_bytes / 1024**3:.1f} GB, "
            f"above the {cap / 1024**3:.0f} GB cap for this kind of query.",
            {"estimated_bytes": estimated_bytes, "cap_bytes": cap},
        )


def _usage_doc_id(user_id: str) -> str:
    month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    return f"{user_id}_{month}"


def check_monthly_budget(user_id: str) -> float:
    """Returns the user's current month-to-date estimated spend, or raises
    GuardrailError if they're already at or over the ceiling."""
    snap = db().collection("usage").document(_usage_doc_id(user_id)).get()
    spent = float(snap.get("estimated_cost_usd") or 0.0) if snap.exists else 0.0
    if spent >= MONTHLY_COST_CEILING_USD:
        raise GuardrailError(
            "monthly_budget_exceeded",
            f"You've reached this month's ${MONTHLY_COST_CEILING_USD:.0f} query budget. "
            "It resets on the 1st.",
            {"spent_usd": spent, "ceiling_usd": MONTHLY_COST_CEILING_USD},
        )
    return spent


def record_usage(user_id: str, bytes_billed: int, plan_usage: dict, synth_usage: dict) -> dict:
    """Called once per completed query. Computes real cost from BigQuery
    bytes billed plus actual Gemini token counts (see llm.py's `_usage()`) —
    not a flat per-call guess like the original `gemini_calls * fixed_cost`
    version. Returns a cost breakdown dict, threaded into the query's
    walkthrough so token cost is visible per-request, not just as a running
    total."""
    bq_cost = (bytes_billed / (1024**4)) * BQ_PRICE_PER_TIB_USD
    plan_cost = (
        (plan_usage.get("prompt_tokens", 0) / 1_000_000) * PLAN_MODEL_INPUT_PRICE_PER_MTOK
        + (plan_usage.get("output_tokens", 0) / 1_000_000) * PLAN_MODEL_OUTPUT_PRICE_PER_MTOK
    )
    synth_cost = (
        (synth_usage.get("prompt_tokens", 0) / 1_000_000) * SYNTH_MODEL_INPUT_PRICE_PER_MTOK
        + (synth_usage.get("output_tokens", 0) / 1_000_000) * SYNTH_MODEL_OUTPUT_PRICE_PER_MTOK
    )
    cost = bq_cost + plan_cost + synth_cost
    doc_ref = db().collection("usage").document(_usage_doc_id(user_id))

    @firestore.transactional
    def _bump(transaction):
        snap = doc_ref.get(transaction=transaction)
        prior = float(snap.get("estimated_cost_usd") or 0.0) if snap.exists else 0.0
        transaction.set(
            doc_ref,
            {
                "user_id": user_id,
                "estimated_cost_usd": prior + cost,
                "query_count": firestore.Increment(1),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )

    _bump(db().transaction())
    return {
        "bq_cost_usd": round(bq_cost, 6),
        "plan_cost_usd": round(plan_cost, 6),
        "synth_cost_usd": round(synth_cost, 6),
        "total_cost_usd": round(cost, 6),
        "plan_tokens": plan_usage,
        "synth_tokens": synth_usage,
    }
