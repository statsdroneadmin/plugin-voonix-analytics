"""
api/routes.py — HTTP routes for voonix-analytics.

  GET  /health-check                 version + row counts (no auth, no data)
  POST /test-connection              probe Voonix with the saved URL + key
  POST /sync-now                     enqueue a sync
  POST /backfill                     ask the next sync for 12 older months, and enqueue it
  GET  /config                       what the widgets need to know (writes on? admin?)
  GET  /report/{name}/meta           dims, measures, date range for a report tab
  GET  /report/{name}                grouped + filtered + sorted report rows and totals
  GET  /manage/{resource}/schema     columns + create/update/delete forms
  GET  /manage/{resource}/rows       mirrored rows for the manage tables
  POST /manage/{resource}/{op}       create / update / delete in Voonix (admin)
  GET  /write-log                    recent writes

All SQL identifiers come from src/voonix_analytics_catalog.py constants;
request values are parameters (G-12). Reference: docs/03-data-and-routes.md
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from nousviz_sdk import get_pg_conn, DictCursor, log_event

_PLUGIN_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_PLUGIN_SRC) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_SRC))

import voonix_analytics_catalog as cat  # noqa: E402
import voonix_analytics_export as ex  # noqa: E402
import voonix_analytics_mappers as mp  # noqa: E402
import voonix_analytics_store as st  # noqa: E402
from voonix_analytics_client import VoonixError  # noqa: E402


router = APIRouter()
PLUGIN_SLUG = "voonix-analytics"
PLUGIN_VERSION = "0.2.3"   # bump alongside plugin.yaml version
BASE = f"/plugins/{PLUGIN_SLUG}"
MAX_WRITE_ROWS = 100


# ── Auth ────────────────────────────────────────────────────────────────────


def _require_analyst(request: Request) -> Any:
    identity = getattr(request.state, "user_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="Auth required")
    return identity


def _identity_role(request: Request) -> str | None:
    ident = getattr(request.state, "user_identity", None)
    if isinstance(ident, dict):
        role = ident.get("role") or ident.get("user_role")
        return str(role) if role else None
    role = getattr(ident, "role", None)
    return str(role) if role else None


def _require_admin(request: Request) -> Any:
    """Writes change the operator's real Voonix account, so they are admin
    only. The identity shape isn't documented by core: role='admin' passes,
    any other role is refused, and if core exposes no role at all the write
    is allowed with a logged warning (same bootstrap rule as plugin-ahrefs-data)."""
    ident = _require_analyst(request)
    role = _identity_role(request)
    if role == "admin":
        return ident
    if role is None:
        log_event("warning", "Voonix write allowed without role information (bootstrap rule)")
        return ident
    raise HTTPException(status_code=403, detail="Only admins can change data in Voonix.")


def _actor(request: Request) -> str:
    ident = getattr(request.state, "user_identity", None)
    if isinstance(ident, dict):
        return str(ident.get("email") or ident.get("username") or ident.get("id") or "unknown")
    for attr in ("email", "username", "id"):
        if getattr(ident, attr, None):
            return str(getattr(ident, attr))
    return str(ident or "unknown")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _rows(cur: Any) -> list[dict[str, Any]]:
    return [{k: _jsonable(v) for k, v in dict(r).items()} for r in cur.fetchall()]


def _parse_date(value: str | None, label: str) -> date | None:
    if not value:
        return None
    d = mp.to_date(value)
    if d is None:
        raise HTTPException(status_code=400, detail=f"{label} must be YYYY-MM-DD")
    return d


def _record_action_run(*, job_id: str, status: str, duration_ms: int, detail: dict[str, Any]) -> None:
    """job_runs row so the setup checklist's last_test_success predicate flips (G-6)."""
    try:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO job_runs (job_id, status, source, started_at, completed_at, duration_ms, details)
                VALUES (%s, %s, 'manual', now(), now(), %s, %s::jsonb)
                """,
                (job_id, status, duration_ms, json.dumps(detail)),
            )
            conn.commit()
    except Exception as exc:
        log_event("warning", f"Failed to write job_runs row for {job_id}", detail={"error": str(exc)})


def _enqueue_sync(via: str) -> tuple[bool, int | None]:
    job_id = f"sync:{PLUGIN_SLUG}"
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT EXISTS (SELECT 1 FROM job_runs WHERE job_id = %s
                           AND status IN ('queued', 'running', 'cancelling', 'paused'))
            """,
            (job_id,),
        )
        (active,) = cur.fetchone()
        if active:
            return False, None
        cur.execute(
            "INSERT INTO job_runs (job_id, status, source, started_at, details) "
            "VALUES (%s, 'queued', 'manual', now(), %s::jsonb) RETURNING id",
            (job_id, json.dumps({"via": via})),
        )
        row = cur.fetchone()
        conn.commit()
    return True, (row[0] if row else None)


# ── Health ──────────────────────────────────────────────────────────────────


@router.get(f"{BASE}/health-check")
def health_check() -> dict[str, Any]:
    """Version + counts only — no Voonix data. Unauthenticated so operators
    can confirm the deployed version matches the tag (G-10)."""
    try:
        counts = {}
        with get_pg_conn() as conn:
            cur = conn.cursor()
            for table in ("voonix_advertisers", "voonix_logins", "voonix_campaigns",
                          "voonix_advertiser_earnings"):
                cur.execute(f"SELECT count(*) FROM {table}")  # constant table names
                counts[table] = cur.fetchone()[0]
        return {"plugin": PLUGIN_SLUG, "version": PLUGIN_VERSION, "ok": True, "counts": counts,
                "as_of": st.now_iso()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {e}")


# ── Actions ─────────────────────────────────────────────────────────────────


@router.post(f"{BASE}/test-connection")
def test_connection(_: Any = Depends(_require_analyst)) -> dict[str, Any]:
    started = time.monotonic()
    job_id = f"hook:{PLUGIN_SLUG}:test_connection"
    try:
        client = st.make_client()
        payload = client.probe()
        systems = len(mp.rows_from(payload))
    except VoonixError as e:
        duration_ms = int((time.monotonic() - started) * 1000)
        _record_action_run(job_id=job_id, status="error", duration_ms=duration_ms,
                           detail={"stage": "probe", "error": str(e)[:500]})
        log_event("warning", "Voonix test connection failed", detail={"error": str(e)[:500]})
        return {"ok": False, "level": "error", "toast": f"Voonix connection failed: {str(e)[:220]}"}
    except Exception as e:
        duration_ms = int((time.monotonic() - started) * 1000)
        tb = traceback.format_exc()[-1500:]
        _record_action_run(job_id=job_id, status="error", duration_ms=duration_ms,
                           detail={"stage": "probe", "error": str(e)[:500], "traceback_tail": tb})
        log_event("error", "Voonix test connection crashed", detail={"error": str(e), "traceback_tail": tb})
        return {"ok": False, "level": "error", "toast": f"Unexpected error: {str(e)[:200]}"}

    duration_ms = int((time.monotonic() - started) * 1000)
    _record_action_run(job_id=job_id, status="success", duration_ms=duration_ms,
                       detail={"stage": "probe", "affiliate_systems": systems})
    return {"ok": True, "level": "info",
            "toast": f"Connected to Voonix — {systems} affiliate systems visible."}


@router.post(f"{BASE}/sync-now")
def sync_now(_: Any = Depends(_require_analyst)) -> dict[str, Any]:
    try:
        queued, run_id = _enqueue_sync("plugin_action")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not enqueue sync: {e}")
    if not queued:
        return {"level": "warning", "toast": "A sync is already running.",
                "navigate": f"/plugin/{PLUGIN_SLUG}/sync"}
    return {"level": "info", "toast": f"Sync queued (job #{run_id}).",
            "navigate": f"/plugin/{PLUGIN_SLUG}/sync"}


@router.post(f"{BASE}/backfill")
def backfill(_: Any = Depends(_require_analyst)) -> dict[str, Any]:
    try:
        floor = (st.get_state("history_floor") or {}).get("month")
        if not floor:
            return {"level": "warning",
                    "toast": "Run the first sync before fetching older history."}
        st.set_state("backfill_request", {"requested": True, "requested_at": st.now_iso()})
        queued, run_id = _enqueue_sync("backfill")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not request backfill: {e}")
    older = mp.add_months(mp.to_date(floor), -12).isoformat()[:7]
    if not queued:
        return {"level": "info",
                "toast": f"A sync is running; the next sync will also fetch back to {older}."}
    return {"level": "info",
            "toast": f"Fetching 12 older months (back to {older}) — job #{run_id}. "
                     "The Sync tab shows whether older data was found.",
            "navigate": f"/plugin/{PLUGIN_SLUG}/sync"}


@router.get(f"{BASE}/config")
def config(request: Request, _: Any = Depends(_require_analyst)) -> dict[str, Any]:
    settings = st.load_settings()
    role = _identity_role(request)
    return {
        "writes_enabled": settings["allow_writes"],
        "can_write": settings["allow_writes"] and role in ("admin", None),
        "role": role,
        "history_floor": (st.get_state("history_floor") or {}).get("month"),
        "backfill_last": st.get_state("backfill_last"),
    }


# ── Reports ─────────────────────────────────────────────────────────────────


@router.get(f"{BASE}/report/{{name}}/meta")
def report_meta(name: str, _: Any = Depends(_require_analyst)) -> dict[str, Any]:
    if name not in cat.REPORTS:
        raise HTTPException(status_code=404, detail="Unknown report")
    meta = cat.report_meta(name)
    q = cat.build_report_query(name, None, None, [], None, None, None, 1, 0)
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(q["range_sql"])
        rng = {k: _jsonable(v) for k, v in dict(cur.fetchone() or {}).items()}
    return {**meta, **rng}


@router.get(f"{BASE}/report/{{name}}")
def report(
    name: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
    group_by: str = Query(""),
    sort: str | None = Query(None),
    dir: str | None = Query(None),
    search: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    _: Any = Depends(_require_analyst),
) -> dict[str, Any]:
    if name not in cat.REPORTS:
        raise HTTPException(status_code=404, detail="Unknown report")
    q = cat.build_report_query(
        name, _parse_date(start, "start"), _parse_date(end, "end"),
        [g.strip() for g in group_by.split(",") if g.strip()],
        sort, dir, (search or "").strip() or None, limit, offset,
    )
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(q["rows_sql"], (*q["params"], limit, offset))
        rows = _rows(cur)
        cur.execute(q["count_sql"], q["params"])
        total = cur.fetchone()["n"]
        cur.execute(q["totals_sql"], q["params"])
        totals = {k: _jsonable(v) for k, v in dict(cur.fetchone() or {}).items()}
    return {"rows": rows, "total": total, "totals": totals, "group_by": q["dims"],
            "sort": q["sort"], "dir": q["dir"]}


# ── Manage (mirror tables + writes) ─────────────────────────────────────────


@router.get(f"{BASE}/manage/{{resource}}/schema")
def manage_schema(resource: str, _: Any = Depends(_require_analyst)) -> dict[str, Any]:
    if resource not in cat.RESOURCES:
        raise HTTPException(status_code=404, detail="Unknown resource")
    schema = cat.resource_schema(resource)
    sources = {f["options_from"] for op in schema["ops"].values() for f in op["fields"]
               if f.get("options_from")}
    options: dict[str, list[dict[str, Any]]] = {}
    if sources:
        with get_pg_conn() as conn:
            cur = DictCursor(conn.cursor())
            for source in sources:
                cur.execute(cat.OPTION_SOURCES[source])
                options[source] = _rows(cur)
    for op in schema["ops"].values():
        op["fields"] = [
            {**f, "options": options.get(f["options_from"], [])} if f.get("options_from") else f
            for f in op["fields"]
        ]
    return schema


@router.get(f"{BASE}/manage/{{resource}}/rows")
def manage_rows(
    resource: str,
    search: str | None = Query(None, max_length=200),
    sort: str | None = Query(None),
    dir: str | None = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: Any = Depends(_require_analyst),
) -> dict[str, Any]:
    if resource not in cat.RESOURCES:
        raise HTTPException(status_code=404, detail="Unknown resource")
    q = cat.build_rows_query(resource, (search or "").strip() or None, sort, dir, limit, offset)
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(q["rows_sql"], (*q["params"], limit, offset))
        rows = _rows(cur)
        cur.execute(q["count_sql"], q["params"])
        total = cur.fetchone()["n"]
    return {"rows": rows, "total": total, "sort": q["sort"], "dir": q["dir"]}


@router.post(f"{BASE}/manage/{{resource}}/{{op}}")
def manage_write(
    resource: str,
    op: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: Any = Depends(_require_admin),
) -> dict[str, Any]:
    settings = st.load_settings()
    if not settings["allow_writes"]:
        raise HTTPException(status_code=403,
                            detail="Changes to Voonix are switched off (Settings → Allow changes).")
    res = cat.RESOURCES.get(resource)
    if res is None or op not in res["ops"]:
        raise HTTPException(status_code=404, detail="Unknown resource or operation")
    op_def = res["ops"][op]

    rows_in = body.get("rows") if isinstance(body.get("rows"), list) else [body.get("row") or {}]
    if not rows_in or len(rows_in) > MAX_WRITE_ROWS:
        raise HTTPException(status_code=400, detail=f"Send between 1 and {MAX_WRITE_ROWS} rows.")

    validated = []
    for i, row in enumerate(rows_in):
        try:
            validated.append(cat.validate_write(resource, op, row if isinstance(row, dict) else {}))
        except ValueError as e:
            prefix = f"Row {i + 1}: " if len(rows_in) > 1 else ""
            raise HTTPException(status_code=400, detail=f"{prefix}{e}")
    api_report, api_op = validated[0][0], validated[0][1]
    payloads = [v[2] for v in validated]
    locals_ = [v[3] for v in validated]

    needs_confirm = op_def.get("danger") or any(p.get("resume_import") for p in payloads)
    if needs_confirm and body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="This change needs explicit confirmation.")

    actor = _actor(request)
    try:
        client = st.make_client(settings)
        response = client.write(api_report, api_op, payloads)
    except VoonixError as e:
        st.log_write(actor=actor, resource=resource, op=op, request_rows=cat.redact(payloads),
                     ok=False, succeeded=0, failed=len(payloads), response=None, error=str(e)[:1000])
        log_event("warning", "Voonix write failed", detail={"resource": resource, "op": op,
                                                             "error": str(e)[:500]})
        return {"ok": False, "error": str(e)[:500], "toast": f"Voonix refused the change: {str(e)[:200]}"}

    resp = response if isinstance(response, dict) else {}
    succeeded = resp.get("succeeded") if isinstance(resp.get("succeeded"), list) else []
    failed = resp.get("failed") if isinstance(resp.get("failed"), list) else []
    succeeded_count = mp.to_int(resp.get("succeeded_count"))
    failed_count = mp.to_int(resp.get("failed_count"))
    succeeded_count = len(succeeded) if succeeded_count is None else succeeded_count
    failed_count = len(failed) if failed_count is None else failed_count
    ok = failed_count == 0

    refreshed: list[str] = []
    refresh_error = None
    if succeeded_count > 0 or (ok and not succeeded):
        try:
            refreshed = st.refresh_after_write(client, resource, payloads, locals_)
        except Exception as e:
            refresh_error = str(e)[:300]
            log_event("warning", "Voonix refresh after write failed",
                      detail={"resource": resource, "error": refresh_error})

    st.log_write(actor=actor, resource=resource, op=op, request_rows=cat.redact(payloads), ok=ok,
                 succeeded=succeeded_count, failed=failed_count, response=cat.redact(resp), error=None)

    noun = res["noun"]
    if ok:
        toast = f"Saved in Voonix ({succeeded_count} {noun}{'' if succeeded_count == 1 else 's'})."
    else:
        toast = f"Voonix accepted {succeeded_count} and rejected {failed_count}."
    if refresh_error:
        toast += " Local copy not refreshed yet — run a sync."
    return {"ok": ok, "succeeded_count": succeeded_count, "failed_count": failed_count,
            "failed": cat.redact(failed), "refreshed": refreshed, "refresh_error": refresh_error,
            "toast": toast}


@router.get(f"{BASE}/write-log")
def write_log(limit: int = Query(50, ge=1, le=500), _: Any = Depends(_require_analyst)) -> dict[str, Any]:
    with get_pg_conn() as conn:
        cur = DictCursor(conn.cursor())
        cur.execute(
            "SELECT created_at, actor, resource, op, row_count, ok, succeeded_count, failed_count, error "
            "FROM voonix_write_log ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        return {"rows": _rows(cur)}


# ── Export ──────────────────────────────────────────────────────────────────
# Files are written to a temp file on the API host (server-side cursor, one
# table at a time), sent as an attachment, then deleted. Any logged-in user
# may export: each install uses its own Voonix key, so it is their data.

EXPORT_MAX_ROWS = 3_000_000
REPORT_EXPORT_MAX_ROWS = 200_000


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _temp_path(ext: str) -> str:
    fd, path = tempfile.mkstemp(prefix="voonix-export-", suffix=f".{ext}")
    os.close(fd)
    return path


def _export_plan(tables: str, start: str | None, end: str | None, include_raw: bool) -> list[tuple[dict[str, Any], Any, dict[str, Any]]]:
    try:
        specs = ex.select_tables(tables)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    s, e_ = _parse_date(start, "start"), _parse_date(end, "end")
    schema = ex.load_schema()
    return [
        (spec, schema[spec["table"]], ex.table_query(spec, schema[spec["table"]], s, e_, include_raw))
        for spec in specs
    ]


def _count_rows(cur: Any, plan: list[tuple[dict[str, Any], Any, dict[str, Any]]]) -> list[dict[str, Any]]:
    counts = []
    for spec, _schema, q in plan:
        cur.execute(q["count_sql"], q["params"])
        counts.append({"table": spec["table"], "label": spec["label"], "rows": int(cur.fetchone()[0])})
    return counts


@router.get(f"{BASE}/export/options")
def export_options(_: Any = Depends(_require_analyst)) -> dict[str, Any]:
    return {
        "formats": [{"key": k, "label": v["label"], "ext": v["ext"], "help": v["help"]} for k, v in ex.FORMATS.items()],
        "tables": [
            {"table": t["table"], "label": t["label"], "group": t["group"], "default": t["default"],
             "dated": bool(t.get("date_col"))}
            for t in ex.EXPORT_TABLES
        ],
        "report_formats": [{"key": k, "label": v["label"]} for k, v in ex.REPORT_FORMATS.items()],
        "max_rows": EXPORT_MAX_ROWS,
    }


@router.get(f"{BASE}/export/estimate")
def export_estimate(
    tables: str = Query(""),
    start: str | None = Query(None),
    end: str | None = Query(None),
    _: Any = Depends(_require_analyst),
) -> dict[str, Any]:
    plan = _export_plan(tables, start, end, include_raw=False)
    with get_pg_conn() as conn:
        counts = _count_rows(conn.cursor(), plan)
    total = sum(c["rows"] for c in counts)
    warnings = []
    if total > EXPORT_MAX_ROWS:
        warnings.append(f"That's more than the {EXPORT_MAX_ROWS:,} rows one export can hold — "
                        "pick a shorter date range or fewer tables.")
    split = [c["label"] for c in counts if c["rows"] >= ex.XLSX_MAX_ROWS - 1]
    if split:
        warnings.append(f"Excel allows about 1 million rows per sheet; {', '.join(split)} will continue on extra sheets.")
    if total > 500_000:
        warnings.append("Large export — it may take a few minutes to prepare.")
    return {"tables": counts, "total": total, "max_rows": EXPORT_MAX_ROWS, "warnings": warnings}


@router.get(f"{BASE}/export")
def export_download(
    fmt: str = Query(..., alias="format"),
    tables: str = Query(""),
    start: str | None = Query(None),
    end: str | None = Query(None),
    include_raw: bool = Query(False),
    _: Any = Depends(_require_analyst),
) -> FileResponse:
    if fmt not in ex.FORMATS:
        raise HTTPException(status_code=400, detail=f"Unknown format: {fmt}")
    plan = _export_plan(tables, start, end, include_raw)
    fmt_spec = ex.FORMATS[fmt]
    exported_at = datetime.now(timezone.utc)
    info = {
        "exported_at": exported_at.isoformat(timespec="seconds"),
        "version": PLUGIN_VERSION,
        "format": fmt,
        "start": start,
        "end": end,
        "include_raw": include_raw,
        "tables": ",".join(spec["table"] for spec, _s, _q in plan),
    }
    path = _temp_path(fmt_spec["ext"])
    try:
        with get_pg_conn() as conn:
            total = sum(c["rows"] for c in _count_rows(conn.cursor(), plan))
            if total > EXPORT_MAX_ROWS:
                raise HTTPException(status_code=413, detail=(
                    f"{total:,} rows is more than one export can hold ({EXPORT_MAX_ROWS:,}). "
                    "Pick a shorter date range or fewer tables."))

            def tables_iter():
                for spec, schema, q in plan:
                    yield ex.ExportTable(
                        name=spec["table"], label=spec["label"], columns=q["columns"], pk=schema.pk,
                        rows=ex.iter_query(conn, q["select_sql"], q["params"]),
                    )

            written = ex.write_export(fmt, path, tables_iter(), info)
    except HTTPException:
        _unlink_quietly(path)
        raise
    except Exception as e:
        _unlink_quietly(path)
        log_event("error", "Voonix export failed", detail={"format": fmt, "error": str(e)[:500]})
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)[:300]}")

    log_event("info", "Voonix export created", detail={
        "format": fmt, "rows": sum(written.values()), "bytes": os.path.getsize(path),
    })
    filename = f"voonix-export-{fmt}-{exported_at.strftime('%Y%m%d-%H%M')}.{fmt_spec['ext']}"
    return FileResponse(path, media_type=fmt_spec["media"], filename=filename,
                        background=BackgroundTask(_unlink_quietly, path))


@router.get(f"{BASE}/report/{{name}}/export")
def report_export(
    name: str,
    fmt: str = Query("xlsx", alias="format"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    group_by: str = Query(""),
    sort: str | None = Query(None),
    dir: str | None = Query(None),
    search: str | None = Query(None, max_length=200),
    _: Any = Depends(_require_analyst),
) -> FileResponse:
    if name not in cat.REPORTS:
        raise HTTPException(status_code=404, detail="Unknown report")
    if fmt not in ex.REPORT_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unknown format: {fmt}")
    start_d, end_d = _parse_date(start, "start"), _parse_date(end, "end")
    q = cat.build_report_query(
        name, start_d, end_d, [g.strip() for g in group_by.split(",") if g.strip()],
        sort, dir, (search or "").strip() or None, REPORT_EXPORT_MAX_ROWS, 0,
    )
    rep = cat.REPORTS[name]
    headers = [rep["dims"][d]["label"] for d in q["dims"]] + [m[1] for m in rep["measures"]]
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute(q["rows_sql"], (*q["params"], REPORT_EXPORT_MAX_ROWS + 1, 0))
        rows = cur.fetchall()
    truncated = len(rows) > REPORT_EXPORT_MAX_ROWS
    rows = rows[:REPORT_EXPORT_MAX_ROWS]

    fmt_spec = ex.REPORT_FORMATS[fmt]
    path = _temp_path(fmt_spec["ext"])
    try:
        ex.write_report_file(fmt, path, rep["label"], headers, iter(rows))
    except Exception as e:
        _unlink_quietly(path)
        log_event("error", "Voonix report export failed", detail={"report": name, "error": str(e)[:500]})
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)[:300]}")
    filename = f"voonix-{name.replace('_', '-')}-{start_d or 'all'}-{end_d or 'all'}.{fmt_spec['ext']}"
    return FileResponse(
        path, media_type=fmt_spec["media"], filename=filename,
        headers={"X-Voonix-Truncated": "1" if truncated else "0",
                 "X-Voonix-Row-Limit": str(REPORT_EXPORT_MAX_ROWS)},
        background=BackgroundTask(_unlink_quietly, path),
    )
