---
id: ac.sec_edgar_company_metric_by_year
type: AttestedComputation
title: SEC-reported company financial metric, by year
description: >
  A public US company's reported value for one curated financial metric
  (revenue, net income, total assets, and similar) from its SEC filings, for
  a given fiscal year or across all years on file. Backed by SEC EDGAR's
  free company-facts API — no model-drafted query, and no model-chosen XBRL
  tag; both the fetch and the metric-to-tag mapping are curated.
trust: human-reviewed
tags: [sec, edgar, xbrl, company, financials, revenue, net-income]
source:
  kind: sec_edgar
  api: company_facts
  docs: https://www.sec.gov/os/webmaster-faq#developers
computation:
  runtime:
    executor: sec_edgar
    attester: human-reviewed
    parameters:
      - name: company
        type: STRING
        required: true
        description: >
          Company name or stock ticker as named in the question, e.g. "Apple"
          or "AAPL". Resolved to a SEC CIK via SEC's own ticker/name list —
          never guessed.
      - name: metric
        type: STRING
        required: true
        description: >
          One of a fixed, curated set of plain-language metric keys: revenue,
          net_income, total_assets, total_liabilities, operating_income,
          cash_and_equivalents, eps_diluted, shares_outstanding. Never a raw
          XBRL tag — pick the closest curated key to what the question asks.
      - name: fiscal_year
        type: INTEGER
        required: false
        description: >
          Four-digit fiscal year, e.g. 2023. Only set this when the question
          names a specific year; omit it to return every year SEC has on
          file for that metric.
---

## Why this exists as a curated mapping, not free-form XBRL

A company's SEC filings tag thousands of XBRL concepts, and the exact tag
for "revenue" or "net income" varies enough across companies and years
(`Revenues` vs. `RevenueFromContractWithCustomerExcludingAssessedTax`, for
example) that letting a model choose a raw tag string risks a silent
mismatch — a plausible-looking tag that isn't the one the company actually
used. Instead, `CURATED_METRICS` in
`backend/accessor/sec_edgar_accessor.py` is a small, human-reviewed mapping
from plain-language metric names to the specific, well-established
US-GAAP/DEI tag each one resolves to. The planner's job is only to recognize
which curated metric key the question is asking about and extract
`company` / optional `fiscal_year` — never to invent a tag or a URL.

This mirrors the same trust pattern as
`covid19_case_rate_by_county_year.md`'s hand-written SQL template: the model
extracts parameter *values*, a person has already reviewed the underlying
lookup.

## Coverage and limits

- Only companies that file XBRL-tagged financials with the SEC (effectively:
  all US public companies) are covered — no private companies, no non-US
  filers without a US listing.
- Only the 8 curated metrics above are fetchable today. A real company that
  simply never reported one of these tags (e.g. a bank without a standard
  `OperatingIncomeLoss` line) correctly returns "no data" rather than a
  wrong number.
- `company` resolution matches on exact ticker, exact registered name, or a
  unique substring of the name; an ambiguous or unmatched name is reported
  back honestly rather than guessed.
- No local currency conversion — figures are exactly as reported (nearly
  always USD for a US-listed filer).

## Trust note

`trust: human-reviewed` — this is the top tier in the OKF provenance model,
same as the SQL-template Attested Computations. Citations synthesized from
this source are labeled accordingly, with the SEC CIK and filing form/date
carried through so a reader can trace a figure back to the original filing.
