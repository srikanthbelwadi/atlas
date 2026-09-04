#!/usr/bin/env bash
# Atlas finance pack, use case D — load the PRIVATE internal risk mart.
#
#   scripts/finance_private_load.sh [DATA_DIR] 2>&1 | tee ~/Documents/ARD_UKF/logs/finance_private_load.log
#
# DATA_DIR (default ~/Documents/ARD_UKF/data/finance_demo) must contain:
#   application_train.csv  bureau.csv  installments_payments.csv  paysim.csv
# Either the Kaggle originals (Home Credit Default Risk: the first three;
# PaySim: rename PS_2017…_log.csv to paysim.csv) or the synthetic set from
#   python3 scripts/finance_private_synth.py --out "$DATA_DIR"
# If the directory is missing, the synthetic set is generated first.
#
# Steps: (1) copy the files to a private GCS bucket in the project,
# (2) bq load each into finance_demo_raw (schema autodetected),
# (3) build the four curated finance_demo tables (infra/finance/private_setup.sql),
# (4) print row counts and the dataset's IAM bindings (there must be no
#     allUsers / allAuthenticatedUsers entry).
set -euo pipefail
PROJECT=${PROJECT:-atlas-ard-okf}
DATA_DIR=${1:-$HOME/Documents/ARD_UKF/data/finance_demo}
BUCKET="gs://${PROJECT}-finance-demo"
gcloud config set project "$PROJECT" >/dev/null

if [ ! -f "$DATA_DIR/application_train.csv" ]; then
  echo "== no data in $DATA_DIR — generating the synthetic set"
  python3 "$(dirname "$0")/finance_private_synth.py" --out "$DATA_DIR"
fi
for f in application_train.csv bureau.csv installments_payments.csv paysim.csv; do
  [ -f "$DATA_DIR/$f" ] || { echo "missing $DATA_DIR/$f"; exit 1; }
done
if head -1 "$DATA_DIR/application_train.csv" | tr ',' '\n' | wc -l | grep -q '^122$'; then
  echo "== source: Kaggle originals (application_train has 122 columns)"; SOURCE=kaggle
else
  echo "== source: synthetic (scripts/finance_private_synth.py)"; SOURCE=synthetic
fi

echo "== 1. private bucket + upload"
gsutil ls -b "$BUCKET" >/dev/null 2>&1 || gsutil mb -l US "$BUCKET"
gsutil -m cp "$DATA_DIR"/application_train.csv "$DATA_DIR"/bureau.csv "$DATA_DIR"/installments_payments.csv "$DATA_DIR"/paysim.csv "$BUCKET/"

echo "== 2. raw loads (finance_demo_raw, autodetect, replace)"
bq --location=US mk --dataset --description "Atlas finance pack (private): raw loads. Not catalogued." "${PROJECT}:finance_demo_raw" 2>/dev/null || true
for t in application_train bureau installments_payments paysim; do
  echo "-- $t"
  bq --location=US load --replace --source_format=CSV --autodetect --skip_leading_rows=1 \
    "${PROJECT}:finance_demo_raw.$t" "$BUCKET/$t.csv"
done

echo "== 3. curated tables (finance_demo)"
bq query --use_legacy_sql=false --format=pretty < "$(dirname "$0")/../infra/finance/private_setup.sql"
bq update --description "Atlas finance pack (private): curated internal risk mart, loaded $(date +%F) from ${SOURCE} data. Restricted; catalogued as visibility=private." "${PROJECT}:finance_demo" >/dev/null || true

echo "== 4. IAM on the private datasets (expect NO allUsers / allAuthenticatedUsers)"
for d in finance_demo finance_demo_raw; do
  echo "-- $d"
  bq show --format=prettyjson "${PROJECT}:$d" | python3 -c "
import json,sys
acl=json.load(sys.stdin).get('access',[])
for a in acl: print('  ', a.get('role'), a.get('userByEmail') or a.get('groupByEmail') or a.get('specialGroup') or a.get('iamMember') or a.get('view'))
bad=[a for a in acl if 'allUsers' in json.dumps(a) or 'allAuthenticatedUsers' in json.dumps(a)]
print('   PUBLIC BINDING FOUND — remove it' if bad else '   ok: private')"
done
echo "== done. Next: scripts/finance_phase_d.sh (crawl + redeploy + entitlement)"
