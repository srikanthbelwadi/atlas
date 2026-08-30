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
- [ ] Firebase project linked, Firestore database + `ard_catalog` BigQuery dataset + `atlas-images` Artifact Registry repo created
- [x] Backend orchestrator (Phase 1): discover → plan → fetch → check → synthesize pipeline with live SSE trace, guarded BigQuery executor (dry-run byte cap + hard `maximum_bytes_billed` + wall-clock timeout), Firestore-backed per-user monthly budget ceiling, Firebase-Auth-gated `/ask` + admin approval console API
- [ ] `backend/crawler/` — scheduled BigQuery public-dataset enumeration into `ard_catalog.embeddings`
- [ ] `frontend/` — Next.js app (ask bar, live trace panel, adaptive answer canvas, admin console)
- [ ] GitHub Actions deploy pipelines wired to Cloud Run + Firebase Hosting

### Backend orchestrator

`backend/orchestrator/` is a FastAPI app (`main.py`) exposing:

- `POST /ask` — Firebase-ID-token-gated, streams the live query trace as SSE (`discover.*`, `plan.*`, `guardrail.*`, `fetch.*`, `check.*`, `synthesize.*`) then a terminal `answer` event with the grounded narrative, citations, and a visualization spec.
- `GET /healthz` — Cloud Run probe.
- `/admin/users`, `/admin/users/{uid}/approve|reject`, `/admin/usage/{uid}` — the approval console API, restricted to `ATLAS_ADMIN_EMAILS` (defaults to the product owner).

`backend/accessor/bigquery_accessor.py` never runs SQL without a preceding dry run against the caller's byte cap, and always sets `maximum_bytes_billed` on the real job as a server-side backstop. `backend/orchestrator/guardrails.py` tracks each user's month-to-date estimated spend in Firestore and blocks new queries once the $100/user ceiling is hit. `okf-catalog/` has two worked examples: a crawler-style `Table` doc (`bigquery-public-data.covid19_open_data`) and a human-reviewed `AttestedComputation` template (case rate by county/year) — the trusted, parameterized-SQL path the plan calls out as the preferred route whenever a question fits a known shape.

Not yet wired: the `on_user_created` Cloud Function that emails the admin when `users/{uid}` is created with `status: pending` (referenced in `main.py`'s docstring, lives under `infra/functions/` once built), and the generic OKF-driven fetcher for non-BigQuery sources ported from Resource Raiser.
