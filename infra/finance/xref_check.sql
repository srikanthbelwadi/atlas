-- Atlas finance pack, phase 0.4: confirm the crosswalk seed against real data.
-- Run in BigQuery (project atlas-ard-okf) after setup.sql + the CSV load.
-- Each block prints the seed rows that DON'T match, so an empty result is
-- the goal. Fix okf-catalog/packs/finance/entity_xref.csv, reload, rerun.

-- 1. CFPB respondent names in the seed that never appear in the complaint database.
SELECT 'cfpb_name_missing' AS check_name, x.display_name, x.cfpb_company_name AS seed_value, NULL AS suggestion
FROM `atlas-ard-okf.finance_pack.entity_xref` x
LEFT JOIN (SELECT DISTINCT company_name FROM `bigquery-public-data.cfpb_complaints.complaint_database`
           WHERE date_received >= '2021-01-01') c
  ON c.company_name = x.cfpb_company_name
WHERE x.cfpb_company_name IS NOT NULL AND c.company_name IS NULL
UNION ALL
-- 2. FDIC certificate numbers in the seed that don't resolve to an active institution.
SELECT 'fdic_cert_missing', x.display_name, x.fdic_cert, NULL
FROM `atlas-ard-okf.finance_pack.entity_xref` x
LEFT JOIN `bigquery-public-data.fdic_banks.institutions` i
  ON i.fdic_certificate_number = x.fdic_cert AND i.active
WHERE x.fdic_cert IS NOT NULL AND i.fdic_certificate_number IS NULL;


-- Suggestions: the top CFPB respondents since 2021 (to find the exact strings)
SELECT company_name, COUNT(*) AS complaints
FROM `bigquery-public-data.cfpb_complaints.complaint_database`
WHERE date_received >= '2021-01-01'
GROUP BY company_name ORDER BY complaints DESC LIMIT 60;

-- Suggestions: the 40 largest active FDIC banks by deposits (to find cert numbers)
SELECT fdic_certificate_number, institution_name, state, total_deposits
FROM `bigquery-public-data.fdic_banks.institutions`
WHERE active ORDER BY total_deposits DESC LIMIT 40;
