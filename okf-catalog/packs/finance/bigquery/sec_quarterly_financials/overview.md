---
id: bq.bigquery-public-data.sec_quarterly_financials.numbers#finance
type: Table
pack: finance
title: SEC filings — every 10-K/10-Q figure by filer, SIC code and quarter (XBRL data sets)
description: >
  BigQuery dataset `bigquery-public-data.sec_quarterly_financials`, a mirror
  of the SEC's Financial Statement Data Sets: every numeric XBRL fact from
  every 10-K and 10-Q filing (`numbers`: net income, revenue, assets,
  deposits, loans… per filer per quarter or year), one row per filing with
  the filer's SIC code (`submission`), the tag dictionary (`measure_tag`)
  and SIC code names. The place to SCREEN filers: which companies or banks
  (SIC 6021 national commercial banks, 6022 state commercial banks, 6029
  other commercial banks, 6035/6036 savings institutions) reported a net
  loss, a fall in revenue, negative equity, or any figure above or below a
  threshold in a given quarter or fiscal year. In the finance pack this
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
tags: [sec, xbrl, filings, filers, 10-k, 10-q, quarterly, sic-code, screening, net-loss, net-income, fundamentals, financial-statements, banks, finance]
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: sec_quarterly_financials
  table: numbers
  refresh: quarterly (SEC), mirror cadence unverified
  stands_in_for: fundamentals warehouse / financial-close output
---

## Vintage

The mirror stops at filings dated 2020-12-31: fiscal 2019 is the last
complete 10-K year (325k filings, 59.6k 10-Ks in total). For anything later
use the SEC EDGAR API templates, which are current.

## Notes for query planning

- Prefer `ac.sec_fact_from_bq` for any single-company annual figure: the
  selection rule (10-K, `number_of_quarters = 4` for flows or `0` for
  instants, `num_dimensions = 0`, latest `date_filed` per fiscal year) is
  easy to get subtly wrong.
- Screening questions route to `ac.sec_filer_screen` (reviewed). If a screen falls outside its parameters, the ad-hoc recipe: `SELECT s.company_name, s.sic, n.period_end_date, n.value
  FROM numbers n JOIN submission s USING (submission_number) WHERE s.sic = '6022'
  AND n.measure_tag = 'NetIncomeLoss' AND n.number_of_quarters = 1 AND n.num_dimensions = 0
  AND n.period_end_date BETWEEN 20190101 AND 20191231 AND n.value < 0` — quarterly
  flows are `number_of_quarters = 1`, annual `4`.
- Ad-hoc SQL is acceptable for screening questions (e.g. which filers in a
  SIC code reported a loss): join `numbers` to `submission` on
  `submission_number`, filter `measure_tag`, and always filter
  `fiscal_year` / `period_end_date` to keep the scan under the cap; dates
  are yyyymmdd integers, so `period_end_date BETWEEN 20250101 AND 20251231`.
- `fiscal_year` is the filing's fiscal year; a 10-K also carries prior-year
  comparatives under the same `submission_number`.
