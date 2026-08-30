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
title). The full prompt is reproduced in §7 below alongside the specific
bugs it was written to fix.

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
single-candidate plan rather than reusing the original — see §7.3, the most
architecturally significant bug found in this pipeline.

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

## 5. Grounding and citations

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

## 6. Cost optimization and guardrails

Two independent, server-side-only limits (`guardrails.py`), both enforced
before spend happens rather than measured after:

1. **Per-query byte cap.** A BigQuery dry run estimates bytes scanned before
   any real query runs. Two tiers: 20 GB for trusted Attested Computation
   templates, 10 GB for ad-hoc SQL a model drafted — templates get more
   headroom because their SQL is human-reviewed and known-safe, while
   freshly-drafted SQL against an unfamiliar table is capped tighter. The
   estimate is checked *and* the same cap is set as `maximum_bytes_billed`
   on the real job, because a dry run and the actual scan can legitimately
   differ.

2. **Per-user monthly ceiling** ($100, configurable via
   `ATLAS_MONTHLY_COST_CEILING_USD`) — tracked in Firestore
   (`usage/{uid}_{yyyy-mm}`) as a running estimated-cost total, checked
   *before* the discover stage even starts. Real cost, not a flat guess:
   BigQuery bytes billed at the on-demand $6.25/TiB rate, plus actual
   Gemini `usage_metadata` token counts (prompt/output, priced separately
   per model tier via env vars — flagged in the code as placeholders to be
   checked against Vertex AI's current published pricing before relying on
   them for real budget enforcement).

A backtrack's redrafted plan is a genuine extra Gemini call with its own
real cost. Early in this pipeline's life that cost would have been silently
excluded from both the walkthrough's displayed total and the budget-ceiling
check — found and fixed by summing every `plan` + `plan_backtrack_N` usage
entry into one total before it's billed (`pipeline.py`), so a question that
needed two planning attempts is actually charged for two.

The crawler's own design is a cost decision: rather than cataloging all of
`bigquery-public-data` (thousands of tables, many multi-terabyte), it crawls
a curated, growable allowlist of ~14 datasets (`backend/crawler/targets.py`)
chosen for being broadly useful and byte-cap-friendly. Tables over 50 GB are
still cataloged (so the model knows they exist) but flagged `large_table`,
nudging the planner toward a template over ad-hoc SQL for them.

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

### 7.1–7.3: three real bugs found by running this pipeline live

Documentation of intent is cheap; these were found by actually asking
Atlas questions and reading what came back wrong, then fixed at the root:

**7.1 — Discovery's ranking never reached the planner (Q2).** Asked to
compare life expectancy in Japan vs. the US, discovery correctly ranked
`world_bank_health_population.country_summary` highest — but
`_describe_candidate_for_planning()` stripped the `score` field before the
planner ever saw it, so nothing signaled that discovery had already done
this work. The model picked a COVID-data table that merely *sounded*
on-topic instead. Fixed by forwarding `score` into the prompt and telling
it candidates arrive pre-ranked, best first, requiring a specific concrete
reason (a missing needed column, missing required params) to override
that ranking rather than a title-level hunch.

**7.2 — Backtrack reused a stale, single-candidate SQL plan (Q4).**
`classify_and_plan` was called exactly once, up front, against the
originally-chosen candidate — but that one `plan` object (including its
one drafted `sql` string, valid only for that candidate's real schema) was
then reused verbatim on every backtrack attempt against a *different*
candidate. Asked about India's GDP per capita, the backtrack attempt
failed with "Planner marked needs_sql but produced no SQL" — Gemini's
answer for the first candidate's columns, reused against a table it was
never drafted for. Fixed by redrafting a fresh, single-candidate plan on
every attempt after the first, with its own `plan.started`/`plan.done`
trace pair (§7's backtrack reasoning above is this fix's direct
side-benefit).

**7.3 — Literal-value SQL against real-world text columns.** Ad-hoc SQL
using exact equality (`place_name = 'Austin, Texas'`) routinely missed real
data stored under different phrasing. Fixed with an explicit prompting rule
to prefer case-insensitive `LIKE` matching on free-text columns, and a
coded/enum column over a free-text one whenever the schema exposes both.
This measurably improved routing quality (California's unemployment rate
now resolves correctly on the first attempt), though it is not a universal
fix: some tables' only identifying column is a coded ID with no text name
at all (Census `place_*` tables' `geo_id` is a bare FIPS code), which no
amount of LIKE-matching can resolve — a data-model gap, not a prompting
one, documented honestly in `test_results.md` rather than papered over.

## 8. Access control and identity

Firebase Auth (Google sign-in) end to end — no separate session or JWT
scheme. Every request to `/ask` and every `/admin/*` call carries the
Firebase ID token as `Authorization: Bearer <token>`, verified server-side
by the Firebase Admin SDK on every call (`main.py`'s `_verify_token`).

New sign-ins default to `status: "pending"` in a `users/{uid}` Firestore
doc and get a 403 until an admin approves them via the `/admin` console —
except two allowlists, both env-var-driven and empty by default so a fresh
deploy behaves exactly as before either was added:

- `ATLAS_ADMIN_EMAILS` — full admin access (approve/reject other users,
  view usage).
- `ATLAS_PREAPPROVED_EMAILS` — skips the approval queue entirely, landing
  as `status: "approved"` on first sign-in, but otherwise an ordinary user
  (shows up as "approved" in the console, not as an admin). Also flips an
  *existing* pending doc to approved on that user's next request, covering
  an email added to the list after that person already signed in once.

An admin who wants to know about a new pending sign-up without polling the
console gets one: `infra/functions/on_user_created` is a Firestore-triggered
2nd-gen Cloud Function, deployed independently of the orchestrator, that
emails `ATLAS_ADMIN_EMAILS` when a `users/{uid}` doc lands as `pending`. It
no-ops safely (logs and returns) if its SMTP transport isn't configured yet,
rather than ever failing the write it's reacting to or retrying
indefinitely — a missing secret degrades to "no notification," never to a
broken sign-up flow.

## 9. Frontend behavior worth calling out

- **SSE by hand.** The backend's `/ask` stream needs the caller's Firebase
  ID token, which the native `EventSource` API can't attach — `lib/api.ts`
  reads the stream manually instead.
- **A stream that ends without a terminal event still resolves cleanly.**
  If the connection drops mid-stream (proxy timeout, server crash) with no
  `answer` or `error` event ever seen, `AskBar.tsx` still surfaces "The
  connection ended before Atlas finished answering" and clears the busy
  state — found while chasing a "stuck on Asking…" report that turned out
  to have two independent causes (a real backend bug, and this gap, which
  would have produced the identical symptom on its own).
- **The question box clears itself on submit**, not just on response.
  Before this, `AskBar`'s input value was only ever set by typing — nothing
  reset it after a question was sent, so leftover text sat in the box and a
  follow-up question typed without clearing it first landed at whatever
  cursor position a click happened to produce, silently concatenating two
  questions into one garbled submission (reproduced live while testing the
  Q2/Q4 fixes above).
- **Visualization components validate shape, not just JSON syntax.** The
  synthesis model's output is schema-constrained but only to field names
  and types — nothing stops a "line" visualization from omitting a usable
  `series` array. Every `*Viz` component in `AnswerCanvas.tsx` re-validates
  its expected shape after parsing and falls back to an empty state rather
  than crashing on `.length` of `undefined` — the exact failure mode this
  defensive parsing was added after hitting live.
- **Chart label sizing is data-driven, not fixed.** A bar chart's rotated
  first label can swing past the SVG's left edge; the fix sizes the
  left-side padding off that specific label's character count rather than
  a constant, because a flat pad tuned for one test case clipped a longer
  real one on the very next query.

## 10. Deployment topology

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

Exact, copy-pasteable commands for every one of these live in
`infra/README.md`, kept as an ordered, idempotent list rather than a
Terraform state file — the project is small enough that an honest command
log is more trustworthy than infrastructure-as-code that could silently
drift from what was actually run.

## 11. Known gaps

Documented rather than hidden, since an honest account of what isn't done
is part of this write-up's job:

- The generic OKF/REST fetcher for non-BigQuery sources (Resource Raiser's
  original primary path) is stubbed, not implemented — every source Atlas
  can actually answer from today is BigQuery.
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

## 12. References

- **[Agentic Resource Discovery (ARD)](https://agenticresourcediscovery.org/spec/)** spec, [repository](https://github.com/ards-project/ard-spec).
- **[Open Knowledge Format (OKF)](https://okf.md/spec/)** spec, [reference tooling](https://github.com/GoogleCloudPlatform/knowledge-catalog), [v0.2 trust-signals announcement](https://cloud.google.com/blog/products/data-analytics/okf-v0-2-adds-trust-signals).
- **[Resource Raiser](https://github.com/TechSoup/resource-raiser)** (TechSoup, Apache-2.0) — the pipeline this project forks; see `THIRD_PARTY_NOTICES.md`.
- `README.md` — repo layout and current build/deploy status.
- `infra/README.md` — the exact, ordered command log for every piece of infrastructure this project runs on.
- `test_results.md` — the full live evaluation history (10 original questions, plus the Q2/Q3/Q4/Q6/Q7 backend fix pass) this document's claims are grounded in.
