// Mirrors the SSE trace event vocabulary emitted by
// backend/orchestrator/pipeline.py — keep these in sync.
export type TraceEventName =
  | "guardrail.started"
  | "guardrail.done"
  | "guardrail.blocked"
  | "discover.started"
  | "discover.done"
  | "plan.started"
  | "plan.done"
  | "fetch.started"
  | "fetch.progress"
  | "fetch.done"
  | "check.started"
  | "check.done"
  | "check.backtrack"
  | "synthesize.started"
  | "synthesize.progress"
  | "synthesize.done"
  | "answer"
  | "error"
  // finance pack: fact-check skill (backend/orchestrator/skills/filing_fact_check.py)
  | "claim.extracted"
  | "claim.verdict";

// Catalog packs (backend/orchestrator/packs.py). Omitted = "public".
export type Pack = "public" | "finance";

export interface TraceEvent {
  event: TraceEventName;
  data: Record<string, unknown>;
  id: string; // client-assigned, for React keys
}

export type TrustLevel = "unverified" | "machine-confirmed" | "human-reviewed";

export interface Citation {
  source_id: string;
  title: string;
  trust: TrustLevel;
}

export type VisualizationKind = "table" | "bar" | "line" | "kpi_cards" | "map" | "infographic" | "verdict_table";

export interface Visualization {
  kind: VisualizationKind;
  data: string; // JSON-encoded, shape depends on `kind`
}

export interface Answer {
  question: string;
  narrative: string;
  citations: Citation[];
  visualization: Visualization;
  elapsed_s: number;
  walkthrough?: Walkthrough;
  // Present only when an Attested Computation answered (finance pack today;
  // see pipeline.build_receipt). The artefact a reviewer keeps.
  receipt?: Receipt;
  // Finance pack, use case D: set when a private source was involved —
  // either withheld (the user lacks the entitlement) or unlocked.
  access?: AccessInfo;
  // "not_entitled" when the answer is a refusal because the best-matching
  // source is restricted (backend/orchestrator/pipeline._withheld_answer).
  refused?: "not_entitled";
}

// A private source discovery matched but did not offer this user.
export interface WithheldSource {
  source_id: string;
  title: string;
  entitlement: string | null;
  score: number | null;
}

export interface AccessInfo {
  entitlements: string[];
  withheld: WithheldSource[];
}

export interface ReceiptQuery {
  step?: string | null;
  source_id: string;
  bytes_billed: number;
  row_count: number;
  params: Record<string, unknown>;
}

export interface Receipt {
  template_id: string;
  title: string;
  version: string | null;
  reviewer: string | null;
  reviewed_on: string | null;
  stale_after: string | null;
  stale: boolean;
  lifecycle: string;
  trust: TrustLevel;
  pack: string;
  executor: string | null;
  sources: Record<string, unknown>[];
  queries: ReceiptQuery[];
  bytes_billed: number;
  tokens: Record<string, TokenUsage>;
  cost: (WalkthroughCost & { generation_cost_usd?: number }) | null;
  citation_template: string | null;
  // use case D: private templates record how they were unlocked
  visibility?: "public" | "private";
  entitlement?: string | null;
  unlocked_by?: string | null;
  restricted_to?: string | null;
}

// One row of a fact-check verdict table (visualization kind "verdict_table").
export type Verdict = "verified" | "differs" | "not_verifiable" | "no_reported_value";

export interface VerdictRow {
  id: string;
  claim: string;
  entity: string;
  metric: string | null;
  fiscal_year: number | null;
  claimed: string | null;
  reported: number | null;
  source: string | null;
  accession: string | null;
  delta_pct: number | null;
  verdict: Verdict;
  sources_agree?: string | null;
  note?: string;
}

// GET /packs/{pack}/catalog
export interface CatalogEntry {
  id: string;
  title: string;
  description: string;
  type: "Table" | "AttestedComputation" | "Dataset";
  kind: string | null;
  executor: string | null;
  trust: TrustLevel;
  pack: string;
  reviewer: string | null;
  reviewed_on: string | null;
  stale_after: string | null;
  stale: boolean;
  lifecycle: string;
  version: string | null;
  parameters?: { name: string; type: string; required: boolean; description: string }[];
  sql?: string | null;
  body?: string;
  tags?: string[];
  sources?: Record<string, unknown>[];
  row_count?: number | null;
  size_gb?: number | null;
  large_table?: boolean | null;
  // use case D: private sources are listed for everyone, queryable by the entitled
  visibility?: "public" | "private";
  entitlement?: string | null;
  restricted_to?: string | null;
  accessible?: boolean;
}

export interface PackCatalog {
  pack: { id: string; title: string; tagline: string };
  entries: CatalogEntry[];
  counts: { attested: number; tables: number; private?: number };
  entitlements?: string[];
}

export interface EntitlementInfo {
  id: string;
  sources: string[];
}

// Mirrors the `walkthrough` dict backend/orchestrator/pipeline.py builds up
// across a run and attaches to BOTH the terminal "answer" event and the
// terminal "error" event's data — so a question that fails still gets a
// full account of what Atlas tried, not just a generic message.
export interface WalkthroughSource {
  source_id: string;
  title: string;
  trust: TrustLevel;
  score: number;
}

export interface WalkthroughQuery {
  step?: string | null;   // multi-step computations (finance pack) name each step
  source_id: string;
  sql: string | null;
  params: Record<string, unknown>;
  bytes_billed: number;
  row_count: number;
}

export interface WalkthroughBacktrack {
  from: string;
  reason: string;
}

export interface TokenUsage {
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

// Matches guardrails.record_usage()'s return dict exactly.
export interface WalkthroughCost {
  bq_cost_usd: number;
  plan_cost_usd: number;
  synth_cost_usd: number;
  total_cost_usd: number;
  plan_tokens: TokenUsage;
  synth_tokens: TokenUsage;
}

export interface WalkthroughSourceUsed {
  id: string;
  title: string;
  trust: TrustLevel;
}

export interface Walkthrough {
  question: string;
  pack?: Pack;
  sources_considered: WalkthroughSource[];
  source_used: WalkthroughSourceUsed | null;
  queries_executed: WalkthroughQuery[];
  backtracks: WalkthroughBacktrack[];
  access?: AccessInfo;
  token_usage: { plan?: TokenUsage; synthesize?: TokenUsage; theme?: TokenUsage; claims?: TokenUsage };
  cost: WalkthroughCost | null;
  elapsed_s: number | null;
}

export type UserStatus = "pending" | "approved" | "rejected";

export interface AdminUser {
  id: string;
  uid: string;
  email: string;
  display_name?: string;
  status: UserStatus;
  created_at?: string;
  entitlements?: string[];
}
