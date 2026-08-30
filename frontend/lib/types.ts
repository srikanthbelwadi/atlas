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
  | "error";

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

export type VisualizationKind = "table" | "bar" | "line" | "kpi_cards" | "map" | "infographic";

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
  sources_considered: WalkthroughSource[];
  source_used: WalkthroughSourceUsed | null;
  queries_executed: WalkthroughQuery[];
  backtracks: WalkthroughBacktrack[];
  token_usage: { plan?: TokenUsage; synthesize?: TokenUsage };
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
}
