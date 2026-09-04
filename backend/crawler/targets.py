"""
Curated crawl targets.

`bigquery-public-data` has thousands of tables across hundreds of datasets —
crawling all of it isn't a sensible use of embedding calls or of anyone's
$100/month query budget, and most of it (raw genomics, multi-terabyte GitHub
source dumps, etc.) is exactly the kind of thing the byte cap exists to keep
users away from. Atlas crawls a curated, growable allowlist instead: broadly
useful, general-audience datasets, biased toward ones that answer the kind of
question a natural-language front door is actually good for (place + time +
metric questions).

Packs: every target belongs to one or more packs (see
backend/accessor/okf_loader.py). The original fourteen datasets are the
`public` pack — the demo at atlasdata.world/ — and the finance section at
/finance discovers only the `finance` pack. A dataset listed under two packs
(BLS below) is catalogued once per pack, under a pack-suffixed doc_id, so
each pack's discovery index is self-contained.

Add a dataset here (and redeploy the crawler, or just wait for the weekly
scheduled run) to bring it into ARD discovery. Removing one here does not
delete its existing `ard_catalog.embeddings` rows — run `main.py --prune` to
also drop rows for datasets no longer in this list.
"""

# (project, dataset, packs[, access]). Project is almost always
# "bigquery-public-data"; kept explicit so a non-public source (a licensed
# Analytics Hub dataset, a customer's own project) is added the same way.
# The optional fourth element marks a PRIVATE dataset: every table it
# catalogues carries `visibility: private` and the entitlement a user must
# hold before discovery will show it (backend/orchestrator/access.py). The
# crawler itself reads it through the same service account either way —
# BigQuery IAM decides what the crawler can see, Atlas entitlements decide
# which users may be offered it.
PRIVATE_FINANCE = {"visibility": "private", "entitlement": "finance.internal"}

CRAWL_TARGETS: list[tuple] = [
    # --- public pack: the original demo catalog, unchanged ---
    ("bigquery-public-data", "covid19_open_data", ("public",)),
    ("bigquery-public-data", "census_bureau_acs", ("public",)),
    ("bigquery-public-data", "world_bank_health_population", ("public",)),
    ("bigquery-public-data", "world_bank_wdi", ("public",)),
    ("bigquery-public-data", "epa_historical_air_quality", ("public",)),
    ("bigquery-public-data", "noaa_gsod", ("public",)),
    ("bigquery-public-data", "google_trends", ("public",)),
    ("bigquery-public-data", "bls", ("public", "finance")),
    ("bigquery-public-data", "chicago_crime", ("public",)),
    ("bigquery-public-data", "san_francisco", ("public",)),
    ("bigquery-public-data", "new_york", ("public",)),
    ("bigquery-public-data", "openaq", ("public",)),
    ("bigquery-public-data", "usa_names", ("public",)),
    ("bigquery-public-data", "fec", ("public",)),
    # --- finance pack: public datasets standing in for bank-internal systems
    #     (see atlas-finance-demo-plan.md §5) ---
    ("bigquery-public-data", "cfpb_complaints", ("finance",)),          # complaint case-management system
    ("bigquery-public-data", "fdic_banks", ("finance",)),               # entity master + peer ratios
    ("bigquery-public-data", "sec_quarterly_financials", ("finance",)), # fundamentals warehouse (XBRL)
    ("bigquery-public-data", "sec_failure_to_deliver", ("finance",)),   # settlement-exceptions ledger
    # --- finance pack, use case D: the bank's OWN data — a private dataset in
    #     our project (infra/finance/private_setup.sql). Same crawler, same
    #     executor; only IAM and the entitlement differ. finance_demo_raw is
    #     deliberately not listed: raw loads are never catalogued.
    ("atlas-ard-okf", "finance_demo", ("finance",), PRIVATE_FINANCE),       # internal risk mart: credit book + payments ledger
]

# Google's public-datasets-pipelines repo defines the FDIC dataset as `fdic`
# while the console has long shown it as `fdic_banks`. The crawler tries the
# listed name first and falls back to the alias if INFORMATION_SCHEMA can't
# be read, recording which one resolved in the crawl log (phase 0.3 of the
# finance plan is exactly this check).
DATASET_ALIASES: dict[str, tuple[str, ...]] = {
    "fdic_banks": ("fdic",),
}

# Tables larger than this are still cataloged (so the model knows they exist
# and can warn the user / route to an Attested Computation instead of raw
# SQL) but flagged `large_table: true` in metadata so the planner leans
# towards templates over ad-hoc SQL for them.
LARGE_TABLE_THRESHOLD_GB = 50


def targets_for(pack: str | None) -> list[tuple[str, str, str, dict]]:
    """Flattens CRAWL_TARGETS into (project, dataset, pack, access) tuples, one
    per pack membership, optionally restricted to a single pack. `access` is
    {} for public datasets."""
    out = []
    for entry in CRAWL_TARGETS:
        project, dataset, packs = entry[0], entry[1], entry[2]
        access = entry[3] if len(entry) > 3 else {}
        for p in packs:
            if pack is None or p == pack:
                out.append((project, dataset, p, access))
    return out
