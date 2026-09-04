---
id: bq.atlas-ard-okf.finance_demo.payment_transactions#finance
type: Table
pack: finance
visibility: private
access:
  entitlement: finance.internal
  restricted_to: orchestrator service account (dataset IAM); Atlas users with the finance.internal entitlement
title: Internal risk mart — payment transactions ledger (private)
description: >
  PRIVATE table `atlas-ard-okf.finance_demo.payment_transactions` — the
  bank's payments ledger: one row per transaction over a 30-day extract
  (hour_step 1–744), txn_type (PAYMENT | TRANSFER | CASH_OUT | CASH_IN |
  DEBIT), amount, origin_account and destination_account with balances
  before and after, is_fraud (confirmed fraud label) and is_flagged (the
  legacy rule: a single transfer over 200,000). Use for "transactions",
  "transfers", "cash-outs", "structuring", "smurfing", "just under the
  threshold", "velocity", "fraud rate" questions about our own ledger.
  Not public data.
  Columns:
    - hour_step (INTEGER)
    - txn_type (STRING)
    - amount (FLOAT)
    - origin_account (STRING)
    - origin_balance_before (FLOAT)
    - origin_balance_after (FLOAT)
    - destination_account (STRING)
    - destination_balance_before (FLOAT)
    - destination_balance_after (FLOAT)
    - is_fraud (INTEGER)
    - is_flagged (INTEGER)
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-04
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [internal, private, payments, ledger, transactions, transfers, structuring, aml, fraud, velocity, risk-mart, finance]
source:
  kind: bigquery
  project: atlas-ard-okf
  dataset: finance_demo
  table: payment_transactions
  refresh: manual (scripts/finance_private_load.sh)
  stands_in_for: the core-banking transaction log a financial-crime team screens
---

## What's in this table

PaySim (a simulator calibrated on a real mobile-money operator's logs) or
the synthetic ledger from `scripts/finance_private_synth.py`, curated.
Amounts are in unstated currency units. `is_flagged` is deliberately a
poor rule — it fires on a single very large transfer and never on
repeated small ones, which is what `ac.paysim_structuring_pattern` finds.

## Notes for query planning

- Structuring / smurfing / just-under-threshold questions must use
  `ac.paysim_structuring_pattern` (window logic is easy to get wrong).
- Simple counts and fraud rates by txn_type are fine as ad-hoc SQL for an
  entitled user; the table is small.
