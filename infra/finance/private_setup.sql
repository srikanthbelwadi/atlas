-- Atlas finance pack, use case D: the PRIVATE internal risk mart.
--
-- Two datasets in our own project, neither of them public:
--   finance_demo_raw  — the files exactly as loaded (bq load, autodetect).
--                       Not crawled, not catalogued, never queried by a template.
--   finance_demo      — four curated tables built from raw by the CTAS
--                       statements below. This is what the crawler catalogues
--                       (with visibility=private) and what the ac.hc_* /
--                       ac.paysim_* templates read.
--
-- IAM: no allUsers / allAuthenticatedUsers binding is ever added. The
-- orchestrator's runtime service account reads through the project-level
-- BigQuery role it already has; see scripts/finance_phase_d.sh (step 3) for
-- the "another principal is denied" demonstration.
--
-- Run: bq query --use_legacy_sql=false < infra/finance/private_setup.sql
--      (after scripts/finance_private_load.sh has filled finance_demo_raw).
-- Idempotent — the curated tables are rebuilt in place.

CREATE SCHEMA IF NOT EXISTS `atlas-ard-okf.finance_demo_raw`
  OPTIONS (location = 'US', description = 'Atlas finance pack (private): raw loads for the internal risk mart. Not catalogued.');

CREATE SCHEMA IF NOT EXISTS `atlas-ard-okf.finance_demo`
  OPTIONS (location = 'US', description = 'Atlas finance pack (private): curated internal risk mart — retail credit book and payments ledger. Restricted; catalogued as visibility=private.');

-- ---------------------------------------------------------------------------
-- 1. loan_applications — one row per credit application (Home Credit
--    application_train shape). TARGET=1 means the client had payment
--    difficulties on that loan: the "default" every template means.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE `atlas-ard-okf.finance_demo.loan_applications`
OPTIONS (description = 'Retail credit applications with outcome. default_flag = 1 means payment difficulties (Home Credit TARGET). Income band, education, channel and bureau-inquiry counts as at application.')
AS
SELECT
  CAST(SK_ID_CURR AS INT64)                         AS application_id,
  CAST(TARGET AS INT64)                             AS default_flag,
  CAST(NAME_CONTRACT_TYPE AS STRING)                AS contract_type,          -- Cash loans | Revolving loans
  CAST(CODE_GENDER AS STRING)                       AS gender,
  CAST(AMT_INCOME_TOTAL AS FLOAT64)                 AS annual_income,
  CAST(AMT_CREDIT AS FLOAT64)                       AS credit_amount,
  CAST(AMT_ANNUITY AS FLOAT64)                      AS annuity_amount,
  CAST(NAME_INCOME_TYPE AS STRING)                  AS income_type,            -- Working | Commercial associate | Pensioner | State servant | ...
  CAST(NAME_EDUCATION_TYPE AS STRING)               AS education,
  CAST(NAME_FAMILY_STATUS AS STRING)                AS family_status,
  CAST(NAME_HOUSING_TYPE AS STRING)                 AS housing_type,
  CAST(OCCUPATION_TYPE AS STRING)                   AS occupation,
  CAST(REGION_RATING_CLIENT AS INT64)               AS region_rating,          -- 1 (best) .. 3
  CAST(-DAYS_BIRTH / 365.25 AS INT64)               AS age_years,
  CASE
    WHEN AMT_INCOME_TOTAL < 100000 THEN '1: <100k'
    WHEN AMT_INCOME_TOTAL < 150000 THEN '2: 100k-150k'
    WHEN AMT_INCOME_TOTAL < 225000 THEN '3: 150k-225k'
    WHEN AMT_INCOME_TOTAL < 350000 THEN '4: 225k-350k'
    ELSE '5: 350k+' END                             AS income_band,
  CAST(AMT_REQ_CREDIT_BUREAU_YEAR AS INT64)         AS bureau_inquiries_last_year,
  CAST(AMT_REQ_CREDIT_BUREAU_QRT AS INT64)          AS bureau_inquiries_last_quarter,
  CAST(EXT_SOURCE_2 AS FLOAT64)                     AS external_score_2,
  CAST(EXT_SOURCE_3 AS FLOAT64)                     AS external_score_3
FROM `atlas-ard-okf.finance_demo_raw.application_train`;

-- ---------------------------------------------------------------------------
-- 2. bureau_credits — prior credits reported by the credit bureau, one row
--    per prior credit per applicant (Home Credit bureau shape).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE `atlas-ard-okf.finance_demo.bureau_credits`
OPTIONS (description = 'Credit-bureau history: one row per prior credit reported for an applicant. days_since_credit_opened is relative to the application date (negative = before).')
AS
SELECT
  CAST(SK_ID_CURR AS INT64)              AS application_id,
  CAST(SK_ID_BUREAU AS INT64)            AS bureau_credit_id,
  CAST(CREDIT_ACTIVE AS STRING)          AS credit_status,          -- Active | Closed | Sold | Bad debt
  CAST(CREDIT_TYPE AS STRING)            AS credit_type,
  CAST(DAYS_CREDIT AS INT64)             AS days_since_credit_opened,
  CAST(CREDIT_DAY_OVERDUE AS INT64)      AS days_overdue,
  CAST(AMT_CREDIT_SUM AS FLOAT64)        AS credit_amount,
  CAST(AMT_CREDIT_SUM_DEBT AS FLOAT64)   AS current_debt,
  CAST(AMT_CREDIT_SUM_OVERDUE AS FLOAT64) AS amount_overdue,
  CAST(CNT_CREDIT_PROLONG AS INT64)      AS times_prolonged
FROM `atlas-ard-okf.finance_demo_raw.bureau`;

-- ---------------------------------------------------------------------------
-- 3. installment_payments — one row per instalment due on prior Home Credit
--    loans, with what was actually paid and when. Days are relative to the
--    current application (negative = before).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE `atlas-ard-okf.finance_demo.installment_payments`
OPTIONS (description = 'Instalment schedule vs actual payments on prior loans. days_late > 0 means paid after the due date; shortfall > 0 means paid less than due.')
AS
SELECT
  CAST(SK_ID_CURR AS INT64)                   AS application_id,
  CAST(SK_ID_PREV AS INT64)                   AS prior_loan_id,
  CAST(NUM_INSTALMENT_NUMBER AS INT64)        AS instalment_number,
  CAST(DAYS_INSTALMENT AS INT64)              AS days_due,
  CAST(DAYS_ENTRY_PAYMENT AS INT64)           AS days_paid,
  CAST(AMT_INSTALMENT AS FLOAT64)             AS amount_due,
  CAST(AMT_PAYMENT AS FLOAT64)                AS amount_paid,
  CAST(DAYS_ENTRY_PAYMENT AS INT64) - CAST(DAYS_INSTALMENT AS INT64) AS days_late,
  GREATEST(CAST(AMT_INSTALMENT AS FLOAT64) - COALESCE(CAST(AMT_PAYMENT AS FLOAT64), 0), 0) AS shortfall,
  CAST(FLOOR(-DAYS_INSTALMENT / 30.4375) AS INT64) AS months_before_application
FROM `atlas-ard-okf.finance_demo_raw.installments_payments`
WHERE DAYS_INSTALMENT IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 4. payment_transactions — a payments ledger (PaySim shape): one row per
--    transaction, hourly step, sender/receiver balances, fraud label.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE `atlas-ard-okf.finance_demo.payment_transactions`
OPTIONS (description = 'Payments ledger: one row per transaction. hour_step counts hours from the start of the extract (30 days); is_fraud is the confirmed-fraud label; is_flagged is the legacy rule (single transfer > 200k).')
AS
SELECT
  CAST(step AS INT64)                      AS hour_step,
  CAST(type AS STRING)                     AS txn_type,          -- PAYMENT | TRANSFER | CASH_OUT | CASH_IN | DEBIT
  CAST(amount AS FLOAT64)                  AS amount,
  CAST(nameOrig AS STRING)                 AS origin_account,
  CAST(oldbalanceOrg AS FLOAT64)           AS origin_balance_before,
  CAST(newbalanceOrig AS FLOAT64)          AS origin_balance_after,
  CAST(nameDest AS STRING)                 AS destination_account,
  CAST(oldbalanceDest AS FLOAT64)          AS destination_balance_before,
  CAST(newbalanceDest AS FLOAT64)          AS destination_balance_after,
  CAST(isFraud AS INT64)                   AS is_fraud,
  CAST(isFlaggedFraud AS INT64)            AS is_flagged
FROM `atlas-ard-okf.finance_demo_raw.paysim`;

-- Row counts, for the log and the catalog doc's "as loaded" line.
SELECT 'loan_applications' AS table_name, COUNT(*) AS row_count FROM `atlas-ard-okf.finance_demo.loan_applications`
UNION ALL SELECT 'bureau_credits', COUNT(*) FROM `atlas-ard-okf.finance_demo.bureau_credits`
UNION ALL SELECT 'installment_payments', COUNT(*) FROM `atlas-ard-okf.finance_demo.installment_payments`
UNION ALL SELECT 'payment_transactions', COUNT(*) FROM `atlas-ard-okf.finance_demo.payment_transactions`
ORDER BY 1;
