---
id: bq.atlas-ard-okf.finance_demo.installment_payments#finance
type: Table
pack: finance
visibility: private
access:
  entitlement: finance.internal
  restricted_to: orchestrator service account (dataset IAM); Atlas users with the finance.internal entitlement
title: Internal risk mart — instalment payments (private)
description: >
  PRIVATE table `atlas-ard-okf.finance_demo.installment_payments` — the
  instalment schedule versus actual payments on applicants' prior loans
  with the bank: one row per instalment (days_due, days_paid, amount_due,
  amount_paid, days_late > 0 = paid late, shortfall > 0 = paid short,
  months_before_application). Use for "late payment", "delinquency",
  "roll rate", "payment behaviour by month / vintage", "arrears" questions
  about our own book. Not public data.
  Columns:
    - application_id (INTEGER)
    - prior_loan_id (INTEGER)
    - instalment_number (INTEGER)
    - days_due (INTEGER, relative to application)
    - days_paid (INTEGER)
    - amount_due (FLOAT)
    - amount_paid (FLOAT)
    - days_late (INTEGER)
    - shortfall (FLOAT)
    - months_before_application (INTEGER)
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-04
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [internal, private, instalments, delinquency, late-payment, vintage, roll-rate, arrears, risk-mart, finance]
source:
  kind: bigquery
  project: atlas-ard-okf
  dataset: finance_demo
  table: installment_payments
  refresh: manual (scripts/finance_private_load.sh)
  stands_in_for: the servicing system's instalment ledger
---

## What's in this table

The Home Credit `installments_payments` file, curated. Dates are relative
to each client's current application (the source is anonymised), so a
"vintage" here is *months before application*, not a calendar month —
`ac.hc_installment_delinquency_vintage` reports it that way and the
answer must say so.
