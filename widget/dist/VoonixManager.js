// VoonixManager.tsx
import { useEffect, useMemo, useState } from "/api/widget-runtime/react.js";
import { jsx, jsxs } from "/api/widget-runtime/react-jsx-runtime.js";
var API = "/api/plugins/voonix-analytics";
var PAGE = 50;
var T = {
  card: "hsl(var(--card))",
  bg: "hsl(var(--background))",
  fg: "hsl(var(--foreground))",
  muted: "hsl(var(--muted-foreground))",
  border: "hsl(var(--border))",
  primary: "hsl(var(--primary))",
  primaryFg: "hsl(var(--primary-foreground))",
  danger: "hsl(var(--destructive, 0 72% 51%))"
};
var inputStyle = {
  width: "100%",
  height: 34,
  padding: "0 8px",
  borderRadius: 6,
  border: `1px solid ${T.border}`,
  background: T.bg,
  color: T.fg,
  fontSize: 13,
  colorScheme: "light dark",
  boxSizing: "border-box"
};
function btn(kind) {
  return {
    padding: "4px 12px",
    borderRadius: 6,
    fontSize: 12,
    cursor: "pointer",
    border: `1px solid ${kind === "primary" ? T.primary : kind === "danger" ? T.danger : T.border}`,
    background: kind === "primary" ? T.primary : "transparent",
    color: kind === "primary" ? T.primaryFg : kind === "danger" ? T.danger : T.fg
  };
}
function display(v, format) {
  if (v === null || v === void 0 || v === "") return "\u2014";
  if (format === "bool") return v === true || v === 1 || v === "1" || v === "true" ? "Yes" : "No";
  if (format === "month") return String(v).slice(0, 7);
  if (format === "date") return String(v).slice(0, 10);
  if (format === "int" || format === "number" || format === "money") {
    const n = Number(v);
    if (!Number.isFinite(n)) return String(v);
    return format === "int" ? window.NousViz.widgets.formatNumber(Math.round(n)) : n.toLocaleString(void 0, { maximumFractionDigits: 2 });
  }
  return String(v);
}
function initialValues(op, row) {
  const values = {};
  for (const f of op.fields) {
    const source = row && op.prefill?.[f.name];
    let v = source ? row[source] : f.default;
    if (f.type === "toggle") v = v === true || v === 1 || v === "1" || v === "true";
    else if (v === null || v === void 0) v = "";
    else if (f.type === "month") v = /^[1-9]\d{3}-(0[1-9]|1[0-2])/.test(String(v)) ? String(v).slice(0, 7) : "";
    else if (f.type === "date") v = /^[1-9]\d{3}-\d{2}-\d{2}/.test(String(v)) ? String(v).slice(0, 10) : "";
    else v = String(v);
    values[f.name] = v;
  }
  return values;
}
function VoonixManager(props) {
  const resource = String(props.config.resource || "");
  const [schema, setSchema] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [sort, setSort] = useState("");
  const [dir, setDir] = useState("asc");
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);
  const [notice, setNotice] = useState(null);
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      window.NousViz.widgets.apiFetch(`${API}/manage/${encodeURIComponent(resource)}/schema`).then((r) => {
        if (!r.ok) throw new Error(`schema HTTP ${r.status}`);
        return r.json();
      }),
      window.NousViz.widgets.apiFetch(`${API}/config`).then((r) => r.ok ? r.json() : { writes_enabled: false, can_write: false })
    ]).then(([s, c]) => {
      if (cancelled) return;
      setSchema(s);
      setCfg(c);
      setSort(s.default_sort);
    }).catch((e) => {
      if (!cancelled) setLoadError(e.message);
    });
    return () => {
      cancelled = true;
    };
  }, [resource, reload]);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => {
    setPage(0);
  }, [debounced, sort, dir]);
  useEffect(() => {
    if (!schema) return;
    let cancelled = false;
    setLoading(true);
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(page * PAGE), dir });
    if (sort) p.set("sort", sort);
    if (debounced) p.set("search", debounced);
    window.NousViz.widgets.apiFetch(`${API}/manage/${encodeURIComponent(resource)}/rows?${p.toString()}`).then(async (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    }).then((res) => {
      if (cancelled) return;
      setRows(res.rows);
      setTotal(res.total);
      setLoading(false);
    }).catch((e) => {
      if (!cancelled) {
        setLoadError(e.message);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [schema, resource, page, sort, dir, debounced, reload]);
  const opEntries = useMemo(() => Object.entries(schema?.ops || {}), [schema]);
  const createOps = opEntries.filter(([, op]) => op.kind === "create");
  const rowOps = opEntries.filter(([, op]) => op.kind === "row");
  const canWrite = !!cfg?.can_write;
  function openForm(opKey, op, row) {
    setFormError(null);
    setForm({ opKey, op, values: initialValues(op, row) });
  }
  function setValue(name, value) {
    setForm((f) => f ? { ...f, values: { ...f.values, [name]: value } } : f);
  }
  async function submit() {
    if (!form) return;
    let confirm = false;
    if (form.op.danger) {
      const typed = window.prompt(`${form.op.confirm || "This cannot be undone."}

Type DELETE to confirm.`);
      if (typed !== "DELETE") return;
      confirm = true;
    }
    if (form.values.resume_import === true) {
      const danger = form.op.fields.find((f) => f.name === "resume_import");
      if (!window.confirm(danger?.help || "Resume import?")) return;
      confirm = true;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const r = await window.NousViz.widgets.apiFetch(
        `${API}/manage/${encodeURIComponent(resource)}/${encodeURIComponent(form.opKey)}`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ row: form.values, confirm }) }
      );
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setFormError(String(data.detail || `HTTP ${r.status}`));
        return;
      }
      if (!data.ok) {
        const reasons = Array.isArray(data.failed) && data.failed.length ? ` ${JSON.stringify(data.failed).slice(0, 400)}` : "";
        setFormError(`${data.toast || data.error || "Voonix rejected the change."}${reasons}`);
        return;
      }
      setForm(null);
      setNotice({ ok: true, text: data.toast || "Saved." });
      setReload((n) => n + 1);
    } catch (e) {
      setFormError(e.message);
    } finally {
      setSubmitting(false);
    }
  }
  const panel = {
    background: T.card,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    padding: 16,
    color: T.fg
  };
  if (loadError && !schema) {
    return /* @__PURE__ */ jsx("div", { style: panel, children: /* @__PURE__ */ jsxs("span", { style: { color: "#f87171", fontSize: 13 }, children: [
      "Could not load: ",
      loadError
    ] }) });
  }
  if (!schema || !cfg) {
    return /* @__PURE__ */ jsx("div", { style: panel, children: /* @__PURE__ */ jsx("span", { style: { color: T.muted, fontSize: 13 }, children: "Loading\u2026" }) });
  }
  const totalPages = Math.max(1, Math.ceil(total / PAGE));
  const th = {
    padding: "8px 10px",
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    color: T.muted,
    borderBottom: `1px solid ${T.border}`,
    whiteSpace: "nowrap",
    textAlign: "left",
    cursor: "pointer",
    userSelect: "none"
  };
  const td = { padding: "7px 10px", borderBottom: `1px solid ${T.border}`, whiteSpace: "nowrap", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" };
  const sections = [];
  if (form) {
    for (const f of form.op.fields) {
      const title = f.section || "";
      let s = sections.find((x) => x.title === title);
      if (!s) {
        s = { title, fields: [] };
        sections.push(s);
      }
      s.fields.push(f);
    }
  }
  return /* @__PURE__ */ jsxs("div", { style: panel, children: [
    /* @__PURE__ */ jsxs("div", { style: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 10 }, children: [
      /* @__PURE__ */ jsx("div", { style: { fontWeight: 600, fontSize: 14 }, children: schema.label }),
      /* @__PURE__ */ jsx("span", { style: { color: T.muted, fontSize: 12 }, children: window.NousViz.widgets.formatNumber(total) }),
      /* @__PURE__ */ jsx(
        "input",
        {
          type: "search",
          placeholder: "Search\u2026",
          value: search,
          onChange: (e) => setSearch(e.target.value),
          style: { ...inputStyle, width: 220, marginLeft: "auto" }
        }
      ),
      canWrite && createOps.map(([key, op]) => /* @__PURE__ */ jsx("button", { type: "button", style: btn("primary"), onClick: () => openForm(key, op, null), children: op.label }, key))
    ] }),
    opEntries.length > 0 && !canWrite && /* @__PURE__ */ jsx("div", { style: { fontSize: 12, color: T.muted, marginBottom: 8 }, children: cfg.writes_enabled ? "Only admins can change data in Voonix." : "Changes to Voonix are switched off (Settings \u2192 Allow changes in Voonix)." }),
    notice && /* @__PURE__ */ jsxs("div", { style: { fontSize: 12, marginBottom: 8, color: notice.ok ? "#34d399" : "#f87171" }, children: [
      notice.text,
      " ",
      /* @__PURE__ */ jsx("button", { type: "button", style: { ...btn("plain"), padding: "0 6px", marginLeft: 6 }, onClick: () => setNotice(null), children: "\xD7" })
    ] }),
    total === 0 && !loading ? /* @__PURE__ */ jsx("div", { style: { color: T.muted, fontSize: 13, padding: "16px 0" }, children: debounced ? "Nothing matches that search." : "Nothing here yet \u2014 run a sync." }) : /* @__PURE__ */ jsx("div", { style: { overflowX: "auto", opacity: loading ? 0.6 : 1 }, children: /* @__PURE__ */ jsxs("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 13 }, children: [
      /* @__PURE__ */ jsx("thead", { children: /* @__PURE__ */ jsxs("tr", { children: [
        schema.columns.map((c) => /* @__PURE__ */ jsxs("th", { style: th, onClick: () => {
          if (sort === c.key) setDir((d) => d === "asc" ? "desc" : "asc");
          else {
            setSort(c.key);
            setDir("asc");
          }
        }, children: [
          c.label,
          sort === c.key ? dir === "asc" ? " \u2191" : " \u2193" : ""
        ] }, c.key)),
        canWrite && rowOps.length > 0 && /* @__PURE__ */ jsx("th", { style: { ...th, cursor: "default" } })
      ] }) }),
      /* @__PURE__ */ jsx("tbody", { children: rows.map((row, i) => /* @__PURE__ */ jsxs("tr", { children: [
        schema.columns.map((c) => /* @__PURE__ */ jsx(
          "td",
          {
            style: { ...td, textAlign: ["int", "number", "money"].includes(c.format) ? "right" : "left" },
            title: row[c.key] === null || row[c.key] === void 0 ? "" : String(row[c.key]),
            children: display(row[c.key], c.format)
          },
          c.key
        )),
        canWrite && rowOps.length > 0 && /* @__PURE__ */ jsx("td", { style: { ...td, textAlign: "right" }, children: rowOps.map(([key, op]) => /* @__PURE__ */ jsx(
          "button",
          {
            type: "button",
            style: { ...btn(op.danger ? "danger" : "plain"), marginLeft: 4 },
            onClick: () => openForm(key, op, row),
            children: op.label
          },
          key
        )) })
      ] }, schema.pk.map((k) => String(row[k])).join("|") || i)) })
    ] }) }),
    totalPages > 1 && /* @__PURE__ */ jsxs("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10, fontSize: 12, color: T.muted }, children: [
      /* @__PURE__ */ jsxs("span", { children: [
        "Page ",
        page + 1,
        " of ",
        totalPages
      ] }),
      /* @__PURE__ */ jsxs("div", { style: { display: "flex", gap: 6 }, children: [
        /* @__PURE__ */ jsx("button", { type: "button", style: btn("plain"), disabled: page === 0, onClick: () => setPage((p) => Math.max(0, p - 1)), children: "Prev" }),
        /* @__PURE__ */ jsx("button", { type: "button", style: btn("plain"), disabled: page >= totalPages - 1, onClick: () => setPage((p) => p + 1), children: "Next" })
      ] })
    ] }),
    form && /* @__PURE__ */ jsx(
      "div",
      {
        style: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1e3, display: "flex", alignItems: "flex-start", justifyContent: "center", overflowY: "auto", padding: "40px 16px" },
        onClick: () => !submitting && setForm(null),
        children: /* @__PURE__ */ jsxs("div", { style: { ...panel, width: "100%", maxWidth: 640 }, onClick: (e) => e.stopPropagation(), children: [
          /* @__PURE__ */ jsxs("div", { style: { display: "flex", alignItems: "center", marginBottom: 12 }, children: [
            /* @__PURE__ */ jsxs("div", { style: { fontWeight: 600, fontSize: 15 }, children: [
              form.op.label,
              " \u2014 ",
              schema.noun
            ] }),
            /* @__PURE__ */ jsx("button", { type: "button", style: { ...btn("plain"), marginLeft: "auto" }, onClick: () => setForm(null), disabled: submitting, children: "Close" })
          ] }),
          form.op.danger && /* @__PURE__ */ jsxs("div", { style: { fontSize: 13, color: T.danger, marginBottom: 12 }, children: [
            form.op.confirm || "This cannot be undone.",
            " This changes your live Voonix account."
          ] }),
          sections.map((s) => /* @__PURE__ */ jsxs("div", { style: { marginBottom: 12 }, children: [
            s.title && /* @__PURE__ */ jsx("div", { style: { fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: T.muted, margin: "8px 0" }, children: s.title }),
            /* @__PURE__ */ jsx("div", { style: { display: "grid", gridTemplateColumns: s.title ? "repeat(auto-fill, minmax(140px, 1fr))" : "1fr", gap: 10 }, children: s.fields.map((f) => {
              const v = form.values[f.name];
              const label = /* @__PURE__ */ jsxs("div", { style: { fontSize: 12, marginBottom: 3, color: f.danger ? T.danger : T.fg }, children: [
                f.label,
                f.required ? " *" : "",
                f.one_of ? " (one of)" : ""
              ] });
              let control;
              if (f.type === "toggle") {
                control = /* @__PURE__ */ jsxs("label", { style: { display: "flex", alignItems: "center", gap: 8, fontSize: 13 }, children: [
                  /* @__PURE__ */ jsx("input", { type: "checkbox", checked: v === true, disabled: f.readonly, onChange: (e) => setValue(f.name, e.target.checked) }),
                  f.label
                ] });
              } else if (f.type === "select" && (f.options?.length || 0) > 0) {
                control = /* @__PURE__ */ jsxs("select", { style: inputStyle, value: String(v ?? ""), disabled: f.readonly, onChange: (e) => setValue(f.name, e.target.value), children: [
                  /* @__PURE__ */ jsx("option", { value: "", children: "\u2014" }),
                  f.options.map((o) => /* @__PURE__ */ jsx("option", { value: o.value, children: o.label }, o.value))
                ] });
              } else if (f.type === "textarea") {
                control = /* @__PURE__ */ jsx(
                  "textarea",
                  {
                    style: { ...inputStyle, height: 64, padding: 8 },
                    value: String(v ?? ""),
                    disabled: f.readonly,
                    onChange: (e) => setValue(f.name, e.target.value)
                  }
                );
              } else {
                const htmlType = f.type === "password" ? "password" : f.type === "number" ? "number" : f.type === "date" ? "date" : f.type === "month" ? "month" : "text";
                control = /* @__PURE__ */ jsx(
                  "input",
                  {
                    style: inputStyle,
                    type: htmlType,
                    value: String(v ?? ""),
                    disabled: f.readonly,
                    autoComplete: f.type === "password" ? "new-password" : "off",
                    step: f.type === "number" ? "any" : void 0,
                    onChange: (e) => setValue(f.name, e.target.value)
                  }
                );
              }
              return /* @__PURE__ */ jsxs("div", { children: [
                f.type !== "toggle" && label,
                control,
                f.help && /* @__PURE__ */ jsx("div", { style: { fontSize: 11, color: f.danger ? T.danger : T.muted, marginTop: 3 }, children: f.help })
              ] }, f.name);
            }) })
          ] }, s.title || "_main")),
          formError && /* @__PURE__ */ jsx("div", { style: { color: "#f87171", fontSize: 13, marginBottom: 10, whiteSpace: "pre-wrap" }, children: formError }),
          /* @__PURE__ */ jsxs("div", { style: { display: "flex", justifyContent: "flex-end", gap: 8 }, children: [
            /* @__PURE__ */ jsx("button", { type: "button", style: btn("plain"), onClick: () => setForm(null), disabled: submitting, children: "Cancel" }),
            /* @__PURE__ */ jsx("button", { type: "button", style: btn(form.op.danger ? "danger" : "primary"), onClick: submit, disabled: submitting, children: submitting ? "Sending to Voonix\u2026" : form.op.danger ? form.op.label : "Save to Voonix" })
          ] })
        ] })
      }
    )
  ] });
}
export {
  VoonixManager as default
};
