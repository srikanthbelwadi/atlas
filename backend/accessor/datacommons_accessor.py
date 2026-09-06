"""
Guarded Data Commons fetcher — the REST v2 API (`/v2/resolve`, `/v2/node`,
`/v2/observation`) behind the `datacommons_place` and `datacommons_children`
executors.

The two templates live in the public catalog (`okf-catalog/attested-
computations/dc_indicator_*.md`), so Data Commons questions are asked in
the same ask bar as everything else; the public planner glossary in
packs.py routes between them and the crawled BigQuery tables.

Why an API accessor and not the crawler: Data Commons' BigQuery mirror
(Analytics Hub) is deprecated — the docs page carries a turn-down notice as
of 2026-08-26 — so the graph is reached the way SEC EDGAR is: one accessor
module, reviewed OKF templates, parameter extraction by the planner, and
nothing invented at request time. See atlas-earth-engine-datacommons-
assessment.md (Route A) for the design and IMPLEMENTATION.md §6 for the
executor table.

What the guardrails are here: Data Commons is free (no per-request bill),
with no published rate limit and no SLA, so — exactly as for EDGAR — they
are a network-safety and payload-shape story, not a cost one:
  - a required API key (DC_API_KEY, from Secret Manager on Cloud Run; a
    missing key is a configuration error, reported as such, never a silent
    fall-through to the public trial key);
  - a wall-clock timeout per call and a response-size cap;
  - an entity cap for "every county in the US"-style expansions
    (MAX_ENTITIES), so a `containedInPlace+` expression can never fan out
    into tens of thousands of places in one request;
  - a row cap on what is returned to synthesis;
  - an in-process TTL cache keyed on the exact call, because the same
    place/variable pair is asked many ways and the data only changes when a
    source publishes.

Three trust rules, same as the SEC accessor:
  1. A place name is never turned into a DCID by the model. `resolve_place`
     asks Data Commons' own resolver and records what it resolved to (dcid
     and canonical name) in the bound params, so the receipt shows it.
  2. A statistical variable is never a model-invented DCID either. The
     planner passes the question's own wording (`indicator`); the accessor
     tries the small human-reviewed CURATED_INDICATORS map first, then Data
     Commons' indicator resolver, and keeps the first candidate that
     actually has an observation for the place asked about. The resolved
     variable, its display name and the candidates considered are recorded.
  3. One facet (source) per answer. Data Commons routinely holds the same
     variable from several sources (Census ACS 1-year vs 5-year, BLS vs
     Census unemployment); mixing them across places or years would make
     a comparison that no single source made. The accessor picks the facet
     that covers the most of the requested entities (ties → Data Commons'
     own preferred ordering) and every row carries that facet's
     importName / provenanceUrl / measurementMethod / observationPeriod so
     synthesis can say where the number came from.

"No data" vs. "fetch failed": a real place with no observation for a
variable returns empty rows (pipeline.py's `if not rows:` handling —
backtrack or an honest "couldn't find"). DataCommonsError is reserved for
genuine failures: missing key, unresolvable place, no variable candidate at
all, network/HTTP errors, a response over the size cap.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = os.environ.get("ATLAS_DC_API_BASE", "https://api.datacommons.org/v2")
API_KEY_ENV = "DC_API_KEY"
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("ATLAS_DC_TIMEOUT_SECONDS", 20))
MAX_RESPONSE_BYTES = int(os.environ.get("ATLAS_DC_MAX_RESPONSE_BYTES", 32 * 1024 * 1024))  # 32 MB
MAX_ENTITIES = int(os.environ.get("ATLAS_DC_MAX_ENTITIES", 3500))   # > the ~3,150 US counties, < any state's cities
MAX_ROWS = int(os.environ.get("ATLAS_DC_MAX_ROWS", 5000))
CACHE_TTL_SECONDS = int(os.environ.get("ATLAS_DC_CACHE_TTL_SECONDS", 6 * 3600))
USER_AGENT = os.environ.get("ATLAS_DC_USER_AGENT", "Atlas (atlas-ard-okf; contact: admin@atlasdata.world)")

# Human-reviewed plain-language key -> Data Commons StatisticalVariable DCID.
# The planner is shown these keys in the template's parameter description
# and may pass one of them, or the question's own wording; either way the
# accessor verifies the variable has an observation for the place before
# using it, and falls back to Data Commons' own indicator resolver when the
# key is unknown or has no data there. Extend from observed misses, as
# KNOWN_ALIASES in sec_edgar_accessor.py is extended — never speculatively.
CURATED_INDICATORS: dict[str, str] = {
    "population": "Count_Person",
    "median_household_income": "Median_Income_Household",
    "median_age": "Median_Age_Person",
    "unemployment_rate": "UnemploymentRate_Person",
    "labor_force": "Count_Person_InLaborForce",
    "poverty_count": "Count_Person_BelowPovertyLevelInThePast12Months",
    "households": "Count_Household",
    "housing_units": "Count_HousingUnit",
    "gdp": "Amount_EconomicActivity_GrossDomesticProduction_Nominal",
    "gdp_per_capita": "Amount_EconomicActivity_GrossDomesticProduction_Nominal_PerCapita",
    "life_expectancy": "LifeExpectancy_Person",
    "fertility_rate": "FertilityRate_Person_Female",
    "co2_emissions": "Amount_Emissions_CarbonDioxide",
    "co2_emissions_per_capita": "Amount_Emissions_CarbonDioxide_PerCapita",
    "diabetes_prevalence": "Percent_Person_WithDiabetes",
    "obesity_prevalence": "Percent_Person_Obesity",
    "crime_count": "Count_CriminalActivities_CombinedCrime",
    "foreign_born_population": "Count_Person_ForeignBorn",
    "bachelors_or_higher": "Count_Person_EducationalAttainmentBachelorsDegreeOrHigher",
}

# Words the resolver should see as the same phrase the curated keys use.
_KEY_SYNONYMS: dict[str, str] = {
    "population": "population",
    "people": "population",
    "residents": "population",
    "median household income": "median_household_income",
    "household income": "median_household_income",
    "median income": "median_household_income",
    "median age": "median_age",
    "unemployment": "unemployment_rate",
    "unemployment rate": "unemployment_rate",
    "gdp per capita": "gdp_per_capita",
    "gdp": "gdp",
    "gross domestic product": "gdp",
    "life expectancy": "life_expectancy",
    "fertility": "fertility_rate",
    "fertility rate": "fertility_rate",
    "co2 per capita": "co2_emissions_per_capita",
    "co2 emissions per capita": "co2_emissions_per_capita",
    "carbon emissions per capita": "co2_emissions_per_capita",
    "co2 emissions": "co2_emissions",
    "carbon emissions": "co2_emissions",
    "diabetes": "diabetes_prevalence",
    "obesity": "obesity_prevalence",
    "crime": "crime_count",
    "households": "households",
    "housing units": "housing_units",
    "foreign born": "foreign_born_population",
    "bachelor's degree": "bachelors_or_higher",
    "college degree": "bachelors_or_higher",
    "labor force": "labor_force",
    "poverty": "poverty_count",
}

# Place-type words a question uses -> the Data Commons `typeOf` value.
PLACE_TYPES: dict[str, str] = {
    "country": "Country", "countries": "Country", "nation": "Country",
    "state": "State", "states": "State", "province": "State", "provinces": "State",
    "county": "County", "counties": "County",
    "city": "City", "cities": "City", "town": "City", "towns": "City",
    "continent": "Continent", "continents": "Continent",
    "zip": "CensusZipCodeTabulationArea", "zip code": "CensusZipCodeTabulationArea", "zip codes": "CensusZipCodeTabulationArea",
    "congressional district": "CongressionalDistrict", "congressional districts": "CongressionalDistrict",
    "census tract": "CensusTract", "census tracts": "CensusTract",
}

# A few places whose everyday name doesn't resolve cleanly, or that have a
# DCID the resolver can't be asked for by name ("the world").
KNOWN_PLACES: dict[str, str] = {
    "world": "Earth",
    "earth": "Earth",
    "global": "Earth",
    "united states": "country/USA",
    "usa": "country/USA",
    "us": "country/USA",
    "u.s.": "country/USA",
    "america": "country/USA",
    "africa": "africa",
    "europe": "europe",
    "asia": "asia",
    "north america": "northamerica",
    "south america": "southamerica",
    "oceania": "oceania",
}


class DataCommonsError(Exception):
    """A genuine fetch failure — never "no observation for this place",
    which is represented as empty rows (see module docstring)."""

    def __init__(self, message: str, code: str = "datacommons_error"):
        self.message = message
        self.code = code
        super().__init__(message)


# --- transport ---------------------------------------------------------------

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise DataCommonsError(
            f"Data Commons isn't configured on this deployment ({API_KEY_ENV} is unset). "
            "Create a key at https://apikeys.datacommons.org and mount it as a secret.",
            code="not_configured",
        )
    return key


def _request(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    """One call to the v2 API, cached by its exact arguments for
    CACHE_TTL_SECONDS. GET puts params in the query string; POST sends
    `body` as JSON with the key in the X-API-Key header (the documented
    shape for both)."""
    cache_key = json.dumps([method, path, params, body], sort_keys=True)
    now = time.time()
    with _cache_lock:
        hit = _cache.get(cache_key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    parsed = _http(method, path, params, body)
    with _cache_lock:
        _cache[cache_key] = (now, parsed)
    return parsed


def _http(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    """The uncached transport. Tests monkeypatch this."""
    key = _api_key()
    url = f"{API_BASE.rstrip('/')}/{path.lstrip('/')}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "X-API-Key": key}
    data = None
    if method == "GET":
        query = urllib.parse.urlencode({**(params or {}), "key": key}, doseq=True)
        url = f"{url}?{query}"
    else:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(2000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        if exc.code in (401, 403):
            raise DataCommonsError("Data Commons rejected the API key (HTTP %d)." % exc.code, code="auth") from exc
        if exc.code == 429:
            raise DataCommonsError("Data Commons rate-limited this request (HTTP 429).", code="rate_limited") from exc
        raise DataCommonsError(f"Data Commons returned HTTP {exc.code} for {path}: {detail[:200]}", code="upstream_error") from exc
    except urllib.error.URLError as exc:
        raise DataCommonsError(f"Couldn't reach Data Commons: {exc.reason}", code="upstream_error") from exc
    except TimeoutError as exc:
        raise DataCommonsError(f"Data Commons didn't respond within {REQUEST_TIMEOUT_SECONDS}s.", code="timeout") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise DataCommonsError(
            f"Data Commons response exceeded the {MAX_RESPONSE_BYTES // (1024 * 1024)} MB safety cap; narrow the place set or years.",
            code="response_too_large",
        )
    try:
        return json.loads(raw or b"{}")
    except ValueError as exc:
        raise DataCommonsError("Data Commons returned a non-JSON response.", code="upstream_error") from exc


def _post_all_pages(path: str, body: dict, max_pages: int = 20) -> list[dict]:
    """POST `body`, following `nextToken` (the v2 API pages node and
    observation responses — a `containedInPlace+` expansion of every US
    county comes back 500 at a time). Each page is cached separately."""
    pages, token = [], None
    for _ in range(max_pages):
        page = _request("POST", path, body={**body, **({"nextToken": token} if token else {})})
        pages.append(page)
        token = page.get("nextToken")
        if not token:
            break
    return pages


def _merge_observation_pages(pages: list[dict]) -> dict:
    by_var: dict = {}
    facets: dict = {}
    for page in pages:
        facets.update(page.get("facets") or {})
        for var, block in (page.get("byVariable") or {}).items():
            target = by_var.setdefault(var, {"byEntity": {}})["byEntity"]
            for ent, eblock in (block.get("byEntity") or {}).items():
                if ent in target and eblock.get("orderedFacets"):
                    target[ent].setdefault("orderedFacets", []).extend(eblock["orderedFacets"])
                else:
                    target[ent] = eblock
    return {"byVariable": by_var, "facets": facets}


def _source_label(meta: dict) -> str | None:
    """A human-readable source for a facet: importName when present, else
    the provenance URL's host, else the measurement method."""
    if meta.get("importName"):
        return str(meta["importName"])
    url = meta.get("provenanceUrl")
    if url:
        host = urllib.parse.urlparse(str(url)).netloc
        return host or str(url)
    return meta.get("measurementMethod")


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# --- resolution ----------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def place_type_for(word: str | None) -> str | None:
    if not word:
        return None
    w = _norm(word)
    if w in PLACE_TYPES:
        return PLACE_TYPES[w]
    # Already a Data Commons type name ("County", "AdministrativeArea1")?
    if re.fullmatch(r"[A-Z][A-Za-z0-9]+", word.strip()):
        return word.strip()
    return None


def names_for(dcids: list[str]) -> dict[str, str]:
    """dcid -> display name via `/v2/node` `->name`. Missing names fall back
    to the dcid itself rather than failing the whole fetch."""
    out: dict[str, str] = {}
    todo = [d for d in dict.fromkeys(dcids) if d]
    for i in range(0, len(todo), 500):
        chunk = todo[i:i + 500]
        resp = _request("POST", "node", body={"nodes": chunk, "property": "->name"})
        data = resp.get("data") or {}
        for dcid in chunk:
            nodes = (((data.get(dcid) or {}).get("arcs") or {}).get("name") or {}).get("nodes") or []
            out[dcid] = str(nodes[0].get("value")) if nodes and nodes[0].get("value") is not None else dcid
    return out


def resolve_place(name: str, type_hint: str | None = None) -> dict:
    """A place as written in the question -> {"dcid", "name", "type"}.
    KNOWN_PLACES first (the handful of names the resolver can't be asked
    for), then Data Commons' own resolver, narrowed by `type_hint` when
    given. Ambiguity is resolved the way Data Commons ranks its candidates
    (its first candidate), and the canonical name is fetched so the receipt
    shows exactly which place answered — an honest "Springfield" problem
    is visible there rather than hidden."""
    raw = re.sub(r"^(the)\s+", "", (name or "").strip(), flags=re.IGNORECASE)
    if not raw:
        raise DataCommonsError("No place was named in the question.", code="unknown_place")
    if raw.startswith(("geoId/", "country/", "wikidataId/", "nuts/")) or raw in ("Earth",):
        dcid = raw
    elif _norm(raw) in KNOWN_PLACES:
        dcid = KNOWN_PLACES[_norm(raw)]
    else:
        dc_type = place_type_for(type_hint)
        prop = f"<-description{{typeOf:{dc_type}}}->dcid" if dc_type else "<-description->dcid"
        resp = _request("GET", "resolve", params={"nodes": raw, "property": prop})
        candidates = []
        for ent in resp.get("entities") or []:
            candidates.extend(ent.get("candidates") or [])
        if not candidates and dc_type:
            # The hint may have been wrong ("state of Bavaria" is an
            # AdministrativeArea1); retry untyped before giving up.
            resp = _request("GET", "resolve", params={"nodes": raw, "property": "<-description->dcid"})
            for ent in resp.get("entities") or []:
                candidates.extend(ent.get("candidates") or [])
        if not candidates:
            raise DataCommonsError(f"Data Commons couldn't resolve the place \"{raw}\".", code="unknown_place")
        dcid = candidates[0].get("dcid")
        if not dcid:
            raise DataCommonsError(f"Data Commons couldn't resolve the place \"{raw}\".", code="unknown_place")
        type_hint = candidates[0].get("dominantType") or type_hint
    canonical = names_for([dcid]).get(dcid, dcid)
    return {"dcid": dcid, "name": canonical, "type": type_hint, "as_written": raw}


_LOCAL_PLACE_RE = re.compile(r"\b(county|parish|borough|city|town|township|municipality)\b\.?$", re.IGNORECASE)


def _is_qualified_place(first: str, second: str) -> bool:
    """"Santa Clara County" + "CA" / "Illinois" — a local place followed by a
    short qualifier — rather than two places to compare."""
    return bool(_LOCAL_PLACE_RE.search(first)) and (len(second) <= 3 or len(second.split()) <= 2)


def split_places(value) -> list[str]:
    """"California, Texas and New York" -> three names. A single name with
    an internal comma ("Santa Clara County, CA") is kept whole when the part
    after the comma looks like a state/country qualifier."""
    if isinstance(value, list):
        parts = [str(v) for v in value]
    else:
        text = str(value or "")
        parts = re.split(r";|\s+and\s+|\s+vs\.?\s+|\s+versus\s+", text)
        expanded = []
        for p in parts:
            bits = [b.strip() for b in p.split(",") if b.strip()]
            # "Santa Clara County, CA" / "Cook County, Illinois" is one place
            # (a county/city followed by its state), not two.
            if len(bits) == 2 and _is_qualified_place(bits[0], bits[1]):
                expanded.append(", ".join(bits))
            else:
                expanded.extend(bits)
        parts = expanded
    out = [p.strip() for p in parts if p and p.strip()]
    return out or [str(value or "").strip()]


def children_of(parent_dcid: str, child_type: str) -> list[dict]:
    """Every place of `child_type` contained (transitively) in the parent,
    as [{"dcid", "name"}], capped at MAX_ENTITIES — a cap hit is a
    DataCommonsError so the planner's next candidate, or an honest
    refusal, takes over rather than a silently truncated ranking."""
    nodes = []
    for page in _post_all_pages("node", {"nodes": [parent_dcid], "property": f"<-containedInPlace+{{typeOf:{child_type}}}"}):
        arcs = ((page.get("data") or {}).get(parent_dcid) or {}).get("arcs") or {}
        for arc in arcs.values():
            nodes.extend(arc.get("nodes") or [])
        if len(nodes) > MAX_ENTITIES:
            break
    seen = set()
    nodes = [n for n in nodes if n.get("dcid") and not (n["dcid"] in seen or seen.add(n["dcid"]))]
    if len(nodes) > MAX_ENTITIES:
        raise DataCommonsError(
            f"{len(nodes):,} places of type {child_type} in that parent exceeds the {MAX_ENTITIES:,}-place cap; "
            "narrow the parent (a state instead of the country) or the type.",
            code="too_many_entities",
        )
    out = [{"dcid": n.get("dcid"), "name": n.get("name") or n.get("dcid")} for n in nodes if n.get("dcid")]
    missing = [o["dcid"] for o in out if o["name"] == o["dcid"]]
    if missing:
        names = names_for(missing)
        for o in out:
            if o["dcid"] in names:
                o["name"] = names[o["dcid"]]
    return out


def _indicator_candidates(indicator: str) -> list[dict]:
    """Ordered candidate variables for a plain-language indicator: curated
    key (or synonym) first, then Data Commons' indicator resolver. Topics
    (`dc/topic/...`) are never candidates — they are groupings, not
    variables."""
    text = _norm(indicator).replace("_", " ")
    key = indicator.strip().lower() if indicator.strip().lower() in CURATED_INDICATORS else _KEY_SYNONYMS.get(text)
    out: list[dict] = []
    if key:
        out.append({"dcid": CURATED_INDICATORS[key], "via": f"curated:{key}", "score": None})
    try:
        resp = _request("GET", "resolve", params={"nodes": indicator, "resolver": "indicator"})
    except DataCommonsError as exc:
        if out:
            return out
        raise exc
    for ent in resp.get("entities") or []:
        for cand in ent.get("candidates") or []:
            dcid = cand.get("dcid")
            if not dcid or dcid.startswith("dc/topic/") or any(o["dcid"] == dcid for o in out):
                continue
            score = cand.get("score")
            out.append({"dcid": dcid, "via": "resolver", "score": float(score) if isinstance(score, (int, float)) else None})
    return out


def _existence(variables: list[str], entities: list[str]) -> dict[str, set[str]]:
    """variable -> set of entities that have at least one observation
    (`select entity, variable` — no values, so it's cheap)."""
    resp = _merge_observation_pages(_post_all_pages("observation", {
        "date": "", "variable": {"dcids": variables}, "entity": {"dcids": entities}, "select": ["entity", "variable"],
    }))
    out: dict[str, set[str]] = {}
    for var, block in (resp.get("byVariable") or {}).items():
        out[var] = set((block.get("byEntity") or {}).keys())
    return out


def resolve_indicator(indicator: str, entity_dcids: list[str], max_candidates: int = 8) -> dict:
    """The first candidate variable that has data for at least one of the
    given entities (checked against a bounded sample of them). Returns
    {"dcid", "name", "via", "considered": [...]}; raises when nothing
    resolves at all."""
    if not (indicator or "").strip():
        raise DataCommonsError("No indicator was named in the question.", code="unknown_indicator")
    cands = _indicator_candidates(indicator)[:max_candidates]
    if not cands:
        raise DataCommonsError(f"Data Commons has no statistical variable matching \"{indicator}\".", code="unknown_indicator")
    sample = list(dict.fromkeys(entity_dcids))[:50]
    have = _existence([c["dcid"] for c in cands], sample) if sample else {}
    chosen = next((c for c in cands if have.get(c["dcid"])), None)
    if chosen is None:
        raise DataCommonsError(
            f"Data Commons has variables matching \"{indicator}\" ({', '.join(c['dcid'] for c in cands[:3])}), "
            "but none of them has an observation for the place(s) asked about.",
            code="no_data_for_place",
        )
    name = names_for([chosen["dcid"]]).get(chosen["dcid"], chosen["dcid"])
    return {"dcid": chosen["dcid"], "name": name, "via": chosen["via"],
            "considered": [{"dcid": c["dcid"], "via": c["via"], "score": c["score"]} for c in cands]}


# --- observations --------------------------------------------------------------

def _year(date: str) -> int | None:
    m = re.match(r"(\d{4})", str(date or ""))
    return int(m.group(1)) if m else None


def fetch_observations(variable: str, entities: list[dict], date: str = "", year: int | None = None,
                       year_from: int | None = None, year_to: int | None = None, latest_only: bool = False) -> dict:
    """Observations for one variable across `entities` ([{"dcid","name"}]),
    one facet for all of them. `date` is the API's own filter ("" = all,
    "LATEST", or an ISO date); `year`/`year_from`/`year_to` filter client-
    side (the API has no range filter); `latest_only` keeps the newest
    observation per entity after filtering. Returns {"rows", "facet",
    "facets_available"}."""
    dcids = [e["dcid"] for e in entities]
    if len(dcids) > MAX_ENTITIES:
        raise DataCommonsError(f"{len(dcids):,} places exceeds the {MAX_ENTITIES:,}-place cap.", code="too_many_entities")
    names = {e["dcid"]: e.get("name") or e["dcid"] for e in entities}
    api_date = "LATEST" if latest_only and not (year or year_from or year_to) else (date or "")
    if year and not (year_from or year_to):
        api_date = str(year)
    resp = _merge_observation_pages(_post_all_pages("observation", {
        "date": api_date, "variable": {"dcids": [variable]}, "entity": {"dcids": dcids},
        "select": ["entity", "variable", "date", "value"],
    }))
    facets_meta = resp.get("facets") or {}
    by_entity = (((resp.get("byVariable") or {}).get(variable) or {}).get("byEntity") or {})

    # One facet for the whole answer: the one covering the most entities;
    # ties broken by Data Commons' own preferred order (first orderedFacet).
    coverage: dict[str, int] = {}
    first_rank: dict[str, int] = {}
    for ent, block in by_entity.items():
        for rank, f in enumerate(block.get("orderedFacets") or []):
            fid = str(f.get("facetId"))
            coverage[fid] = coverage.get(fid, 0) + 1
            first_rank[fid] = min(first_rank.get(fid, 99), rank)
    if not coverage:
        return {"rows": [], "facet": None, "facets_available": []}
    facet_id = sorted(coverage, key=lambda f: (-coverage[f], first_rank[f], f))[0]
    meta = facets_meta.get(facet_id) or {}
    facet = {
        "facet_id": facet_id,
        "source": _source_label(meta),
        "provenance_url": meta.get("provenanceUrl"),
        "measurement_method": meta.get("measurementMethod"),
        "observation_period": meta.get("observationPeriod"),
        "unit": meta.get("unit"),
        "covers_places": coverage[facet_id],
        "of_places": len(by_entity),
    }

    rows = []
    for ent, block in by_entity.items():
        chosen = next((f for f in block.get("orderedFacets") or [] if str(f.get("facetId")) == facet_id), None)
        if not chosen:
            continue
        obs = chosen.get("observations") or []
        kept = []
        for o in obs:
            y = _year(o.get("date"))
            if year and y != year:
                continue
            if year_from and (y is None or y < year_from):
                continue
            if year_to and (y is None or y > year_to):
                continue
            kept.append(o)
        if latest_only and kept:
            kept = [max(kept, key=lambda o: str(o.get("date")))]
        for o in kept:
            rows.append({
                "place": names.get(ent, ent),
                "place_dcid": ent,
                "date": o.get("date"),
                "value": o.get("value"),
                "unit": facet["unit"],
                "source": facet["source"],
                "measurement_method": facet["measurement_method"],
                "observation_period": facet["observation_period"],
                "provenance_url": facet["provenance_url"],
            })
    rows.sort(key=lambda r: (str(r["place"]), str(r["date"])))
    if len(rows) > MAX_ROWS:
        raise DataCommonsError(f"{len(rows):,} observations exceeds the {MAX_ROWS:,}-row cap; narrow the years or places.", code="too_many_rows")
    available = [{"facet_id": f, "source": _source_label(facets_meta.get(f) or {}), "covers_places": coverage[f],
                  "facet_raw": facets_meta.get(f) or {}} for f in
                 sorted(coverage, key=lambda f: (-coverage[f], first_rank[f], f))]
    return {"rows": rows, "facet": facet, "facets_available": available}


# --- template entry points -------------------------------------------------------

def _as_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _facet_params(facet: dict | None) -> dict:
    """The chosen facet, flattened into receipt-friendly scalar params."""
    if not facet:
        return {"source": None}
    return {
        "source": facet.get("source"),
        "measurement_method": facet.get("measurement_method"),
        "observation_period": facet.get("observation_period"),
        "unit": facet.get("unit"),
        "provenance_url": facet.get("provenance_url"),
        "facet_covers": f"{facet.get('covers_places')} of {facet.get('of_places')} places",
    }


def run_place(params: dict) -> dict:
    """Executor `datacommons_place` (ac.dc_indicator_for_place): one
    indicator for one or more named places — a point value, a year range,
    or the whole history. Returns {"rows", "params": bound params for the
    receipt, "notes": [...]}. Empty rows (not an error) when the places
    resolve but hold no observation in the requested window."""
    place_names = split_places(params.get("place", ""))
    type_hint = params.get("place_type")
    places = [resolve_place(p, type_hint) for p in place_names]
    indicator = resolve_indicator(str(params.get("indicator", "")), [p["dcid"] for p in places])
    year = _as_int(params.get("year"))
    year_from, year_to = _as_int(params.get("year_from")), _as_int(params.get("year_to"))
    latest = _norm(str(params.get("period", ""))) == "latest" and not (year or year_from or year_to)
    result = fetch_observations(indicator["dcid"], places, year=year, year_from=year_from, year_to=year_to, latest_only=latest)
    rows = [{"variable": indicator["name"], **r} for r in result["rows"]]
    bound = {
        "indicator": params.get("indicator"),
        "variable_dcid": indicator["dcid"],
        "variable_name": indicator["name"],
        "resolved_via": indicator["via"],
        "place": ", ".join(p["as_written"] for p in places),
        "place_dcids": ", ".join(p["dcid"] for p in places),
        "place_names": ", ".join(p["name"] for p in places),
        "period": "latest" if latest else ("year" if year else ("range" if (year_from or year_to) else "all")),
        **({"year": year} if year else {}),
        **({"year_from": year_from} if year_from else {}),
        **({"year_to": year_to} if year_to else {}),
        **_facet_params(result["facet"]),
    }
    return {"rows": rows, "params": bound, "considered": indicator["considered"], "facets_available": result["facets_available"]}


def run_children(params: dict) -> dict:
    """Executor `datacommons_children` (ac.dc_indicator_across_places):
    one indicator for every place of `child_type` inside `parent_place`,
    latest value per place (or one named year), ranked."""
    parent = resolve_place(str(params.get("parent_place", "")), params.get("parent_type"))
    child_type = place_type_for(params.get("child_type")) or "County"
    children = children_of(parent["dcid"], child_type)
    if not children:
        return {"rows": [], "params": {"parent_place": parent["name"], "parent_dcid": parent["dcid"], "child_type": child_type},
                "considered": [], "facets_available": []}
    indicator = resolve_indicator(str(params.get("indicator", "")), [c["dcid"] for c in children])
    year = _as_int(params.get("year"))
    result = fetch_observations(indicator["dcid"], children, year=year, latest_only=True)
    rows = [{"variable": indicator["name"], **r} for r in result["rows"]]
    order = _norm(str(params.get("order", "desc")))
    numeric = [r for r in rows if isinstance(r.get("value"), (int, float))]
    numeric.sort(key=lambda r: r["value"], reverse=(order != "asc"))
    top_n = min(_as_int(params.get("top_n")) or 25, 500)
    ranked = numeric[:top_n]
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    bound = {
        "indicator": params.get("indicator"),
        "variable_dcid": indicator["dcid"],
        "variable_name": indicator["name"],
        "resolved_via": indicator["via"],
        "parent_place": parent["as_written"],
        "parent_dcid": parent["dcid"],
        "parent_name": parent["name"],
        "child_type": child_type,
        "places_in_parent": len(children),
        "places_with_data": len(numeric),
        "order": "asc" if order == "asc" else "desc",
        "top_n": top_n,
        **({"year": year} if year else {"period": "latest"}),
        **_facet_params(result["facet"]),
    }
    return {"rows": ranked, "params": bound, "considered": indicator["considered"], "facets_available": result["facets_available"]}


EXECUTORS = {"datacommons_place": run_place, "datacommons_children": run_children}


def run(executor: str, params: dict) -> dict:
    fn = EXECUTORS.get(executor)
    if fn is None:
        raise DataCommonsError(f"Unknown Data Commons executor {executor!r}.", code="unknown_executor")
    return fn(params or {})
