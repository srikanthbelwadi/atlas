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
  financial close. Column names below are as crawled (they differ from the
  SEC's own file layout).
  Columns (numbers): adsh (STRING, accession), tag (STRING), version
  (STRING), coreg (STRING), ddate (DATE, period end), qtrs (INTEGER,
  duration in quarters; 0 = instant), uom (STRING), value (FLOAT),
  footnote (STRING). Columns (submission): adsh, cik (INTEGER), name
  (STRING), sic (STRING), fy (INTEGER), fp (STRING: FY, Q1..Q3), form
  (STRING: 10-K, 10-Q, ...), period (DATE), filed (DATE).
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [sec, xbrl, filings, 10-k, fundamentals, financial-statements, finance]
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: sec_quarterly_financials
  table: numbers
  refresh: quarterly (SEC), mirror cadence unverified
  stands_in_for: fundamentals warehouse / financial-close output
---

## Notes for query planning

- Prefer `ac.sec_fact_from_bq` for any single-company annual figure: the
  selection rule (10-K, `number_of_quarters = 4` for flows or `0` for
  instants, `num_dimensions = 0`, latest `date_filed` per fiscal year) is
  easy to get subtly wrong.
- Ad-hoc SQL is acceptable for screening questions (e.g. which filers in a
  SIC code reported a loss): join `numbers` to `submission` on
  `submission_number`, filter `measure_tag`, and always filter
  `fiscal_year` / `period_end_date` to keep the scan under the cap; dates
  are yyyymmdd integers, so `period_end_date BETWEEN 20250101 AND 20251231`.
- `fiscal_year` is the filing's fiscal year; a 10-K also carries prior-year
  comparatives under the same `submission_number`.
