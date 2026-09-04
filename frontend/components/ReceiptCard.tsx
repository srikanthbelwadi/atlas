"use client";

import { Receipt } from "@/lib/types";
import TrustChip, { VisibilityChip } from "@/components/TrustChip";

function fmtBytes(b: number): string {
  if (!b) return "0 B";
  if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(2)} GB`;
  if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  return `${(b / 1024).toFixed(0)} KB`;
}

function fmtUsd(v: number | undefined | null): string {
  if (v === undefined || v === null) return "—";
  return `$${v.toFixed(4)}`;
}

/**
 * The receipt: what a model-risk reviewer keeps. Which reviewed template
 * answered, its version and reviewer, freshness, every query step with its
 * bound parameters and bytes, tokens by stage, and cost. Rendered only when
 * the backend attached one (attested-computation answers).
 */
export default function ReceiptCard({ receipt }: { receipt: Receipt }) {
  const tokens = Object.entries(receipt.tokens || {})
    .filter(([, u]) => u && (u.total_tokens || 0) > 0)
    .map(([stage, u]) => `${stage} ${u.prompt_tokens.toLocaleString()} in / ${u.output_tokens.toLocaleString()} out`)
    .join(" · ");

  return (
    <section className="receipt" aria-label="Receipt">
      <div className="receipt-head">
        <div>
          <div style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--ink-dim)", marginBottom: 4 }}>
            Receipt
          </div>
          <div className="receipt-title">{receipt.title}</div>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <TrustChip trust={receipt.trust} />
          <VisibilityChip visibility={receipt.visibility} entitlement={receipt.entitlement} accessible={receipt.visibility === "private" ? true : undefined} />
          {receipt.stale && <span className="trust-chip stale">needs re-review</span>}
          {receipt.lifecycle === "draft" && <span className="trust-chip draft">draft</span>}
        </div>
      </div>

      <dl className="receipt-grid">
        <dt>template</dt>
        <dd>
          {receipt.template_id}
          {receipt.version ? ` · v${receipt.version}` : ""}
        </dd>
        <dt>reviewed</dt>
        <dd>
          {receipt.reviewer || "—"}
          {receipt.reviewed_on ? ` on ${receipt.reviewed_on}` : ""}
          {receipt.stale_after ? ` · stale after ${receipt.stale_after}` : ""}
        </dd>
        <dt>executor</dt>
        <dd>{receipt.executor || "—"}</dd>
        {receipt.visibility === "private" && (
          <>
            <dt>access</dt>
            <dd>
              private source · unlocked by entitlement <span className="mono">{receipt.unlocked_by || receipt.entitlement || "—"}</span>
              {receipt.restricted_to ? <span style={{ color: "var(--ink-dim)" }}> · restricted to: {receipt.restricted_to}</span> : null}
            </dd>
          </>
        )}
        {receipt.queries.map((q, i) => (
          <QueryRow key={i} index={i} step={q.step} sourceId={q.source_id} bytes={q.bytes_billed} rows={q.row_count} params={q.params} />
        ))}
        <dt>scanned</dt>
        <dd>{fmtBytes(receipt.bytes_billed)}</dd>
        {tokens && (
          <>
            <dt>tokens</dt>
            <dd>{tokens}</dd>
          </>
        )}
        <dt>cost</dt>
        <dd>
          {fmtUsd(receipt.cost?.total_cost_usd)}
          {receipt.cost?.generation_cost_usd !== undefined ? ` (incl. generation ${fmtUsd(receipt.cost.generation_cost_usd)})` : ""}
        </dd>
      </dl>

      {receipt.citation_template && <div className="receipt-note">{receipt.citation_template}</div>}
    </section>
  );
}

function QueryRow({
  index,
  step,
  sourceId,
  bytes,
  rows,
  params,
}: {
  index: number;
  step?: string | null;
  sourceId: string;
  bytes: number;
  rows: number;
  params: Record<string, unknown>;
}) {
  const bound = Object.entries(params || {})
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
  return (
    <>
      <dt>{step ? `step ${index + 1} · ${step}` : "query"}</dt>
      <dd>
        {sourceId} · {rows} row{rows === 1 ? "" : "s"} · {fmtBytes(bytes)}
        {bound ? <span style={{ color: "var(--ink-dim)" }}> · {bound}</span> : null}
      </dd>
    </>
  );
}
