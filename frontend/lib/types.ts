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
