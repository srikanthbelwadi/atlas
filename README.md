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

Phase 0 (project + repo + CI/CD skeleton) — in progress.

- [x] Google Cloud project created (`atlas-ard-okf`), billing linked
- [ ] Required APIs enabled
- [ ] Firebase project linked, Hosting/App Hosting configured
- [ ] GitHub Actions deploy pipelines wired to Cloud Run + Firebase Hosting
