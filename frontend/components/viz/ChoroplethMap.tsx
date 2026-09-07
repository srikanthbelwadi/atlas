"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { GeoPayload } from "@/lib/types";

/**
 * Choropleth renderer for map answers (atlas-earth-engine-ui-plan.md §3).
 *
 * Everything drawn here came from the backend: `geo.features` are place
 * boundaries joined to the fetched rows on stable ids (backend/geo/
 * boundaries.py), each carrying {key, label, value, date?, source?}. The
 * synthesis model only chose the kind and named the columns; it never
 * produced a coordinate. The basemap is context and is optional — if the
 * style fails to load (offline, blocked host) the polygons still render on
 * a plain background, so an answer never depends on a third party to be
 * readable.
 */

const BASEMAP_STYLE = process.env.NEXT_PUBLIC_ATLAS_BASEMAP_STYLE || "https://tiles.openfreemap.org/styles/positron";

// Brand-derived sequential ramp (the teal accent, light → dark). Six
// classes, quantile-binned, so a skewed distribution (a few huge counties)
// still shows variation everywhere.
const RAMP_LIGHT = ["#e4efec", "#b9d8d2", "#8bbfb6", "#5aa093", "#2f7f73", "#175a50"];
const RAMP_DARK = ["#1c3a36", "#245a53", "#2f7f73", "#4a9e91", "#7cc3b8", "#b6e3db"];

const BLANK_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "rgba(0,0,0,0)" } }],
};

function quantileBreaks(values: number[], classes: number): number[] {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return [];
  const breaks: number[] = [];
  for (let i = 1; i < classes; i++) {
    const idx = Math.min(sorted.length - 1, Math.floor((i / classes) * sorted.length));
    breaks.push(sorted[idx]);
  }
  // Collapse duplicate breaks (many identical values) so every bin is real.
  return breaks.filter((b, i, arr) => i === 0 || b !== arr[i - 1]);
}

export function formatValue(v: number | null | undefined, unit?: string): string {
  if (v == null || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  let s: string;
  if (abs >= 1e9) s = `${(v / 1e9).toFixed(2)}B`;
  else if (abs >= 1e6) s = `${(v / 1e6).toFixed(2)}M`;
  else if (abs >= 1e4) s = Math.round(v).toLocaleString();
  else if (abs >= 100) s = v.toFixed(1);
  else s = v.toFixed(2);
  return unit ? `${s} ${unit}` : s;
}

interface Props {
  geo: GeoPayload;
  unit?: string;
  title?: string;
  onHover?: (key: string | null) => void;
  highlightKey?: string | null;
}

export default function ChoroplethMap({ geo, unit, title, onHover, highlightKey }: Props) {
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const [dark, setDark] = useState(false);
  const [basemapFailed, setBasemapFailed] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    setDark(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const ramp = dark ? RAMP_DARK : RAMP_LIGHT;
  const values = useMemo(
    () => geo.features.features.map((f) => f.properties.value).filter((v): v is number => typeof v === "number" && !Number.isNaN(v)),
    [geo]
  );
  const breaks = useMemo(() => quantileBreaks(values, ramp.length), [values, ramp.length]);

  // MapLibre "step" expression: colour by value across the quantile breaks.
  const fillColor = useMemo(() => {
    const expr: unknown[] = ["step", ["coalesce", ["get", "value"], -1e300], ramp[0]];
    breaks.forEach((b, i) => expr.push(b, ramp[Math.min(i + 1, ramp.length - 1)]));
    return expr;
  }, [breaks, ramp]);

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: BASEMAP_STYLE,
      bounds: geo.bounds ? [geo.bounds[0], geo.bounds[1], geo.bounds[2], geo.bounds[3]] : undefined,
      fitBoundsOptions: { padding: 28 },
      attributionControl: false,
      cooperativeGestures: true,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "Boundaries: Data Commons" }));

    let styleFailed = false;
    map.on("error", (e) => {
      // A basemap that can't be fetched (blocked host, offline) must not
      // take the data with it: fall back to a blank style; the choropleth
      // layers are re-added on the following style.load.
      const msg = String((e as { error?: { message?: string } }).error?.message || "");
      if (!styleFailed && !map.isStyleLoaded() && /style|fetch|Failed|NetworkError|404|403/i.test(msg)) {
        styleFailed = true;
        setBasemapFailed(true);
        map.setStyle(BLANK_STYLE);
      }
    });

    const addData = () => {
      if (map.getSource("places")) return;
      map.addSource("places", { type: "geojson", data: geo.features as GeoJSON.FeatureCollection, promoteId: "key" });
      map.addLayer({
        id: "places-fill",
        type: "fill",
        source: "places",
        paint: { "fill-color": fillColor as never, "fill-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 0.95, 0.78] },
      });
      map.addLayer({
        id: "places-line",
        type: "line",
        source: "places",
        paint: { "line-color": dark ? "#0f1a20" : "#ffffff", "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 2, 0.6] },
      });
      if (geo.bounds) map.fitBounds([geo.bounds[0], geo.bounds[1], geo.bounds[2], geo.bounds[3]], { padding: 28, duration: 0 });
    };
    map.on("style.load", addData);

    let hovered: string | null = null;
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: "280px" });
    popupRef.current = popup;
    map.on("mousemove", "places-fill", (e) => {
      const f = e.features?.[0];
      if (!f) return;
      const key = String(f.id ?? f.properties?.key ?? "");
      if (hovered && hovered !== key) map.setFeatureState({ source: "places", id: hovered }, { hover: false });
      hovered = key;
      map.setFeatureState({ source: "places", id: key }, { hover: true });
      map.getCanvas().style.cursor = "pointer";
      const p = f.properties || {};
      const extra = [p.date ? `<span>${p.date}</span>` : "", p.source ? `<span>${p.source}</span>` : ""].filter(Boolean).join(" · ");
      popup
        .setLngLat(e.lngLat)
        .setHTML(
          `<div style="font-family:var(--font-sans);font-size:12px;line-height:1.4;color:#16212b">` +
            `<div style="font-weight:600">${p.label ?? key}</div>` +
            `<div style="font-variant-numeric:tabular-nums">${formatValue(Number(p.value), unit)}</div>` +
            (extra ? `<div style="color:#57626c;font-size:11px;margin-top:2px">${extra}</div>` : "") +
            `</div>`
        )
        .addTo(map);
      onHover?.(key);
    });
    map.on("mouseleave", "places-fill", () => {
      if (hovered) map.setFeatureState({ source: "places", id: hovered }, { hover: false });
      hovered = null;
      map.getCanvas().style.cursor = "";
      popup.remove();
      onHover?.(null);
    });

    return () => {
      popup.remove();
      map.remove();
      mapRef.current = null;
    };
    // The map is created once per answer; colour/theme changes are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo]);

  // Re-paint on theme change without rebuilding the map.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer("places-fill")) return;
    map.setPaintProperty("places-fill", "fill-color", fillColor as never);
    map.setPaintProperty("places-line", "line-color", dark ? "#0f1a20" : "#ffffff");
  }, [fillColor, dark]);

  // External highlight (hovering a table row) → feature state.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("places")) return;
    geo.features.features.forEach((f) => map.setFeatureState({ source: "places", id: f.properties.key }, { hover: f.properties.key === highlightKey }));
  }, [highlightKey, geo]);

  const legendStops = useMemo(() => {
    const stops: { color: string; label: string }[] = [];
    const edges = [Math.min(...values), ...breaks, Math.max(...values)];
    for (let i = 0; i < edges.length - 1; i++) {
      stops.push({ color: ramp[Math.min(i, ramp.length - 1)], label: `${formatValue(edges[i])} – ${formatValue(edges[i + 1])}` });
    }
    return stops;
  }, [values, breaks, ramp]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <div style={{ fontSize: "0.88rem", fontWeight: 600 }}>{title || geo.value_field}</div>
        <div style={{ fontSize: "0.74rem", color: "var(--ink-dim)" }}>
          {geo.matched} places · boundaries from Data Commons{basemapFailed ? " · basemap unavailable" : ""}
        </div>
      </div>
      <div
        ref={container}
        style={{ width: "100%", height: "min(60vh, 520px)", borderRadius: 10, overflow: "hidden", border: "1px solid var(--border)", background: "var(--surface-2)" }}
        aria-label={`Map of ${geo.matched} places coloured by ${title || geo.value_field}`}
      />
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 14px", fontSize: "0.74rem", color: "var(--ink-dim)", alignItems: "center" }}>
        {legendStops.map((s) => (
          <span key={s.label} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 14, height: 10, background: s.color, borderRadius: 2, display: "inline-block", border: "1px solid var(--border)" }} />
            <span style={{ fontVariantNumeric: "tabular-nums" }}>{s.label}</span>
          </span>
        ))}
        {unit ? <span>({unit})</span> : null}
      </div>
    </div>
  );
}
