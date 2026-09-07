# Infra

No Terraform yet — the project is small enough that a short, ordered list of
commands is more honest about what's actually been run than a state file
that's out of sync with reality. This doc is that list. Everything here is
idempotent (safe to re-run).

Project: `atlas-ard-okf`. Region: `us-central1` (Cloud Run, Vertex AI);
BigQuery datasets are multi-region `US` to match `bigquery-public-data`.

Nothing here uses Vercel or any non-Google host — the frontend deploys to
Firebase App Hosting (which runs on Cloud Run under the hood), the backend to
Cloud Run directly, and the crawler as a Cloud Run Job. Firebase + Google
Cloud only, per the product decision.

## Done

```bash
# 1. APIs
gcloud services enable bigquery.googleapis.com aiplatform.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com firebase.googleapis.com \
  firestore.googleapis.com cloudfunctions.googleapis.com secretmanager.googleapis.com \
  cloudscheduler.googleapis.com identitytoolkit.googleapis.com --project=atlas-ard-okf

# 2. Link Firebase to the GCP project
firebase projects:addfirebase atlas-ard-okf

# 3. Firestore database (Native mode) — confirmed live: (default), Standard edition, us-central1
gcloud firestore databases create --project=atlas-ard-okf --location=us-central1 --type=firestore-native

# 4. ard_catalog BigQuery dataset — confirmed live, empty (crawler hasn't run yet)
bq query --use_legacy_sql=false < infra/setup.sql

# 5. Artifact Registry repo for orchestrator/crawler images — confirmed live
gcloud artifacts repositories create atlas-images \
  --repository-format=docker --location=us-central1 --project=atlas-ard-okf
```

Also done via the Firebase console (no CLI equivalent): Google enabled as an
Authentication sign-in provider, and a web app ("atlas-web") registered to
get the client-side Firebase config now baked into `frontend/apphosting.yaml`
and `frontend/.env.local.example`.

## Remaining (run in Cloud Shell, project atlas-ard-okf)

```bash
# 6. Developer Connect API — REQUIRED before "Connect GitHub" works in the
#    App Hosting setup wizard. Without this, the wizard hangs on "Import a
#    GitHub repository" and silently fails: the underlying GitHub connection
#    needs a Google-managed service agent
#    (service-<PROJECT_NUMBER>@gcp-sa-devconnect.iam.gserviceaccount.com)
#    that only gets created once this API is enabled. Confirmed via the
#    browser console's own network log — a SetIamPolicy call failing with
#    "Service account ...@gcp-sa-devconnect.iam.gserviceaccount.com does not
#    exist."
gcloud services enable developerconnect.googleapis.com --project=atlas-ard-okf

# 7. Clone the repo here (Cloud Shell's disk is ephemeral per session)
git clone https://github.com/srikanthbelwadi/atlas.git
cd atlas

# 8. Build + deploy the orchestrator to Cloud Run
gcloud builds submit --config=infra/cloudbuild-orchestrator.yaml .
gcloud run deploy atlas-orchestrator \
  --image=us-central1-docker.pkg.dev/atlas-ard-okf/atlas-images/atlas-orchestrator:latest \
  --region=us-central1 --allow-unauthenticated --timeout=600 \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=atlas-ard-okf,VERTEX_LOCATION=us-central1

# 9. Build the crawler image, create its Cloud Run Job, and run it once to
#    seed ard_catalog.embeddings before anyone asks a question
gcloud builds submit --config=infra/cloudbuild-crawler.yaml .
gcloud run jobs deploy atlas-crawler \
  --image=us-central1-docker.pkg.dev/atlas-ard-okf/atlas-images/atlas-crawler:latest \
  --region=us-central1 --set-env-vars=GOOGLE_CLOUD_PROJECT=atlas-ard-okf \
  --max-retries=1 --task-timeout=15m
gcloud run jobs execute atlas-crawler --region=us-central1
```

After step 8, copy the printed Cloud Run URL into
`frontend/apphosting.yaml`'s `NEXT_PUBLIC_ATLAS_API_BASE_URL` (replacing the
`atlas-orchestrator-REPLACE.run.app` placeholder), commit, and push — App
Hosting picks up the change on its next deploy once it's connected (next
section).

```bash
# 10. Weekly re-crawl: have Cloud Scheduler invoke the crawler's Cloud Run
#     Job on a schedule instead of re-running step 9's last line by hand.
#     Needs a service account with permission to invoke Cloud Run Jobs —
#     the Compute Engine default service account (used implicitly above)
#     already has this in a fresh project; tighten it to a dedicated SA
#     later if desired.
gcloud scheduler jobs create http atlas-crawler-weekly \
  --project=atlas-ard-okf --location=us-central1 \
  --schedule="0 6 * * 1" \
  --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/atlas-ard-okf/jobs/atlas-crawler:run" \
  --http-method=POST \
  --oauth-service-account-email="$(gcloud projects describe atlas-ard-okf --format='value(projectNumber)')-compute@developer.gserviceaccount.com"

# 11. Admin sign-up notification: emails ATLAS_ADMIN_EMAILS when a new
#     users/{uid} doc lands as status="pending" (infra/functions/on_user_created).
#     One-time: install firebase-tools if you don't have it, and set the
#     SMTP password as a secret (never a plain env var / never committed).
npm install -g firebase-tools
firebase functions:secrets:set ATLAS_SMTP_PASSWORD --project=atlas-ard-okf

# Then, every deploy: copy infra/functions/on_user_created/.env.example to
# infra/functions/on_user_created/.env (gitignored) with real, non-secret
# values (admin emails, SMTP host/user), and deploy:
firebase deploy --only functions --project=atlas-ard-okf
```

## Connecting the frontend (after step 6 above)

In the Firebase console: **App Hosting → Get started → region us-central1 →
Connect GitHub → `srikanthbelwadi/atlas`, root directory `frontend/`**. This
opens a GitHub App install/authorization popup — that's a real permission
grant to your GitHub account, so it needs you to click through it directly
rather than being automated. Once connected, every push to `main` touching
`frontend/**` deploys automatically; no separate GitHub Actions step ships
it (see `.github/workflows/deploy-frontend.yml`'s docstring).

## Still to design/build

- **Workload Identity Federation** for GitHub Actions -> Cloud Run/Artifact
  Registry deploys without a long-lived service-account key
  (`.github/workflows/deploy-backend.yml` / `catalog-refresh.yml` currently
  placeholders pending this — steps 8/9 above are the manual equivalent)
- Add the App Hosting backend's live URL to Firebase Auth's **authorized
  domains** list (Authentication → Settings) once it exists, or Google
  sign-in will reject it

Both the `on_user_created` admin-notification Cloud Function and the weekly
Cloud Scheduler re-crawl are now built — see steps 10/11 above.


## Finance pack

`scripts/finance_phase0.sh` does every Google Cloud step the finance section
needs, in order: the `finance_pack` dataset and entity crosswalk
(`infra/finance/setup.sql`, CSV load, MERGE), a crawler rebuild and one
`--pack finance` run, the crosswalk check (`infra/finance/xref_check.sql`),
and an orchestrator build deployed as a **no-traffic** Cloud Run revision
tagged `finance` with `ATLAS_PACKS_ENABLED=public,finance`. Golden runs
(`scripts/golden_run.py`, sets in `tests/golden/`) go against the tagged
URL; `tests/golden/public_regression.yaml` is the "did not interfere"
check. Promote with `gcloud run services update-traffic atlas-orchestrator
--to-latest`, then set `NEXT_PUBLIC_ATLAS_FINANCE_ENABLED` to `"true"` in
`frontend/apphosting.yaml`.

## Adding a backend package

`backend/orchestrator/Dockerfile` copies the backend packages it needs one
by one (`orchestrator`, `accessor`, `crawler` targets, `geo`). A new
package under `backend/` needs its own `COPY` line or the container fails
at import time and the revision serves 503 — found live when `backend/geo`
was added.

## Google Data Commons (public catalog)

`scripts/datacommons_phase0.sh` (needs `DC_API_KEY` in the environment — a free
key from https://apikeys.datacommons.org with the REST V2 API enabled)
stores the key in Secret Manager as `dc-api-key`, grants the orchestrator's
service account access, runs `scripts/dc_smoke.py` against the live API,
and deploys a **no-traffic** revision tagged `places` with `DC_API_KEY`
mounted from the secret (the two Data Commons templates are part of the
public catalog — no pack flag). Golden runs: `tests/golden/places_a.yaml`
against the tagged URL, plus `public_regression.yaml` and `finance_a.yaml`
as the did-not-interfere checks. Promote with `gcloud run services
update-traffic atlas-orchestrator --to-latest`. No BigQuery, crawler or
Firestore changes — Data Commons is an API source like SEC EDGAR.

### Private internal data (use case D)

Two datasets in the project that are never public: `finance_demo_raw`
(loads as they arrive; not catalogued) and `finance_demo` (four curated
tables: `loan_applications`, `bureau_credits`, `installment_payments`,
`payment_transactions`, built by `infra/finance/private_setup.sql`).
`scripts/finance_private_load.sh [DATA_DIR]` does the whole load — Kaggle
originals (Home Credit Default Risk + PaySim) or the synthetic set that
`scripts/finance_private_synth.py` writes with the same column names —
through a private bucket `gs://atlas-ard-okf-finance-demo`, and ends by
printing both datasets' ACLs, flagging any `allUsers` /
`allAuthenticatedUsers` binding. `scripts/finance_phase_d.sh` then rebuilds
and runs the crawler for the finance pack (the `finance_demo` rows get
`visibility=private` / `entitlement=finance.internal` in their metadata),
redeploys the tagged orchestrator revision, prints who can read the dataset
(dataset ACL + project BigQuery roles + the orchestrator's service account),
and grants the `finance.internal` entitlement to the test account
(`scripts/finance_entitle.py`, or the toggle on `/admin`). Golden sets:
`tests/golden/finance_d.yaml` (entitled) and `finance_d_noaccess.yaml`
(entitlement revoked — internal questions must be refused naming the
withheld sources).
