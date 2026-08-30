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
GEMINI_FIXED_COST_ESTIMATE_USD = float(os.environ.get("ATLAS_GEMINI_FIXED_COST_ESTIMATE_USD", 0.02))

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


def record_usage(user_id: str, bytes_billed: int, gemini_calls: int = 2) -> float:
    """Called once per completed query. Returns the incremental cost added."""
    bq_cost = (bytes_billed / (1024**4)) * BQ_PRICE_PER_TIB_USD
    cost = bq_cost + gemini_calls * GEMINI_FIXED_COST_ESTIMATE_USD
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
    return cost
