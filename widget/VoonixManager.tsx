/// <reference path="./nousviz_widget_types.d.ts" />
/**
 * VoonixManager — browse one mirrored Voonix resource and create / edit /
 * delete it in Voonix.
 *
 * Dashboard YAML config:
 *   resource : key in src/voonix_analytics_catalog.py RESOURCES
 *
 * Columns, forms, validation rules and dropdown options all come from
 * GET /api/plugins/voonix-analytics/manage/{resource}/schema, so the form
 * can't offer a field the server would reject. Writes POST to
 * /manage/{resource}/{op}; the server re-validates, requires admin, and
 * refreshes the local copy from Voonix before answering.
 *
 * Hooks are all declared before any early return (React #310).
 */

import { useEffect, useMemo, useState } from "react";

interface Option { value: string; label: string }
interface Field {
  name: string;
  label: string;
  type: "text" | "textarea" | "password" | "number" | "toggle" | "select" | "date" | "month";
  required?: boolean;
  readonly?: boolean;
  help?: string;
  options?: Option[];
  default?: unknown;
  one_of?: string;
  danger?: boolean;
  section?: string;
}
interface Op {
  label: string;
  kind: "create" | "row";
  danger?: boolean;
  confirm?: string;
  fields: Field[];
  prefill?: Record<string, string>;
}
interface Column { key: string; label: string; format: string }
interface Schema { label: string; noun: string; pk: string[]; columns: Column[]; default_sort: string; ops: Record<string, Op> }
interface Config { writes_enabled: boolean; can_write: boolean }
type Row = Record<string, unknown>;

const API = "/api/plugins/voonix-analytics";
const PAGE = 50;
const T = {
  card: "hsl(var(--card))",
  bg: "hsl(var(--background))",
  fg: "hsl(var(--foreground))",
  muted: "hsl(var(--muted-foreground))",
  border: "hsl(var(--border))",
  primary: "hsl(var(--primary))",
  primaryFg: "hsl(var(--primary-foreground))",
  danger: "hsl(var(--destructive, 0 72% 51%))",
};
const inputStyle: React.CSSProperties = {
  width: "100%", height: 34, padding: "0 8px", borderRadius: 6, border: `1px solid ${T.border}`,
  background: T.bg, color: T.fg, fontSize: 13, colorScheme: "light dark", boxSizing: "border-box",
};

function btn(kind: "primary" | "plain" | "danger"): React.CSSProperties {
  return {
    padding: "4px 12px", borderRadius: 6, fontSize: 12, cursor: "pointer",
    border: `1px solid ${kind === "primary" ? T.primary : kind === "danger" ? T.danger : T.border}`,
    background: kind === "primary" ? T.primary : "transparent",
    color: kind === "primary" ? T.primaryFg : kind === "danger" ? T.danger : T.fg,
  };
}

function display(v: unknown, format: string): string {
  if (v === null || v === undefined || v === "") return "—";
  if (format === "bool") return v === true || v === 1 || v === "1" || v === "true" ? "Yes" : "No";
  if (format === "month") return String(v).slice(0, 7);
  if (format === "date") return String(v).slice(0, 10);
  if (format === "int" || format === "number" || format === "money") {
    const n = Number(v);
    if (!Number.isFinite(n)) return String(v);
    return format === "int"
      ? window.NousViz.widgets.formatNumber(Math.round(n))
      : n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(v);
}

function initialValues(op: Op, row: Row | null): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const f of op.fields) {
    const source = row && op.prefill?.[f.name];
    let v: unknown = source ? row[source] : f.default;
    if (f.type === "toggle") v = v === true || v === 1 || v === "1" || v === "true";
    else if (v === null || v === undefined) v = "";
    // Voonix uses 0000-00-00 for "no date"; don't prefill values the server would reject.
    else if (f.type === "month") v = /^[1-9]\d{3}-(0[1-9]|1[0-2])/.test(String(v)) ? String(v).slice(0, 7) : "";
    else if (f.type === "date") v = /^[1-9]\d{3}-\d{2}-\d{2}/.test(String(v)) ? String(v).slice(0, 10) : "";
    else v = String(v);
    values[f.name] = v;
  }
  return values;
}

export default function VoonixManager(props: CustomWidgetProps) {
  const resource = String(props.config.resource || "");

  const [schema, setSchema] = useState<Schema | null>(null);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [sort, setSort] = useState("");
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState<{ opKey: string; op: Op; values: Record<string, unknown> } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      window.NousViz.widgets.apiFetch(`${API}/manage/${encodeURIComponent(resource)}/schema`).then((r) => {
        if (!r.ok) throw new Error(`schema HTTP ${r.status}`);
        return r.json();
      }),
      window.NousViz.widgets.apiFetch(`${API}/config`).then((r) => (r.ok ? r.json() : { writes_enabled: false, can_write: false })),
    ])
      .then(([s, c]: [Schema, Config]) => {
        if (cancelled) return;
        setSchema(s);
        setCfg(c);
        setSort(s.default_sort);
      })
      .catch((e: Error) => { if (!cancelled) setLoadError(e.message); });
    return () => { cancelled = true; };
  }, [resource, reload]);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => { setPage(0); }, [debounced, sort, dir]);

  useEffect(() => {
    if (!schema) return;
    let cancelled = false;
    setLoading(true);
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(page * PAGE), dir });
    if (sort) p.set("sort", sort);
    if (debounced) p.set("search", debounced);
    window.NousViz.widgets
      .apiFetch(`${API}/manage/${encodeURIComponent(resource)}/rows?${p.toString()}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((res: { rows: Row[]; total: number }) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        setLoading(false);
      })
      .catch((e: Error) => { if (!cancelled) { setLoadError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [schema, resource, page, sort, dir, debounced, reload]);

  const opEntries = useMemo(() => Object.entries(schema?.ops || {}), [schema]);
  const createOps = opEntries.filter(([, op]) => op.kind === "create");
  const rowOps = opEntries.filter(([, op]) => op.kind === "row");
  const canWrite = !!cfg?.can_write;

  function openForm(opKey: string, op: Op, row: Row | null) {
    setFormError(null);
    setForm({ opKey, op, values: initialValues(op, row) });
  }

  function setValue(name: string, value: unknown) {
    setForm((f) => (f ? { ...f, values: { ...f.values, [name]: value } } : f));
  }

  async function submit() {
    if (!form) return;
    let confirm = false;
    if (form.op.danger) {
      const typed = window.prompt(`${form.op.confirm || "This cannot be undone."}\n\nType DELETE to confirm.`);
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
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ row: form.values, confirm }) },
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
      setFormError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const panel: React.CSSProperties = {
    background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, padding: 16, color: T.fg,
  };

  if (loadError && !schema) {
    return <div style={panel}><span style={{ color: "#f87171", fontSize: 13 }}>Could not load: {loadError}</span></div>;
  }
  if (!schema || !cfg) {
    return <div style={panel}><span style={{ color: T.muted, fontSize: 13 }}>Loading…</span></div>;
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE));
  const th: React.CSSProperties = {
    padding: "8px 10px", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", color: T.muted,
    borderBottom: `1px solid ${T.border}`, whiteSpace: "nowrap", textAlign: "left", cursor: "pointer", userSelect: "none",
  };
  const td: React.CSSProperties = { padding: "7px 10px", borderBottom: `1px solid ${T.border}`, whiteSpace: "nowrap", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" };

  const sections: { title: string; fields: Field[] }[] = [];
  if (form) {
    for (const f of form.op.fields) {
      const title = f.section || "";
      let s = sections.find((x) => x.title === title);
      if (!s) { s = { title, fields: [] }; sections.push(s); }
      s.fields.push(f);
    }
  }

  return (
    <div style={panel}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{schema.label}</div>
        <span style={{ color: T.muted, fontSize: 12 }}>{window.NousViz.widgets.formatNumber(total)}</span>
        <input type="search" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)}
          style={{ ...inputStyle, width: 220, marginLeft: "auto" }} />
        {canWrite && createOps.map(([key, op]) => (
          <button key={key} type="button" style={btn("primary")} onClick={() => openForm(key, op, null)}>{op.label}</button>
        ))}
      </div>

      {opEntries.length > 0 && !canWrite && (
        <div style={{ fontSize: 12, color: T.muted, marginBottom: 8 }}>
          {cfg.writes_enabled
            ? "Only admins can change data in Voonix."
            : "Changes to Voonix are switched off (Settings → Allow changes in Voonix)."}
        </div>
      )}
      {notice && (
        <div style={{ fontSize: 12, marginBottom: 8, color: notice.ok ? "#34d399" : "#f87171" }}>
          {notice.text} <button type="button" style={{ ...btn("plain"), padding: "0 6px", marginLeft: 6 }} onClick={() => setNotice(null)}>×</button>
        </div>
      )}

      {total === 0 && !loading ? (
        <div style={{ color: T.muted, fontSize: 13, padding: "16px 0" }}>
          {debounced ? "Nothing matches that search." : "Nothing here yet — run a sync."}
        </div>
      ) : (
        <div style={{ overflowX: "auto", opacity: loading ? 0.6 : 1 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                {schema.columns.map((c) => (
                  <th key={c.key} style={th} onClick={() => {
                    if (sort === c.key) setDir((d) => (d === "asc" ? "desc" : "asc"));
                    else { setSort(c.key); setDir("asc"); }
                  }}>
                    {c.label}{sort === c.key ? (dir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                ))}
                {canWrite && rowOps.length > 0 && <th style={{ ...th, cursor: "default" }} />}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={schema.pk.map((k) => String(row[k])).join("|") || i}>
                  {schema.columns.map((c) => (
                    <td key={c.key} style={{ ...td, textAlign: ["int", "number", "money"].includes(c.format) ? "right" : "left" }}
                      title={row[c.key] === null || row[c.key] === undefined ? "" : String(row[c.key])}>
                      {display(row[c.key], c.format)}
                    </td>
                  ))}
                  {canWrite && rowOps.length > 0 && (
                    <td style={{ ...td, textAlign: "right" }}>
                      {rowOps.map(([key, op]) => (
                        <button key={key} type="button" style={{ ...btn(op.danger ? "danger" : "plain"), marginLeft: 4 }}
                          onClick={() => openForm(key, op, row)}>
                          {op.label}
                        </button>
                      ))}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10, fontSize: 12, color: T.muted }}>
          <span>Page {page + 1} of {totalPages}</span>
          <div style={{ display: "flex", gap: 6 }}>
            <button type="button" style={btn("plain")} disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>Prev</button>
            <button type="button" style={btn("plain")} disabled={page >= totalPages - 1} onClick={() => setPage((p) => p + 1)}>Next</button>
          </div>
        </div>
      )}

      {form && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000, display: "flex", alignItems: "flex-start", justifyContent: "center", overflowY: "auto", padding: "40px 16px" }}
          onClick={() => !submitting && setForm(null)}>
          <div style={{ ...panel, width: "100%", maxWidth: 640 }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 15 }}>{form.op.label} — {schema.noun}</div>
              <button type="button" style={{ ...btn("plain"), marginLeft: "auto" }} onClick={() => setForm(null)} disabled={submitting}>Close</button>
            </div>
            {form.op.danger && (
              <div style={{ fontSize: 13, color: T.danger, marginBottom: 12 }}>
                {form.op.confirm || "This cannot be undone."} This changes your live Voonix account.
              </div>
            )}
            {sections.map((s) => (
              <div key={s.title || "_main"} style={{ marginBottom: 12 }}>
                {s.title && <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: T.muted, margin: "8px 0" }}>{s.title}</div>}
                <div style={{ display: "grid", gridTemplateColumns: s.title ? "repeat(auto-fill, minmax(140px, 1fr))" : "1fr", gap: 10 }}>
                  {s.fields.map((f) => {
                    const v = form.values[f.name];
                    const label = (
                      <div style={{ fontSize: 12, marginBottom: 3, color: f.danger ? T.danger : T.fg }}>
                        {f.label}{f.required ? " *" : ""}{f.one_of ? " (one of)" : ""}
                      </div>
                    );
                    let control: JSX.Element;
                    if (f.type === "toggle") {
                      control = (
                        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                          <input type="checkbox" checked={v === true} disabled={f.readonly} onChange={(e) => setValue(f.name, e.target.checked)} />
                          {f.label}
                        </label>
                      );
                    } else if (f.type === "select" && (f.options?.length || 0) > 0) {
                      control = (
                        <select style={inputStyle} value={String(v ?? "")} disabled={f.readonly} onChange={(e) => setValue(f.name, e.target.value)}>
                          <option value="">—</option>
                          {f.options!.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                      );
                    } else if (f.type === "textarea") {
                      control = (
                        <textarea style={{ ...inputStyle, height: 64, padding: 8 }} value={String(v ?? "")} disabled={f.readonly}
                          onChange={(e) => setValue(f.name, e.target.value)} />
                      );
                    } else {
                      const htmlType = f.type === "password" ? "password" : f.type === "number" ? "number" : f.type === "date" ? "date" : f.type === "month" ? "month" : "text";
                      control = (
                        <input style={inputStyle} type={htmlType} value={String(v ?? "")} disabled={f.readonly}
                          autoComplete={f.type === "password" ? "new-password" : "off"} step={f.type === "number" ? "any" : undefined}
                          onChange={(e) => setValue(f.name, e.target.value)} />
                      );
                    }
                    return (
                      <div key={f.name}>
                        {f.type !== "toggle" && label}
                        {control}
                        {f.help && <div style={{ fontSize: 11, color: f.danger ? T.danger : T.muted, marginTop: 3 }}>{f.help}</div>}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
            {formError && <div style={{ color: "#f87171", fontSize: 13, marginBottom: 10, whiteSpace: "pre-wrap" }}>{formError}</div>}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button type="button" style={btn("plain")} onClick={() => setForm(null)} disabled={submitting}>Cancel</button>
              <button type="button" style={btn(form.op.danger ? "danger" : "primary")} onClick={submit} disabled={submitting}>
                {submitting ? "Sending to Voonix…" : form.op.danger ? form.op.label : "Save to Voonix"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
