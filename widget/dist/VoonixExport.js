// VoonixExport.tsx
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

// VoonixExport.tsx
import { Fragment, jsx, jsxs } from "/api/widget-runtime/react-jsx-runtime.js";
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
function VoonixExport(_props) {
  const [options, setOptions] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [format, setFormat] = useState("xlsx");
  const [selected, setSelected] = useState([]);
  const [range, setRange] = useState("all");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [includeRaw, setIncludeRaw] = useState(false);
  const [estimate, setEstimate] = useState(null);
  const [estimating, setEstimating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [message, setMessage] = useState(null);
  useEffect(() => {
    let cancelled = false;
    window.NousViz.widgets.apiFetch(`${API}/export/options`).then(async (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }).then((o) => {
      if (cancelled) return;
      setOptions(o);
      setSelected(o.tables.filter((t) => t.default).map((t) => t.table));
    }).catch((e) => {
      if (!cancelled) setLoadError(e.message);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const [effStart, effEnd] = useMemo(() => {
    const now = /* @__PURE__ */ new Date();
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
    if (!options || selected.length === 0) {
      setEstimate(null);
      return;
    }
    let cancelled = false;
    setEstimating(true);
    const t = setTimeout(() => {
      window.NousViz.widgets.apiFetch(`${API}/export/estimate?${params.toString()}`).then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      }).then((e) => {
        if (!cancelled) {
          setEstimate(e);
          setEstimating(false);
        }
      }).catch(() => {
        if (!cancelled) {
          setEstimate(null);
          setEstimating(false);
        }
      });
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [options, params, selected.length]);
  const groups = useMemo(() => {
    const out = [];
    for (const t of options?.tables || []) {
      let g = out.find((x) => x.name === t.group);
      if (!g) {
        g = { name: t.group, tables: [] };
        out.push(g);
      }
      g.tables.push(t);
    }
    return out;
  }, [options]);
  function toggle(table) {
    setSelected((s) => s.includes(table) ? s.filter((x) => x !== table) : [...s, table]);
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
      setMessage({ ok: false, text: `Export failed: ${e.message}` });
    } finally {
      setDownloading(false);
    }
  }
  const panel = {
    background: T.card,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: 16,
    color: T.fg
  };
  const sectionTitle = {
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    color: T.muted,
    margin: "16px 0 8px"
  };
  if (loadError) {
    return /* @__PURE__ */ jsx("div", { style: panel, children: /* @__PURE__ */ jsxs("span", { style: { color: "#f87171", fontSize: 13 }, children: [
      "Could not load export options: ",
      loadError
    ] }) });
  }
  if (!options) {
    return /* @__PURE__ */ jsx("div", { style: panel, children: /* @__PURE__ */ jsx("span", { style: { color: T.muted, fontSize: 13 }, children: "Loading\u2026" }) });
  }
  const tooBig = !!estimate && estimate.total > estimate.max_rows;
  const chip = (active) => ({
    padding: "4px 12px",
    borderRadius: 999,
    fontSize: 12,
    cursor: "pointer",
    border: `1px solid ${active ? T.primary : T.border}`,
    background: active ? T.primary : "transparent",
    color: active ? T.primaryFg : T.fg
  });
  return /* @__PURE__ */ jsxs("div", { style: panel, children: [
    /* @__PURE__ */ jsx("div", { style: { fontWeight: 600, fontSize: 15 }, children: "Export your Voonix data" }),
    /* @__PURE__ */ jsx("div", { style: { fontSize: 13, color: T.muted, marginTop: 4 }, children: "Download everything this plugin has stored, in the format that suits you." }),
    /* @__PURE__ */ jsx("div", { style: sectionTitle, children: "Format" }),
    /* @__PURE__ */ jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }, children: options.formats.map((f) => /* @__PURE__ */ jsxs("label", { style: {
      display: "block",
      padding: 10,
      borderRadius: 8,
      cursor: "pointer",
      border: `1px solid ${format === f.key ? T.primary : T.border}`
    }, children: [
      /* @__PURE__ */ jsxs("div", { style: { display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600 }, children: [
        /* @__PURE__ */ jsx("input", { type: "radio", name: "voonix-export-format", checked: format === f.key, onChange: () => setFormat(f.key) }),
        f.label
      ] }),
      /* @__PURE__ */ jsx("div", { style: { fontSize: 12, color: T.muted, marginTop: 4 }, children: f.help })
    ] }, f.key)) }),
    /* @__PURE__ */ jsx("div", { style: sectionTitle, children: "Tables" }),
    /* @__PURE__ */ jsxs("div", { style: { display: "flex", gap: 6, marginBottom: 8 }, children: [
      /* @__PURE__ */ jsx("button", { type: "button", style: chip(false), onClick: () => setSelected(options.tables.map((t) => t.table)), children: "Select all" }),
      /* @__PURE__ */ jsx("button", { type: "button", style: chip(false), onClick: () => setSelected([]), children: "Select none" })
    ] }),
    /* @__PURE__ */ jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 }, children: groups.map((g) => /* @__PURE__ */ jsxs("div", { children: [
      /* @__PURE__ */ jsx("div", { style: { fontSize: 12, fontWeight: 600, marginBottom: 4 }, children: g.name }),
      g.tables.map((t) => {
        const rows = estimate?.tables.find((x) => x.table === t.table)?.rows;
        return /* @__PURE__ */ jsxs("label", { style: { display: "flex", alignItems: "center", gap: 8, fontSize: 13, padding: "2px 0" }, children: [
          /* @__PURE__ */ jsx("input", { type: "checkbox", checked: selected.includes(t.table), onChange: () => toggle(t.table) }),
          /* @__PURE__ */ jsx("span", { children: t.label }),
          /* @__PURE__ */ jsx("span", { style: { color: T.muted, fontSize: 12, marginLeft: "auto" }, children: rows === void 0 ? "" : window.NousViz.widgets.formatNumber(rows) })
        ] }, t.table);
      })
    ] }, g.name)) }),
    /* @__PURE__ */ jsx("div", { style: sectionTitle, children: "Date range (report tables and change log)" }),
    /* @__PURE__ */ jsxs("div", { style: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }, children: [
      [["all", "All history"], ["12m", "Last 12 months"], ["ytd", "This year"], ["custom", "Custom"]].map(([key, label]) => /* @__PURE__ */ jsx("button", { type: "button", style: chip(range === key), onClick: () => setRange(key), children: label }, key)),
      range === "custom" && /* @__PURE__ */ jsxs(Fragment, { children: [
        /* @__PURE__ */ jsx("input", { type: "date", value: start, onChange: (e) => setStart(e.target.value), style: inputStyle, "aria-label": "Start date" }),
        /* @__PURE__ */ jsx("span", { style: { color: T.muted, fontSize: 12 }, children: "to" }),
        /* @__PURE__ */ jsx("input", { type: "date", value: end, onChange: (e) => setEnd(e.target.value), style: inputStyle, "aria-label": "End date" })
      ] })
    ] }),
    /* @__PURE__ */ jsx("div", { style: { fontSize: 12, color: T.muted, marginTop: 6 }, children: "Account tables (advertisers, logins, campaigns\u2026) are always exported in full." }),
    /* @__PURE__ */ jsx("div", { style: sectionTitle, children: "Options" }),
    /* @__PURE__ */ jsxs("label", { style: { display: "flex", alignItems: "center", gap: 8, fontSize: 13 }, children: [
      /* @__PURE__ */ jsx("input", { type: "checkbox", checked: includeRaw, onChange: (e) => setIncludeRaw(e.target.checked) }),
      "Include raw Voonix records"
    ] }),
    /* @__PURE__ */ jsx("div", { style: { fontSize: 12, color: T.muted, marginTop: 2, marginLeft: 22 }, children: "Adds the original API response for each row as JSON. Complete, but makes files larger and noisier." }),
    /* @__PURE__ */ jsxs("div", { style: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, marginTop: 18 }, children: [
      /* @__PURE__ */ jsx(
        "button",
        {
          type: "button",
          onClick: download,
          disabled: downloading || selected.length === 0 || tooBig,
          style: {
            padding: "8px 18px",
            borderRadius: 6,
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            border: `1px solid ${T.primary}`,
            background: T.primary,
            color: T.primaryFg,
            opacity: downloading || selected.length === 0 || tooBig ? 0.6 : 1
          },
          children: downloading ? "Preparing export\u2026" : "Download export"
        }
      ),
      /* @__PURE__ */ jsx("span", { style: { fontSize: 13, color: T.muted }, children: selected.length === 0 ? "Select at least one table." : estimating || !estimate ? "Counting rows\u2026" : `${window.NousViz.widgets.formatNumber(estimate.total)} rows across ${selected.length} tables` })
    ] }),
    downloading && /* @__PURE__ */ jsx("div", { style: { fontSize: 12, color: T.muted, marginTop: 6 }, children: "Large exports can take a few minutes. Keep this tab open." }),
    estimate?.warnings.map((w) => /* @__PURE__ */ jsx("div", { style: { fontSize: 12, color: "#f59e0b", marginTop: 6 }, children: w }, w)),
    message && /* @__PURE__ */ jsx("div", { style: { fontSize: 13, marginTop: 8, color: message.ok ? "#34d399" : "#f87171" }, children: message.text })
  ] });
}
export {
  VoonixExport as default
};
