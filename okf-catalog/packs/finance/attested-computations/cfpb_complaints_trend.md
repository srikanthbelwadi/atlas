---
id: ac.cfpb_complaints_trend
type: AttestedComputation
pack: finance
title: Complaint volume trend by product, issue and company
description: >
  Number of CFPB complaints per month, quarter or year, optionally filtered
  to one product and/or one company, with the share that were answered on
  time and the share closed with relief. The board-pack "complaint trend"
  chart, computed one reviewed way. Use for "how did complaints about X
  change", "which products grew most", "complaints for company Y by quarter".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [cfpb, complaints, trend, product, company, quarterly, conduct, finance]
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: cfpb_complaints
  table: complaint_database
sources:
  - kind: bigquery
    project: bigquery-public-data
    dataset: cfpb_complaints
    table: complaint_database
  - kind: bigquery
    project: atlas-ard-okf
    dataset: finance_pack
    table: entity_xref
cost_profile:
  expected_bytes: 2500000000
  cap_bytes: 21474836480
citation_template: "CFPB Consumer Complaint Database, complaints by date_received; timely = timely_response, relief = company_response_to_consumer containing 'relief'."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: date_from
        type: DATE
        required: true
        description: Start of the window (inclusive), ISO date, e.g. "2021-01-01". If the question says "since 2021" use "2021-01-01".
      - name: date_to
        type: DATE
        required: true
        description: End of the window (inclusive), ISO date. If the question names only a start, use "2023-03-31".
      - name: grain
        type: STRING
        required: false
        default: quarter
        description: One of month, quarter, year. Default quarter.
      - name: product
        type: STRING
        required: false
        description: A CFPB product name to filter on, matched case-insensitively as a substring (e.g. "mortgage", "credit card", "debt collection", "credit reporting"). Omit to include all products.
      - name: company
        type: STRING
        required: false
        description: A bank or company named in the question, as written (e.g. "Wells Fargo"); resolved through the entity crosswalk. Omit to include all companies.
    sql: |
      WITH xref AS (
        SELECT cfpb_company_name FROM `atlas-ard-okf.finance_pack.entity_xref`
        WHERE @company IS NOT NULL AND (
          LOWER(display_name) = LOWER(@company)
          OR LOWER(ticker) = LOWER(@company)
          OR EXISTS (SELECT 1 FROM UNNEST(aliases) a WHERE LOWER(a) = LOWER(@company))
        )
      ),
      base AS (
        SELECT
          CASE @grain
            WHEN 'month' THEN DATE_TRUNC(date_received, MONTH)
            WHEN 'year'  THEN DATE_TRUNC(date_received, YEAR)
            ELSE DATE_TRUNC(date_received, QUARTER)
          END AS period,
          product,
          timely_response,
          LOWER(company_response_to_consumer) LIKE '%relief%' AS with_relief
        FROM `bigquery-public-data.cfpb_complaints.complaint_database`
        WHERE date_received BETWEEN @date_from AND @date_to
          AND (@product IS NULL OR LOWER(product) LIKE CONCAT('%', LOWER(@product), '%'))
          AND (@company IS NULL OR company_name IN (SELECT cfpb_company_name FROM xref))
      )
      SELECT
        period,
        COUNT(*) AS complaints,
        ROUND(100 * COUNTIF(timely_response) / COUNT(*), 1) AS timely_pct,
        ROUND(100 * COUNTIF(with_relief) / COUNT(*), 1) AS relief_pct
      FROM base
      GROUP BY period
      ORDER BY period
---

## Why this is a template

"Complaint trend" is the most common question a complaints team asks and
the easiest to compute inconsistently: which date (received vs sent to
company), what counts as "upheld", whether the grain is calendar or fiscal.
This template fixes all three (`date_received`, relief = any
`company_response_to_consumer` containing "relief", calendar periods), so
the ad-hoc question and the board pack agree.

## Parameters the planner extracts

Only the window, the grain and optional product/company filters. Company
names go through the reviewed crosswalk (`finance_pack.entity_xref`) —
an unknown company yields zero rows, which the pipeline reports honestly.

## Cost

Unpartitioned table; a full-window scan of the needed columns is ~2–3 GB.
