# Third-Party Notices

This repository is a derivative work of [Resource Raiser](https://github.com/TechSoup/resource-raiser)
by TechSoup, used and extended under the terms of the Apache License,
Version 2.0. Resource Raiser's own discover → plan → fetch → check →
synthesize pipeline shape, and its approach of describing data sources
once via the Open Knowledge Format instead of writing source-specific query
code, are the foundation this project (Atlas) builds on — see
`IMPLEMENTATION.md` for exactly which parts were kept, and which were
replaced or added, for a natural-language front door to public BigQuery
datasets specifically.

Per Apache License 2.0 §4(b) and §4(d), this file carries the required
notice that this is a modified work, and retains Resource Raiser's original
copyright and license notice below.

---

Copyright TechSoup

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

---

## Modifications made in this derivative work (Atlas)

Summarized here per §4(b); see `IMPLEMENTATION.md` for full technical detail.

- Narrowed scope from Resource Raiser's ~20 general-purpose US authoritative
  sources (SEC, Census, Treasury, IRS Form 990, CDC, federal grants, plus a
  relational IRS 990 nonprofit grant graph) to public BigQuery datasets
  specifically, replacing its generic REST accessor as the primary path
  with a guarded BigQuery executor (byte cap + timeout + budget ceiling).
- Replaced the "validate whether a source can structurally answer the
  question" plan step's SQL/parameter drafting with Vertex AI Gemini calls
  running under strict JSON-schema-constrained output, deployed on Google
  Cloud (Cloud Run, Firebase App Hosting, Firestore) rather than
  Resource Raiser's original hosting.
- Added a live SSE query trace (discover/plan/guardrail/fetch/check/
  synthesize events) streamed to the frontend as the pipeline runs, plus a
  post-hoc "walkthrough" (sources considered, queries executed, backtracks,
  token cost) attached to every answer and every error.
- Added Firebase-Auth-gated access control with an admin approval queue and
  a pre-approved-email allowlist, a Firestore-backed per-user monthly
  budget guardrail, and a scheduled BigQuery-catalog crawler that builds
  the ARD/OKF-described discovery index used at query time.
- New Next.js frontend (ask bar, live trace panel, adaptive answer canvas,
  admin console) — none of Resource Raiser's original frontend code is
  reused.

## Third-party specifications referenced (not vendored code)

Atlas implements against two open specifications rather than embedding a
copy of either's reference implementation. Referenced here for attribution;
see `IMPLEMENTATION.md` for how this project maps its own catalog and trust
model onto them.

- **Agentic Resource Discovery (ARD)** — <https://agenticresourcediscovery.org/spec/>,
  spec repository <https://github.com/ards-project/ard-spec>.
- **Open Knowledge Format (OKF)** — <https://okf.md/spec/>, reference
  tooling <https://github.com/GoogleCloudPlatform/knowledge-catalog>.
