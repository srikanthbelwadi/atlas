---
id: ac.cfpb_timely_response_rate
type: AttestedComputation
pack: finance
title: Timely-response and relief rates for a bank versus its deposit-size peers
description: >
  Quarterly share of CFPB complaints a named bank answered on time and
  closed with relief, side by side with the same rates for the N largest
  FDIC-insured banks by deposits (the peer set), optionally for one product.
  Use for "how does bank X compare to the top-10 banks on timely responses",
  "X's uphold rate on mortgages vs peers".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [cfpb, fdic, peer, timely-response, relief, uphold, bank, conduct, finance]
sources:
  - kind: bigquery
    project: bigquery-public-data
    dataset: cfpb_complaints
    table: complaint_database
  - kind: bigquery
    project: bigquery-public-data
    dataset: fdic_banks
    table: institutions
  - kind: bigquery
    project: atlas-ard-okf
    dataset: finance_pack
    table: entity_xref
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: cfpb_complaints
  table: complaint_database
cost_profile:
  expected_bytes: 2500000000
  cap_bytes: 21474836480
citation_template: "CFPB complaints joined to FDIC institutions through the Atlas entity crosswalk; peer set = top N active FDIC banks by total deposits; timely = timely_response, relief = response containing 'relief'."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: company
        type: STRING
        required: true
        description: The bank named in the question, as written (name or ticker), e.g. "Wells Fargo".
      - name: peer_n
        type: INT64
        required: false
        default: 10
        description: Size of the peer set (largest banks by deposits). Default 10.
      - name: product
        type: STRING
        required: false
        description: Optional CFPB product substring filter, e.g. "mortgage". Omit for all products.
      - name: date_from
        type: DATE
        required: false
        default: "2023-01-01"
        description: Start of the window (inclusive). Default 2023-01-01.
      - name: date_to
        type: DATE
        required: false
        default: "2026-08-31"
        description: End of the window (inclusive). Default 2026-08-31.
    sql: |
      WITH xref AS (
        SELECT display_name, cfpb_company_name, fdic_cert
        FROM `atlas-ard-okf.finance_pack.entity_xref`
        WHERE fdic_cert IS NOT NULL
      ),
      target AS (
        SELECT display_name, cfpb_company_name FROM `atlas-ard-okf.finance_pack.entity_xref`
        WHERE LOWER(display_name) = LOWER(@company)
           OR LOWER(ticker) = LOWER(@company)
           OR EXISTS (SELECT 1 FROM UNNEST(aliases) a WHERE LOWER(a) = LOWER(@company))
      ),
      peers AS (
        SELECT x.display_name, x.cfpb_company_name
        FROM `bigquery-public-data.fdic_banks.institutions` i
        JOIN xref x ON x.fdic_cert = i.fdic_certificate_number
        WHERE i.active
        QUALIFY ROW_NUMBER() OVER (ORDER BY i.total_deposits DESC) <= @peer_n
      ),
      complaints AS (
        SELECT
          DATE_TRUNC(date_received, QUARTER) AS quarter,
          company_name,
          timely_response,
          LOWER(company_response_to_consumer) LIKE '%relief%' AS with_relief
        FROM `bigquery-public-data.cfpb_complaints.complaint_database`
        WHERE date_received BETWEEN @date_from AND @date_to
          AND (@product IS NULL OR LOWER(product) LIKE CONCAT('%', LOWER(@product), '%'))
      )
      SELECT quarter, cohort, complaints, timely_pct, relief_pct FROM (
        SELECT c.quarter, t.display_name AS cohort, COUNT(*) AS complaints,
               ROUND(100 * COUNTIF(c.timely_response) / COUNT(*), 1) AS timely_pct,
               ROUND(100 * COUNTIF(c.with_relief) / COUNT(*), 1) AS relief_pct
        FROM complaints c JOIN target t ON c.company_name = t.cfpb_company_name
        GROUP BY c.quarter, t.display_name
        UNION ALL
        SELECT c.quarter, CONCAT('Top ', CAST(@peer_n AS STRING), ' banks by deposits') AS cohort, COUNT(*) AS complaints,
               ROUND(100 * COUNTIF(c.timely_response) / COUNT(*), 1) AS timely_pct,
               ROUND(100 * COUNTIF(c.with_relief) / COUNT(*), 1) AS relief_pct
        FROM complaints c JOIN peers p ON c.company_name = p.cfpb_company_name
        GROUP BY c.quarter
      )
      ORDER BY quarter, cohort
---

## Why this is a template

Peer comparison is where definitions drift most: who counts as a peer,
which name a bank files complaints under, what "upheld" means. This
template fixes the peer set (largest active FDIC banks by deposits, through
the reviewed crosswalk) and the rates (timely = `timely_response`, relief =
any response containing "relief") and reports the target bank and the peer
aggregate on the same quarterly grain.

## Known limits

The peer aggregate includes the target bank when it is itself a top-N bank
(by design: it is "the top N", not "the others"). The crosswalk seeds
about 50 banks; a bank outside it returns zero target rows and the answer
says so.
