# Atlas Finance Pack — Implementation

Status: live at [atlasdata.world/finance](https://atlasdata.world/finance) since 3 September 2026 · use cases A, B live (golden 22/22: public 10, A 6, B 6) · **use case D (private internal data) built 4 September 2026, awaiting its data load, crawl and golden run** (§12) · code in [`srikanthbelwadi/atlas`](https://github.com/srikanthbelwadi/atlas) `main`.

This document describes what was built for the finance section, as built. The plan it implements is `atlas-finance-demo-plan.md` (use cases, data selection) and the design it follows is [`FINANCE-DESIGN.md`](https://github.com/srikanthbelwadi/atlas/blob/main/frontend/public/FINANCE-DESIGN.md) (also at `/finance/design`). Section 12 covers the internal-enterprise-data use case D — why A and B could not demonstrate it, and what was built to.

## 1. What the finance pack is

A second catalog inside the same Atlas deployment, isolated from the public demo by a **pack** boundary, that answers two finance use cases over public BigQuery datasets standing in for bank-internal systems:

- **A · Complaint & conduct intelligence** — the CFPB complaint database as a bank's complaint case-management system, joined to FDIC institutions for peer normalisation; five reviewed templates including narrative theming with verified quotes.
- **B · Filing-grounded fact-check & peer benchmark** — SEC EDGAR (API) and the SEC Financial Statement Data Sets (BigQuery) as a fundamentals warehouse, FDIC ratios as regulatory peer data; a two-source reconciliation, curated ratios, a SIC-code screen, and a paragraph fact-check that verifies claims through attested computations only.
- **D · Internal risk mart behind the same catalog** — a *private* dataset in our own project (a retail credit book and a payments ledger, Home Credit and PaySim shapes) catalogued by the same crawler, marked `visibility: private`, answered by four reviewed templates, and offered only to users holding the `finance.internal` entitlement. The demonstration that A and B cannot give: Atlas over data nobody outside can see, with the customer's access control still deciding who gets an answer.

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
                        access.split_candidates(user.entitlements) → visible | withheld (private, D)
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
| Access (D) | `visibility: private` + `access.entitlement` on OKF docs and crawled rows; private candidates withheld from discovery unless the user's Firestore `entitlements` include it; fetch-stage and ad-hoc-SQL checks as defence in depth | [`access.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/orchestrator/access.py) |

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
`template_id, title, version, reviewer, reviewed_on, stale_after, stale, lifecycle, trust, pack, visibility, entitlement, executor, sources[], queries[] {step, source_id, bytes_billed, row_count, params}, bytes_billed, tokens{plan, theme?, synthesize}, cost{…, generation_cost_usd?}, citation_template, unlocked_by, restricted_to`. For a private template `unlocked_by` names the entitlement that let this user run it. Rendered by [`ReceiptCard.tsx`](https://github.com/srikanthbelwadi/atlas/blob/main/frontend/components/ReceiptCard.tsx).

## 3. Catalog inventory (`okf-catalog/packs/finance/`)

### 3.1 Reviewed table documents

| Document | Stands in for | Vintage (confirmed 2026-09-03) |
|---|---|---|
| [`cfpb_complaints/complaint_database.md`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/bigquery/cfpb_complaints/complaint_database.md) | complaint case-management system | 3.46 M complaints, 2011-12-01 → **2023-03-23**; 1.25 M narratives |
| [`fdic_banks/institutions.md`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/bigquery/fdic_banks/institutions.md) | entity master + peer financials | late-2022 snapshot |
| [`sec_quarterly_financials/overview.md`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/bigquery/sec_quarterly_financials/overview.md) | fundamentals warehouse | filings to 2020-12-31; **fiscal 2019** last complete 10-K year |

Crawled (machine-confirmed) rows for the pack: `cfpb_complaints` (1 table), `fdic_banks` (2), `sec_quarterly_financials` (10), `bls` (9, shared with public), and — after `scripts/finance_phase_d.sh` — `atlas-ard-okf.finance_demo` (4 private tables, `visibility: private`).

Private table documents (use case D, [`okf-catalog/packs/finance/private/finance_demo/`](https://github.com/srikanthbelwadi/atlas/tree/main/okf-catalog/packs/finance/private/finance_demo)): [`loan_applications.md`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/private/finance_demo/loan_applications.md) (the credit book: one row per application with outcome, segments, bureau-inquiry counts), [`bureau_credits.md`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/private/finance_demo/bureau_credits.md) (prior credits per applicant), [`installment_payments.md`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/private/finance_demo/installment_payments.md) (instalment schedule vs payments), [`payment_transactions.md`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/private/finance_demo/payment_transactions.md) (the payments ledger with fraud labels). All carry `visibility: private`, `access.entitlement: finance.internal`, and `restricted_to`.

### 3.2 Attested computations (16: 12 public-data + 4 private)

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
| 🔒 [`ac.hc_default_rate_by_segment`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/hc_default_rate_by_segment.md) | D1 default rate by one of ten segments, small segments folded, book rate on every row | bigquery (private) | <$0.001 |
| 🔒 [`ac.hc_bureau_history_vs_default`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/hc_bureau_history_vs_default.md) | D2 inquiries / prior credits / overdue history → default rate, per-applicant aggregation | bigquery (private, 2 tables) | <$0.001 |
| 🔒 [`ac.hc_installment_delinquency_vintage`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/hc_installment_delinquency_vintage.md) | D3 late / short-paid share by month before application, split by later outcome | bigquery (private, 2 tables) | ~$0.003 |
| 🔒 [`ac.paysim_structuring_pattern`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/attested-computations/paysim_structuring_pattern.md) | D4 repeated just-under-threshold transfers within a sliding window vs the legacy flag | bigquery (private) | ~$0.002 |

Entity crosswalk: [`entity_xref.csv`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/entity_xref.csv) (63 rows, every CFPB string, FDIC cert and CIK verified against the data with [`infra/finance/xref_check.sql`](https://github.com/srikanthbelwadi/atlas/blob/main/infra/finance/xref_check.sql)), loaded into `atlas-ard-okf.finance_pack.entity_xref` by [`infra/finance/setup.sql`](https://github.com/srikanthbelwadi/atlas/blob/main/infra/finance/setup.sql).

## 4. The fact-check skill (server side)

[`skills/filing_fact_check.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/orchestrator/skills/filing_fact_check.py): claim extraction (plan-tier model, response schema) → per claim, `ac.sec_fact_reconcile` (levels) or `ac.sec_ratio_by_year` (ratios) through the shared `_fetch_one` → verdicts `verified` / `differs` / `not_verifiable` / `no_reported_value` → `verdict_table` visualization + receipt. Growth or percentage-change claims about level metrics are *not verifiable* by design; a byte-cap hit on one claim becomes that claim's verdict rather than aborting the check. No ad-hoc SQL exists in this path.

## 5. Frontend

`/finance` (Ask | Fact-check a paragraph; grouped example chips including an "Internal risk mart (private)" group; trace; answer; access card; receipt; walkthrough), `/finance/catalog` (every source with trust, visibility 🔒, reviewer, freshness, expandable SQL — a private entry's SQL and notes are only served to entitled accounts; a "Private" filter and the caller's own entitlements in the banner), `/finance/design`, `/finance/implementation` (this document), `/admin` (approval plus a per-user entitlement toggle). Components: `ReceiptCard` (now with the access line), `TrustChip` + `VisibilityChip`, `AccessCard` (the withheld-sources refusal card, or the "unlocked by" note), `FactCheckBar`, `CatalogTable`, `VerdictTableViz` (in `AnswerCanvas`); `TracePanel` shows multi-step fetches, quote verification, claim verdicts and withheld sources. Same design tokens as the public demo (IBM Plex; navy/amber/teal).

## 6. Data vintage — and why the demo years are 2022 and 2019

Confirmed by query on 2026-09-03 ([`xref_lookup.sql`](https://github.com/srikanthbelwadi/atlas/blob/main/infra/finance/xref_lookup.sql), [`sec_vintage.sql`](https://github.com/srikanthbelwadi/atlas/blob/main/infra/finance/sec_vintage.sql)): the CFPB mirror's public pipeline stopped on 2023-03-23; the SEC bulk mirror's last filings are dated 2020-12-31 (fiscal 2019 is the last complete 10-K year); the FDIC snapshot is late 2022. The EDGAR API is current. Every template default, the planner glossary and the example questions are pinned accordingly, and answers name the vintage. This is also the strongest argument for §12: the public mirrors are stand-ins, and the same catalog over a *current* internal extract is the product.

## 7. Golden results and cost

| Set | Result | Notes |
|---|---|---|
| `public_regression.yaml` | 10/10 | run against the finance-enabled revision before promotion |
| `finance_a.yaml` | 6/6 | A4 theming ~$0.05, 2–4 min; A6 honest refusal |
| `finance_b.yaml` | 6/6 | B1 reconcile $0.13; B4 fact-check $0.26 (four claims); B5 screen $0.14; B6 honest refusal |
| `finance_d.yaml` | pending (needs the load + crawl + redeploy in §12.5) | entitled account: D1–D4 attested with private receipts, D6 ad-hoc over the private ledger, D7 public question unaffected |
| `finance_d_noaccess.yaml` | pending | same account without the entitlement: D5/D5b refused naming the withheld sources, D5c (SQL naming the private table in the question) never touches `finance_demo`, D7b public question unaffected |

Runner: [`scripts/golden_run.py`](https://github.com/srikanthbelwadi/atlas/blob/main/scripts/golden_run.py) (asserts path, source, bound params, bytes, quotes, verdicts; writes a markdown report). Unit tests: [`tests/test_finance_catalog.py`](https://github.com/srikanthbelwadi/atlas/blob/main/tests/test_finance_catalog.py), 57 tests, no GCP required — public catalog unchanged, pack isolation, every template (now 16) parses (sqlglot) and binds its parameters and touches only declared sources, tag-map sync, composite graph, quote verification, verdict arithmetic, and for D: private docs confined to `finance_demo`, no public doc reads it, the withheld split, the fetch-stage and SQL-scan refusals, the private receipt fields, and the synthetic generator's columns covering `private_setup.sql`. The four private templates were additionally executed end to end on the synthetic data in DuckDB (BigQuery-isms translated) before commit.

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
| **D: load the private mart** | [`scripts/finance_private_load.sh`](https://github.com/srikanthbelwadi/atlas/blob/main/scripts/finance_private_load.sh) `[DATA_DIR]` — Kaggle originals or the synthetic set from [`scripts/finance_private_synth.py`](https://github.com/srikanthbelwadi/atlas/blob/main/scripts/finance_private_synth.py) (generated automatically if the directory is empty) → private bucket → `finance_demo_raw` → curated `finance_demo` via [`infra/finance/private_setup.sql`](https://github.com/srikanthbelwadi/atlas/blob/main/infra/finance/private_setup.sql) → IAM check |
| **D: crawl, redeploy, entitle** | [`scripts/finance_phase_d.sh`](https://github.com/srikanthbelwadi/atlas/blob/main/scripts/finance_phase_d.sh) — crawler rebuild + finance crawl, orchestrator redeploy (tagged revision), IAM readout, grant `finance.internal` to the test account |
| **D: grant / revoke an entitlement** | `/admin` toggle, or [`scripts/finance_entitle.py`](https://github.com/srikanthbelwadi/atlas/blob/main/scripts/finance_entitle.py) `<email> --grant\|--revoke finance.internal` (needs `google-cloud-firestore` in the venv) |

Environment on the orchestrator revision: `ATLAS_PACKS_ENABLED=public,finance`; optional `ATLAS_TEMPLATE_BYTE_CAP_MAX` (default 40 GB).

## 9. Agent skills (SKILL.md)

The plan's Layer-3 skills — procedures an orchestrating agent follows *through* Atlas's API — live in [`skills/finance/`](https://github.com/srikanthbelwadi/atlas/tree/main/skills/finance) ([index](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/README.md)):

| Skill | Purpose |
|---|---|
| [`complaint-root-cause`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/complaint-root-cause/SKILL.md) | trend → movers → peer normalisation → verified themes → brief with receipts |
| [`conduct-outcome-monitor`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/conduct-outcome-monitor/SKILL.md) | vulnerable-cohort outcome gaps by product and year, definitions stated |
| [`filing-fact-check`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/filing-fact-check/SKILL.md) | drive `/skills/filing-fact-check` and mark up the paragraph with verdicts |
| [`peer-benchmark`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/peer-benchmark/SKILL.md) | size-defined peer table with the FDIC-vs-XBRL definition chosen explicitly |
| 🔒 [`credit-portfolio-monitor`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/credit-portfolio-monitor/SKILL.md) | D · portfolio-risk review over the bank's own loan book: segments, bureau gradient, early-warning series, private receipts kept |
| 🔒 [`payments-structuring-screen`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/payments-structuring-screen/SKILL.md) | D · structuring screen over the bank's own ledger with a sensitivity pass and the legacy blind-spot count |
| 🔒 [`private-data-access-check`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/private-data-access-check/SKILL.md) | D · which private sources an account can query, with a live enforcement check, before planning on them |
| [`receipt-to-audit-pack`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/receipt-to-audit-pack/SKILL.md) | receipt + walkthrough → replayable model-risk artefact |
| [`attested-computation-author`](https://github.com/srikanthbelwadi/atlas/blob/main/skills/finance/attested-computation-author/SKILL.md) | draft a new reviewed template from repeated ad-hoc questions |

They are ready to run from Claude Code (or any MCP host) against the deployed API today; the MCP wrapper that would expose `ask` / `fact_check` / `catalog` as tools is the plan's phase 4 and is not built.

## 10. Not built (from the plan), by design

Optional showpiece C (AML on chain data), the deterministic attester (SQL-text hash check on execution), per-agent-identity budgets, the audit-pack export button in the UI, the MCP surface. The skills in §9 are the agent-side half of several of these; the platform-side half is the phase-3/4 backlog.

## 11. Known limits

Public mirrors are dated (§6). SEC bulk scans cost ~$0.13 each because `numbers` is unpartitioned and unclustered — clustering a copy in the project would make them pennies. Discovery is embedding-only; a question that names "banks" leans toward FDIC sources, which is why the screening question names the SEC filings explicitly. The crosswalk covers ~40 banks and ~20 large filers; anything outside it resolves to "no evidence" rather than a guess.

## 12. Internal (private) enterprise data — use case D

### 12.1 Why A and B could not show it

Neither A nor B queries private data: every source is `bigquery-public-data.*` or the public EDGAR API, and every template had `visibility: public`. The only object in our own project was `finance_pack.entity_xref`, a reviewed helper table. So the pack proved discovery, attestation, cost control and receipts over *public stand-ins*, and asserted — without showing — that the same path works over a customer's warehouse. A buyer's first question is "show me this over *my* data with *my* access controls", and that is a different property from anything in A or B.

Use case C in the plan (AML fund-flow on public chain data) does not answer it either — C's point is the budget stop on a multi-terabyte public table. The internal-data demonstration got its own label, **use case D — Internal risk mart behind the same catalog**, and was built in preference to C.

### 12.2 What was built

| Component | Choice | Why |
|---|---|---|
| Private datasets | `atlas-ard-okf.finance_demo_raw` (loads, never catalogued) and `atlas-ard-okf.finance_demo` (four curated tables), US, no `allUsers` / `allAuthenticatedUsers` binding | same project the public pack reads from, so "same crawler, same executor, different IAM" is literally true; the load script prints the ACL and fails the check if a public binding ever appears |
| Credit book | [`loan_applications`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/private/finance_demo/loan_applications.md), [`bureau_credits`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/private/finance_demo/bureau_credits.md), [`installment_payments`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/private/finance_demo/installment_payments.md) — the Home Credit Default Risk shape (applications × 18 curated columns, bureau history, instalment ledger) | the most realistic relational *decisioning-mart* schema in the public domain |
| Payments ledger | [`payment_transactions`](https://github.com/srikanthbelwadi/atlas/blob/main/okf-catalog/packs/finance/private/finance_demo/payment_transactions.md) — the PaySim shape (hourly step, type, amount, balances, fraud label, legacy flag) | a core-banking transaction log a financial-crime team screens |
| Data source | either the Kaggle originals (Home Credit: `application_train.csv`, `bureau.csv`, `installments_payments.csv`; PaySim renamed `paysim.csv`) **or** the synthetic set from [`scripts/finance_private_synth.py`](https://github.com/srikanthbelwadi/atlas/blob/main/scripts/finance_private_synth.py) — same column names, planted structure (default rises with inquiries and falls with income; late payment clusters before application; twelve structuring accounts), fixed seed, no real person | the demo needs the *shape* of internal data, not those rows; the synthetic path removes the Kaggle-account dependency and runs in seconds. [`private_setup.sql`](https://github.com/srikanthbelwadi/atlas/blob/main/infra/finance/private_setup.sql) curates either into the same four tables |
| Catalog | four private table docs + four private templates (§3), all `visibility: private`, `access.entitlement: finance.internal`, `restricted_to` stated; the crawler catalogues `finance_demo` through [`targets.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/crawler/targets.py)'s new fourth tuple element and stamps `visibility` / `entitlement` into each row's metadata with "PRIVATE" in the embedded text | the same crawl job, the same embeddings table, the same discovery query — only a marking differs |
| Access model | Firestore `users/{uid}.entitlements: [string]`; `require_approved_user` returns them with the approval; [`access.py`](https://github.com/srikanthbelwadi/atlas/blob/main/backend/orchestrator/access.py) splits discovery candidates into visible / withheld, refuses a private template at fetch time, and scans ad-hoc SQL for private dataset references | approval says "may use Atlas"; an entitlement says "may be offered this private source". BigQuery IAM stays what decides what the service account can *read* — Atlas never re-implements IAM in Python |
| Refusal semantics | if the best-matching source overall is withheld, Atlas refuses (`refused: not_entitled`) and names the withheld sources by id and title only — never their contents, never a public stand-in answer dressed up as the internal one | the "your controls still apply" moment, made visible rather than silent |
| Receipt | private answers carry `visibility: private`, `unlocked_by: finance.internal`, `restricted_to` | the artefact a reviewer keeps now says *how* the answer was unlocked |
| Frontend | `AccessCard` (withheld list or "unlocked by"), `VisibilityChip` 🔒 on catalog rows and receipts, "Private" catalog filter, the caller's entitlements in the catalog banner, entitlement toggle per user on `/admin`, a private example-chip group | |
| Admin API | `GET /admin/entitlements` (every entitlement the catalog names, with its sources), `POST /admin/users/{uid}/entitlements` (replace list, unknown names rejected) | entitlements are defined by the catalog, not typed free-hand |
| Planner | finance glossary gains the internal-data vocabulary ("our", "the bank's own", "internal" → private sources; the four routings; no calendar dates; never answer an internal question from a public stand-in) and the synthesis rule names internal sources as "(private)" | |

### 12.3 What the demo shows that A and B cannot

1. **Catalog page** lists `finance_demo.*` rows tagged 🔒 private with their row counts, crawled by the same job as the public tables, with "restricted to: orchestrator service account (dataset IAM); Atlas users with the finance.internal entitlement", and the caller's own entitlements in the banner.
2. **An entitled account** asks "What is our default rate by income band…" and gets an attested answer whose receipt reads *private · unlocked by entitlement finance.internal*.
3. **The same question from an account without the entitlement** is refused: the trace's discover line says "1 private source withheld … the best match is among them, so Atlas will not answer from a public stand-in"; the answer card names `ac.hc_default_rate_by_segment` and nothing more; `/admin` is where the grant happens, one click, effective on the next request.
4. **Defence in depth**: a question that spells out the private table name in SQL terms never reaches BigQuery for an unentitled user — the SQL scan refuses it before the dry run.
5. **Public questions are unaffected** either way (D7 / D7b in the golden sets).
6. **IAM readout** (`finance_phase_d.sh` step 3): the dataset ACL and the project's BigQuery roles, showing the orchestrator identity and no public principal — the "another principal is denied" half of the story without needing a second Cloud Run service.

### 12.4 Deliberate limits

The Home Credit and PaySim shapes carry no calendar dates or geography (the sources are anonymised), so the private+public join the recommendation sketched ("default rate vs the national unemployment rate that year") cannot be made honestly and was not built; the templates say "months before application" and the glossary forbids implying a period. The fresh-CFPB-extract-as-internal-table idea (`source_override`) remains backlog. Entitlement is one string today (`finance.internal`); row-level or column-level policy would be a BigQuery policy-tag concern, not an Atlas one.

### 12.5 Bringing D live (Bel's commands)

```
# 1. data → private datasets (synthetic by default; put Kaggle files in ~/Documents/ARD_UKF/data/finance_demo first to use them)
scripts/finance_private_load.sh 2>&1 | tee ~/Documents/ARD_UKF/logs/finance_private_load.log
# 2. crawl + redeploy the tagged revision + IAM readout + entitle the test account
.venv/bin/pip install google-cloud-firestore
scripts/finance_phase_d.sh 2>&1 | tee ~/Documents/ARD_UKF/logs/finance_phase_d.log
# 3. golden runs (entitled, then not)
python scripts/golden_run.py --base $BASE --token "$(scripts/firebase_token.sh)" --set tests/golden/finance_d.yaml --report ~/Documents/ARD_UKF/logs/golden_finance_d.md
python3 scripts/finance_entitle.py atlas-test@atlasdata.world --revoke finance.internal
python scripts/golden_run.py --base $BASE --token "$(scripts/firebase_token.sh)" --set tests/golden/finance_d_noaccess.yaml --report ~/Documents/ARD_UKF/logs/golden_finance_d_noaccess.md
python3 scripts/finance_entitle.py atlas-test@atlasdata.world --grant finance.internal
# 4. public regression on the same revision, then promote
python scripts/golden_run.py --base $BASE --token "$(scripts/firebase_token.sh)" --set tests/golden/public_regression.yaml --report ~/Documents/ARD_UKF/logs/golden_public_after_d.md
gcloud run services update-traffic atlas-orchestrator --region us-central1 --to-latest
```

## 13. Backlog after D

Cluster a project-local copy of SEC `numbers` (cost); the deterministic attester; per-agent budgets; a second Cloud Run identity without dataset IAM for a live "permission denied" trace; the MCP surface so the §9 skills run as tools; the audit-pack export button; a fresh CFPB extract loaded into `finance_demo` behind `source_override` so A's templates run on a *current* private table; row/column policy tags on `finance_demo`; optional C reusing the private ledger for the byte-cap showpiece.
