---
id: bq.bigquery-public-data.fdic_banks.institutions#finance
type: Table
pack: finance
title: FDIC-insured institutions (BankFind)
description: >
  BigQuery table `bigquery-public-data.fdic_banks.institutions`. One row per
  FDIC-insured institution, current and historical, with location, status
  and headline financials from the most recent call report: total assets,
  total deposits, equity capital, net income, return on assets and return
  on equity. In the finance pack this stands in for a bank's entity master
  and its peer-benchmarking reference table.
  Columns (subset of 151):
    - fdic_certificate_number (STRING)
    - institution_name (STRING)
    - city (STRING)
    - state (STRING)
    - state_name (STRING)
    - active (BOOLEAN)
    - established_date (DATE)
    - total_assets (INTEGER, thousands of USD)
    - total_deposits (INTEGER, thousands of USD)
    - equity_capital (INTEGER, thousands of USD)
    - net_income (INTEGER, thousands of USD)
    - return_on_assets (FLOAT, percent, year-to-date annualised)
    - return_on_equity (FLOAT, percent, year-to-date annualised)
    - roa_quarterly (FLOAT, percent)
    - roe_quarterly (FLOAT, percent)
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [fdic, banks, institutions, peer-benchmark, roa, roe, deposits, assets, finance]
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: fdic_banks
  table: institutions
  alias_dataset: fdic
  refresh: daily (Google public-datasets-pipelines)
  stands_in_for: entity master / legal-hierarchy reference and peer-group financials
---

## What's in this table

Every institution the FDIC has ever insured. Filter `active = TRUE` for the
current population (about 4,500 banks). Dollar columns are in **thousands
of USD** as in the FDIC source (`total_deposits * 1000` is dollars).

`return_on_assets` and `return_on_equity` are the FDIC's regulatory
definitions (annualised year-to-date net income over average assets /
average equity from quarterly call reports). They are a **different
definition** from a ratio computed from XBRL 10-K facts; templates say
which one they use.

## Notes for query planning

- Peer sets are defined by size: rank active institutions by
  `total_deposits` or `total_assets`.
- Institution names are legal names (`Wells Fargo Bank, National
  Association`); join to CFPB or SEC identities through the entity crosswalk
  (`atlas-ard-okf.finance_pack.entity_xref`), not by name.
- The dataset may be registered as `fdic` rather than `fdic_banks`; the
  crawler records which name resolved, and templates use the resolved name.
