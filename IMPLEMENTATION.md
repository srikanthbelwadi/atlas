# Atlas — Implementation

<p class="doc-status">Live at <a href="https://atlasdata.world">atlasdata.world</a> (public pack) and <a href="https://atlasdata.world/finance">/finance</a> (finance pack) · 17 reviewed templates, 8 reviewed table documents, ~40 crawled datasets across two packs · golden sets 32/32 · code in <a href="https://github.com/srikanthbelwadi/atlas">srikanthbelwadi/atlas</a> · updated 4 September 2026</p>

This is the engineering companion to the demo, written for developers and
technical decision makers: what Atlas is, how it is built, why it is built
that way, which data it answers from, and how the **finance pack** — the first
vertical built on it — reuses every part of the platform rather than adding
a parallel one. It is reference material and needs no sign-in.

## 1. What Atlas is

Atlas is a natural-language front door to large-scale data. A signed-in
user asks a plain-English question — "What was the average temperature in
Chicago in 2023?" — and gets back a grounded, cited answer with an
appropriate chart or table, generated from a real, guarded query against a
described data source, never from the model's own knowledge. Every step the
system takes to get there is streamed live to the browser and left
inspectable afterward: which data sources it considered, why it picked the
one it used, the literal query it ran, and what that query cost.

The approach is source-agnostic. Any data store or API that can be described
once in the Open Knowledge Format — an enterprise data warehouse, an
operational database, an internal or third-party REST API — becomes
discoverable, plannable, and queryable through the same pipeline, with the
same cost guardrails and the same trust tiers. BigQuery is the first
executor and the one this instance is pointed at. Nothing in the design
depends on the data being public.

One deployment serves more than one catalog. A **pack** is a named,
isolated slice of the catalog (§5.2): the original demo is the `public`
pack; the **finance pack** at `/finance` is the same platform pointed at
a different catalog — public datasets standing in for a bank's complaint
system, entity master and fundamentals warehouse, plus a genuinely private
internal risk mart that only entitled accounts can query (§5.4, §8.3); and
the **places pack** at `/places` points it at a source that is not a
table at all — Google Data Commons' knowledge graph of ~250,000 reported
statistics for countries, states, counties and cities, reached through
its REST API behind two reviewed templates (§8.4). The finance pack is
described in one place, §9; everything it and the places pack rely on —
packs, entitlements, executors, receipts, the agent skills — is a platform
feature documented in the sections before it.

## 2. Where it came from

Atlas is a derivative of [NeuralKG](https://github.com/rvguha/Neuralkg)
(Apache-2.0), a general-purpose agentic query engine over ~20 US
authoritative sources (SEC, Census, Treasury, IRS Form 990, CDC, federal
grants). NeuralKG's central idea — describe each data source once in
the [Open Knowledge Format](https://okf.md/spec/) (OKF), make it discoverable
through an [Agentic Resource Discovery](https://agenticresourcediscovery.org/spec/)
(ARD) index, and run every question through the same
**discover → plan → fetch → check → synthesize** pipeline instead of writing
per-source query code — is the foundation this project keeps.

What changed, and why:

| Kept from NeuralKG | Replaced or newly built for Atlas |
|---|---|
| The five-stage discover/plan/fetch/check/synthesize pipeline shape | A guarded BigQuery executor as the first-class execution path for large tabular stores, alongside OKF-described APIs — the catalog is a curated set of BigQuery datasets plus the SEC EDGAR API, not NeuralKG's original ~20 REST sources |
| Describing sources once via OKF documents, never per-source code | Byte-capped execution (dry-run estimate + hard `maximum_bytes_billed` + wall-clock timeout) as the default fetch path, replacing the generic REST accessor |
| The "plan" stage validating whether a source can structurally answer a question before fetching | Vertex AI Gemini under strict JSON-schema output for both planning and synthesis, on Google Cloud infrastructure |
| Citations with a provenance/trust label on every answer | A live SSE trace of every stage as it runs, plus a persisted post-hoc "walkthrough" (sources considered, queries run, backtracks, real token cost) — NeuralKG's original UI showed only a finished answer |
| — | Firebase-Auth-gated access control: admin approval queue, pre-approved-email allowlist, per-user monthly budget guardrail in Firestore, and per-user **entitlements** that gate private catalog entries |
| — | A scheduled crawler that builds the ARD/OKF discovery index directly from a store's own schema metadata (BigQuery `INFORMATION_SCHEMA` today), so table descriptions can't hallucinate what a table contains |
| — | Packs: several isolated catalogs served by one deployment, with pack-specific planner vocabulary and executors |
| — | Receipts: a signed-off record under every attested answer (template version, reviewer, freshness, every query step, cost) |
| — | Entirely new Next.js frontend — none of NeuralKG's original frontend code is reused |

## 3. Tech stack

**Backend** — Python 3.12, FastAPI (`backend/orchestrator/main.py`) on
Cloud Run, `google-genai` 0.7.0 against Vertex AI Gemini (`gemini-2.5-flash`
for planning, `gemini-2.5-pro` for synthesis), `google-cloud-bigquery` for
both the query engine and the ARD catalog, `google-cloud-firestore` for
users, usage and entitlements, `firebase-admin` for ID-token verification,
`sse-starlette` for the streamed trace, `python-frontmatter` + `pyyaml` for
reading OKF documents, `sqlglot` in the test suite to parse every reviewed
template.

**Frontend** — Next.js 14 (App Router), deployed on Firebase App Hosting
(which runs it on Cloud Run under the hood). Firebase Auth (Google sign-in)
client-side; the backend's SSE stream is consumed by hand rather than the
native `EventSource` API, since `EventSource` can't attach the Firebase ID
token every request needs. Design system: IBM Plex Serif/Sans/Mono, a navy
(`#16324a` / dark `#9fc3de`) and terracotta-accent (`#a6501c` / dark
`#e08a4f`) palette defined as CSS custom properties with a
`prefers-color-scheme: dark` variant, and a teal secondary accent
(`#1f6f66`) for the human-reviewed trust tier. All visualization kinds
(table, bar, line, KPI cards, verdict table; infographic composes from KPI
cards; map falls back to a table) are hand-drawn inline SVG — no charting
library.

**Infrastructure** — Google Cloud only: Cloud Run (orchestrator), Cloud Run
Jobs (crawler), Firebase App Hosting (frontend), Firestore (users, usage,
entitlements), BigQuery (the public datasets, the private `finance_demo`
dataset, the `finance_pack.entity_xref` crosswalk and the `ard_catalog`
discovery index, queried with native `VECTOR_SEARCH`), Cloud Functions 2nd
gen (admin notification), Cloud Scheduler (weekly re-crawl of every pack),
Artifact Registry + Cloud Build (container images).

## 4. Architecture: discover → plan → fetch → check → synthesize

`backend/orchestrator/pipeline.py`'s `run()` is an async generator; every
stage yields one or more `{"event": "<stage>.<phase>", "data": {...}}`
dicts consumed directly by `main.py`'s `EventSourceResponse` and rendered
live by the frontend's `TracePanel`. The same five stages NeuralKG used,
with the pack, the caller's entitlements and the executor fan-out added:

```
frontend (Next.js, Firebase App Hosting)              orchestrator (FastAPI, Cloud Run — one service)
/            public demo ─────── POST /ask {question} ─────────▶ pipeline.run(q, user, pack="public")
/finance     ask + fact-check ── POST /ask {question, pack} ────▶ pipeline.run(q, user, pack="finance")
             └── fact-check ──── POST /skills/filing-fact-check ▶ skills.filing_fact_check.run
/finance/catalog ─────────────── GET /packs/{pack}/catalog ─────▶ OKF docs + crawled rows for the pack
                                                                 │
                     discovery.discover(q, pack) ◀───────────────┘
                       ├─ VECTOR_SEARCH over ard_catalog.embeddings WHERE metadata.pack = @pack
                       └─ in-process ranking of okf-catalog/ documents WHERE pack ∈ doc.packs
                     access.split_candidates(user.entitlements) → visible | withheld (private sources)
                     planner (Gemini flash) + pack glossary → attested template or ad-hoc SQL
                     fetch → executor: bigquery | bigquery_sample_llm | composite |
                                       sec_edgar | sec_edgar_annual | sec_ratio
                     check (non-empty, quotes verified, backtrack) → synthesize (Gemini pro)
                     → answer {narrative, citations, visualization, walkthrough, receipt?, access?}
```

**Discover** (`discovery.py`) — the question is embedded once
(`text-embedding-005`, 768 dimensions) and matched against two candidate
pools, merged and deduplicated by score: BigQuery `VECTOR_SEARCH` over
`ard_catalog.embeddings` (the crawler-maintained index of real tables), and
an in-process cosine ranking over the hand-authored `okf-catalog/` bundle
(reviewed table documents and Attested Computation templates). Both pools
are pre-filtered by pack. Both return the same candidate shape —
`{source_id, kind, title, description, trust, type, score, visibility,
entitlement}` — so nothing downstream cares which pool a candidate came
from. The public pack keeps the top 6 candidates, the finance pack the top
8 (it has more templates competing for a question). Before planning, the
candidates are split into *visible* and *withheld* by the caller's
entitlements (§5.4).

**Plan** (`llm.py`'s `classify_and_plan`) — a fast-tier Gemini call decides
the question's shape (point / ranking / aggregate / trend / status) and
picks one candidate. If the chosen candidate is an OKF `AttestedComputation`
(a human-reviewed, parameterized SQL template), the model only extracts
parameter values from the question's wording — the SQL text itself never
changes. If it's a plain table, the model drafts ad-hoc SQL against the real
column list the crawler captured (never invented from a table's title). A
pack may append a **glossary** to the planner prompt (`packs.py`): the
finance glossary maps domain vocabulary ("timely response", "peer banks",
"our loan book") to the templates that answer it, states the data vintage,
and forbids answering a question about internal data from a public
stand-in. The public pack's prompts are byte-identical to what they were
before packs existed (unit-tested).

**Fetch** (`_fetch_one` → the executor the document declares, §6) — every
BigQuery query, templated or ad-hoc, goes through the same guarded two-step
path: a zero-cost dry run checks the estimated bytes scanned against a byte
cap (higher for reviewed templates than for ad-hoc SQL), then the real query
runs with `maximum_bytes_billed` set to that same cap as a hard server-side
backstop and a wall-clock timeout. A dry run and the real scan can differ
(partitioned tables, cached results) — the hard cap, not the estimate alone,
is what actually protects the budget. Multi-step executors record one
`queries_executed` entry per step.

**Check** — the fetched rows are sanity-checked (non-empty) before being
handed to synthesis; an executor may add its own check, such as verifying
that every quoted excerpt from a narrative sample exists verbatim in the
sampled row it cites. An empty result or a fetch-time exception triggers a
**backtrack**: retry against the next-best candidate, up to
`MAX_BACKTRACKS` (1) additional attempt. Every backtrack redrafts a fresh,
single-candidate plan rather than reusing the original.

**Synthesize** (`llm.py`'s `synthesize`) — a pro-tier Gemini call, given
only the fetched rows (never the model's own training knowledge), produces
a narrative, a citation list with trust level, and a visualization spec
under a strict JSON schema (`PRESENTATION_SCHEMA`) so the frontend always
gets a shape it can render.

Every stage's events accumulate into a `walkthrough` dict attached to the
terminal `answer` or `error` event — sources considered (and withheld),
every query actually executed (SQL + bound params + bytes billed), every
backtrack and why, and real per-call token usage. A failed or refused
question is exactly as inspectable as a successful one.

## 5. The catalog

### 5.1 OKF documents and the crawler

Every source Atlas can answer from is an OKF document. Two kinds matter here:

- **`Table`** documents describe one queryable table — its columns, what it
  covers, what it stands in for, and its vintage. Most are written by the
  **crawler** (`backend/crawler/main.py`, a Cloud Run Job run weekly): for
  each `(project, dataset, packs)` in the curated target list
  (`crawler/targets.py`) it enumerates tables through `INFORMATION_SCHEMA`,
  builds a deterministic, template-driven description from the real schema
  (never model-generated, so it cannot hallucinate what a table contains),
  records the exact `row_count` and `size_gb`, embeds the text and upserts
  it into `ard_catalog.embeddings`. A few tables also have a hand-written
  document in `okf-catalog/` that adds meaning the schema alone can't carry
  (e.g. that `date_received` in the complaint database is when the CFPB
  received the complaint, not when the event occurred).
- **`AttestedComputation`** documents are reviewed, parameterized templates:
  a fixed SQL text (or, for API sources, a fixed accessor call), a declared
  parameter list with types and defaults, the sources the template touches,
  a `cost_profile` (expected bytes, optional per-template byte cap), a
  reviewer, a review date and a `stale_after` date. The planner binds
  parameter values; it never edits the text. In an enterprise deployment
  this directory is where a data team's sanctioned metric definitions live,
  version-controlled and reviewed like code.

The crawler runs unchanged against any project or dataset its service
account can read — the private `finance_demo` dataset (§8.3) is catalogued
by the same job, into the same embeddings table, with only a visibility
marking added.

### 5.2 Packs — isolation at every layer

A pack is a named slice of the catalog that discovery never mixes with
another. `public` is the default everywhere a pack isn't named; `finance`
and `places` are the other two. Every layer knows about packs, and every
default keeps the public demo exactly as it was:

| Layer | Mechanism | Where |
|---|---|---|
| OKF documents | `pack: finance`, or `packs: [public, finance]` for a template shared by both (the SEC EDGAR metric template is); absent = `public`. Pack documents live under `okf-catalog/packs/<pack>/` | `backend/accessor/okf_loader.py` |
| Crawler | each target lists its packs; a non-public row's `doc_id` is suffixed `#<pack>` and carries `metadata.pack` | `backend/crawler/targets.py`, `crawler/main.py` |
| Discovery | the `VECTOR_SEARCH` base table and the hand-authored documents are both pre-filtered by pack | `backend/orchestrator/discovery.py` |
| API | `POST /ask` takes an optional `pack`; a pack not listed in `ATLAS_PACKS_ENABLED` is refused with a 400, never answered from the public catalog | `backend/orchestrator/main.py` |
| Prompts | a pack's glossary and synthesis rule are appended only for that pack; the public prompts are byte-identical (unit-tested) | `backend/orchestrator/packs.py`, `llm.py` |
| Budget | one $100/user/month ceiling across packs; the usage record gains a `by_pack` breakdown | `backend/orchestrator/guardrails.py` |
| Frontend | `/finance/*` routes return 404 unless `NEXT_PUBLIC_ATLAS_FINANCE_ENABLED=true`, `/places/*` unless `NEXT_PUBLIC_ATLAS_PLACES_ENABLED=true`; the header links are under the same flags | `frontend/app/finance/layout.tsx`, `lib/finance.ts`, `app/places/layout.tsx`, `lib/places.ts` |

The isolation is tested from both sides: the public regression set (§12)
includes a CFPB question that must *not* find a finance source when asked
in the public pack, and the finance sets include public questions that must
answer identically inside the finance pack.

### 5.3 Trust tiers

Every answer carries a citation naming the exact table or Attested
Computation used and its OKF trust tier:

- **`human-reviewed`** — a curated `AttestedComputation` template, or a
  hand-written table document, written and reviewed by a person, where only
  parameter values are model-supplied.
- **`machine-confirmed`** — a table described by the crawler directly from
  the store's own schema metadata (deterministic, template-driven text —
  never model-generated) but not reviewed by a person.
- **`unverified`** — reserved for OKF documents that carry neither
  attestation; not currently produced by anything in Atlas's own catalog
  but part of the trust model any future non-crawled source would use.

This is a direct implementation of OKF v0.2's three-tier trust-signal model
(`verified` absent / machine-only / `human:<id>`), surfaced end to end: the
crawler writes it into `ard_catalog.embeddings`' metadata, `discovery.py`
carries it into each candidate, and the frontend renders it as a colored
dot next to every citation chip and catalog row.

### 5.4 Visibility and entitlements (private catalogs)

A catalog entry is either **public** (the default) or **private**. A private
document — a table or a template — carries `visibility: private`, names the
**entitlement** an Atlas user must hold to be offered it
(`access.entitlement`, e.g. `finance.internal`) and states in prose who it
is `restricted_to`. The crawler stamps the same two fields into every row it
catalogues from a private dataset and prefixes the embedded text with
"PRIVATE", so a private table is findable by meaning but marked as such
from the moment it enters the index. Private entries are shown with a 🔒
throughout this document, in the catalog page and on receipts.

Two separate controls decide who sees what, and Atlas deliberately keeps
them separate:

- **IAM decides what the service can read.** The private dataset has no
  public binding; only the orchestrator's service account can read it.
  Atlas never re-implements IAM in Python.
- **Entitlements decide which Atlas users may be offered a private source.**
  `users/{uid}.entitlements` in Firestore is a list of strings, granted by
  an admin (a toggle on `/admin`, or `POST /admin/users/{uid}/entitlements`;
  unknown names are rejected — an entitlement exists only because a catalog
  document names it). Approval says "may use Atlas"; an entitlement says "may
  be offered this private source".

Enforcement (`backend/orchestrator/access.py`) is layered:

1. **Discovery** splits candidates into *visible* and *withheld*. A withheld
   source never reaches the planner, so the planner cannot route to it. The
   trace says how many sources were withheld and which entitlement they
   need, naming them by id and title only — never their contents.
2. **Refusal rather than substitution.** If the best-matching source overall
   is withheld, Atlas refuses (`refused: not_entitled`) instead of answering
   from the next-best public source. A question about "our loan book" is
   never answered from a public stand-in dressed up as the internal data.
   The refusal names the withheld sources and tells the user to contact
   their Atlas administrator if they believe they should have access.
3. **Fetch-stage check.** A private template is refused at execution time
   for a caller without its entitlement — defence in depth if a candidate
   ever reached the planner another way.
4. **Ad-hoc SQL scan.** Model-drafted SQL is scanned for references to
   private datasets; for an unentitled caller it is refused before the dry
   run, so a question that spells out the private table's name never
   reaches BigQuery.
5. **Catalog listing.** `GET /packs/{pack}/catalog` lists private entries to
   everyone (so a user can see what exists and ask for access) but strips
   the SQL text, notes and column detail unless the caller holds the
   entitlement.

Entitlement is one string per private source today. Row- or column-level
policy is a BigQuery policy-tag concern, not an Atlas one, and composes with
this model unchanged.

## 6. Executors and guardrails

An OKF document declares which **executor** runs it. All of them share the
same fetch entry point (`_fetch_one`), record their steps into the same
walkthrough, and are subject to the same per-user budget; they differ in
what a "query" is. The BigQuery executors are guarded in bytes; the API
executors (SEC EDGAR, Data Commons) are free per request, so their
guardrails are wall-clock timeouts, response-size caps and — for Data
Commons — entity and row caps on how far a "every county in…" expansion
may fan out.

| Executor | Used by | What it does | Guardrails |
|---|---|---|---|
| `bigquery` | crawled tables (ad-hoc SQL) and most templates | guarded SQL: dry run, then the real query with `maximum_bytes_billed` | ad-hoc cap; reviewed templates may declare `cost_profile.cap_bytes`, clamped to `ATLAS_TEMPLATE_BYTE_CAP_MAX` (40 GB) — needed for the ~21 GB SEC bulk scans |
| `bigquery_sample_llm` | `ac.cfpb_narrative_themes` | step 1: guarded SQL draws a bounded sample of free-text rows (≤ `max_sample_n` = 500); step 2: the plan-tier model themes the sample using the document's own prompt; the check stage verifies every quoted excerpt is a verbatim substring of the row it cites and drops the rest | sample cap; generation tokens priced separately (`token_usage.theme`) |
| `composite` | `ac.sec_fact_reconcile` | ordered `steps`, each another attested computation with a parameter map; `combine: reconcile` adds `delta_pct` and `agreement` between two independently sourced values | each step's own guardrails; one `queries_executed` entry per step |
| `sec_edgar` | `ac.sec_edgar_company_metric_by_year` (both packs) | resolves a company name or ticker to a CIK and returns one of 21 curated metrics by fiscal year, for one or more companies, from the EDGAR `company-facts` API | free API, 10 requests/s per IP |
| `sec_edgar_annual` | `ac.sec_fact_annual_api` | one 10-K fact per fiscal year selected the way an analyst would: latest period end, ≥ 300-day duration, latest filing | free API |
| `sec_ratio` | `ac.sec_ratio_by_year` | ROA, ROE, net margin, efficiency ratio and equity-to-assets from annual facts, with the averaging rule stated in the answer | free API |
| `datacommons_place` | `ac.dc_indicator_for_place` (places pack) | resolves place name(s) and a plain-language indicator through Data Commons' own resolvers (`/v2/resolve`, curated key map first), then one `/v2/observation` call; a single source facet for the whole answer, named on every row | free API (key required); 20 s timeout, 32 MB response cap, 3,500-place and 5,000-row caps, 6 h in-process cache |
| `datacommons_children` | `ac.dc_indicator_across_places` (places pack) | enumerates every place of a type inside a parent (`containedInPlace+`), fetches the indicator for all of them from one facet, ranks (latest per place or a named year) | same caps; a parent with more children than the cap is refused, never truncated |

The metric-to-XBRL-tag map lives once, in
`backend/accessor/xbrl_metrics.py`; the BigQuery template that reads the
same facts from the bulk data set (`ac.sec_fact_from_bq`) carries the same
map inline, and a unit test keeps the two identical. That is the pattern
for any further API source, private or public: one OKF document plus one
accessor module.

**Budget and cost guardrails**, in the order they apply to a request:

1. **Approval** — every request needs a Firebase ID token for an approved
   user (§10.1). New accounts are created `pending` and must be approved by
   an admin; addresses in `ATLAS_PREAPPROVED_EMAILS` skip the queue.
2. **Entitlement** — private sources are withheld or refused as in §5.4.
3. **Monthly ceiling** — `guardrails.py` keeps a per-user usage document in
   Firestore (bytes billed, model tokens, estimated USD, by pack) and blocks
   a request that would exceed $100 in the calendar month with a
   `guardrail.blocked` event before any query runs.
4. **Byte cap** — the dry run and `maximum_bytes_billed` above. A cap hit
   is reported as a normal, inspectable outcome (in the fact-check
   endpoint, as that one claim's verdict) rather than an exception.
5. **Wall-clock timeout** on every query and model call.

## 7. Answers: grounding, citations, receipts and the trace

**Grounding.** Atlas never lets the synthesis model answer from what it
already "knows." `synthesize()`'s prompt is explicit — compose the answer
"using ONLY the evidence provided — never invent figures" — and the
evidence it receives is exactly the rows `fetch` returned, nothing else.
When no source produces usable evidence at all — nothing discovered, every
candidate's fetch empty or failing — Atlas returns an explicit "I couldn't
find a data source that answers this well enough to cite" rather than
letting synthesis run on nothing.

**Citations.** Every answer names the exact table or Attested Computation
it used and that source's trust tier (§5.3). A reviewed template's document
states the `citation_template` the answer must use, so a figure from the
SEC financial statement data sets is always attributed to that mirror and
its vintage, not to "the SEC".

**Receipts.** An answer produced by an attested computation carries a
**receipt**, assembled by `pipeline.build_receipt` and rendered by
`ReceiptCard.tsx`:

```
template_id, title, version, reviewer, reviewed_on, stale_after, stale, lifecycle,
trust, pack, visibility, entitlement, executor, sources[],
queries[] {step, source_id, bytes_billed, row_count, params},
bytes_billed, tokens {plan, theme?, synthesize}, cost {…, generation_cost_usd?},
citation_template, unlocked_by, restricted_to
```

A receipt is the artefact a reviewer keeps: which reviewed definition
produced the number, who reviewed it and when, whether it is past its
`stale_after` date, every query step with its bound parameters and bytes,
and what the answer cost. For a private source, `unlocked_by` names the
entitlement that let this user run it. Ad-hoc answers carry the walkthrough
only — a receipt can never suggest a reviewer signed off on model-drafted
SQL.

**Live trace.** The frontend never shows a bare spinner. Every stage
streams its own `.started`/`.done` (and, for fetch/check,
`.progress`/`.backtrack`) events over SSE the moment they happen, rendered
by `TracePanel.tsx` as a stage-by-stage timeline that fills in live.
`classify_and_plan`'s JSON output includes a `reasoning` field — one
plain-language sentence on why this source and shape were chosen.
`discover.done` is narrated with the actual top candidates and their scores
and, where relevant, how many private sources were withheld and why.
Multi-step executors report each step; the narrative-theming executor
reports how many quotes it verified; the fact-check endpoint reports each
claim's verdict as it lands. A backtrack's redrafted plan emits its own
`plan.started`/`plan.done` pair with its own reasoning, so a question that
needed two routing attempts shows *both* decisions.

This was a deliberate, constrained design choice: the pinned
`google-genai==0.7.0` SDK predates Gemini's `thinking_config`/thought-summary
support, and every model call already requires strict `response_schema`
JSON output. Rather than bump the SDK for literal model "thinking" tokens,
the design makes the pipeline's *own* real decisions legible, with no new
dependency and no schema risk.

**Post-hoc walkthrough.** `Walkthrough.tsx` renders the full accumulated
record after a question finishes (success, refusal or failure): every
candidate considered with its score, which one was used, every backtrack
and its reason, the literal SQL and bound parameters for every query
actually executed, and a token/cost breakdown per model call.

## 8. Data sources

Atlas is source-agnostic: anything described in OKF and reachable by an
executor is queryable. The sources below are what this deployment answers
from, grouped by pack. Public datasets were chosen because they are large,
real and free to query without credentials — a convenient stand-in for the
private warehouses, operational stores and internal APIs an enterprise
deployment would point at instead. Entries marked 🔒 are **private**: they
live in a dataset nobody outside the project can read, and Atlas offers
them only to accounts holding the named entitlement.

Sizes are order-of-magnitude figures for the reader. The crawler records
the exact `row_count` and `size_gb` of every table it catalogs (from
`INFORMATION_SCHEMA.TABLE_STORAGE`) into `ard_catalog.embeddings`, which is
also what the byte-cap guardrail and the "large table" flag are computed
from. (This is the queryable data surface — Firestore's users/usage records
are infrastructure, not answerable content.)

### 8.1 Public pack

**BigQuery datasets (crawled, `machine-confirmed`).** Fourteen datasets
from the `bigquery-public-data` project, each expanded into its individual
tables via `INFORMATION_SCHEMA` at crawl time:

| Dataset | Covers | Approximate scale |
|---|---|---|
| `covid19_open_data` | COVID-19 cases, deaths, tests and government-response indicators, by day and place, worldwide | 1 main table, ~12 M rows, several GB; backs the public pack's SQL Attested Computation |
| `census_bureau_acs` | American Community Survey estimates — population, income, housing — by geography and 1-/5-year vintage | ~200 tables (geography × vintage); largest ~220 k rows (block group); each table is one vintage snapshot |
| `world_bank_health_population` | Country-level health and population indicators | ~2 M indicator rows across ~200 countries |
| `world_bank_wdi` | World Development Indicators — GDP, trade, macro/development series by country and year | ~20 M indicator rows |
| `epa_historical_air_quality` | Hourly, daily and annual pollutant summaries (PM2.5, ozone, CO, …) by monitoring station | ~30 tables; hourly tables in the hundreds of millions of rows each; >100 GB total — the largest store in the catalog |
| `noaa_gsod` | Global daily weather-station summaries, 1929–present | one table per year (~95 tables), ~3–4 M rows per recent year, ~300 M rows total |
| `google_trends` | Daily top and rising search terms by US DMA and by country | ~100 M+ rows, tens of GB |
| `bls` (shared with the finance pack) | Labor statistics — unemployment (CPS), CPI, employment hours and earnings | ~15 tables, tens of millions of rows |
| `chicago_crime` | Chicago Police Department incident reports since 2001 | 1 table, ~8 M rows, ~1.6 GB |
| `san_francisco` | SF city operations — 311 cases, police incidents, bikeshare, permits | ~10 tables, ~10 M rows |
| `new_york` | NYC city operations — 311 requests, motor-vehicle collisions, Citi Bike trips, tree census | ~30 tables; 311 alone ~35 M rows; >100 M rows total |
| `openaq` | Global air-quality sensor network readings | several million rows |
| `usa_names` | SSA baby-name counts by year, sex and state, 1910–present | 1 table, ~6 M rows |
| `fec` | Federal campaign contributions, committees and candidates, by election cycle | individual-contribution tables of 20–70 M rows per cycle; >200 M rows across cycles |

The target list is deliberately curated rather than "all of
`bigquery-public-data`": most of that project is either far larger than the
byte cap makes usable or too niche for a general front door.

**APIs (OKF-described, `human-reviewed`).** The second kind of source is
not a table at all. **SEC EDGAR `company-facts`** is the SEC's free XBRL API
covering every US public filer's reported financial facts:

| Source | Covers | Approximate scale |
|---|---|---|
| SEC EDGAR company-facts API | Every XBRL-tagged financial fact reported by SEC filers, from ~2009 onward, by fiscal year and period | 8,000+ active filers (≈15 k CIKs with facts); the equivalent bulk archive is ~1.4 GB compressed JSON; a single large filer returns ~2 MB per call; 10 requests/s per IP |

It is reached through `backend/accessor/sec_edgar_accessor.py` and the
`human-reviewed` template `ac.sec_edgar_company_metric_by_year`, which is
shared with the finance pack.

**Hand-authored documents.** `okf-catalog/` holds one reviewed `Table`
document (`covid19_open_data`, a worked example of the format) and two
Attested Computations: `ac.covid19_case_rate_by_county_year` (BigQuery SQL)
and `ac.sec_edgar_company_metric_by_year` (the EDGAR API).

### 8.2 Finance pack — public data standing in for a bank's systems

**BigQuery datasets (crawled, `machine-confirmed`)**, each with a reviewed
`Table` document that says what it stands in for, its vintage and how to
read its columns:

| Dataset | Stands in for | Covers | Scale and vintage (confirmed 2026-09-03) |
|---|---|---|---|
| `cfpb_complaints` | a bank's complaint case-management system | every consumer complaint the CFPB received, by product, issue, company, state and outcome; 1.25 M with a consented narrative | 3.46 M complaints, 2011-12-01 → **2023-03-23** (the public mirror's pipeline stopped there) |
| `fdic_banks` | entity master and regulatory peer data | every FDIC-insured institution with its identifiers, deposits, assets and a set of reported ratios | 2 tables; late-2022 snapshot |
| `sec_quarterly_financials` | a fundamentals warehouse | the SEC Financial Statement Data Sets — every XBRL number from every 10-K/10-Q, with submission, tag and dimension tables | 10 tables; `numbers` alone ~21 GB, unpartitioned; filings to 2020-12-31, so **fiscal 2019** is the last complete 10-K year |
| `sec_failure_to_deliver` | a settlement-exceptions ledger | SEC fails-to-deliver data by security and settlement date | crawled for discovery; no reviewed template yet |
| `bls` | macro context | shared with the public pack | see §8.1 |

The **SEC EDGAR API** (§8.1) is the second, current source for the same
facts, which is what makes the two-source reconciliation in §9 possible.
An **entity crosswalk** (`okf-catalog/packs/finance/entity_xref.csv`, loaded
into `finance_pack.entity_xref`) maps ~40 banks and ~20 large filers across
their CFPB company string, FDIC certificate and SEC CIK; every row was
verified against the data. Anything outside it resolves to "no evidence"
rather than a guess.

### 8.3 Finance pack — private internal risk mart 🔒

The demonstration public data cannot give: Atlas over data nobody outside
can see, with the customer's access control still deciding who gets an
answer. `atlas-ard-okf.finance_demo` is a private dataset in the same
project the public pack reads from — same crawler, same executor, same
discovery query — with no public IAM binding. Its four curated tables have
the shape of a retail bank's decisioning mart and payments ledger (the
Home Credit and PaySim schemas; the rows are synthetic with planted
structure, no real person):

| Table 🔒 | What it is | Rows |
|---|---|---|
| `finance_demo.loan_applications` | the credit book: one row per application with its outcome (`default_flag`), ten segments as at application (contract type, income band, education, housing, occupation, region rating, …) and bureau-inquiry counts | 60 k |
| `finance_demo.bureau_credits` | prior credits per applicant reported by the credit bureau, with overdue history | ~203 k |
| `finance_demo.installment_payments` | the instalment schedule versus what was actually paid, by month before application | ~1.05 M |
| `finance_demo.payment_transactions` | the payments ledger: hourly step, type, amount, balances, a fraud label and the legacy rule's flag | ~400 k |

All four table documents (`okf-catalog/packs/finance/private/finance_demo/`)
carry `visibility: private`, `access.entitlement: finance.internal` and
`restricted_to: orchestrator service account (dataset IAM); Atlas users with
the finance.internal entitlement`. They deliberately carry no calendar dates
or geography (the source shapes are anonymised), so the templates over them
speak of "months before application" and the planner glossary forbids
implying a period.

### 8.4 Places pack — Google Data Commons

The third pack (`places`, `okf-catalog/packs/places/`, route `/places`) has
one source: **Google Data Commons**, the knowledge graph that harmonises
200+ public datasets (Census, BLS, World Bank, WHO, CDC, UN, …) onto one
place graph with ~250,000 statistical variables. It is reached through the
REST v2 API (`backend/accessor/datacommons_accessor.py`), not BigQuery:
Data Commons' Analytics Hub mirror carries a turn-down notice (2026-08-26),
so the crawler cannot be pointed at it. Design and the Earth Engine
follow-on: `atlas-earth-engine-datacommons-assessment.md`.

| Source | Covers | Approximate scale |
|---|---|---|
| Data Commons REST v2 (`/v2/resolve`, `/v2/node`, `/v2/observation`) | Reported statistics for countries, states, counties, cities and more; deepest for the US, country-level worldwide; one facet (source) per observation series with `importName`, `provenanceUrl`, `measurementMethod`, `observationPeriod` | 250k+ variables, 200+ sources; free with an API key, no SLA, no published rate limit |

Two `human-reviewed` templates cover it (§8.5): a point / trend /
comparison for named places, and a ranking of every place of one type
inside a parent. Neither lets the model write a DCID: places and variables
are resolved by Data Commons' resolvers (a small curated key map first for
the twenty most-asked indicators), the accessor keeps the first variable
that actually has data for the place, and the receipt records the DCIDs,
the canonical names and the facet that were chosen. Requires `DC_API_KEY`
(Secret Manager) and `places` in `ATLAS_PACKS_ENABLED`; golden set
`tests/golden/places_a.yaml` (9/9 live, 2026-09-06); `scripts/dc_smoke.py` measured 1.2–2.1 s per accessor call against the live API (≈0 s cached).

### 8.5 Attested computations — all 19

Every reviewed template in the deployment, with its pack, executor and
typical cost per run. Private templates (🔒) read only `finance_demo` and
are withheld from accounts without `finance.internal`; a unit test asserts
that no public document reads the private dataset.

| Template | Pack | Answers | Executor | Cost / run |
|---|---|---|---|---|
| `ac.covid19_case_rate_by_county_year` | public | COVID-19 case rate by county and year | bigquery | ~$0.01 |
| `ac.sec_edgar_company_metric_by_year` | public + finance | one of 21 curated metrics by fiscal year, one or more companies | sec_edgar | ~$0.005–0.07 |
| `ac.dc_indicator_for_place` | places | a reported statistic for one or more named places — latest, one year, a range or the full history | datacommons_place | $0 (free API; Gemini tokens only) |
| `ac.dc_indicator_across_places` | places | every county / state / city / country inside a parent, ranked by a reported statistic | datacommons_children | $0 (free API; Gemini tokens only) |
| `ac.cfpb_complaints_trend` | finance | complaint trend by product, company and grain | bigquery | ~$0.01 |
| `ac.cfpb_timely_response_rate` | finance | a bank's timely-response rate versus deposit-size peers | bigquery (3 sources) | ~$0.01 |
| `ac.cfpb_complaint_rate_per_deposits` | finance | complaints per $1 B of deposits | bigquery | ~$0.007 |
| `ac.cfpb_narrative_themes` | finance | themes in complaint narratives with verified verbatim quotes | bigquery_sample_llm | ~$0.05, 2–4 min |
| `ac.cfpb_outcome_gap_by_tag` | finance | outcome gap for a tagged cohort (older Americans, servicemembers) versus untagged | bigquery | ~$0.006 |
| `ac.sec_fact_annual_api` | finance | one 10-K fact from the EDGAR API (the API half of a reconciliation) | sec_edgar_annual | ~$0.005 |
| `ac.sec_fact_from_bq` | finance | the same 10-K fact from the bulk data set (the warehouse half) | bigquery, cap 30 GB | ~$0.13 |
| `ac.sec_fact_reconcile` | finance | the two above, reconciled, with delta and agreement | composite | ~$0.13 |
| `ac.sec_ratio_by_year` | finance | ROA, ROE, net margin, efficiency, equity-to-assets from filings | sec_ratio | ~$0.005 |
| `ac.fdic_peer_ratios` | finance | a size-defined FDIC peer table (the size measure is a required parameter) | bigquery | ~$0.006 |
| `ac.sec_filer_screen` | finance | SIC-code screen over quarterly or annual filings against a threshold | bigquery, cap 30 GB | ~$0.14 |
| `ac.entity_resolve` | finance | a name → its CFPB, FDIC and SEC identities via the crosswalk | bigquery | <$0.001 |
| 🔒 `ac.hc_default_rate_by_segment` | finance · private | default rate by one of ten segments, small segments folded, book rate on every row | bigquery | <$0.001 |
| 🔒 `ac.hc_bureau_history_vs_default` | finance · private | bureau inquiries, prior credits and overdue history against default rate, aggregated per applicant | bigquery (2 tables) | <$0.001 |
| 🔒 `ac.hc_installment_delinquency_vintage` | finance · private | late or short-paid share by month before application, split by later outcome | bigquery (2 tables) | ~$0.003 |
| 🔒 `ac.paysim_structuring_pattern` | finance · private | repeated just-under-threshold transfers within a sliding window, versus the legacy flag | bigquery | ~$0.002 |

Costs are BigQuery on-demand pricing ($6.25/TiB) plus model calls. The
SEC bulk scans are the expensive ones because `numbers` is unpartitioned
and unclustered; clustering a copy inside the project would make them
pennies.

## 9. The finance pack: Atlas for one vertical

The finance pack is not a second product. It is the platform above with a
second catalog (§8.2–8.4), a pack glossary for the planner, three executors
that the public pack simply never routes to (§6), one extra endpoint (§9.2)
and its own section of the site (§9.3). Everything else — discovery,
guarded execution, trust tiers, receipts, the trace, budgets, approval and
entitlements — is shared code, and the public regression set proves the
public demo is unchanged by it.

### 9.1 What it answers

Three families of question, each backed by reviewed templates so that the
answer, its definition and its provenance are things a reviewer signed off
on:

**Complaint and conduct intelligence** — the CFPB complaint database as
the bank's own complaint system, joined to FDIC institutions for peer
normalisation. Which products' complaints rose fastest and what share was
answered on time; a bank's timely-response rate against deposit-size peers;
complaints per $1 B of deposits; the main themes in a quarter's narratives
with three verbatim, verified quotes each; whether a tagged cohort (older
Americans, servicemembers) was resolved with relief less often than the
rest. The theming template is the one place a model reads free text, and
its check stage drops any quote that is not a verbatim excerpt of the row
it cites.

**Filing-grounded fact-check and peer benchmark** — SEC EDGAR (API, current)
and the SEC Financial Statement Data Sets (BigQuery, to fiscal 2019) as a
fundamentals warehouse, FDIC ratios as regulatory peer data. A 10-K figure
fetched from both sources and reconciled, with the delta stated; curated
ratios (ROA, ROE, net margin, efficiency) with the averaging rule spelled
out; a size-defined FDIC peer table; a SIC-code screen ("which state
commercial banks reported a quarterly net loss in 2019"); and a paragraph
fact-check (§9.2) that verifies every numeric claim through attested
computations only.

**Internal risk over the bank's own data 🔒** — the private mart of §8.3.
Default rate by segment against the book rate; whether applicants with many
bureau inquiries default more often; how instalment delinquency trended in
the months before application for clients who later defaulted; which ledger
accounts made repeated just-under-threshold transfers inside a window, and
whether the legacy rule caught them. The same questions from an account
without the `finance.internal` entitlement are refused with the withheld
sources named (§5.4) — the "your controls still apply" moment, made visible
rather than silent.

**Data vintage.** The public mirrors are dated: CFPB to 2023-03-23, the SEC
bulk data to fiscal 2019, FDIC to late 2022; the EDGAR API is current. Every
template default, the planner glossary and the example questions are pinned
accordingly — which is why the example questions ask about 2022 and fiscal
2019 — and every answer names the vintage it used. The same catalog over a
*current* internal extract is the product; the mirrors are stand-ins.

### 9.2 The fact-check endpoint

`POST /skills/filing-fact-check` (`backend/orchestrator/skills/filing_fact_check.py`)
takes a paragraph of prose and returns a verdict per numeric claim:

1. **Claim extraction** — the plan-tier model extracts each numeric claim
   under a response schema: company, metric, fiscal year, claimed value,
   whether it is a level or a ratio (`claim.extracted`).
2. **Verification** — each level claim runs `ac.sec_fact_reconcile` (both
   sources) and each ratio claim runs `ac.sec_ratio_by_year`, through the
   same `_fetch_one` the ask path uses. No ad-hoc SQL exists in this path.
3. **Verdicts** — `verified`, `differs` (with `delta_pct`),
   `not_verifiable` (growth or percentage-change claims about level
   metrics are not verifiable by design, and a byte-cap hit on one claim
   becomes that claim's verdict rather than aborting the check) or
   `no_reported_value` (`claim.verdict`, one per claim, as each lands).
4. **Answer** — a `verdict_table` visualization plus a receipt covering
   every template run.

### 9.3 The finance section of the site

`/finance` is the pack's home. Signed out, it explains what the section is
and what an account gets after signing in: asking over complaints, filings
and peers with a receipt under every attested answer; fact-checking a
paragraph; browsing the catalog; and, for entitled accounts, the private
internal mart. Signing in uses the same Google sign-in and the same
approval queue as the public demo (§10.1): a new account sees an
"awaiting approval" state until an admin approves it, and only then can
ask. Once approved:

- **Ask | Fact-check a paragraph** — the ask experience of the public demo
  with the pack set to `finance`, grouped example questions (one group is
  the private mart), the live trace, the answer, and under it the
  **receipt** and, when a private source was involved, an **access card**:
  either the withheld sources and how to request access, or the entitlement
  that unlocked the answer.
- **`/finance/catalog`** — every source the pack can discover with its
  trust tier, visibility (🔒), reviewer and freshness, and for reviewed
  templates the exact SQL that runs (the model only binds parameter values).
  A private entry's SQL and notes are served only to entitled accounts; the
  banner shows the caller's own entitlements and a "Private" filter.
- **`/admin`** (admins only) — the approval queue and a per-user
  entitlement toggle, effective on the user's next request.

Components added for the pack — `ReceiptCard`, `AccessCard`,
`VisibilityChip`, `FactCheckBar`, `CatalogTable`, the verdict-table
visualization and the multi-step, quote-verification and withheld-source
lines in `TracePanel` — use the same design tokens as the public demo.

## 10. Using Atlas from an agent: the HTTP API and skills

Atlas is built to be driven by an orchestrating agent (Claude Code, an ADK
agent, any MCP host) as readily as by a person, and everything the site
does goes through the same three endpoints.

### 10.1 Endpoints

All endpoints require `Authorization: Bearer <Firebase ID token>` for an
**approved** user. A new account's first request creates its user record
as `pending`, notifies the admin, and returns `403 Account created — waiting
on admin approval.` until an admin approves it; `ATLAS_PREAPPROVED_EMAILS`
bypasses the queue. Tokens expire hourly.

| Endpoint | Body | Returns |
|---|---|---|
| `POST /ask` | `{question, pack?}` — `pack` omitted means `public`; a pack not in `ATLAS_PACKS_ENABLED` is a 400 | SSE stream (below) |
| `POST /skills/filing-fact-check` | `{text, pack: "finance"}` | SSE stream with `claim.extracted` / `claim.verdict` events and a `verdict_table` answer |
| `GET /packs/{pack}/catalog` | — | `{entries[], counts{attested, tables, private}, entitlements[]}` — every document discovery can see for the pack, with trust, visibility, reviewer, freshness, parameters, cost profile and (for entitled callers) SQL |
| `GET /admin/users`, `POST /admin/users/{uid}/approve` · `/reject`, `GET /admin/entitlements`, `POST /admin/users/{uid}/entitlements`, `GET /admin/usage/{uid}` | admin only | approval queue, entitlement management, per-user usage |

**Stream shape.** `/ask` and `/skills/*` return Server-Sent Events. Each
frame is `event: <name>` + `data: <json>`; the names are
`guardrail.{started,done,blocked}`, `discover.{started,done}`,
`plan.{started,done}`, `fetch.{started,progress,done}`,
`check.{started,done,backtrack}`, `synthesize.{started,progress,done}`,
`claim.{extracted,verdict}`, and exactly one terminal `answer` or `error`.
Both terminal events carry `walkthrough`; an attested `answer` also carries
`receipt`; an answer that touched a private source carries `access`
(`{entitlements[], withheld[]}`) and, if refused, `refused: "not_entitled"`.
A `guardrail.blocked` event carries `code` (`monthly_budget_exceeded`,
`byte_cap_exceeded`, `not_entitled`) and a `message`. `scripts/golden_run.py` in the repository
has a reference parser (`stream()`).

### 10.2 Conventions every skill follows

A **skill** is a `SKILL.md` in the Anthropic agent-skills convention
(frontmatter `name` + `description`, then the procedure) that an agent
loads to run a multi-step workflow *through* Atlas's API — so the skill
inherits every guardrail (byte caps, monthly budget, attested-first routing,
receipts, entitlements) rather than re-implementing any of it. The index is
`skills/finance/README.md`; every skill follows the same rules:

- **Attested first, refuse honestly.** A skill never rewrites a question to
  coax an answer out of ad-hoc SQL when the attested path returned nothing;
  it reports "no attested evidence" and moves on. Every figure in a skill's
  output is copied from an `answer.visualization.data` row or the
  `walkthrough.queries_executed` list — never recomputed.
- **Vintage.** Skills default their windows to the data's vintage and print
  the vintage line the receipt carries.
- **Private data.** A skill checks `GET /packs/finance/catalog` →
  `entitlements` before planning on a private source, treats
  `guardrail.blocked {code: not_entitled}` or `answer.refused ==
  "not_entitled"` as a final answer to report (with `answer.access.withheld`),
  and never rephrases a question to reach private data through a public
  stand-in.
- **Budget.** A skill states its expected spend up front (the sum of the
  templates' `cost_profile.expected_bytes` at $6.25/TiB plus model calls)
  and stops if a `guardrail.blocked` event arrives.

### 10.3 Skills index

| Skill | Purpose | Atlas templates it leans on |
|---|---|---|
| `complaint-root-cause` | "what's driving X" → trend → movers → peer normalisation → verified themes → a root-cause brief with receipts | `ac.cfpb_complaints_trend`, `ac.cfpb_timely_response_rate`, `ac.cfpb_complaint_rate_per_deposits`, `ac.cfpb_narrative_themes` |
| `conduct-outcome-monitor` | Consumer Duty / UDAAP outcome check by cohort, product and year, definitions stated | `ac.cfpb_outcome_gap_by_tag`, `ac.cfpb_timely_response_rate` |
| `filing-fact-check` | drive `/skills/filing-fact-check` and mark up the paragraph with verdicts | `ac.sec_fact_reconcile`, `ac.sec_ratio_by_year` |
| `peer-benchmark` | a size-defined peer table with the FDIC-vs-XBRL definition chosen explicitly | `ac.fdic_peer_ratios`, `ac.sec_ratio_by_year`, `ac.entity_resolve` |
| 🔒 `credit-portfolio-monitor` | portfolio-risk review over the bank's own loan book: segments, bureau gradient, early-warning series, private receipts kept | `ac.hc_default_rate_by_segment`, `ac.hc_bureau_history_vs_default`, `ac.hc_installment_delinquency_vintage` |
| 🔒 `payments-structuring-screen` | structuring screen over the bank's own ledger with a sensitivity pass and the legacy blind-spot count | `ac.paysim_structuring_pattern` |
| 🔒 `private-data-access-check` | which private sources this account can query, with a live enforcement check, before planning on them | `GET /packs/finance/catalog`, any private template |
| `receipt-to-audit-pack` | turn an answer's receipt and walkthrough into a replayable model-risk artefact | any attested answer |
| `attested-computation-author` | draft a new reviewed template from a repeated ad-hoc question | catalog + walkthroughs |

The skills run today from Claude Code or any MCP host against the deployed
API. An MCP server that exposes `ask`, `fact_check` and `catalog` as tools
is the natural next step and is not built.

## 11. Extending Atlas

Three things a team adds, in increasing order of review:

**A source.** For a table store: add the `(project, dataset, packs)` to the
crawler's target list — optionally with `visibility: private` and the
entitlement it needs — and run the crawl. The tables become
`machine-confirmed` candidates with real schemas. Optionally add a reviewed
`Table` document for the meaning a schema can't carry. For an API: one OKF
document plus one accessor module, as the SEC EDGAR source shows and the
Data Commons source (`backend/accessor/datacommons_accessor.py`, two
templates, one new `kind` branch in `_fetch_one`) repeats.

**A reviewed template.** Write an `AttestedComputation` document: the SQL
(or accessor call), typed parameters with defaults, the sources it touches,
a `cost_profile`, a `citation_template`, a reviewer and `stale_after`. The
test suite parses it, binds its parameters, checks it touches only declared
sources, and — for a private template — that it reads only private data.
The `attested-computation-author` skill drafts one from repeated ad-hoc
questions.

**A pack.** A directory under `okf-catalog/packs/<pack>/`, a glossary and
synthesis rule in `packs.py`, the pack name in `ATLAS_PACKS_ENABLED`, and —
if it gets its own section of the site — a route behind a build-time flag.
The finance pack is the worked example of all three.

## 12. Verification

**Unit tests** (`tests/`, 73 tests, no GCP required): the public catalog is
unchanged by packs; pack isolation; every one of the 17 finance/public
templates parses (sqlglot), binds its parameters and touches only declared
sources; the two Data Commons templates parse and the accessor's place and
indicator resolution, single-facet selection, year filters, ranking and
caps run against a fake of the v2 API (`tests/test_places_catalog.py`); the
XBRL tag map is identical in both places it lives; the composite graph is
acyclic; quote verification; verdict arithmetic; private documents are
confined to `finance_demo` and no public document reads it; the
visible/withheld split; the fetch-stage and SQL-scan refusals; the private
receipt fields. The four private templates were additionally executed end
to end on the synthetic data in DuckDB before commit.

**Golden sets** (`tests/golden/`, run live against the deployed API by
`scripts/golden_run.py`, which asserts the routing path, the source, the
bound parameters, bytes, quotes and verdicts, and writes a report):

| Set | Result | What it proves |
|---|---|---|
| `public_regression` | 10/10 | the public demo's example questions route and answer as before, and a CFPB question asked in the public pack finds no finance source |
| `finance_a` (complaints and conduct) | 6/6 | five attested answers including narrative theming with verified quotes; one honest refusal |
| `finance_b` (filings and peers) | 6/6 | two-source reconciliation, curated ratios, the SIC-code screen, a four-claim fact-check; one honest refusal |
| `finance_d` (private mart, entitled account) | 6/6 | four attested private answers with `unlocked_by` receipts; one ad-hoc question over the private ledger; one public question unaffected |
| `finance_d_noaccess` (same account, entitlement revoked) | 4/4 | the same private questions refused naming the withheld sources; SQL naming the private table in the question never reaches BigQuery; a public question unaffected |
| `places_a` (Data Commons) | 9/9 | eight attested places-pack answers with resolved DCIDs and a named source facet (13–19 s end to end; 54 s for the ~3,100-county expansion); one honest no-evidence answer. `public_regression` re-run 10/10 on the same revision |

Five rounds of golden runs found and fixed: JSON serialisation of DATE rows
in synthesis, multi-company EDGAR questions, the 21 GB SEC scan versus the
20 GB template cap (per-template caps), growth claims mis-typed as levels,
and two routing misses that became a template (`ac.sec_filer_screen`) and a
required parameter (`ac.fdic_peer_ratios.measure`).

## 13. Known limits

- **Dated public mirrors** (§9.1): CFPB to March 2023, SEC bulk to fiscal
  2019, FDIC to late 2022. The EDGAR API is current.
- **SEC bulk scans cost ~$0.13 each** because `numbers` is unpartitioned;
  a clustered copy inside the project would make them pennies.
- **Discovery is embedding-only.** A question that says "banks" leans
  toward FDIC sources, which is why the screening example names the SEC
  filings explicitly.
- **The crosswalk covers ~40 banks and ~20 large filers**; anything outside
  it resolves to "no evidence" rather than a guess.
- **The private mart has no dates or geography**, so a private-plus-public
  join ("our default rate against that year's unemployment rate") cannot be
  made honestly and is not offered.
- **One entitlement string per private source.** Row- and column-level
  policy is a BigQuery policy-tag concern.
- **The SDK is pinned** (`google-genai` 0.7.0) for schema stability; the
  trace shows the pipeline's decisions, not the model's thinking tokens.

## 14. References

- **[Agentic Resource Discovery (ARD)](https://agenticresourcediscovery.org/spec/)** spec, [repository](https://github.com/ards-project/ard-spec).
- **[Open Knowledge Format (OKF)](https://okf.md/spec/)** spec, [reference tooling](https://github.com/GoogleCloudPlatform/knowledge-catalog), [v0.2 trust-signals announcement](https://cloud.google.com/blog/products/data-analytics/okf-v0-2-adds-trust-signals).
- **[NeuralKG](https://github.com/rvguha/Neuralkg)** (Apache-2.0) — the pipeline this project forks.
- **[Atlas on GitHub](https://github.com/srikanthbelwadi/atlas)** — the code, the OKF catalog (`okf-catalog/`), the agent skills (`skills/finance/`) and the golden sets (`tests/golden/`).
