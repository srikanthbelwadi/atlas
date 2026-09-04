# Atlas

A natural-language front door to large-scale data — any data store or API
described once in [OKF](https://okf.md/spec/), discovered through
[ARD](https://agenticresourcediscovery.org/spec/), answered by Gemini under
hard cost guardrails, and grown from
[NeuralKG](https://github.com/rvguha/Neuralkg)'s
discover → plan → fetch → check → synthesize engine.

The approach works for enterprise private warehouses, operational stores and
internal APIs exactly as it does for the demo. BigQuery is the first-class
executor; the **demo instance** is pointed at a curated set of BigQuery
datasets plus the SEC EDGAR API because they are large, real, and free to
query without credentials — not because the design is limited to them.

This repository is a derivative work of NeuralKG (Apache License 2.0). Original copyright and license notices are retained in `THIRD_PARTY_NOTICES.md` as required by that license.

See `IMPLEMENTATION.md` for the full engineering design: architecture, the ARD/OKF catalog over BigQuery and API sources, life of a query end to end, cost guardrails, grounding/citation model, the live reasoning trace, and exactly what was kept vs. replaced vs. newly built relative to NeuralKG.

## Layout

- `frontend/` — Next.js app, deployed via Firebase App Hosting
- `backend/orchestrator/` — the discover → plan → fetch → check → synthesize pipeline (Cloud Run)
- `backend/accessor/` — generic OKF-driven fetcher (REST sources) + guarded BigQuery executor
- `backend/crawler/` — scheduled BigQuery dataset enumeration + OKF/embedding generation (Cloud Run Job); point it at any project/dataset the service account can read
- `okf-catalog/` — git-versioned OKF bundle: the source of truth for the ARD registry
- `infra/` — infrastructure setup (Terraform or gcloud scripts): project, IAM, BigQuery, Cloud Run, Scheduler
- `.github/workflows/` — CI/CD: PR preview channels, backend deploy, weekly catalog refresh

## Status

- [x] Google Cloud project created (`atlas-ard-okf`), billing linked
- [x] Required APIs enabled (BigQuery, Vertex AI, Cloud Run, Cloud Build, Artifact Registry, Firebase, Firestore, Cloud Functions, Secret Manager, Cloud Scheduler, Identity Toolkit)
- [x] Firebase project linked, Firestore database + `ard_catalog` BigQuery dataset + `atlas-images` Artifact Registry repo created — all confirmed live in-console
- [x] Firebase Auth: Google sign-in enabled; web app registered, its config baked into `frontend/apphosting.yaml`
- [x] Backend orchestrator (Phase 1): discover → plan → fetch → check → synthesize pipeline with live SSE trace, guarded BigQuery executor (dry-run byte cap + hard `maximum_bytes_billed` + wall-clock timeout), Firestore-backed per-user monthly budget ceiling, Firebase-Auth-gated `/ask` + admin approval console API
- [x] Orchestrator deployed to Cloud Run (`atlas-orchestrator`), confirmed live at `https://atlas-orchestrator-653988957394.us-central1.run.app`
- [x] `backend/crawler/` — curated-target BigQuery enumeration into `ard_catalog.embeddings` (Cloud Run Job `atlas-crawler`); first run hit a real bug (BigQuery rejects `NOT NULL` on the `embedding ARRAY<FLOAT64>` column — fixed in `backend/crawler/main.py` and `infra/setup.sql`), rerun triggered after the fix
- [x] `frontend/` — Next.js app: Google sign-in gate, ask bar, live query trace panel, adaptive answer canvas (table/bar/line/kpi cards/infographic), admin approval console — type-checks and builds clean
- [x] GitHub Actions workflows written (`deploy-backend.yml`, `deploy-frontend.yml` CI, `catalog-refresh.yml`) — blocked on Workload Identity Federation (see `infra/README.md`); manual Cloud Build equivalents (`infra/cloudbuild-*.yaml`) work today
- [x] Firebase App Hosting backend `atlas-web` created via `firebase apphosting:backends:create`, connected to `srikanthbelwadi/atlas`'s `main` branch (nodejs22 runtime), first rollout triggered — live at `https://atlas-web--atlas-ard-okf.us-central1.hosted.app` once the rollout finishes; that hostname is added to Firebase Auth's authorized domains so Google sign-in works there
- [x] `on_user_created` Cloud Function (`infra/functions/on_user_created`) — emails `ATLAS_ADMIN_EMAILS` when a new `users/{uid}` doc lands as `status: pending`; deploy steps in `infra/README.md`
- [x] Cloud Scheduler job for the weekly crawler re-run — command in `infra/README.md`
- [x] Finance pack (`/finance`): pack-isolated catalog, 16 attested computations, receipts, fact-check; golden sets pass 22/22 (see `IMPLEMENTATION.md` §9, `skills/finance/` and `tests/golden/`)
- [x] Private internal risk mart (`finance_demo`, `visibility: private`, entitlements, withheld-source refusals, private receipts); loaded, crawled and live — golden sets `finance_d` 6/6 and `finance_d_noaccess` 4/4 (`IMPLEMENTATION.md` §5.4, §8.3)
- [ ] Workload Identity Federation for CI/CD (see "Still to design/build" in `infra/README.md`)

**No Vercel anywhere in this stack.** The frontend is a standard Next.js app, which is what Vercel is best known for hosting, but it deploys to **Firebase App Hosting** (which runs it on Cloud Run under the hood) — nothing in `frontend/` references Vercel, and `apphosting.yaml` is Firebase's own config format, not Vercel's.

### Backend orchestrator

`backend/orchestrator/` is a FastAPI app (`main.py`) exposing:

- `POST /ask` — Firebase-ID-token-gated, streams the live query trace as SSE (`discover.*`, `plan.*`, `guardrail.*`, `fetch.*`, `check.*`, `synthesize.*`) then a terminal `answer` event with the grounded narrative, citations, and a visualization spec.
- `GET /healthz` — Cloud Run probe.
- `/admin/users`, `/admin/users/{uid}/approve|reject`, `/admin/usage/{uid}` — the approval console API, restricted to `ATLAS_ADMIN_EMAILS` (defaults to the product owner).

`backend/accessor/bigquery_accessor.py` never runs SQL without a preceding dry run against the caller's byte cap, and always sets `maximum_bytes_billed` on the real job as a server-side backstop. `backend/orchestrator/guardrails.py` tracks each user's month-to-date estimated spend in Firestore and blocks new queries once the $100/user ceiling is hit. `okf-catalog/` has two worked examples: a crawler-style `Table` doc (`bigquery-public-data.covid19_open_data`) and a human-reviewed `AttestedComputation` template (case rate by county/year) — the trusted, parameterized-SQL path the plan calls out as the preferred route whenever a question fits a known shape.

API sources are added the way SEC EDGAR was: one OKF document plus one accessor module (`backend/accessor/sec_edgar_accessor.py` is the template); `_fetch_one()` in `pipeline.py` is the dispatch point. The `on_user_created` Cloud Function referenced in `main.py`'s docstring is built — see `infra/functions/on_user_created/`.

### Crawler

`backend/crawler/main.py` is a Cloud Run Job entrypoint (`python -m backend.crawler.main`, weekly via Cloud Scheduler once deployed): for each `(project, dataset)` in the curated allowlist in `targets.py`, it enumerates tables via `INFORMATION_SCHEMA`, builds a deterministic schema-derived description (never model-generated, so it can't hallucinate what a table contains — see the trust note in `main.py`), embeds it, and upserts into `ard_catalog.embeddings`, which `discovery.py` queries with BigQuery `VECTOR_SEARCH` at request time. The demo target list is a curated 14 datasets from `bigquery-public-data` (see `IMPLEMENTATION.md` §8 for what each covers and how large it is); the same crawler runs unchanged against any private project/dataset the service account can read.

### Frontend

`frontend/` is a Next.js 14 App Router app deployed via Firebase App Hosting:

- `app/page.tsx` — the ask experience: `AskBar` posts to `/ask` and streams the SSE response by hand (native `EventSource` can't carry the Firebase ID token the backend requires), `TracePanel` renders the live query trace as a stage-by-stage timeline, `AnswerCanvas` renders the narrative + citations + whichever visualization kind the synthesis model chose (table, bar, line, KPI cards, infographic; map falls back to a table until a mapping library is wired in).
- `app/admin/page.tsx` — the approval console: lists pending/approved/rejected users, approve/reject buttons calling the backend's `/admin/*` API. No separate admin auth scheme — same Firebase ID token, checked server-side against `ATLAS_ADMIN_EMAILS`.
- Design system: IBM Plex Serif/Sans/Mono, a navy/amber/teal palette defined as CSS custom properties in `app/globals.css` with a `prefers-color-scheme: dark` variant.
- `npm install && npx tsc --noEmit && npx next build` all pass as of this commit. Per the "web only, never local" instruction, this has been verified to *build* correctly but not run in a browser yet — that happens once it's deployed to an App Hosting preview channel.

## References

- **[Agentic Resource Discovery (ARD)](https://agenticresourcediscovery.org/spec/)** — the discovery-side specification `discovery.py`'s candidate resolution is modeled on: resources described once, indexed by a registry, and searched rather than manually wired up. Spec repository: [ards-project/ard-spec](https://github.com/ards-project/ard-spec).
- **[Open Knowledge Format (OKF)](https://okf.md/spec/)** — the markdown-with-YAML-frontmatter format `okf-catalog/` is written in, including the three-tier trust model (`unverified` / `machine-confirmed` / `human-reviewed`) surfaced throughout the pipeline and UI. Reference tooling: [GoogleCloudPlatform/knowledge-catalog](https://github.com/GoogleCloudPlatform/knowledge-catalog); announcement: [Google Cloud Blog](https://cloud.google.com/blog/products/data-analytics/okf-v0-2-adds-trust-signals).
- **[NeuralKG](https://github.com/rvguha/Neuralkg)** — the discover → plan → fetch → check → synthesize pipeline this project forks and extends with a guarded BigQuery executor and OKF-described API sources. See `THIRD_PARTY_NOTICES.md` for the Apache-2.0 notice and a summary of what changed.
- **`IMPLEMENTATION.md`** — the single implementation document (also rendered at [atlasdata.world/implementation](https://atlasdata.world/implementation), no sign-in needed): architecture, the catalog model (packs, trust tiers, private catalogs and entitlements), executors and guardrails, receipts and the trace, every data source, the finance pack as one section, the HTTP API and agent skills, and the fork-vs-new-work breakdown against NeuralKG. `docs/FINANCE-DESIGN.md` is the pre-build design note for the finance pack, kept for history.
