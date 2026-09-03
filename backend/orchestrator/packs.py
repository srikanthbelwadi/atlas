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
            "templates: pass them all in the company parameter separated by commas.\n\n"
        ),
        "synthesis_rules": (
            "\n\nFinance-pack rule: the first sentence of the narrative must name the metric "
            "definition and the source it came from (e.g. 'Using FDIC-reported return on "
            "assets…' or 'From the 10-K as filed with the SEC…'). Never restate a figure with "
            "more precision than the evidence carries."
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


def info(pack: str) -> dict:
    meta = PACKS.get(pack, {})
    return {"id": pack, "title": meta.get("title", pack), "tagline": meta.get("tagline", "")}
