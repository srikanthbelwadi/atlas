#!/usr/bin/env bash
# Atlas × Google Data Commons — phase 0 on Google Cloud (project atlas-ard-okf).
#
# Idempotent; run from the repo root with gcloud authenticated:
#
#   DC_API_KEY=... scripts/datacommons_phase0.sh 2>&1 | tee /tmp/datacommons_phase0.log
#
# Steps:
#   1. Secret Manager: create/update `dc-api-key` from $DC_API_KEY and grant
#      the orchestrator's runtime service account access to it. Get a key
#      at https://apikeys.datacommons.org (hostname: the orchestrator's
#      run.app host; enable the REST V2 API on it).
#   2. Local smoke + timing run of the accessor (scripts/dc_smoke.py) so a
#      bad key or a changed API shape fails here, before a build.
#   3. Build the orchestrator image and deploy it as a NO-TRAFFIC revision
#      tagged `places`, with DC_API_KEY mounted from the secret (the Data
#      Commons templates live in the public catalog — no pack flag). The
#      public URL keeps serving the previous revision until you promote.
#   4. Print the tagged URL for the golden run:
#        scripts/golden_run.py --base <tagged-url> --token "$(scripts/firebase_token.sh)" \
#            --set tests/golden/places_a.yaml --report /tmp/places_a.md
#        scripts/golden_run.py ... --set tests/golden/public_regression.yaml   # did-not-interfere
#      Promote with: gcloud run services update-traffic atlas-orchestrator --to-latest --region=us-central1
set -euo pipefail

PROJECT=${PROJECT:-atlas-ard-okf}
REGION=${REGION:-us-central1}
SERVICE=${SERVICE:-atlas-orchestrator}
SECRET=${SECRET:-dc-api-key}
IMAGE_REPO="us-central1-docker.pkg.dev/${PROJECT}/atlas-images"
PACKS=${PACKS:-public,finance}

: "${DC_API_KEY:?set DC_API_KEY (https://apikeys.datacommons.org)}"
gcloud config set project "$PROJECT" >/dev/null

echo "== 1. Secret Manager: ${SECRET}"
if gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
  printf '%s' "$DC_API_KEY" | gcloud secrets versions add "$SECRET" --data-file=- --quiet
else
  printf '%s' "$DC_API_KEY" | gcloud secrets create "$SECRET" --data-file=- --replication-policy=automatic --quiet
fi
SA=$(gcloud run services describe "$SERVICE" --region="$REGION" --format="value(spec.template.spec.serviceAccountName)")
SA=${SA:-$(gcloud projects describe "$PROJECT" --format="value(projectNumber)")-compute@developer.gserviceaccount.com}
gcloud secrets add-iam-policy-binding "$SECRET" --member="serviceAccount:${SA}" --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
echo "-- secret readable by ${SA}"

echo "== 2. local smoke + timing (scripts/dc_smoke.py)"
python3 scripts/dc_smoke.py

echo "== 3. orchestrator: build + deploy a no-traffic revision tagged 'places'"
gcloud builds submit --config=infra/cloudbuild-orchestrator.yaml . --quiet
gcloud run deploy "$SERVICE" \
  --image="${IMAGE_REPO}/atlas-orchestrator:latest" --region="$REGION" \
  --no-traffic --tag=places \
  --update-env-vars="^:^ATLAS_PACKS_ENABLED=${PACKS}" \
  --update-secrets="DC_API_KEY=${SECRET}:latest" --quiet

echo "== 4. tagged URL (golden runs go here before promoting)"
gcloud run services describe "$SERVICE" --region="$REGION" --format="value(status.traffic)" | tr ';' '\n' | grep -i places || true
echo
echo "next: scripts/golden_run.py --base <tagged-url> --token \"\$(scripts/firebase_token.sh)\" --set tests/golden/places_a.yaml --report /tmp/places_a.md"
