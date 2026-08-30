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

Add a dataset here (and redeploy the crawler, or just wait for the weekly
scheduled run) to bring it into ARD discovery. Removing one here does not
delete its existing `ard_catalog.embeddings` rows — run `main.py --prune` to
also drop rows for datasets no longer in this list.
"""

# (project, dataset) pairs. Project is almost always "bigquery-public-data";
# kept explicit so a non-public source (e.g. a licensed Analytics Hub
# dataset) can be added the same way later.
CRAWL_TARGETS: list[tuple[str, str]] = [
    ("bigquery-public-data", "covid19_open_data"),
    ("bigquery-public-data", "census_bureau_acs"),
    ("bigquery-public-data", "world_bank_health_population"),
    ("bigquery-public-data", "world_bank_wdi"),
    ("bigquery-public-data", "epa_historical_air_quality"),
    ("bigquery-public-data", "noaa_gsod"),
    ("bigquery-public-data", "google_trends"),
    ("bigquery-public-data", "bls"),
    ("bigquery-public-data", "chicago_crime"),
    ("bigquery-public-data", "san_francisco"),
    ("bigquery-public-data", "new_york"),
    ("bigquery-public-data", "openaq"),
    ("bigquery-public-data", "usa_names"),
    ("bigquery-public-data", "fec"),
]

# Tables larger than this are still cataloged (so the model knows they exist
# and can warn the user / route to an Attested Computation instead of raw
# SQL) but flagged `large_table: true` in metadata so the planner leans
# towards templates over ad-hoc SQL for them.
LARGE_TABLE_THRESHOLD_GB = 50
