---
id: ac.cfpb_complaint_rate_per_deposits
type: AttestedComputation
pack: finance
title: Complaints per $1B of deposits, largest banks
description: >
  For the N largest active FDIC-insured banks by deposits, the number of
  CFPB complaints received in a calendar year divided by total deposits in
  billions of dollars — the size-normalised complaint rate used to compare
  banks fairly. Use for "complaints per billion of deposits", "which large
  bank has the most complaints relative to its size".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [cfpb, fdic, complaint-rate, deposits, normalised, ranking, banks, finance]
sources:
  - kind: bigquery
    project: bigquery-public-data
    dataset: cfpb_complaints
    table: complaint_database
  - kind: bigquery
    project: bigquery-public-data
    dataset: fdic_banks
    table: institutions
  - kind: bigquery
    project: atlas-ard-okf
    dataset: finance_pack
    table: entity_xref
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: cfpb_complaints
  table: complaint_database
cost_profile:
  expected_bytes: 1500000000
  cap_bytes: 21474836480
citation_template: "CFPB complaints received in the year ÷ FDIC total deposits (thousands of USD × 1,000) per $1B; peer set = top N active FDIC banks by deposits via the Atlas entity crosswalk."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: year
        type: INT64
        required: true
        description: Calendar year of date_received, e.g. 2025.
      - name: top_n
        type: INT64
        required: false
        default: 10
        description: How many of the largest banks by deposits to rank. Default 10.
    sql: |
      WITH peers AS (
        SELECT x.display_name, x.cfpb_company_name, i.total_deposits * 1000 AS deposits_usd
        FROM `bigquery-public-data.fdic_banks.institutions` i
        JOIN `atlas-ard-okf.finance_pack.entity_xref` x ON x.fdic_cert = i.fdic_certificate_number
        WHERE i.active
        QUALIFY ROW_NUMBER() OVER (ORDER BY i.total_deposits DESC) <= @top_n
      ),
      counts AS (
        SELECT company_name, COUNT(*) AS complaints
        FROM `bigquery-public-data.cfpb_complaints.complaint_database`
        WHERE EXTRACT(YEAR FROM date_received) = @year
        GROUP BY company_name
      )
      SELECT
        p.display_name AS bank,
        COALESCE(c.complaints, 0) AS complaints,
        ROUND(p.deposits_usd / 1e9, 1) AS deposits_bn,
        ROUND(COALESCE(c.complaints, 0) / (p.deposits_usd / 1e9), 2) AS complaints_per_bn_deposits
      FROM peers p LEFT JOIN counts c ON c.company_name = p.cfpb_company_name
      ORDER BY complaints_per_bn_deposits DESC
---

## Why this is a template

Raw complaint counts reward small banks; the normalised rate is the fair
comparison, and the denominator (FDIC total deposits, reported in thousands
of USD) is exactly the kind of unit detail an ad-hoc query gets wrong by a
factor of a thousand. Deposits are the current FDIC figure, not the
year-end of `@year` — the answer says so via the citation template.
