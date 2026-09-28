"""
src/voonix_analytics_store.py — database side of the Voonix mirror.

Fetch → map → write for every Voonix resource. Shared by the sync script
(full runs) and api/routes.py (targeted refresh right after a write), so
both paths land data identically.

Write strategies:
  - Dimensions (advertisers, logins, campaigns, …): upsert by primary key;
    rows that disappeared from Voonix are deleted only when the fetch is
    known to be complete (never after a possibly-truncated page).
  - Period facts (earnings, payouts, custom stats): one API call covers one
    calendar month, and the month is replaced atomically (DELETE + INSERT
    in one transaction). Restated or clawed-back numbers therefore
    overwrite the old ones, and an API error leaves the old month intact.

Reference: docs/03-data-and-routes.md, docs/06-sync-and-jobs.md
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable
import json
import uuid

from psycopg2 import sql
from psycopg2.extras import execute_values

from nousviz_sdk import get_pg_conn, get_credential, log_event
from nousviz_sdk.settings import get_connection_field

import voonix_analytics_mappers as mp
from voonix_analytics_catalog import RESOURCES
from voonix_analytics_client import VoonixClient


PLUGIN_SLUG = "voonix-analytics"

# `campaigns&list` defaults to 200 rows and documents no offset.
CAMPAIGN_DEFAULT_LIMIT = 200
CAMPAIGN_BULK_LIMIT = 100000
LOGIN_PAGE = 500
PAYER_MAX = 1000  # docs: "Accepted values: '1-1000'", no offset


class Cancelled(Exception):
    """Raised from a progress callback when the operator cancels the job."""


Tick = Callable[[dict[str, Any]], None]


def _no_tick(_progress: dict[str, Any]) -> None:
    return None


# ── Settings ─────────────────────────────────────────────────────────────────


def _int_field(name: str, default: int, lo: int, hi: int) -> int:
    raw = get_connection_field(PLUGIN_SLUG, name)
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def load_settings() -> dict[str, Any]:
    allow = get_connection_field(PLUGIN_SLUG, "allow_writes")
    return {
        "base_url": get_connection_field(PLUGIN_SLUG, "base_url") or "",
        "history_months": _int_field("history_months", 24, 1, 240),
        "resync_months": _int_field("resync_months", 3, 1, 24),
        "datamonitor_days": _int_field("datamonitor_days", 14, 0, 90),
        "allow_writes": True if allow is None else mp.to_bool(allow) is not False,
    }


def make_client(settings: dict[str, Any] | None = None) -> VoonixClient:
    settings = settings or load_settings()
    return VoonixClient(settings["base_url"], get_credential(PLUGIN_SLUG, "api_key") or "")


# ── Sync state ───────────────────────────────────────────────────────────────


def get_state(key: str) -> Any:
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM voonix_sync_state WHERE key = %s", (key,))
        row = cur.fetchone()
    if not row:
        return None
    value = row[0]
    return json.loads(value) if isinstance(value, str) else value


def set_state(key: str, value: Any) -> None:
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO voonix_sync_state (key, value, updated_at)
            VALUES (%s, %s::jsonb, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            (key, mp.jdump(value)),
        )
        conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Generic writers ──────────────────────────────────────────────────────────


def _cols_sql(cols: tuple[str, ...] | list[str]) -> sql.Composable:
    return sql.SQL(", ").join(sql.Identifier(c) for c in cols)


def _insert(cur: Any, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    cols = mp.TABLE_COLUMNS[table]
    query = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(sql.Identifier(table), _cols_sql(cols))
    execute_values(cur, query.as_string(cur), [tuple(r[c] for c in cols) for r in rows], page_size=500)


def _dedupe(rows: list[dict[str, Any]], pk: list[str]) -> list[dict[str, Any]]:
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in rows:
        key = tuple(r[k] for k in pk)
        if any(k is None for k in key):
            continue
        by_key[key] = r
    return list(by_key.values())


def _upsert(cur: Any, table: str, pk: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    cols = mp.TABLE_COLUMNS[table]
    updates = [c for c in cols if c not in pk]
    query = sql.SQL(
        "INSERT INTO {t} ({cols}) VALUES %s ON CONFLICT ({pk}) DO UPDATE SET {sets}, synced_at = now()"
    ).format(
        t=sql.Identifier(table),
        cols=_cols_sql(cols),
        pk=_cols_sql(pk),
        sets=sql.SQL(", ").join(
            sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in updates
        ),
    )
    execute_values(cur, query.as_string(cur), [tuple(r[c] for c in cols) for r in rows], page_size=500)


def _delete_missing(cur: Any, table: str, pk_col: str, keep: list[Any]) -> int:
    cur.execute(
        sql.SQL("DELETE FROM {} WHERE NOT ({} = ANY(%s))").format(
            sql.Identifier(table), sql.Identifier(pk_col)
        ),
        (keep,),
    )
    return cur.rowcount


# ── Dimension refreshers ─────────────────────────────────────────────────────


def refresh_affiliate_systems(client: VoonixClient, tick: Tick = _no_tick) -> dict[str, Any]:
    rows = _dedupe([mp.map_affiliate_system(r) for r in mp.rows_from(client.get("affiliatesystems", flag=None))], ["id"])
    with get_pg_conn() as conn:
        cur = conn.cursor()
        _upsert(cur, "voonix_affiliate_systems", ["id"], rows)
        _delete_missing(cur, "voonix_affiliate_systems", "id", [r["id"] for r in rows])
        conn.commit()
    return {"rows": len(rows), "complete": True}


def refresh_advertisers(client: VoonixClient, tick: Tick = _no_tick) -> dict[str, Any]:
    rows = _dedupe([mp.map_advertiser(r) for r in mp.rows_from(client.get("advertisers"))], ["id"])
    with get_pg_conn() as conn:
        cur = conn.cursor()
        _upsert(cur, "voonix_advertisers", ["id"], rows)
        _delete_missing(cur, "voonix_advertisers", "id", [r["id"] for r in rows])
        conn.commit()
    return {"rows": len(rows), "complete": True}


def fetch_logins(client: VoonixClient, tick: Tick = _no_tick) -> tuple[list[dict[str, Any]], bool]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    for _page in range(1000):
        tick({"phase": "logins", "offset": offset})
        batch = mp.rows_from(client.get("advertiserlogins", limit=LOGIN_PAGE, offset=offset), "logins", "data")
        if len(batch) > LOGIN_PAGE:  # limit ignored → everything came back at once
            return batch, True
        fresh = [b for b in batch if str(b.get("id")) not in seen]
        seen.update(str(b.get("id")) for b in fresh)
        out.extend(fresh)
        if len(batch) < LOGIN_PAGE:
            return out, True
        if not fresh:  # offset ignored → same page again; can't page further
            return out, False
        offset += LOGIN_PAGE
    return out, False


def refresh_logins(client: VoonixClient, tick: Tick = _no_tick) -> dict[str, Any]:
    raw, complete = fetch_logins(client, tick)
    logins, deals = [], []
    for r in raw:
        login, history = mp.map_login(r)
        logins.append(login)
        deals.extend(history)
    logins = _dedupe(logins, ["id"])
    deals = _dedupe(deals, ["login_id", "start_month"])
    ids = [r["id"] for r in logins]
    with get_pg_conn() as conn:
        cur = conn.cursor()
        _upsert(cur, "voonix_logins", ["id"], logins)
        cur.execute("DELETE FROM voonix_login_history_deals WHERE login_id = ANY(%s)", (ids,))
        _insert(cur, "voonix_login_history_deals", deals)
        if complete:
            _delete_missing(cur, "voonix_logins", "id", ids)
            _delete_missing(cur, "voonix_login_history_deals", "login_id", ids)
        conn.commit()
    if not complete:
        log_event("warning", "Voonix logins: paging stopped early; stale logins were kept",
                  detail={"fetched": len(logins)})
    return {"rows": len(logins), "history_deals": len(deals), "complete": complete}


def fetch_campaigns(client: VoonixClient, tick: Tick = _no_tick) -> tuple[list[dict[str, Any]], bool, str]:
    bulk = mp.rows_from(client.get("campaigns", limit=CAMPAIGN_BULK_LIMIT))
    if len(bulk) not in (CAMPAIGN_DEFAULT_LIMIT, CAMPAIGN_BULK_LIMIT):
        return bulk, True, "bulk"

    # Exactly 200 back suggests the default cap ignored our limit. Fall back
    # to one call per login so no login's campaigns get cut off.
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM voonix_logins ORDER BY id")
        login_ids = [r[0] for r in cur.fetchall()]
    if not login_ids:
        return bulk, False, "bulk-capped"
    by_key: dict[str, dict[str, Any]] = {}
    complete = True
    for i, login_id in enumerate(login_ids):
        tick({"phase": "campaigns", "login": i + 1, "logins": len(login_ids)})
        batch = mp.rows_from(client.get("campaigns", advertiser_login=login_id, limit=CAMPAIGN_BULK_LIMIT))
        if len(batch) in (CAMPAIGN_DEFAULT_LIMIT, CAMPAIGN_BULK_LIMIT):
            complete = False
        for b in batch:
            by_key[str(b.get("id") or f"{login_id}:{b.get('key')}")] = b
    return list(by_key.values()), complete, "per-login"


def refresh_campaigns(client: VoonixClient, tick: Tick = _no_tick) -> dict[str, Any]:
    raw, complete, mode = fetch_campaigns(client, tick)
    campaigns, deals = [], []
    for r in raw:
        campaign, campaign_deals = mp.map_campaign(r)
        campaigns.append(campaign)
        deals.extend(campaign_deals)
    campaigns = _dedupe(campaigns, ["id"])
    deals = _dedupe(deals, ["id"])
    ids = [r["id"] for r in campaigns]
    with get_pg_conn() as conn:
        cur = conn.cursor()
        _upsert(cur, "voonix_campaigns", ["id"], campaigns)
        cur.execute("DELETE FROM voonix_campaign_deals WHERE campaign_id = ANY(%s)", (ids,))
        _upsert(cur, "voonix_campaign_deals", ["id"], deals)
        if complete:
            _delete_missing(cur, "voonix_campaigns", "id", ids)
            _delete_missing(cur, "voonix_campaign_deals", "campaign_id", ids)
        conn.commit()
    if not complete:
        log_event("warning", "Voonix campaigns may be truncated (a call returned exactly the row cap)",
                  detail={"fetched": len(campaigns), "mode": mode})
    return {"rows": len(campaigns), "deals": len(deals), "complete": complete, "mode": mode}


def refresh_sites(client: VoonixClient, tick: Tick = _no_tick) -> dict[str, Any]:
    rows = _dedupe([mp.map_site(r) for r in mp.rows_from(client.get("sites"))], ["id"])
    with get_pg_conn() as conn:
        cur = conn.cursor()
        _upsert(cur, "voonix_sites", ["id"], rows)
        _delete_missing(cur, "voonix_sites", "id", [r["id"] for r in rows])
        conn.commit()
    return {"rows": len(rows), "complete": True}


def refresh_payers(client: VoonixClient, tick: Tick = _no_tick) -> dict[str, Any]:
    raw = mp.rows_from(client.get("payers", flag=None, structure="flat", limit=PAYER_MAX))
    rows = _dedupe([mp.map_payer(r) for r in raw], ["id"])
    complete = len(raw) < PAYER_MAX
    with get_pg_conn() as conn:
        cur = conn.cursor()
        _upsert(cur, "voonix_payers", ["id"], rows)
        if complete:
            _delete_missing(cur, "voonix_payers", "id", [r["id"] for r in rows])
        conn.commit()
    return {"rows": len(rows), "complete": complete}


def refresh_data_validation(client: VoonixClient, tick: Tick = _no_tick) -> dict[str, Any]:
    rows = _dedupe([mp.map_data_validation(r) for r in mp.rows_from(client.get("datavalidation"))], ["login_id"])
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM voonix_data_validation")
        _insert(cur, "voonix_data_validation", rows)
        conn.commit()
    return {"rows": len(rows), "complete": True}


DIMENSION_REFRESHERS: dict[str, Callable[..., dict[str, Any]]] = {
    "affiliate_systems": refresh_affiliate_systems,
    "advertisers": refresh_advertisers,
    "logins": refresh_logins,
    "campaigns": refresh_campaigns,
    "sites": refresh_sites,
    "payers": refresh_payers,
    "data_validation": refresh_data_validation,
}


# ── Period facts ─────────────────────────────────────────────────────────────

PERIOD_ENDPOINTS: dict[str, dict[str, Any]] = {
    "advertiser_earnings": {
        "report": "advertiserearnings", "flag": "list", "table": "voonix_advertiser_earnings",
        "mapper": mp.map_adv_earning,
        "params": {"breakdown_period": "daily", "breakdown_level": "campaign",
                   "structure": "flat", "export": "json"},
    },
    "site_earnings": {
        "report": "siteearnings", "flag": "list", "table": "voonix_site_earnings",
        "mapper": mp.map_site_earning,
        "params": {"breakdown_period": "daily", "breakdown_level": "advertiser", "export": "json"},
    },
    "invoice_earnings": {
        "report": "earnings", "flag": "list", "table": "voonix_invoice_earnings",
        "mapper": mp.map_invoice_earning,
        "params": {"breakdown_level": "earnings", "structure": "flat", "export": "json"},
    },
    "payouts": {
        # BETA in the docs. start/end only appear in the example, not the parameter list.
        "report": "payout", "flag": None, "table": "voonix_payouts",
        "mapper": mp.map_payout,
        "params": {"breakdown_level": "payment", "structure": "flat", "status": "all", "export": "json"},
    },
    "custom_stats": {
        "report": "customstats", "flag": "list", "table": "voonix_custom_stats",
        "mapper": mp.map_custom_stat,
        "params": {"breakdown_period": "daily", "breakdown_level": "campaign"},
    },
}


def refresh_period(client: VoonixClient, name: str, month: date) -> int:
    ep = PERIOD_ENDPOINTS[name]
    month = mp.month_start(month)
    payload = client.get(
        ep["report"], flag=ep["flag"],
        start=month.isoformat(), end=mp.month_end(month).isoformat(), **ep["params"],
    )
    rows = [ep["mapper"](r, month, i) for i, r in enumerate(mp.rows_from(payload))]
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            sql.SQL("DELETE FROM {} WHERE period_month = %s").format(sql.Identifier(ep["table"])),
            (month,),
        )
        _insert(cur, ep["table"], rows)
        conn.commit()
    return len(rows)


def refresh_datamonitor_day(client: VoonixClient, day: date) -> int:
    rows: list[dict[str, Any]] = []
    for r in mp.rows_from(client.get("datamonitor", flag=None, date=day.isoformat())):
        rows.extend(mp.map_datamonitor(r, day, len(rows)))
    with get_pg_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM voonix_datamonitor WHERE date = %s", (day,))
        _insert(cur, "voonix_datamonitor", rows)
        conn.commit()
    return len(rows)


# ── After a write ────────────────────────────────────────────────────────────


def refresh_after_write(
    client: VoonixClient, resource: str, payloads: list[dict[str, Any]], locals_: list[dict[str, Any]]
) -> list[str]:
    done: list[str] = []
    for target in RESOURCES[resource]["refresh"]:
        if target.startswith("period:"):
            name = target.split(":", 1)[1]
            months = {
                mp.month_start(d)
                for d in (mp.to_date(p.get("date") or l.get("date")) for p, l in zip(payloads, locals_))
                if d
            }
            for m in sorted(months):
                refresh_period(client, name, m)
                done.append(f"{name} {m.isoformat()[:7]}")
        else:
            DIMENSION_REFRESHERS[target](client)
            done.append(target)
    return done


def log_write(
    *, actor: str, resource: str, op: str, request_rows: list[dict[str, Any]], ok: bool,
    succeeded: int, failed: int, response: Any, error: str | None,
) -> None:
    try:
        with get_pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO voonix_write_log (
                    id, actor, resource, op, row_count, ok, succeeded_count,
                    failed_count, request, response, error
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    str(uuid.uuid4()), actor, resource, op, len(request_rows), ok, succeeded,
                    failed, mp.jdump(request_rows), mp.jdump(response)[:20000]
                    if len(mp.jdump(response)) <= 20000 else mp.jdump({"truncated": True}),
                    error,
                ),
            )
            conn.commit()
    except Exception as exc:
        log_event("warning", "Voonix write log insert failed", detail={"error": str(exc)})
