# Atlas — Implementation Documentation

This is the engineering companion to the demo: what Atlas is, how it is
built, why it is built that way, and exactly which parts are new versus
carried over from the project it forks.

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
executor and the one this demo instance is pointed at; the demo's catalog
happens to be built from a handful of BigQuery datasets plus the SEC EDGAR
API because those are large, real, and free to query without credentials.
Nothing in the design depends on the data being public.

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
| The five-stage discover/plan/fetch/check/synthesize pipeline shape | A guarded BigQuery executor as the first-class execution path for large tabular stores, alongside OKF-described APIs — the demo catalog is a curated set of BigQuery datasets plus the SEC EDGAR API, not NeuralKG's original ~20 REST sources |
| Describing sources once via OKF documents, never per-source code | A guarded BigQuery executor (dry-run byte cap + hard `maximum_bytes_billed` + wall-clock timeout) as the primary fetch path, replacing the generic REST accessor as the default |
| The "plan" stage validating whether a source can structurally answer a question before fetching | Vertex AI Gemini under strict JSON-schema output for both planning and synthesis, on Google Cloud infrastructure |
| Citations with a provenance/trust label on every answer | A live SSE trace of every stage as it runs, plus a persisted post-hoc "walkthrough" (sources considered, queries run, backtracks, real token cost) — NeuralKG's original UI showed only a finished answer |
| — | Firebase-Auth-gated access control: admin approval queue, pre-approved-email allowlist, per-user monthly budget guardrail in Firestore |
| — | A scheduled crawler that builds the ARD/OKF discovery index directly from a store's own schema metadata (BigQuery `INFORMATION_SCHEMA` today), so table descriptions can't hallucinate what a table contains |
| — | Entirely new Next.js frontend — none of NeuralKG's original frontend code is reused |

## 3. Tech stack

**Backend** — Python 3.12, FastAPI (`backend/orchestrator/main.py`) on
Cloud Run, `google-genai` 0.7.0 against Vertex AI Gemini (`gemini-2.5-flash`
for planning, `gemini-2.5-pro` for synthesis), `google-cloud-bigquery` for
both the query engine and the ARD catalog, `google-cloud-firestore` for
users/usage state, `firebase-admin` for ID-token verification,
`sse-starlette` for the streamed trace, `python-frontmatter` + `pyyaml` for
reading OKF documents.

**Frontend** — Next.js 14 (App Router), deployed on Firebase App Hosting
(which runs it on Cloud Run under the hood). Firebase Auth (Google sign-in) client-side; the backend's SSE
stream is consumed by hand rather than the native `EventSource` API, since
`EventSource` can't attach the Firebase ID token every request needs.
Design system: IBM Plex Serif/Sans/Mono, a navy (`#16324a` / dark
`#9fc3de`) and terracotta-accent (`#a6501c` / dark `#e08a4f`) palette
defined as CSS custom properties with a `prefers-color-scheme: dark`
variant, and a teal secondary accent (`#1f6f66`) for the human-reviewed
trust tier. All four wired-up visualization kinds (table, bar, line, KPI
cards; infographic composes from KPI cards; map falls back to a table) are
hand-drawn inline SVG — no charting library.

**Infrastructure** — Google Cloud only: Cloud Run (orchestrator), Cloud Run
Jobs (crawler), Firebase App Hosting (frontend), Firestore (users/usage),
BigQuery (both the demo datasets and the `ard_catalog` discovery
index, queried with native `VECTOR_SEARCH`), Cloud Functions 2nd
gen (admin notification), Cloud Scheduler (weekly re-crawl), Artifact
Registry + Cloud Build (container images).

## 4. Architecture: discover → plan → fetch → check → synthesize

`backend/orchestrator/pipeline.py`'s `run()` is an async generator; every
stage yields one or more `{"event": "<stage>.<phase>", "data": {...}}`
dicts consumed directly by `main.py`'s `EventSourceResponse` and rendered
live by the frontend's `TracePanel`. The same five stages NeuralKG
used, with BigQuery as the first-class executor for large tabular stores
and OKF-described APIs as the second:

**Discover** (`discovery.py`) — the question is embedded once
(`text-embedding-005`, 768 dimensions) and matched against two candidate
pools, merged and deduplicated by score: BigQuery `VECTOR_SEARCH` over
`ard_catalog.embeddings` (the crawler-maintained index of real tables), and an in-process cosine ranking over the small hand-authored
`okf-catalog/` bundle (curated Attested Computation templates). Both
return the same candidate shape — `{source_id, kind, title, description,
trust, type, score}` — so nothing downstream cares which pool a candidate
came from.

**Plan** (`llm.py`'s `classify_and_plan`) — a fast-tier Gemini call decides
the question's shape (point / ranking / aggregate / trend / status) and
picks one candidate. If the chosen candidate is an OKF `AttestedComputation`
(a human-reviewed, parameterized SQL template), the model only extracts
parameter values from the question's wording — the SQL text itself never
changes. If it's a plain BigQuery table, the model drafts ad-hoc SQL against
the real column list the crawler captured (never invented from a table's
title).

**Fetch** (`bigquery_accessor.py`) — every query, templated or ad-hoc, goes
through the same guarded two-step path: a zero-cost BigQuery dry run checks
the estimated bytes scanned against a byte cap (higher for trusted
templates than for ad-hoc SQL), then the real query runs with
`maximum_bytes_billed` set to that same cap as a hard server-side backstop
and a wall-clock timeout. A dry run and the real scan can differ
(partitioned tables, cached results) — the hard cap, not the estimate
alone, is what actually protects the budget.

**Check** — the fetched rows are sanity-checked (non-empty) before being
handed to synthesis. An empty result or a fetch-time exception triggers a
**backtrack**: retry against the next-best candidate, up to
`MAX_BACKTRACKS` (1) additional attempt. Every backtrack redrafts a fresh,
single-candidate plan rather than reusing the original.

**Synthesize** (`llm.py`'s `synthesize`) — a pro-tier Gemini call, given
only the fetched rows (never the model's own training knowledge), produces
a narrative, a citation list with trust level, and a visualization spec
under a strict JSON schema (`PRESENTATION_SCHEMA`) so the frontend always
gets a shape it can render.

Every stage's events accumulate into a `walkthrough` dict attached to the
terminal `answer` or `error` event — sources considered, every query
actually executed (SQL + bound params + bytes billed), every backtrack and
why, and real per-call token usage. A failed question is exactly as
inspectable as a successful one; nothing about the walkthrough depends on
the run having succeeded.

## 5. Data sources (demo catalog)

Atlas is source-agnostic: anything described in OKF and reachable by an
executor is queryable. The sources below are the **demo catalog** — chosen
because they are large, real, and free to query without credentials, which
makes them a convenient stand-in for the private warehouses, operational
stores and internal APIs an enterprise deployment would point at instead.
(This is the queryable data surface — not Atlas's own operational state;
Firestore's `users`/`usage` records are infrastructure, not answerable
content.)

Sizes are order-of-magnitude figures for the demo reader. The crawler
records the exact `row_count` and `size_gb` of every table it catalogs (from
`INFORMATION_SCHEMA.TABLE_STORAGE`) into `ard_catalog.embeddings` metadata,
which is also what the byte-cap guardrail and the "large table" flag are
computed from.

### BigQuery datasets (crawled, `machine-confirmed`)

Fourteen datasets from the `bigquery-public-data` project, each expanded
into its individual tables via `INFORMATION_SCHEMA` at crawl time
(`backend/crawler/targets.py`):

| Dataset | Covers | Approximate scale |
|---|---|---|
| `covid19_open_data` | COVID-19 cases, deaths, tests and government-response indicators, by day and place, worldwide | 1 main table, ~12 M rows, several GB; backs the demo's SQL Attested Computation |
| `census_bureau_acs` | American Community Survey estimates — population, income, housing — by geography and 1-/5-year vintage | ~200 tables (geography × vintage); largest ~220 k rows (block group); each table is one vintage snapshot |
| `world_bank_health_population` | Country-level health and population indicators | ~2 M indicator rows across ~200 countries |
| `world_bank_wdi` | World Development Indicators — GDP, trade, macro/development series by country and year | ~20 M indicator rows |
| `epa_historical_air_quality` | Hourly, daily and annual pollutant summaries (PM2.5, ozone, CO, …) by monitoring station | ~30 tables; hourly tables in the hundreds of millions of rows each; >100 GB total — the largest store in the demo |
| `noaa_gsod` | Global daily weather-station summaries, 1929–present | one table per year (~95 tables), ~3–4 M rows per recent year, ~300 M rows total |
| `google_trends` | Daily top and rising search terms by US DMA and by country | ~100 M+ rows, tens of GB |
| `bls` | Labor statistics — unemployment (CPS), CPI, employment hours and earnings | ~15 tables, tens of millions of rows |
| `chicago_crime` | Chicago Police Department incident reports since 2001 | 1 table, ~8 M rows, ~1.6 GB |
| `san_francisco` | SF city operations — 311 cases, police incidents, bikeshare, permits | ~10 tables, ~10 M rows |
| `new_york` | NYC city operations — 311 requests, motor-vehicle collisions, Citi Bike trips, tree census | ~30 tables; 311 alone ~35 M rows; >100 M rows total |
| `openaq` | Global air-quality sensor network readings | several million rows |
| `usa_names` | SSA baby-name counts by year, sex and state, 1910–present | 1 table, ~6 M rows |
| `fec` | Federal campaign contributions, committees and candidates, by election cycle | individual-contribution tables of 20–70 M rows per cycle; >200 M rows across cycles |

The target list is deliberately curated rather than "all of
`bigquery-public-data`": most of that project is either far larger than the
byte cap makes usable in a demo or too niche for a general front door.

### APIs (OKF-described, `human-reviewed`)

The second kind of source in the demo is not a table at all. **SEC EDGAR
`company-facts`** is the SEC's free XBRL API covering every US public
filer's reported financial facts:

| Source | Covers | Approximate scale |
|---|---|---|
| SEC EDGAR company-facts API | Every XBRL-tagged financial fact reported by SEC filers, from ~2009 onward, by fiscal year and period | 8,000+ active filers (≈15 k CIKs with facts); the equivalent bulk archive is ~1.4 GB compressed JSON; a single large filer returns ~2 MB / ~47 k lines per call; 10 requests/s per IP |

It is reached through a dedicated accessor
(`backend/accessor/sec_edgar_accessor.py`) and a `human-reviewed` Attested
Computation (`ac.sec_edgar_company_metric_by_year`) that resolves a company
name or ticker to a CIK and returns one of eight curated metrics (revenue,
net income, total assets, …). The metric-to-XBRL-tag mapping is a small
human-reviewed dict, so the planner extracts parameter values only — never a
raw tag or a URL. This is the template for adding any further API source,
private or public: one OKF document plus one accessor module.

### Hand-authored OKF documents

Alongside the crawled entries, `okf-catalog/` holds the human-authored
documents that sit at the top trust tier: the two Attested Computations
above (`ac.covid19_case_rate_by_county_year` for BigQuery SQL, and
`ac.sec_edgar_company_metric_by_year` for the EDGAR API) and a hand-written
`Table` document for `covid19_open_data` used as a worked example of the
format. In an enterprise deployment this directory is where a data team's
sanctioned metric definitions live, version-controlled and reviewed like
code.

## 6. Grounding and citations

Atlas never lets the synthesis model answer from what it already "knows."
`synthesize()`'s prompt is explicit — compose the answer "using ONLY the
evidence provided — never invent figures" — and the evidence it receives is
exactly the rows `fetch` returned, nothing else. Every answer carries a
citation naming the exact BigQuery table or Attested Computation used and
its OKF trust tier:

- **`human-reviewed`** — a curated `AttestedComputation` template, written
  and reviewed by a person, where only parameter values are model-supplied
  (e.g. `okf-catalog/attested-computations/covid19_case_rate_by_county_year.md`).
- **`machine-confirmed`** — a table described by the crawler directly from
  the store's own schema metadata (BigQuery `INFORMATION_SCHEMA` today) (deterministic, template-driven
  text — never model-generated, so it can't hallucinate what a table
  contains) but not reviewed by a person.
- **`unverified`** — reserved for OKF documents that carry neither
  attestation, not currently produced by anything in Atlas's own catalog
  but part of the trust model any future non-crawled source would use.

This is a direct implementation of OKF v0.2's three-tier trust-signal model
(`verified` absent / machine-only / `human:<id>`), surfaced end to end: the
crawler writes it into `ard_catalog.embeddings`' metadata, `discovery.py`
carries it into each candidate, and `AnswerCanvas.tsx` renders it as a
colored dot next to every citation chip.

When no source produces usable evidence at all — nothing discovered, every
candidate's fetch empty or failing — Atlas returns an explicit "I couldn't
find a data source that answers this well enough to cite" rather than
letting synthesis run on nothing, ever.

## 7. Reasoning trace and tracing design

The frontend never shows a bare spinner. Every stage streams its own
`.started`/`.done` (and, for fetch/check, `.progress`/`.backtrack`) events
over SSE the moment they happen, rendered by `TracePanel.tsx` as a
stage-by-stage timeline that fills in live.

Two layers of transparency sit on top of that event stream:

**Live, in-request reasoning.** `classify_and_plan`'s JSON output includes
a `reasoning` field — one plain-language sentence on why this source and
shape were chosen, written for the person who asked, not a restatement of
the prompt's own instructions. `discover.done` is narrated with the actual
top 2-3 candidates and their scores rather than a bare count. `synthesize`
gets two derived notes (using data already known, not an extra model call):
what it's about to draft (row count, source, trust level) and what it chose
(visualization kind, citation count). A backtrack's redrafted plan emits
its own `plan.started`/`plan.done` pair with its own reasoning, so a
question that needed two routing attempts shows *both* decisions and why
the second one differs from the first — `TracePanel.tsx`'s `notesFor()`
returns an array of notes per stage specifically so this doesn't collapse
to only the latest one.

This was a deliberate, constrained design choice: the pinned
`google-genai==0.7.0` SDK predates Gemini's `thinking_config`/thought-summary
support, and every model call in this pipeline already requires strict
`response_schema` JSON output. Bumping the SDK to get literal model
"thinking" tokens would have touched other pinned behavior (e.g.
`usage_metadata`'s field names) for a feature this design achieves more
simply: make the pipeline's *own* real decisions legible, with no new
dependency and no schema risk.

**Post-hoc walkthrough.** `Walkthrough.tsx` renders the full accumulated
record after a question finishes (success or failure): every candidate
considered with its score, which one was used, every backtrack and its
reason, the literal SQL and bound parameters for every query actually
executed, and a token/cost breakdown per model call. This is what survives
after the live trace panel scrolls out of view.

## 8. Packs (the finance section)

Atlas serves more than one catalog from one deployment. A **pack** is a named
slice of the catalog that discovery never mixes with another: the original
demo is the `public` pack (the default everywhere a pack isn't named) and
the finance section at `/finance` is the `finance` pack. Every layer knows
about packs, and every default keeps the public demo exactly as it was:

- **OKF documents** declare `pack: finance` (or `packs: [public, finance]`
  for a shared template like the SEC EDGAR one); no field means `public`.
  Finance documents live under `okf-catalog/packs/finance/`.
- **The crawler** (`backend/crawler/targets.py`) lists each dataset with its
  packs; rows in `ard_catalog.embeddings` carry `metadata.pack`, and a
  non-public pack's `doc_id` is suffixed `#<pack>`.
- **Discovery** pre-filters both the `VECTOR_SEARCH` base table and the
  hand-authored documents by pack.
- **`POST /ask`** takes an optional `pack`; a pack not listed in
  `ATLAS_PACKS_ENABLED` (default `public`) is refused with a 400, never
  answered from the public catalog.
- **The frontend** builds `/finance/*` only when
  `NEXT_PUBLIC_ATLAS_FINANCE_ENABLED=true`; otherwise those routes 404 and the
  header shows no link.

The finance pack adds three executor kinds beyond guarded SQL and the EDGAR
API: `bigquery_sample_llm` (a byte-capped narrative sample themed by the
plan-tier model, every quote verified against the sample in the check
stage), `composite` (ordered steps over other attested computations, e.g.
the two-source SEC reconciliation), and `sec_ratio`/`sec_edgar_annual`
(10-K annual-fact selection and curated ratios from
`backend/accessor/xbrl_metrics.py`, the one metric-to-tag map both the API
and BigQuery paths share). Attested answers carry a **receipt** (template
version, reviewer, `stale_after`, every query step, bytes, tokens, cost),
and `POST /skills/filing-fact-check` verifies each numeric claim in a
paragraph through attested computations only. The engineering design is at
`/finance/design`; the as-built implementation document (catalog inventory,
executors, golden results, operations, skills index and the internal-data
recommendation) is `FINANCE-IMPLEMENTATION.md` (also `/finance/implementation`);
agent skills live in `skills/finance/`; the demo plan is
`atlas-finance-demo-plan.md` in the project folder.

## 9. References

- **[Agentic Resource Discovery (ARD)](https://agenticresourcediscovery.org/spec/)** spec, [repository](https://github.com/ards-project/ard-spec).
- **[Open Knowledge Format (OKF)](https://okf.md/spec/)** spec, [reference tooling](https://github.com/GoogleCloudPlatform/knowledge-catalog), [v0.2 trust-signals announcement](https://cloud.google.com/blog/products/data-analytics/okf-v0-2-adds-trust-signals).
- **[NeuralKG](https://github.com/rvguha/Neuralkg)** (Apache-2.0) — the pipeline this project forks.
