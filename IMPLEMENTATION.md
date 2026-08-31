# Atlas — Implementation Documentation

This is the engineering companion to the demo: what Atlas is, how it is
built, why it is built that way, and exactly which parts are new versus
carried over from the project it forks. Where the original planning
document (shared before any code was written) described intent, this
document describes what actually ships, including the real bugs found and
fixed by running it live rather than just reading the code.

## 1. What Atlas is

Atlas is a natural-language front door to public BigQuery datasets. A
signed-in user asks a plain-English question — "What was the average
temperature in Chicago in 2023?" — and gets back a grounded, cited answer
with an appropriate chart or table, generated from a real, guarded SQL query
against Google's public-data BigQuery catalog, never from the model's own
knowledge. Every step the system takes to get there is streamed live to the
browser and left inspectable afterward: which data sources it considered,
why it picked the one it used, the literal query it ran, and what that
query cost.

## 2. Where it came from

Atlas is a derivative of [Resource Raiser](https://github.com/TechSoup/resource-raiser)
(TechSoup, Apache-2.0), a general-purpose agentic query engine over ~20 US
authoritative sources (SEC, Census, Treasury, IRS Form 990, CDC, federal
grants). Resource Raiser's central idea — describe each data source once in
the [Open Knowledge Format](https://okf.md/spec/) (OKF), make it discoverable
through an [Agentic Resource Discovery](https://agenticresourcediscovery.org/spec/)
(ARD) index, and run every question through the same
**discover → plan → fetch → check → synthesize** pipeline instead of writing
per-source query code — is the foundation this project keeps.

What changed, and why:

| Kept from Resource Raiser | Replaced or newly built for Atlas |
|---|---|
| The five-stage discover/plan/fetch/check/synthesize pipeline shape | Narrowed source universe: public BigQuery datasets specifically, not ~20 heterogeneous REST APIs |
| Describing sources once via OKF documents, never per-source code | A guarded BigQuery executor (dry-run byte cap + hard `maximum_bytes_billed` + wall-clock timeout) as the primary fetch path, replacing the generic REST accessor as the default |
| The "plan" stage validating whether a source can structurally answer a question before fetching | Vertex AI Gemini under strict JSON-schema output for both planning and synthesis, on Google Cloud infrastructure |
| Citations with a provenance/trust label on every answer | A live SSE trace of every stage as it runs, plus a persisted post-hoc "walkthrough" (sources considered, queries run, backtracks, real token cost) — Resource Raiser's original UI showed only a finished answer |
| — | Firebase-Auth-gated access control: admin approval queue, pre-approved-email allowlist, per-user monthly budget guardrail in Firestore |
| — | A scheduled crawler that builds the ARD/OKF discovery index directly from BigQuery's own `INFORMATION_SCHEMA`, so table descriptions can't hallucinate what a table contains |
| — | Entirely new Next.js frontend — none of Resource Raiser's original frontend code is reused |

`_fetch_one()` in `pipeline.py` still has a stub branch for Resource
Raiser's original generic OKF/REST fetcher (non-BigQuery sources) — kept as
a documented gap, not silently dropped, since the OKF catalog format
supports describing that kind of source even though nothing in Atlas
exercises it yet.

See `THIRD_PARTY_NOTICES.md` for the license notice this fork is required to
carry, and the full modification summary.

## 3. Tech stack

**Backend** — Python 3.12, FastAPI (`backend/orchestrator/main.py`) on
Cloud Run, `google-genai` 0.7.0 against Vertex AI Gemini (`gemini-2.5-flash`
for planning, `gemini-2.5-pro` for synthesis), `google-cloud-bigquery` for
both the query engine and the ARD catalog, `google-cloud-firestore` for
users/usage state, `firebase-admin` for ID-token verification,
`sse-starlette` for the streamed trace, `python-frontmatter` + `pyyaml` for
reading OKF documents.

**Frontend** — Next.js 14 (App Router), deployed on Firebase App Hosting
(which runs it on Cloud Run under the hood — no Vercel anywhere in this
stack). Firebase Auth (Google sign-in) client-side; the backend's SSE
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
BigQuery (both the public datasets themselves and the `ard_catalog`
discovery index, queried with native `VECTOR_SEARCH`), Cloud Functions 2nd
gen (admin notification), Cloud Scheduler (weekly re-crawl), Artifact
Registry + Cloud Build (container images).

## 4. Architecture: discover → plan → fetch → check → synthesize

`backend/orchestrator/pipeline.py`'s `run()` is an async generator; every
stage yields one or more `{"event": "<stage>.<phase>", "data": {...}}`
dicts consumed directly by `main.py`'s `EventSourceResponse` and rendered
live by the frontend's `TracePanel`. The same five stages Resource Raiser
used, applied to this project's narrower BigQuery-only scope:

**Discover** (`discovery.py`) — the question is embedded once
(`text-embedding-005`, 768 dimensions) and matched against two candidate
pools, merged and deduplicated by score: BigQuery `VECTOR_SEARCH` over
`ard_catalog.embeddings` (the crawler-maintained index of real public
tables), and an in-process cosine ranking over the small hand-authored
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

## 5. Data sources

Everything Atlas can actually query falls into three tiers, ordered by how
much of it is exercised today. (This is the queryable data surface — not
Atlas's own operational state; Firestore's `users`/`usage` records are
infrastructure, not answerable content.)

**14 crawled BigQuery public-dataset groups** (`backend/crawler/targets.py`).
Each entry is a whole BigQuery dataset, expanded into its individual tables
via `INFORMATION_SCHEMA` at crawl time and cataloged as `machine-confirmed`
— the exact table count per group is discovered dynamically, not fixed here:

| Dataset | Covers | Notes from live use |
|---|---|---|
| `covid19_open_data` | COVID-19 case/death/test counts and government-response indicators, by day and place | Backs the project's one Attested Computation template as well as ad-hoc queries; reporting cadence varies by jurisdiction (documented in the table's own OKF doc) |
| `census_bureau_acs` | American Community Survey estimates — population, income, housing, by place | Coverage gap found live: each table is a single 5-year-vintage snapshot (e.g. `place_2010_5yr`), not a real multi-year series, so a "population trend over the decade" question backtracks through every candidate and fails honestly rather than answering wrong — this is why that question was removed from the suggestion chips |
| `world_bank_health_population` | Country-level health and population indicators (life expectancy, mortality, etc.) | Used for cross-country comparisons; the discovery-ranking fix that forwards each candidate's score into the planning prompt exists specifically so this outranks COVID data for health questions |
| `world_bank_wdi` | World Development Indicators — GDP, trade, and other macro/development stats, by country and year | Same family as `world_bank_health_population`; not yet exercised by any of the verified example questions |
| `epa_historical_air_quality` | Daily and annual pollutant summaries (PM2.5, ozone, CO, etc.) by monitoring station/county | Verified live; the synthesized answer named an "arithmetic mean" value without naming which pollutant it measured — a synthesis-prompt gap worth tightening, not a fetch failure |
| `noaa_gsod` | Global daily weather station summaries (temperature, wind, precipitation), 1929–present | Verified live but the slowest query observed in testing (45s) — likely the planner filtering to one station only after scanning a multi-decade table |
| `google_trends` | Daily/weekly top search terms by region | Known data-model limitation, not a bug: `international_top_terms` only lists terms that were literally the top term some day, so a real but never-#1 term (e.g. "electric vehicles") can legitimately never appear — see Known gaps |
| `bls` | Labor statistics — unemployment rate, CPS series, by state | Verified live, correct figure on first attempt |
| `chicago_crime` | Chicago Police Department incident reports since 2001 | Verified live, correct ranking |
| `san_francisco` | SF city operations data (311 cases, crime, permits, etc.) | Cataloged but not yet exercised by any verified example question |
| `new_york` | NYC city operations data (311, motor vehicle collisions, etc.) | Cataloged but not yet exercised by any verified example question |
| `openaq` | Global air-quality sensor network readings | Cataloged but not yet exercised by any verified example question |
| `usa_names` | SSA baby name popularity by year, sex, state | Verified live, correct answer |
| `fec` | Federal campaign contributions and committee filings | Verified live, correct ranking |

Five of the fourteen — `san_francisco`, `new_york`, `openaq`, `world_bank_wdi`,
and (beyond the one question that surfaced its gap) the rest of
`census_bureau_acs` — are cataloged and searchable but have never actually
been asked a question in this project's live testing, so their real answer
quality is unverified rather than confirmed either way.

**3 hand-authored OKF docs** (`okf-catalog/`), the only entries in the catalog
not generated by the crawler:

- `ac.covid19_case_rate_by_county_year` — a `human-reviewed` Attested
  Computation: fixed, parameterized SQL for "case rate in \<county\> by
  year," the top trust tier. Narrow by design — one question shape, one
  table.
- `bq.bigquery-public-data.covid19_open_data.covid19_open_data` — a
  hand-written `Table` doc describing the same underlying table the crawler
  *also* catalogs automatically, under the identical `doc_id`.
  `discovery.discover()`'s dedup logic keeps whichever of the two scores
  higher for a given question, so the hand-authored doc and the crawler's
  machine-generated one are silently competing rather than one clearly
  superseding the other — worth resolving (retire one, or document why both
  are kept) rather than leaving it as a leftover from an early manual example.
- `ac.sec_edgar_company_metric_by_year` — a `human-reviewed` Attested
  Computation, but the first one that isn't BigQuery/SQL at all: it runs
  against SEC EDGAR's free `company-facts` XBRL API (`backend/accessor/
  sec_edgar_accessor.py`), resolving a company name or ticker to a CIK and
  returning one of eight curated financial metrics (revenue, net income,
  total assets, and similar), by year or across all years on file. The
  metric-to-XBRL-tag mapping is a small, human-reviewed Python dict, the
  same curated-mapping trust story as the COVID SQL template above, so the
  planner extracts parameter values only — never a raw tag or a query.

**Inherited but still inactive: Resource Raiser's other ~19 non-BigQuery
sources** (Census, Treasury, IRS Form 990, CDC, federal grants — everything
except SEC, which is now live via the Attested Computation above). The
generic OKF/REST fetcher that would query them is stubbed, not implemented
(`pipeline.py`'s `_fetch_one()`), and no OKF docs exist for any of them, so
none are queryable today. SEC EDGAR's company-facts API was the first of
these ported over — chosen because it's a genuinely free, no-key REST
endpoint (unlike, say, IRS Form 990's bulk-file/ETL shape) and a good
minimal validation of the pattern; the same curated-mapping approach could
extend to the others, at the cost of a new accessor module and OKF doc per
source, same as this one.

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
- **`machine-confirmed`** — a plain BigQuery table, described by the
  crawler directly from `INFORMATION_SCHEMA` (deterministic, template-driven
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
find a public dataset that answers this well enough to cite" rather than
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

## 8. Deployment topology

- **Frontend** — Firebase App Hosting, auto-deploys on every `git push` to
  `main` that touches `frontend/**` (connected via the Firebase console to
  this GitHub repo).
- **Orchestrator** — Cloud Run, deployed manually: `gcloud builds submit`
  + `gcloud run deploy` (no CI/CD wired yet — Workload Identity Federation
  for GitHub Actions is the one still-open infra item; see
  `infra/README.md`).
- **Crawler** — Cloud Run Job, invoked on demand or by the weekly Cloud
  Scheduler trigger set up in `infra/README.md`.
- **Admin notification** — Cloud Functions 2nd gen, deployed independently
  via `firebase deploy --only functions`.

## 9. Known gaps

Documented rather than hidden, since an honest account of what isn't done
is part of this write-up's job:

- The generic OKF/REST fetcher for non-BigQuery sources (Resource Raiser's
  original primary path) is stubbed, not implemented — SEC EDGAR (§5) is
  the one exception, ported as its own dedicated accessor rather than
  through that generic stub. Every other non-BigQuery source is still
  unreachable today.
- Two of the ten originally-evaluated test questions (Austin median
  household income; electric-vehicle Google Trends interest) still don't
  produce a real answer, for two different, now well-understood reasons —
  a coded-ID-only schema with no text column to match against, and what
  appears to be a genuine data-coverage gap in the crawled Trends tables —
  documented in full in `test_results.md`. Both fail honestly (a clear "no
  data" answer, visible in the reasoning trace) rather than silently or
  via a crash, and neither is offered as a suggested question in the UI.
- Workload Identity Federation for GitHub Actions CI/CD is designed but not
  set up; manual `gcloud` deploys are the equivalent today.
- Map visualizations fall back to a table — no mapping library is wired in.

## 10. References

- **[Agentic Resource Discovery (ARD)](https://agenticresourcediscovery.org/spec/)** spec, [repository](https://github.com/ards-project/ard-spec).
- **[Open Knowledge Format (OKF)](https://okf.md/spec/)** spec, [reference tooling](https://github.com/GoogleCloudPlatform/knowledge-catalog), [v0.2 trust-signals announcement](https://cloud.google.com/blog/products/data-analytics/okf-v0-2-adds-trust-signals).
- **[Resource Raiser](https://github.com/TechSoup/resource-raiser)** (TechSoup, Apache-2.0) — the pipeline this project forks.
