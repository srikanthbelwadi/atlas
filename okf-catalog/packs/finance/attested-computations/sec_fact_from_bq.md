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
stale_after: 2027-03-01
lifecycle: active
version: "1"
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
  expected_bytes: 22800000000
  cap_bytes: 32212254720   # 30 GB: `numbers` scans ~21.2 GB (measured 2026-09-03); the server maximum is 40 GB
citation_template: "SEC Financial Statement Data Sets (BigQuery mirror); 10-K fact for the fiscal year: number_of_quarters = 4 for flows / 0 for balances, non-dimensional, latest filed; tag per backend/accessor/xbrl_metrics.py."
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
        SELECT s.submission_number, s.company_name, s.fiscal_year, s.date_filed, s.form, s.period
        FROM `bigquery-public-data.sec_quarterly_financials.submission` s
        JOIN target t ON s.central_index_key = t.cik
        WHERE s.fiscal_year = @fiscal_year AND s.fiscal_period_focus = 'FY' AND s.form IN ('10-K', '10-K/A')
      ),
      facts AS (
        SELECT f.submission_number, f.company_name, f.fiscal_year, f.date_filed, f.form,
               n.measure_tag, n.period_end_date, n.number_of_quarters, n.units, n.value, m.ord
        FROM `bigquery-public-data.sec_quarterly_financials.numbers` n
        JOIN filings f ON n.submission_number = f.submission_number
        JOIN metric_tags m ON n.measure_tag = m.tag
        WHERE n.units IN ('USD', 'shares', 'USD/shares')
          AND (n.coregistrant IS NULL OR n.coregistrant = '')
          AND n.num_dimensions = 0
          AND ((m.period_kind = 'duration' AND n.number_of_quarters = 4) OR (m.period_kind = 'instant' AND n.number_of_quarters = 0))
          AND n.period_end_date = f.period
      )
      SELECT
        'sec_bulk_bq' AS source,
        company_name AS entity_name,
        fiscal_year,
        measure_tag AS concept,
        value,
        units AS unit,
        FORMAT_DATE('%Y-%m-%d', PARSE_DATE('%Y%m%d', CAST(period_end_date AS STRING))) AS period_end,
        form,
        FORMAT_DATE('%Y-%m-%d', PARSE_DATE('%Y%m%d', CAST(date_filed AS STRING))) AS filed,
        submission_number AS accession
      FROM facts
      QUALIFY ROW_NUMBER() OVER (ORDER BY date_filed DESC, ord ASC) = 1
---

## Vintage and schema (confirmed 2026-09-03)

**The BigQuery mirror's last filings are dated 2020-12-31; its last complete
10-K year is fiscal 2019.** A question about a later fiscal year returns no
row here (honestly), and `ac.sec_fact_reconcile` then reports `single
source` with the EDGAR API's value — the API is current.


`submission`: `submission_number` (accession), `central_index_key`,
`company_name`, `form`, `fiscal_year`, `fiscal_period_focus` (FY, Q1…),
`period` and `date_filed` (integers, yyyymmdd). `numbers`:
`submission_number`, `measure_tag`, `period_end_date` (yyyymmdd integer),
`number_of_quarters` (0 = instant), `units`, `value`, `coregistrant`,
`num_dimensions`. These differ from the SEC's published column names,
which is exactly why this template was held in draft until the crawl.

## Selection rule (mirrors `ac.sec_fact_annual_api`)

10-K or 10-K/A with `fp = FY` for the fiscal year; the fact whose period
end equals the filing's own `period` (so a restated prior year is never
picked); `number_of_quarters = 4` for income-statement/cash-flow flows and
`0` for balance-sheet instants; no co-registrant and no dimensions
(consolidated total, not a segment); latest `date_filed` first, then the
canonical tag (`ord`). One row or none.
