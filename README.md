# Atlas

A natural-language front door to every public BigQuery dataset — wrapped in ARD/OKF discovery, answered by Gemini, and grown from [Resource Raiser](https://github.com/TechSoup/resource-raiser)'s discover → plan → fetch → check → synthesize engine.

This repository is a derivative work of TechSoup's Resource Raiser (Apache License 2.0). Original copyright and license notices are retained in `THIRD_PARTY_NOTICES.md` as required by that license.

See the full implementation plan for architecture, the ARD/OKF wrapper design over BigQuery public datasets, the live query trace, access control, and the deployment pipeline.

## Layout

- `frontend/` — Next.js app, deployed via Firebase App Hosting
- `backend/orchestrator/` — the discover → plan → fetch → check → synthesize pipeline (Cloud Run)
- `backend/accessor/` — generic OKF-driven fetcher (REST sources) + guarded BigQuery executor
- `backend/crawler/` — scheduled BigQuery public-dataset enumeration + OKF/embedding generation (Cloud Run Job)
- `okf-catalog/` — git-versioned OKF bundle: the source of truth for the ARD registry
- `infra/` — infrastructure setup (Terraform or gcloud scripts): project, IAM, BigQuery, Cloud Run, Scheduler
- `.github/workflows/` — CI/CD: PR preview channels, backend deploy, weekly catalog refresh

## Status

- [x] Google Cloud project created (`atlas-ard-okf`), billing linked
- [x] Required APIs enabled (BigQuery, Vertex AI, Cloud Run, Cloud Build, Artifact Registry, Firebase, Firestore, Cloud Functions, Secret Manager, Cloud Scheduler, Identity Toolkit)
- [x] Firebase project linked, Firestore database + `ard_catalog` BigQuery dataset + `atlas-images` Artifact Registry repo created — all confirmed live in-console
- [x] Firebase Auth: Google sign-in enabled; web app registered, its config baked into `frontend/apphosting.yaml`
- [x] Backend orchestrator (Phase 1): discover → plan → fetch → check → synthesize pipeline with live SSE trace, guarded BigQuery executor (dry-run byte cap + hard `maximum_bytes_billed` + wall-clock timeout), Firestore-backed per-user monthly budget ceiling, Firebase-Auth-gated `/ask` + admin approval console API
- [x] `backend/crawler/` — curated-target BigQuery enumeration into `ard_catalog.embeddings` (Cloud Run Job, not yet deployed)
- [x] `frontend/` — Next.js app: Google sign-in gate, ask bar, live query trace panel, adaptive answer canvas (table/bar/line/kpi cards/infographic), admin approval console — type-checks and builds clean, not yet deployed
- [x] GitHub Actions workflows written (`deploy-backend.yml`, `deploy-frontend.yml` CI, `catalog-refresh.yml`) — blocked on Workload Identity Federation (see `infra/README.md`); manual Cloud Build equivalents (`infra/cloudbuild-*.yaml`) work today
- [ ] Orchestrator, crawler, and frontend actually deployed — `infra/README.md` has the exact remaining commands, including a real blocker found and fixed: Firebase App Hosting's "Connect GitHub" step needs the Developer Connect API enabled first, or it hangs silently

**No Vercel anywhere in this stack.** The frontend is a standard Next.js app, which is what Vercel is best known for hosting, but it deploys to **Firebase App Hosting** (which runs it on Cloud Run under the hood) — nothing in `frontend/` references Vercel, and `apphosting.yaml` is Firebase's own config format, not Vercel's.

### Backend orchestrator

`backend/orchestrator/` is a FastAPI app (`main.py`) exposing:

- `POST /ask` — Firebase-ID-token-gated, streams the live query trace as SSE (`discover.*`, `plan.*`, `guardrail.*`, `fetch.*`, `check.*`, `synthesize.*`) then a terminal `answer` event with the grounded narrative, citations, and a visualization spec.
- `GET /healthz` — Cloud Run probe.
- `/admin/users`, `/admin/users/{uid}/approve|reject`, `/admin/usage/{uid}` — the approval console API, restricted to `ATLAS_ADMIN_EMAILS` (defaults to the product owner).

`backend/accessor/bigquery_accessor.py` never runs SQL without a preceding dry run against the caller's byte cap, and always sets `maximum_bytes_billed` on the real job as a server-side backstop. `backend/orchestrator/guardrails.py` tracks each user's month-to-date estimated spend in Firestore and blocks new queries once the $100/user ceiling is hit. `okf-catalog/` has two worked examples: a crawler-style `Table` doc (`bigquery-public-data.covid19_open_data`) and a human-reviewed `AttestedComputation` template (case rate by county/year) — the trusted, parameterized-SQL path the plan calls out as the preferred route whenever a question fits a known shape.

Not yet wired: the `on_user_created` Cloud Function that emails the admin when `users/{uid}` is created with `status: pending` (referenced in `main.py`'s docstring, lives under `infra/functions/` once built), and the generic OKF-driven fetcher for non-BigQuery sources ported from Resource Raiser.

### Crawler

`backend/crawler/main.py` is a Cloud Run Job entrypoint (`python -m backend.crawler.main`, weekly via Cloud Scheduler once deployed): for each `(project, dataset)` in the curated allowlist in `targets.py`, it enumerates tables via `INFORMATION_SCHEMA`, builds a deterministic schema-derived description (never model-generated, so it can't hallucinate what a table contains — see the trust note in `main.py`), embeds it, and upserts into `ard_catalog.embeddings`, which `discovery.py` queries with BigQuery `VECTOR_SEARCH` at request time. The target list is deliberately a curated ~14 datasets, not all of `bigquery-public-data` — most of that project is either far larger than the byte cap makes usable or too niche for a general natural-language front door.

### Frontend

`frontend/` is a Next.js 14 App Router app deployed via Firebase App Hosting:

- `app/page.tsx` — the ask experience: `AskBar` posts to `/ask` and streams the SSE response by hand (native `EventSource` can't carry the Firebase ID token the backend requires), `TracePanel` renders the live query trace as a stage-by-stage timeline, `AnswerCanvas` renders the narrative + citations + whichever visualization kind the synthesis model chose (table, bar, line, KPI cards, infographic; map falls back to a table until a mapping library is wired in).
- `app/admin/page.tsx` — the approval console: lists pending/approved/rejected users, approve/reject buttons calling the backend's `/admin/*` API. No separate admin auth scheme — same Firebase ID token, checked server-side against `ATLAS_ADMIN_EMAILS`.
- Design system: IBM Plex Serif/Sans/Mono, a navy/amber/teal palette defined as CSS custom properties in `app/globals.css` with a `prefers-color-scheme: dark` variant.
- `npm install && npx tsc --noEmit && npx next build` all pass as of this commit. Per the "web only, never local" instruction, this has been verified to *build* correctly but not run in a browser yet — that happens once it's deployed to an App Hosting preview channel.
