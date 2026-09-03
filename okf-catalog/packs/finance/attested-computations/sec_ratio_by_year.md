---
id: ac.sec_ratio_by_year
type: AttestedComputation
pack: finance
title: Curated financial ratio for one company and fiscal year (from 10-K facts)
description: >
  Return on assets, return on equity, net margin, efficiency ratio or
  equity-to-assets for one company and fiscal year, computed from 10-K
  facts with the numerator, denominator and averaging rule written down.
  This is the XBRL definition, NOT the FDIC regulatory definition (see
  ac.fdic_peer_ratios). Use for "X's ROA in 2025 from its filings", "net
  margin for Y", "efficiency ratio of Z".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [sec, ratio, roa, roe, net-margin, efficiency-ratio, 10-k, xbrl, finance]
source:
  kind: sec_ratio
  api: company_facts
citation_template: "Ratio computed from SEC EDGAR 10-K facts; numerator/denominator tags and averaging rule per backend/accessor/xbrl_metrics.py CURATED_RATIOS — not the FDIC regulatory definition."
computation:
  runtime:
    executor: sec_ratio
    attester: human-reviewed
    parameters:
      - name: company
        type: STRING
        required: true
        description: Company name or ticker as written.
      - name: ratio
        type: STRING
        required: true
        description: One of roa, roe, net_margin, efficiency_ratio, equity_to_assets.
      - name: fiscal_year
        type: INT64
        required: true
        description: Four-digit fiscal year.
---

## Definitions (from `xbrl_metrics.CURATED_RATIOS`)

- **roa** = net_income ÷ average(total_assets at this and the prior fiscal
  year end)
- **roe** = net_income ÷ average(stockholders_equity, same two year-ends)
- **net_margin** = net_income ÷ revenue
- **efficiency_ratio** = noninterest_expense ÷ (net_interest_income +
  noninterest_income) — banks only
- **equity_to_assets** = stockholders_equity ÷ total_assets at year end

Every input is fetched through `fetch_annual_fact` (the 10-K selection
rule), and the answer names the definition. If a prior-year balance is
missing the ratio falls back to the year-end balance and says so in
`averaging`.
