#!/usr/bin/env bash
# Atlas finance pack, use case D — after scripts/finance_private_load.sh:
#   1. rebuild the crawler and crawl the finance pack (adds finance_demo.* rows
#      with visibility=private to ard_catalog.embeddings)
#   2. build the orchestrator and redeploy the `finance` tagged revision
#   3. show who can read the private dataset (IAM), for the demo narrative
#   4. grant the test account the finance.internal entitlement
#   scripts/finance_phase_d.sh 2>&1 | tee ~/Documents/ARD_UKF/logs/finance_phase_d.log
set -euo pipefail
PROJECT=${PROJECT:-atlas-ard-okf}; REGION=${REGION:-us-central1}
IMAGE_REPO="us-central1-docker.pkg.dev/${PROJECT}/atlas-images"
TEST_EMAIL=${TEST_EMAIL:-atlas-test@atlasdata.world}
gcloud config set project "$PROJECT" >/dev/null

echo "== 1. crawler rebuild + finance crawl (private tables get visibility=private)"
gcloud builds submit --config=infra/cloudbuild-crawler.yaml . --quiet
gcloud run jobs deploy atlas-crawler --image="${IMAGE_REPO}/atlas-crawler:latest" --region="$REGION" \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT}" --max-retries=1 --task-timeout=20m --quiet
gcloud run jobs execute atlas-crawler --region="$REGION" --args="--pack,finance" --wait
bq query --use_legacy_sql=false --format=pretty "
SELECT doc_id, JSON_VALUE(metadata, '$.visibility') AS visibility, JSON_VALUE(metadata, '$.entitlement') AS entitlement,
       JSON_VALUE(metadata, '$.row_count') AS row_count
FROM \`${PROJECT}.ard_catalog.embeddings\` WHERE doc_id LIKE 'bq.${PROJECT}.finance_demo.%' ORDER BY doc_id"

echo "== 2. orchestrator build + redeploy of the 'finance' tagged revision"
gcloud builds submit --config=infra/cloudbuild-orchestrator.yaml . --quiet
gcloud run deploy atlas-orchestrator --image="${IMAGE_REPO}/atlas-orchestrator:latest" --region="$REGION" \
  --no-traffic --tag=finance --update-env-vars="^:^ATLAS_PACKS_ENABLED=public,finance" --quiet
gcloud run services describe atlas-orchestrator --region="$REGION" --format="value(status.traffic)" | tr ';' '\n' | grep -i finance || true

echo "== 3. who can read finance_demo (dataset ACL + project BigQuery roles)"
SA=$(gcloud run services describe atlas-orchestrator --region="$REGION" --format="value(spec.template.spec.serviceAccountName)")
echo "-- orchestrator runs as: ${SA:-<project default compute SA>}"
bq show --format=prettyjson "${PROJECT}:finance_demo" | python3 -c "
import json,sys
for a in json.load(sys.stdin).get('access',[]): print('  ', a.get('role'), a.get('userByEmail') or a.get('groupByEmail') or a.get('specialGroup') or a.get('iamMember'))"
echo "-- project-level BigQuery data roles:"
gcloud projects get-iam-policy "$PROJECT" --flatten="bindings[].members" --filter="bindings.role:bigquery" \
  --format="table(bindings.role, bindings.members)" || true

echo "== 4. entitlement: grant finance.internal to ${TEST_EMAIL}"
python3 "$(dirname "$0")/finance_entitle.py" "$TEST_EMAIL" --grant finance.internal
echo "== done. Golden runs:"
echo "  python scripts/golden_run.py --base \$BASE --token \"\$(scripts/firebase_token.sh)\" --set tests/golden/finance_d.yaml --report ~/Documents/ARD_UKF/logs/golden_finance_d.md"
echo "  python3 scripts/finance_entitle.py $TEST_EMAIL --revoke finance.internal"
echo "  python scripts/golden_run.py --base \$BASE --token \"\$(scripts/firebase_token.sh)\" --set tests/golden/finance_d_noaccess.yaml --report ~/Documents/ARD_UKF/logs/golden_finance_d_noaccess.md"
echo "  python3 scripts/finance_entitle.py $TEST_EMAIL --grant finance.internal"
