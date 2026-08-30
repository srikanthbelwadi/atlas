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

// `finished` is true once the stream's terminal event ("answer" or "error")
// has arrived. Without it, a stage that was interrupted mid-attempt — e.g.
// "fetch" backtracked away from a bad candidate, or "check" never got its
// own .done because the whole run then failed on the *next* candidate —
// stays reported as "active" forever, since it only ever saw a non-".done"
// event for that stage. That rendered as a permanently spinning "running…"
// next to a request that had, in fact, already finished (successfully or
// not) — indistinguishable from the app actually being stuck, which is
// exactly the failure mode this session has spent most of its time hunting
// down elsewhere in the stack. Once the run is finished, any stage still
// sitting in "active" gets folded into "done" instead — it isn't literally
// running anymore, and the note text (e.g. "Backtracking — trying another
// source") still explains what actually happened there.
function statusFor(stage: string, events: TraceEvent[], finished: boolean): Status {
  const forStage = events.filter((e) => e.event.startsWith(`${stage}.`));
  if (forStage.some((e) => e.event.endsWith(".blocked"))) return "blocked";
  if (forStage.some((e) => e.event.endsWith(".done"))) return "done";
  if (forStage.length > 0) return finished ? "done" : "active";
  return "pending";
}

// One rendered line under a stage. `reasoning: true` marks a line that's
// the pipeline explaining WHY it did something (as opposed to just WHAT
// happened) — rendered visually distinct (italic) so the two read as
// different kinds of information at a glance.
interface Note {
  text: string;
  reasoning?: boolean;
}

// Returns every line worth showing for a stage, in the order the underlying
// events actually happened — not just the latest one. This matters most for
// "plan": a backtrack redrafts the plan against a new candidate (see
// pipeline.py), which fires its own plan.started/plan.done pair, so a
// backtracked question has TWO routing decisions to explain, each with its
// own reasoning — collapsing to only the last one would hide exactly the
// "why did it change its mind" step this is meant to surface. "synthesize"
// similarly now carries three sequential notes (what it's about to draft,
// what it chose, how long it took) instead of one terminal timestamp.
function notesFor(stage: string, events: TraceEvent[]): Note[] {
  const forStage = events.filter((e) => e.event.startsWith(`${stage}.`));
  if (forStage.length === 0) return [];

  if (stage === "plan") {
    const notes: Note[] = [];
    for (const e of forStage) {
      if (e.event !== "plan.done") continue;
      const retry = e.data.note ? "Retry — " : "";
      notes.push({ text: `${retry}Question shape: ${e.data.shape} · routed to ${e.data.source_id}` });
      const reasoning = String(e.data.reasoning || "").trim();
      if (reasoning) notes.push({ text: reasoning, reasoning: true });
    }
    return notes;
  }

  if (stage === "discover") {
    const last = forStage[forStage.length - 1];
    if (last.event !== "discover.done") return [];
    const candidates = (last.data.candidates as { title: string; score: number }[]) || [];
    if (!candidates.length) return [{ text: "No matching sources found" }];
    const top = candidates
      .slice(0, 3)
      .map((c) => `${c.title} (${(c.score ?? 0).toFixed(2)})`)
      .join(", ");
    return [{ text: `${candidates.length} candidate source${candidates.length === 1 ? "" : "s"} considered — top matches: ${top}` }];
  }

  if (stage === "synthesize") {
    const notes: Note[] = [];
    for (const e of forStage) {
      if (e.event === "synthesize.started" && e.data.note) {
        notes.push({ text: String(e.data.note), reasoning: true });
      } else if (e.event === "synthesize.progress" && e.data.note) {
        notes.push({ text: String(e.data.note) });
      } else if (e.event === "synthesize.done") {
        notes.push({ text: `Done in ${e.data.elapsed_s}s` });
      }
    }
    return notes;
  }

  // Every other stage (guardrail, fetch, check): unchanged single-line
  // behavior, keyed off the most recent event for that stage.
  const last = forStage[forStage.length - 1];
  switch (last.event) {
    case "guardrail.done": {
      const spent = Number(last.data.spent_usd ?? last.data.query_cost_usd ?? 0);
      return [{ text: `Month-to-date spend: $${spent.toFixed(2)}` }];
    }
    case "guardrail.blocked":
      return [{ text: String(last.data.message || "Blocked by a budget guardrail") }];
    case "fetch.done":
      return [{ text: `${last.data.rows} row${last.data.rows === 1 ? "" : "s"} · ${((last.data.bytes_billed as number) / 1024 ** 2).toFixed(1)} MB scanned` }];
    case "fetch.progress":
      // Emitted by pipeline.py when a fetch attempt is blocked, times out, or
      // throws for any other reason (e.g. a planner-picked template missing
      // a required parameter) — previously silently dropped, so a backtrack
      // looked like nothing had happened until the next stage's event arrived.
      return [{ text: String(last.data.note || "Fetch attempt didn't complete") }];
    case "check.done":
      return [{ text: last.data.ok ? `${last.data.row_count} rows look usable` : `Rejected: ${last.data.reason}` }];
    case "check.backtrack":
      return [{ text: `Backtracking — trying another source (${last.data.reason})` }];
    default:
      return [];
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
  const finished = events.some((e) => e.event === "answer" || e.event === "error");

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
          const status = statusFor(key, events, finished);
          const notes = notesFor(key, events);
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
                {notes.map((note, i) => (
                  <div
                    key={i}
                    style={{
                      fontSize: "0.82rem",
                      color: status === "blocked" ? "var(--danger)" : "var(--ink-dim)",
                      marginTop: i === 0 ? 2 : 4,
                      fontStyle: note.reasoning ? "italic" : "normal",
                    }}
                  >
                    {note.text}
                  </div>
                ))}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
