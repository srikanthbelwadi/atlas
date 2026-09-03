#!/usr/bin/env bash
# Atlas finance pack — phase 0 on Google Cloud (project atlas-ard-okf).
#
# Everything in phases 0–2 that needs a real project, in order. Idempotent;
# safe to re-run. Run from the repo root with gcloud + bq authenticated:
#
#   scripts/finance_phase0.sh 2>&1 | tee /tmp/finance_phase0.log
#
# Steps:
#   1. finance_pack dataset + entity_xref (infra/finance/setup.sql, CSV load, MERGE)
#   2. crawler image rebuild + one `--pack finance` execution (resolves the
#      fdic_banks/fdic naming question and confirms the SEC table schema)
#   3. print what the crawl catalogued, and the crosswalk check results
#   4. build the orchestrator image and deploy it as a NO-TRAFFIC revision
#      tagged `finance`, with ATLAS_PACKS_ENABLED=public,finance — the
#      public URL keeps serving the previous revision until you promote.
set -euo pipefail

PROJECT=${PROJECT:-atlas-ard-okf}
REGION=${REGION:-us-central1}
IMAGE_REPO="us-central1-docker.pkg.dev/${PROJECT}/atlas-images"
gcloud config set project "$PROJECT" >/dev/null

echo "== 1. finance_pack dataset + entity crosswalk"
bq query --use_legacy_sql=false --project_id="$PROJECT" < infra/finance/setup.sql >/dev/null
bq load --project_id="$PROJECT" --source_format=CSV --skip_leading_rows=1 --replace \
  finance_pack._entity_xref_staging okf-catalog/packs/finance/entity_xref.csv \
  display_name:STRING,entity_kind:STRING,cfpb_company_name:STRING,fdic_cert:STRING,cik:INTEGER,ticker:STRING,aliases:STRING,seed_status:STRING
# Re-run the MERGE half of setup.sql now that staging is loaded.
bq query --use_legacy_sql=false --project_id="$PROJECT" < infra/finance/setup.sql >/dev/null
bq query --use_legacy_sql=false --format=prettyjson "SELECT COUNT(*) AS xref_rows, COUNTIF(fdic_cert IS NOT NULL) AS with_fdic, COUNTIF(cik IS NOT NULL) AS with_cik FROM \`${PROJECT}.finance_pack.entity_xref\`"

echo "== 2. crawler: rebuild image, run once for the finance pack"
gcloud builds submit --config=infra/cloudbuild-crawler.yaml . --quiet
gcloud run jobs deploy atlas-crawler \
  --image="${IMAGE_REPO}/atlas-crawler:latest" --region="$REGION" \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT}" --max-retries=1 --task-timeout=20m --quiet
gcloud run jobs execute atlas-crawler --region="$REGION" --args="--pack,finance" --wait
echo "-- crawler log (last 80 lines):"
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=atlas-crawler" --limit=80 --format="value(textPayload)" --freshness=30m | (tail -r 2>/dev/null || tac) || true

echo "== 3. what the finance crawl catalogued"
bq query --use_legacy_sql=false --format=pretty "
SELECT doc_id, JSON_TYPE(metadata) AS metadata_type
FROM \`${PROJECT}.ard_catalog.embeddings\`
WHERE doc_id LIKE '%#finance' ORDER BY doc_id"
echo "-- SEC numbers/submission columns as crawled (for ac.sec_fact_from_bq promotion):"
for t in submission numbers; do echo "-- schema: sec_quarterly_financials.$t"; bq show --schema --format=prettyjson "bigquery-public-data:sec_quarterly_financials.$t" | python3 -c "import json,sys; print(', '.join(c['name']+' ('+c['type']+')' for c in json.load(sys.stdin)))"; done
echo "-- crosswalk check (empty = every seed row resolves):"
bq query --use_legacy_sql=false --format=pretty < infra/finance/xref_check.sql || true

echo "== 4. orchestrator: build + deploy a no-traffic revision tagged 'finance'"
gcloud builds submit --config=infra/cloudbuild-orchestrator.yaml . --quiet
gcloud run deploy atlas-orchestrator \
  --image="${IMAGE_REPO}/atlas-orchestrator:latest" --region="$REGION" \
  --no-traffic --tag=finance \
  --update-env-vars="^:^ATLAS_PACKS_ENABLED=public,finance" --quiet
echo "-- tagged URL (use this for golden runs before promoting):"
gcloud run services describe atlas-orchestrator --region="$REGION" --format="value(status.traffic)" | tr ';' '\n' | grep -i finance || true
echo
echo "Next: scripts/golden_run.py --base <tagged URL> --set tests/golden/public_regression.yaml, then finance_a / finance_b."
echo "Promote with: gcloud run services update-traffic atlas-orchestrator --region=$REGION --to-latest"
