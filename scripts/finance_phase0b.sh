#!/usr/bin/env bash
# Atlas finance pack — phase 0, second pass (after the first run's findings):
#   1. print the real SEC submission/numbers schemas + how metadata is stored
#   2. rebuild the crawler (metadata now written as JSON objects) and re-crawl
#      the finance pack, then re-check the crosswalk
#   3. build the orchestrator and deploy the NO-TRAFFIC revision tagged
#      `finance` (fixed --update-env-vars syntax)
#   scripts/finance_phase0b.sh 2>&1 | tee ~/Documents/ARD_UKF/logs/finance_phase0b.log
set -euo pipefail
PROJECT=${PROJECT:-atlas-ard-okf}; REGION=${REGION:-us-central1}
IMAGE_REPO="us-central1-docker.pkg.dev/${PROJECT}/atlas-images"
gcloud config set project "$PROJECT" >/dev/null

echo "== 1. SEC schemas and metadata encoding"
for t in submission numbers; do
  echo "-- bigquery-public-data.sec_quarterly_financials.$t"
  bq show --schema --format=prettyjson "bigquery-public-data:sec_quarterly_financials.$t" \
    | python3 -c "import json,sys; print(', '.join(c['name']+' ('+c['type']+')' for c in json.load(sys.stdin)))"
done
echo "-- fdic_banks.institutions: first 20 columns"
bq show --schema --format=prettyjson "bigquery-public-data:fdic_banks.institutions" \
  | python3 -c "import json,sys; print(', '.join(c['name']+' ('+c['type']+')' for c in json.load(sys.stdin)[:20]))"
bq query --use_legacy_sql=false --format=pretty "
SELECT JSON_TYPE(metadata) AS metadata_type, COUNTIF(doc_id LIKE '%#finance') AS finance_rows, COUNT(*) AS row_count
FROM \`${PROJECT}.ard_catalog.embeddings\` GROUP BY 1"

echo "== 2. crawler rebuild + finance re-crawl"
gcloud builds submit --config=infra/cloudbuild-crawler.yaml . --quiet
gcloud run jobs deploy atlas-crawler --image="${IMAGE_REPO}/atlas-crawler:latest" --region="$REGION" \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT}" --max-retries=1 --task-timeout=20m --quiet
gcloud run jobs execute atlas-crawler --region="$REGION" --args="--pack,finance" --wait
bq query --use_legacy_sql=false --format=pretty "
SELECT JSON_TYPE(metadata) AS metadata_type, JSON_VALUE(metadata, '$.pack') AS pack, COUNT(*) AS row_count
FROM \`${PROJECT}.ard_catalog.embeddings\` GROUP BY 1, 2 ORDER BY 2"
echo "-- crosswalk check, CFPB + FDIC halves (empty = every seed row resolves):"
bq query --use_legacy_sql=false --format=pretty < infra/finance/xref_check.sql || true

echo "== 3. orchestrator build + no-traffic revision tagged 'finance'"
gcloud builds submit --config=infra/cloudbuild-orchestrator.yaml . --quiet
gcloud run deploy atlas-orchestrator --image="${IMAGE_REPO}/atlas-orchestrator:latest" --region="$REGION" \
  --no-traffic --tag=finance --update-env-vars="^:^ATLAS_PACKS_ENABLED=public,finance" --quiet
echo "-- tagged URL:"
gcloud run services describe atlas-orchestrator --region="$REGION" --format="value(status.traffic)" | tr ';' '\n' | grep -i finance || true
