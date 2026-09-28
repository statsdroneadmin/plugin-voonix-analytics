/// <reference path="./nousviz_widget_types.d.ts" />
/**
 * VoonixExport — full data export: pick tables, date range, format,
 * optional raw Voonix records, see the row count, download.
 *
 * Talks to:
 *   GET /api/plugins/voonix-analytics/export/options
 *   GET /api/plugins/voonix-analytics/export/estimate?tables&start&end
 *   GET /api/plugins/voonix-analytics/export?format&tables&start&end&include_raw
 *
 * The file is generated on the server, then fetched with the session token
 * (apiFetch) and saved from a Blob — the same pattern as the other plugins'
 * downloads. All hooks are declared before any early return (React #310).
 */

import { useEffect, useMemo, useState } from "react";
import { downloadFile } from "./_voonix_download";

interface FormatOpt { key: string; label: string; ext: string; help: string }
interface TableOpt { table: string; label: string; group: string; default: boolean; dated: boolean }
interface Options { formats: FormatOpt[]; tables: TableOpt[]; max_rows: number }
interface Estimate { tables: { table: string; label: string; rows: number }[]; total: number; max_rows: number; warnings: string[] }

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

export default function VoonixExport(_props: CustomWidgetProps) {
  const [options, setOptions] = useState<Options | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [format, setFormat] = useState("xlsx");
  const [selected, setSelected] = useState<string[]>([]);
  const [range, setRange] = useState<"all" | "12m" | "ytd" | "custom">("all");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [includeRaw, setIncludeRaw] = useState(false);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    window.NousViz.widgets
      .apiFetch(`${API}/export/options`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((o: Options) => {
        if (cancelled) return;
        setOptions(o);
        setSelected(o.tables.filter((t) => t.default).map((t) => t.table));
      })
      .catch((e: Error) => { if (!cancelled) setLoadError(e.message); });
    return () => { cancelled = true; };
  }, []);

  const [effStart, effEnd] = useMemo(() => {
    const now = new Date();
    if (range === "12m") return [iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 11, 1))), iso(now)];
    if (range === "ytd") return [`${now.getUTCFullYear()}-01-01`, iso(now)];
    if (range === "custom") return [start, end];
    return ["", ""];
  }, [range, start, end]);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    p.set("tables", selected.join(","));
    if (effStart) p.set("start", effStart);
    if (effEnd) p.set("end", effEnd);
    return p;
  }, [selected, effStart, effEnd]);

  useEffect(() => {
    if (!options || selected.length === 0) { setEstimate(null); return; }
    let cancelled = false;
    setEstimating(true);
    const t = setTimeout(() => {
      window.NousViz.widgets
        .apiFetch(`${API}/export/estimate?${params.toString()}`)
        .then(async (r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((e: Estimate) => { if (!cancelled) { setEstimate(e); setEstimating(false); } })
        .catch(() => { if (!cancelled) { setEstimate(null); setEstimating(false); } });
    }, 400);
    return () => { cancelled = true; clearTimeout(t); };
  }, [options, params, selected.length]);

  const groups = useMemo(() => {
    const out: { name: string; tables: TableOpt[] }[] = [];
    for (const t of options?.tables || []) {
      let g = out.find((x) => x.name === t.group);
      if (!g) { g = { name: t.group, tables: [] }; out.push(g); }
      g.tables.push(t);
    }
    return out;
  }, [options]);

  function toggle(table: string) {
    setSelected((s) => (s.includes(table) ? s.filter((x) => x !== table) : [...s, table]));
  }

  async function download() {
    if (!options) return;
    setDownloading(true);
    setMessage(null);
    try {
      const p = new URLSearchParams(params);
      p.set("format", format);
      if (includeRaw) p.set("include_raw", "true");
      const ext = options.formats.find((f) => f.key === format)?.ext || "zip";
      await downloadFile(`${API}/export?${p.toString()}`, `voonix-export.${ext}`);
      setMessage({ ok: true, text: "Export downloaded." });
    } catch (e) {
      setMessage({ ok: false, text: `Export failed: ${(e as Error).message}` });
    } finally {
      setDownloading(false);
    }
  }

  const panel: React.CSSProperties = {
    background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, padding: 16, color: T.fg,
  };
  const sectionTitle: React.CSSProperties = {
    fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: T.muted, margin: "16px 0 8px",
  };

  if (loadError) {
    return <div style={panel}><span style={{ color: "#f87171", fontSize: 13 }}>Could not load export options: {loadError}</span></div>;
  }
  if (!options) {
    return <div style={panel}><span style={{ color: T.muted, fontSize: 13 }}>Loading…</span></div>;
  }

  const tooBig = !!estimate && estimate.total > estimate.max_rows;
  const chip = (active: boolean): React.CSSProperties => ({
    padding: "4px 12px", borderRadius: 999, fontSize: 12, cursor: "pointer",
    border: `1px solid ${active ? T.primary : T.border}`,
    background: active ? T.primary : "transparent", color: active ? T.primaryFg : T.fg,
  });

  return (
    <div style={panel}>
      <div style={{ fontWeight: 600, fontSize: 15 }}>Export your Voonix data</div>
      <div style={{ fontSize: 13, color: T.muted, marginTop: 4 }}>
        Download everything this plugin has stored, in the format that suits you.
      </div>

      <div style={sectionTitle}>Format</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
        {options.formats.map((f) => (
          <label key={f.key} style={{
            display: "block", padding: 10, borderRadius: 8, cursor: "pointer",
            border: `1px solid ${format === f.key ? T.primary : T.border}`,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600 }}>
              <input type="radio" name="voonix-export-format" checked={format === f.key} onChange={() => setFormat(f.key)} />
              {f.label}
            </div>
            <div style={{ fontSize: 12, color: T.muted, marginTop: 4 }}>{f.help}</div>
          </label>
        ))}
      </div>

      <div style={sectionTitle}>Tables</div>
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <button type="button" style={chip(false)} onClick={() => setSelected(options.tables.map((t) => t.table))}>Select all</button>
        <button type="button" style={chip(false)} onClick={() => setSelected([])}>Select none</button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 }}>
        {groups.map((g) => (
          <div key={g.name}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{g.name}</div>
            {g.tables.map((t) => {
              const rows = estimate?.tables.find((x) => x.table === t.table)?.rows;
              return (
                <label key={t.table} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, padding: "2px 0" }}>
                  <input type="checkbox" checked={selected.includes(t.table)} onChange={() => toggle(t.table)} />
                  <span>{t.label}</span>
                  <span style={{ color: T.muted, fontSize: 12, marginLeft: "auto" }}>
                    {rows === undefined ? "" : window.NousViz.widgets.formatNumber(rows)}
                  </span>
                </label>
              );
            })}
          </div>
        ))}
      </div>

      <div style={sectionTitle}>Date range (report tables and change log)</div>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
        {([["all", "All history"], ["12m", "Last 12 months"], ["ytd", "This year"], ["custom", "Custom"]] as const).map(([key, label]) => (
          <button key={key} type="button" style={chip(range === key)} onClick={() => setRange(key)}>{label}</button>
        ))}
        {range === "custom" && (
          <>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} style={inputStyle} aria-label="Start date" />
            <span style={{ color: T.muted, fontSize: 12 }}>to</span>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} style={inputStyle} aria-label="End date" />
          </>
        )}
      </div>
      <div style={{ fontSize: 12, color: T.muted, marginTop: 6 }}>Account tables (advertisers, logins, campaigns…) are always exported in full.</div>

      <div style={sectionTitle}>Options</div>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
        <input type="checkbox" checked={includeRaw} onChange={(e) => setIncludeRaw(e.target.checked)} />
        Include raw Voonix records
      </label>
      <div style={{ fontSize: 12, color: T.muted, marginTop: 2, marginLeft: 22 }}>
        Adds the original API response for each row as JSON. Complete, but makes files larger and noisier.
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, marginTop: 18 }}>
        <button type="button" onClick={download}
          disabled={downloading || selected.length === 0 || tooBig}
          style={{
            padding: "8px 18px", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer",
            border: `1px solid ${T.primary}`, background: T.primary, color: T.primaryFg,
            opacity: downloading || selected.length === 0 || tooBig ? 0.6 : 1,
          }}>
          {downloading ? "Preparing export…" : "Download export"}
        </button>
        <span style={{ fontSize: 13, color: T.muted }}>
          {selected.length === 0
            ? "Select at least one table."
            : estimating || !estimate
              ? "Counting rows…"
              : `${window.NousViz.widgets.formatNumber(estimate.total)} rows across ${selected.length} tables`}
        </span>
      </div>
      {downloading && (
        <div style={{ fontSize: 12, color: T.muted, marginTop: 6 }}>
          Large exports can take a few minutes. Keep this tab open.
        </div>
      )}
      {estimate?.warnings.map((w) => (
        <div key={w} style={{ fontSize: 12, color: "#f59e0b", marginTop: 6 }}>{w}</div>
      ))}
      {message && (
        <div style={{ fontSize: 13, marginTop: 8, color: message.ok ? "#34d399" : "#f87171" }}>{message.text}</div>
      )}
    </div>
  );
}
