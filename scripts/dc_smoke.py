#!/usr/bin/env python3
"""
Live smoke + timing check for the Data Commons accessor — the "Phase 0
spike" from atlas-earth-engine-datacommons-assessment.md §6/§7.

    DC_API_KEY=... python scripts/dc_smoke.py            # from the repo root

Runs each places-pack template the way the pipeline would (real resolvers,
real observation calls, cache cleared between cases), prints the resolved
place/variable/facet and wall-clock per case, and exits non-zero if any
case raises. No Google Cloud needed — only the key. Run it once from a
laptop and once from Cloud Run (`gcloud run jobs` or a shell in the
container) so the latency numbers in the assessment are measured, not
guessed.
"""
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from backend.accessor import datacommons_accessor as dc  # noqa: E402

CASES = [
    ("place: point", "datacommons_place", {"indicator": "population", "place": "India", "period": "latest"}),
    ("place: trend", "datacommons_place", {"indicator": "median household income", "place": "Santa Clara County, CA", "year_from": 2014}),
    ("place: compare", "datacommons_place", {"indicator": "life expectancy", "place": "Japan, United States", "period": "latest"}),
    ("place: resolver phrase", "datacommons_place", {"indicator": "share of adults with obesity", "place": "Texas", "period": "latest"}),
    ("children: CA counties", "datacommons_children", {"indicator": "unemployment rate", "parent_place": "California", "child_type": "county", "top_n": 5}),
    ("children: US states", "datacommons_children", {"indicator": "median_household_income", "parent_place": "United States", "child_type": "state", "top_n": 10}),
    ("children: all US counties", "datacommons_children", {"indicator": "population", "parent_place": "United States", "child_type": "county", "top_n": 10}),
    ("children: Africa countries asc", "datacommons_children", {"indicator": "life expectancy", "parent_place": "Africa", "child_type": "country", "order": "asc", "top_n": 10}),
]


def main() -> int:
    if not os.environ.get(dc.API_KEY_ENV):
        print(f"set {dc.API_KEY_ENV} first (https://apikeys.datacommons.org)")
        return 2
    failures = 0
    print(f"{'case':32} {'secs':>6}  rows  resolved")
    dc.clear_cache()
    for label, executor, params in CASES:
        t0 = time.monotonic()
        try:
            out = dc.run(executor, params)
            secs = time.monotonic() - t0
            p = out["params"]
            where = p.get("place_dcids") or f"{p.get('parent_dcid')} → {p.get('places_in_parent')} {p.get('child_type')}"
            print(f"{label:32} {secs:6.2f}  {len(out['rows']):4}  {p.get('variable_dcid')} @ {where} | {p.get('source')}")
            if out["rows"]:
                r = out["rows"][0]
                print(f"{'':32} {'':6}        e.g. {r.get('place')} {r.get('date')}: {r.get('value')} {r.get('unit') or ''}")
            if out.get("facets_available"):
                print(f"{'':32} {'':6}        facet: {out['facets_available'][0].get('facet_raw')}")
        except dc.DataCommonsError as exc:
            failures += 1
            print(f"{label:32} {time.monotonic() - t0:6.2f}  FAIL  [{exc.code}] {exc.message}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{label:32} {time.monotonic() - t0:6.2f}  FAIL  {exc!r}")
    # A second run of the first case, with nothing cleared, shows the in-process cache at work.
    t0 = time.monotonic()
    dc.run("datacommons_place", CASES[0][2])
    print(f"{'cached repeat of first case':32} {time.monotonic() - t0:6.2f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
