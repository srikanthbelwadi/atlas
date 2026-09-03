---
id: bq.bigquery-public-data.cfpb_complaints.complaint_database#finance
type: Table
pack: finance
title: CFPB consumer complaint database
description: >
  BigQuery table `bigquery-public-data.cfpb_complaints.complaint_database`.
  One row per complaint sent by the CFPB to a financial company (banks, card
  issuers, servicers, debt collectors, credit bureaus), 2011 to present, with
  the product/issue taxonomy, channel, company response, timeliness, dispute
  flag and — where the consumer consented — the free-text narrative. In the
  finance pack this stands in for a bank's complaint case-management system.
  Columns:
    - date_received (DATE)
    - product (STRING)
    - subproduct (STRING)
    - issue (STRING)
    - subissue (STRING)
    - consumer_complaint_narrative (STRING)
    - company_public_response (STRING)
    - company_name (STRING)
    - state (STRING)
    - zip_code (STRING)
    - tags (STRING)
    - consumer_consent_provided (STRING)
    - submitted_via (STRING)
    - date_sent_to_company (DATE)
    - company_response_to_consumer (STRING)
    - timely_response (BOOLEAN)
    - consumer_disputed (BOOLEAN)
    - complaint_id (STRING)
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [cfpb, complaints, conduct, consumer-duty, udaap, narratives, banks, finance]
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: cfpb_complaints
  table: complaint_database
  partitioning: none
  refresh: daily (Google public-datasets-pipelines)
  stands_in_for: complaint case-management system (Salesforce Service Cloud, Pega, in-house)
---

## What's in this table

Roughly ten million complaints (the CFPB received about 6.6 million in 2025
alone). About 3.8 million rows carry `consumer_complaint_narrative`, only
where `consumer_consent_provided = 'Consent provided'`.

Key semantics:

- `company_response_to_consumer` values: `Closed with explanation`,
  `Closed with monetary relief`, `Closed with non-monetary relief`,
  `Closed`, `Closed without relief`, `Closed with relief`, `In progress`,
  `Untimely response`. "Relief" (an upheld complaint, in Consumer Duty
  terms) is any value containing `relief`.
- `timely_response` is TRUE when the company responded within 15 days.
- `consumer_disputed` is only populated for complaints before mid-2017; do
  not use it for recent trends.
- `tags` carries `Older American`, `Servicemember`, or both — the closest
  public proxy for a vulnerable-customer flag.
- `company_name` is the CFPB's registered name for the respondent, e.g.
  `WELLS FARGO & COMPANY`, and differs from the FDIC institution name.
  Resolve institutions through the finance pack's entity crosswalk
  (`ac.entity_resolve`), never by free-text matching in ad-hoc SQL.

## Notes for query planning

- Always filter on `date_received`; the table is not partitioned, so a
  full scan is a few GB — inside the template cap, outside a careless
  ad-hoc `SELECT *`.
- Never select `consumer_complaint_narrative` in ad-hoc SQL. Narrative
  questions route to `ac.cfpb_narrative_themes`, which samples under a hard
  row limit and verifies every quote.
- On 14 August 2026 the CFPB announced it would stop publishing new
  complaint narratives. Existing narratives remain; treat narrative
  coverage after mid-2026 as thin and say so.
