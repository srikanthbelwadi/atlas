---
id: bq.bigquery-public-data.sec_quarterly_financials.numbers#finance
type: Table
pack: finance
title: SEC financial statement data sets (XBRL numbers and submissions)
description: >
  BigQuery dataset `bigquery-public-data.sec_quarterly_financials`, a mirror
  of the SEC's Financial Statement Data Sets: every numeric XBRL fact from
  10-K and 10-Q filings (`numbers`), one row per filing (`submission`), the
  tag dictionary (`measure_tag`) and SIC codes. In the finance pack this
  stands in for a fundamentals data warehouse or the output of the
  financial close. The schema below is the SEC's documented layout and is
  confirmed by the Atlas crawler before any template is run against it.
  Columns (numbers): adsh (STRING, accession), tag (STRING), version
  (STRING), coreg (STRING), ddate (DATE, period end), qtrs (INTEGER,
  duration in quarters; 0 = instant), uom (STRING), value (FLOAT),
  footnote (STRING). Columns (submission): adsh, cik (INTEGER), name
  (STRING), sic (STRING), fy (INTEGER), fp (STRING: FY, Q1..Q3), form
  (STRING: 10-K, 10-Q, ...), period (DATE), filed (DATE).
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2026-12-01
lifecycle: draft
version: "0.1"
tags: [sec, xbrl, filings, 10-k, fundamentals, financial-statements, finance]
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: sec_quarterly_financials
  table: numbers
  refresh: quarterly (SEC), mirror cadence unverified
  stands_in_for: fundamentals warehouse / financial-close output
---

## Status

`lifecycle: draft` until the finance-pack crawl confirms table and column
names (phase 0.3 of the finance plan). Discovery still lists it so the
planner knows the source exists, but `ac.sec_fact_from_bq` — the only path
that runs SQL against it — is what gets promoted to `active` once the crawl
log is in.

## Notes for query planning

- Never draft ad-hoc SQL over `numbers`: the annual-fact selection rule
  (10-K, `qtrs = 4` for flows or `0` for instants, latest `filed` per fiscal
  year, `uom = 'USD'`) is easy to get subtly wrong and is encoded once in
  `ac.sec_fact_from_bq`.
- `fy` is the filer's fiscal year and `ddate` its period end; a 10-K also
  carries prior-year comparatives under the same `adsh`.
