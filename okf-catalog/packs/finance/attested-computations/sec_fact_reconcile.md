---
id: ac.sec_fact_reconcile
type: AttestedComputation
pack: finance
title: Reconcile one reported figure across the EDGAR API and the SEC bulk data set
description: >
  Fetches the same curated metric for one company and fiscal year from two
  independent copies of the filing data — the SEC EDGAR company-facts API
  and the SEC Financial Statement Data Sets in BigQuery — and reports each
  value with its accession number plus whether they agree within 0.5%.
  The fact-check primitive. Use for "does the SEC data set agree with
  EDGAR", "verify X's net income for 2025", "what did X report for Y in
  fiscal 2025 (with sources)".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [sec, reconcile, fact-check, two-sources, edgar, bulk, 10-k, finance]
source:
  kind: composite
sources:
  - kind: sec_edgar_annual
    api: company_facts
  - kind: bigquery
    project: bigquery-public-data
    dataset: sec_quarterly_financials
    table: numbers
citation_template: "Two independent SEC sources (EDGAR company-facts API; Financial Statement Data Sets in BigQuery), same 10-K selection rule, same curated tag map; agreement within 0.5%."
computation:
  runtime:
    executor: composite
    attester: human-reviewed
    combine: reconcile
    value_field: value
    tolerance_pct: 0.5
    parameters:
      - name: company
        type: STRING
        required: true
        description: Company name or ticker as written in the question.
      - name: metric
        type: STRING
        required: true
        description: One curated metric key, e.g. net_income, revenue, total_assets, deposits.
      - name: fiscal_year
        type: INT64
        required: true
        description: Four-digit fiscal year, e.g. 2025.
    steps:
      - name: sec_edgar_api
        computation: ac.sec_fact_annual_api
        params: {company: company, metric: metric, fiscal_year: fiscal_year}
        note: EDGAR company-facts API, 10-K/FY selection
      - name: sec_bulk_bq
        computation: ac.sec_fact_from_bq
        params: {company: company, metric: metric, fiscal_year: fiscal_year}
        note: SEC Financial Statement Data Sets in BigQuery, same rule
---

## Why a composite

The point of use case B is that a figure reaching a research note or a
regulator can be traced to a filing *and* checked against an independent
copy. Each step runs through its own executor and guardrails and shows up
as its own entry in the walkthrough; the combine step adds one
`reconciliation` row with `delta_pct` and `agreement` (`agree`, `differ`,
`single source`, `no data`). A missing source is a visible finding, not a
silent fallback.
