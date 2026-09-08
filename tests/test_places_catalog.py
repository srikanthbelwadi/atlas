"""
Google Data Commons (public catalog): catalog and accessor unit tests, no
network and no Google Cloud.

Run from the repo root:  python -m pytest tests -q

What these cover:
  - the two Data Commons templates parse, declare governance, and sit in
    the public catalog only (never the finance pack);
  - the accessor's transport seam (`_http`) is the only thing mocked — the cache above it runs for real;
    everything above it — place resolution, indicator resolution with the
    existence check, single-facet selection, year filtering, latest-only,
    ranking, entity/row caps, the missing-key error — runs for real against
    a fake of the v2 API's documented response shapes;
  - pipeline._fetch_one dispatches `kind: datacommons` to the accessor and
    returns the rows/params/doc shape the rest of the pipeline expects.
"""
import json
import os
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

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

from backend.accessor import datacommons_accessor as dc, okf_loader  # noqa: E402
from backend.orchestrator import packs, pipeline  # noqa: E402

CATALOG = os.path.join(ROOT, "okf-catalog")
PLACES_IDS = {"ac.dc_indicator_for_place", "ac.dc_indicator_across_places"}


# --- catalog ---------------------------------------------------------------

def dc_docs():
    return [d for d in okf_loader.load_all(CATALOG, pack="public") if d.id in PLACES_IDS]


def test_places_docs_parse_with_governance():
    docs = dc_docs()
    assert {d.id for d in docs} == PLACES_IDS
    for d in docs:
        assert d.type == "AttestedComputation"
        assert d.trust == "human-reviewed"
        assert d.source.get("kind") == "datacommons"
        assert d.executor in dc.EXECUTORS, d.id
        assert d.reviewer and d.reviewed_on and d.stale_after and d.citation_template
        names = {p["name"] for p in d.computation["runtime"]["parameters"]}
        assert "indicator" in names
        required = {p["name"] for p in d.computation["runtime"]["parameters"] if p.get("required", True)}
        assert required <= {"indicator", "place", "parent_place", "child_type"}, d.id


def test_places_docs_are_public_only():
    finance = {d.id for d in okf_loader.load_all(CATALOG, pack="finance")}
    assert not (PLACES_IDS & finance)
    assert "places" not in packs.PACKS, "Data Commons lives in the public catalog, not a pack of its own"


def test_public_glossary_routes_between_the_two_templates():
    g = packs.glossary("public")
    assert "ac.dc_indicator_for_place" in g and "ac.dc_indicator_across_places" in g
    assert "Never write a Data Commons variable id" in g
    assert "EVEN WHEN a BigQuery table has a higher `score`" in g, "the override clause is what beats the crawled tables' rank"
    assert "names one place: it is for_place" in g
    assert "Health prevalence rates" in g
    assert g.endswith("\n\n")
    assert "never choose `map`" in packs.synthesis_rules("public")


def test_curated_indicator_keys_are_advertised_in_both_templates():
    for d in dc_docs():
        desc = next(p["description"] for p in d.computation["runtime"]["parameters"] if p["name"] == "indicator")
        for key in dc.CURATED_INDICATORS:
            assert key in desc, f"{d.id} does not advertise curated key {key}"


# --- a fake of the v2 API ----------------------------------------------------

NAMES = {
    "geoId/06": "California", "geoId/48": "Texas", "country/USA": "United States", "country/IND": "India",
    "geoId/06085": "Santa Clara County", "geoId/06001": "Alameda County", "geoId/06037": "Los Angeles County",
    "Count_Person": "Population", "Median_Income_Household": "Median household income",
    "UnemploymentRate_Person": "Unemployment rate", "Earth": "World",
}
RESOLVE = {
    "California": "geoId/06", "Texas": "geoId/48", "India": "country/IND",
    "Santa Clara County, CA": "geoId/06085",
}
CHILDREN = {"geoId/06": [("geoId/06085", "Santa Clara County"), ("geoId/06001", "Alameda County"), ("geoId/06037", "Los Angeles County")]}
# variable -> entity -> orderedFacets
OBS = {
    "Count_Person": {
        "geoId/06": [{"facetId": "acs5", "observations": [{"date": "2019", "value": 39_000_000}, {"date": "2022", "value": 39_200_000}]},
                     {"facetId": "wiki", "observations": [{"date": "2023", "value": 39_500_000}]}],
        "geoId/48": [{"facetId": "acs5", "observations": [{"date": "2019", "value": 28_900_000}, {"date": "2022", "value": 30_000_000}]}],
        "country/IND": [{"facetId": "wb", "observations": [{"date": "2021", "value": 1_407_000_000}, {"date": "2022", "value": 1_417_000_000}]}],
        "geoId/06085": [{"facetId": "acs5", "observations": [{"date": "2022", "value": 1_900_000}]}],
        "geoId/06001": [{"facetId": "acs5", "observations": [{"date": "2022", "value": 1_650_000}]}],
        "geoId/06037": [{"facetId": "acs1", "observations": [{"date": "2023", "value": 9_700_000}]},
                        {"facetId": "acs5", "observations": [{"date": "2022", "value": 9_800_000}]}],
    },
    "UnemploymentRate_Person": {
        "geoId/06085": [{"facetId": "bls", "observations": [{"date": "2024-01", "value": 3.4}, {"date": "2024-02", "value": 3.6}]}],
        "geoId/06001": [{"facetId": "bls", "observations": [{"date": "2024-02", "value": 4.1}]}],
        "geoId/06037": [{"facetId": "bls", "observations": [{"date": "2024-02", "value": 5.2}]}],
    },
}
FACETS = {
    "acs5": {"importName": "CensusACS5YearSurvey", "provenanceUrl": "https://census.gov/acs", "measurementMethod": "CensusACS5yrSurvey", "observationPeriod": "P5Y"},
    "acs1": {"importName": "CensusACS1YearSurvey", "provenanceUrl": "https://census.gov/acs", "measurementMethod": "CensusACS1yrSurvey", "observationPeriod": "P1Y"},
    "wiki": {"importName": "WikidataPopulation", "provenanceUrl": "https://wikidata.org"},
    "wb": {"importName": "WorldBank", "provenanceUrl": "https://data.worldbank.org", "observationPeriod": "P1Y"},
    "bls": {"importName": "BLS_LAUS", "provenanceUrl": "https://bls.gov/lau", "observationPeriod": "P1M", "unit": "Percent"},
}


class FakeAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, params=None, body=None):
        self.calls.append((method, path, params, body))
        if path == "resolve" and (params or {}).get("resolver") == "indicator":
            phrase = params["nodes"].lower()
            cands = []
            if "unemploy" in phrase:
                cands = [{"dcid": "dc/topic/Employment"}, {"dcid": "UnemploymentRate_Person", "score": 0.9}]
            elif "people" in phrase or "population" in phrase:
                cands = [{"dcid": "Count_Person", "score": 0.95}, {"dcid": "Count_Person_Male", "score": 0.5}]
            elif "income" in phrase:
                cands = [{"dcid": "Median_Income_Household", "score": 0.8}]
            return {"entities": [{"node": params["nodes"], "candidates": cands}]}
        if path == "resolve":
            name = params["nodes"]
            dcid = RESOLVE.get(name)
            return {"entities": [{"node": name, "candidates": ([{"dcid": dcid, "dominantType": "State"}] if dcid else [])}]}
        if path == "node" and body["property"] == "->name":
            return {"data": {d: {"arcs": {"name": {"nodes": [{"value": NAMES[d]}]}}} for d in body["nodes"] if d in NAMES}}
        if path == "node" and body["property"].startswith("->geoJsonCoordinates"):
            # a square per known place; India deliberately has no geometry
            data = {}
            for i, d in enumerate(body["nodes"]):
                if d in NAMES and d != "country/IND" and not d.startswith(("Count_", "Median_", "Unemployment")):
                    geom = {"type": "Polygon", "coordinates": [[[i, 0], [i + 1, 0], [i + 1, 1], [i, 1], [i, 0]]]}
                    data[d] = {"arcs": {body["property"][2:]: {"nodes": [{"value": json.dumps(geom)}]}}}
            return {"data": data}
        if path == "node" and body["property"].startswith("<-containedInPlace+"):
            parent = body["nodes"][0]
            kids = CHILDREN.get(parent, [])
            return {"data": {parent: {"arcs": {"containedInPlace+": {"nodes": [{"dcid": d, "name": n} for d, n in kids]}}}}}
        if path == "observation":
            variables = body["variable"]["dcids"]
            entities = body["entity"]["dcids"]
            want_values = "value" in body["select"]
            by_var = {}
            for v in variables:
                by_entity = {}
                for e in entities:
                    facets = OBS.get(v, {}).get(e)
                    if not facets:
                        continue
                    if want_values:
                        by_entity[e] = {"orderedFacets": [dict(f) for f in facets]}
                    else:
                        by_entity[e] = {}
                if by_entity:
                    by_var[v] = {"byEntity": by_entity}
            return {"byVariable": by_var, **({"facets": FACETS} if want_values else {})}
        raise AssertionError(f"unexpected call {method} {path} {params} {body}")


@pytest.fixture
def api(monkeypatch):
    fake = FakeAPI()
    monkeypatch.setattr(dc, "_http", fake)
    monkeypatch.setenv("DC_API_KEY", "test-key")
    dc.clear_cache()
    return fake


# --- accessor ------------------------------------------------------------------

def test_missing_api_key_is_a_configuration_error(monkeypatch):
    monkeypatch.delenv("DC_API_KEY", raising=False)
    dc.clear_cache()
    with pytest.raises(dc.DataCommonsError) as exc:
        dc._http("GET", "resolve", params={"nodes": "x"})
    assert exc.value.code == "not_configured"


def test_split_places_keeps_qualified_county_together():
    assert dc.split_places("California, Texas and New York") == ["California", "Texas", "New York"]
    assert dc.split_places("Santa Clara County, CA") == ["Santa Clara County, CA"]
    assert dc.split_places("Cook County, Illinois vs Harris County, Texas") == ["Cook County, Illinois", "Harris County, Texas"]
    assert dc.split_places("Japan vs. the United States") == ["Japan", "the United States"]


def test_resolve_place_uses_known_places_then_resolver(api):
    assert dc.resolve_place("the world")["dcid"] == "Earth"
    assert dc.resolve_place("United States")["dcid"] == "country/USA"
    r = dc.resolve_place("California", "state")
    assert r["dcid"] == "geoId/06" and r["name"] == "California" and r["type"] == "State"
    typed = [c for c in api.calls if c[1] == "resolve" and "{typeOf:State}" in (c[2] or {}).get("property", "")]
    assert typed, "state hint should type the resolver property"
    with pytest.raises(dc.DataCommonsError) as exc:
        dc.resolve_place("Nowhere Land")
    assert exc.value.code == "unknown_place"


def test_indicator_curated_first_then_resolver_and_existence_check(api):
    r = dc.resolve_indicator("population", ["geoId/06"])
    assert r["dcid"] == "Count_Person" and r["via"] == "curated:population" and r["name"] == "Population"
    # A phrase with no curated key goes to the resolver; topics are dropped;
    # a candidate with no data for the place is skipped.
    r = dc.resolve_indicator("jobless rate unemployment", ["geoId/06085"])
    assert r["dcid"] == "UnemploymentRate_Person" and r["via"] == "resolver"
    assert all(not c["dcid"].startswith("dc/topic/") for c in r["considered"])
    with pytest.raises(dc.DataCommonsError) as exc:
        dc.resolve_indicator("median household income", ["country/IND"])
    assert exc.value.code == "no_data_for_place"


def test_single_facet_covers_all_places_and_rows_carry_provenance(api):
    places = [{"dcid": "geoId/06", "name": "California"}, {"dcid": "geoId/48", "name": "Texas"}]
    res = dc.fetch_observations("Count_Person", places)
    assert res["facet"]["facet_id"] == "acs5" and res["facet"]["covers_places"] == 2
    assert {r["source"] for r in res["rows"]} == {"CensusACS5YearSurvey"}
    assert all(r["provenance_url"] and r["observation_period"] == "P5Y" for r in res["rows"])
    # the wikidata facet (California only) was available but not used
    assert [f["facet_id"] for f in res["facets_available"]] == ["acs5", "wiki"]
    assert len(res["rows"]) == 4


def test_year_filters_and_latest_only(api):
    places = [{"dcid": "geoId/06", "name": "California"}]
    assert [r["date"] for r in dc.fetch_observations("Count_Person", places, year=2019)["rows"]] == ["2019"]
    assert [r["date"] for r in dc.fetch_observations("Count_Person", places, year_from=2020)["rows"]] == ["2022"]
    assert [r["date"] for r in dc.fetch_observations("Count_Person", places, latest_only=True)["rows"]] == ["2022"]
    assert dc.fetch_observations("Count_Person", places, year=1900)["rows"] == []


def test_run_place_binds_receipt_params(api):
    out = dc.run_place({"indicator": "population", "place": "California, Texas", "period": "latest"})
    assert len(out["rows"]) == 2 and {r["place"] for r in out["rows"]} == {"California", "Texas"}
    p = out["params"]
    assert p["variable_dcid"] == "Count_Person" and p["place_dcids"] == "geoId/06, geoId/48"
    assert p["period"] == "latest" and p["source"] == "CensusACS5YearSurvey" and p["facet_covers"] == "2 of 2 places"
    assert out["rows"][0]["variable"] == "Population"


def test_run_place_empty_rows_when_no_observation_in_window(api):
    out = dc.run_place({"indicator": "population", "place": "India", "year": 1990})
    assert out["rows"] == [] and out["params"]["variable_dcid"] == "Count_Person"


def test_run_children_ranks_with_one_facet(api):
    out = dc.run_children({"indicator": "population", "parent_place": "California", "child_type": "counties", "top_n": 2})
    rows = out["rows"]
    assert [r["place"] for r in rows] == ["Los Angeles County", "Santa Clara County"]
    assert [r["rank"] for r in rows] == [1, 2]
    assert [r["place"] for r in out["map_rows"]] == ["Los Angeles County", "Santa Clara County", "Alameda County"], "the map gets every place with data"
    assert out["map_rows"][2]["rank"] == 3
    # LA has an acs1 row too, but acs5 covers all three counties, so acs5 is used everywhere
    assert {r["source"] for r in rows} == {"CensusACS5YearSurvey"} and rows[0]["value"] == 9_800_000
    p = out["params"]
    assert p["child_type"] == "County" and p["places_in_parent"] == 3 and p["places_with_data"] == 3 and p["top_n"] == 2
    asc = dc.run_children({"indicator": "unemployment rate", "parent_place": "California", "child_type": "county", "order": "asc"})
    assert [r["place"] for r in asc["rows"]] == ["Santa Clara County", "Alameda County", "Los Angeles County"]
    assert asc["rows"][0]["date"] == "2024-02", "latest per place, not the first observation"


def test_entity_cap_is_enforced(api, monkeypatch):
    monkeypatch.setattr(dc, "MAX_ENTITIES", 2)
    with pytest.raises(dc.DataCommonsError) as exc:
        dc.children_of("geoId/06", "County")
    assert exc.value.code == "too_many_entities"


def test_pipeline_dispatches_datacommons_kind(api):
    candidate = {"source_id": "ac.dc_indicator_for_place", "kind": "datacommons", "type": "AttestedComputation",
                 "title": "t", "trust": "human-reviewed"}
    fetched = pipeline._fetch_one(candidate, {"params": {"indicator": "population", "place": "India", "period": "latest"}}, "q")
    assert fetched["bytes_billed"] == 0 and fetched["sql"] is None
    assert fetched["rows"][0]["place"] == "India" and fetched["rows"][0]["value"] == 1_417_000_000
    assert fetched["doc"].id == "ac.dc_indicator_for_place"
    receipt = pipeline.build_receipt(fetched["doc"], {"queries_executed": [{"source_id": "ac.dc_indicator_for_place", "params": fetched["params"]}]}, 0, None)
    assert receipt["executor"] == "datacommons_place" and receipt["queries"][0]["params"]["variable_dcid"] == "Count_Person"


def test_transport_cache_dedupes_identical_calls(api):
    dc.resolve_place("California")
    n = len(api.calls)
    dc.resolve_place("California")
    assert len(api.calls) == n


def test_children_follow_next_token_pages(monkeypatch):
    """The node API pages `containedInPlace+` expansions (500 at a time for
    every US county); the accessor must follow nextToken, not stop at page 1."""
    monkeypatch.setenv("DC_API_KEY", "test-key")
    dc.clear_cache()
    pages = {
        None: {"data": {"country/USA": {"arcs": {"containedInPlace+": {"nodes": [{"dcid": "geoId/01001", "name": "Autauga County"}]}}}}, "nextToken": "p2"},
        "p2": {"data": {"country/USA": {"arcs": {"containedInPlace+": {"nodes": [{"dcid": "geoId/01003", "name": "Baldwin County"}]}}}}},
    }
    monkeypatch.setattr(dc, "_http", lambda m, p, params=None, body=None: pages[(body or {}).get("nextToken")])
    kids = dc.children_of("country/USA", "County")
    assert [k["dcid"] for k in kids] == ["geoId/01001", "geoId/01003"]


def test_source_label_falls_back_to_provenance_host():
    assert dc._source_label({"importName": "CensusACS5YearSurvey"}) == "CensusACS5YearSurvey"
    assert dc._source_label({"provenanceUrl": "https://www2.census.gov/programs-surveys/popest"}) == "www2.census.gov"
    assert dc._source_label({"measurementMethod": "WorldBankEstimate"}) == "WorldBankEstimate"


def test_discovery_caps_crawled_candidates_per_dataset():
    from backend.orchestrator import discovery
    acs = [{"source_id": f"bq.bigquery-public-data.census_bureau_acs.state_{y}_5yr", "score": 0.9 - i * 0.01}
           for i, y in enumerate(range(2010, 2020))]
    other = [{"source_id": "bq.bigquery-public-data.bls.unemployment_cps", "score": 0.7},
             {"source_id": "bq.bigquery-public-data.bls.cpi_u#finance", "score": 0.69}]
    kept = discovery._cap_per_dataset(acs + other, 2)
    ids = [c["source_id"] for c in kept]
    assert ids[:2] == [acs[0]["source_id"], acs[1]["source_id"]]
    assert sum(i.startswith("bq.bigquery-public-data.census_bureau_acs") for i in ids) == 2
    assert sum(i.startswith("bq.bigquery-public-data.bls") for i in ids) == 2, "the #pack suffix must not split a dataset"
    assert discovery._dataset_key("ac.dc_indicator_for_place") == "ac.dc_indicator_for_place"


def test_bound_evidence_keeps_every_entity_and_its_latest_rows():
    """The general fix for the EDGAR cut-off: over the cap, each company
    keeps an equal share of rows, most recent first, re-ordered
    chronologically; under the cap rows are untouched; the coverage record
    says what happened."""
    rows = []
    for company in ("Apple", "Microsoft", "Nvidia"):
        for fy in range(2000, 2026):
            for q in range(1, 9):   # 8 facts per year per company -> 624 rows
                rows.append({"company": company, "fiscal_year": fy, "value": fy * 10 + q})
    sent, cov = pipeline.bound_evidence(rows, 60)
    assert cov == {"rows_total": 624, "rows_sent": 60, "truncated": True, "stratified_by": "company", "ordered_by": "fiscal_year"}
    by = {}
    for r in sent:
        by.setdefault(r["company"], []).append(r["fiscal_year"])
    assert set(by) == {"Apple", "Microsoft", "Nvidia"}, "no entity may vanish"
    assert all(len(v) == 20 for v in by.values())
    assert all(max(v) == 2025 for v in by.values()), "the latest year survives for every entity"
    assert all(v == sorted(v) for v in by.values()), "chronological within each entity"

    small = rows[:10]
    assert pipeline.bound_evidence(small, 60) == (small, {"rows_total": 10, "rows_sent": 10, "truncated": False, "stratified_by": None, "ordered_by": None})

    # No entity column: keep the most recent rows.
    series = [{"date": f"{y:04d}-01-01", "value": y} for y in range(1900, 2026)]
    sent, cov = pipeline.bound_evidence(series, 5)
    assert [r["date"][:4] for r in sent] == ["2021", "2022", "2023", "2024", "2025"] and cov["stratified_by"] is None and cov["ordered_by"] == "date"


def test_bound_evidence_hands_small_groups_surplus_to_large_ones():
    rows = [{"place": "A", "year": y} for y in range(2020, 2023)] + [{"place": "B", "year": y} for y in range(1990, 2026)]
    sent, cov = pipeline.bound_evidence(rows, 20)
    counts = {}
    for r in sent:
        counts[r["place"]] = counts.get(r["place"], 0) + 1
    assert counts == {"A": 3, "B": 17} and cov["rows_sent"] == 20


# --- map answers: backend/geo/boundaries.py + pipeline.finalize_map --------

from backend.geo import boundaries  # noqa: E402


def test_place_key_from_dcid_fips_and_iso():
    pk = boundaries.place_key
    assert pk({"place_dcid": "geoId/06085"}) == "geoId/06085"
    assert pk({"geo_id": "06085"}) == "geoId/06085"
    assert pk({"geo_id": "6"}) == "geoId/06"
    assert pk({"state_fips_code": "06", "county_fips_code": "085"}) == "geoId/06085"
    assert pk({"county_fips_code": "06085"}) == "geoId/06085"
    assert pk({"zip_code": "95014"}) == "zip/95014"
    assert pk({"country_code": "usa"}) == "country/USA"
    assert pk({"place": "Springfield"}) is None, "a name is never a key"
    assert boundaries.geo_capable([{"place_dcid": f"geoId/0{i}"} for i in range(5)])
    assert not boundaries.geo_capable([{"place_dcid": "geoId/06"}] * 10)


def test_attach_joins_rows_to_boundaries_and_reports(api):
    boundaries.clear_cache()
    rows = [{"place": "Santa Clara County", "place_dcid": "geoId/06085", "date": "2024-02", "value": 3.6, "source": "BLS"},
            {"place": "Alameda County", "place_dcid": "geoId/06001", "date": "2024-02", "value": 4.1, "source": "BLS"},
            {"place": "Los Angeles County", "place_dcid": "geoId/06037", "date": "2024-02", "value": 5.2, "source": "BLS"},
            {"place": "Los Angeles County", "place_dcid": "geoId/06037", "date": "2024-01", "value": 9.9, "source": "BLS"}]
    geo = boundaries.attach(rows, "value", "place")
    assert geo["ok"] and geo["matched"] == 3 and geo["detail"] == "DP3"
    la = next(f for f in geo["features"]["features"] if f["id"] == "geoId/06037")
    assert la["properties"]["value"] == 5.2, "the latest observation per place, not the first row"
    assert la["properties"]["label"] == "Los Angeles County" and la["properties"]["source"] == "BLS"
    assert geo["bounds"] and len(geo["bounds"]) == 4
    calls = [c for c in api.calls if c[1] == "node" and "geoJsonCoordinates" in (c[3] or {}).get("property", "")]
    assert calls and calls[0][3]["property"] == "->geoJsonCoordinatesDP3"

    # A place Data Commons has no geometry for is reported, not drawn.
    rows.append({"place": "India", "place_dcid": "country/IND", "date": "2024", "value": 7.0})
    geo = boundaries.attach(rows, "value", "place")
    assert geo["ok"] and geo["matched"] == 3 and geo["unmatched"] == ["country/IND"]


def test_finalize_map_attaches_or_downgrades(api):
    boundaries.clear_cache()
    rows = [{"place": n, "place_dcid": d, "value": v} for n, d, v in
            (("Santa Clara County", "geoId/06085", 3.6), ("Alameda County", "geoId/06001", 4.1), ("Los Angeles County", "geoId/06037", 5.2))]
    pres = {"visualization": {"kind": "choropleth", "data": json.dumps({"value_field": "value", "label_field": "place", "title": "Unemployment rate, %"})}}
    geo, note = pipeline.finalize_map(pres, rows)
    assert geo and geo["ok"] and pres["visualization"]["kind"] == "choropleth" and "3 places" in note
    # map_rows (every place) paints the map; rows (the top N) stay the narrative's evidence
    geo, note = pipeline.finalize_map(pres, rows[:1], rows)
    assert geo and geo["matched"] == 3

    # No boundaries at all -> same rows as a ranked bar, kind rewritten, reason recorded.
    india = [{"place": f"Place {i}", "place_dcid": "country/IND", "value": i} for i in range(6)]
    pres = {"visualization": {"kind": "choropleth", "data": json.dumps({"value_field": "value", "label_field": "place"})}}
    geo, note = pipeline.finalize_map(pres, india)
    assert geo is None and pres["visualization"]["kind"] == "bar" and "downgraded" in note
    bar = json.loads(pres["visualization"]["data"])
    assert bar["labels"] and bar["values"] == sorted(bar["values"], reverse=True)


# --- Earth Engine in BigQuery (phase B) ---------------------------------------

EE_IDS = {"ac.ee_era5_climate_by_county", "ac.ee_forest_cover_by_county"}


def test_earth_engine_templates_parse_bind_and_declare_method():
    import re
    import sqlglot
    docs = [d for d in okf_loader.load_all(CATALOG, pack="public") if d.id in EE_IDS]
    assert {d.id for d in docs} == EE_IDS
    for d in docs:
        assert d.executor == "bigquery", "phase B rides the guarded BigQuery executor"
        sql = d.computation["runtime"]["sql"]
        sqlglot.parse_one(sql, read="bigquery")
        used = set(re.findall(r"@([a-zA-Z_][a-zA-Z0-9_]*)", sql))
        declared = {p["name"] for p in d.computation["runtime"]["parameters"]}
        assert used == declared, d.id
        assert "ST_REGIONSTATS" in sql and "ee://" in sql
        assert "geo_id" in sql, "rows must carry the county FIPS so the answer maps"
        assert "estimate" in d.citation_template.lower(), "computed measurements say so in the citation"
        assert any(src.get("kind") == "earth_engine" for src in d.sources)
        assert d.computation["runtime"].get("max_geometries", 0) >= 254, "Texas has 254 counties"
    assert "EARTH ENGINE templates" in packs.glossary("public")
    assert "satellite- or" in packs.synthesis_rules("public")
