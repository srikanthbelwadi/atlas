"""
Guarded SEC EDGAR fetcher — company-facts, the free XBRL-facts-by-company API.

Unlike BigQuery, there's no per-request bill to guard here (EDGAR is free,
no auth), so the guardrails are a network safety story instead of a cost
one: a short wall-clock timeout, a response-size cap (some companies' full
filing history is tens of MB of tagged XBRL facts), and a required,
descriptive `User-Agent` header — sec.gov rejects/blocks requests without
one (https://www.sec.gov/os/webmaster-faq#developers), and rate-limits at
roughly 10 requests/second per source IP.

These constants live here, not in orchestrator/guardrails.py, on purpose:
that module frames itself specifically as BigQuery byte-cap / monthly-$
guardrails, and this is an unrelated, unbilled network-safety concern.

Two live calls, not one:
  1. https://www.sec.gov/files/company_tickers.json — ticker/name -> CIK,
     fetched once and cached in-process (it's the whole ~9,000-company list,
     refreshed roughly daily by SEC; a matter of correctness, not cost, to
     refresh it — see TICKER_CACHE_TTL_SECONDS).
  2. https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:0>10}.json — every
     XBRL-tagged fact SEC has on file for that company, across every filing.

Never invents a metric: CURATED_METRICS is the only set of concept tags this
will ever fetch, each one a real, well-known US-GAAP/DEI tag chosen and
reviewed by a person — the same curated-mapping trust story used by the
AttestedComputation templates in okf-catalog/attested-computations/. The
model picks a `metric` key from this fixed list, never a raw XBRL tag string.

Design note on "no data" vs. "fetch failed": a company that legitimately has
no reported value for a metric/year is NOT an error — fetch_metric() returns
empty rows for that case, same as an ad-hoc BigQuery query returning zero
rows, so it flows through pipeline.py's existing `if not rows:` handling
(backtrack, or a graceful "couldn't find" answer). SecEdgarError is reserved
for genuine fetch failures: unresolvable company, unknown curated metric,
network/timeout/HTTP errors, or a response that trips the size cap.
"""
import json
import os
import time
import urllib.error
import urllib.request

REQUEST_TIMEOUT_SECONDS = int(os.environ.get("ATLAS_SEC_EDGAR_TIMEOUT_SECONDS", 15))
MAX_RESPONSE_BYTES = int(os.environ.get("ATLAS_SEC_EDGAR_MAX_RESPONSE_BYTES", 15 * 1024 * 1024))  # 15 MB
TICKER_CACHE_TTL_SECONDS = int(os.environ.get("ATLAS_SEC_EDGAR_TICKER_CACHE_TTL_SECONDS", 24 * 3600))

USER_AGENT = os.environ.get("ATLAS_SEC_EDGAR_USER_AGENT", "Atlas (atlas-ard-okf; contact: admin@atlasdata.world)")

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Curated metric key -> (XBRL taxonomy, concept tag, expected unit). Only
# these keys are ever fetched; the planner extracts one of these keys, never
# a raw tag string, so a hallucinated tag can never reach a real request.
CURATED_METRICS: dict[str, tuple[str, str, str]] = {
    "revenue": ("us-gaap", "Revenues", "USD"),
    "net_income": ("us-gaap", "NetIncomeLoss", "USD"),
    "total_assets": ("us-gaap", "Assets", "USD"),
    "total_liabilities": ("us-gaap", "Liabilities", "USD"),
    "operating_income": ("us-gaap", "OperatingIncomeLoss", "USD"),
    "cash_and_equivalents": ("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "USD"),
    "eps_diluted": ("us-gaap", "EarningsPerShareDiluted", "USD/shares"),
    "shares_outstanding": ("dei", "EntityCommonStockSharesOutstanding", "shares"),
}


class SecEdgarError(Exception):
    """A genuine fetch failure — not "this company has no data for that
    metric/year", which is represented as empty rows instead (see module
    docstring)."""

    def __init__(self, message: str, code: str = "sec_edgar_error"):
        self.message = message
        self.code = code
        super().__init__(message)


_ticker_cache: dict | None = None
_ticker_cache_at: float = 0.0


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SecEdgarError(f"SEC EDGAR has no record at {url}.", code="not_found") from exc
        raise SecEdgarError(f"SEC EDGAR returned HTTP {exc.code} for {url}.", code="upstream_error") from exc
    except urllib.error.URLError as exc:
        raise SecEdgarError(f"Couldn't reach SEC EDGAR: {exc.reason}", code="upstream_error") from exc
    except TimeoutError as exc:
        raise SecEdgarError(f"SEC EDGAR didn't respond within {REQUEST_TIMEOUT_SECONDS}s.", code="timeout") from exc

    if len(raw) > MAX_RESPONSE_BYTES:
        raise SecEdgarError(
            f"SEC EDGAR response exceeded the {MAX_RESPONSE_BYTES // (1024 * 1024)} MB safety cap.",
            code="response_too_large",
        )
    return json.loads(raw)


def _load_ticker_map() -> dict:
    """Ticker (upper) and lowercased company name -> zero-padded 10-digit
    CIK. Cached in-process; SEC refreshes the source file roughly daily, so
    TICKER_CACHE_TTL_SECONDS is a correctness knob, not a cost one (this
    endpoint is free either way)."""
    global _ticker_cache, _ticker_cache_at
    now = time.time()
    if _ticker_cache is not None and (now - _ticker_cache_at) < TICKER_CACHE_TTL_SECONDS:
        return _ticker_cache
    data = _http_get_json(TICKERS_URL)
    mapping: dict[str, str] = {}
    for row in data.values():
        cik = str(row["cik_str"]).zfill(10)
        mapping[row["ticker"].upper()] = cik
        mapping[row["title"].strip().lower()] = cik
    _ticker_cache = mapping
    _ticker_cache_at = now
    return mapping


def resolve_cik(company_or_ticker: str) -> str:
    """Resolves a ticker or company name (as extracted from the question) to
    a zero-padded 10-digit CIK. Tries an exact ticker match, then an exact
    name match, then a unique substring match; raises SecEdgarError if none
    or more than one company matches."""
    mapping = _load_ticker_map()
    key = company_or_ticker.strip()
    if key.upper() in mapping:
        return mapping[key.upper()]
    if key.lower() in mapping:
        return mapping[key.lower()]
    needle = key.lower()
    # Only search the lowercase company-name entries (skip the uppercase
    # ticker entries) so a short ticker-like substring can't spuriously
    # match a company name too.
    matches = {cik for name, cik in mapping.items() if name.islower() and needle in name}
    if len(matches) == 1:
        return matches.pop()
    if len(matches) > 1:
        raise SecEdgarError(
            f"\"{company_or_ticker}\" matches more than one SEC-registered company; try the exact name or ticker.",
            code="ambiguous_company",
        )
    raise SecEdgarError(
        f"Couldn't find a SEC-registered company matching \"{company_or_ticker}\".",
        code="unknown_company",
    )


def fetch_metric(company: str, metric: str, fiscal_year: int | None = None) -> dict:
    """Fetches one curated metric's reported values for a company, optionally
    filtered to one fiscal year. Returns {"rows": [...], "cik", "entity_name",
    "concept"} — `rows` is [] (not an exception) when the company is real but
    has no reported value for this metric/year, so pipeline.py's existing
    empty-result handling takes over from there."""
    if metric not in CURATED_METRICS:
        raise SecEdgarError(
            f"\"{metric}\" isn't one of the curated SEC metrics Atlas knows how to fetch: "
            f"{', '.join(sorted(CURATED_METRICS))}.",
            code="unknown_metric",
        )
    taxonomy, concept, unit = CURATED_METRICS[metric]
    cik = resolve_cik(company)
    facts = _http_get_json(COMPANY_FACTS_URL.format(cik=cik))
    entity_name = facts.get("entityName", company)
    concept_data = facts.get("facts", {}).get(taxonomy, {}).get(concept)

    if not concept_data:
        # Real company, but it has never reported this concept (e.g. asking
        # a non-bank for a bank-specific tag). Not an error — empty rows let
        # the pipeline's own "empty_result" path handle it gracefully.
        return {"rows": [], "cik": cik, "entity_name": entity_name, "concept": f"{taxonomy}:{concept}"}

    values = concept_data.get("units", {}).get(unit, [])
    if fiscal_year is not None:
        values = [v for v in values if v.get("fy") == fiscal_year]

    rows = [
        {
            "value": v["val"],
            "unit": unit,
            "period_end": v.get("end"),
            "period_start": v.get("start"),
            "fiscal_year": v.get("fy"),
            "fiscal_period": v.get("fp"),
            "form": v.get("form"),
            "filed": v.get("filed"),
        }
        for v in values
    ]
    return {"rows": rows, "cik": cik, "entity_name": entity_name, "concept": f"{taxonomy}:{concept}"}
