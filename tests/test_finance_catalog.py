"""
Finance pack: catalog and pipeline unit tests that need no Google Cloud.

Run from the repo root:  python -m pytest tests -q

What these cover:
  - every OKF document parses, packs resolve, the public catalog is exactly
    what it was (the "did not interfere" check at the catalog level);
  - every finance Attested Computation declares parameters its SQL uses,
    parses as BigQuery SQL (sqlglot), and stays inside the pack's sources;
  - the metric→tag map in ac.sec_fact_from_bq matches xbrl_metrics.py;
  - composite step graphs resolve; quote verification drops fabrications;
  - the reconciliation and fact-check verdict arithmetic.
"""
import os
import re
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# Stub the heavy Google clients so the orchestrator modules import cleanly
# here — none of these tests execute a query or a model call.
import types  # noqa: E402

for name in ("google", "google.cloud", "google.cloud.bigquery", "google.cloud.firestore", "google.genai", "google.genai.types"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["google.cloud"].bigquery = sys.modules["google.cloud.bigquery"]
sys.modules["google.cloud"].firestore = sys.modules["google.cloud.firestore"]
sys.modules["google.genai"].types = sys.modules["google.genai.types"]
sys.modules["google.genai"].Client = object
sys.modules["google.cloud.firestore"].Client = object
sys.modules["google.cloud.firestore"].transactional = lambda f: f
sys.modules["google.cloud.firestore"].Increment = lambda v: v
sys.modules["google.cloud.firestore"].SERVER_TIMESTAMP = None


class _QP:
    def __init__(self, name, ptype, value):
        self.name, self.ptype, self.value = name, ptype, value


sys.modules["google.cloud.bigquery"].ScalarQueryParameter = _QP
sys.modules["google.cloud.bigquery"].ArrayQueryParameter = _QP
sys.modules["google.cloud.bigquery"].QueryJobConfig = lambda **kw: kw
sys.modules["google.cloud.bigquery"].Client = object

from backend.accessor import okf_loader, xbrl_metrics  # noqa: E402
from backend.crawler import targets  # noqa: E402
from backend.orchestrator import packs, pipeline  # noqa: E402
from backend.orchestrator.skills import filing_fact_check  # noqa: E402

CATALOG = os.path.join(ROOT, "okf-catalog")
PUBLIC_IDS_BEFORE_FINANCE = {
    "bq.bigquery-public-data.covid19_open_data.covid19_open_data",
    "ac.covid19_case_rate_by_county_year",
    "ac.sec_edgar_company_metric_by_year",
}


def finance_docs():
    return okf_loader.load_all(CATALOG, pack="finance")


def attested(docs):
    return [d for d in docs if d.type == "AttestedComputation"]


# --- packs and isolation -------------------------------------------------

def test_public_catalog_is_unchanged():
    ids = {d.id for d in okf_loader.load_all(CATALOG, pack="public")}
    assert ids == PUBLIC_IDS_BEFORE_FINANCE


def test_every_finance_doc_declares_finance_pack_and_governance():
    docs = finance_docs()
    assert len(docs) >= 12
    for d in docs:
        assert "finance" in d.packs, d.id
        assert d.trust in ("human-reviewed", "machine-confirmed"), d.id
        assert d.reviewer and d.reviewed_on and d.stale_after, f"{d.id} missing governance fields"
        assert d.lifecycle in ("draft", "active", "deprecated"), d.id


def test_no_finance_doc_leaks_into_public():
    public = {d.id for d in okf_loader.load_all(CATALOG, pack="public")}
    for d in finance_docs():
        if "public" not in d.packs:
            assert d.id not in public


def test_pack_flag_defaults_to_public_only(monkeypatch):
    monkeypatch.delenv("ATLAS_PACKS_ENABLED", raising=False)
    assert packs.enabled_packs() == {"public"}
    assert packs.is_enabled("public") and not packs.is_enabled("finance")
    monkeypatch.setenv("ATLAS_PACKS_ENABLED", "public,finance")
    assert packs.is_enabled("finance")


def test_crawler_targets_keep_the_public_fourteen():
    public = [(p, d) for p, d, pk in targets.targets_for("public")]
    assert len(public) == 14
    finance = {d for _, d, _ in targets.targets_for("finance")}
    assert {"cfpb_complaints", "fdic_banks", "sec_quarterly_financials", "bls"} <= finance


def test_public_planner_prompt_gets_no_glossary():
    assert packs.glossary("public") == ""
    assert packs.synthesis_rules("public") == ""
    assert packs.glossary("finance").endswith("\n\n")


# --- attested computations ------------------------------------------------

def _params_in_sql(sql: str) -> set[str]:
    return set(re.findall(r"@([a-zA-Z_][a-zA-Z0-9_]*)", sql))


@pytest.mark.parametrize("doc", attested(finance_docs()), ids=lambda d: d.id)
def test_attested_sql_parses_and_binds_every_parameter(doc):
    runtime = doc.computation["runtime"]
    declared = {p["name"] for p in runtime.get("parameters", [])}
    sql = runtime.get("sql")
    if sql is None:
        assert runtime["executor"] in ("composite", "sec_edgar", "sec_edgar_annual", "sec_ratio"), doc.id
        return
    used = _params_in_sql(sql)
    assert used <= declared, f"{doc.id} uses undeclared params {used - declared}"
    assert declared <= used, f"{doc.id} declares unused params {declared - used}"
    import sqlglot
    sqlglot.parse_one(sql, read="bigquery")  # raises on a syntax error


@pytest.mark.parametrize("doc", attested(finance_docs()), ids=lambda d: d.id)
def test_attested_sql_only_touches_declared_sources(doc):
    sql = doc.computation["runtime"].get("sql") or ""
    tables = set(re.findall(r"`([a-z0-9\-]+\.[a-z0-9_]+\.[a-z0-9_]+)`", sql))
    declared = {f"{s['project']}.{s['dataset']}.{s['table']}" for s in (doc.sources or [doc.source]) if s.get("kind") == "bigquery"}
    assert tables <= declared, f"{doc.id} queries undeclared tables {tables - declared}"


def test_optional_params_have_defaults_or_null_guards():
    for doc in attested(finance_docs()):
        runtime = doc.computation["runtime"]
        sql = runtime.get("sql") or ""
        for p in runtime.get("parameters", []):
            if p.get("required", True) or "default" in p or not sql:
                continue
            assert f"@{p['name']} IS NULL" in sql or f"@{p['name']} IS NOT NULL" in sql, \
                f"{doc.id}: optional {p['name']} without default must be NULL-guarded in SQL"


def test_sec_fact_from_bq_tag_map_matches_xbrl_metrics():
    doc = okf_loader.load_by_id("ac.sec_fact_from_bq", CATALOG)
    sql = doc.computation["runtime"]["sql"]
    in_sql = set()
    for m in re.finditer(r"STRUCT\('([a-z_]+)'(?: AS metric)?, '([A-Za-z]+)'(?: AS tag)?, '(duration|instant)'", sql):
        in_sql.add((m.group(1), m.group(2), m.group(3)))
    in_module = {(k, tag, v[3]) for k, v in xbrl_metrics.CURATED_METRICS.items() for tag in v[1]}
    assert in_sql == in_module, f"sql-only: {in_sql - in_module}; module-only: {in_module - in_sql}"


def test_composite_steps_resolve():
    doc = okf_loader.load_by_id("ac.sec_fact_reconcile", CATALOG)
    declared = {p["name"] for p in doc.computation["runtime"]["parameters"]}
    for step in doc.computation["runtime"]["steps"]:
        sub = okf_loader.load_by_id(step["computation"], CATALOG)
        assert sub is not None and sub.type == "AttestedComputation", step
        sub_params = {p["name"] for p in sub.computation["runtime"]["parameters"] if p.get("required", True)}
        assert sub_params <= set(step["params"].keys()), f"{step['name']} misses {sub_params - set(step['params'])}"
        assert set(step["params"].values()) <= declared


def test_narrative_template_is_bounded():
    doc = okf_loader.load_by_id("ac.cfpb_narrative_themes", CATALOG)
    rt = doc.computation["runtime"]
    assert rt["executor"] == "bigquery_sample_llm"
    assert rt["max_sample_n"] <= 500
    assert "LIMIT @sample_n" in rt["sql"]
    assert "consumer_consent_provided = 'Consent provided'" in rt["sql"]
    assert rt.get("prompt")


def test_edgar_template_shared_with_both_packs():
    doc = okf_loader.load_by_id("ac.sec_edgar_company_metric_by_year", CATALOG)
    assert doc.packs == ["public", "finance"]
    listed = set(re.findall(r"\b([a-z_]+)\b", doc.computation["runtime"]["parameters"][1]["description"]))
    assert set(xbrl_metrics.CURATED_METRICS) <= listed


# --- pipeline helpers -----------------------------------------------------

def test_quote_verification_drops_fabrications():
    sample = [
        {"complaint_id": "1", "consumer_complaint_narrative": "I disputed the item twice and nothing was corrected on my report."},
        {"complaint_id": "2", "consumer_complaint_narrative": "The payment was applied to the wrong account."},
    ]
    rows = [{"theme": "disputes", "quotes": [
        {"complaint_id": "1", "excerpt": "nothing was corrected on my report"},
        {"complaint_id": "1", "excerpt": "they refunded me immediately"},   # fabricated
        {"complaint_id": "9", "excerpt": "The payment was applied"},        # wrong id
        {"complaint_id": "2", "excerpt": "applied  to the WRONG account"},  # whitespace/case-insensitive match
    ]}]
    out, verified, dropped = pipeline._verify_quotes(rows, sample)
    assert verified == 2 and dropped == 2
    assert [q["complaint_id"] for q in out[0]["quotes"]] == ["1", "2"]


def test_reconcile_rows():
    rows = pipeline._reconcile(
        {"sec_edgar_api": [{"value": 100.0, "unit": "USD", "period_end": "2025-12-31", "accession": None, "form": "10-K", "filed": "2026-02-20"}],
         "sec_bulk_bq": [{"value": 100.3, "unit": "USD", "period_end": "2025-12-31", "accession": "0001-26-000001", "form": "10-K", "filed": "2026-02-20"}]},
        "value", 0.5)
    assert rows[-1]["agreement"] == "agree" and rows[-1]["delta_pct"] < 0.5
    rows = pipeline._reconcile({"sec_edgar_api": [{"value": 100.0}], "sec_bulk_bq": []}, "value", 0.5)
    assert rows[-1]["agreement"] == "single source" and rows[1]["status"] == "no annual fact on file"


def test_receipt_only_for_attested():
    doc = okf_loader.load_by_id("ac.cfpb_complaints_trend", CATALOG)
    wt = {"queries_executed": [{"source_id": doc.id, "bytes_billed": 10, "row_count": 3, "params": {"year": 2025}}], "token_usage": {}}
    r = pipeline.build_receipt(doc, wt, 10, {"total_cost_usd": 0.01})
    assert r["template_id"] == doc.id and r["reviewer"] == "Bel" and r["stale"] is False
    assert pipeline.build_receipt(None, wt, 10, None) is None


def test_fact_check_number_parsing_and_verdicts():
    assert filing_fact_check._parse_number("$118.3 billion") == 118.3e9
    assert filing_fact_check._parse_number("6%") == 6
    assert filing_fact_check._parse_number("grew") is None
    assert filing_fact_check._verdict(118.3e9, 118.5e9, False)[0] == "verified"
    assert filing_fact_check._verdict(118.3e9, 130e9, False)[0] == "differs"
    assert filing_fact_check._verdict(None, 1.0, False)[0] == "not_verifiable"
    assert filing_fact_check._verdict(1.1, 1.2, True)[0] == "verified"


def test_split_companies_and_template_cap():
    assert pipeline._split_companies("Apple, Microsoft and Nvidia") == ["Apple", "Microsoft", "Nvidia"]
    assert pipeline._split_companies("Procter & Gamble") == ["Procter & Gamble"]
    assert pipeline._split_companies("JPMorgan vs Bank of America") == ["JPMorgan", "Bank of America"]
    from backend.orchestrator import guardrails as g
    assert g.template_byte_cap(None) == g.TEMPLATE_BYTE_CAP
    assert g.template_byte_cap({"cap_bytes": 1}) == g.TEMPLATE_BYTE_CAP
    assert g.template_byte_cap({"cap_bytes": 10**12}) == g.TEMPLATE_BYTE_CAP_MAX
    assert g.template_byte_cap({"cap_bytes": 30 * 1024**3}) == 30 * 1024**3
