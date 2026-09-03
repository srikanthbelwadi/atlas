#!/usr/bin/env bash
# Rebuild the orchestrator image from the working tree and redeploy the
# NO-TRAFFIC revision tagged `finance` (public traffic untouched). Run after
# any backend/catalog change, before golden runs:
#   scripts/finance_redeploy.sh 2>&1 | tee ~/Documents/ARD_UKF/logs/finance_redeploy.log
set -euo pipefail
PROJECT=${PROJECT:-atlas-ard-okf}; REGION=${REGION:-us-central1}
IMAGE_REPO="us-central1-docker.pkg.dev/${PROJECT}/atlas-images"
gcloud config set project "$PROJECT" >/dev/null
gcloud builds submit --config=infra/cloudbuild-orchestrator.yaml . --quiet
gcloud run deploy atlas-orchestrator --image="${IMAGE_REPO}/atlas-orchestrator:latest" --region="$REGION" \
  --no-traffic --tag=finance --update-env-vars="^:^ATLAS_PACKS_ENABLED=public,finance" --quiet
gcloud run services describe atlas-orchestrator --region="$REGION" --format="value(status.traffic)" | tr ';' '\n' | grep -i finance || true
