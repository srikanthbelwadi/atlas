---
id: ac.hc_bureau_history_vs_default
type: AttestedComputation
pack: finance
visibility: private
access:
  entitlement: finance.internal
title: Internal loan book — bureau history vs default rate (private)
description: >
  PRIVATE. Does credit-bureau history predict default in the bank's own
  book? Buckets applicants by one bureau dimension — inquiries in the last
  year (0, 1, 2, 3-4, 5+), number of prior credits on file (none, 1-2,
  3-5, 6-9, 10+), or overdue history (any prior credit overdue vs none) —
  and reports the default rate per bucket against the book rate. Use for
  "more than three bureau inquiries", "prior credits and default",
  "applicants with overdue history", "does bureau history matter".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-04
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [internal, private, credit-bureau, inquiries, prior-credits, overdue, default-rate, risk-mart, finance]
sources:
  - kind: bigquery
    project: atlas-ard-okf
    dataset: finance_demo
    table: loan_applications
  - kind: bigquery
    project: atlas-ard-okf
    dataset: finance_demo
    table: bureau_credits
source:
  kind: bigquery
  project: atlas-ard-okf
  dataset: finance_demo
  table: loan_applications
cost_profile:
  expected_bytes: 80000000
  cap_bytes: 2147483648
citation_template: "Default rate per bucket = applications with default_flag = 1 ÷ applications in the bucket; buckets from the bank's internal loan_applications (inquiry counts) and bureau_credits (prior credits, overdue history) tables — private data."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: dimension
        type: STRING
        required: true
        description: >
          One of: inquiries_last_year (credit-bureau inquiries in the 12 months
          before application), prior_credits (number of prior credits the
          bureau reports), overdue_history (whether any prior credit was ever
          overdue). "Inquiries", "bureau pulls", "credit checks" mean
          inquiries_last_year; "prior loans", "existing credits" mean
          prior_credits; "overdue", "arrears elsewhere" mean overdue_history.
    sql: |
      WITH hist AS (
        SELECT application_id,
               COUNT(bureau_credit_id) AS prior_credits,
               COUNTIF(days_overdue > 0 OR amount_overdue > 0) AS overdue_credits
        FROM `atlas-ard-okf.finance_demo.bureau_credits`
        GROUP BY application_id
      ),
      base AS (
        SELECT
          a.default_flag,
          CASE @dimension
            WHEN 'inquiries_last_year' THEN
              CASE WHEN a.bureau_inquiries_last_year IS NULL THEN '(unknown)'
                   WHEN a.bureau_inquiries_last_year = 0 THEN '0 inquiries'
                   WHEN a.bureau_inquiries_last_year = 1 THEN '1 inquiry'
                   WHEN a.bureau_inquiries_last_year = 2 THEN '2 inquiries'
                   WHEN a.bureau_inquiries_last_year <= 4 THEN '3-4 inquiries'
                   ELSE '5+ inquiries' END
            WHEN 'prior_credits' THEN
              CASE WHEN COALESCE(h.prior_credits, 0) = 0 THEN '0: no bureau history'
                   WHEN h.prior_credits <= 2 THEN '1: 1-2 prior credits'
                   WHEN h.prior_credits <= 5 THEN '2: 3-5 prior credits'
                   WHEN h.prior_credits <= 9 THEN '3: 6-9 prior credits'
                   ELSE '4: 10+ prior credits' END
            WHEN 'overdue_history' THEN
              CASE WHEN COALESCE(h.prior_credits, 0) = 0 THEN 'no bureau history'
                   WHEN h.overdue_credits > 0 THEN 'overdue on a prior credit'
                   ELSE 'no overdue history' END
            ELSE ERROR(CONCAT('unknown dimension: ', @dimension))
          END AS bucket,
          CASE @dimension
            WHEN 'inquiries_last_year' THEN COALESCE(a.bureau_inquiries_last_year, -1)
            WHEN 'prior_credits' THEN COALESCE(h.prior_credits, 0)
            ELSE COALESCE(h.overdue_credits, 0) END AS sort_key
        FROM `atlas-ard-okf.finance_demo.loan_applications` a
        LEFT JOIN hist h USING (application_id)
      )
      SELECT
        @dimension AS dimension,
        bucket,
        COUNT(*) AS applicants,
        SUM(default_flag) AS defaults,
        ROUND(100 * SUM(default_flag) / COUNT(*), 2) AS default_rate_pct,
        ROUND(100 * (SELECT SUM(default_flag) / COUNT(*) FROM base), 2) AS book_default_rate_pct,
        ROUND(100 * SUM(default_flag) / COUNT(*) - 100 * (SELECT SUM(default_flag) / COUNT(*) FROM base), 2) AS vs_book_pts
      FROM base
      GROUP BY bucket
      ORDER BY MIN(sort_key)
---

## Why this is a template

The interesting join here is applicant-level: bureau rows must be
aggregated *per applicant* before the default rate is taken, or applicants
with many prior credits are counted many times and the rate is wrong in a
way that still looks plausible. "No bureau history" is reported as its own
bucket rather than dropped, because thin-file applicants are a real
segment with a real (usually higher) default rate.
