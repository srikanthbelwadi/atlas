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
    # Google Data Commons joined the public catalog on 2026-09-06 (two
    # reviewed templates, backend/accessor/datacommons_accessor.py).
    "ac.dc_indicator_for_place",
    "ac.dc_indicator_across_places",
    "ac.usa_top_baby_names",
    # Earth Engine in BigQuery (ST_REGIONSTATS), 2026-09-08.
    "ac.ee_era5_climate_by_county",
    "ac.ee_forest_cover_by_county",
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
    public = [(p, d) for p, d, pk, _a in targets.targets_for("public")]
    assert len(public) == 14
    assert all(not a for _, _, _, a in targets.targets_for("public")), "no public-pack dataset may be private"
    finance = {d for _, d, _, _ in targets.targets_for("finance")}
    assert {"cfpb_complaints", "fdic_banks", "sec_quarterly_financials", "bls", "finance_demo"} <= finance
    private = {d: a for _, d, _, a in targets.targets_for("finance") if a}
    assert private == {"finance_demo": {"visibility": "private", "entitlement": "finance.internal"}}
    assert "finance_demo_raw" not in finance, "raw loads are never catalogued"


def test_public_planner_prompt_gets_no_finance_glossary():
    # The public glossary exists only to route Data Commons questions; none
    # of the finance-pack rules may leak into it.
    for word in ("CFPB", "FDIC", "finance_demo", "fiscal", "bank"):
        assert word.lower() not in packs.glossary("public").lower(), word
        assert word.lower() not in packs.synthesis_rules("public").lower(), word
    assert packs.glossary("public").startswith("Data Commons glossary")
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


# --- use case D: private sources and entitlements -------------------------

from backend.orchestrator import access  # noqa: E402

PRIVATE_TEMPLATES = {"ac.hc_default_rate_by_segment", "ac.hc_bureau_history_vs_default",
                     "ac.hc_installment_delinquency_vintage", "ac.paysim_structuring_pattern"}


def private_docs():
    return [d for d in finance_docs() if d.visibility == "private"]


def test_private_docs_are_marked_and_confined_to_finance_demo():
    docs = private_docs()
    assert {d.id for d in docs if d.type == "AttestedComputation"} == PRIVATE_TEMPLATES
    assert len([d for d in docs if d.type == "Table"]) == 4
    for d in docs:
        assert d.access.get("entitlement") == "finance.internal", d.id
        assert d.governance()["visibility"] == "private" and d.governance()["entitlement"] == "finance.internal"
        for src in (d.sources or [d.source]):
            assert (src["project"], src["dataset"]) == ("atlas-ard-okf", "finance_demo"), f"{d.id} reads outside finance_demo"
    # and nothing public reads the private dataset
    for d in finance_docs() + okf_loader.load_all(CATALOG, pack="public"):
        if d.visibility != "private":
            for src in (d.sources or [d.source]):
                assert src.get("dataset") != "finance_demo", f"public doc {d.id} reads the private dataset"


def test_private_dataset_registry_and_sql_scan():
    assert access.private_datasets().get("atlas-ard-okf.finance_demo") == "finance.internal"
    access.check_sql_references("SELECT 1 FROM `bigquery-public-data.cfpb_complaints.complaint_database`", [])
    access.check_sql_references("SELECT 1 FROM `atlas-ard-okf.finance_demo.loan_applications`", ["finance.internal"])
    with pytest.raises(access.AccessDenied):
        access.check_sql_references("SELECT 1 FROM `atlas-ard-okf.finance_demo.loan_applications`", [])
    with pytest.raises(access.AccessDenied):
        access.check_sql_references("select * from atlas-ard-okf . finance_demo.payment_transactions", ["other"])


def test_split_candidates_withholds_private_without_entitlement():
    cands = [
        {"source_id": "ac.hc_default_rate_by_segment", "title": "private t", "score": 0.9, "visibility": "private", "entitlement": "finance.internal", "description": "secret"},
        {"source_id": "ac.cfpb_complaints_trend", "title": "public t", "score": 0.7},
    ]
    visible, withheld = access.split_candidates(cands, [])
    assert [c["source_id"] for c in visible] == ["ac.cfpb_complaints_trend"]
    assert withheld == [{"source_id": "ac.hc_default_rate_by_segment", "title": "private t", "entitlement": "finance.internal", "score": 0.9}]
    assert "description" not in withheld[0]
    visible, withheld = access.split_candidates(cands, ["finance.internal"])
    assert len(visible) == 2 and withheld == []


def test_fetch_stage_refuses_private_template_without_entitlement():
    doc = okf_loader.load_by_id("ac.hc_default_rate_by_segment", CATALOG)
    with pytest.raises(access.AccessDenied):
        access.assert_may_query(doc, [])
    access.assert_may_query(doc, ["finance.internal"])
    access.assert_may_query(okf_loader.load_by_id("ac.cfpb_complaints_trend", CATALOG), [])


def test_private_receipt_names_the_entitlement():
    doc = okf_loader.load_by_id("ac.paysim_structuring_pattern", CATALOG)
    receipt = pipeline.build_receipt(doc, {"queries_executed": [], "token_usage": {}}, 0, None)
    assert receipt["visibility"] == "private" and receipt["unlocked_by"] == "finance.internal"
    assert receipt["restricted_to"] is None or isinstance(receipt["restricted_to"], str)
    public = pipeline.build_receipt(okf_loader.load_by_id("ac.cfpb_complaints_trend", CATALOG), {"queries_executed": [], "token_usage": {}}, 0, None)
    assert public["visibility"] == "public" and public["unlocked_by"] is None


def test_withheld_answer_is_a_refusal():
    ans = pipeline._withheld_answer("our default rate", [{"source_id": "x", "title": "x", "entitlement": "finance.internal", "score": 0.9}])
    assert ans["refused"] == "not_entitled" and ans["citations"] == [] and "finance.internal" in ans["narrative"]


def test_private_synth_columns_cover_private_setup_sql():
    """The synthetic generator must emit every raw column private_setup.sql
    reads, or the load works on Kaggle files and fails on synthetic ones."""
    sql = open(os.path.join(ROOT, "infra", "finance", "private_setup.sql")).read()
    synth = open(os.path.join(ROOT, "scripts", "finance_private_synth.py")).read()
    raw_cols = set(re.findall(r"CAST\((-?)([A-Za-z_]+) AS", sql))
    names = {c for _, c in raw_cols} | set(re.findall(r"WHEN ([A-Z_]+) <", sql)) | {"DAYS_INSTALMENT"}
    missing = {c for c in names if f'"{c}"' not in synth and c not in ("step", "type", "amount")}
    assert not missing, f"synthetic generator lacks columns {missing}"


def test_annual_series_one_10k_value_per_fiscal_year(monkeypatch):
    """The multi-year EDGAR path: quarterlies dropped, restated prior years
    superseded by the year's own 10-K, an amendment beating the original,
    a January year-end labelled by the filer's own fiscal year, and
    `years` keeping only the most recent N. Motivated by a live answer
    that stopped at FY2023 because 593 raw facts hit the 500-row cap."""
    from backend.accessor import sec_edgar_accessor as sec

    def fact(val, start, end, fy, fp, form, filed):
        return {"val": val, "start": start, "end": end, "fy": fy, "fp": fp, "form": form, "filed": filed}

    facts = {
        "entityName": "NVIDIA CORP",
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            # FY2023 10-K (year ends 2023-01-29): current year + restated prior year + a Q4 duration
            fact(26_974, "2022-01-31", "2023-01-29", 2023, "FY", "10-K", "2023-02-24"),
            fact(26_914, "2021-02-01", "2022-01-30", 2023, "FY", "10-K", "2023-02-24"),
            fact(6_051, "2022-10-31", "2023-01-29", 2023, "FY", "10-K", "2023-02-24"),
            # FY2022 10-K
            fact(26_914, "2021-02-01", "2022-01-30", 2022, "FY", "10-K", "2022-03-18"),
            fact(16_675, "2020-01-27", "2021-01-31", 2022, "FY", "10-K", "2022-03-18"),
            # FY2024 10-K plus an amendment with a corrected figure
            fact(60_922, "2023-01-30", "2024-01-28", 2024, "FY", "10-K", "2024-02-21"),
            fact(60_922, "2023-01-30", "2024-01-28", 2024, "FY", "10-K/A", "2024-03-01"),
            # FY2025 10-K
            fact(130_497, "2024-01-29", "2025-01-26", 2025, "FY", "10-K", "2025-02-26"),
            # a quarterly 10-Q, never part of the series
            fact(44_062, "2025-01-27", "2025-04-27", 2026, "Q1", "10-Q", "2025-05-28"),
        ]}}}},
    }
    monkeypatch.setattr(sec, "resolve_cik", lambda c: "0001045810")
    monkeypatch.setattr(sec, "_http_get_json", lambda url: facts)

    out = sec.fetch_annual_series("Nvidia", "revenue")
    series = [(r["fiscal_year"], r["value"], r["form"]) for r in out["rows"]]
    assert series == [(2021, 16_675, "10-K"), (2022, 26_914, "10-K"), (2023, 26_974, "10-K"),
                      (2024, 60_922, "10-K/A"), (2025, 130_497, "10-K")], series
    assert out["rows"][-1]["period_end"] == "2025-01-26", "January year-end keeps the filer's FY label"

    last3 = sec.fetch_annual_series("Nvidia", "revenue", years=3)
    assert [r["fiscal_year"] for r in last3["rows"]] == [2023, 2024, 2025]
