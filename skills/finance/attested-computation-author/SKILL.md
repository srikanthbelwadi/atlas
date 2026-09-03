---
name: attested-computation-author
description: Draft a new Atlas attested computation (OKF AttestedComputation document with parameters, SQL, cost profile, governance fields and golden questions) from a question that keeps being answered by ad-hoc SQL, ready for a reviewer to attest. Use when a walkthrough shows a repeated machine-confirmed ad-hoc path.
---

# Attested-computation author

## When to use
A question shape has been answered by ad-hoc SQL more than a couple of
times (walkthrough `source_used.id` starts with `bq.` and `trust` is
`machine-confirmed`), or a reviewer wants a screening / ratio / rate
computation sanctioned.

## Procedure
1. **Collect evidence.** Gather the ad-hoc walkthroughs for the shape
   (their `queries_executed[].sql`, bytes, row counts) and the catalog entry
   for the table (`GET /packs/finance/catalog` → columns, vintage).
2. **Name the shape.** One sentence: what it computes, for which
   parameters, and the definition choices an analyst would argue about
   (which date, which denominator, which XBRL tag, which period kind).
3. **Write the document** at
   `okf-catalog/packs/finance/attested-computations/<id>.md`, following an
   existing one (`cfpb_complaints_trend.md` for BigQuery templates,
   `sec_fact_reconcile.md` for composites). Required frontmatter: `id`
   (`ac.<snake_case>`), `type: AttestedComputation`, `pack: finance`,
   `title`, `description` (name the question shapes it answers — this is
   what discovery embeds), `trust: human-reviewed`, `reviewer`,
   `reviewed_on`, `stale_after`, `lifecycle: draft`, `version: "0.1"`,
   `tags`, `source`/`sources`, `cost_profile` (`expected_bytes` from a dry
   run; `cap_bytes` only when the source is inherently large),
   `citation_template`, and `computation.runtime` with `executor`,
   `parameters` (every one with `type`, `required`, `description`, and
   `default` where optional) and `sql` using only `@param` bindings.
4. **Make the SQL defensive:** NULL-guard every optional parameter
   (`@p IS NULL OR …`), bound the scan (date/year filters, `LIMIT`), and
   join institutions through `finance_pack.entity_xref`, never by name.
5. **Add the golden question(s)** to `tests/golden/finance_*.yaml`
   (`path: attested`, `source_id`, `params_include`) and, if the shape is a
   demo chip, to `frontend/lib/finance.ts`.
6. **Run the checks:** `python -m pytest tests -q` (parses the SQL, checks
   parameters and declared sources), then a dry run in BigQuery for
   `expected_bytes`.
7. **Hand to the reviewer** with the draft, the evidence walkthroughs, and
   the dry-run bytes. The reviewer flips `lifecycle: active`, bumps
   `version` to `"1"` and sets `reviewed_on`. Nothing runs against the
   attested path until then (draft documents are catalogued but the
   planner is told to prefer active ones).

## Output
The `.md` document, the golden YAML entry, and a one-paragraph review note.
