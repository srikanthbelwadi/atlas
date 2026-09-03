---
id: ac.cfpb_outcome_gap_by_tag
type: AttestedComputation
pack: finance
title: Complaint outcomes for tagged (older American / servicemember) vs untagged consumers
description: >
  For one year and optionally one product, the mix of company responses
  (relief, explanation only, other) for complaints tagged "Older American"
  or "Servicemember" compared with untagged complaints, with the relief
  gap in percentage points. The vulnerable-customer outcomes check. Use for
  "did older Americans get relief less often", "servicemember outcomes vs
  everyone else".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [cfpb, vulnerable-customers, older-american, servicemember, outcomes, relief, conduct, consumer-duty, finance]
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: cfpb_complaints
  table: complaint_database
cost_profile:
  expected_bytes: 2000000000
  cap_bytes: 21474836480
citation_template: "CFPB complaints by tag; relief = company_response_to_consumer containing 'relief'; tagged = tags containing the named tag; gap = tagged relief % − untagged relief %."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: tag
        type: STRING
        required: true
        description: Exactly "Older American" or "Servicemember" (the two CFPB tags). Map "older", "elderly", "seniors" to "Older American"; "military", "veterans" to "Servicemember".
      - name: year
        type: INT64
        required: true
        description: Calendar year of date_received, e.g. 2022 (latest full year in the BigQuery mirror).
      - name: product
        type: STRING
        required: false
        description: Optional CFPB product substring, e.g. "debt collection". Omit for all products.
    sql: |
      WITH base AS (
        SELECT
          IF(tags LIKE CONCAT('%', @tag, '%'), @tag, 'Untagged') AS cohort,
          CASE
            WHEN LOWER(company_response_to_consumer) LIKE '%relief%' THEN 'relief'
            WHEN company_response_to_consumer = 'Closed with explanation' THEN 'explanation_only'
            ELSE 'other'
          END AS outcome
        FROM `bigquery-public-data.cfpb_complaints.complaint_database`
        WHERE EXTRACT(YEAR FROM date_received) = @year
          AND (@product IS NULL OR LOWER(product) LIKE CONCAT('%', LOWER(@product), '%'))
      ),
      by_cohort AS (
        SELECT cohort, COUNT(*) AS complaints,
               ROUND(100 * COUNTIF(outcome = 'relief') / COUNT(*), 2) AS relief_pct,
               ROUND(100 * COUNTIF(outcome = 'explanation_only') / COUNT(*), 2) AS explanation_only_pct,
               ROUND(100 * COUNTIF(outcome = 'other') / COUNT(*), 2) AS other_pct
        FROM base GROUP BY cohort
      )
      SELECT cohort, complaints, relief_pct, explanation_only_pct, other_pct,
             ROUND(relief_pct - (SELECT relief_pct FROM by_cohort WHERE cohort = 'Untagged'), 2) AS relief_gap_pts
      FROM by_cohort
      ORDER BY cohort
---

## Why this is a template

This is a conduct question a regulator can ask verbatim, and the number
that reaches a board must be reproducible: the tag test, the outcome
classes and the gap arithmetic are fixed here. `relief_gap_pts` is the
tagged cohort's relief share minus the untagged cohort's, so a negative
number means tagged consumers got relief less often.
