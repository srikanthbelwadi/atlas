---
id: ac.cfpb_narrative_themes
type: AttestedComputation
pack: finance
title: Themes in complaint narratives, with verified quotes
description: >
  What consumers are actually saying: a bounded random sample of consented
  free-text complaint narratives for one product (and optionally one issue)
  in a date window, themed into a handful of named themes with a share,
  a summary and verbatim quotes that Atlas verifies against the sample
  before showing. Use for "what are the main themes in complaints about X",
  "why are people complaining about Y", "representative complaints about Z".
trust: human-reviewed
reviewer: Bel
reviewed_on: 2026-09-03
stale_after: 2027-03-01
lifecycle: active
version: "1"
tags: [cfpb, narratives, themes, root-cause, natural-language, quotes, conduct, finance]
source:
  kind: bigquery
  project: bigquery-public-data
  dataset: cfpb_complaints
  table: complaint_database
cost_profile:
  expected_bytes: 6000000000
  cap_bytes: 21474836480
citation_template: "Random sample of consented CFPB complaint narratives (consumer_consent_provided = 'Consent provided'), themed by Atlas; every quote verified verbatim against the sampled narrative it cites."
computation:
  runtime:
    executor: bigquery_sample_llm
    attester: human-reviewed
    max_sample_n: 500
    max_themes: 6
    parameters:
      - name: product
        type: STRING
        required: true
        description: CFPB product substring, e.g. "credit reporting", "mortgage", "credit card", "debt collection".
      - name: issue
        type: STRING
        required: false
        description: Optional CFPB issue substring, e.g. "incorrect information", "trouble during payment process". Omit for all issues.
      - name: date_from
        type: DATE
        required: false
        default: "2023-01-01"
        description: Start of the window (inclusive). Default 2023-01-01.
      - name: date_to
        type: DATE
        required: false
        default: "2026-06-30"
        description: End of the window (inclusive). Default 2026-06-30 (public narratives stop being published after August 2026).
      - name: sample_n
        type: INT64
        required: false
        default: 300
        description: How many narratives to sample, at most 500. Default 300.
    sql: |
      SELECT complaint_id, date_received, product, subproduct, issue, company_name, state,
             consumer_complaint_narrative
      FROM `bigquery-public-data.cfpb_complaints.complaint_database`
      WHERE date_received BETWEEN @date_from AND @date_to
        AND consumer_consent_provided = 'Consent provided'
        AND consumer_complaint_narrative IS NOT NULL
        AND LENGTH(consumer_complaint_narrative) BETWEEN 200 AND 3000
        AND LOWER(product) LIKE CONCAT('%', LOWER(@product), '%')
        AND (@issue IS NULL OR LOWER(issue) LIKE CONCAT('%', LOWER(@issue), '%'))
      ORDER BY FARM_FINGERPRINT(complaint_id)
      LIMIT @sample_n
    prompt: |
      The narratives are consumer complaints submitted to the CFPB about the
      named product. Group them by the underlying problem the consumer is
      describing (not by the product name), e.g. "disputed item not
      corrected", "payment misapplied", "unable to reach a person". Prefer
      fewer, well-separated themes over many overlapping ones. Shares should
      sum to roughly 100. Do not include personal details (names, account
      numbers) in summaries; the source text already masks them as XXXX.
---

## Why this is a template, and why it runs in two steps

Free-text complaints are the richest signal a conduct team has and the
easiest place for an agent to run up a bill or invent a quote. This
template bounds both:

1. **Sample** — the SQL above runs through the normal guarded path (dry
   run, byte cap, timeout). The sample is deterministic for a given window
   (`FARM_FINGERPRINT` order) and capped at `max_sample_n = 500` rows on
   the server regardless of what a caller asks for.
2. **Theme** — the sampled rows are themed by the plan-tier model using
   the reviewed prompt above, never request-time instructions. The
   pipeline's check stage then verifies every quote is a verbatim excerpt
   of the narrative with that `complaint_id` and drops any that isn't; the
   trace reports how many survived, and the receipt carries the generation
   token cost as its own line.

## Limits

Themes describe a sample, not the population; the answer says the sample
size. Narrative coverage after mid-2026 is thin (CFPB stopped publishing
new narratives in August 2026), so windows default to end 2026-06-30.
