"""
src/voonix_analytics_mappers.py — pure parsing for Voonix API v3 responses.

No SDK or database imports, so this module runs under plain Python in
tests/ (and is where every doc-derived assumption lives).

Every mapper returns a dict whose keys are exactly TABLE_COLUMNS[table];
tests/test_voonix_analytics.py enforces that, so the store can build its
INSERT statements from the constant.

The docs' response examples are hand-written: `data` can be a list, an
id-keyed object, or grouped under "YYYY-MM" keys, and numbers arrive as
strings or numbers. Everything here tolerates all of those. Field names
are matched case-insensitively. # VERIFY each mapping against a live
response — the docs are the only source until then.

Reference: docs-voonix-api/API_NOTES.md
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

# Returned by `advertiserlogins&list` (key1/key2 are the operator's
# affiliate-program API keys). Never stored, not even in `raw`.
SECRET_LOGIN_FIELDS = ("password", "key1", "key2")


# ── Scalar coercion ──────────────────────────────────────────────────────────


def num(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return Decimal(int(v))
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def to_int(v: Any) -> int | None:
    d = num(v)
    if d is None or d != d.to_integral_value():
        return None
    return int(d)


def to_bool(v: Any) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    d = num(s)
    return None if d is None else d != 0


def text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    s = str(v).strip()
    return s or None


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?")


def to_date(v: Any) -> date | None:
    """YYYY-MM-DD or YYYY-MM (→ first of month). 0000-00-00 → None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    m = _DATE_RE.match(str(v).strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    except ValueError:
        return None


def to_ts(v: Any) -> datetime | None:
    """Voonix timestamps look like '2025-10-15 15:03:15' (timezone not
    documented — stored as timestamp without time zone)."""
    if v is None:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def jdump(obj: Any) -> str:
    return json.dumps(obj, default=str)


# ── Months ───────────────────────────────────────────────────────────────────


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def add_months(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def month_end(m: date) -> date:
    return add_months(m, 1) - timedelta(days=1)


def month_range(first: date, last: date) -> list[date]:
    """Inclusive, ascending, month starts."""
    out, m, last = [], month_start(first), month_start(last)
    while m <= last:
        out.append(m)
        m = add_months(m, 1)
    return out


def plan_months(
    today: date,
    history_months: int,
    resync_months: int,
    floor: date | None = None,
    backfill: bool = False,
    backfill_step: int = 12,
) -> tuple[list[date], date]:
    """Which report months a sync fetches, newest first, plus the floor it
    is trying to reach.

    - First run (no floor): every month back to `history_months`.
    - Later runs: the last `resync_months` (restated / clawed-back data),
      plus any gap between the stored floor and a larger `history_months`.
    - Backfill: additionally `backfill_step` months below the stored floor.
    """
    current = month_start(today)
    history_months = max(1, int(history_months))
    resync_months = max(1, int(resync_months))
    desired = add_months(current, -(history_months - 1))
    if floor is None:
        return month_range(desired, current)[::-1], desired

    floor = month_start(floor)
    target = min(desired, floor)
    if backfill:
        target = min(target, add_months(floor, -backfill_step))
    resync_from = max(add_months(current, -(resync_months - 1)), target)
    months = set(month_range(resync_from, current))
    if target < floor:
        months.update(month_range(target, add_months(floor, -1)))
    return sorted(months, reverse=True), target


def advance_floor(
    old_floor: date | None, target: date, ok_months: set[date], current: date
) -> date | None:
    """Lowest month reached with no holes: walk down from just below the
    old floor (or the current month on a first run) while every month
    succeeded."""
    floor = old_floor
    m = add_months(old_floor, -1) if old_floor else month_start(current)
    while m >= target and m in ok_months:
        floor = m
        m = add_months(m, -1)
    return floor


# ── Response envelopes ───────────────────────────────────────────────────────


def flatten(obj: Any) -> list[dict[str, Any]]:
    """List → dict items. Dict of lists (month-grouped) → concatenated.
    Dict of dicts (id-keyed) → values. A single record → [record]."""
    if obj is None:
        return []
    if isinstance(obj, list):
        out: list[dict[str, Any]] = []
        for x in obj:
            if isinstance(x, dict):
                out.append(x)
            elif isinstance(x, list):
                out.extend(flatten(x))
        return out
    if isinstance(obj, dict):
        vals = list(obj.values())
        if not vals:
            return []
        if all(isinstance(v, list) for v in vals):
            return [x for v in vals for x in v if isinstance(x, dict)]
        if all(isinstance(v, dict) for v in vals):
            return vals
        return [obj]
    return []


def rows_from(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return flatten(payload)
    if not isinstance(payload, dict):
        return []
    for k in keys or ("data",):
        if k in payload:
            return flatten(payload[k])
    return []


def _lower(r: dict[str, Any]) -> dict[str, Any]:
    return {str(k).lower(): v for k, v in r.items()}


def pick(low: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = low.get(k.lower())
        if v not in (None, ""):
            return v
    return None


def strip_secrets(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if str(k).lower() not in SECRET_LOGIN_FIELDS}


# ── Table columns (insert order; synced_at is defaulted by the DB) ───────────

EARNING_MEASURES: dict[str, tuple[str, ...]] = {
    "clicks": ("clicks",),
    "unique_clicks": ("unique_clicks",),
    "signups": ("signups",),
    "active_players": ("active_players",),
    "depositors": ("depositors",),
    "deposits": ("deposits",),
    "deposit_value": ("deposit_value",),
    "ftd": ("ftd", "ftds"),
    "cpa_count": ("cpa_count", "cpas"),
    "rev_income": ("rev_income", "revshare"),
    "cpa_income": ("cpa_income", "cpa_commission"),
    "cpl_income": ("cpl_income",),
    "extra_fee": ("extra_fee", "fees"),
    "bonus": ("bonus",),
    "net_revenue": ("netrevenue", "net_revenue"),
    "turnover": ("turnover",),
}

MONEY_MEASURES: dict[str, tuple[str, ...]] = {
    "deposit_value": ("deposit_value",),
    "rev_income": ("rev_income",),
    "cpa_income": ("cpa_income",),
    "extra_fee": ("extra_fee",),
    "bonus": ("bonus",),
    "net_revenue": ("netrevenue", "net_revenue"),
    "gross_revenue": ("gross_revenue",),
    "turnover": ("turnover",),
    "deduction": ("deduction",),
    "total": ("total",),
    "raw_total": ("raw_total",),
}

TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "voonix_affiliate_systems": (
        "id", "name", "has_api", "daily", "brand_id_required", "igaming",
        "report_names", "raw",
    ),
    "voonix_advertisers": (
        "id", "optional_id", "name", "description", "market", "affiliate_system",
        "login_url", "group_name", "currency", "brand_id", "brand_extra",
        "operator", "url_error", "brand_split_possible", "contact_name",
        "contact_email", "contact_skype", "contact_note", "raw",
    ),
    "voonix_logins": (
        "id", "optional_id", "advertiser_id", "advertiser_name", "affiliate_system",
        "username", "group_name", "status", "currency", "note", "extra_note",
        "cosmetic_deal", "locked", "paused", "baseline", "error", "deal_type",
        "deal_rev", "deal_cpa", "deal_cpl", "voonix_created_at", "created_by_name",
        "voonix_updated_at", "updated_by_name", "raw",
    ),
    "voonix_login_history_deals": (
        "login_id", "start_month", "login_username", "advertiser_name", "type",
        "rev", "cpa", "cpl",
    ),
    "voonix_campaigns": (
        "id", "key", "name", "login_id", "login_optional_id", "username",
        "advertiser_id", "advertiser_optional_id", "advertiser_name",
        "campaign_optional_id", "site_id", "site_name", "alias", "group_name",
        "note", "raw",
    ),
    "voonix_campaign_deals": (
        "id", "campaign_id", "campaign_key", "campaign_name", "login_id",
        "start_date", "type", "rev", "cpa", "cpl",
    ),
    "voonix_sites": ("id", "name", "group_name", "url", "country", "raw"),
    "voonix_payers": (
        "id", "name", "payer_advertisers", "payment_provider", "payment_method",
        "threshold", "address", "zip", "city", "country", "vat", "raw",
    ),
    "voonix_data_validation": (
        "login_id", "advertiser_id", "advertiser_name", "login_username",
        "affiliate_system", "data_from_api", "columns", "missing_count",
        "unavailable_count",
    ),
    "voonix_advertiser_earnings": (
        "period_month", "row_no", "date", "advertiser_id", "advertiser_name",
        "login_id", "login_username", "campaign_key", "campaign_name",
        *EARNING_MEASURES.keys(), "raw",
    ),
    "voonix_site_earnings": (
        "period_month", "row_no", "date", "site_id", "site_name", "site_group",
        "advertiser_id", "advertiser_name", *EARNING_MEASURES.keys(), "raw",
    ),
    "voonix_invoice_earnings": (
        "period_month", "row_no", "date", "host", "username", "brand", "campaign",
        "payment_id", "product", "reward_plan", "currency_code", "exchange_rate",
        "base_currency", *MONEY_MEASURES.keys(), "raw",
    ),
    "voonix_payouts": (
        "period_month", "row_no", "host", "username", "brand", "campaign",
        "currency_code", "exchange_rate", "base_currency", *MONEY_MEASURES.keys(),
        "raw",
    ),
    "voonix_custom_stats": (
        "period_month", "row_no", "date", "custom_id", "advertiser_id",
        "advertiser_name", "login_id", "login_username", "campaign_key",
        "campaign_name", "clicks", "unique_clicks", "signups", "active_players",
        "depositors", "deposits", "deposit_value", "ndc", "qndc", "ftd",
        "cpa_count", "rev_income", "cpa_income", "extra_fee", "bonus",
        "net_revenue", "turnover", "gross_revenue", "raw",
    ),
    "voonix_datamonitor": (
        "date", "row_no", "advertiser_id", "advertiser", "login_id", "username",
        "campaign_key", "metric", "current_value", "backup_value", "difference",
    ),
}


def _measures(low: dict[str, Any], spec: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    return {col: num(pick(low, *keys)) for col, keys in spec.items()}


# ── Dimension mappers ────────────────────────────────────────────────────────


def map_affiliate_system(r: dict[str, Any]) -> dict[str, Any]:
    low = _lower(r)
    return {
        "id": to_int(pick(low, "afsy_id", "id")),
        "name": text(pick(low, "afsy_system", "name")),
        "has_api": to_bool(low.get("afsy_api")),
        "daily": to_bool(low.get("afsy_daily")),
        "brand_id_required": to_bool(low.get("afsy_brand_id_required")),
        "igaming": to_bool(low.get("afsy_igaming")),
        "report_names": text(low.get("afsy_report_names")),
        "raw": jdump(r),
    }


def map_advertiser(r: dict[str, Any]) -> dict[str, Any]:
    low = _lower(r)
    return {
        "id": to_int(low.get("id")),
        "optional_id": text(low.get("optional_id")),
        "name": text(low.get("name")),
        "description": text(low.get("description")),
        "market": text(pick(low, "market", "affiliate_market")),
        "affiliate_system": text(low.get("affiliate_system")),
        "login_url": text(pick(low, "login_url", "affiliate_login_url")),
        "group_name": text(pick(low, "group", "affiliate_group")),
        "currency": text(pick(low, "currency", "affiliate_system_currency")),
        "brand_id": text(pick(low, "brand_id", "affiliate_system_brand")),
        "brand_extra": text(pick(low, "brand_extra", "affiliate_system_extra")),
        "operator": text(pick(low, "operator", "affiliate_operator")),
        "url_error": to_bool(low.get("url_error")),
        "brand_split_possible": to_bool(low.get("brand_split_possible")),
        "contact_name": text(low.get("contact_name")),
        "contact_email": text(low.get("contact_email")),
        "contact_skype": text(low.get("contact_skype")),
        "contact_note": text(low.get("contact_note")),
        "raw": jdump(r),
    }


def _deal_list(obj: Any, date_key: str) -> list[dict[str, Any]]:
    """Deals come as a list (v3 docs) or a dict keyed by start date (v2)."""
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            if isinstance(v, dict):
                v = dict(v)
                if not pick(_lower(v), date_key, "start_month", "start_date"):
                    v[date_key] = k
                out.append(v)
        return out
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    return []


def map_login(r: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    clean = strip_secrets(r)
    low = _lower(clean)
    deal = _lower(low.get("deal") or {}) if isinstance(low.get("deal"), dict) else {}
    login_id = to_int(pick(low, "id", "login"))
    username = text(low.get("username"))
    advertiser_name = text(low.get("advertiser_name"))
    row = {
        "id": login_id,
        "optional_id": text(low.get("optional_id")),
        "advertiser_id": to_int(pick(low, "advertiser_id", "advertiser")),
        "advertiser_name": advertiser_name,
        "affiliate_system": text(low.get("advertiser_affiliate_system")),
        "username": username,
        "group_name": text(low.get("group")),
        "status": text(low.get("status")),
        "currency": text(low.get("currency")),
        "note": text(low.get("note")),
        "extra_note": text(low.get("extra_note")),
        "cosmetic_deal": text(low.get("cosmetic_deal")),
        "locked": text(low.get("locked")),
        "paused": to_bool(low.get("paused")),
        "baseline": to_bool(low.get("baseline")),
        "error": to_bool(low.get("error")),
        "deal_type": text(pick(deal, "type") or low.get("type")),
        "deal_rev": num(pick(deal, "rev") or low.get("rev")),
        "deal_cpa": num(pick(deal, "cpa") or low.get("cpa")),
        "deal_cpl": num(pick(deal, "cpl") or low.get("cpl")),
        "voonix_created_at": to_ts(low.get("created_at")),
        "created_by_name": text(low.get("created_by_name")),
        "voonix_updated_at": to_ts(low.get("updated_at")),
        "updated_by_name": text(low.get("updated_by_name")),
        "raw": jdump(clean),
    }
    history: list[dict[str, Any]] = []
    seen: set[date] = set()
    for d in _deal_list(low.get("history_deal"), "start_month"):
        dl = _lower(d)
        start = to_date(pick(dl, "start_month", "start_date"))
        if login_id is None or start is None or start in seen:
            continue
        seen.add(start)
        history.append({
            "login_id": login_id,
            "start_month": start,
            "login_username": username,
            "advertiser_name": advertiser_name,
            "type": text(dl.get("type")),
            "rev": num(dl.get("rev")),
            "cpa": num(dl.get("cpa")),
            "cpl": num(dl.get("cpl")),
        })
    return row, history


def map_campaign(r: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    low = _lower(r)
    login_id = to_int(pick(low, "login_id", "fk_login"))
    key = text(low.get("key"))
    cid = text(low.get("id")) or (f"{login_id}:{key}" if key else None)
    sites = flatten(low.get("sites"))
    site_ids = [text(pick(_lower(s), "site_id", "id")) for s in sites]
    site_names = [text(pick(_lower(s), "site_name", "name")) for s in sites]
    name = text(low.get("name"))
    row = {
        "id": cid,
        "key": key,
        "name": name,
        "login_id": login_id,
        "login_optional_id": text(low.get("login_optional_id")),
        "username": text(low.get("username")),
        "advertiser_id": to_int(low.get("advertiser_id")),
        "advertiser_optional_id": text(low.get("advertiser_optional_id")),
        "advertiser_name": text(low.get("advertiser_name")),
        "campaign_optional_id": text(low.get("campaign_optional_id")),
        "site_id": ", ".join(s for s in site_ids if s) or None,
        "site_name": ", ".join(s for s in site_names if s) or None,
        "alias": text(low.get("alias")),
        "group_name": text(low.get("group")),
        "note": text(low.get("note")),
        "raw": jdump(r),
    }
    deals = []
    for d in _deal_list(low.get("campaign_deals"), "start_date"):
        dl = _lower(d)
        deal_id = text(dl.get("id"))
        if not deal_id or cid is None:
            continue
        deals.append({
            "id": deal_id,
            "campaign_id": cid,
            "campaign_key": key,
            "campaign_name": name,
            "login_id": login_id,
            "start_date": to_date(pick(dl, "start_date", "start_month")),
            "type": text(dl.get("type")),
            "rev": num(dl.get("rev")),
            "cpa": num(dl.get("cpa")),
            "cpl": num(dl.get("cpl")),
        })
    return row, deals


def map_site(r: dict[str, Any]) -> dict[str, Any]:
    low = _lower(r)
    return {
        "id": to_int(low.get("id")),
        "name": text(low.get("name")),
        "group_name": text(low.get("group")),
        "url": text(low.get("url")),
        "country": text(low.get("country")),
        "raw": jdump(r),
    }


def map_payer(r: dict[str, Any]) -> dict[str, Any]:
    low = _lower(r)
    return {
        "id": to_int(low.get("id")),
        "name": text(low.get("name")),
        "payer_advertisers": text(low.get("payer_advertisers")),
        "payment_provider": text(low.get("payment_provider")),
        "payment_method": text(low.get("payment_method")),
        "threshold": num(low.get("threshold")),
        "address": text(low.get("address")),
        "zip": text(low.get("zip")),
        "city": text(low.get("city")),
        "country": text(low.get("country")),
        "vat": text(low.get("vat")),
        "raw": jdump(r),
    }


_VALIDATION_IDENTITY = {
    "advertiser", "advertiser_name", "advertiserlogin", "advertiserlogin_username",
    "affiliate_system", "data_from_api",
}


def map_data_validation(r: dict[str, Any]) -> dict[str, Any]:
    low = _lower(r)
    columns = {k: v for k, v in low.items() if k not in _VALIDATION_IDENTITY}
    values = [str(v).strip().lower() for v in columns.values() if v is not None]
    return {
        "login_id": to_int(low.get("advertiserlogin")),
        "advertiser_id": to_int(low.get("advertiser")),
        "advertiser_name": text(low.get("advertiser_name")),
        "login_username": text(low.get("advertiserlogin_username")),
        "affiliate_system": text(low.get("affiliate_system")),
        "data_from_api": text(low.get("data_from_api")),
        "columns": jdump(columns),
        "missing_count": values.count("missing"),
        "unavailable_count": values.count("unavailable"),
    }


# ── Fact mappers (one calendar month per API call) ───────────────────────────


def map_adv_earning(r: dict[str, Any], period_month: date, row_no: int) -> dict[str, Any]:
    low = _lower(r)
    return {
        "period_month": period_month,
        "row_no": row_no,
        "date": to_date(low.get("date")),
        "advertiser_id": to_int(low.get("advertiser")),
        "advertiser_name": text(low.get("advertiser_name")),
        "login_id": to_int(low.get("advertiserlogin")),
        "login_username": text(low.get("advertiserlogin_username")),
        "campaign_key": text(low.get("campaignkey")),
        "campaign_name": text(low.get("campaignname")),
        **_measures(low, EARNING_MEASURES),
        "raw": jdump(r),
    }


def map_site_earning(r: dict[str, Any], period_month: date, row_no: int) -> dict[str, Any]:
    low = _lower(r)
    return {
        "period_month": period_month,
        "row_no": row_no,
        "date": to_date(low.get("date")),
        "site_id": to_int(low.get("site")),
        "site_name": text(low.get("site_name")),
        "site_group": text(low.get("site_group")),
        "advertiser_id": to_int(low.get("advertiser")),
        "advertiser_name": text(low.get("advertiser_name")),
        **_measures(low, EARNING_MEASURES),
        "raw": jdump(r),
    }


def _currency(low: dict[str, Any]) -> tuple[str | None, Decimal | None]:
    cur = low.get("currency")
    if isinstance(cur, dict):
        cl = _lower(cur)
        return text(cl.get("code")), num(pick(cl, "exchange", "exchange_rate"))
    return text(cur), num(pick(low, "exchange_rate", "exchange"))


def map_invoice_earning(r: dict[str, Any], period_month: date, row_no: int) -> dict[str, Any]:
    low = _lower(r)
    code, rate = _currency(low)
    return {
        "period_month": period_month,
        "row_no": row_no,
        "date": to_date(low.get("date")),
        "host": text(low.get("host")),
        "username": text(low.get("username")),
        "brand": text(low.get("brand")),
        "campaign": text(low.get("campaign")),
        "payment_id": text(low.get("payment_id")),
        "product": text(low.get("product")),
        "reward_plan": text(low.get("reward_plan")),
        "currency_code": code,
        "exchange_rate": rate,
        "base_currency": text(low.get("base_currency")),
        **_measures(low, MONEY_MEASURES),
        "raw": jdump(r),
    }


def map_payout(r: dict[str, Any], period_month: date, row_no: int) -> dict[str, Any]:
    low = _lower(r)
    code, rate = _currency(low)
    return {
        "period_month": period_month,
        "row_no": row_no,
        "host": text(low.get("host")),
        "username": text(low.get("username")),
        "brand": text(low.get("brand")),
        "campaign": text(low.get("campaign")),
        "currency_code": code,
        "exchange_rate": rate,
        "base_currency": text(low.get("base_currency")),
        **_measures(low, MONEY_MEASURES),
        "raw": jdump(r),
    }


def map_custom_stat(r: dict[str, Any], period_month: date, row_no: int) -> dict[str, Any]:
    low = _lower(r)
    return {
        "period_month": period_month,
        "row_no": row_no,
        "date": to_date(low.get("date")),
        "custom_id": to_int(pick(low, "custom_id", "cust_id")),
        "advertiser_id": to_int(low.get("advertiser")),
        "advertiser_name": text(low.get("advertiser_name")),
        "login_id": to_int(low.get("advertiserlogin")),
        "login_username": text(low.get("advertiserlogin_username")),
        "campaign_key": text(low.get("campaignkey")),
        "campaign_name": text(low.get("campaignname")),
        "clicks": num(low.get("clicks")),
        "unique_clicks": num(low.get("unique_clicks")),
        "signups": num(low.get("signups")),
        "active_players": num(low.get("active_players")),
        "depositors": num(low.get("depositors")),
        "deposits": num(low.get("deposits")),
        "deposit_value": num(low.get("deposit_value")),
        "ndc": num(pick(low, "ndc", "ndcs")),
        "qndc": num(pick(low, "qndc", "qndcs")),
        "ftd": num(pick(low, "ftd", "ftds")),
        "cpa_count": num(pick(low, "cpa_count", "cpas")),
        "rev_income": num(pick(low, "rev_income", "revshare")),
        "cpa_income": num(pick(low, "cpa_income", "cpa_commission")),
        "extra_fee": num(pick(low, "extra_fee", "fees")),
        "bonus": num(low.get("bonus")),
        "net_revenue": num(pick(low, "netrevenue", "net_revenue")),
        "turnover": num(low.get("turnover")),
        "gross_revenue": num(low.get("gross_revenue")),
        "raw": jdump(r),
    }


def map_datamonitor(r: dict[str, Any], day: date, start_row_no: int) -> list[dict[str, Any]]:
    """One issue row per metric: {"FTD": {"current": .., "backup": .., "difference": ..}}."""
    low = _lower(r)
    out = []
    for key, val in r.items():
        if not isinstance(val, dict):
            continue
        vl = _lower(val)
        if not any(k in vl for k in ("current", "backup", "difference")):
            continue
        out.append({
            "date": day,
            "row_no": start_row_no + len(out),
            "advertiser_id": to_int(low.get("advertiser_id")),
            "advertiser": text(low.get("advertiser")),
            "login_id": to_int(low.get("tracker_login_id")),
            "username": text(low.get("username")),
            "campaign_key": text(low.get("campaign_key")),
            "metric": str(key),
            "current_value": num(vl.get("current")),
            "backup_value": num(vl.get("backup")),
            "difference": num(vl.get("difference")),
        })
    return out
