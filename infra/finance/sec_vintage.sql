-- How current is the SEC financial-statement mirror? (pins the use-case B years)
SELECT MAX(fiscal_year) AS max_fiscal_year, MAX(date_filed) AS max_date_filed, COUNT(*) AS filings,
       COUNTIF(form = '10-K') AS ten_ks
FROM `bigquery-public-data.sec_quarterly_financials.submission`;
SELECT fiscal_year, COUNTIF(form = '10-K') AS ten_ks
FROM `bigquery-public-data.sec_quarterly_financials.submission` GROUP BY fiscal_year ORDER BY fiscal_year DESC LIMIT 8;
-- and JPMorgan specifically (cik 19617), to see which fiscal years the reconcile question can use
SELECT fiscal_year, form, date_filed, submission_number FROM `bigquery-public-data.sec_quarterly_financials.submission`
WHERE central_index_key = 19617 AND form IN ('10-K','10-K/A') ORDER BY fiscal_year DESC LIMIT 6;
