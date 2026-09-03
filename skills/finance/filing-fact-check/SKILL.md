---
name: filing-fact-check
description: Verify every numeric claim in a paragraph of a research note or regulatory response against SEC filings through Atlas's attested computations only (EDGAR API reconciled with the SEC bulk data set; curated ratios), returning a verdict per claim — verified, differs, not verifiable — with accession-level receipts. Never guesses.
---

# Filing fact-check

## When to use
A draft paragraph with figures about a public company's reported
financials ("net income reached $36.4 billion", "ROA was 1.33%"). Not for
forecasts, guidance, or non-SEC filers.

## Procedure
1. `POST /skills/filing-fact-check {"text": <paragraph ≤ 4,000 chars>, "pack": "finance"}`.
2. Read the stream: `claim.extracted` lists the claims Atlas found;
   `claim.verdict` arrives per claim; the terminal `answer` has
   `visualization.kind = "verdict_table"` with one row per claim
   (`claim, entity, metric, fiscal_year, claimed, reported, source,
   accession, delta_pct, verdict, sources_agree, note`) and a `receipt`.
3. Interpret verdicts exactly: `verified` (within 0.5 % for levels, 0.25 pts
   for ratios), `differs` (show both values and the delta), `not_verifiable`
   (growth / percentage-change claims, no fiscal year, no curated metric —
   the `note` says which), `no_reported_value` (the filer has no such fact).
4. Produce the marked-up paragraph: each claim followed by `[✓ 36.43 B,
   10-K FY2019, EDGAR]`, `[≠ reported 1.37 %, Δ 0.04 pts]` or `[?]`, then
   the verdict table and the receipt (template versions, sources, bytes,
   cost).

## Notes
- Two-source agreement (`sources_agree: agree`) is only possible for fiscal
  2019 and earlier (the BigQuery mirror's vintage); later years reconcile as
  `single source` — the EDGAR API — and that is stated, not hidden.
- Cost is ~$0.13 per level claim that touches the bulk data set; a
  four-claim paragraph is ~$0.26. Ratios cost pennies.
- The skill never rewrites a claim to make it checkable.
