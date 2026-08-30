"use client";

import { Answer, TrustLevel } from "@/lib/types";

const TRUST_LABEL: Record<TrustLevel, string> = {
  "human-reviewed": "Human-reviewed",
  "machine-confirmed": "Machine-confirmed",
  unverified: "Unverified",
};

const TRUST_COLOR: Record<TrustLevel, string> = {
  "human-reviewed": "var(--accent-2)",
  "machine-confirmed": "var(--navy)",
  unverified: "var(--danger)",
};

function safeParse<T>(json: string, fallback: T): T {
  try {
    return JSON.parse(json) as T;
  } catch {
    return fallback;
  }
}

function TableViz({ data }: { data: string }) {
  const rows = safeParse<Record<string, unknown>[]>(data, []);
  if (!rows.length) return <Empty />;
  const columns = Object.keys(rows[0]);
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} style={{ textAlign: "left", padding: "8px 10px", borderBottom: "2px solid var(--border)", color: "var(--ink-dim)", fontWeight: 500 }}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} style={{ padding: "8px 10px", borderBottom: "1px solid var(--border)", fontVariantNumeric: "tabular-nums" }}>
                  {String(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BarViz({ data }: { data: string }) {
  const parsed = safeParse<{ labels: string[]; values: number[]; label?: string }>(data, { labels: [], values: [] });
  const { labels, values } = parsed;
  if (!labels.length) return <Empty />;
  const max = Math.max(...values, 1);
  const width = 640;
  const height = 220;
  const barWidth = width / labels.length;

  return (
    <svg viewBox={`0 0 ${width} ${height + 30}`} style={{ width: "100%", height: "auto" }}>
      {values.map((v, i) => {
        const h = (v / max) * height;
        return (
          <g key={i}>
            <rect x={i * barWidth + barWidth * 0.15} y={height - h} width={barWidth * 0.7} height={h} fill="var(--accent)" rx={3} />
            <text x={i * barWidth + barWidth / 2} y={height + 18} textAnchor="middle" fontSize="11" fill="var(--ink-dim)">
              {labels[i]}
            </text>
            <text x={i * barWidth + barWidth / 2} y={height - h - 6} textAnchor="middle" fontSize="11" fill="var(--ink)" className="mono">
              {v}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function LineViz({ data }: { data: string }) {
  const parsed = safeParse<{ labels: string[]; series: { name: string; values: number[] }[] }>(data, { labels: [], series: [] });
  const { labels, series } = parsed;
  if (!labels.length || !series.length) return <Empty />;
  const width = 640;
  const height = 220;
  const allValues = series.flatMap((s) => s.values);
  const max = Math.max(...allValues, 1);
  const min = Math.min(...allValues, 0);
  const range = max - min || 1;
  const colors = ["var(--accent)", "var(--accent-2)", "var(--navy)"];

  const points = (values: number[]) =>
    values
      .map((v, i) => {
        const x = (i / Math.max(labels.length - 1, 1)) * width;
        const y = height - ((v - min) / range) * height;
        return `${x},${y}`;
      })
      .join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height + 30}`} style={{ width: "100%", height: "auto" }}>
      <line x1={0} y1={height} x2={width} y2={height} stroke="var(--border)" />
      {series.map((s, si) => (
        <polyline key={s.name} points={points(s.values)} fill="none" stroke={colors[si % colors.length]} strokeWidth={2.5} />
      ))}
      {labels.map((l, i) => (
        <text key={l} x={(i / Math.max(labels.length - 1, 1)) * width} y={height + 18} textAnchor="middle" fontSize="11" fill="var(--ink-dim)">
          {l}
        </text>
      ))}
      {series.length > 1 && (
        <g>
          {series.map((s, si) => (
            <text key={s.name} x={8} y={16 + si * 16} fontSize="11" fill={colors[si % colors.length]}>
              ● {s.name}
            </text>
          ))}
        </g>
      )}
    </svg>
  );
}

function KpiCardsViz({ data }: { data: string }) {
  const cards = safeParse<{ label: string; value: string }[]>(data, []);
  if (!cards.length) return <Empty />;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
      {cards.map((c) => (
        <div key={c.label} style={{ background: "var(--surface-2)", borderRadius: 10, padding: "16px 18px" }}>
          <div style={{ fontSize: "1.6rem", fontFamily: "var(--font-serif)", fontWeight: 600 }}>{c.value}</div>
          <div style={{ fontSize: "0.78rem", color: "var(--ink-dim)", marginTop: 4 }}>{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function InfographicViz({ data }: { data: string }) {
  const parsed = safeParse<{ headline: string; stats: { label: string; value: string }[]; note?: string }>(data, { headline: "", stats: [] });
  if (!parsed.headline && !parsed.stats.length) return <Empty />;
  return (
    <div style={{ background: "var(--accent-soft)", borderRadius: 12, padding: "22px 24px" }}>
      {parsed.headline && <div style={{ fontFamily: "var(--font-serif)", fontSize: "1.3rem", marginBottom: 14 }}>{parsed.headline}</div>}
      <KpiCardsViz data={JSON.stringify(parsed.stats)} />
      {parsed.note && <div style={{ fontSize: "0.8rem", color: "var(--ink-dim)", marginTop: 12 }}>{parsed.note}</div>}
    </div>
  );
}

function MapViz({ data }: { data: string }) {
  const parsed = safeParse<{ points: { lat: number; lon: number; label: string }[] }>(data, { points: [] });
  if (!parsed.points.length) return <Empty />;
  return (
    <div>
      <div style={{ fontSize: "0.8rem", color: "var(--ink-dim)", marginBottom: 8 }}>
        Map rendering isn&rsquo;t wired up yet — showing the underlying points:
      </div>
      <TableViz data={JSON.stringify(parsed.points)} />
    </div>
  );
}

function Empty() {
  return <div style={{ color: "var(--ink-dim)", fontSize: "0.85rem" }}>No data to show.</div>;
}

const VIZ_COMPONENTS: Record<string, (props: { data: string }) => JSX.Element> = {
  table: TableViz,
  bar: BarViz,
  line: LineViz,
  kpi_cards: KpiCardsViz,
  infographic: InfographicViz,
  map: MapViz,
};

export default function AnswerCanvas({ answer }: { answer: Answer }) {
  const Viz = VIZ_COMPONENTS[answer.visualization.kind] || TableViz;

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "24px 26px",
        background: "var(--surface)",
        display: "flex",
        flexDirection: "column",
        gap: 20,
      }}
    >
      <p style={{ fontSize: "1.05rem", margin: 0, lineHeight: 1.65 }}>{answer.narrative}</p>

      <Viz data={answer.visualization.data} />

      {answer.citations.length > 0 && (
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 14, display: "flex", flexWrap: "wrap", gap: 8 }}>
          {answer.citations.map((c) => (
            <span
              key={c.source_id}
              className="mono"
              style={{
                fontSize: "0.72rem",
                padding: "4px 10px",
                borderRadius: 999,
                background: "var(--surface-2)",
                color: "var(--ink-dim)",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
              }}
              title={c.source_id}
            >
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: TRUST_COLOR[c.trust], display: "inline-block" }} />
              {c.title} · {TRUST_LABEL[c.trust]}
            </span>
          ))}
        </div>
      )}

      <div style={{ fontSize: "0.72rem", color: "var(--ink-dim)" }}>Answered in {answer.elapsed_s}s</div>
    </div>
  );
}
