-- Atlas finance pack: CIK half of the crosswalk check, kept separate because the
-- SEC `submission` table's issuer-id column name is confirmed from the crawl
-- (confirmed 2026-09-03: `central_index_key`).
-- 3. CIKs in the seed with no 10-K submission in the SEC data set.
SELECT 'cik_missing', x.display_name, CAST(x.cik AS STRING), NULL
FROM `atlas-ard-okf.finance_pack.entity_xref` x
LEFT JOIN (SELECT DISTINCT central_index_key AS cik FROM `bigquery-public-data.sec_quarterly_financials.submission` WHERE form = '10-K') s
  ON s.cik = x.cik
WHERE x.cik IS NOT NULL AND s.cik IS NULL;
