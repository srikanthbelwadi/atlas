# Infra

No Terraform yet — the project is small enough that a short, ordered list of
commands is more honest about what's actually been run than a state file
that's out of sync with reality. This doc is that list. Everything here is
idempotent (safe to re-run).

Project: `atlas-ard-okf`. Region: `us-central1` (Cloud Run, Vertex AI);
BigQuery datasets are multi-region `US` to match `bigquery-public-data`.

## Done

```bash
# 1. APIs
gcloud services enable bigquery.googleapis.com aiplatform.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com firebase.googleapis.com \
  firestore.googleapis.com cloudfunctions.googleapis.com secretmanager.googleapis.com \
  cloudscheduler.googleapis.com identitytoolkit.googleapis.com --project=atlas-ard-okf
```

## Remaining (run in Cloud Shell, project atlas-ard-okf)

```bash
# 2. Link Firebase to the GCP project (safe to re-run)
firebase projects:addfirebase atlas-ard-okf

# 3. Firestore database (Native mode — Firestore, not Datastore mode)
gcloud firestore databases create --project=atlas-ard-okf --location=us-central1 --type=firestore-native

# 4. ard_catalog BigQuery dataset + embeddings table
bq query --use_legacy_sql=false < infra/setup.sql
# (or the crawler creates these itself on first run — see backend/crawler/main.py:ensure_catalog_table)

# 5. Artifact Registry repo for orchestrator/crawler container images
gcloud artifacts repositories create atlas-images \
  --repository-format=docker --location=us-central1 --project=atlas-ard-okf

# 6. Enable Google as a Firebase Auth sign-in provider (console step, no CLI
#    equivalent): console.cloud.google.com/customer-identity/providers,
#    project atlas-ard-okf -> enable "Google"
```

## Still to design/build

- **Workload Identity Federation** for GitHub Actions -> Cloud Run/Artifact
  Registry deploys without a long-lived service-account key
  (`.github/workflows/deploy-backend.yml` currently a placeholder pending this)
- **`on_user_created` Cloud Function**: Firestore trigger on `users/{uid}`
  create with `status: pending`, emails `ATLAS_ADMIN_EMAILS` (Firebase
  "Trigger Email" extension, SendGrid-backed, or a plain `smtplib` call from
  a 2nd-gen Cloud Function) — referenced in `backend/orchestrator/main.py`'s
  docstring, not yet built
- **Cloud Scheduler job** to invoke the crawler's Cloud Run Job weekly
  (`gcloud scheduler jobs create http ... --uri=.../jobs/atlas-crawler:run`)
  once the crawler image has been built and deployed once by hand
