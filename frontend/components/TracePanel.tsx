"use client";

import { TraceEvent } from "@/lib/types";

const STAGES: { key: string; label: string }[] = [
  { key: "guardrail", label: "Budget check" },
  { key: "discover", label: "Discovering sources" },
  { key: "plan", label: "Planning the query" },
  { key: "fetch", label: "Fetching data" },
  { key: "check", label: "Checking the evidence" },
  { key: "synthesize", label: "Composing the answer" },
];

type Status = "pending" | "active" | "done" | "blocked";

function statusFor(stage: string, events: TraceEvent[]): Status {
  const forStage = events.filter((e) => e.event.startsWith(`${stage}.`));
  if (forStage.some((e) => e.event.endsWith(".blocked"))) return "blocked";
  if (forStage.some((e) => e.event.endsWith(".done"))) return "done";
  if (forStage.length > 0) return "active";
  return "pending";
}

function noteFor(stage: string, events: TraceEvent[]): string | null {
  const forStage = events.filter((e) => e.event.startsWith(`${stage}.`));
  const last = forStage[forStage.length - 1];
  if (!last) return null;

  switch (last.event) {
    case "discover.done": {
      const candidates = (last.data.candidates as any[]) || [];
      return candidates.length
        ? `${candidates.length} candidate source${candidates.length === 1 ? "" : "s"} — best match: ${candidates[0]?.title}`
        : "No matching sources found";
    }
    case "plan.done":
      return `Question shape: ${last.data.shape} · routed to ${last.data.source_id}`;
    case "guardrail.done": {
      const spent = Number(last.data.spent_usd ?? last.data.query_cost_usd ?? 0);
      return `Month-to-date spend: $${spent.toFixed(2)}`;
    }
    case "guardrail.blocked":
      return String(last.data.message || "Blocked by a budget guardrail");
    case "fetch.done":
      return `${last.data.rows} row${last.data.rows === 1 ? "" : "s"} · ${((last.data.bytes_billed as number) / 1024 ** 2).toFixed(1)} MB scanned`;
    case "fetch.progress":
      // Emitted by pipeline.py when a fetch attempt is blocked, times out, or
      // throws for any other reason (e.g. a planner-picked template missing
      // a required parameter) — previously silently dropped by the
      // `default: return null` case below, so a backtrack looked like
      // nothing had happened until the next stage's event arrived.
      return String(last.data.note || "Fetch attempt didn't complete");
    case "check.done":
      return last.data.ok ? `${last.data.row_count} rows look usable` : `Rejected: ${last.data.reason}`;
    case "check.backtrack":
      return `Backtracking — trying another source (${last.data.reason})`;
    case "synthesize.done":
      return `Done in ${last.data.elapsed_s}s`;
    default:
      return null;
  }
}

const DOT_COLOR: Record<Status, string> = {
  pending: "var(--border)",
  active: "var(--accent)",
  done: "var(--accent-2)",
  blocked: "var(--danger)",
};

export default function TracePanel({ events }: { events: TraceEvent[] }) {
  if (events.length === 0) return null;

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "18px 20px",
        background: "var(--surface)",
      }}
    >
      <div style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--ink-dim)", marginBottom: 14 }}>
        Life of this query
      </div>
      <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 14 }}>
        {STAGES.map(({ key, label }) => {
          const status = statusFor(key, events);
          const note = noteFor(key, events);
          if (status === "pending") return null;
          return (
            <li key={key} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
              <span
                style={{
                  marginTop: 4,
                  width: 9,
                  height: 9,
                  borderRadius: "50%",
                  flexShrink: 0,
                  background: DOT_COLOR[status],
                  boxShadow: status === "active" ? `0 0 0 4px ${DOT_COLOR.active}22` : "none",
                }}
              />
              <div>
                <div style={{ fontSize: "0.92rem", fontWeight: 500 }}>
                  {label}
                  {status === "active" && <span className="mono" style={{ color: "var(--ink-dim)", marginLeft: 8, fontSize: "0.8rem" }}>running…</span>}
                </div>
                {note && (
                  <div style={{ fontSize: "0.82rem", color: status === "blocked" ? "var(--danger)" : "var(--ink-dim)", marginTop: 2 }}>
                    {note}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
