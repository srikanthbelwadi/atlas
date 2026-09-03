"use client";

import { useState } from "react";
import { CatalogEntry } from "@/lib/types";
import TrustChip from "@/components/TrustChip";

type Filter = "all" | "AttestedComputation" | "Table";

function fmtSize(e: CatalogEntry): string {
  if (e.size_gb != null) return `${e.size_gb} GB`;
  if (e.row_count != null) return `${Number(e.row_count).toLocaleString()} rows`;
  return "—";
}

/**
 * /finance/catalog: what discovery can see for the pack. Rows expand to the
 * document body, parameters and the exact SQL text — the "what stands in
 * for what" handout, live.
 */
export default function CatalogTable({ entries }: { entries: CatalogEntry[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<string | null>(null);
  const shown = entries
    .filter((e) => filter === "all" || e.type === filter)
    .sort((a, b) => (a.type === b.type ? a.title.localeCompare(b.title) : a.type === "AttestedComputation" ? -1 : 1));

  return (
    <div>
      <div className="filter-row" role="group" aria-label="Filter">
        {(["all", "AttestedComputation", "Table"] as Filter[]).map((f) => (
          <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
            {f === "all" ? `All (${entries.length})` : f === "AttestedComputation" ? "Attested computations" : "Tables"}
          </button>
        ))}
      </div>
      <div style={{ overflowX: "auto", border: "1px solid var(--border)", borderRadius: 12, background: "var(--surface)" }}>
        <table className="catalog-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Kind</th>
              <th>Trust</th>
              <th>Reviewed</th>
              <th>Stale after</th>
              <th>Size</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((e) => (
              <Row key={e.id} entry={e} open={open === e.id} onToggle={() => setOpen(open === e.id ? null : e.id)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Row({ entry, open, onToggle }: { entry: CatalogEntry; open: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className="catalog-row" onClick={onToggle} aria-expanded={open}>
        <td>
          <div style={{ fontWeight: 500 }}>{entry.title}</div>
          <div className="mono" style={{ fontSize: "0.72rem", color: "var(--ink-dim)" }}>{entry.id}</div>
        </td>
        <td style={{ whiteSpace: "nowrap" }}>
          {entry.type === "AttestedComputation" ? "attested computation" : "table"}
          {entry.executor && entry.executor !== "bigquery" ? <div className="mono" style={{ fontSize: "0.72rem", color: "var(--ink-dim)" }}>{entry.executor}</div> : null}
        </td>
        <td>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <TrustChip trust={entry.trust} />
            {entry.stale && <span className="trust-chip stale">stale</span>}
            {entry.lifecycle === "draft" && <span className="trust-chip draft">draft</span>}
          </div>
        </td>
        <td style={{ whiteSpace: "nowrap" }}>
          {entry.reviewer ? `${entry.reviewer} · ${entry.reviewed_on}` : entry.type === "Table" ? "crawler" : "—"}
        </td>
        <td className="mono" style={{ whiteSpace: "nowrap" }}>{entry.stale_after || "—"}</td>
        <td className="mono" style={{ whiteSpace: "nowrap" }}>{fmtSize(entry)}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={6} style={{ padding: 0 }}>
            <div className="catalog-detail">
              <p style={{ margin: "0 0 10px", fontSize: "0.88rem", whiteSpace: "pre-wrap" }}>{entry.description}</p>
              {entry.parameters && entry.parameters.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div className="example-group-label">Parameters</div>
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: "0.84rem" }}>
                    {entry.parameters.map((p) => (
                      <li key={p.name}>
                        <span className="mono">{p.name}</span> ({p.type}
                        {p.required ? "" : ", optional"}) — {p.description}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {entry.sql && (
                <div>
                  <div className="example-group-label">SQL (this exact text runs; only parameter values are bound)</div>
                  <pre className="mono">{entry.sql}</pre>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
