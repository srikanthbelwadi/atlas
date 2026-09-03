---
id: ac.sec_fact_annual_api
type: AttestedComputation
pack: finance
title: One annual reported figure from the 10-K (SEC EDGAR API)
description: >
  A single curated financial metric (revenue, net income, total assets,
  deposits, and so on) for one company and one fiscal year, selected from
  SEC EDGAR's company-facts API the way an analyst reads the 10-K: annual
  form, fiscal-period FY, the current year's period, latest filing wins.
  The API half of the two-source reconciliation. Use when a question asks
  for one company's figure in one fiscal year.
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [sec, edgar, xbrl, 10-k, annual, fiscal-year, fact, finance]
source:
  kind: sec_edgar_annual
  api: company_facts
  docs: https://www.sec.gov/os/webmaster-faq#developers
citation_template: "SEC EDGAR company-facts API; 10-K/FY fact for the fiscal year, latest period end, latest filing; tag per backend/accessor/xbrl_metrics.py."
computation:
  runtime:
    executor: sec_edgar_annual
    attester: human-reviewed
    parameters:
      - name: company
        type: STRING
        required: true
        description: Company name or ticker as written in the question, e.g. "JPMorgan" or "JPM".
      - name: metric
        type: STRING
        required: true
        description: One curated metric key (see ac.sec_edgar_company_metric_by_year), e.g. net_income, revenue, total_assets, deposits.
      - name: fiscal_year
        type: INT64
        required: true
        description: Four-digit fiscal year, e.g. 2025.
---

## Selection rule (mirrored in `ac.sec_fact_from_bq`)

1. Only `form` 10-K or 10-K/A with `fp = FY`.
2. `fy` in company-facts is the filing's fiscal year and a 10-K restates
   prior years under it, so keep the row with the latest `end`.
3. Duration metrics must span at least 300 days.
4. Among originals and amendments, the latest `filed` wins.

Implemented in `sec_edgar_accessor.fetch_annual_fact`, which returns empty
rows — never an error — when no annual fact is on file.
