// VoonixReport.tsx
import { useEffect, useMemo, useState } from "/api/widget-runtime/react.js";

// _voonix_download.ts
async function downloadFile(url, fallbackName) {
  const r = await window.NousViz.widgets.apiFetch(url);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const body = await r.json();
      if (body && body.detail) msg = String(body.detail);
    } catch {
    }
    throw new Error(msg);
  }
  const cd = r.headers.get("Content-Disposition") || "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = match ? decodeURIComponent(match[1]) : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2e3);
  return r;
}

// VoonixReport.tsx
import { jsx, jsxs } from "/api/widget-runtime/react-jsx-runtime.js";
var PAGE = 50;
var API = "/api/plugins/voonix-analytics";
var T = {
  card: "hsl(var(--card))",
  bg: "hsl(var(--background))",
  fg: "hsl(var(--foreground))",
  muted: "hsl(var(--muted-foreground))",
  border: "hsl(var(--border))",
  primary: "hsl(var(--primary))",
  primaryFg: "hsl(var(--primary-foreground))"
};
var inputStyle = {
  height: 32,
  padding: "0 8px",
  borderRadius: 6,
  border: `1px solid ${T.border}`,
  background: T.bg,
  color: T.fg,
  fontSize: 13,
  colorScheme: "light dark"
};
function iso(d) {
  return d.toISOString().slice(0, 10);
}
function presets(monthGrain) {
  const now = /* @__PURE__ */ new Date();
  const today = iso(now);
  const daysAgo = (n) => iso(new Date(now.getTime() - n * 864e5));
  const monthStart = (offset) => iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + offset, 1)));
  const monthEnd = (offset) => iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + offset + 1, 0)));
  const list = [
    { label: "This month", start: monthStart(0), end: today },
    { label: "Last month", start: monthStart(-1), end: monthEnd(-1) },
    { label: "Last 12 months", start: monthStart(-11), end: today },
    { label: "Year to date", start: `${now.getUTCFullYear()}-01-01`, end: today },
    { label: "All", start: "", end: "" }
  ];
  if (!monthGrain) {
    list.unshift({ label: "30 days", start: daysAgo(29), end: today });
    list.unshift({ label: "7 days", start: daysAgo(6), end: today });
  }
  return list;
}
function toNum(v) {
  if (v === null || v === void 0 || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}
function fmt(v, format) {
  const n = toNum(v);
  if (n === null) return "\u2014";
  if (format === "money" || format === "number") {
    return n.toLocaleString(void 0, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return window.NousViz.widgets.formatNumber(Math.round(n));
}
function VoonixReport(props) {
  const report = String(props.config.report || "");
  const defaultDays = Number(props.config.default_days || 30);
  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [groupBy, setGroupBy] = useState([]);
  const [showAll, setShowAll] = useState(false);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [sort, setSort] = useState("");
  const [dir, setDir] = useState("desc");
  const [page, setPage] = useState(0);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportFormat, setExportFormat] = useState("xlsx");
  useEffect(() => {
    let cancelled = false;
    window.NousViz.widgets.apiFetch(`${API}/report/${encodeURIComponent(report)}/meta`).then(async (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }).then((m) => {
      if (cancelled) return;
      setMeta(m);
      setGroupBy(m.default_group_by);
      setSort(m.default_sort);
      const now = /* @__PURE__ */ new Date();
      if (m.month_grain) {
        setStart(iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 11, 1))));
      } else {
        setStart(iso(new Date(now.getTime() - (defaultDays - 1) * 864e5)));
      }
      setEnd(iso(now));
    }).catch((e) => {
      if (!cancelled) setMetaError(e.message);
    });
    return () => {
      cancelled = true;
    };
  }, [report, defaultDays]);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => {
    setPage(0);
  }, [start, end, groupBy, debounced, sort, dir]);
  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (start) p.set("start", start);
    if (end) p.set("end", end);
    p.set("group_by", groupBy.join(","));
    if (sort) p.set("sort", sort);
    p.set("dir", dir);
    if (debounced) p.set("search", debounced);
    return p;
  }, [start, end, groupBy, sort, dir, debounced]);
  useEffect(() => {
    if (!meta) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    const p = new URLSearchParams(query);
    p.set("limit", String(PAGE));
    p.set("offset", String(page * PAGE));
    window.NousViz.widgets.apiFetch(`${API}/report/${encodeURIComponent(report)}?${p.toString()}`).then(async (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }).then((res) => {
      if (!cancelled) {
        setResult(res);
        setLoading(false);
      }
    }).catch((e) => {
      if (!cancelled) {
        setError(e.message);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [meta, report, query, page]);
  const measures = useMemo(() => {
    if (!meta) return [];
    return showAll ? meta.measures : meta.measures.filter((m) => meta.default_measures.includes(m.key));
  }, [meta, showAll]);
  const dims = useMemo(() => {
    if (!meta || !result) return [];
    return result.group_by.map((k) => meta.dims.find((d) => d.key === k)).filter((d) => !!d);
  }, [meta, result]);
  function toggleDim(key) {
    setGroupBy((g) => {
      if (g.includes(key)) return g.length > 1 ? g.filter((k) => k !== key) : g;
      return [...g, key];
    });
  }
  function clickSort(key) {
    if (sort === key) setDir((d) => d === "asc" ? "desc" : "asc");
    else {
      setSort(key);
      setDir(meta?.dims.some((d) => d.key === key) ? "asc" : "desc");
    }
  }
  async function exportFile() {
    if (!meta) return;
    setExporting(true);
    setError(null);
    try {
      const p = new URLSearchParams(query);
      p.set("format", exportFormat);
      const r = await downloadFile(
        `${API}/report/${encodeURIComponent(report)}/export?${p.toString()}`,
        `voonix-${report}.${exportFormat}`
      );
      if (r.headers.get("X-Voonix-Truncated") === "1") {
        setError(`Download capped at ${r.headers.get("X-Voonix-Row-Limit")} rows \u2014 narrow the date range or grouping for the rest.`);
      }
    } catch (e) {
      setError(`Export failed: ${e.message}`);
    } finally {
      setExporting(false);
    }
  }
  const panel = {
    background: T.card,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: 16,
    color: T.fg
  };
  if (metaError) {
    return /* @__PURE__ */ jsx("div", { style: panel, children: /* @__PURE__ */ jsxs("span", { style: { color: "#f87171", fontSize: 13 }, children: [
      "Could not load report: ",
      metaError
    ] }) });
  }
  if (!meta) {
    return /* @__PURE__ */ jsx("div", { style: panel, children: /* @__PURE__ */ jsx("span", { style: { color: T.muted, fontSize: 13 }, children: "Loading\u2026" }) });
  }
  const totalPages = result ? Math.max(1, Math.ceil(result.total / PAGE)) : 1;
  const chip = (active) => ({
    padding: "3px 10px",
    borderRadius: 999,
    fontSize: 12,
    cursor: "pointer",
    border: `1px solid ${active ? T.primary : T.border}`,
    background: active ? T.primary : "transparent",
    color: active ? T.primaryFg : T.fg
  });
  const th = {
    padding: "8px 10px",
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    color: T.muted,
    borderBottom: `1px solid ${T.border}`,
    whiteSpace: "nowrap",
    cursor: "pointer",
    userSelect: "none"
  };
  const td = { padding: "7px 10px", borderBottom: `1px solid ${T.border}`, whiteSpace: "nowrap" };
  return /* @__PURE__ */ jsxs("div", { style: panel, children: [
    /* @__PURE__ */ jsxs("div", { style: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 10 }, children: [
      /* @__PURE__ */ jsx("div", { style: { fontWeight: 600, fontSize: 14, marginRight: 8 }, children: meta.label }),
      /* @__PURE__ */ jsx("input", { type: "date", value: start, onChange: (e) => setStart(e.target.value), style: inputStyle, "aria-label": "Start date" }),
      /* @__PURE__ */ jsx("span", { style: { color: T.muted, fontSize: 12 }, children: "to" }),
      /* @__PURE__ */ jsx("input", { type: "date", value: end, onChange: (e) => setEnd(e.target.value), style: inputStyle, "aria-label": "End date" }),
      presets(meta.month_grain).map((p) => /* @__PURE__ */ jsx(
        "button",
        {
          type: "button",
          style: chip(start === p.start && end === p.end),
          onClick: () => {
            setStart(p.start);
            setEnd(p.end);
          },
          children: p.label
        },
        p.label
      )),
      /* @__PURE__ */ jsx(
        "input",
        {
          type: "search",
          placeholder: "Search\u2026",
          value: search,
          onChange: (e) => setSearch(e.target.value),
          style: { ...inputStyle, marginLeft: "auto", minWidth: 180 }
        }
      ),
      /* @__PURE__ */ jsxs(
        "select",
        {
          value: exportFormat,
          onChange: (e) => setExportFormat(e.target.value),
          style: inputStyle,
          "aria-label": "Download format",
          children: [
            /* @__PURE__ */ jsx("option", { value: "xlsx", children: "Excel" }),
            /* @__PURE__ */ jsx("option", { value: "csv", children: "CSV" }),
            /* @__PURE__ */ jsx("option", { value: "json", children: "JSON" })
          ]
        }
      ),
      /* @__PURE__ */ jsx("button", { type: "button", style: chip(false), onClick: exportFile, disabled: exporting, children: exporting ? "Preparing\u2026" : "Download" })
    ] }),
    /* @__PURE__ */ jsxs("div", { style: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, marginBottom: 12 }, children: [
      /* @__PURE__ */ jsx("span", { style: { color: T.muted, fontSize: 12, marginRight: 4 }, children: "Group by" }),
      meta.dims.map((d) => /* @__PURE__ */ jsx("button", { type: "button", style: chip(groupBy.includes(d.key)), onClick: () => toggleDim(d.key), children: d.label }, d.key)),
      /* @__PURE__ */ jsx("span", { style: { flex: 1 } }),
      /* @__PURE__ */ jsx("button", { type: "button", style: chip(showAll), onClick: () => setShowAll((s) => !s), children: showAll ? "Fewer columns" : "All columns" })
    ] }),
    error && /* @__PURE__ */ jsx("div", { style: { color: "#f87171", fontSize: 13, marginBottom: 8 }, children: error }),
    result && result.total === 0 && !loading ? /* @__PURE__ */ jsxs("div", { style: { color: T.muted, fontSize: 13, padding: "16px 0" }, children: [
      "No data for this range",
      meta.max_date ? ` (data runs ${meta.min_date} \u2192 ${meta.max_date})` : " yet \u2014 run a sync",
      "."
    ] }) : /* @__PURE__ */ jsx("div", { style: { overflowX: "auto", opacity: loading ? 0.6 : 1 }, children: /* @__PURE__ */ jsxs("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 13 }, children: [
      /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
        dims.map((d) => /* @__PURE__ */ jsxs("th", { style: { ...th, textAlign: "left" }, onClick: () => clickSort(d.key), children: [
          d.label,
          sort === d.key ? dir === "asc" ? " \u2191" : " \u2193" : ""
        ] }, d.key)),
        measures.map((m) => /* @__PURE__ */ jsxs("th", { style: { ...th, textAlign: "right" }, onClick: () => clickSort(m.key), children: [
          m.label,
          sort === m.key ? dir === "asc" ? " \u2191" : " \u2193" : ""
        ] }, m.key))
      ] }) }),
      /* @__PURE__ */ jsxs("tbody", { children: [
        result && /* @__PURE__ */ jsxs("tr", { style: { fontWeight: 600 }, children: [
          /* @__PURE__ */ jsxs("td", { style: td, colSpan: Math.max(1, dims.length), children: [
            "Total (",
            window.NousViz.widgets.formatNumber(result.total),
            " rows)"
          ] }),
          measures.map((m) => /* @__PURE__ */ jsx("td", { style: { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }, children: fmt(result.totals[m.key], m.format) }, m.key))
        ] }),
        result?.rows.map((row, i) => /* @__PURE__ */ jsxs("tr", { children: [
          dims.map((d) => /* @__PURE__ */ jsx("td", { style: td, children: row[d.key] === null || row[d.key] === void 0 ? "\u2014" : String(row[d.key]) }, d.key)),
          measures.map((m) => /* @__PURE__ */ jsx("td", { style: { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }, children: fmt(row[m.key], m.format) }, m.key))
        ] }, i))
      ] })
    ] }) }),
    result && totalPages > 1 && /* @__PURE__ */ jsxs("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10, fontSize: 12, color: T.muted }, children: [
      /* @__PURE__ */ jsxs("span", { children: [
        "Page ",
        page + 1,
        " of ",
        totalPages
      ] }),
      /* @__PURE__ */ jsxs("div", { style: { display: "flex", gap: 6 }, children: [
        /* @__PURE__ */ jsx("button", { type: "button", style: chip(false), disabled: page === 0, onClick: () => setPage((p) => Math.max(0, p - 1)), children: "Prev" }),
        /* @__PURE__ */ jsx("button", { type: "button", style: chip(false), disabled: page >= totalPages - 1, onClick: () => setPage((p) => p + 1), children: "Next" })
      ] })
    ] }),
    /* @__PURE__ */ jsx("div", { style: { marginTop: 8, fontSize: 11, color: T.muted }, children: "Amounts are shown as Voonix reports them. Downloads include every column and use the filters above." })
  ] });
}
export {
  VoonixReport as default
};
