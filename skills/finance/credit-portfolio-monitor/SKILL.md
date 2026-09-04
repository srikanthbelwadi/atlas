---
name: credit-portfolio-monitor
description: Run a portfolio-risk review over the bank's OWN loan book through Atlas's finance pack — default rate by segment, bureau history versus default, and instalment delinquency before application — using only the private attested computations, and stop cleanly with a named refusal when the account lacks the finance.internal entitlement.
---

# Credit portfolio monitor (private data)

## When to use
"Which segments of our book default most?", "does bureau history predict
default for our applicants?", "is payment behaviour deteriorating before
application?", a monthly portfolio-review pack over internal data.

## Preconditions
- The account must hold the `finance.internal` entitlement. Check first:
  `GET /packs/finance/catalog` → `entitlements` includes `finance.internal`
  and the four `ac.hc_*` / `ac.paysim_*` entries have `accessible: true`.
  If not, stop and report *which* entitlement is missing (the catalog says
  so); do not rephrase questions to reach the data another way.
- The internal tables carry no calendar dates or geography. Never ask
  "this year" or "by state" of them; ask by segment and by months-before-
  application.

## Procedure
1. **Book by segment.** `POST /ask` {pack: finance} "What is our default
   rate by `<segment>`, and which segment is furthest above the book rate?"
   for each segment the review needs (`income_band`, `contract_type`,
   `education`, `region_rating`, `age_band`, `occupation`) →
   `ac.hc_default_rate_by_segment`. Read `default_rate_pct`,
   `book_default_rate_pct`, `vs_book_pts`; `other (small segments)` is the
   fold of segments under `min_applicants` — say so if it is large.
2. **Bureau history.** "Do applicants with more than three bureau inquiries
   in the last year default more often than the rest of our book?" and the
   same for `prior_credits` and `overdue_history` →
   `ac.hc_bureau_history_vs_default`. Report the bucket gradient, including
   the `no bureau history` bucket (thin files), which is a segment in its
   own right.
3. **Early-warning series.** "How did late payment on instalments trend over
   the twelve months before application, for clients who later defaulted
   versus those who didn't?" → `ac.hc_installment_delinquency_vintage`
   (`late_share_pct_later_defaulted` vs `late_share_pct_not_defaulted` by
   `months_before_application`). Use `grace_days` 5 or 10 for the
   policy-grade view and say which was used.
4. **Receipts.** Every answer carries a receipt with `visibility: private`
   and `unlocked_by: finance.internal`. Keep all of them — they are the
   evidence that the review ran on entitled access, template by template.

## Output
For each step: the table as returned, the citation line from the receipt
(it states the denominator and the "no calendar dates" caveat), and the
receipt id/version. A one-paragraph summary that names the three largest
`vs_book_pts` gaps and the bureau gradient. No recomputed figures.

## Refusal handling
A `guardrail.blocked` event with `code: not_entitled`, or an `answer` with
`refused: not_entitled`, means the account lost the entitlement mid-run.
Report the withheld source ids from `answer.access.withheld` and stop.
