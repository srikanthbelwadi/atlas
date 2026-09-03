---
id: ac.fdic_peer_ratios
type: AttestedComputation
pack: finance
title: FDIC-reported ratios for the largest banks (peer table)
description: >
  For the N largest active FDIC-insured banks by deposits or assets, the
  FDIC's own regulatory return on assets, return on equity, equity-to-
  assets, total assets, deposits and net income from the latest call
  report. The regulatory definition of ROA/ROE (annualised year-to-date
  over quarterly average balances), distinct from a ratio derived from
  XBRL 10-K facts. Use for "compare ROA of the five largest banks", "peer
  table of the biggest banks", "which large bank has the highest ROE".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [fdic, peer, roa, roe, banks, ranking, regulatory, finance]
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: fdic_banks
  table: institutions
cost_profile:
  expected_bytes: 50000000
  cap_bytes: 21474836480
citation_template: "FDIC BankFind institutions, latest call report; return_on_assets / return_on_equity are the FDIC regulatory definitions (annualised YTD over average balances); dollar columns converted from thousands."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: measure
        type: STRING
        required: false
        default: total_deposits
        description: Size measure for the peer set — "total_deposits" (default) or "total_assets".
      - name: top_n
        type: INT64
        required: false
        default: 10
        description: How many banks. Default 10.
    sql: |
      SELECT
        institution_name AS bank,
        fdic_certificate_number AS fdic_cert,
        state,
        ROUND(total_assets / 1e6, 1) AS total_assets_bn,
        ROUND(total_deposits / 1e6, 1) AS total_deposits_bn,
        ROUND(net_income / 1e6, 2) AS net_income_bn_ytd,
        return_on_assets AS roa_pct_fdic,
        return_on_equity AS roe_pct_fdic,
        ROUND(100 * equity_capital / total_assets, 2) AS equity_to_assets_pct
      FROM `bigquery-public-data.fdic_banks.institutions`
      WHERE active
      QUALIFY ROW_NUMBER() OVER (ORDER BY IF(@measure = 'total_assets', total_assets, total_deposits) DESC) <= @top_n
      ORDER BY IF(@measure = 'total_assets', total_assets, total_deposits) DESC
---

## Why this is a template

"ROA of the largest banks" has two defensible answers depending on the
definition; this template is the FDIC one and says so in every citation.
Dollar columns in the FDIC data are thousands of USD, hence the `/ 1e6`
to billions. `net_income` is year-to-date at the latest call report, not a
full year.
