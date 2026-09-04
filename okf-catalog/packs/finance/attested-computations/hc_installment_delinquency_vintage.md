---
id: ac.hc_installment_delinquency_vintage
type: AttestedComputation
pack: finance
visibility: private
access:
  entitlement: finance.internal
title: Internal servicing ledger — instalment delinquency by month before application (private)
description: >
  PRIVATE. Payment behaviour on prior loans in the bank's own servicing
  ledger, by month before the current application: instalments due, share
  paid late (after the due date, by more than a grace period), share paid
  short, average days late, and the same measures split by whether the
  applicant later defaulted. Use for "late payment trend", "delinquency by
  vintage / month", "roll rate", "arrears before application", "did
  payment behaviour deteriorate", "early-warning".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-04
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [internal, private, instalments, delinquency, late-payment, vintage, roll-rate, arrears, early-warning, risk-mart, finance]
sources:
  - kind: bigquery
    project: atlas-ard-okf
    dataset: finance_demo
    table: installment_payments
  - kind: bigquery
    project: atlas-ard-okf
    dataset: finance_demo
    table: loan_applications
source:
  kind: bigquery
  project: atlas-ard-okf
  dataset: finance_demo
  table: installment_payments
cost_profile:
  expected_bytes: 500000000
  cap_bytes: 5368709120
citation_template: "Late = paid more than @grace_days after the due date; short = paid less than due. Grouped by months before the client's current application (the ledger has no calendar dates), from the bank's internal installment_payments and loan_applications tables — private data."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: months_back
        type: INT64
        required: false
        default: 24
        description: How many months before application to report (1 = the month before). Default 24.
      - name: grace_days
        type: INT64
        required: false
        default: 0
        description: Days after the due date that still count as on time. Default 0 (any day late is late); use 5 or 10 for a grace-period view.
    sql: |
      WITH ip AS (
        SELECT i.months_before_application AS months_before, i.days_late, i.shortfall, a.default_flag
        FROM `atlas-ard-okf.finance_demo.installment_payments` i
        JOIN `atlas-ard-okf.finance_demo.loan_applications` a USING (application_id)
        WHERE i.months_before_application BETWEEN 1 AND @months_back
          AND i.days_paid IS NOT NULL
      )
      SELECT
        months_before AS months_before_application,
        COUNT(*) AS instalments,
        ROUND(100 * COUNTIF(days_late > @grace_days) / COUNT(*), 2) AS late_share_pct,
        ROUND(100 * COUNTIF(shortfall > 0) / COUNT(*), 2) AS short_paid_share_pct,
        ROUND(AVG(IF(days_late > 0, days_late, NULL)), 1) AS avg_days_late_when_late,
        ROUND(100 * COUNTIF(days_late > @grace_days AND default_flag = 1) / NULLIF(COUNTIF(default_flag = 1), 0), 2) AS late_share_pct_later_defaulted,
        ROUND(100 * COUNTIF(days_late > @grace_days AND default_flag = 0) / NULLIF(COUNTIF(default_flag = 0), 0), 2) AS late_share_pct_not_defaulted
      FROM ip
      GROUP BY months_before
      ORDER BY months_before
---

## Why this is a template

Three details decide whether a delinquency series is right: instalments
with no recorded payment must be excluded (not counted as infinitely
late), "late" needs an explicit grace period, and the time axis in this
ledger is *months before the client's application*, not calendar months —
the answer has to say that or it reads as a calendar trend. Splitting the
late share by later outcome is what makes it an early-warning view.
