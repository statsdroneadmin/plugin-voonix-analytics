"""
src/voonix_analytics_export.py — data export writers for the Export tab
and the per-report download buttons.

Full-dump formats: CSV (zip), JSON Lines (zip), Excel (.xlsx), SQLite,
PostgreSQL SQL dump (zip). Report formats: CSV, Excel, JSON.

Standard library only — no NousViz plugin ships openpyxl or pyarrow, so the
.xlsx is written as SpreadsheetML by hand and zipped with zipfile.

Writers consume rows lazily, one table at a time, and write to a file on
disk, so a large dump never has to fit in the API process's memory.

Column order, types and primary keys come from this plugin's own migration
files (load_schema), so exports can't drift from the database.

No SDK imports — tests/ run this under plain Python.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import sqlite3
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape as _xml_escape


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "storage" / "migrations"

FORMATS: dict[str, dict[str, str]] = {
    "xlsx": {"label": "Excel workbook (.xlsx)", "ext": "xlsx",
             "media": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "help": "One sheet per table. Tables over ~1M rows continue on extra sheets."},
    "csv": {"label": "CSV files (.zip)", "ext": "zip", "media": "application/zip",
            "help": "One CSV per table. Opens in Excel, Google Sheets and most BI tools."},
    "sqlite": {"label": "SQLite database (.sqlite)", "ext": "sqlite", "media": "application/vnd.sqlite3",
               "help": "Every table in one queryable file (DB Browser for SQLite, DBeaver, Python)."},
    "sql": {"label": "PostgreSQL SQL dump (.zip)", "ext": "zip", "media": "application/zip",
            "help": "CREATE TABLE + INSERT statements. Load into an empty PostgreSQL database with psql."},
    "jsonl": {"label": "JSON Lines (.zip)", "ext": "zip", "media": "application/zip",
              "help": "One .jsonl per table, one JSON object per line. For scripts and data pipelines."},
}

REPORT_FORMATS: dict[str, dict[str, str]] = {
    "xlsx": FORMATS["xlsx"],
    "csv": {"label": "CSV", "ext": "csv", "media": "text/csv"},
    "json": {"label": "JSON", "ext": "json", "media": "application/json"},
}

# Export order and grouping. `raw_cols` are dropped unless "include raw" is on.
EXPORT_TABLES: list[dict[str, Any]] = [
    {"table": "voonix_advertiser_earnings", "label": "Advertiser earnings", "group": "Reports", "date_col": "date", "raw_cols": ["raw"], "default": True},
    {"table": "voonix_site_earnings", "label": "Site earnings", "group": "Reports", "date_col": "date", "raw_cols": ["raw"], "default": True},
    {"table": "voonix_invoice_earnings", "label": "Invoiceable earnings", "group": "Reports", "date_col": "date", "raw_cols": ["raw"], "default": True},
    {"table": "voonix_payouts", "label": "Payouts", "group": "Reports", "date_col": "period_month", "month": True, "raw_cols": ["raw"], "default": True},
    {"table": "voonix_custom_stats", "label": "Custom stats", "group": "Reports", "date_col": "date", "raw_cols": ["raw"], "default": True},
    {"table": "voonix_datamonitor", "label": "Datamonitor issues", "group": "Reports", "date_col": "date", "raw_cols": [], "default": True},
    {"table": "voonix_advertisers", "label": "Advertisers", "group": "Accounts", "raw_cols": ["raw"], "default": True},
    {"table": "voonix_logins", "label": "Logins", "group": "Accounts", "raw_cols": ["raw"], "default": True},
    {"table": "voonix_login_history_deals", "label": "History deals", "group": "Accounts", "raw_cols": [], "default": True},
    {"table": "voonix_campaigns", "label": "Campaigns", "group": "Accounts", "raw_cols": ["raw"], "default": True},
    {"table": "voonix_campaign_deals", "label": "Campaign deals", "group": "Accounts", "raw_cols": [], "default": True},
    {"table": "voonix_sites", "label": "Sites", "group": "Accounts", "raw_cols": ["raw"], "default": True},
    {"table": "voonix_payers", "label": "Payers", "group": "Accounts", "raw_cols": ["raw"], "default": True},
    {"table": "voonix_data_validation", "label": "Data validation", "group": "Accounts", "raw_cols": [], "default": True},
    {"table": "voonix_affiliate_systems", "label": "Affiliate systems", "group": "Accounts", "raw_cols": ["raw"], "default": True},
    {"table": "voonix_write_log", "label": "Change log", "group": "Plugin records", "date_col": "created_at", "raw_cols": ["request", "response"], "default": True},
    {"table": "voonix_sync_state", "label": "Sync state", "group": "Plugin records", "raw_cols": [], "default": False},
]
_SPECS = {t["table"]: t for t in EXPORT_TABLES}

XLSX_MAX_ROWS = 1_048_576   # Excel's per-sheet limit, header included
XLSX_CELL_MAX = 32_767      # Excel's per-cell character limit


# ── Schema from migrations ───────────────────────────────────────────────────

_TYPES = ("timestamptz", "timestamp", "bigint", "integer", "numeric", "boolean", "date", "text", "jsonb")
_TYPE_ALT = "|".join(_TYPES)
_CREATE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+([a-z_][a-z0-9_]*)\s*\((.*?)\n\);", re.S | re.I)
_COL_RE = re.compile(rf"^\s*([a-z_][a-z0-9_]*)\s+({_TYPE_ALT})\b(.*)$", re.I)
_PK_RE = re.compile(r"^\s*PRIMARY KEY\s*\(([^)]*)\)", re.I)
_ALTER_RE = re.compile(
    rf"ALTER TABLE\s+(?:IF EXISTS\s+)?([a-z_][a-z0-9_]*)\s+ADD COLUMN\s+(?:IF NOT EXISTS\s+)?([a-z_][a-z0-9_]*)\s+({_TYPE_ALT})\b",
    re.I,
)


@dataclass
class TableSchema:
    name: str
    columns: list[tuple[str, str]] = field(default_factory=list)
    pk: list[str] = field(default_factory=list)


def load_schema(migrations_dir: Path = MIGRATIONS_DIR) -> dict[str, TableSchema]:
    schema: dict[str, TableSchema] = {}
    for path in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
        if path.name.endswith("_down.sql"):
            continue
        text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        for m in _CREATE_RE.finditer(text):
            table = TableSchema(m.group(1).lower())
            for line in m.group(2).splitlines():
                pk = _PK_RE.match(line)
                if pk:
                    table.pk = [c.strip().lower() for c in pk.group(1).split(",")]
                    continue
                col = _COL_RE.match(line)
                if col:
                    table.columns.append((col.group(1).lower(), col.group(2).lower()))
                    if "PRIMARY KEY" in col.group(3).upper():
                        table.pk = [col.group(1).lower()]
            schema[table.name] = table
        for m in _ALTER_RE.finditer(text):
            table = schema.get(m.group(1).lower())
            if table and m.group(2).lower() not in dict(table.columns):
                table.columns.append((m.group(2).lower(), m.group(3).lower()))
    return schema


def select_tables(param: str | None) -> list[dict[str, Any]]:
    """Comma-separated table names → specs in export order. Empty → defaults."""
    wanted = [t.strip() for t in (param or "").split(",") if t.strip()]
    if not wanted:
        return [t for t in EXPORT_TABLES if t["default"]]
    unknown = [t for t in wanted if t not in _SPECS]
    if unknown:
        raise ValueError(f"Unknown table(s): {', '.join(unknown)}")
    return [t for t in EXPORT_TABLES if t["table"] in wanted]


def table_query(
    spec: dict[str, Any], schema: TableSchema, start: date | None, end: date | None, include_raw: bool,
) -> dict[str, Any]:
    """SELECT + COUNT for one table. Identifiers come from the migration schema only."""
    types = dict(schema.columns)
    columns = [(c, t) for c, t in schema.columns if include_raw or c not in spec["raw_cols"]]
    where: list[str] = []
    params: list[Any] = []
    dc = spec.get("date_col")
    if dc:
        is_ts = types.get(dc) == "timestamptz"
        if start:
            if spec.get("month"):
                where.append(f'"{dc}" >= %s')
                params.append(date(start.year, start.month, 1))
            else:
                where.append(f'"{dc}" >= %s::date' if is_ts else f'"{dc}" >= %s')
                params.append(start)
        if end:
            where.append(f'"{dc}" < (%s::date + 1)' if is_ts else f'"{dc}" <= %s')
            params.append(end)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    order = ", ".join(f'"{c}"' for c in schema.pk) or "1"
    col_sql = ", ".join(f'"{c}"' for c, _ in columns)
    return {
        "columns": columns,
        "params": params,
        "select_sql": f'SELECT {col_sql} FROM "{schema.name}" {where_sql} ORDER BY {order}',
        "count_sql": f'SELECT COUNT(*) FROM "{schema.name}" {where_sql}',
    }


# ── Value conversion ─────────────────────────────────────────────────────────


@dataclass
class ExportTable:
    name: str
    label: str
    columns: list[tuple[str, str]]
    pk: list[str]
    rows: Iterable[tuple[Any, ...]]


def short_name(table: str) -> str:
    return table[len("voonix_"):] if table.startswith("voonix_") else table


def _dec_str(d: Decimal) -> str:
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal):
        return _dec_str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


def to_json_value(v: Any) -> Any:
    if isinstance(v, Decimal):
        if not v.is_finite():
            return None
        return int(v) if v == v.to_integral_value() and abs(v) < 2**53 else float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def to_sqlite_value(v: Any) -> Any:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, Decimal):
        if not v.is_finite():
            return None
        return int(v) if v == v.to_integral_value() and abs(v) < 2**63 else float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return v


def sql_literal(v: Any) -> str:
    """PostgreSQL literal (standard_conforming_strings = on)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v) if math.isfinite(v) else "NULL"
    if isinstance(v, Decimal):
        return _dec_str(v) if v.is_finite() else "NULL"
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False, default=str)
    elif isinstance(v, (datetime, date)):
        v = v.isoformat()
    s = str(v).replace("\x00", "")  # PostgreSQL text cannot hold NUL
    return "'" + s.replace("'", "''") + "'"


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(v: Any) -> str:
    """For human-facing report CSVs: stop text cells being run as spreadsheet formulas."""
    s = to_text(v)
    return "'" + s if isinstance(v, str) and s.startswith(_FORMULA_START) else s


def readme(info: dict[str, Any], counts: dict[str, int]) -> str:
    lines = [
        "Voonix Analytics data export",
        "============================",
        f"Generated:   {info.get('exported_at', '')}",
        f"Plugin:      voonix-analytics {info.get('version', '')}",
        f"Format:      {info.get('format', '')}",
        f"Date range:  {info.get('start') or 'all'} to {info.get('end') or 'all'} "
        "(applies to report tables and the change log; account tables are always complete)",
        f"Raw Voonix records included: {'yes' if info.get('include_raw') else 'no'}",
        "",
        "Rows per table:",
    ]
    lines += [f"  {short_name(t)}: {n}" for t, n in counts.items()]
    lines += [
        "",
        "Notes:",
        "  - Amounts are as Voonix reports them; commission = revshare + CPA + CPL income.",
        "  - Login passwords and affiliate keys (key1/key2) are never stored, so they are not in this export.",
        "  - CSV/JSON values are exported as-is (no spreadsheet formula escaping).",
    ]
    return "\n".join(lines) + "\n"


# ── Writers (each returns {table: row_count}) ────────────────────────────────


def write_csv_zip(path: str, tables: Iterable[ExportTable], info: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for t in tables:
            n = 0
            with zf.open(f"{short_name(t.name)}.csv", "w", force_zip64=True) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                writer = csv.writer(text)
                writer.writerow([c for c, _ in t.columns])
                for row in t.rows:
                    writer.writerow([to_text(v) for v in row])
                    n += 1
                text.flush()
                text.detach()
            counts[t.name] = n
        zf.writestr("README.txt", readme(info, counts))
    return counts


def write_jsonl_zip(path: str, tables: Iterable[ExportTable], info: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for t in tables:
            names = [c for c, _ in t.columns]
            n = 0
            with zf.open(f"{short_name(t.name)}.jsonl", "w", force_zip64=True) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", newline="\n")
                for row in t.rows:
                    obj = {k: to_json_value(v) for k, v in zip(names, row)}
                    text.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
                    n += 1
                text.flush()
                text.detach()
            counts[t.name] = n
        zf.writestr("README.txt", readme(info, counts))
    return counts


_SQLITE_TYPES = {"bigint": "INTEGER", "integer": "INTEGER", "boolean": "INTEGER", "numeric": "NUMERIC"}


def write_sqlite(path: str, tables: Iterable[ExportTable], info: dict[str, Any], batch: int = 2000) -> dict[str, int]:
    counts: dict[str, int] = {}
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode = OFF")
        con.execute("PRAGMA synchronous = OFF")
        for t in tables:
            names = [c for c, _ in t.columns]
            defs = [f'"{c}" {_SQLITE_TYPES.get(typ, "TEXT")}' for c, typ in t.columns]
            if t.pk and all(p in names for p in t.pk):
                defs.append("PRIMARY KEY (" + ", ".join(f'"{p}"' for p in t.pk) + ")")
            con.execute(f'CREATE TABLE "{t.name}" ({", ".join(defs)})')
            insert = f'INSERT INTO "{t.name}" ({", ".join(chr(34) + c + chr(34) for c in names)}) VALUES ({", ".join("?" for _ in names)})'
            buf: list[tuple[Any, ...]] = []
            n = 0
            for row in t.rows:
                buf.append(tuple(to_sqlite_value(v) for v in row))
                n += 1
                if len(buf) >= batch:
                    con.executemany(insert, buf)
                    buf.clear()
            if buf:
                con.executemany(insert, buf)
            counts[t.name] = n
        con.execute('CREATE TABLE "_export_info" ("key" TEXT PRIMARY KEY, "value" TEXT)')
        rows = [(k, to_text(v)) for k, v in info.items()] + [("row_counts", json.dumps(counts))]
        con.executemany('INSERT INTO "_export_info" VALUES (?, ?)', rows)
        con.commit()
    finally:
        con.close()
    return counts


def write_sql_zip(path: str, tables: Iterable[ExportTable], info: dict[str, Any], batch: int = 500) -> dict[str, int]:
    counts: dict[str, int] = {}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("voonix-export.sql", "w", force_zip64=True) as raw:
            out = io.TextIOWrapper(raw, encoding="utf-8", newline="\n")
            out.write(
                "-- Voonix Analytics data export (PostgreSQL)\n"
                f"-- Generated {info.get('exported_at', '')} by voonix-analytics {info.get('version', '')}\n"
                "-- Load into an EMPTY database, e.g.:  createdb voonix && psql -d voonix -f voonix-export.sql\n"
                "-- Tables are created if missing; rows that already exist are skipped (ON CONFLICT DO NOTHING).\n\n"
                "SET client_encoding = 'UTF8';\nSET standard_conforming_strings = on;\n\nBEGIN;\n\n"
            )
            for t in tables:
                names = [c for c, _ in t.columns]
                defs = [f'    "{c}" {typ}' for c, typ in t.columns]
                if t.pk and all(p in names for p in t.pk):
                    defs.append("    PRIMARY KEY (" + ", ".join(f'"{p}"' for p in t.pk) + ")")
                out.write(f'CREATE TABLE IF NOT EXISTS "{t.name}" (\n' + ",\n".join(defs) + "\n);\n\n")
                col_sql = ", ".join(f'"{c}"' for c in names)
                buf: list[str] = []
                n = 0

                def flush() -> None:
                    out.write(f'INSERT INTO "{t.name}" ({col_sql}) VALUES\n' + ",\n".join(buf)
                              + "\nON CONFLICT DO NOTHING;\n")
                    buf.clear()

                for row in t.rows:
                    buf.append("(" + ", ".join(sql_literal(v) for v in row) + ")")
                    n += 1
                    if len(buf) >= batch:
                        flush()
                if buf:
                    flush()
                out.write("\n")
                counts[t.name] = n
            out.write("COMMIT;\n")
            out.flush()
            out.detach()
        zf.writestr("README.txt", readme(info, counts))
    return counts


# ── Excel ────────────────────────────────────────────────────────────────────

_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_SHEET_HEAD = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<worksheet xmlns="{_NS}"><sheetViews><sheetView workbookViewId="0">'
    '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
    "</sheetView></sheetViews><sheetData>"
)
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<styleSheet xmlns="{_NS}">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def _col_letter(i: int) -> str:
    s, n = "", i + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx_cell(ref: str, v: Any, bold: bool = False) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"><v>{int(v)}</v></c>'
    if isinstance(v, (int, float, Decimal)):
        if isinstance(v, float) and not math.isfinite(v):
            return ""
        if isinstance(v, Decimal) and not v.is_finite():
            return ""
        num = _dec_str(v) if isinstance(v, Decimal) else repr(v) if isinstance(v, float) else str(v)
        return f'<c r="{ref}"><v>{num}</v></c>'
    text = _ILLEGAL_XML.sub("", to_text(v))[:XLSX_CELL_MAX]
    style = ' s="1"' if bold else ""
    return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{_xml_escape(text)}</t></is></c>'


def _sheet_name(base: str, used: set[str]) -> str:
    name = re.sub(r"[\[\]:*?/\\]", "_", base).strip("'")[:31] or "Sheet"
    candidate, k = name, 2
    while candidate.lower() in used:
        suffix = f" {k}"
        candidate = name[: 31 - len(suffix)] + suffix
        k += 1
    used.add(candidate.lower())
    return candidate


def write_xlsx(path: str, tables: Iterable[ExportTable], info: dict[str, Any] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    sheets: list[str] = []
    used: set[str] = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:

        def open_sheet(label: str, header: list[str]) -> io.TextIOWrapper:
            sheets.append(_sheet_name(label, used))
            raw = zf.open(f"xl/worksheets/sheet{len(sheets)}.xml", "w", force_zip64=True)
            out = io.TextIOWrapper(raw, encoding="utf-8")
            out.write(_SHEET_HEAD)
            cells = "".join(_xlsx_cell(f"{_col_letter(i)}1", h, bold=True) for i, h in enumerate(header))
            out.write(f'<row r="1">{cells}</row>')
            return out

        def close_sheet(out: io.TextIOWrapper) -> None:
            out.write("</sheetData></worksheet>")
            out.flush()
            out.close()

        for t in tables:
            header = [c for c, _ in t.columns]
            letters = [_col_letter(i) for i in range(len(header))]
            base = t.label or short_name(t.name)
            part = 1
            out = open_sheet(base, header)
            r = 1
            n = 0
            for row in t.rows:
                if r >= XLSX_MAX_ROWS:
                    close_sheet(out)
                    part += 1
                    out = open_sheet(f"{base} {part}", header)
                    r = 1
                r += 1
                cells = "".join(_xlsx_cell(f"{letters[i]}{r}", v) for i, v in enumerate(row))
                out.write(f'<row r="{r}">{cells}</row>')
                n += 1
            close_sheet(out)
            counts[t.name] = n

        if info is not None:
            out = open_sheet("Export info", ["key", "value"])
            items = [(k, to_text(v)) for k, v in info.items()] + [
                (f"rows: {short_name(k)}", n) for k, n in counts.items()
            ]
            for i, (k, v) in enumerate(items, start=2):
                out.write(f'<row r="{i}">{_xlsx_cell(f"A{i}", k)}{_xlsx_cell(f"B{i}", v)}</row>')
            close_sheet(out)

        sheet_xml = "".join(
            f'<sheet name="{_xml_escape(name, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
            for i, name in enumerate(sheets, start=1)
        )
        zf.writestr("xl/workbook.xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                    f'<workbook xmlns="{_NS}" xmlns:r="{_REL}"><sheets>{sheet_xml}</sheets></workbook>')
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="{_REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        rels += f'<Relationship Id="rId{len(sheets) + 1}" Type="{_REL}/styles" Target="styles.xml"/>'
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                    f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        zf.writestr("xl/styles.xml", _STYLES)
        zf.writestr("_rels/.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/>'
                    "</Relationships>")
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/xl/workbook.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                    '<Override PartName="/xl/styles.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                    f"{overrides}</Types>")
    return counts


WRITERS = {
    "csv": write_csv_zip,
    "jsonl": write_jsonl_zip,
    "xlsx": write_xlsx,
    "sqlite": write_sqlite,
    "sql": write_sql_zip,
}


def write_export(fmt: str, path: str, tables: Iterable[ExportTable], info: dict[str, Any]) -> dict[str, int]:
    if fmt not in WRITERS:
        raise ValueError(f"Unknown export format: {fmt}")
    return WRITERS[fmt](path, tables, info)


def write_report_file(fmt: str, path: str, title: str, headers: list[str], rows: Iterable[tuple[Any, ...]]) -> int:
    """Single-table download for a report tab (CSV, Excel or JSON)."""
    if fmt == "csv":
        n = 0
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in rows:
                writer.writerow([csv_safe(v) for v in row])
                n += 1
        return n
    if fmt == "json":
        n = 0
        with open(path, "w", encoding="utf-8") as f:
            f.write("[")
            for row in rows:
                obj = {h: to_json_value(v) for h, v in zip(headers, row)}
                f.write(("," if n else "") + "\n" + json.dumps(obj, ensure_ascii=False, default=str))
                n += 1
            f.write("\n]\n")
        return n
    if fmt == "xlsx":
        table = ExportTable(name=title, label=title, columns=[(h, "text") for h in headers], pk=[], rows=rows)
        return write_xlsx(path, [table], info=None)[title]
    raise ValueError(f"Unknown report format: {fmt}")


def iter_query(conn: Any, select_sql: str, params: list[Any], itersize: int = 5000) -> Iterable[tuple[Any, ...]]:
    """Stream rows through a server-side cursor so a large table never loads
    into memory. WITH HOLD keeps the cursor valid whether or not the
    connection is in autocommit mode (the SDK pool's mode isn't documented)."""
    from uuid import uuid4

    cur = conn.cursor(name=f"voonix_export_{uuid4().hex[:16]}", withhold=True)
    cur.itersize = itersize
    try:
        cur.execute(select_sql, params)
        for row in cur:
            yield row
    finally:
        cur.close()
