---
id: ac.sec_filer_screen
type: AttestedComputation
pack: finance
title: Screen SEC filers by SIC code — which companies reported a figure below or above a threshold
description: >
  From the SEC filings mirror, the list of filers in one SIC code whose
  reported value of a curated metric (net income, revenue, total assets,
  deposits…) was below or above a threshold in any quarter — or in the
  fiscal year — of a given year. The screening question, done one reviewed
  way: "which state commercial banks (SIC 6022) reported a quarterly net
  loss in 2019", "which SIC 6021 filers had negative net income", "which
  filers in SIC 7372 reported revenue above $1B in 2018".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [sec, screening, sic-code, filers, net-loss, quarterly, 10-q, 10-k, banks, finance]
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: sec_quarterly_financials
  table: numbers
sources:
  - kind: bigquery
    project: bigquery-public-data
    dataset: sec_quarterly_financials
    table: numbers
  - kind: bigquery
    project: bigquery-public-data
    dataset: sec_quarterly_financials
    table: submission
cost_profile:
  expected_bytes: 20000000000
  cap_bytes: 32212254720   # 30 GB: the `numbers` table scans ~21 GB regardless of filters
citation_template: "SEC Financial Statement Data Sets (BigQuery mirror, filings to 2020-12-31): filers by SIC code from `submission`, non-dimensional facts from `numbers`; quarterly = number_of_quarters 1, annual = 4; tag per backend/accessor/xbrl_metrics.py."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: sic_code
        type: STRING
        required: true
        description: >
          Four-digit SIC code as a string, e.g. "6022" (state commercial banks), "6021"
          (national commercial banks), "6029", "6035", "7372". Required — a question
          without a SIC code or industry group does not fit this template.
      - name: fiscal_year
        type: INT64
        required: true
        description: Four-digit year, e.g. 2019 (the mirror ends with fiscal 2019).
      - name: metric
        type: STRING
        required: false
        default: net_income
        description: One curated metric key — net_income (default), revenue, total_assets, deposits, loans, stockholders_equity.
      - name: threshold
        type: FLOAT64
        required: false
        default: 0
        description: The value to compare against, in USD. Default 0 (a "net loss" is net_income below 0).
      - name: direction
        type: STRING
        required: false
        default: below
        description: '"below" (default; "loss", "negative", "under") or "above" ("exceeded", "over", "more than").'
      - name: grain
        type: STRING
        required: false
        default: quarter
        description: '"quarter" (default; any quarter of the year, from 10-Q/10-K quarterly facts) or "year" (the fiscal-year figure).'
    sql: |
      WITH metric_tags AS (
        SELECT tag, ord FROM UNNEST([
          STRUCT('NetIncomeLoss' AS tag, 1 AS ord, 'net_income' AS metric),
          STRUCT('Revenues', 1, 'revenue'),
          STRUCT('RevenueFromContractWithCustomerExcludingAssessedTax', 2, 'revenue'),
          STRUCT('RevenueFromContractWithCustomerIncludingAssessedTax', 3, 'revenue'),
          STRUCT('Assets', 1, 'total_assets'),
          STRUCT('Deposits', 1, 'deposits'),
          STRUCT('LoansAndLeasesReceivableNetReportedAmount', 1, 'loans'),
          STRUCT('StockholdersEquity', 1, 'stockholders_equity')
        ]) WHERE metric = @metric
      ),
      filings AS (
        SELECT submission_number, company_name, central_index_key, fiscal_year, fiscal_period_focus, form
        FROM `bigquery-public-data.sec_quarterly_financials.submission`
        WHERE sic = @sic_code AND fiscal_year = @fiscal_year AND form IN ('10-Q', '10-K', '10-K/A', '10-Q/A')
      ),
      facts AS (
        SELECT f.company_name, f.central_index_key, f.fiscal_period_focus, f.form,
               n.period_end_date, n.number_of_quarters, n.value, m.ord
        FROM `bigquery-public-data.sec_quarterly_financials.numbers` n
        JOIN filings f ON n.submission_number = f.submission_number
        JOIN metric_tags m ON n.measure_tag = m.tag
        WHERE n.units = 'USD' AND n.num_dimensions = 0 AND (n.coregistrant IS NULL OR n.coregistrant = '')
          AND n.number_of_quarters = IF(@grain = 'year', 4, IF(@metric IN ('total_assets','deposits','loans','stockholders_equity'), 0, 1))
          AND CAST(FLOOR(n.period_end_date / 10000) AS INT64) = @fiscal_year
      ),
      dedup AS (
        SELECT * FROM facts
        QUALIFY ROW_NUMBER() OVER (PARTITION BY central_index_key, period_end_date ORDER BY ord, form) = 1
      )
      SELECT
        company_name AS filer,
        central_index_key AS cik,
        COUNT(*) AS periods_matching,
        MIN(value) AS lowest_value,
        MAX(value) AS highest_value,
        STRING_AGG(FORMAT_DATE('%Y-%m-%d', PARSE_DATE('%Y%m%d', CAST(period_end_date AS STRING))), ', ' ORDER BY period_end_date) AS periods
      FROM dedup
      WHERE IF(@direction = 'above', value > @threshold, value < @threshold)
      GROUP BY filer, cik
      ORDER BY lowest_value
      LIMIT 200
---

## Why this is a template

"Which filers in industry X reported a loss" is the canonical screening
question and the easiest to get subtly wrong in ad-hoc SQL: quarterly versus
annual facts (`number_of_quarters` 1 vs 4), balance-sheet instants (0),
dimensional segment facts that duplicate the consolidated line, restated
periods across 10-Q and 10-K, and the yyyymmdd integer dates. This template
fixes all of that; the planner only binds the SIC code, year, metric,
threshold and direction.

## Limits

The mirror ends with filings dated 2020-12-31, so `fiscal_year` 2019 is the
last complete year. Scanning `numbers` costs ~21 GB (about $0.13) however
tight the filters, because the table is neither partitioned nor clustered.
