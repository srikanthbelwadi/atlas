-- Atlas finance pack: CIK half of the crosswalk check, kept separate because the
-- SEC `submission` table's issuer-id column name is confirmed from the crawl
-- (the first run showed it is not `cik`). Adjust the column below to match
-- `bq show --schema bigquery-public-data:sec_quarterly_financials.submission`.
-- 3. CIKs in the seed with no 10-K submission in the SEC data set.
SELECT 'cik_missing', x.display_name, CAST(x.cik AS STRING), NULL
FROM `atlas-ard-okf.finance_pack.entity_xref` x
LEFT JOIN (SELECT DISTINCT cik FROM `bigquery-public-data.sec_quarterly_financials.submission` WHERE form = '10-K') s
  ON s.cik = x.cik
WHERE x.cik IS NOT NULL AND s.cik IS NULL;
