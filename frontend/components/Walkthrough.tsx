"use client";

import type { ReactNode } from "react";
import { Walkthrough as WalkthroughData, WalkthroughQuery, TokenUsage } from "@/lib/types";

// Renders the full "what did Atlas actually do" account that
// backend/orchestrator/pipeline.py attaches to both the "answer" and
// "error" terminal events: which sources were considered, the exact query
// (SQL + bound params) run against whichever one was used, any backtracks
// and why, real Gemini token counts per call, and total estimated cost.
// Shown regardless of whether the question ultimately succeeded — a failed
// run should be just as inspectable as a successful one.

function fmtBytes(n: number): string {
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

function fmtTokens(t: TokenUsage | undefined): string {
  if (!t) return "—";
  return `${t.prompt_tokens.toLocaleString()} in · ${t.output_tokens.toLocaleString()} out`;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div
        style={{
          fontSize: "0.72rem",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--ink-dim)",
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

function QueryCard({ q }: { q: WalkthroughQuery }) {
  const hasParams = q.params && Object.keys(q.params).length > 0;
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        background: "var(--surface-2)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: "0.8rem" }}>{q.source_id}</span>
        <span style={{ fontSize: "0.78rem", color: "var(--ink-dim)", fontVariantNumeric: "tabular-nums" }}>
          {q.row_count} row{q.row_count === 1 ? "" : "s"} · {fmtBytes(q.bytes_billed)} scanned
        </span>
      </div>
      {hasParams && (
        <div className="mono" style={{ fontSize: "0.76rem", color: "var(--ink-dim)" }}>
          {Object.entries(q.params).map(([k, v]) => `${k} = ${JSON.stringify(v)}`).join("  ·  ")}
        </div>
      )}
      {q.sql && (
        <details>
          <summary style={{ cursor: "pointer", fontSize: "0.78rem", color: "var(--accent)" }}>View SQL</summary>
          <pre
            className="mono"
            style={{
              margin: "8px 0 0",
              padding: "10px 12px",
              borderRadius: 6,
              background: "var(--surface)",
              fontSize: "0.76rem",
              overflowX: "auto",
              whiteSpace: "pre",
            }}
          >
            {q.sql}
          </pre>
        </details>
      )}
    </div>
  );
}

export default function Walkthrough({ walkthrough }: { walkthrough: WalkthroughData }) {
  const w = walkthrough;
  const cost = w.cost;

  return (
    <details
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "var(--surface)",
      }}
    >
      <summary
        style={{
          cursor: "pointer",
          padding: "16px 20px",
          fontSize: "0.85rem",
          fontWeight: 500,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <span>Walkthrough — what Atlas did</span>
        <span style={{ fontSize: "0.78rem", color: "var(--ink-dim)", fontWeight: 400, fontVariantNumeric: "tabular-nums" }}>
          {w.elapsed_s != null ? `${w.elapsed_s}s` : ""}
          {cost ? ` · $${cost.total_cost_usd.toFixed(4)} est.` : ""}
        </span>
      </summary>

      <div style={{ padding: "0 20px 20px", display: "flex", flexDirection: "column", gap: 18 }}>
        <Section title="Sources considered">
          {w.sources_considered.length === 0 ? (
            <div style={{ fontSize: "0.85rem", color: "var(--ink-dim)" }}>None matched this question.</div>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {w.sources_considered.map((s) => {
                const used = w.source_used?.id === s.source_id;
                return (
                  <span
                    key={s.source_id}
                    className="mono"
                    title={s.source_id}
                    style={{
                      fontSize: "0.74rem",
                      padding: "4px 10px",
                      borderRadius: 999,
                      background: used ? "var(--accent-soft)" : "var(--surface-2)",
                      border: used ? "1px solid var(--accent)" : "1px solid transparent",
                      color: used ? "var(--accent)" : "var(--ink-dim)",
                    }}
                  >
                    {s.title} · {s.score.toFixed(2)}
                    {used ? " · used" : ""}
                  </span>
                );
              })}
            </div>
          )}
        </Section>

        {w.backtracks.length > 0 && (
          <Section title="Backtracks">
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {w.backtracks.map((b, i) => (
                <div key={i} style={{ fontSize: "0.82rem", color: "var(--danger)" }}>
                  Gave up on <span className="mono">{b.from}</span> — {b.reason}
                </div>
              ))}
            </div>
          </Section>
        )}

        {w.queries_executed.length > 0 && (
          <Section title="Queries executed">
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {w.queries_executed.map((q, i) => (
                <QueryCard key={i} q={q} />
              ))}
            </div>
          </Section>
        )}

        <Section title="Token usage &amp; cost">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
            <div style={{ fontSize: "0.82rem" }}>
              <div style={{ color: "var(--ink-dim)", fontSize: "0.74rem" }}>Planner</div>
              <div className="mono" style={{ fontVariantNumeric: "tabular-nums" }}>
                {fmtTokens(w.token_usage.plan)}
              </div>
              {cost && <div style={{ color: "var(--ink-dim)", fontSize: "0.74rem" }}>${cost.plan_cost_usd.toFixed(4)}</div>}
            </div>
            <div style={{ fontSize: "0.82rem" }}>
              <div style={{ color: "var(--ink-dim)", fontSize: "0.74rem" }}>Synthesis</div>
              <div className="mono" style={{ fontVariantNumeric: "tabular-nums" }}>
                {fmtTokens(w.token_usage.synthesize)}
              </div>
              {cost && <div style={{ color: "var(--ink-dim)", fontSize: "0.74rem" }}>${cost.synth_cost_usd.toFixed(4)}</div>}
            </div>
            <div style={{ fontSize: "0.82rem" }}>
              <div style={{ color: "var(--ink-dim)", fontSize: "0.74rem" }}>BigQuery</div>
              <div className="mono" style={{ fontVariantNumeric: "tabular-nums" }}>
                {w.queries_executed.reduce((sum, q) => sum + q.bytes_billed, 0) > 0
                  ? fmtBytes(w.queries_executed.reduce((sum, q) => sum + q.bytes_billed, 0))
                  : "—"}
              </div>
              {cost && <div style={{ color: "var(--ink-dim)", fontSize: "0.74rem" }}>${cost.bq_cost_usd.toFixed(4)}</div>}
            </div>
            <div style={{ fontSize: "0.82rem" }}>
              <div style={{ color: "var(--ink-dim)", fontSize: "0.74rem" }}>Total (est.)</div>
              <div className="mono" style={{ fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
                {cost ? `$${cost.total_cost_usd.toFixed(4)}` : "—"}
              </div>
            </div>
          </div>
          {!cost && (
            <div style={{ fontSize: "0.76rem", color: "var(--ink-dim)" }}>
              No cost recorded — synthesis didn&rsquo;t complete for this question.
            </div>
          )}
        </Section>
      </div>
    </details>
  );
}
