-- Atlas: ard_catalog provisioning.
--
-- Run once (idempotent) in Cloud Shell, project atlas-ard-okf, after the
-- APIs-enabled batch. The crawler (backend/crawler/main.py) also creates
-- these on first run if they don't exist yet, so this file exists mainly
-- for reproducibility / disaster recovery, not because it's load-bearing.

CREATE SCHEMA IF NOT EXISTS `atlas-ard-okf.ard_catalog`
  OPTIONS (location = 'US');

CREATE TABLE IF NOT EXISTS `atlas-ard-okf.ard_catalog.embeddings` (
  doc_id STRING NOT NULL OPTIONS (description = 'e.g. bq.bigquery-public-data.covid19_open_data.covid19_open_data'),
  embedding ARRAY<FLOAT64> NOT NULL OPTIONS (description = 'text-embedding-005 output, 768-dim'),
  metadata JSON NOT NULL OPTIONS (description = 'title/description/trust/type/source, see backend/crawler/main.py'),
  updated_at TIMESTAMP NOT NULL
);

-- A VECTOR INDEX turns VECTOR_SEARCH from a brute-force scan into an
-- approximate-nearest-neighbor lookup. Skippable while the catalog is small
-- (a few thousand rows from the curated target list in backend/crawler/targets.py
-- brute-forces in well under a second) — add it once the crawl list grows
-- enough that discovery latency starts eating into the 60s query budget.
-- CREATE VECTOR INDEX IF NOT EXISTS embeddings_ivf
--   ON `atlas-ard-okf.ard_catalog.embeddings`(embedding)
--   OPTIONS (index_type = 'IVF', distance_type = 'COSINE');
