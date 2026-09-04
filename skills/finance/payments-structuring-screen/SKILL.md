---
name: payments-structuring-screen
description: Screen the bank's OWN payments ledger for structuring (repeated just-under-threshold transfers) through Atlas's private attested computation, compare the hits with the legacy single-transaction flag, and hand a reviewer a pattern list with receipts — never a conclusion of wrongdoing.
---

# Payments structuring screen (private data)

## When to use
"Who is structuring transfers under 10,000?", "smurfing in our ledger",
"did the legacy flag miss repeated small transfers?", a financial-crime
team's periodic threshold review.

## Preconditions
Entitlement `finance.internal` (see `credit-portfolio-monitor`). The ledger
is a 30-day extract with an hourly `hour_step`, no calendar dates, amounts
in unstated units.

## Procedure
1. **Default screen.** `POST /ask` {pack: finance} "Which accounts in our
   ledger made three or more transfers just under 10,000 within 72 hours,
   and did the legacy flag catch any?" → `ac.paysim_structuring_pattern`
   with defaults (`threshold` 10000, `band_pct` 85, `min_count` 3,
   `window_hours` 72). Columns: `qualifying_txns`, `total_amount`,
   `min_amount`/`max_amount`, `first_hour`/`last_hour`, `span_hours`,
   `confirmed_fraud_txns`, `legacy_rule_flagged`.
2. **Sensitivity.** Re-ask with a tighter band ("between 9,000 and 10,000")
   and a shorter window ("within 24 hours") — the template binds
   `band_pct: 90` and `window_hours: 24`. Report how the hit list changes;
   accounts present at every setting go to the top.
3. **Legacy comparison.** From step 1's rows, count hits with
   `legacy_rule_flagged = 0`: that is the blind spot of the single-
   transaction rule, stated as a number, not an opinion.
4. **Context, if asked.** "How many transactions of each type are in our
   payments ledger, and what share of each type is confirmed fraud?" is an
   ad-hoc, machine-confirmed answer over the same private table — label it
   as such next to the attested screen.

## Output
The pattern table (step 1), the sensitivity note (step 2), the legacy
blind-spot count (step 3), and the receipt's citation line verbatim — it
says "a pattern, not a finding: review before acting". Never name an
account as a wrongdoer; the skill's job ends at the reviewer's desk.
