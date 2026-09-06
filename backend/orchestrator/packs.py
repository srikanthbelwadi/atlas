"""
Packs: named slices of the catalog that never see each other's sources.

`public` is the original demo (atlasdata.world/) and the default everywhere a
pack isn't named. `finance` is the finance section (/finance). A pack is only
servable when it's listed in ATLAS_PACKS_ENABLED — the deploy-time switch
that lets the backend ship with the finance code present but inert
(`ATLAS_PACKS_ENABLED=public`) until its catalog has been crawled and its
golden questions pass.

Everything pack-specific that isn't catalog content lives here: the
planner/synthesis glossary a pack appends to its prompts, and the display
metadata the /finance banner and /packs/{pack}/catalog endpoint show.
"""
import os

DEFAULT_PACK = "public"

PACKS: dict[str, dict] = {
    "public": {
        "title": "Atlas",
        "tagline": "Ask a question, get a cited answer from large-scale data.",
        "planner_glossary": "",
        "synthesis_rules": "",
    },
    "finance": {
        "title": "Finance pack",
        # The finance catalog is ~40 sources with many near-synonyms (three
        # FDIC/CFPB bank templates score alike on any "bank" question), so
        # discovery keeps two more candidates than the public pack's six.
        "top_k": 8,
        "tagline": (
            "Public datasets standing in for a bank's complaint system, entity master "
            "and fundamentals mart — every answer carries a receipt."
        ),
        # Appended to the planner prompt only for this pack. Short and
        # concrete: these are the definitional traps the finance golden
        # questions exercise, not a general finance tutorial.
        "planner_glossary": (
            "Finance-pack glossary (apply when binding parameters):\n"
            "- 'Fiscal year' means the filer's own fiscal year (fy in SEC data), which may end in "
            "any month; 'in 2025' for a filing question means fiscal_year=2025.\n"
            "- Complaint 'uphold' or 'relief' means company_response_to_consumer values that "
            "include 'relief'; 'timely' means timely_response = TRUE.\n"
            "- 'Return on assets' from FDIC and from XBRL filings are DIFFERENT definitions; "
            "templates name which one they use — pick the one the question names, and if it "
            "names neither, prefer the FDIC (regulatory) definition for banks.\n"
            "- Bank and company names must be resolved through templates that use the entity "
            "crosswalk; never free-text match a bank name in ad-hoc SQL when a template exists.\n"
            "- Narrative (free-text complaint) questions must use the narrative-themes template; "
            "never draft ad-hoc SQL that selects consumer_complaint_narrative.\n"
            "- Data vintage: the CFPB complaint mirror ends 2023-03-23 and the FDIC snapshot is "
            "late 2022. 'Latest year' means 2022. When a question names no dates for complaints, "
            "use date_from='2021-01-01' and date_to='2023-03-31'. A question about 2024 or later "
            "cannot be answered from these tables — choose no candidate rather than invent one. "
            "The SEC BigQuery mirror ends with fiscal 2019 (filings to 2020-12-31); the SEC EDGAR API "
            "templates are current, so prefer them for any filing question about fiscal 2020 or later.\n"
            "- A question that asks whether two sources AGREE, to VERIFY or RECONCILE a figure, or mentions "
            "both the EDGAR API and the SEC bulk data set, must use ac.sec_fact_reconcile.\n"
            "- Screening questions (which filers/companies/banks reported X, filtered by SIC code, loss, "
            "threshold) are NOT answered by a peer-ratio or single-company template: draft ad-hoc SQL "
            "over sec_quarterly_financials (join numbers to submission on submission_number) with a "
            "fiscal_year / period_end_date filter, or over fdic_banks.institutions for bank screens.\n"
            "- Several companies in one question (\"Apple, Microsoft and Nvidia\") are fine for the EDGAR "
            "templates: pass them all in the company parameter separated by commas.\n"
            "- INTERNAL DATA: 'our', 'the bank's own', 'internal', 'our loan book / applicants / ledger / "
            "transactions / portfolio' mean the PRIVATE finance_demo sources (titles say 'Internal risk mart' "
            "or '(private)'). Default rate by a segment → ac.hc_default_rate_by_segment; bureau inquiries, "
            "prior credits or overdue history vs default → ac.hc_bureau_history_vs_default; late payment, "
            "delinquency, arrears or roll rate by month → ac.hc_installment_delinquency_vintage; structuring, "
            "smurfing, just-under-threshold or velocity → ac.paysim_structuring_pattern. 'Default' there means "
            "default_flag = 1 (payment difficulties). The internal tables carry no calendar dates or geography. "
            "If a question is plainly about internal data and no private source is among the candidates, "
            "choose no candidate — never answer an internal question from a public stand-in.\n\n"
        ),
        "synthesis_rules": (
            "\n\nFinance-pack rule: the first sentence of the narrative must name the metric "
            "definition and the source it came from (e.g. 'Using FDIC-reported return on "
            "assets…' or 'From the 10-K as filed with the SEC…'; for an internal source, 'From the "
            "bank's internal loan_applications table (private)…'). Never restate a figure with "
            "more precision than the evidence carries. When the source is internal and undated, "
            "say the data carries no calendar dates rather than implying a period."
        ),
    },
    "places": {
        "title": "Places pack",
        "tagline": (
            "Reported statistics for any place — countries, states, counties, cities — from "
            "Google Data Commons' harmonised graph of 200+ public sources, with the source named on every row."
        ),
        # Two templates only, so discovery's default top_k is plenty.
        "planner_glossary": (
            "Places-pack glossary (apply when binding parameters):\n"
            "- Both candidates are Data Commons templates. A question about ONE or a FEW NAMED places "
            "(a value, a trend, 'X vs Y') → ac.dc_indicator_for_place. A question that RANKS or lists "
            "ALL places of a kind inside a parent ('which counties in California', 'by state', "
            "'countries in Africa', 'top 10 cities in Texas') → ac.dc_indicator_across_places.\n"
            "- `indicator` is the statistic in the question's own words, or the matching curated key from "
            "the parameter description. Never write a Data Commons variable id such as Count_Person.\n"
            "- `place` / `parent_place` are names exactly as written ('Santa Clara County, CA', 'India', "
            "'the world'); never a geoId or DCID. Several places to compare go in one comma-separated "
            "`place` value.\n"
            "- 'What is', 'how many', 'current' with no year → period='latest'. 'Trend', 'over time', "
            "'since', 'change', 'history' → period='all' or a year_from. A named year → year. Never invent "
            "a year.\n"
            "- 'Highest/most/largest' → order='desc' (default); 'lowest/least/smallest/worst unemployment' "
            "→ order='asc' only when the question asks for the smallest values. 'Top 10' → top_n=10.\n"
            "- Data Commons is deepest for the United States; country-level data is global.\n\n"
        ),
        "synthesis_rules": (
            "\n\nPlaces-pack rules: the first sentence must name the source the rows carry (the `source` "
            "field, e.g. 'According to the Census Bureau's ACS 5-year estimates as published on Data "
            "Commons…') and the observation date(s). If `date` differs across places, say the values are "
            "the latest each place has, not one common year. Never mix or restate figures with more "
            "precision than the rows carry. Use `bar` for a ranking or a comparison of places, `line` for "
            "a trend, `kpi_cards` for a single value; never choose `map` (the evidence has no coordinates)."
        ),
    },
}


def enabled_packs() -> set[str]:
    raw = os.environ.get("ATLAS_PACKS_ENABLED", DEFAULT_PACK)
    return {p.strip() for p in raw.split(",") if p.strip()} or {DEFAULT_PACK}


def is_enabled(pack: str) -> bool:
    return pack in PACKS and pack in enabled_packs()


def glossary(pack: str) -> str:
    return PACKS.get(pack, {}).get("planner_glossary", "")


def synthesis_rules(pack: str) -> str:
    return PACKS.get(pack, {}).get("synthesis_rules", "")


def top_k(pack: str, default: int) -> int:
    return int(PACKS.get(pack, {}).get("top_k") or default)


def info(pack: str) -> dict:
    meta = PACKS.get(pack, {})
    return {"id": pack, "title": meta.get("title", pack), "tagline": meta.get("tagline", "")}
