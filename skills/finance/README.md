# Finance pack — agent skills

Procedural know-how an orchestrating agent (Claude Code, an ADK agent, or
any MCP host) loads to run a multi-step finance workflow *through* Atlas.
Each skill is a `SKILL.md` in the Anthropic agent-skills convention
(frontmatter `name` + `description`, then the procedure), and each one
calls Atlas only through its HTTP API — `POST /ask` with `pack: finance`,
`POST /skills/filing-fact-check`, `GET /packs/finance/catalog` — so the
skill inherits every guardrail (byte caps, monthly budget, attested-first
routing, receipts) rather than re-implementing any of it.

| Skill | Use case | Atlas templates it leans on |
|---|---|---|
| [`complaint-root-cause`](complaint-root-cause/SKILL.md) | A · "what's driving X" → a defensible root-cause brief | `ac.cfpb_complaints_trend`, `ac.cfpb_timely_response_rate`, `ac.cfpb_complaint_rate_per_deposits`, `ac.cfpb_narrative_themes` |
| [`conduct-outcome-monitor`](conduct-outcome-monitor/SKILL.md) | A · Consumer Duty / UDAAP outcome check by cohort | `ac.cfpb_outcome_gap_by_tag`, `ac.cfpb_timely_response_rate` |
| [`filing-fact-check`](filing-fact-check/SKILL.md) | B · verify every figure in a paragraph against SEC filings | `POST /skills/filing-fact-check` → `ac.sec_fact_reconcile`, `ac.sec_ratio_by_year` |
| [`peer-benchmark`](peer-benchmark/SKILL.md) | B · compare a bank with a size-defined peer set, definition named | `ac.fdic_peer_ratios`, `ac.sec_ratio_by_year`, `ac.entity_resolve` |
| [`receipt-to-audit-pack`](receipt-to-audit-pack/SKILL.md) | A+B · turn an answer's receipt + walkthrough into a model-risk artefact | any attested answer |
| [`attested-computation-author`](attested-computation-author/SKILL.md) | platform · draft a new reviewed template from a repeated ad-hoc question | catalog + walkthroughs |

## Conventions shared by every skill

- **Auth.** Every call carries `Authorization: Bearer <Firebase ID token>` of
  an approved user (`scripts/firebase_token.sh` mints one for the test
  account). Tokens expire hourly.
- **Streaming.** `/ask` and `/skills/*` return Server-Sent Events. Read to
  the terminal `answer` or `error` event; both carry `walkthrough`, and an
  attested `answer` also carries `receipt`. `scripts/golden_run.py` has a
  reference parser (`stream()`).
- **Attested first, refuse honestly.** A skill never rewrites a question to
  coax an answer out of ad-hoc SQL when the attested path returned nothing;
  it reports "no attested evidence" and moves on. Every figure in a skill's
  output is copied from an `answer.visualization.data` row or the
  `walkthrough.queries_executed` list — never recomputed.
- **Vintage.** The BigQuery mirrors are dated (CFPB to 2023-03-23, SEC bulk
  to fiscal 2019; the EDGAR API is current). Skills default their windows
  accordingly and print the vintage line the receipt carries.
- **Budget.** A skill states its expected spend up front (sum of the
  templates' `cost_profile.expected_bytes` at $6.25/TiB plus model calls)
  and stops if a `guardrail.blocked` event arrives.
