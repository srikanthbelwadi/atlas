---
name: receipt-to-audit-pack
description: Turn an Atlas answer's receipt and walkthrough into a model-risk / audit artefact — the question, every query as executed with bound parameters, bytes, tokens and cost, template versions with reviewer and freshness, sources and citations — as a single markdown pack a validator can replay.
---

# Receipt → audit pack

## When to use
After any attested answer (an `answer` event carrying `receipt`) that will
reach a client, a filing, a board pack or a regulator. Also useful for a
failed question: the `error` event's `walkthrough` documents what was
tried.

## Procedure
1. Take the terminal event's `walkthrough` and (if present) `receipt`.
2. Write `audit-pack-<template_id>-<timestamp>.md` with these sections, in
   this order, copying values verbatim:
   1. **Question** and `pack`.
   2. **Answer** — the narrative and the visualization rows.
   3. **Template** — `template_id`, `title`, `version`, `trust`,
      `reviewer`, `reviewed_on`, `stale_after`, `stale`, `lifecycle`,
      `executor`, `citation_template`.
   4. **Sources considered** — every `sources_considered` entry with score
      and trust; the one used marked.
   5. **Queries executed** — for each `queries_executed` entry: `step`,
      `source_id`, the full `sql` text (or the API name when `sql` is null),
      the bound `params`, `bytes_billed`, `row_count`.
   6. **Backtracks** — each `{from, reason}`; "none" if empty.
   7. **Cost** — `bq_cost_usd`, `plan_cost_usd`, `synth_cost_usd`,
      `generation_cost_usd` (when present), `total_cost_usd`; token counts
      by stage.
   8. **Vintage and limits** — the source vintages the template documents.
   9. **Replay** — the `bq query --use_legacy_sql=false --parameter=...`
      command reconstructed from the SQL and bound params (or the EDGAR
      URL for API steps), so a validator can re-run it.
3. Hash the pack (`sha256`) and print the hash with the filename.

## Rules
Nothing is summarised or rounded; a value that is not in the walkthrough
or receipt is not in the pack.
