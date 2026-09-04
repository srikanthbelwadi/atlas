---
id: ac.hc_default_rate_by_segment
type: AttestedComputation
pack: finance
visibility: private
access:
  entitlement: finance.internal
title: Internal loan book — default rate by segment (private)
description: >
  PRIVATE. Default rate (share of applications with payment difficulties)
  in the bank's own loan book, broken down by one segment: contract_type,
  income_band, income_type, education, occupation, housing_type,
  family_status, region_rating, gender or age_band. Reports applicants,
  defaults and the rate with the base rate for comparison; segments below a
  minimum applicant count are folded into "other (small segments)". Use for
  "our default rate by …", "which segment of our book defaults most",
  "portfolio risk by income / education / channel", "internal credit risk".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-04
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [internal, private, credit, default-rate, segment, portfolio, loan-book, risk-mart, finance]
sources:
  - kind: bigquery
    project: atlas-ard-okf
    dataset: finance_demo
    table: loan_applications
source:
  kind: bigquery
  project: atlas-ard-okf
  dataset: finance_demo
  table: loan_applications
cost_profile:
  expected_bytes: 30000000
  cap_bytes: 1073741824
citation_template: "Default rate = applications with default_flag = 1 ÷ all applications in the segment, from the bank's internal loan_applications table (private; Home Credit shape). Segments under @min_applicants applicants are grouped as 'other'."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: segment
        type: STRING
        required: true
        description: >
          Which segment to break the rate down by. One of: contract_type,
          income_band, income_type, education, occupation, housing_type,
          family_status, region_rating, gender, age_band. "Channel" or
          "product" in a question means contract_type; "income" means
          income_band; "age" means age_band.
      - name: min_applicants
        type: INT64
        required: false
        default: 500
        description: Segments with fewer applicants than this are folded into "other (small segments)". Default 500.
    sql: |
      WITH base AS (
        SELECT
          CASE @segment
            WHEN 'contract_type'  THEN contract_type
            WHEN 'income_band'    THEN income_band
            WHEN 'income_type'    THEN income_type
            WHEN 'education'      THEN education
            WHEN 'occupation'     THEN COALESCE(NULLIF(occupation, ''), '(not stated)')
            WHEN 'housing_type'   THEN housing_type
            WHEN 'family_status'  THEN family_status
            WHEN 'region_rating'  THEN CONCAT('region rating ', CAST(region_rating AS STRING))
            WHEN 'gender'         THEN gender
            WHEN 'age_band'       THEN CASE WHEN age_years < 30 THEN '1: under 30' WHEN age_years < 40 THEN '2: 30-39'
                                            WHEN age_years < 50 THEN '3: 40-49' WHEN age_years < 60 THEN '4: 50-59' ELSE '5: 60+' END
            ELSE ERROR(CONCAT('unknown segment: ', @segment))
          END AS segment_value,
          default_flag
        FROM `atlas-ard-okf.finance_demo.loan_applications`
      ),
      sized AS (
        SELECT segment_value, COUNT(*) AS applicants FROM base GROUP BY segment_value
      ),
      folded AS (
        SELECT IF(s.applicants >= @min_applicants, b.segment_value, 'other (small segments)') AS segment_value, b.default_flag
        FROM base b JOIN sized s USING (segment_value)
      )
      SELECT
        @segment AS segment,
        segment_value,
        COUNT(*) AS applicants,
        SUM(default_flag) AS defaults,
        ROUND(100 * SUM(default_flag) / COUNT(*), 2) AS default_rate_pct,
        ROUND(100 * (SELECT SUM(default_flag) / COUNT(*) FROM base), 2) AS book_default_rate_pct,
        ROUND(100 * SUM(default_flag) / COUNT(*) - 100 * (SELECT SUM(default_flag) / COUNT(*) FROM base), 2) AS vs_book_pts
      FROM folded
      GROUP BY segment_value
      ORDER BY default_rate_pct DESC
---

## Why this is a template

"Default rate by X" is the question every portfolio review starts with,
and the two things an ad-hoc query gets wrong are the denominator (all
applications in the segment, not all applications) and small-segment
noise (an occupation with 40 applicants and 9 defaults looks alarming and
means nothing). The template fixes both and reports the book-wide rate on
every row so the segment is always read against it.

## Access

This template reads a private table. Discovery only offers it to users
holding the `finance.internal` entitlement; the receipt records
`visibility: private` and the entitlement that unlocked it.
