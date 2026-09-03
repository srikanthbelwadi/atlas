---
id: ac.sec_fact_from_bq
type: AttestedComputation
pack: finance
title: One annual reported figure from the SEC bulk data set (BigQuery)
description: >
  The same single curated metric for one company and one fiscal year, but
  taken from the SEC Financial Statement Data Sets mirrored in BigQuery
  (sec_quarterly_financials) — an independent copy of the filing data,
  selected with the same 10-K rule as the API template so the two can be
  reconciled. Use when a question asks for a company's figure in one
  fiscal year "from the SEC data set" or "from the bulk data".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2026-12-01
lifecycle: draft
version: "0.1"
tags: [sec, xbrl, 10-k, annual, fiscal-year, bulk, bigquery, finance]
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
  - kind: bigquery
    project: atlas-ard-okf
    dataset: finance_pack
    table: entity_xref
cost_profile:
  expected_bytes: 8000000000
  cap_bytes: 21474836480
citation_template: "SEC Financial Statement Data Sets (BigQuery mirror); 10-K fact for the fiscal year: qtrs = 4 for flows / 0 for balances, latest filed, uom USD; tag per backend/accessor/xbrl_metrics.py."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: company
        type: STRING
        required: true
        description: Company name or ticker as written; resolved to a CIK through the entity crosswalk.
      - name: metric
        type: STRING
        required: true
        description: One curated metric key, e.g. net_income, revenue, total_assets.
      - name: fiscal_year
        type: INT64
        required: true
        description: Four-digit fiscal year, e.g. 2025.
    # The tag list per metric is the one in backend/accessor/xbrl_metrics.py;
    # tests/test_finance_catalog.py checks this SQL's metric_tags CTE stays in
    # sync with that module.
    sql: |
      WITH metric_tags AS (
        SELECT metric, tag, period_kind, ord FROM UNNEST([
          STRUCT('revenue' AS metric, 'Revenues' AS tag, 'duration' AS period_kind, 1 AS ord),
          STRUCT('revenue', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'duration', 2),
          STRUCT('revenue', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'duration', 3),
          STRUCT('net_income', 'NetIncomeLoss', 'duration', 1),
          STRUCT('operating_income', 'OperatingIncomeLoss', 'duration', 1),
          STRUCT('interest_expense', 'InterestExpense', 'duration', 1),
          STRUCT('income_tax_expense', 'IncomeTaxExpenseBenefit', 'duration', 1),
          STRUCT('net_interest_income', 'InterestIncomeExpenseNet', 'duration', 1),
          STRUCT('net_interest_income', 'InterestIncomeExpenseAfterProvisionForLoanLoss', 'duration', 2),
          STRUCT('provision_for_credit_losses', 'ProvisionForLoanLeaseAndOtherLosses', 'duration', 1),
          STRUCT('provision_for_credit_losses', 'ProvisionForLoanLossesExpensed', 'duration', 2),
          STRUCT('provision_for_credit_losses', 'ProvisionForCreditLosses', 'duration', 3),
          STRUCT('noninterest_expense', 'NoninterestExpense', 'duration', 1),
          STRUCT('noninterest_income', 'NoninterestIncome', 'duration', 1),
          STRUCT('eps_diluted', 'EarningsPerShareDiluted', 'duration', 1),
          STRUCT('dividends_declared_per_share', 'CommonStockDividendsPerShareDeclared', 'duration', 1),
          STRUCT('operating_cash_flow', 'NetCashProvidedByUsedInOperatingActivities', 'duration', 1),
          STRUCT('capital_expenditures', 'PaymentsToAcquirePropertyPlantAndEquipment', 'duration', 1),
          STRUCT('total_assets', 'Assets', 'instant', 1),
          STRUCT('total_liabilities', 'Liabilities', 'instant', 1),
          STRUCT('stockholders_equity', 'StockholdersEquity', 'instant', 1),
          STRUCT('stockholders_equity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', 'instant', 2),
          STRUCT('cash_and_equivalents', 'CashAndCashEquivalentsAtCarryingValue', 'instant', 1),
          STRUCT('cash_and_equivalents', 'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents', 'instant', 2),
          STRUCT('deposits', 'Deposits', 'instant', 1),
          STRUCT('loans', 'LoansAndLeasesReceivableNetReportedAmount', 'instant', 1),
          STRUCT('loans', 'NotesReceivableNet', 'instant', 2),
          STRUCT('loans', 'FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss', 'instant', 3),
          STRUCT('long_term_debt', 'LongTermDebt', 'instant', 1),
          STRUCT('long_term_debt', 'LongTermDebtNoncurrent', 'instant', 2),
          STRUCT('shares_outstanding', 'EntityCommonStockSharesOutstanding', 'instant', 1)
        ]) WHERE metric = @metric
      ),
      target AS (
        SELECT cik, display_name FROM `atlas-ard-okf.finance_pack.entity_xref`
        WHERE cik IS NOT NULL AND (
          LOWER(display_name) = LOWER(@company)
          OR LOWER(ticker) = LOWER(@company)
          OR EXISTS (SELECT 1 FROM UNNEST(aliases) a WHERE LOWER(a) = LOWER(@company))
        )
        LIMIT 1
      ),
      filings AS (
        SELECT s.adsh, s.name, s.fy, s.filed, s.form, s.period
        FROM `bigquery-public-data.sec_quarterly_financials.submission` s
        JOIN target t ON s.cik = t.cik
        WHERE s.fy = @fiscal_year AND s.fp = 'FY' AND s.form IN ('10-K', '10-K/A')
      ),
      facts AS (
        SELECT f.adsh, f.name, f.fy, f.filed, f.form, n.tag, n.ddate, n.qtrs, n.uom, n.value, m.ord
        FROM `bigquery-public-data.sec_quarterly_financials.numbers` n
        JOIN filings f ON n.adsh = f.adsh
        JOIN metric_tags m ON n.tag = m.tag
        WHERE n.uom IN ('USD', 'shares', 'USD/shares')
          AND (n.coreg IS NULL OR n.coreg = '')
          AND ((m.period_kind = 'duration' AND n.qtrs = 4) OR (m.period_kind = 'instant' AND n.qtrs = 0))
          AND n.ddate = f.period
      )
      SELECT
        'sec_bulk_bq' AS source,
        name AS entity_name,
        fy AS fiscal_year,
        tag AS concept,
        value,
        uom AS unit,
        CAST(ddate AS STRING) AS period_end,
        form,
        CAST(filed AS STRING) AS filed,
        adsh AS accession
      FROM facts
      QUALIFY ROW_NUMBER() OVER (ORDER BY filed DESC, ord ASC) = 1
---

## Status

`lifecycle: draft`: the column names (`adsh, tag, ddate, qtrs, uom, value,
coreg` in `numbers`; `cik, name, fy, fp, form, period, filed` in
`submission`) follow the SEC's published Financial Statement Data Sets
layout and are confirmed against the crawled schema before this template
is promoted to `active`. Until then the planner prefers
`ac.sec_fact_annual_api` (the API path) for single-source questions.

## Selection rule (mirrors `ac.sec_fact_annual_api`)

10-K or 10-K/A with `fp = FY` for the fiscal year; the fact whose period
end equals the filing's own `period` (so a restated prior year is never
picked); `qtrs = 4` for income-statement/cash-flow flows and `qtrs = 0` for
balance-sheet instants; no co-registrant; latest `filed` first, then the
canonical tag (`ord`). One row or none.
