"""
Place boundaries for map answers — from Data Commons, keyed by DCID.

Why here and not a geometry build: Data Commons place nodes carry
simplified GeoJSON (`geoJsonCoordinatesDP1` … `DP3`, Douglas–Peucker at
three tolerances) for countries, states/provinces, counties, cities and
more, worldwide, keyed by the same DCIDs the Data Commons templates already
return in every row (`place_dcid`). BigQuery rows keyed by FIPS or ISO map
onto those ids mechanically (`geoId/06085`, `country/USA`). So one accessor
call, the cache the accessor already has, no BigQuery `ST_SIMPLIFY` build,
no Cloud Storage bucket, and the same key for every source.

Contract with the rest of Atlas (atlas-earth-engine-ui-plan.md §2): the
synthesis model chooses the visualization *kind* (`choropleth`) and names
the value / label columns; it never emits geometry. `attach()` joins the
fetched rows to boundaries on stable ids — never on display names — and
returns a FeatureCollection whose properties carry the row's value, label
and provenance, plus a match report the walkthrough records. A poor match
(fewer than MIN_FEATURES places, or under MIN_MATCH_RATE of the rows) is
reported so the pipeline can downgrade the answer to a bar chart rather
than draw a half-empty map.
"""
import json
import os
import re
import threading

from ..accessor import datacommons_accessor as dc

MAX_FEATURES = int(os.environ.get("ATLAS_GEO_MAX_FEATURES", 3500))
MIN_FEATURES = int(os.environ.get("ATLAS_GEO_MIN_FEATURES", 3))
MIN_MATCH_RATE = float(os.environ.get("ATLAS_GEO_MIN_MATCH_RATE", 0.5))
# Detail level by feature count: DP1 is the coarsest (fine for 3,000 US
# counties at country scale), DP2 for a state's counties or a continent's
# countries, DP3 for a handful of places.
DETAIL_BY_COUNT = ((40, "DP3"), (400, "DP2"), (MAX_FEATURES + 1, "DP1"))

_cache: dict[tuple[str, str], dict | None] = {}
_cache_lock = threading.Lock()

# Row columns that can carry a place identity, in priority order. Names of
# places are deliberately absent — a name is never a key.
_DCID_COLUMNS = ("place_dcid", "dcid", "parent_dcid")
_FIPS_COLUMNS = ("geo_id", "geoid", "fips", "fips_code", "county_fips", "county_fips_code", "state_fips", "state_fips_code",
                 "county_geoid", "state_geoid", "zip_code", "zipcode", "zcta")
_ISO3_COLUMNS = ("iso3", "iso_3", "country_iso3", "country_code_iso3", "country_code")


def place_key(row: dict) -> str | None:
    """A Data Commons DCID for the place a row is about, or None."""
    for col in _DCID_COLUMNS:
        v = row.get(col)
        if (isinstance(v, str) and "/" in v) or v == "Earth":
            return v
    state = row.get("state_fips_code") or row.get("state_fips")
    county = row.get("county_fips_code") or row.get("county_fips")
    if state is not None and county is not None:
        s, c = str(state).strip(), str(county).strip()
        if s.isdigit() and c.isdigit():
            return f"geoId/{s.zfill(2)}{c.zfill(3)}" if len(c) <= 3 else f"geoId/{c.zfill(5)}"
    for col in _FIPS_COLUMNS:
        v = row.get(col)
        if v is None:
            continue
        s = str(v).strip()
        if not s.isdigit():
            continue
        if col in ("zip_code", "zipcode", "zcta") and len(s) == 5:
            return f"zip/{s}"
        if len(s) in (1, 2):
            return f"geoId/{s.zfill(2)}"
        if len(s) in (4, 5):
            return f"geoId/{s.zfill(5)}"
        if len(s) in (10, 11):
            return f"geoId/{s.zfill(11)}"
    for col in _ISO3_COLUMNS:
        v = row.get(col)
        if isinstance(v, str) and re.fullmatch(r"[A-Za-z]{3}", v.strip()):
            return f"country/{v.strip().upper()}"
    return None


def geo_capable(rows: list[dict], minimum: int = 5) -> bool:
    """True when at least `minimum` distinct places in the rows have a key —
    the signal synthesis is given so it may choose `choropleth`."""
    keys = {place_key(r) for r in rows if isinstance(r, dict)}
    keys.discard(None)
    return len(keys) >= minimum


def detail_for(n: int) -> str:
    for limit, level in DETAIL_BY_COUNT:
        if n < limit:
            return level
    return "DP1"


def fetch_geometries(dcids: list[str], detail: str) -> dict[str, dict | None]:
    """dcid -> GeoJSON geometry dict (or None when Data Commons has none),
    via `/v2/node` `->geoJsonCoordinates<detail>`, cached for the life of
    the process (boundaries do not change)."""
    out: dict[str, dict | None] = {}
    todo = []
    with _cache_lock:
        for d in dict.fromkeys(dcids):
            if (d, detail) in _cache:
                out[d] = _cache[(d, detail)]
            else:
                todo.append(d)
    for i in range(0, len(todo), 200):
        chunk = todo[i:i + 200]
        pages = dc._post_all_pages("node", {"nodes": chunk, "property": f"->geoJsonCoordinates{detail}"})
        data: dict = {}
        for page in pages:
            data.update(page.get("data") or {})
        for d in chunk:
            geom = None
            nodes = (((data.get(d) or {}).get("arcs") or {}).get(f"geoJsonCoordinates{detail}") or {}).get("nodes") or []
            raw = nodes[0].get("value") if nodes else None
            if raw:
                try:
                    geom = json.loads(raw) if isinstance(raw, str) else raw
                except ValueError:
                    geom = None
            if geom is not None and geom.get("type") not in ("Polygon", "MultiPolygon", "Point"):
                geom = None
            out[d] = geom
            with _cache_lock:
                _cache[(d, detail)] = geom
    return out


def _bounds(features: list[dict]) -> list[float] | None:
    w = s = float("inf")
    e = n = float("-inf")

    def walk(coords):
        nonlocal w, s, e, n
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            x, y = coords[0], coords[1]
            w, e, s, n = min(w, x), max(e, x), min(s, y), max(n, y)
        else:
            for c in coords:
                walk(c)

    for f in features:
        walk((f.get("geometry") or {}).get("coordinates"))
    if w == float("inf"):
        return None
    return [w, s, e, n]


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return None
    return None


def attach(rows: list[dict], value_field: str, label_field: str | None = None, extra_fields: tuple[str, ...] = ("date", "source", "unit", "rank")) -> dict:
    """Boundaries for the places in `rows`, with each feature carrying
    {key, label, value, ...extra_fields} from its row. Returns
    {"features": FeatureCollection, "key_field", "value_field",
    "label_field", "bounds", "detail", "matched", "unmatched",
    "rows_with_key", "ok", "reason"} — `ok` is the pipeline's go/no-go."""
    # One row per place: the latest observation when rows carry a
    # date/year column (a trend for several places maps its newest values),
    # otherwise the first row seen.
    order_col = next((c for c in ("date", "year", "fiscal_year", "period_end") if any(isinstance(r, dict) and r.get(c) is not None for r in rows)), None)
    keyed: dict[str, dict] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        k = place_key(r)
        if not k or _number(r.get(value_field)) is None:
            continue
        prev = keyed.get(k)
        if prev is None or (order_col and str(r.get(order_col) or "") > str(prev.get(order_col) or "")):
            keyed[k] = r
    report = {"key_field": "key", "value_field": value_field, "label_field": label_field, "rows_with_key": len(keyed),
              "matched": 0, "unmatched": [], "detail": None, "bounds": None, "ok": False, "reason": None}
    if len(keyed) < MIN_FEATURES:
        report["reason"] = f"only {len(keyed)} rows carry a place key with a numeric {value_field}"
        return {"features": {"type": "FeatureCollection", "features": []}, **report}
    dcids = list(keyed)[:MAX_FEATURES]
    detail = detail_for(len(dcids))
    geoms = fetch_geometries(dcids, detail)
    features, unmatched = [], []
    for d in dcids:
        geom = geoms.get(d)
        if geom is None:
            unmatched.append(d)
            continue
        r = keyed[d]
        label = r.get(label_field) if label_field else None
        if label is None:
            label = r.get("place") or r.get("name") or r.get("place_name") or d
        props = {"key": d, "label": str(label), "value": _number(r.get(value_field))}
        for f in extra_fields:
            if f in r and r[f] is not None:
                props[f] = r[f]
        features.append({"type": "Feature", "id": d, "geometry": geom, "properties": props})
    report.update({"matched": len(features), "unmatched": unmatched[:20], "detail": detail, "bounds": _bounds(features)})
    rate = len(features) / len(dcids) if dcids else 0.0
    if len(features) < MIN_FEATURES or rate < MIN_MATCH_RATE:
        report["reason"] = f"boundaries found for {len(features)} of {len(dcids)} places"
        return {"features": {"type": "FeatureCollection", "features": features}, **report}
    report["ok"] = True
    return {"features": {"type": "FeatureCollection", "features": features}, **report}


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
