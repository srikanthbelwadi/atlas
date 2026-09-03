-- Atlas finance pack: finance_pack dataset provisioning.
--
-- Run once (idempotent) in project atlas-ard-okf, then load the crosswalk
-- with scripts/finance_phase0.sh (bq load from okf-catalog/packs/finance/
-- entity_xref.csv into a staging table, then the MERGE below). The
-- finance-pack Attested Computations join through `entity_xref`; nothing in
-- the public pack references this dataset.

CREATE SCHEMA IF NOT EXISTS `atlas-ard-okf.finance_pack`
  OPTIONS (location = 'US', description = 'Atlas finance pack: reviewed entity crosswalk and pack-local helper tables');

CREATE TABLE IF NOT EXISTS `atlas-ard-okf.finance_pack.entity_xref` (
  display_name        STRING NOT NULL OPTIONS (description = 'Plain-language name used in answers'),
  entity_kind         STRING OPTIONS (description = 'bank | credit_union | credit_bureau | company'),
  cfpb_company_name   STRING OPTIONS (description = 'Exact company_name string in cfpb_complaints.complaint_database'),
  fdic_cert           STRING OPTIONS (description = 'FDIC certificate number as a string, matching fdic_banks.institutions.fdic_certificate_number'),
  cik                 INT64  OPTIONS (description = 'SEC Central Index Key'),
  ticker              STRING,
  aliases             ARRAY<STRING> OPTIONS (description = 'Lower-case alternate names a question might use'),
  seed_status         STRING OPTIONS (description = 'seed | verified — flipped by scripts/finance_xref_check.sql findings'),
  reviewed_on         DATE
);

-- Staging table shape for `bq load` of the CSV (aliases arrive pipe-separated).
CREATE TABLE IF NOT EXISTS `atlas-ard-okf.finance_pack._entity_xref_staging` (
  display_name STRING, entity_kind STRING, cfpb_company_name STRING, fdic_cert STRING,
  cik INT64, ticker STRING, aliases STRING, seed_status STRING
);

-- MERGE from staging (run after each bq load). Keyed on display_name.
MERGE `atlas-ard-okf.finance_pack.entity_xref` T
USING (
  SELECT display_name, entity_kind, NULLIF(cfpb_company_name, '') AS cfpb_company_name,
         NULLIF(fdic_cert, '') AS fdic_cert, cik, NULLIF(ticker, '') AS ticker,
         ARRAY(SELECT LOWER(TRIM(a)) FROM UNNEST(SPLIT(COALESCE(aliases, ''), '|')) a WHERE TRIM(a) != '') AS aliases,
         seed_status
  FROM `atlas-ard-okf.finance_pack._entity_xref_staging`
) S
ON T.display_name = S.display_name
WHEN MATCHED THEN UPDATE SET
  entity_kind = S.entity_kind, cfpb_company_name = S.cfpb_company_name, fdic_cert = S.fdic_cert,
  cik = S.cik, ticker = S.ticker, aliases = S.aliases, seed_status = S.seed_status, reviewed_on = CURRENT_DATE()
WHEN NOT MATCHED THEN INSERT (display_name, entity_kind, cfpb_company_name, fdic_cert, cik, ticker, aliases, seed_status, reviewed_on)
  VALUES (S.display_name, S.entity_kind, S.cfpb_company_name, S.fdic_cert, S.cik, S.ticker, S.aliases, S.seed_status, CURRENT_DATE());
