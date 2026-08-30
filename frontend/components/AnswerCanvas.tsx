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
  // Defensive: the synthesis model's `data` string is only *typed* as
  // matching each kind's expected shape — nothing stops it from actually
  // returning a different shape (an object instead of an array, a missing
  // field). safeParse only guards against invalid JSON, not a valid-JSON
  // wrong shape, so every field read below re-validates before use. This is
  // exactly the class of bug that crashed this panel in testing: valid JSON,
  // unexpected shape, `.length` read on `undefined`.
  const parsed = safeParse<unknown>(data, []);
  const rows = Array.isArray(parsed) ? (parsed as Record<string, unknown>[]) : [];
  if (!rows.length) return <Empty />;
  const columns = Object.keys(rows[0] ?? {});
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

function fmtBarValue(v: number): string {
  if (!Number.isFinite(v)) return "—";
  // Synthesis hands back raw floats straight off a BigQuery aggregate
  // (e.g. 24556.895695) — fine for the narrative's own rounding, but ugly
  // stacked directly over a bar. One decimal place under 100, none above,
  // with thousands separators so a 5-digit AQI reads at a glance.
  return v.toLocaleString(undefined, { maximumFractionDigits: Math.abs(v) < 100 ? 1 : 0 });
}

function BarViz({ data }: { data: string }) {
  const parsed = safeParse<Partial<{ labels: string[]; values: number[]; label?: string }>>(data, {});
  const labels = Array.isArray(parsed.labels) ? parsed.labels : [];
  const values = Array.isArray(parsed.values) ? parsed.values : [];
  if (!labels.length || !values.length) return <Empty />;
  const max = Math.max(...values, 1);
  const width = 640;
  const height = 220;
  const barWidth = width / labels.length;
  // A category label routinely runs longer than the ~64px a bar gets when
  // there are several of them (county/state names, e.g. "Providence, Rhode
  // Island") — confirmed live: a 10-bar ranking rendered with every label
  // overlapping its neighbors, and the first one clipped at the left edge
  // ("ence, Rhode Island" instead of "Providence..."). Past a handful of
  // bars, angle the labels instead of centering them under each bar — each
  // one gets much more room without needing the bars themselves to widen.
  const manyLabels = labels.length > 4;
  const bottomMargin = manyLabels ? 110 : 30;

  return (
    <svg viewBox={`0 0 ${width} ${height + bottomMargin}`} style={{ width: "100%", height: "auto" }}>
      {values.map((v, i) => {
        const h = (v / max) * height;
        const cx = i * barWidth + barWidth / 2;
        const labelY = height + (manyLabels ? 14 : 18);
        return (
          <g key={i}>
            <rect x={i * barWidth + barWidth * 0.15} y={height - h} width={barWidth * 0.7} height={h} fill="var(--accent)" rx={3} />
            <text
              x={cx}
              y={labelY}
              textAnchor={manyLabels ? "end" : "middle"}
              fontSize="11"
              fill="var(--ink-dim)"
              transform={manyLabels ? `rotate(-40 ${cx} ${labelY})` : undefined}
            >
              {labels[i]}
            </text>
            <text x={cx} y={height - h - 6} textAnchor="middle" fontSize="11" fill="var(--ink)" className="mono">
              {fmtBarValue(v)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function LineViz({ data }: { data: string }) {
  // This exact shape mismatch — synthesis returning valid JSON for a "line"
  // visualization without a usable `series` array — was the crash seen live:
  // `!series.length` threw "Cannot read properties of undefined" because
  // `series` didn't validate as an array before `.length` was read.
  const parsed = safeParse<Partial<{ labels: string[]; series: { name: string; values: number[] }[] }>>(data, {});
  const labels = Array.isArray(parsed.labels) ? parsed.labels : [];
  const series = Array.isArray(parsed.series)
    ? parsed.series.filter((s) => s && Array.isArray(s.values))
    : [];
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
      {labels.map((l, i) => {
        // The first/last label sits exactly on the viewBox edge (x=0 or
        // x=width). textAnchor="middle" there centers the text ON that
        // edge, so half of it — e.g. the leading "20" of "2020" — renders
        // outside the viewBox and gets clipped. Anchoring the end labels
        // to "start"/"end" instead keeps the tick position accurate while
        // letting the full label render inward, on-canvas.
        const x = (i / Math.max(labels.length - 1, 1)) * width;
        const anchor = i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle";
        return (
          <text key={l} x={x} y={height + 18} textAnchor={anchor} fontSize="11" fill="var(--ink-dim)">
            {l}
          </text>
        );
      })}
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
  const parsed = safeParse<unknown>(data, []);
  const cards = Array.isArray(parsed) ? (parsed as { label: string; value: string }[]) : [];
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
  const parsed = safeParse<Partial<{ headline: string; stats: { label: string; value: string }[]; note?: string }>>(data, {});
  const headline = typeof parsed.headline === "string" ? parsed.headline : "";
  const stats = Array.isArray(parsed.stats) ? parsed.stats : [];
  if (!headline && !stats.length) return <Empty />;
  return (
    <div style={{ background: "var(--accent-soft)", borderRadius: 12, padding: "22px 24px" }}>
      {headline && <div style={{ fontFamily: "var(--font-serif)", fontSize: "1.3rem", marginBottom: 14 }}>{headline}</div>}
      <KpiCardsViz data={JSON.stringify(stats)} />
      {parsed.note && <div style={{ fontSize: "0.8rem", color: "var(--ink-dim)", marginTop: 12 }}>{parsed.note}</div>}
    </div>
  );
}

function MapViz({ data }: { data: string }) {
  const parsed = safeParse<Partial<{ points: { lat: number; lon: number; label: string }[] }>>(data, {});
  const points = Array.isArray(parsed.points) ? parsed.points : [];
  if (!points.length) return <Empty />;
  return (
    <div>
      <div style={{ fontSize: "0.8rem", color: "var(--ink-dim)", marginBottom: 8 }}>
        Map rendering isn&rsquo;t wired up yet — showing the underlying points:
      </div>
      <TableViz data={JSON.stringify(points)} />
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
  // Defensive: the synthesis model's structured output is schema-validated
  // server-side, but a bare `.citations`/`.visualization` access would still
  // white-screen the whole page on any unexpected shape (a proxy truncating
  // the response, a future schema change). Fall back to something renderable.
  const citations = answer.citations ?? [];
  const visualization = answer.visualization ?? { kind: "table", data: "[]" };
  const vizData = visualization.data ?? "[]";
  const Viz = VIZ_COMPONENTS[visualization.kind] || TableViz;

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

      <Viz data={vizData} />

      {citations.length > 0 && (
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 14, display: "flex", flexWrap: "wrap", gap: 8 }}>
          {citations.map((c) => (
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

      <div style={{ fontSize: "0.72rem", color: "var(--ink-dim)" }}>
        {answer.elapsed_s != null ? `Answered in ${answer.elapsed_s}s` : null}
      </div>
    </div>
  );
}
