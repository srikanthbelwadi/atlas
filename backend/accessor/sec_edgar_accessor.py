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
import re
import time
import urllib.error
import urllib.request

REQUEST_TIMEOUT_SECONDS = int(os.environ.get("ATLAS_SEC_EDGAR_TIMEOUT_SECONDS", 15))
MAX_RESPONSE_BYTES = int(os.environ.get("ATLAS_SEC_EDGAR_MAX_RESPONSE_BYTES", 15 * 1024 * 1024))  # 15 MB
TICKER_CACHE_TTL_SECONDS = int(os.environ.get("ATLAS_SEC_EDGAR_TICKER_CACHE_TTL_SECONDS", 24 * 3600))

USER_AGENT = os.environ.get("ATLAS_SEC_EDGAR_USER_AGENT", "Atlas (atlas-ard-okf; contact: admin@atlasdata.world)")

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Curated metric key -> (XBRL taxonomy, candidate concept tags in priority
# order, expected unit). Only these keys are ever fetched; the planner
# extracts one of these keys, never a raw tag string, so a hallucinated tag
# can never reach a real request.
#
# "revenue" carries more than one candidate tag on purpose: ASC 606 (adopted
# by most large filers around 2018) moved top-line revenue reporting from
# the older `Revenues` concept to `RevenueFromContractWithCustomerExcluding/
# IncludingAssessedTax`. A company's history can straddle that transition —
# older filings under `Revenues`, newer ones under the ASC 606 tag — so
# fetch_metric() merges whatever candidate tags actually have data rather
# than picking one and failing if that one happens to be empty (this is
# exactly the bug a live test surfaced: Apple's FY2023 revenue lives under
# the ASC 606 tag, not the legacy `Revenues` tag, which has none). All
# candidates are real, well-known US-GAAP concepts — never a guessed tag.
CURATED_METRICS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "revenue": (
        "us-gaap",
        (
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ),
        "USD",
    ),
    "net_income": ("us-gaap", ("NetIncomeLoss",), "USD"),
    "total_assets": ("us-gaap", ("Assets",), "USD"),
    "total_liabilities": ("us-gaap", ("Liabilities",), "USD"),
    "operating_income": ("us-gaap", ("OperatingIncomeLoss",), "USD"),
    "cash_and_equivalents": ("us-gaap", ("CashAndCashEquivalentsAtCarryingValue",), "USD"),
    "eps_diluted": ("us-gaap", ("EarningsPerShareDiluted",), "USD/shares"),
    "shares_outstanding": ("dei", ("EntityCommonStockSharesOutstanding",), "shares"),
}


class SecEdgarError(Exception):
    """A genuine fetch failure — not "this company has no data for that
    metric/year", which is represented as empty rows instead (see module
    docstring)."""

    def __init__(self, message: str, code: str = "sec_edgar_error"):
        self.message = message
        self.code = code
        super().__init__(message)


# Common consumer/product names that differ from the company's own SEC
# filer name — a plain-language question says "Google", never "Alphabet
# Inc."; "Facebook", never "Meta Platforms, Inc." No amount of suffix-
# stripping or substring matching bridges that gap, since the words don't
# overlap at all. A small, curated, human-reviewed list (same trust story
# as CURATED_METRICS above) mapping the everyday name to the ticker its
# SEC filings are actually under — never inferred or guessed at request
# time. Found via a live test that surfaced "Google" resolving to nothing;
# extend this list the same way, from real observed gaps, not speculatively.
KNOWN_ALIASES: dict[str, str] = {
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "facebook": "META",
    "meta": "META",
}

_ticker_cache: dict | None = None
_ticker_cache_at: float = 0.0
_normalized_name_cache: dict[str, set] | None = None

# Trailing corporate-form words SEC's company titles routinely carry (e.g.
# "Apple Inc." or "Apple Hospitality REIT, Inc.") that a plain-language
# question never includes ("Apple"). Stripped repeatedly from the end of a
# name so a bare company name can exact-match its full registered title
# without falling through to ambiguous substring search.
_CORP_SUFFIX_RE = re.compile(
    r"[,.]?\s*\b(incorporated|inc|corporation|corp|company|co|holdings?|"
    r"group|plc|llc|l l c|ltd|limited|lp|l p|reit)\b\.?\s*$",
    re.IGNORECASE,
)


def _normalize_company_name(name: str) -> str:
    """Lowercases and strips trailing corporate-form suffixes (Inc., Corp.,
    REIT, etc.) so "Apple" can exact-match the registered title "Apple
    Inc." without colliding with unrelated companies that merely contain
    "apple" as a substring (e.g. "Apple Hospitality REIT, Inc.")."""
    name = name.strip().lower()
    prev = None
    while prev != name:
        prev = name
        name = _CORP_SUFFIX_RE.sub("", name).strip()
    return name


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
    global _ticker_cache, _ticker_cache_at, _normalized_name_cache
    now = time.time()
    if _ticker_cache is not None and (now - _ticker_cache_at) < TICKER_CACHE_TTL_SECONDS:
        return _ticker_cache
    data = _http_get_json(TICKERS_URL)
    mapping: dict[str, str] = {}
    normalized: dict[str, set] = {}
    for row in data.values():
        cik = str(row["cik_str"]).zfill(10)
        title = row["title"].strip()
        mapping[row["ticker"].upper()] = cik
        mapping[title.lower()] = cik
        normalized.setdefault(_normalize_company_name(title), set()).add(cik)
    _ticker_cache = mapping
    _ticker_cache_at = now
    _normalized_name_cache = normalized
    return mapping


def _load_normalized_name_map() -> dict[str, set]:
    _load_ticker_map()  # ensures _normalized_name_cache is populated/fresh
    return _normalized_name_cache or {}


def resolve_cik(company_or_ticker: str) -> str:
    """Resolves a ticker or company name (as extracted from the question) to
    a zero-padded 10-digit CIK. Tries, in order: an exact ticker match, an
    exact full-title match, a curated brand-name alias (KNOWN_ALIASES —
    "Google" isn't a substring or suffix variant of "Alphabet Inc.", so no
    amount of normalization finds it without an explicit mapping), an exact
    match once corporate suffixes (Inc., Corp., REIT, ...) are stripped from
    both sides (so a plain "Apple" resolves straight to "Apple Inc." instead
    of colliding with unrelated companies that merely contain "apple", like
    "Apple Hospitality REIT, Inc."), and finally a unique substring match.
    Raises SecEdgarError if none or more than one company matches at
    whichever tier resolves it."""
    mapping = _load_ticker_map()
    key = company_or_ticker.strip()
    if key.upper() in mapping:
        return mapping[key.upper()]
    if key.lower() in mapping:
        return mapping[key.lower()]

    alias_ticker = KNOWN_ALIASES.get(key.lower())
    if alias_ticker and alias_ticker in mapping:
        return mapping[alias_ticker]

    normalized_key = _normalize_company_name(key)
    normalized_matches = _load_normalized_name_map().get(normalized_key, set())
    if len(normalized_matches) == 1:
        return next(iter(normalized_matches))
    if len(normalized_matches) > 1:
        raise SecEdgarError(
            f"\"{company_or_ticker}\" matches more than one SEC-registered company; try the exact name or ticker.",
            code="ambiguous_company",
        )

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
    empty-result handling takes over from there.

    A metric can have more than one candidate XBRL concept tag (see
    CURATED_METRICS) when filers have migrated tags over time (e.g. the ASC
    606 revenue-recognition change). Every candidate that has data is
    merged into one deduplicated, fiscal-year-sorted series, rather than
    stopping at the first candidate and risking a false "no data" — or a
    truncated history — if that particular company happens to report under
    a different candidate tag."""
    if metric not in CURATED_METRICS:
        raise SecEdgarError(
            f"\"{metric}\" isn't one of the curated SEC metrics Atlas knows how to fetch: "
            f"{', '.join(sorted(CURATED_METRICS))}.",
            code="unknown_metric",
        )
    taxonomy, concepts, unit = CURATED_METRICS[metric]
    cik = resolve_cik(company)
    facts = _http_get_json(COMPANY_FACTS_URL.format(cik=cik))
    entity_name = facts.get("entityName", company)
    taxonomy_facts = facts.get("facts", {}).get(taxonomy, {})

    seen_keys = set()
    rows = []
    contributing_concepts = []
    for concept in concepts:
        concept_data = taxonomy_facts.get(concept)
        if not concept_data:
            continue
        values = concept_data.get("units", {}).get(unit, [])
        if fiscal_year is not None:
            values = [v for v in values if v.get("fy") == fiscal_year]
        if not values:
            continue
        contributing_concepts.append(concept)
        for v in values:
            dedupe_key = (v.get("end"), v.get("start"), v.get("fy"), v.get("fp"), v.get("form"), v.get("val"))
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            rows.append(
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
            )

    if not rows:
        # Real company, but none of this metric's candidate tags have a
        # reported value for it/this year. Not an error — empty rows let
        # the pipeline's own "empty_result" path handle it gracefully.
        # Cite the primary (first-listed) candidate tag since none of them
        # actually contributed data.
        return {"rows": [], "cik": cik, "entity_name": entity_name, "concept": f"{taxonomy}:{concepts[0]}"}

    rows.sort(key=lambda r: (r.get("fiscal_year") or 0, r.get("period_end") or ""))
    concept_label = f"{taxonomy}:" + "|".join(contributing_concepts)
    return {"rows": rows, "cik": cik, "entity_name": entity_name, "concept": concept_label}
