// TrendCards.tsx
import { useEffect, useMemo, useState } from "/api/widget-runtime/react.js";
import { jsx, jsxs } from "/api/widget-runtime/react-jsx-runtime.js";
function asNumber(x) {
  if (x === null || x === void 0) return null;
  if (typeof x === "number" && Number.isFinite(x)) return x;
  if (typeof x === "string") {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}
function asString(x) {
  return x === null || x === void 0 ? "" : String(x);
}
function fmtValue(n, format) {
  if (n === null) return "\u2014";
  const fmt = window.NousViz.widgets.formatNumber;
  if (format === "percent") {
    return `${n.toFixed(1)}%`;
  }
  if (format === "compact") {
    if (Math.abs(n) >= 1e3) {
      return `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}k`;
    }
    return Math.round(n).toString();
  }
  return Number.isInteger(n) ? fmt(n) : n.toFixed(1);
}
function Sparkline({
  values,
  width = 200,
  height = 36,
  stroke
}) {
  const clean = values.map((v, i) => ({ v, i })).filter(
    (p) => p.v !== null && Number.isFinite(p.v)
  );
  if (clean.length < 2) {
    return /* @__PURE__ */ jsx("svg", { width: "100%", height, viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", style: { display: "block", opacity: 0.3 } });
  }
  const min = Math.min(...clean.map((p) => p.v));
  const max = Math.max(...clean.map((p) => p.v));
  const range = max - min || 1;
  const xStep = clean.length === 1 ? 0 : (width - 2) / (clean.length - 1);
  const linePts = [];
  const areaPts = [];
  clean.forEach((p, idx) => {
    const x = 1 + idx * xStep;
    const y = height - 2 - (p.v - min) / range * (height - 4) + 1;
    linePts.push(`${idx === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`);
    areaPts.push(`${idx === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`);
  });
  const lastX = 1 + (clean.length - 1) * xStep;
  areaPts.push(`L ${lastX.toFixed(1)} ${height} L 1 ${height} Z`);
  const gradientId = `spark-${Math.random().toString(36).slice(2, 9)}`;
  return /* @__PURE__ */ jsxs(
    "svg",
    {
      width: "100%",
      height,
      viewBox: `0 0 ${width} ${height}`,
      preserveAspectRatio: "none",
      style: { display: "block" },
      children: [
        /* @__PURE__ */ jsx("defs", { children: /* @__PURE__ */ jsxs("linearGradient", { id: gradientId, x1: "0", y1: "0", x2: "0", y2: "1", children: [
          /* @__PURE__ */ jsx("stop", { offset: "0%", stopColor: stroke, stopOpacity: 0.35 }),
          /* @__PURE__ */ jsx("stop", { offset: "100%", stopColor: stroke, stopOpacity: 0 })
        ] }) }),
        /* @__PURE__ */ jsx("path", { d: areaPts.join(" "), fill: `url(#${gradientId})`, stroke: "none" }),
        /* @__PURE__ */ jsx("path", { d: linePts.join(" "), stroke, strokeWidth: "1.5", fill: "none", strokeLinejoin: "round", strokeLinecap: "round" })
      ]
    }
  );
}
function Arrow({ direction }) {
  const path = direction === "up" ? "M 6 2 L 10 7 L 7 7 L 7 11 L 5 11 L 5 7 L 2 7 Z" : direction === "down" ? "M 6 11 L 2 6 L 5 6 L 5 2 L 7 2 L 7 6 L 10 6 Z" : "M 2 6 L 10 6";
  if (direction === "flat") {
    return /* @__PURE__ */ jsx("svg", { width: "12", height: "12", viewBox: "0 0 12 12", style: { display: "inline-block", verticalAlign: "middle" }, children: /* @__PURE__ */ jsx("path", { d: path, stroke: "currentColor", strokeWidth: "1.5", fill: "none", strokeLinecap: "round" }) });
  }
  return /* @__PURE__ */ jsx("svg", { width: "12", height: "12", viewBox: "0 0 12 12", style: { display: "inline-block", verticalAlign: "middle" }, children: /* @__PURE__ */ jsx("path", { d: path, fill: "currentColor" }) });
}
function BarsIcon() {
  return /* @__PURE__ */ jsxs("svg", { width: "14", height: "14", viewBox: "0 0 14 14", style: { display: "inline-block", verticalAlign: "middle", color: "hsl(var(--muted-foreground))" }, children: [
    /* @__PURE__ */ jsx("rect", { x: "2", y: "8", width: "2", height: "4", fill: "currentColor" }),
    /* @__PURE__ */ jsx("rect", { x: "6", y: "5", width: "2", height: "7", fill: "currentColor" }),
    /* @__PURE__ */ jsx("rect", { x: "10", y: "2", width: "2", height: "10", fill: "currentColor" })
  ] });
}
function MetricCard({
  card,
  valueFormat,
  compareOffset,
  comparePeriodLabel
}) {
  const lastIdx = (() => {
    for (let i = card.values.length - 1; i >= 0; i--) {
      if (card.values[i] !== null) return i;
    }
    return -1;
  })();
  const latest = lastIdx >= 0 ? card.values[lastIdx] : null;
  const prevIdx = lastIdx - compareOffset;
  const previous = prevIdx >= 0 ? card.values[prevIdx] : null;
  let direction = "flat";
  let deltaPct = null;
  if (latest !== null && previous !== null && previous !== 0) {
    deltaPct = (latest - previous) / Math.abs(previous) * 100;
    if (Math.abs(deltaPct) < 0.05) direction = "flat";
    else if (deltaPct > 0) direction = "up";
    else direction = "down";
  }
  const overallDirection = (() => {
    const firstReal = card.values.find((v) => v !== null);
    if (firstReal === void 0 || latest === null) return "flat";
    const diff = latest - firstReal;
    if (Math.abs(diff) < 0.05) return "flat";
    return diff > 0 ? "up" : "down";
  })();
  const sparkStroke = overallDirection === "up" ? "#34d399" : (
    // green-400
    overallDirection === "down" ? "#f87171" : (
      // red-400
      "#a1a1aa"
    )
  );
  const valueColor = direction === "up" ? "#34d399" : direction === "down" ? "#f87171" : "hsl(var(--foreground))";
  const deltaColor = direction === "up" ? "#34d399" : direction === "down" ? "#f87171" : "hsl(var(--muted-foreground))";
  return /* @__PURE__ */ jsxs(
    "div",
    {
      style: {
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
        overflow: "hidden"
      },
      children: [
        /* @__PURE__ */ jsxs("div", { style: { display: "flex", alignItems: "center", gap: 6 }, children: [
          /* @__PURE__ */ jsx(BarsIcon, {}),
          /* @__PURE__ */ jsx("span", { style: {
            fontSize: 10,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: "hsl(var(--muted-foreground))"
          }, children: card.label })
        ] }),
        /* @__PURE__ */ jsx("div", { style: {
          fontSize: 28,
          fontWeight: 700,
          color: valueColor,
          fontVariantNumeric: "tabular-nums",
          lineHeight: 1.1
        }, children: fmtValue(latest, valueFormat) }),
        /* @__PURE__ */ jsxs("div", { style: {
          display: "flex",
          alignItems: "center",
          gap: 4,
          fontSize: 11,
          color: deltaColor,
          fontVariantNumeric: "tabular-nums"
        }, children: [
          /* @__PURE__ */ jsx(Arrow, { direction }),
          /* @__PURE__ */ jsx("span", { children: deltaPct === null ? previous === null ? "\u2014" : `was ${fmtValue(previous, valueFormat)}` : `${Math.abs(deltaPct).toFixed(1)}% was ${fmtValue(previous, valueFormat)}` }),
          /* @__PURE__ */ jsxs("span", { style: { color: "hsl(var(--muted-foreground))", marginLeft: 4 }, children: [
            "\xB7 ",
            comparePeriodLabel
          ] })
        ] }),
        /* @__PURE__ */ jsx("div", { style: { marginTop: 4, marginLeft: -6, marginRight: -6 }, children: /* @__PURE__ */ jsx(Sparkline, { values: card.values, stroke: sparkStroke }) })
      ]
    }
  );
}
function TrendCards(props) {
  const config = props.config;
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
    engine = "postgres"
  } = config;
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!query) {
      setError("No query configured");
      setLoaded(true);
      return;
    }
    window.NousViz.widgets.apiFetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql: query, engine })
    }).then(async (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }).then((data) => {
      if (cancelled) return;
      const dataRows = data?.rows ?? (Array.isArray(data) ? data : []);
      setRows(dataRows);
      setLoaded(true);
    }).catch((e) => {
      if (cancelled) return;
      setError(e.message);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [query, engine]);
  const cards = useMemo(() => {
    if (rows.length === 0) return [];
    if (!series_key) {
      const sorted = [...rows].sort(
        (a, b) => asString(a[period_key]).localeCompare(asString(b[period_key]))
      );
      return [{
        key: "_single",
        label,
        periods: sorted.map((r) => asString(r[period_key])),
        values: sorted.map((r) => asNumber(r[value_key]))
      }];
    }
    const groups = /* @__PURE__ */ new Map();
    for (const r of rows) {
      const k = asString(r[series_key]);
      if (!k) continue;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(r);
    }
    return Array.from(groups.entries()).map(([k, group]) => {
      const sorted = group.sort(
        (a, b) => asString(a[period_key]).localeCompare(asString(b[period_key]))
      );
      const meta = series_labels?.[k];
      return {
        key: k,
        label: meta?.label ?? k,
        periods: sorted.map((r) => asString(r[period_key])),
        values: sorted.map((r) => asNumber(r[value_key]))
      };
    });
  }, [rows, period_key, value_key, series_key, label, series_labels]);
  if (!loaded) {
    return /* @__PURE__ */ jsxs("div", { className: "bg-card border border-border rounded-lg p-4", children: [
      title && /* @__PURE__ */ jsx("div", { className: "text-sm font-medium mb-2", children: title }),
      /* @__PURE__ */ jsx("div", { className: "text-xs text-muted-foreground", children: "Loading\u2026" })
    ] });
  }
  if (error) {
    return /* @__PURE__ */ jsxs("div", { className: "bg-card border border-border rounded-lg p-4", children: [
      title && /* @__PURE__ */ jsx("div", { className: "text-sm font-medium mb-2", children: title }),
      /* @__PURE__ */ jsxs("div", { className: "text-xs", style: { color: "#f87171" }, children: [
        "Trend cards query failed: ",
        error
      ] })
    ] });
  }
  if (cards.length === 0) {
    return /* @__PURE__ */ jsxs("div", { className: "bg-card border border-border rounded-lg p-4", children: [
      title && /* @__PURE__ */ jsx("div", { className: "text-sm font-medium mb-2", children: title }),
      /* @__PURE__ */ jsx("div", { className: "text-xs text-muted-foreground", children: "No data." })
    ] });
  }
  const useFlushLayout = cards.length === 1 && !title;
  if (useFlushLayout) {
    return /* @__PURE__ */ jsx(
      MetricCard,
      {
        card: cards[0],
        valueFormat: value_format,
        compareOffset: compare_period_offset,
        comparePeriodLabel: compare_period_label
      }
    );
  }
  return /* @__PURE__ */ jsxs("div", { className: "bg-card border border-border rounded-lg p-4", children: [
    title && /* @__PURE__ */ jsx("div", { className: "text-sm font-medium mb-3 text-foreground", children: title }),
    /* @__PURE__ */ jsx("div", { style: { display: "flex", flexWrap: "wrap", gap: 12 }, children: cards.map((c) => /* @__PURE__ */ jsx(
      MetricCard,
      {
        card: c,
        valueFormat: value_format,
        compareOffset: compare_period_offset,
        comparePeriodLabel: compare_period_label
      },
      c.key
    )) })
  ] });
}
export {
  TrendCards as default
};
