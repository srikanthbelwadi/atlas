---
name: complaint-root-cause
description: Turn "what is driving the rise in complaints about X" into a defensible root-cause brief from the CFPB complaint mirror via Atlas's finance pack — trend, movers, peer normalisation, verified narrative themes — with a receipt for every figure. Use when a complaints, conduct or Consumer Duty team asks why complaints moved.
---

# Complaint root-cause brief

## When to use
A question of the form "why did complaints about *product/issue/company*
rise (or fall) in *period*?", or "what is behind the spike in *X*?". Not
for single-number lookups (ask Atlas directly) and not for anything after
2023-03 (the mirror's vintage; say so and stop).

## Inputs
- `subject`: product and/or issue substring, optionally a company (as the
  question names it — the crosswalk resolves it).
- `window`: `date_from`, `date_to` (default 2021-01-01 – 2023-03-31).
- `peer_n` (default 10) when a company is named.

## Procedure
Each step is one `POST /ask {"question": ..., "pack": "finance"}`. Keep the
question wording close to the template's own description so the planner
routes to the attested path; check `walkthrough.source_used.id` after each
call and stop with "no attested evidence" if it is not the expected one.

1. **Trend.** "Complaints about `<subject>` by quarter from `<date_from>`
   to `<date_to>`, with the share answered on time and the share closed
   with relief." → expect `ac.cfpb_complaints_trend`. Keep the rows.
2. **Movers.** "Which five products had the largest year-over-year increase
   in complaints in `<latest full year>`?" (ad-hoc is acceptable here; note
   `trust: machine-confirmed` in the brief). Skip when the subject is
   already one product.
3. **Peer normalisation** (company named only). "`<company>`'s
   timely-response rate on `<product>` complaints by quarter since
   `<date_from>`, versus the top-`<peer_n>` banks by deposits." → expect
   `ac.cfpb_timely_response_rate`. Then "Complaints per $1B of deposits for
   the ten largest banks in `<year>`." → expect
   `ac.cfpb_complaint_rate_per_deposits`.
4. **Themes.** "What are the main themes in narratives about `<subject>`
   filed between `<date_from>` and `<date_to>`, with three representative
   quotes each?" → expect `ac.cfpb_narrative_themes`. Use only quotes that
   survived verification (the `check.done` event reports
   `verified_quotes`/`dropped_quotes`; dropped quotes never appear in the
   answer).
5. **Assemble the brief** (markdown): headline finding in one sentence; the
   trend table; the movers; the peer comparison with the *definition* line
   from each receipt's `citation_template`; the themes with quoted
   `complaint_id`s; a "Sources and receipts" section listing every
   `receipt.template_id`, `version`, `reviewer`, `reviewed_on`,
   `stale_after`, bytes and cost; and the vintage line.

## Output
`root-cause-<subject>-<date>.md`. Every number traces to a receipt; the
brief says which figures came from an ad-hoc (machine-confirmed) query.

## Guardrails
Expected spend ≈ $0.10 (the theming step is ~$0.05). If any step yields
`guardrail.blocked`, stop and report it. Never paraphrase a narrative quote.
