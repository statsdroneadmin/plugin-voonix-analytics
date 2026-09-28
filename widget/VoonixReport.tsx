/// <reference path="./nousviz_widget_types.d.ts" />
/**
 * VoonixReport — date-range + group-by report table over one mirrored
 * Voonix report (advertiser earnings, site earnings, payouts, …).
 *
 * Dashboard YAML config:
 *   report       : key in src/voonix_analytics_catalog.py REPORTS
 *   default_days : optional initial range length (default 30; month-grain
 *                  reports default to the last 12 months)
 *
 * Everything else (dims, measures, defaults) comes from
 * GET /api/plugins/voonix-analytics/report/{report}/meta.
 * Downloads (Excel / CSV / JSON) are generated server-side by
 * GET /report/{report}/export with the same filters as the table.
 *
 * Styling uses host theme tokens so it reads in light and dark themes.
 */

import { useEffect, useMemo, useState } from "react";
import { downloadFile } from "./_voonix_download";

interface Dim { key: string; label: string }
interface Measure { key: string; label: string; format: "int" | "money" | "number" }
interface Meta {
  label: string;
  month_grain: boolean;
  dims: Dim[];
  measures: Measure[];
  default_measures: string[];
  default_group_by: string[];
  default_sort: string;
  min_date: string | null;
  max_date: string | null;
}
type Row = Record<string, unknown>;
interface Result { rows: Row[]; total: number; totals: Row; group_by: string[]; sort: string; dir: string }
type ExportFormat = "xlsx" | "csv" | "json";

const PAGE = 50;
const API = "/api/plugins/voonix-analytics";
const T = {
  card: "hsl(var(--card))",
  bg: "hsl(var(--background))",
  fg: "hsl(var(--foreground))",
  muted: "hsl(var(--muted-foreground))",
  border: "hsl(var(--border))",
  primary: "hsl(var(--primary))",
  primaryFg: "hsl(var(--primary-foreground))",
};

const inputStyle: React.CSSProperties = {
  height: 32, padding: "0 8px", borderRadius: 6, border: `1px solid ${T.border}`,
  background: T.bg, color: T.fg, fontSize: 13, colorScheme: "light dark",
};

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function presets(monthGrain: boolean): { label: string; start: string; end: string }[] {
  const now = new Date();
  const today = iso(now);
  const daysAgo = (n: number) => iso(new Date(now.getTime() - n * 86400000));
  const monthStart = (offset: number) => iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + offset, 1)));
  const monthEnd = (offset: number) => iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + offset + 1, 0)));
  const list = [
    { label: "This month", start: monthStart(0), end: today },
    { label: "Last month", start: monthStart(-1), end: monthEnd(-1) },
    { label: "Last 12 months", start: monthStart(-11), end: today },
    { label: "Year to date", start: `${now.getUTCFullYear()}-01-01`, end: today },
    { label: "All", start: "", end: "" },
  ];
  if (!monthGrain) {
    list.unshift({ label: "30 days", start: daysAgo(29), end: today });
    list.unshift({ label: "7 days", start: daysAgo(6), end: today });
  }
  return list;
}

function toNum(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmt(v: unknown, format: Measure["format"]): string {
  const n = toNum(v);
  if (n === null) return "—";
  if (format === "money" || format === "number") {
    return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return window.NousViz.widgets.formatNumber(Math.round(n));
}

export default function VoonixReport(props: CustomWidgetProps) {
  const report = String(props.config.report || "");
  const defaultDays = Number(props.config.default_days || 30);

  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [groupBy, setGroupBy] = useState<string[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [sort, setSort] = useState("");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportFormat, setExportFormat] = useState<ExportFormat>("xlsx");

  useEffect(() => {
    let cancelled = false;
    window.NousViz.widgets
      .apiFetch(`${API}/report/${encodeURIComponent(report)}/meta`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((m: Meta) => {
        if (cancelled) return;
        setMeta(m);
        setGroupBy(m.default_group_by);
        setSort(m.default_sort);
        const now = new Date();
        if (m.month_grain) {
          setStart(iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 11, 1))));
        } else {
          setStart(iso(new Date(now.getTime() - (defaultDays - 1) * 86400000)));
        }
        setEnd(iso(now));
      })
      .catch((e: Error) => { if (!cancelled) setMetaError(e.message); });
    return () => { cancelled = true; };
  }, [report, defaultDays]);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => { setPage(0); }, [start, end, groupBy, debounced, sort, dir]);

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
    window.NousViz.widgets
      .apiFetch(`${API}/report/${encodeURIComponent(report)}?${p.toString()}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((res: Result) => { if (!cancelled) { setResult(res); setLoading(false); } })
      .catch((e: Error) => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [meta, report, query, page]);

  const measures = useMemo(() => {
    if (!meta) return [];
    return showAll ? meta.measures : meta.measures.filter((m) => meta.default_measures.includes(m.key));
  }, [meta, showAll]);

  const dims = useMemo(() => {
    if (!meta || !result) return [];
    return result.group_by.map((k) => meta.dims.find((d) => d.key === k)).filter((d): d is Dim => !!d);
  }, [meta, result]);

  function toggleDim(key: string) {
    setGroupBy((g) => {
      if (g.includes(key)) return g.length > 1 ? g.filter((k) => k !== key) : g;
      return [...g, key];
    });
  }

  function clickSort(key: string) {
    if (sort === key) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSort(key); setDir(meta?.dims.some((d) => d.key === key) ? "asc" : "desc"); }
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
        `voonix-${report}.${exportFormat}`,
      );
      if (r.headers.get("X-Voonix-Truncated") === "1") {
        setError(`Download capped at ${r.headers.get("X-Voonix-Row-Limit")} rows — narrow the date range or grouping for the rest.`);
      }
    } catch (e) {
      setError(`Export failed: ${(e as Error).message}`);
    } finally {
      setExporting(false);
    }
  }

  const panel: React.CSSProperties = {
    background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, padding: 16, color: T.fg,
  };

  if (metaError) {
    return <div style={panel}><span style={{ color: "#f87171", fontSize: 13 }}>Could not load report: {metaError}</span></div>;
  }
  if (!meta) {
    return <div style={panel}><span style={{ color: T.muted, fontSize: 13 }}>Loading…</span></div>;
  }

  const totalPages = result ? Math.max(1, Math.ceil(result.total / PAGE)) : 1;
  const chip = (active: boolean): React.CSSProperties => ({
    padding: "3px 10px", borderRadius: 999, fontSize: 12, cursor: "pointer",
    border: `1px solid ${active ? T.primary : T.border}`,
    background: active ? T.primary : "transparent", color: active ? T.primaryFg : T.fg,
  });
  const th: React.CSSProperties = {
    padding: "8px 10px", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em",
    color: T.muted, borderBottom: `1px solid ${T.border}`, whiteSpace: "nowrap", cursor: "pointer",
    userSelect: "none",
  };
  const td: React.CSSProperties = { padding: "7px 10px", borderBottom: `1px solid ${T.border}`, whiteSpace: "nowrap" };

  return (
    <div style={panel}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <div style={{ fontWeight: 600, fontSize: 14, marginRight: 8 }}>{meta.label}</div>
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} style={inputStyle} aria-label="Start date" />
        <span style={{ color: T.muted, fontSize: 12 }}>to</span>
        <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} style={inputStyle} aria-label="End date" />
        {presets(meta.month_grain).map((p) => (
          <button key={p.label} type="button" style={chip(start === p.start && end === p.end)}
            onClick={() => { setStart(p.start); setEnd(p.end); }}>
            {p.label}
          </button>
        ))}
        <input type="search" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)}
          style={{ ...inputStyle, marginLeft: "auto", minWidth: 180 }} />
        <select value={exportFormat} onChange={(e) => setExportFormat(e.target.value as ExportFormat)}
          style={inputStyle} aria-label="Download format">
          <option value="xlsx">Excel</option>
          <option value="csv">CSV</option>
          <option value="json">JSON</option>
        </select>
        <button type="button" style={chip(false)} onClick={exportFile} disabled={exporting}>
          {exporting ? "Preparing…" : "Download"}
        </button>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, marginBottom: 12 }}>
        <span style={{ color: T.muted, fontSize: 12, marginRight: 4 }}>Group by</span>
        {meta.dims.map((d) => (
          <button key={d.key} type="button" style={chip(groupBy.includes(d.key))} onClick={() => toggleDim(d.key)}>
            {d.label}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <button type="button" style={chip(showAll)} onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Fewer columns" : "All columns"}
        </button>
      </div>

      {error && <div style={{ color: "#f87171", fontSize: 13, marginBottom: 8 }}>{error}</div>}

      {result && result.total === 0 && !loading ? (
        <div style={{ color: T.muted, fontSize: 13, padding: "16px 0" }}>
          No data for this range{meta.max_date ? ` (data runs ${meta.min_date} → ${meta.max_date})` : " yet — run a sync"}.
        </div>
      ) : (
        <div style={{ overflowX: "auto", opacity: loading ? 0.6 : 1 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                {dims.map((d) => (
                  <th key={d.key} style={{ ...th, textAlign: "left" }} onClick={() => clickSort(d.key)}>
                    {d.label}{sort === d.key ? (dir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                ))}
                {measures.map((m) => (
                  <th key={m.key} style={{ ...th, textAlign: "right" }} onClick={() => clickSort(m.key)}>
                    {m.label}{sort === m.key ? (dir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result && (
                <tr style={{ fontWeight: 600 }}>
                  <td style={td} colSpan={Math.max(1, dims.length)}>Total ({window.NousViz.widgets.formatNumber(result.total)} rows)</td>
                  {measures.map((m) => (
                    <td key={m.key} style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                      {fmt(result.totals[m.key], m.format)}
                    </td>
                  ))}
                </tr>
              )}
              {result?.rows.map((row, i) => (
                <tr key={i}>
                  {dims.map((d) => (
                    <td key={d.key} style={td}>{row[d.key] === null || row[d.key] === undefined ? "—" : String(row[d.key])}</td>
                  ))}
                  {measures.map((m) => (
                    <td key={m.key} style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                      {fmt(row[m.key], m.format)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {result && totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10, fontSize: 12, color: T.muted }}>
          <span>Page {page + 1} of {totalPages}</span>
          <div style={{ display: "flex", gap: 6 }}>
            <button type="button" style={chip(false)} disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>Prev</button>
            <button type="button" style={chip(false)} disabled={page >= totalPages - 1} onClick={() => setPage((p) => p + 1)}>Next</button>
          </div>
        </div>
      )}
      <div style={{ marginTop: 8, fontSize: 11, color: T.muted }}>
        Amounts are shown as Voonix reports them. Downloads include every column and use the filters above.
      </div>
    </div>
  );
}
