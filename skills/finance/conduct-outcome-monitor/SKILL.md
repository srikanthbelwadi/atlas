---
name: conduct-outcome-monitor
description: Consumer Duty / UDAAP style outcome check — did a vulnerable-customer cohort (older Americans, servicemembers) get relief or timely responses less often than everyone else, by product and year — computed one reviewed way through Atlas's finance pack and reported with the metric definitions used.
---

# Conduct outcome monitor

## When to use
"Did `<tagged cohort>` complaints about `<product>` get resolved with relief
less often than untagged ones in `<year>`?", or a periodic outcomes check
across products. Cohorts available in the public mirror: `Older American`,
`Servicemember` (the closest public proxy for a vulnerability flag).

## Procedure
1. For each product in scope (or all products), `POST /ask`:
   "Did `<cohort>`-tagged complaints about `<product>` get resolved with
   relief less often than untagged ones in `<year>`?" → expect
   `ac.cfpb_outcome_gap_by_tag`. Record `relief_pct`, `explanation_only_pct`,
   `other_pct`, `relief_gap_pts` per cohort row.
2. Optionally add timeliness: "`<company>`'s timely-response rate on
   `<product>` complaints by quarter since `<date_from>`, versus the
   top-10 banks by deposits." → `ac.cfpb_timely_response_rate`.
3. Build the outcomes table: one row per product, columns tagged relief %,
   untagged relief %, gap (pts), complaints in cohort. Flag any gap below
   −2 pts as "review", and state the cohort size beside every flag (a gap
   on 40 complaints is not a finding).
4. Write the definitions block verbatim from the receipts'
   `citation_template` lines (relief = response containing "relief";
   tagged = `tags` containing the cohort), then the receipts list.

## Output
`conduct-outcomes-<cohort>-<year>.md` with the table, flags, definitions
and receipts. Never infer intent or causation; the skill reports gaps.

## Guardrails
About $0.01 per product-year. Mirror ends 2023-03-23: `<year>` must be 2022
or earlier; say so if asked for later.
