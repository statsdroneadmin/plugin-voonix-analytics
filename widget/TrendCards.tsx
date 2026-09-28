/// <reference path="./nousviz_widget_types.d.ts" />
/**
 * TrendCards — KPI cards with auto-zoomed sparkline + direction-coded delta.
 *
 * Drop-in replacement for `type: bar_chart` panels whose y-axis was
 * anchored at zero (so a 7,700–8,200 segment headcount range rendered
 * as 24 nearly-identical bars). The sparkline auto-fits to the actual
 * data range, and the delta line gives the operator an at-a-glance
 * "is this growing or shrinking, and by how much" signal.
 *
 * Pattern borrowed from plugin-avizo-jira's _metric_card.tsx:
 *   icon · label · big tabular value · delta with arrow + previous +
 *   period label · auto-zoomed sparkline along the bottom.
 *
 * Dependency surface kept minimal — no lucide-react, no recharts,
 * just inline SVG (matches v0.4.9 row-sparkline approach in
 * GrowthHeatmap). Bundle stays small; hygiene checks pass without
 * any new external deps.
 *
 * Dashboard YAML config consumed:
 *   query                  : SQL string returning rows
 *   period_key             : column for the time axis (default "month")
 *   value_key              : column for the metric (default "total")
 *   series_key             : optional — column to split into N cards
 *   label                  : single-card mode label
 *   icon                   : single-card mode icon (currently "bars")
 *   value_format           : "number" | "compact" | "percent"
 *   compare_period_offset  : periods back for delta (default 1)
 *   compare_period_label   : "vs prior month", "vs 12 months ago", …
 *   series_labels          : { series_value: { label, icon? } } map
 *                            (multi-card layouts)
 *   engine                 : "postgres"
 *
 * Reference: docs/05-widgets-custom-react.md in the parent SDK guide.
 */

import { useEffect, useMemo, useState } from "react";

interface SeriesLabel {
  label?: string;
  icon?: string;
}

interface Config {
  query: string;
  title?: string;
  period_key?: string;
  value_key?: string;
  series_key?: string;
  label?: string;
  icon?: string;
  value_format?: "number" | "compact" | "percent";
  compare_period_offset?: number;
  compare_period_label?: string;
  series_labels?: Record<string, SeriesLabel>;
  engine?: string;
}

interface Row {
  [key: string]: unknown;
}

function asNumber(x: unknown): number | null {
  if (x === null || x === undefined) return null;
  if (typeof x === "number" && Number.isFinite(x)) return x;
  if (typeof x === "string") {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function asString(x: unknown): string {
  return x === null || x === undefined ? "" : String(x);
}

function fmtValue(n: number | null, format: Config["value_format"]): string {
  if (n === null) return "—";
  const fmt = window.NousViz.widgets.formatNumber;
  if (format === "percent") {
    return `${n.toFixed(1)}%`;
  }
  if (format === "compact") {
    if (Math.abs(n) >= 1000) {
      return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
    }
    return Math.round(n).toString();
  }
  return Number.isInteger(n) ? fmt(n) : n.toFixed(1);
}

interface CardData {
  key: string;
  label: string;
  values: Array<number | null>;   // ordered by period ascending
  periods: string[];              // matching period labels
}

/**
 * Auto-zoomed inline-SVG sparkline. Same pattern as the v0.4.9 row
 * sparkline in GrowthHeatmap, but sized for a card footer (full width,
 * 36px tall) with a subtle area fill underneath the line.
 */
function Sparkline({
  values, width = 200, height = 36, stroke,
}: {
  values: Array<number | null>;
  width?: number;
  height?: number;
  stroke: string;
}) {
  const clean = values
    .map((v, i) => ({ v, i }))
    .filter((p): p is { v: number; i: number } =>
      p.v !== null && Number.isFinite(p.v),
    );
  if (clean.length < 2) {
    return <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ display: "block", opacity: 0.3 }} />;
  }
  const min = Math.min(...clean.map((p) => p.v));
  const max = Math.max(...clean.map((p) => p.v));
  const range = max - min || 1;
  const xStep = clean.length === 1 ? 0 : (width - 2) / (clean.length - 1);

  const linePts: string[] = [];
  const areaPts: string[] = [];
  clean.forEach((p, idx) => {
    const x = 1 + idx * xStep;
    const y = (height - 2) - ((p.v - min) / range) * (height - 4) + 1;
    linePts.push(`${idx === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`);
    areaPts.push(`${idx === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`);
  });
  // Close the area path along the bottom edge.
  const lastX = 1 + (clean.length - 1) * xStep;
  areaPts.push(`L ${lastX.toFixed(1)} ${height} L 1 ${height} Z`);

  // gradientId must be unique per render to avoid SVG fill collisions
  // when multiple sparklines are on the same page.
  const gradientId = `spark-${Math.random().toString(36).slice(2, 9)}`;

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ display: "block" }}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity={0.35} />
          <stop offset="100%" stopColor={stroke} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={areaPts.join(" ")} fill={`url(#${gradientId})`} stroke="none" />
      <path d={linePts.join(" ")} stroke={stroke} strokeWidth="1.5" fill="none" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function Arrow({ direction }: { direction: "up" | "down" | "flat" }) {
  // Inline SVG so no lucide dep. 12px square.
  const path =
    direction === "up"   ? "M 6 2 L 10 7 L 7 7 L 7 11 L 5 11 L 5 7 L 2 7 Z" :
    direction === "down" ? "M 6 11 L 2 6 L 5 6 L 5 2 L 7 2 L 7 6 L 10 6 Z" :
    "M 2 6 L 10 6";
  if (direction === "flat") {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" style={{ display: "inline-block", verticalAlign: "middle" }}>
        <path d={path} stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" style={{ display: "inline-block", verticalAlign: "middle" }}>
      <path d={path} fill="currentColor" />
    </svg>
  );
}

function BarsIcon() {
  // Tiny "bar chart" glyph — placeholder for the card's leading icon
  // until we add proper lucide support. Kept inline-SVG to avoid deps.
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" style={{ display: "inline-block", verticalAlign: "middle", color: "hsl(var(--muted-foreground))" }}>
      <rect x="2" y="8" width="2" height="4" fill="currentColor" />
      <rect x="6" y="5" width="2" height="7" fill="currentColor" />
      <rect x="10" y="2" width="2" height="10" fill="currentColor" />
    </svg>
  );
}

/**
 * One metric card. Rendered inside a flex row by the parent.
 */
function MetricCard({
  card, valueFormat, compareOffset, comparePeriodLabel,
}: {
  card: CardData;
  valueFormat: Config["value_format"];
  compareOffset: number;
  comparePeriodLabel: string;
}) {
  // Latest = last non-null value. Previous = value `compareOffset` periods
  // before that. If either is missing, we degrade gracefully.
  const lastIdx = (() => {
    for (let i = card.values.length - 1; i >= 0; i--) {
      if (card.values[i] !== null) return i;
    }
    return -1;
  })();

  const latest = lastIdx >= 0 ? card.values[lastIdx] : null;
  const prevIdx = lastIdx - compareOffset;
  const previous = prevIdx >= 0 ? card.values[prevIdx] : null;

  let direction: "up" | "down" | "flat" = "flat";
  let deltaPct: number | null = null;
  if (latest !== null && previous !== null && previous !== 0) {
    deltaPct = ((latest - previous) / Math.abs(previous)) * 100;
    if (Math.abs(deltaPct) < 0.05) direction = "flat";
    else if (deltaPct > 0) direction = "up";
    else direction = "down";
  }

  // Overall first→last direction drives sparkline color.
  const overallDirection: "up" | "down" | "flat" = (() => {
    const firstReal = card.values.find((v) => v !== null);
    if (firstReal === undefined || latest === null) return "flat";
    const diff = latest - firstReal;
    if (Math.abs(diff) < 0.05) return "flat";
    return diff > 0 ? "up" : "down";
  })();

  const sparkStroke =
    overallDirection === "up"   ? "#34d399" :   // green-400
    overallDirection === "down" ? "#f87171" :   // red-400
    "#a1a1aa";                                  // zinc-400

  const valueColor =
    direction === "up"   ? "#34d399" :
    direction === "down" ? "#f87171" :
    "hsl(var(--foreground))";

  const deltaColor =
    direction === "up"   ? "#34d399" :
    direction === "down" ? "#f87171" :
    "hsl(var(--muted-foreground))";

  // Card chrome — all inline-style to defeat host Tailwind purging (G-5).
  return (
    <div
      style={{
        backgroundColor: "transparent",
        border: "1px solid hsl(var(--border))",
        borderRadius: 8,
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        flex: "1 1 220px",
        minWidth: 220,
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Header — icon + uppercase label */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <BarsIcon />
        <span style={{
          fontSize: 10,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "hsl(var(--muted-foreground))",
        }}>
          {card.label}
        </span>
      </div>

      {/* Big value */}
      <div style={{
        fontSize: 28,
        fontWeight: 700,
        color: valueColor,
        fontVariantNumeric: "tabular-nums",
        lineHeight: 1.1,
      }}>
        {fmtValue(latest, valueFormat)}
      </div>

      {/* Delta line */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        fontSize: 11,
        color: deltaColor,
        fontVariantNumeric: "tabular-nums",
      }}>
        <Arrow direction={direction} />
        <span>
          {deltaPct === null
            ? (previous === null ? "—" : `was ${fmtValue(previous, valueFormat)}`)
            : `${Math.abs(deltaPct).toFixed(1)}% was ${fmtValue(previous, valueFormat)}`}
        </span>
        <span style={{ color: "hsl(var(--muted-foreground))", marginLeft: 4 }}>· {comparePeriodLabel}</span>
      </div>

      {/* Sparkline */}
      <div style={{ marginTop: 4, marginLeft: -6, marginRight: -6 }}>
        <Sparkline values={card.values} stroke={sparkStroke} />
      </div>
    </div>
  );
}

export default function TrendCards(props: CustomWidgetProps) {
  const config = props.config as unknown as Config;
  const {
    query,
    title,
    period_key = "month",
    value_key = "total",
    series_key,
    label = "Total",
    value_format = "number",
    compare_period_offset = 1,
    compare_period_label = "vs prior month",
    series_labels,
    engine = "postgres",
  } = config;

  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!query) {
      setError("No query configured");
      setLoaded(true);
      return;
    }
    window.NousViz.widgets
      .apiFetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql: query, engine }),
      })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: unknown) => {
        if (cancelled) return;
        const dataRows =
          (data as { rows?: Row[] })?.rows ??
          (Array.isArray(data) ? (data as Row[]) : []);
        setRows(dataRows);
        setLoaded(true);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setError(e.message);
        setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [query, engine]);

  const cards: CardData[] = useMemo(() => {
    if (rows.length === 0) return [];

    // Single-series mode (no series_key) — collapse all rows into one card.
    if (!series_key) {
      const sorted = [...rows].sort((a, b) =>
        asString(a[period_key]).localeCompare(asString(b[period_key])),
      );
      return [{
        key: "_single",
        label,
        periods: sorted.map((r) => asString(r[period_key])),
        values: sorted.map((r) => asNumber(r[value_key])),
      }];
    }

    // Multi-series mode — group by series_key, sort each by period.
    const groups = new Map<string, Row[]>();
    for (const r of rows) {
      const k = asString(r[series_key]);
      if (!k) continue;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k)!.push(r);
    }
    return Array.from(groups.entries()).map(([k, group]) => {
      const sorted = group.sort((a, b) =>
        asString(a[period_key]).localeCompare(asString(b[period_key])),
      );
      const meta = series_labels?.[k];
      return {
        key: k,
        label: meta?.label ?? k,
        periods: sorted.map((r) => asString(r[period_key])),
        values: sorted.map((r) => asNumber(r[value_key])),
      };
    });
  }, [rows, period_key, value_key, series_key, label, series_labels]);

  if (!loaded) {
    return (
      <div className="bg-card border border-border rounded-lg p-4">
        {title && <div className="text-sm font-medium mb-2">{title}</div>}
        <div className="text-xs text-muted-foreground">Loading…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-card border border-border rounded-lg p-4">
        {title && <div className="text-sm font-medium mb-2">{title}</div>}
        <div className="text-xs" style={{ color: "#f87171" }}>Trend cards query failed: {error}</div>
      </div>
    );
  }

  if (cards.length === 0) {
    return (
      <div className="bg-card border border-border rounded-lg p-4">
        {title && <div className="text-sm font-medium mb-2">{title}</div>}
        <div className="text-xs text-muted-foreground">No data.</div>
      </div>
    );
  }

  // When there's exactly one card and no panel title, skip the outer
  // panel-chrome wrapper — the card itself is the panel. Avoids the
  // "double border" look when 8 single-card panels are arranged in a
  // grid (Overview dashboard, v0.5.1+).
  const useFlushLayout = cards.length === 1 && !title;

  if (useFlushLayout) {
    return (
      <MetricCard
        card={cards[0]}
        valueFormat={value_format}
        compareOffset={compare_period_offset}
        comparePeriodLabel={compare_period_label}
      />
    );
  }

  return (
    <div className="bg-card border border-border rounded-lg p-4">
      {title && (
        <div className="text-sm font-medium mb-3 text-foreground">{title}</div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {cards.map((c) => (
          <MetricCard
            key={c.key}
            card={c}
            valueFormat={value_format}
            compareOffset={compare_period_offset}
            comparePeriodLabel={compare_period_label}
          />
        ))}
      </div>
    </div>
  );
}
