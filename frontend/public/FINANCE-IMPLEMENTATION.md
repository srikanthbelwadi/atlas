# Atlas Finance Pack — Implementation

Status: live at [atlasdata.world/finance](https://atlasdata.world/finance) since 3 September 2026 · golden sets 22/22 (public 10, A 6, B 6) · code in [`srikanthbelwadi/atlas`](https://github.com/srikanthbelwadi/atlas) `main`.

This document describes what was built for the finance section, as built. The plan it implements is `atlas-finance-demo-plan.md` (use cases, data selection) and the design it follows is [`FINANCE-DESIGN.md`](https://github.com/srikanthbelwadi/atlas/blob/main/frontend/public/FINANCE-DESIGN.md) (also at `/finance/design`). Sections 12–13 cover what the pack does *not* yet demonstrate — internal enterprise data — and the recommended way to add it.

## 1. What the finance pack is

A second catalog inside the same Atlas deployment, isolated from the public demo by a **pack** boundary, that answers two finance use cases over public BigQuery datasets standing in for bank-internal systems:

- **A · Complaint & conduct intelligence** — the CFPB complaint database as a bank's complaint case-management system, joined to FDIC institutions for peer normalisation; five reviewed templates including narrative theming with verified quotes.
- **B · Filing-grounded fact-check & peer benchmark** — SEC EDGAR (API) and the SEC Financial Statement Data Sets (BigQuery) as a fundamentals warehouse, FDIC ratios as regulatory peer data; a two-source reconciliation, curated ratios, a SIC-code screen, and a paragraph fact-check that verifies claims through attested computations only.

Every attested answer carries a **receipt** (template, version, reviewer, freshness, every query step with bound parameters, bytes, tokens, cost). Ad-hoc answers carry the existing walkthrough only, so a receipt can never suggest a reviewer signed off on model-drafted SQL.

## 2. Architecture

```
frontend (Next.js, Firebase App Hosting)                orchestrator (FastAPI, Cloud Run — one service)
/            public demo ─────── POST /ask {question} ───────▶ pipeline.run(q, user, pack="public")
/finance     ask + fact-check ── POST /ask {question, pack} ──▶ pipeline.run(q, user, pack="finance")
             └── fact-check ──── POST /skills/filing-fact-check ▶ skills.filing_fact_check.run
/finance/catalog ─────────────── GET /packs/finance/catalog ──▶ OKF docs + crawled rows for the pack
                                                               │
                        discovery.discover(q, pack) ◀──────────┘
                          ├─ VECTOR_SEARCH over ard_catalog.embeddings WHERE metadata.pack = @pack
                          └─ in-process ranking of okf-catalog/ docs WHERE pack ∈ doc.packs
                        planner (Gemini flash) + pack glossary → attested template or ad-hoc SQL
                        _fetch_one → executor: bigquery | bigquery_sample_llm | composite |
                                               sec_edgar | sec_edgar_annual | sec_ratio
                        check → synthesize (Gemini pro) → answer {narrative, viz, walkthrough, receipt}
```

### 2.1 Pack isolation (the "does not interfere" property)

| Layer | Mechanism | File |
|---|---|---|
| OKF documents | `pack: finance` or `packs: [public, finance]` in frontmatter; absent = `public` | [`okf_loader.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/accessor/okf_loader.py) |
| Crawler | `CRAWL_TARGETS` rows carry packs; non-public rows get a `#<pack>` doc_id suffix and `metadata.pack` | [`crawler/targets.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/crawler/targets.py), [`crawler/main.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/crawler/main.py) |
| Discovery | pre-filtered `VECTOR_SEARCH` base table (both JSON encodings handled) + pack-filtered OKF docs; finance keeps 8 candidates, public 6 | [`discovery.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/orchestrator/discovery.py) |
| API | `/ask` accepts `pack`; a pack not in `ATLAS_PACKS_ENABLED` is refused (400), never answered from the public catalog | [`main.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/orchestrator/main.py) |
| Prompts | the finance glossary and synthesis rule are appended only for `pack == finance`; the public prompts are byte-identical (unit-tested) | [`packs.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/orchestrator/packs.py), [`llm.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/orchestrator/llm.py) |
| Frontend | `/finance/*` routes `notFound()` unless `NEXT_PUBLIC_ATLAS_FINANCE_ENABLED=true`; header link under the same flag | [`app/finance/layout.tsx`](https://github.com/srikanthbelwadi/atlas/blob/main/frontend/app/finance/layout.tsx), [`lib/finance.ts`](https://github.com/srikanthbelwadi/atlas/blob/main/frontend/lib/finance.ts) |
| Budget | same $100/user/month ceiling; usage doc gains `by_pack` | [`guardrails.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/orchestrator/guardrails.py) |

Proof: `tests/golden/public_regression.yaml` (the nine public suggestion chips plus a CFPB question that must *not* find a finance source) passes 10/10 against the finance-enabled revision.

### 2.2 Executors added

| Executor | Declared in | What it does | Guardrails |
|---|---|---|---|
| `bigquery` (per-template cap) | any template | existing guarded SQL; a template may declare `cost_profile.cap_bytes`, clamped to ≤ `ATLAS_TEMPLATE_BYTE_CAP_MAX` (40 GB) | dry run + `maximum_bytes_billed` |
| `bigquery_sample_llm` | `ac.cfpb_narrative_themes` | step 1 guarded sample SQL (≤ `max_sample_n` = 500 rows); step 2 plan-tier model themes the sample with the document's own `prompt`; **check stage verifies every quote is a verbatim excerpt of the cited narrative and drops the rest** | sample cap, generation tokens priced separately (`token_usage.theme`) |
| `composite` | `ac.sec_fact_reconcile` | ordered `steps`, each another attested computation with a parameter map; `combine: reconcile` adds `delta_pct` / `agreement` | each step's own guardrails; one `queries_executed` entry per step |
| `sec_edgar_annual` | `ac.sec_fact_annual_api` | one 10-K/FY fact selected the analyst's way (latest period end, ≥300-day duration, latest filing) | free API, 10 req/s |
| `sec_ratio` | `ac.sec_ratio_by_year` | ROA/ROE/net margin/efficiency/equity-to-assets from annual facts with the averaging rule stated | free API |
| `sec_edgar` (extended) | `ac.sec_edgar_company_metric_by_year` | 21 curated metrics; multiple companies in one question | free API |

The metric→XBRL-tag map lives once in [`xbrl_metrics.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/accessor/xbrl_metrics.py); the BigQuery template `ac.sec_fact_from_bq` carries the same map inline and a unit test keeps the two identical.

### 2.3 Receipt

Assembled in `pipeline.build_receipt` for attested answers only:
`template_id, title, version, reviewer, reviewed_on, stale_after, stale, lifecycle, trust, pack, executor, sources[], queries[] {step, source_id, bytes_billed, row_count, params}, bytes_billed, tokens{plan, theme?, synthesize}, cost{…, generation_cost_usd?}, citation_template`. Rendered by [`ReceiptCard.tsx`](https://github.com/srikanthbelwadi/atlas/blob/main/frontend/components/ReceiptCard.tsx).

## 3. Catalog inventory (`okf-catalog/packs/finance/`)

### 3.1 Reviewed table documents

| Document | Stands in for | Vintage (confirmed 2026-09-03) |
|---|---|---|
| [`cfpb_complaints/complaint_database.md`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/bigquery/cfpb_complaints/complaint_database.md) | complaint case-management system | 3.46 M complaints, 2011-12-01 → **2023-03-23**; 1.25 M narratives |
| [`fdic_banks/institutions.md`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/bigquery/fdic_banks/institutions.md) | entity master + peer financials | late-2022 snapshot |
| [`sec_quarterly_financials/overview.md`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/bigquery/sec_quarterly_financials/overview.md) | fundamentals warehouse | filings to 2020-12-31; **fiscal 2019** last complete 10-K year |

Crawled (machine-confirmed) rows for the pack: `cfpb_complaints` (1 table), `fdic_banks` (2), `sec_quarterly_financials` (10), `bls` (9, shared with public).

### 3.2 Attested computations (12)

| id | Use | Executor | Cost / run |
|---|---|---|---|
| [`ac.cfpb_complaints_trend`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/cfpb_complaints_trend.md) | A1 trend by product/company/grain | bigquery | ~$0.01 |
| [`ac.cfpb_timely_response_rate`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/cfpb_timely_response_rate.md) | A2 bank vs deposit-size peers | bigquery (3 sources) | ~$0.01 |
| [`ac.cfpb_complaint_rate_per_deposits`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/cfpb_complaint_rate_per_deposits.md) | A3 complaints per $1B deposits | bigquery | ~$0.007 |
| [`ac.cfpb_narrative_themes`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/cfpb_narrative_themes.md) | A4 themes + verified quotes | bigquery_sample_llm | ~$0.05, ~2–4 min |
| [`ac.cfpb_outcome_gap_by_tag`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/cfpb_outcome_gap_by_tag.md) | A5 vulnerable-cohort outcomes | bigquery | ~$0.006 |
| [`ac.sec_edgar_company_metric_by_year`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/attested-computations/sec_edgar_company_metric_by_year.md) | B3 metric series, one or more companies | sec_edgar | ~$0.005–0.07 |
| [`ac.sec_fact_annual_api`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/sec_fact_annual_api.md) | one 10-K fact (API half of reconcile) | sec_edgar_annual | ~$0.005 |
| [`ac.sec_fact_from_bq`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/sec_fact_from_bq.md) | one 10-K fact (bulk half) | bigquery, cap 30 GB | ~$0.13 |
| [`ac.sec_fact_reconcile`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/sec_fact_reconcile.md) | B1 two-source reconciliation | composite | ~$0.13 |
| [`ac.sec_ratio_by_year`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/sec_ratio_by_year.md) | B2/B4 curated ratios from filings | sec_ratio | ~$0.005 |
| [`ac.fdic_peer_ratios`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/fdic_peer_ratios.md) | B2 FDIC peer table (size measure required) | bigquery | ~$0.006 |
| [`ac.sec_filer_screen`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/sec_filer_screen.md) | B5 SIC-code screen (quarterly/annual, threshold) | bigquery, cap 30 GB | ~$0.14 |
| [`ac.entity_resolve`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/entity_resolve.md) | name → CFPB / FDIC / SEC identities | bigquery | <$0.001 |

Entity crosswalk: [`entity_xref.csv`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/entity_xref.csv) (63 rows, every CFPB string, FDIC cert and CIK verified against the data with [`infra/finance/xref_check.sql`](https://github.com/srikanthbelwadi/atlas/blob/main/infra/finance/xref_check.sql)), loaded into `atlas-ard-okf.finance_pack.entity_xref` by [`infra/finance/setup.sql`](https://github.com/srikanthbelwadi/atlas/blob/main/infra/finance/setup.sql).

## 4. The fact-check skill (server side)

[`skills/filing_fact_check.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/orchestrator/skills/filing_fact_check.py): claim extraction (plan-tier model, response schema) → per claim, `ac.sec_fact_reconcile` (levels) or `ac.sec_ratio_by_year` (ratios) through the shared `_fetch_one` → verdicts `verified` / `differs` / `not_verifiable` / `no_reported_value` → `verdict_table` visualization + receipt. Growth or percentage-change claims about level metrics are *not verifiable* by design; a byte-cap hit on one claim becomes that claim's verdict rather than aborting the check. No ad-hoc SQL exists in this path.

## 5. Frontend

`/finance` (Ask | Fact-check a paragraph; grouped example chips; trace; answer; receipt; walkthrough), `/finance/catalog` (every source with trust, reviewer, freshness, expandable SQL), `/finance/design`, `/finance/implementation` (this document). New components: `ReceiptCard`, `TrustChip`, `FactCheckBar`, `CatalogTable`, `VerdictTableViz` (in `AnswerCanvas`); `TracePanel` shows multi-step fetches, quote verification and claim verdicts. Same design tokens as the public demo (IBM Plex; navy/amber/teal).

## 6. Data vintage — and why the demo years are 2022 and 2019

Confirmed by query on 2026-09-03 ([`xref_lookup.sql`](https://github.com/srikanthbelwadi/atlas/blob/main/infra/finance/xref_lookup.sql), [`sec_vintage.sql`](https://github.com/srikanthbelwadi/atlas/blob/main/infra/finance/sec_vintage.sql)): the CFPB mirror's public pipeline stopped on 2023-03-23; the SEC bulk mirror's last filings are dated 2020-12-31 (fiscal 2019 is the last complete 10-K year); the FDIC snapshot is late 2022. The EDGAR API is current. Every template default, the planner glossary and the example questions are pinned accordingly, and answers name the vintage. This is also the strongest argument for §12: the public mirrors are stand-ins, and the same catalog over a *current* internal extract is the product.

## 7. Golden results and cost

| Set | Result | Notes |
|---|---|---|
| `public_regression.yaml` | 10/10 | run against the finance-enabled revision before promotion |
| `finance_a.yaml` | 6/6 | A4 theming ~$0.05, 2–4 min; A6 honest refusal |
| `finance_b.yaml` | 6/6 | B1 reconcile $0.13; B4 fact-check $0.26 (four claims); B5 screen $0.14; B6 honest refusal |

Runner: [`scripts/golden_run.py`](https://github.com/srikanthbelwadi/atlas/blob/main/scripts/golden_run.py) (asserts path, source, bound params, bytes, quotes, verdicts; writes a markdown report). Unit tests: [`tests/test_finance_catalog.py`](https://github.com/srikanthbelwadi/atlas/blob/main/tests/test_finance_catalog.py), 42 tests, no GCP required — public catalog unchanged, pack isolation, every template parses (sqlglot) and binds its parameters and touches only declared sources, tag-map sync, composite graph, quote verification, verdict arithmetic.

Five rounds of golden runs found and fixed: JSON-serialisation of DATE rows in synthesis, multi-company EDGAR questions, the 21 GB SEC scan versus the 20 GB template cap (per-template caps), growth claims mis-typed as levels, and two routing misses that became a template (`ac.sec_filer_screen`) and a required parameter (`ac.fdic_peer_ratios.measure`).

## 8. Operations

| Task | Command / file |
|---|---|
| Full phase-0 (crosswalk, crawl, no-traffic revision) | [`scripts/finance_phase0.sh`](https://github.com/srikanthbelwadi/atlas/blob/main/scripts/finance_phase0.sh), [`finance_phase0b.sh`](https://github.com/srikanthbelwadi/atlas/blob/main/scripts/finance_phase0b.sh) |
| Rebuild + redeploy the tagged revision after a backend/catalog change | [`scripts/finance_redeploy.sh`](https://github.com/srikanthbelwadi/atlas/blob/main/scripts/finance_redeploy.sh) → test at `https://finance---atlas-orchestrator-….run.app` → `gcloud run services update-traffic atlas-orchestrator --to-latest` |
| Golden runs | `scripts/golden_run.py --base … --token "$(scripts/firebase_token.sh)" --set tests/golden/<set>.yaml [--only B4,B5]` |
| Crawl the finance pack again | `gcloud run jobs execute atlas-crawler --args="--pack,finance"` (weekly scheduler crawls every pack) |
| Hide the section | `NEXT_PUBLIC_ATLAS_FINANCE_ENABLED="false"` in `apphosting.yaml` → push; or route traffic to a pre-finance revision |
| Test account | Firebase Email/Password user `atlas-test@atlasdata.world`, approved in `/admin`; `scripts/firebase_token.sh` |

Environment on the orchestrator revision: `ATLAS_PACKS_ENABLED=public,finance`; optional `ATLAS_TEMPLATE_BYTE_CAP_MAX` (default 40 GB).

## 9. Agent skills (SKILL.md)

The plan's Layer-3 skills — procedures an orchestrating agent follows *through* Atlas's API — live in [`skills/finance/`](https://github.com/srikanthbelwadi/atlas/tree/main/skills/finance) ([index](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/README.md)):

| Skill | Purpose |
|---|---|
| [`complaint-root-cause`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/complaint-root-cause/SKILL.md) | trend → movers → peer normalisation → verified themes → brief with receipts |
| [`conduct-outcome-monitor`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/conduct-outcome-monitor/SKILL.md) | vulnerable-cohort outcome gaps by product and year, definitions stated |
| [`filing-fact-check`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/filing-fact-check/SKILL.md) | drive `/skills/filing-fact-check` and mark up the paragraph with verdicts |
| [`peer-benchmark`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/peer-benchmark/SKILL.md) | size-defined peer table with the FDIC-vs-XBRL definition chosen explicitly |
| [`receipt-to-audit-pack`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/receipt-to-audit-pack/SKILL.md) | receipt + walkthrough → replayable model-risk artefact |
| [`attested-computation-author`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/attested-computation-author/SKILL.md) | draft a new reviewed template from repeated ad-hoc questions |

They are ready to run from Claude Code (or any MCP host) against the deployed API today; the MCP wrapper that would expose `ask` / `fact_check` / `catalog` as tools is the plan's phase 4 and is not built.

## 10. Not built (from the plan), by design

Optional showpiece C (AML on chain data), the Kaggle loads, the deterministic attester (SQL-text hash check on execution), per-agent-identity budgets, the audit-pack export button in the UI, the MCP surface. The skills in §9 are the agent-side half of several of these; the platform-side half is the phase-3/4 backlog.

## 11. Known limits

Public mirrors are dated (§6). SEC bulk scans cost ~$0.13 each because `numbers` is unpartitioned and unclustered — clustering a copy in the project would make them pennies. Discovery is embedding-only; a question that names "banks" leans toward FDIC sources, which is why the screening question names the SEC filings explicitly. The crosswalk covers ~40 banks and ~20 large filers; anything outside it resolves to "no evidence" rather than a guess.

## 12. Internal (private) enterprise data — analysis

**Where the pack stands.** Neither A nor B queries private data. Every source is `bigquery-public-data.*` or the public EDGAR API. The only object in our own project is `finance_pack.entity_xref`, a reviewed helper table — real "private data" in the plumbing sense (the crawler, the templates and IAM all treat it exactly as they would a customer table), but not a business dataset. So the demo currently proves discovery, attestation, cost control and receipts over *public stand-ins*, and asserts — without showing — that the same path works over a customer's warehouse.

**Why this matters commercially.** The proposal's revenue lines (Gateway, curation) are all about the customer's own estate. A buyer's first question is "show me this over *my* data with *my* access controls." A and B answer "here is how governed answers look"; they don't answer "here is Atlas cataloguing a table I own, restricting it to who may see it, and combining it with public reference data in one answer."

**Is it use case C?** No. C in the plan is the AML fund-flow *guardrail showpiece* on public chain data (`crypto_ethereum`); its point is the budget stop on a multi-terabyte table. The internal-data demonstration is a different property and deserves its own label: **use case D — Internal risk mart behind the same catalog.**

### 12.1 Recommendation: use case D

Load two Kaggle-style datasets that ML teams train on — exactly the "representative of internal enterprise data" material the original brief asked for — into a *private* dataset in our project, catalogue them with the unchanged crawler, mark them `visibility: private` in OKF, add four reviewed templates, and answer questions that join private and public sources in one receipt.

| Component | Choice | Why |
|---|---|---|
| Private dataset | `atlas-ard-okf.finance_demo` (US multi-region, IAM: orchestrator service account only) | the same project the public pack reads from, so "same crawler, same executor, different IAM" is literally true |
| Credit decisioning mart | **Home Credit Default Risk** (7 relational tables: applications 307 k × 122, bureau 1.7 M, prior applications, instalments 13.6 M, credit-card and POS balances) | the most realistic *relational* internal schema in the public domain; a retail-bank decisioning mart shape |
| Payments / transaction log | **PaySim** (6.36 M mobile-money transactions with fraud flags) — or IBM AML (HI-Small) if C is built later, shared with it | a ledger shape for "your transactions" questions and a structuring/velocity template |
| Fresh CFPB extract (optional, high value) | CFPB bulk CSV (current) loaded as `finance_demo.complaints_internal` | turns A's questions into 2024–2026 questions and demonstrates *the same templates* running on a private, current table — the "internal complaint system" story without any new SQL |

**Templates (reviewed):** `ac.hc_default_rate_by_segment` (default rate by income band / contract type / channel, denominators stated), `ac.hc_bureau_inquiries_vs_default` (prior inquiries bucket → default rate), `ac.hc_installment_delinquency_vintage` (roll-rate by origination month), `ac.paysim_structuring_pattern` (repeated just-under-threshold transfers per account within N days), plus `ac.cfpb_*` re-pointed to the internal complaint table through a `source_override` (one line per template) if the fresh extract is loaded.

**What the demo shows that A and B cannot:**

1. *Catalog page* lists `finance_demo.*` rows tagged **private**, crawled by the same job as the public tables, with row counts and a "restricted to: orchestrator SA" line.
2. *A question that joins private and public in one attested answer* — e.g. "default rate for applicants with more than three bureau inquiries, versus the national unemployment rate that year" (Home Credit + `bls.unemployment_cps`) — with the receipt naming both sources and their trust tiers.
3. *Access enforcement*: the same question asked in the public pack is refused (pack isolation), and a second Cloud Run identity without dataset IAM gets a clean BigQuery permission error in the trace rather than data — the "your controls still apply" moment.
4. *Freshness*: if the CFPB extract is loaded, the vintage line changes from "mirror ends 2023-03" to "internal extract, loaded 2026-09-xx", on the same template.

**Effort:** about one week — half a day of loads (GCS + `bq load`, licences checked: Home Credit competition terms, PaySim CC BY-SA 4.0), one day for the OKF docs and `visibility` field in loader/catalog/receipt, two days for the four templates and their golden questions, one day for the IAM demonstration and a second identity, half a day for chips and the catalog badge.

**Sequencing:** D before C. D is what a Gateway buyer needs to see; C is a nice 40-second guardrail moment that can reuse D's PaySim table (a deliberately unbounded scan of it, or of `crypto_ethereum`) once D exists.

## 13. Backlog after D

Cluster a project-local copy of SEC `numbers` (cost); the deterministic attester; per-agent budgets and a second identity (needed for D's access demonstration anyway); the MCP surface so the §9 skills run as tools; the audit-pack export button; fresh CFPB extract refresh job.
