-- Atlas finance pack: find the exact CFPB respondent strings and FDIC certs
-- for the seed rows xref_check.sql flagged. Run in BigQuery, paste results
-- into okf-catalog/packs/finance/entity_xref.csv, reload with
-- scripts/finance_phase0.sh step 1 (or the bq load + setup.sql pair).

-- A. CFPB coverage of the mirror: is it complete and current?
SELECT MIN(date_received) AS first_complaint, MAX(date_received) AS last_complaint, COUNT(*) AS complaints,
       COUNTIF(consumer_complaint_narrative IS NOT NULL) AS with_narrative
FROM `bigquery-public-data.cfpb_complaints.complaint_database`;

SELECT EXTRACT(YEAR FROM date_received) AS year, COUNT(*) AS complaints
FROM `bigquery-public-data.cfpb_complaints.complaint_database` GROUP BY year ORDER BY year;

-- B. Candidate CFPB strings for the unmatched banks (all years).
SELECT needle, company_name, COUNT(*) AS complaints
FROM `bigquery-public-data.cfpb_complaints.complaint_database`,
UNNEST(['FLAGSTAR','NEW YORK COMMUNITY','ASSOCIATED BANK','SYNOVUS','COMERICA','FROST','VALLEY NATIONAL',
        'ZIONS','KEYBANK','KEYCORP','WESTERN ALLIANCE','MORGAN STANLEY','SCHWAB','FIRST CITIZENS','FIRST-CITIZENS',
        'HUNTINGTON','M&T','REGIONS','FIFTH THIRD','CITIZENS','BMO','HSBC','WEBSTER','EAST WEST','POPULAR']) AS needle
WHERE UPPER(company_name) LIKE CONCAT('%', needle, '%')
GROUP BY needle, company_name ORDER BY needle, complaints DESC;

-- C. FDIC certs for the two that didn't resolve.
SELECT fdic_certificate_number, institution_name, city, state, active, total_deposits
FROM `bigquery-public-data.fdic_banks.institutions`
WHERE UPPER(institution_name) LIKE '%FLAGSTAR%' OR UPPER(institution_name) LIKE '%FROST%'
   OR UPPER(institution_name) LIKE '%NEW YORK COMMUNITY%'
ORDER BY active DESC, total_deposits DESC;
