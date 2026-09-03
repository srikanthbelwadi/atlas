---
id: ac.entity_resolve
type: AttestedComputation
pack: finance
title: Resolve a bank or company name to its CFPB, FDIC and SEC identities
description: >
  Looks a name or ticker up in the reviewed entity crosswalk and returns
  every matching institution with its CFPB respondent name, FDIC
  certificate number, SEC CIK and ticker. Use when a question asks "which
  bank is X", "what is X's FDIC cert / CIK", or when an institution name
  is ambiguous.
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [entity, crosswalk, cik, fdic-cert, ticker, identity, finance]
source:
  kind: bigquery
  project: atlas-ard-okf
  dataset: finance_pack
  table: entity_xref
cost_profile:
  expected_bytes: 100000
  cap_bytes: 21474836480
citation_template: "Atlas finance-pack entity crosswalk (okf-catalog/packs/finance/entity_xref.csv), human-reviewed."
computation:
  runtime:
    executor: bigquery
    attester: human-reviewed
    parameters:
      - name: name_or_ticker
        type: STRING
        required: true
        description: The institution name or ticker as written in the question.
    sql: |
      SELECT display_name, cfpb_company_name, fdic_cert, cik, ticker, ARRAY_TO_STRING(aliases, ', ') AS aliases, entity_kind
      FROM `atlas-ard-okf.finance_pack.entity_xref`
      WHERE LOWER(display_name) = LOWER(@name_or_ticker)
         OR LOWER(ticker) = LOWER(@name_or_ticker)
         OR EXISTS (SELECT 1 FROM UNNEST(aliases) a WHERE LOWER(a) = LOWER(@name_or_ticker))
         OR LOWER(display_name) LIKE CONCAT('%', LOWER(@name_or_ticker), '%')
      ORDER BY (LOWER(display_name) = LOWER(@name_or_ticker)) DESC, display_name
      LIMIT 10
---

## Why a crosswalk

The same bank is `WELLS FARGO & COMPANY` to the CFPB, `Wells Fargo Bank,
National Association` (cert 3511) to the FDIC and CIK 72971 / `WFC` to the
SEC. Letting a model free-text match across those produces the wrong bank
often enough that every cross-source template joins through this table
instead. More than one row back means the name is ambiguous and the
answer should say so rather than pick.
