---
id: bq.atlas-ard-okf.finance_demo.bureau_credits#finance
type: Table
pack: finance
visibility: private
access:
  entitlement: finance.internal
  restricted_to: orchestrator service account (dataset IAM); Atlas users with the finance.internal entitlement
title: Internal risk mart — bureau credit history (private)
description: >
  PRIVATE table `atlas-ard-okf.finance_demo.bureau_credits` — credit-bureau
  history for the bank's applicants: one row per prior credit reported by
  the bureau (credit_status Active | Closed | Sold | Bad debt, credit_type,
  days_since_credit_opened relative to the application, days_overdue,
  credit_amount, current_debt, amount_overdue, times_prolonged). Joins to
  loan_applications on application_id. Use for "prior credits", "bureau
  history", "overdue history", "external debt" questions about our
  applicants. Not public data.
  Columns:
    - application_id (INTEGER)
    - bureau_credit_id (INTEGER)
    - credit_status (STRING)
    - credit_type (STRING)
    - days_since_credit_opened (INTEGER, negative = before application)
    - days_overdue (INTEGER)
    - credit_amount (FLOAT)
    - current_debt (FLOAT)
    - amount_overdue (FLOAT)
    - times_prolonged (INTEGER)
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-04
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [internal, private, credit-bureau, prior-credits, overdue, risk-mart, finance]
source:
  kind: bigquery
  project: atlas-ard-okf
  dataset: finance_demo
  table: bureau_credits
  refresh: manual (scripts/finance_private_load.sh)
  stands_in_for: the bureau-pull history the decisioning system stores per applicant
---

## What's in this table

The Home Credit `bureau` file, curated. Many applicants have several rows;
some have none (no bureau history) — a LEFT JOIN from `loan_applications`
is the right shape, and "no history" is a bucket of its own in
`ac.hc_bureau_history_vs_default`.
