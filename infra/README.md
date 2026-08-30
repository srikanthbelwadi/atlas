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
  --region=us-central1 --allow-unauthenticated \
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
- **`on_user_created` Cloud Function**: Firestore trigger on `users/{uid}`
  create with `status: pending`, emails `ATLAS_ADMIN_EMAILS` (Firebase
  "Trigger Email" extension, SendGrid-backed, or a plain `smtplib` call from
  a 2nd-gen Cloud Function) — referenced in `backend/orchestrator/main.py`'s
  docstring, not yet built
- **Cloud Scheduler job** to invoke the crawler's Cloud Run Job weekly
  (`gcloud scheduler jobs create http ... --uri=.../jobs/atlas-crawler:run`)
  — the crawler image and job exist after step 9 above, this just automates
  the recurring re-run
- Add the App Hosting backend's live URL to Firebase Auth's **authorized
  domains** list (Authentication → Settings) once it exists, or Google
  sign-in will reject it
