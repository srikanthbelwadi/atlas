"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import type { GeoPayload } from "@/lib/types";
import { decimalsFor, formatValue } from "./ChoroplethMap";

// MapLibre touches `window` at import time, so the map itself is loaded
// client-side only; the table beneath it renders immediately.
const ChoroplethMap = dynamic(() => import("./ChoroplethMap"), {
  ssr: false,
  loading: () => (
    <div style={{ height: "min(60vh, 520px)", borderRadius: 10, border: "1px solid var(--border)", background: "var(--surface-2)", display: "grid", placeItems: "center", color: "var(--ink-dim)", fontSize: "0.85rem" }}>
      Loading map…
    </div>
  ),
});

const MAPS_ENABLED = process.env.NEXT_PUBLIC_ATLAS_MAPS_ENABLED !== "false";

interface Spec {
  value_field?: string;
  label_field?: string;
  unit?: string;
  title?: string;
}

/**
 * The `choropleth` visualization kind: a map of the answer's places
 * coloured by value, with the ranked rows beneath (the map is the reading,
 * the table is the evidence). `geo` is attached by the backend
 * (pipeline.finalize_map); when it is absent the rows still render as a
 * table, so a map answer degrades to something readable rather than to
 * nothing.
 */
export default function ChoroplethViz({ data, geo }: { data: string; geo?: GeoPayload }) {
  const spec = useMemo<Spec>(() => {
    try {
      const parsed = JSON.parse(data || "{}");
      return parsed && typeof parsed === "object" ? (parsed as Spec) : {};
    } catch {
      return {};
    }
  }, [data]);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const rows = useMemo(() => {
    const feats = geo?.features?.features ?? [];
    return feats
      .map((f) => f.properties)
      .filter((p) => typeof p.value === "number")
      .sort((a, b) => (b.value as number) - (a.value as number));
  }, [geo]);

  if (!geo || !rows.length) {
    return <div style={{ color: "var(--ink-dim)", fontSize: "0.88rem" }}>No mappable places in this answer.</div>;
  }
  const decimals = decimalsFor(rows.map((p) => p.value as number));
  // Date and source are per row; when every row agrees they belong in the
  // header ("May 2026 · www.bls.gov via Data Commons") rather than repeated.
  const dates = new Set(rows.map((p) => (p.date == null ? "" : String(p.date))));
  const sources = new Set(rows.map((p) => (p.source == null ? "" : String(p.source))));
  const oneDate = dates.size === 1 ? [...dates][0] : "";
  const oneSource = sources.size === 1 ? [...sources][0] : "";
  const subtitle = [oneDate, oneSource ? `${oneSource} via Data Commons` : "boundaries from Data Commons"].filter(Boolean).join(" · ")
    + (dates.size > 1 ? " · latest value per place" : "");
  const showDate = dates.size > 1;
  const showSource = sources.size > 1;

  const visible = showAll ? rows : rows.slice(0, 15);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {MAPS_ENABLED && <ChoroplethMap geo={geo} unit={spec.unit} title={spec.title} subtitle={subtitle} onHover={setHoverKey} highlightKey={hoverKey} />}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.86rem" }}>
          <thead>
            <tr>
              {["#", "Place", spec.title || spec.value_field || "Value", ...(showDate ? ["Date"] : []), ...(showSource ? ["Source"] : [])].map((h, i) => (
                <th key={h} style={{ textAlign: i === 2 ? "right" : "left", padding: "6px 10px", borderBottom: "2px solid var(--border)", color: "var(--ink-dim)", fontWeight: 500 }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((p, i) => (
              <tr
                key={p.key}
                onMouseEnter={() => setHoverKey(p.key)}
                onMouseLeave={() => setHoverKey(null)}
                style={{ background: hoverKey === p.key ? "var(--surface-2)" : "transparent", cursor: "default" }}
              >
                <td style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)", color: "var(--ink-dim)" }}>{i + 1}</td>
                <td style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)" }}>{p.label}</td>
                <td style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{formatValue(p.value as number, spec.unit, decimals)}</td>
                {showDate && <td style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)", color: "var(--ink-dim)" }}>{p.date ? String(p.date) : ""}</td>}
                {showSource && <td style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)", color: "var(--ink-dim)" }} className="mono">{p.source ? String(p.source) : ""}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > 15 && (
          <button type="button" onClick={() => setShowAll((s) => !s)} className="nav-link" style={{ marginTop: 8, background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: "0.8rem" }}>
            {showAll ? "Show top 15" : `Show all ${rows.length} places`}
          </button>
        )}
      </div>
    </div>
  );
}
