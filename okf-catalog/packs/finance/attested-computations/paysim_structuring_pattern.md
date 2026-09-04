---
id: ac.paysim_structuring_pattern
type: AttestedComputation
pack: finance
visibility: private
access:
  entitlement: finance.internal
title: Internal payments ledger — structuring (just-under-threshold) pattern (private)
description: >
  PRIVATE. Finds accounts in the bank's own payments ledger that made
  repeated transfers or cash-outs just under a reporting threshold within a
  short window — the structuring / smurfing pattern the legacy single-
  transaction flag never fires on. Reports each account's qualifying
  transaction count, total, amount range, window, how many were later
  confirmed fraud and whether the legacy rule flagged any. Use for
  "structuring", "smurfing", "just under 10,000", "repeated transfers below
  the threshold", "velocity", "AML pattern" questions about our ledger.
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-04
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [internal, private, payments, structuring, smurfing, aml, threshold, velocity, fraud, ledger, risk-mart, finance]
sources:
  - kind: bigquery
    project: atlas-ard-okf
    dataset: finance_demo
    table: payment_transactions
source:
  kind: bigquery
  project: atlas-ard-okf
  dataset: finance_demo
  table: payment_transactions
cost_profile:
  expected_bytes: 400000000
  cap_bytes: 5368709120
citation_template: "Structuring candidate = origin account with at least @min_count TRANSFER/CASH_OUT transactions of between @band_pct% and 100% of @threshold, all within @window_hours hours, from the bank's internal payment_transactions ledger — private data. A pattern, not a finding: review before acting."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: threshold
        type: FLOAT64
        required: false
        default: 10000
        description: The reporting threshold amounts stay under. Default 10000.
      - name: band_pct
        type: FLOAT64
        required: false
        default: 85
        description: Lower edge of the "just under" band as a percentage of the threshold. Default 85 (i.e. 8,500–9,999.99 for a 10,000 threshold).
      - name: min_count
        type: INT64
        required: false
        default: 3
        description: Minimum qualifying transactions per account within the window. Default 3.
      - name: window_hours
        type: INT64
        required: false
        default: 72
        description: Window (hours) all qualifying transactions must fall within. Default 72.
      - name: top_n
        type: INT64
        required: false
        default: 25
        description: How many accounts to return, most transactions first. Default 25.
    sql: |
      WITH cand AS (
        SELECT origin_account, hour_step, amount, is_fraud, is_flagged
        FROM `atlas-ard-okf.finance_demo.payment_transactions`
        WHERE txn_type IN ('TRANSFER', 'CASH_OUT')
          AND amount >= @threshold * @band_pct / 100 AND amount < @threshold
      ),
      windowed AS (
        -- for every qualifying transaction, how many of the same account's
        -- qualifying transactions fall in the @window_hours before it
        SELECT a.origin_account, a.hour_step, COUNT(*) AS n_in_window
        FROM cand a JOIN cand b
          ON b.origin_account = a.origin_account
         AND b.hour_step BETWEEN a.hour_step - @window_hours AND a.hour_step
        GROUP BY a.origin_account, a.hour_step
      ),
      hits AS (
        SELECT origin_account FROM windowed GROUP BY origin_account HAVING MAX(n_in_window) >= @min_count
      )
      SELECT
        c.origin_account,
        COUNT(*) AS qualifying_txns,
        ROUND(SUM(c.amount), 2) AS total_amount,
        ROUND(MIN(c.amount), 2) AS min_amount,
        ROUND(MAX(c.amount), 2) AS max_amount,
        MIN(c.hour_step) AS first_hour,
        MAX(c.hour_step) AS last_hour,
        MAX(c.hour_step) - MIN(c.hour_step) AS span_hours,
        SUM(c.is_fraud) AS confirmed_fraud_txns,
        SUM(c.is_flagged) AS legacy_rule_flagged
      FROM cand c JOIN hits USING (origin_account)
      GROUP BY c.origin_account
      ORDER BY qualifying_txns DESC, total_amount DESC
      LIMIT @top_n
---

## Why this is a template

A structuring screen is a windowed count, and the window is where ad-hoc
SQL goes wrong (a calendar bucket splits a 3-transaction burst across two
days and misses it). The template uses a sliding RANGE window over the
hourly step so any @min_count transactions within @window_hours count,
whatever the calendar. It reports a *pattern*, not a conclusion — the
citation says so — and shows the legacy rule's blind spot on the same rows.
