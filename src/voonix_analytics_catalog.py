"""
src/voonix_analytics_catalog.py — declarative catalog of reports and
manageable (create/update/delete) resources.

Single source of truth for three consumers:
  - api/routes.py builds report SQL and validates writes from it,
  - the VoonixReport / VoonixManager widgets render from the schema the
    routes serve (so the UI never offers a field the server would reject),
  - tests/ check it offline.

Every identifier that reaches SQL comes from the constants in this file;
user input only ever selects among them (G-12).

Write field names/semantics come from docs-voonix-api/API_NOTES.md.
Where the docs contradict themselves, the choice is noted inline.

No SDK imports.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

# ── Reports ──────────────────────────────────────────────────────────────────

_EARN_MONEY = [
    ("commission", "Commission", "money"),
    ("rev_income", "Revshare income", "money"),
    ("cpa_income", "CPA income", "money"),
    ("cpl_income", "CPL income", "money"),
    ("extra_fee", "Extra fee", "money"),
]
_EARN_ACTIVITY = [
    ("clicks", "Clicks", "int"),
    ("unique_clicks", "Unique clicks", "int"),
    ("signups", "Signups", "int"),
    ("ftd", "FTDs", "int"),
    ("cpa_count", "CPAs", "int"),
    ("depositors", "Depositors", "int"),
    ("deposits", "Deposits", "int"),
    ("active_players", "Active players", "int"),
    ("deposit_value", "Deposit value", "money"),
    ("net_revenue", "Net revenue", "money"),
    ("bonus", "Bonus", "money"),
    ("turnover", "Turnover", "money"),
]
_INVOICE_MONEY = [
    ("total", "Total", "money"),
    ("raw_total", "Total (original currency)", "money"),
    ("rev_income", "Revshare income", "money"),
    ("cpa_income", "CPA income", "money"),
    ("extra_fee", "Extra fee", "money"),
    ("deduction", "Deduction", "money"),
    ("net_revenue", "Net revenue", "money"),
    ("gross_revenue", "Gross revenue", "money"),
    ("deposit_value", "Deposit value", "money"),
    ("bonus", "Bonus", "money"),
    ("turnover", "Turnover", "money"),
]


def _dim(label: str, expr: str, searchable: bool = False) -> dict[str, Any]:
    return {"label": label, "expr": expr, "searchable": searchable}


REPORTS: dict[str, dict[str, Any]] = {
    "advertiser_earnings": {
        "label": "Advertiser earnings",
        "table": "voonix_advertiser_earnings",
        "date_col": "date",
        "month_grain": False,
        "dims": {
            "month": _dim("Month", "to_char(date, 'YYYY-MM')"),
            "date": _dim("Date", "to_char(date, 'YYYY-MM-DD')"),
            "advertiser": _dim("Advertiser", "advertiser_name", True),
            "login": _dim("Login", "login_username", True),
            "campaign_key": _dim("Campaign key", "campaign_key", True),
            "campaign": _dim("Campaign", "campaign_name", True),
        },
        "measures": _EARN_MONEY + _EARN_ACTIVITY,
        "default_measures": ["commission", "clicks", "signups", "ftd", "cpa_count", "net_revenue"],
        "default_group_by": ["advertiser"],
        "default_sort": "commission",
    },
    "site_earnings": {
        "label": "Site earnings",
        "table": "voonix_site_earnings",
        "date_col": "date",
        "month_grain": False,
        "dims": {
            "month": _dim("Month", "to_char(date, 'YYYY-MM')"),
            "date": _dim("Date", "to_char(date, 'YYYY-MM-DD')"),
            "site": _dim("Site", "site_name", True),
            "site_group": _dim("Site group", "site_group", True),
            "advertiser": _dim("Advertiser", "advertiser_name", True),
        },
        "measures": _EARN_MONEY + _EARN_ACTIVITY,
        "default_measures": ["commission", "clicks", "signups", "ftd", "cpa_count", "net_revenue"],
        "default_group_by": ["site"],
        "default_sort": "commission",
    },
    "invoice_earnings": {
        "label": "Invoiceable earnings",
        "table": "voonix_invoice_earnings",
        "date_col": "date",
        "month_grain": False,
        "dims": {
            "month": _dim("Month", "to_char(date, 'YYYY-MM')"),
            "date": _dim("Date", "to_char(date, 'YYYY-MM-DD')"),
            "brand": _dim("Brand", "brand", True),
            "username": _dim("Username", "username", True),
            "host": _dim("Host", "host", True),
            "campaign": _dim("Campaign", "campaign", True),
            "product": _dim("Product", "product", True),
            "reward_plan": _dim("Reward plan", "reward_plan", True),
            "currency": _dim("Currency", "currency_code", True),
        },
        "measures": _INVOICE_MONEY,
        "default_measures": ["total", "rev_income", "cpa_income", "extra_fee", "deduction", "net_revenue"],
        "default_group_by": ["brand"],
        "default_sort": "total",
    },
    "payouts": {
        "label": "Payouts",
        "table": "voonix_payouts",
        "date_col": "period_month",
        "month_grain": True,
        "dims": {
            "month": _dim("Month", "to_char(period_month, 'YYYY-MM')"),
            "brand": _dim("Brand", "brand", True),
            "username": _dim("Username", "username", True),
            "host": _dim("Host", "host", True),
            "campaign": _dim("Campaign", "campaign", True),
            "currency": _dim("Currency", "currency_code", True),
        },
        "measures": _INVOICE_MONEY,
        "default_measures": ["total", "raw_total", "rev_income", "cpa_income", "deduction"],
        "default_group_by": ["month"],
        "default_sort": "month",
    },
    "custom_stats": {
        "label": "Custom stats",
        "table": "voonix_custom_stats",
        "date_col": "date",
        "month_grain": False,
        "dims": {
            "month": _dim("Month", "to_char(date, 'YYYY-MM')"),
            "date": _dim("Date", "to_char(date, 'YYYY-MM-DD')"),
            "advertiser": _dim("Advertiser", "advertiser_name", True),
            "login": _dim("Login", "login_username", True),
            "campaign_key": _dim("Campaign key", "campaign_key", True),
            "campaign": _dim("Campaign", "campaign_name", True),
        },
        "measures": [
            ("rev_income", "Revshare income", "money"),
            ("cpa_income", "CPA income", "money"),
            ("extra_fee", "Extra fee", "money"),
            ("clicks", "Clicks", "int"),
            ("unique_clicks", "Unique clicks", "int"),
            ("signups", "Signups", "int"),
            ("ftd", "FTDs", "int"),
            ("ndc", "NDCs", "int"),
            ("qndc", "QNDCs", "int"),
            ("cpa_count", "CPAs", "int"),
            ("depositors", "Depositors", "int"),
            ("deposits", "Deposits", "int"),
            ("active_players", "Active players", "int"),
            ("deposit_value", "Deposit value", "money"),
            ("net_revenue", "Net revenue", "money"),
            ("gross_revenue", "Gross revenue", "money"),
            ("bonus", "Bonus", "money"),
            ("turnover", "Turnover", "money"),
        ],
        "default_measures": ["rev_income", "cpa_income", "clicks", "signups", "ftd", "net_revenue"],
        "default_group_by": ["advertiser"],
        "default_sort": "rev_income",
    },
    "datamonitor": {
        "label": "Datamonitor issues",
        "table": "voonix_datamonitor",
        "date_col": "date",
        "month_grain": False,
        "dims": {
            "date": _dim("Date", "to_char(date, 'YYYY-MM-DD')"),
            "advertiser": _dim("Advertiser", "advertiser", True),
            "username": _dim("Login", "username", True),
            "campaign_key": _dim("Campaign key", "campaign_key", True),
            "metric": _dim("Metric", "metric", True),
        },
        "measures": [
            ("issues", "Issues", "int", "COUNT(*)"),
            ("difference", "Difference", "number"),
            ("current_value", "Current", "number"),
            ("backup_value", "Backup", "number"),
        ],
        "default_measures": ["issues", "difference", "current_value", "backup_value"],
        "default_group_by": ["date", "advertiser", "metric"],
        "default_sort": "date",
    },
}


def report_meta(name: str) -> dict[str, Any]:
    rep = REPORTS[name]
    return {
        "name": name,
        "label": rep["label"],
        "month_grain": rep["month_grain"],
        "dims": [{"key": k, "label": d["label"]} for k, d in rep["dims"].items()],
        "measures": [{"key": m[0], "label": m[1], "format": m[2]} for m in rep["measures"]],
        "default_measures": rep["default_measures"],
        "default_group_by": rep["default_group_by"],
        "default_sort": rep["default_sort"],
    }


def build_report_query(
    name: str,
    start: date | None,
    end: date | None,
    group_by: list[str],
    sort: str | None,
    direction: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    if name not in REPORTS:
        raise ValueError(f"Unknown report: {name}")
    rep = REPORTS[name]
    dims = [g for g in group_by if g in rep["dims"]] or list(rep["default_group_by"])
    measures = [(m[0], m[3] if len(m) > 3 else f"SUM({m[0]})") for m in rep["measures"]]

    where: list[str] = []
    params: list[Any] = []
    dc = rep["date_col"]
    if start:
        where.append(f"{dc} >= date_trunc('month', %s::date)::date" if rep["month_grain"] else f"{dc} >= %s")
        params.append(start)
    if end:
        where.append(f"{dc} <= %s")
        params.append(end)
    if search:
        cols = [rep["dims"][d]["expr"] for d in dims if rep["dims"][d]["searchable"]]
        if cols:
            where.append("(" + " OR ".join(f"{c} ILIKE %s" for c in cols) + ")")
            params.extend([f"%{search}%"] * len(cols))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    select_dims = [f'{rep["dims"][d]["expr"]} AS "{d}"' for d in dims]
    select_measures = [f'{expr} AS "{key}"' for key, expr in measures]
    group_sql = "GROUP BY " + ", ".join(str(i + 1) for i in range(len(dims)))

    allowed_sort = set(dims) | {m[0] for m in measures}
    sort_key = sort if sort in allowed_sort else (
        rep["default_sort"] if rep["default_sort"] in allowed_sort else dims[0]
    )
    dir_sql = "ASC" if (direction or "").lower() == "asc" else "DESC"

    table = rep["table"]
    return {
        "dims": dims,
        "sort": sort_key,
        "dir": dir_sql.lower(),
        "params": params,
        "rows_sql": (
            f"SELECT {', '.join(select_dims + select_measures)} FROM {table} {where_sql} "
            f'{group_sql} ORDER BY "{sort_key}" {dir_sql} NULLS LAST LIMIT %s OFFSET %s'
        ),
        "count_sql": f"SELECT COUNT(*) AS n FROM (SELECT 1 FROM {table} {where_sql} {group_sql}) t",
        "totals_sql": f"SELECT {', '.join(select_measures)} FROM {table} {where_sql}",
        "range_sql": f"SELECT MIN({dc}) AS min_date, MAX({dc}) AS max_date FROM {table}",
        "limit": limit,
        "offset": offset,
    }


# ── Manageable resources ─────────────────────────────────────────────────────

DEAL_TYPES = ["REV", "CPA", "CPL", "REV-CPA", "REV-CPL", "CPA-CPL"]
# Campaign deals list five types (no REV-CPL) in the docs.
CAMPAIGN_DEAL_TYPES = ["REV", "REV-CPA", "CPA", "CPA-CPL", "CPL"]

RESUME_IMPORT_WARNING = (
    "Voonix warns: this clears login errors so importing resumes. Only use it "
    "if you are certain the login credentials are correct — otherwise the "
    "operator may ban or block the account."
)


def F(name: str, label: str, type: str = "text", **kw: Any) -> dict[str, Any]:
    field = {"name": name, "label": label, "type": type}
    field.update(kw)
    return field


def _opts(values: list[str]) -> list[dict[str, str]]:
    return [{"value": v, "label": v} for v in values]


def C(key: str, label: str, format: str = "text") -> dict[str, str]:
    return {"key": key, "label": label, "format": format}


def _advertiser_fields(create: bool) -> list[dict[str, Any]]:
    return [
        F("name", "Name", required=create, help="Must be unique in Voonix."),
        F("description", "Description", "textarea"),
        F("affiliate_system", "Affiliate system", "select", required=create,
          options_from="affiliate_systems",
          help="Case-sensitive; must match the name in Voonix."),
        F("affiliate_system_currency", "Currency", required=create, help="Currency code, e.g. EUR."),
        F("affiliate_login_url", "Affiliate login URL", required=create,
          help="The exact URL of the affiliate program's login page."),
        F("affiliate_market", "Market", help="E.g. iGaming. Case-sensitive."),
        F("affiliate_operator", "Operator"),
        F("affiliate_system_brand", "Brand ID", help="Required by some affiliate systems."),
        F("affiliate_system_extra", "Brand ID extra"),
        F("affiliate_group", "Group"),
        F("contact_name", "Contact name"),
        F("contact_email", "Contact email"),
        F("contact_skype", "Contact Skype"),
        F("contact_note", "Contact note", "textarea"),
    ]


def _login_fields(create: bool) -> list[dict[str, Any]]:
    return [
        F("username", "Username", required=create),
        F("password", "Password", "password",
          help="Write-only. Leave blank to keep the current password."),
        F("key1", "Key 1", "password", help="Write-only. Leave blank to keep the current value."),
        F("key2", "Key 2", "password", help="Write-only. Leave blank to keep the current value."),
        F("type", "Deal type", "select", required=create, options=_opts(DEAL_TYPES)),
        F("rev", "Revshare %", "number", help="Most often 100, because Voonix takes commission."),
        F("cpa", "CPA value", "number"),
        F("cpl", "CPL value", "number"),
        F("currency", "Currency", help="Overrides the advertiser's currency."),
        F("group", "Group"),
        F("status", "Custom status"),
        F("cosmetic_deal", "Cosmetic deal", help="Display-only deal text."),
        F("note", "Note", "textarea"),
        F("baseline", "Baseline for CPAs", "toggle", help="Stops Voonix using FTDs."),
        F("paused", "Paused", "toggle", help="A paused account imports no data."),
        F("lock", "Lock up to month", "month",
          help="No data is imported up to and including this month."),
    ]


_CUSTOM_STAT_METRICS = [
    # (write field, label, stored column, integer?) — mapping proven by the
    # docs' create example (values 1..18) against the list response.
    ("clicks", "Clicks", "clicks", True),
    ("unique_clicks", "Unique clicks", "unique_clicks", True),
    ("signups", "Signups", "signups", True),
    ("active_players", "Active players", "active_players", True),
    ("depositors", "Depositors", "depositors", True),
    ("deposits", "Deposits", "deposits", True),
    ("deposit_value", "Deposit value", "deposit_value", False),
    ("bonus", "Bonus", "bonus", False),
    ("ndcs", "NDCs", "ndc", True),
    ("qndcs", "QNDCs", "qndc", True),
    ("ftds", "FTDs", "ftd", True),
    ("cpas", "CPAs", "cpa_count", True),
    ("cpa_commission", "CPA commission", "cpa_income", False),
    ("fees", "Fees", "extra_fee", False),
    ("turnover", "Turnover", "turnover", False),
    ("gross_revenue", "Gross revenue", "gross_revenue", False),
    ("net_revenue", "Net revenue", "net_revenue", False),
    ("revshare", "Revshare", "rev_income", False),
]


def _metric_fields() -> list[dict[str, Any]]:
    return [F(w, label, "number", integer=is_int, section="Metrics")
            for w, label, _col, is_int in _CUSTOM_STAT_METRICS]


def _custom_column_fields() -> list[dict[str, Any]]:
    # Docs list "custom_columns1" but every example sends custom_column1..10
    # nested under "custom_columns" in JSON mode — the examples win.
    return [F(f"custom_column{i}", f"Custom column {i}", "number",
              pack="custom_columns", section="Custom columns")
            for i in range(1, 11)]


RESOURCES: dict[str, dict[str, Any]] = {
    "advertisers": {
        "label": "Advertisers",
        "noun": "advertiser",
        "table": "voonix_advertisers",
        "pk": ["id"],
        "columns": [
            C("id", "ID", "int"), C("name", "Name"), C("affiliate_system", "Affiliate system"),
            C("market", "Market"), C("operator", "Operator"), C("group_name", "Group"),
            C("currency", "Currency"), C("url_error", "URL error", "bool"),
        ],
        "extra_columns": ["description", "login_url", "brand_id", "brand_extra",
                          "contact_name", "contact_email", "contact_skype", "contact_note"],
        "search": ["name", "affiliate_system", "operator", "group_name", "market"],
        "default_sort": "name",
        "refresh": ["advertisers"],
        "ops": {
            "create": {
                "label": "New advertiser", "kind": "create",
                "api_report": "advertisers", "api_op": "create",
                "fields": _advertiser_fields(create=True),
            },
            "update": {
                "label": "Edit", "kind": "row",
                "api_report": "advertisers", "api_op": "update",
                "fields": [F("id", "Advertiser ID", "number", integer=True, required=True, readonly=True)]
                + _advertiser_fields(create=False),
                "prefill": {
                    "id": "id", "name": "name", "description": "description",
                    "affiliate_system": "affiliate_system", "affiliate_system_currency": "currency",
                    "affiliate_login_url": "login_url", "affiliate_market": "market",
                    "affiliate_operator": "operator", "affiliate_system_brand": "brand_id",
                    "affiliate_system_extra": "brand_extra", "affiliate_group": "group_name",
                    "contact_name": "contact_name", "contact_email": "contact_email",
                    "contact_skype": "contact_skype", "contact_note": "contact_note",
                },
            },
            "delete": {
                "label": "Delete", "kind": "row", "danger": True,
                "confirm": "This deletes the advertiser in Voonix.",
                "api_report": "advertisers", "api_op": "delete",
                "fields": [F("id", "Advertiser ID", "number", integer=True, required=True, readonly=True)],
                "prefill": {"id": "id"},
            },
        },
    },
    "logins": {
        "label": "Logins",
        "noun": "login",
        "table": "voonix_logins",
        "pk": ["id"],
        "columns": [
            C("id", "ID", "int"), C("advertiser_name", "Advertiser"), C("username", "Username"),
            C("group_name", "Group"), C("status", "Status"), C("currency", "Currency"),
            C("deal_type", "Deal"), C("deal_rev", "Rev %", "number"), C("deal_cpa", "CPA", "number"),
            C("deal_cpl", "CPL", "number"), C("paused", "Paused", "bool"), C("error", "Error", "bool"),
        ],
        "extra_columns": ["optional_id", "advertiser_id", "note", "cosmetic_deal", "baseline", "locked"],
        "search": ["advertiser_name", "username", "group_name", "status", "optional_id"],
        "default_sort": "advertiser_name",
        "refresh": ["logins"],
        "ops": {
            "create": {
                "label": "New login", "kind": "create",
                "api_report": "advertiserlogins", "api_op": "create",
                "fields": [
                    F("advertiser_id", "Advertiser", "select", integer=True, required=True,
                      options_from="advertisers"),
                ] + _login_fields(create=True),
            },
            "update": {
                "label": "Edit", "kind": "row",
                "api_report": "advertiserlogins", "api_op": "update",
                "fields": [
                    F("id", "Login ID", "number", integer=True, required=True, readonly=True),
                ] + _login_fields(create=False) + [
                    F("resume_import", "Resume import (clear login errors)", "toggle",
                      bool_style="bool", send_if_true=True, danger=True, help=RESUME_IMPORT_WARNING),
                ],
                "prefill": {
                    "id": "id", "username": "username", "type": "deal_type", "rev": "deal_rev",
                    "cpa": "deal_cpa", "cpl": "deal_cpl", "currency": "currency", "group": "group_name",
                    "status": "status", "cosmetic_deal": "cosmetic_deal", "note": "note",
                    "baseline": "baseline", "paused": "paused", "lock": "locked",
                },
            },
            "delete": {
                "label": "Delete", "kind": "row", "danger": True,
                "confirm": "This deletes the login in Voonix.",
                "api_report": "advertiserlogins", "api_op": "delete",
                "fields": [F("id", "Login ID", "number", integer=True, required=True, readonly=True)],
                "prefill": {"id": "id"},
            },
        },
    },
    "history_deals": {
        "label": "History deals",
        "noun": "history deal",
        "table": "voonix_login_history_deals",
        "pk": ["login_id", "start_month"],
        "columns": [
            C("login_id", "Login ID", "int"), C("advertiser_name", "Advertiser"),
            C("login_username", "Username"), C("start_month", "Starts", "month"), C("type", "Deal"),
            C("rev", "Rev %", "number"), C("cpa", "CPA", "number"), C("cpl", "CPL", "number"),
        ],
        "extra_columns": [],
        "search": ["advertiser_name", "login_username", "type"],
        "default_sort": "login_id",
        "refresh": ["logins"],
        "ops": {
            "create": {
                "label": "New history deal", "kind": "create",
                "api_report": "historydeals", "api_op": "create",
                "fields": [
                    F("id", "Login", "select", integer=True, required=True, options_from="logins"),
                    F("start_month", "Starts in month", "month", required=True),
                    F("type", "Deal type", "select", required=True, options=_opts(DEAL_TYPES)),
                    F("rev", "Revshare %", "number", help="Defaults to 100 in Voonix."),
                    F("cpa", "CPA value", "number"),
                    F("cpl", "CPL value", "number"),
                    F("keep_original", "Keep original login deal", "toggle", bool_style="bool",
                      default=True,
                      help="On: Voonix copies the current login deal to 2000-01 so this deal only "
                           "applies from the chosen month."),
                ],
            },
            "update": {
                "label": "Edit", "kind": "row",
                "api_report": "historydeals", "api_op": "update",
                "fields": [
                    F("login", "Login ID", "number", integer=True, required=True, readonly=True),
                    F("start_month", "Starts in month", "month", required=True, readonly=True),
                    F("type", "Deal type", "select", required=True, options=_opts(DEAL_TYPES)),
                    F("rev", "Revshare %", "number"),
                    F("cpa", "CPA value", "number"),
                    F("cpl", "CPL value", "number"),
                ],
                "prefill": {"login": "login_id", "start_month": "start_month", "type": "type",
                            "rev": "rev", "cpa": "cpa", "cpl": "cpl"},
            },
            "delete": {
                "label": "Delete", "kind": "row", "danger": True,
                "confirm": "This deletes the history deal in Voonix.",
                "api_report": "historydeals", "api_op": "delete",
                "fields": [
                    F("login", "Login ID", "number", integer=True, required=True, readonly=True),
                    F("start_month", "Starts in month", "month", required=True, readonly=True),
                ],
                "prefill": {"login": "login_id", "start_month": "start_month"},
            },
        },
    },
    "campaigns": {
        "label": "Campaigns",
        "noun": "campaign",
        "table": "voonix_campaigns",
        "pk": ["id"],
        "columns": [
            C("id", "ID"), C("key", "Key"), C("name", "Name"), C("advertiser_name", "Advertiser"),
            C("username", "Login"), C("site_name", "Site"), C("alias", "Alias"),
            C("group_name", "Group"), C("note", "Note"),
        ],
        "extra_columns": ["login_id", "campaign_optional_id"],
        "search": ["key", "name", "advertiser_name", "username", "alias", "group_name", "site_name"],
        "default_sort": "advertiser_name",
        "refresh": ["campaigns"],
        "ops": {
            "update": {
                "label": "Edit", "kind": "row",
                "api_report": "campaigns", "api_op": "update",
                "fields": [
                    F("id", "Campaign ID", required=True, readonly=True),
                    F("alias", "Alias"),
                    F("group", "Group"),
                    F("note", "Note", "textarea"),
                ],
                "prefill": {"id": "id", "alias": "alias", "group": "group_name", "note": "note"},
            },
            "mark_deleted": {
                "label": "Delete", "kind": "row", "danger": True,
                "confirm": "This marks the campaign as deleted in Voonix (it can be restored in Voonix).",
                "api_report": "campaigns", "api_op": "update",
                "fields": [F("id", "Campaign ID", required=True, readonly=True)],
                "prefill": {"id": "id"},
                "fixed": {"deleted": 1},
            },
        },
    },
    "campaign_deals": {
        "label": "Campaign deals",
        "noun": "campaign deal",
        "table": "voonix_campaign_deals",
        "pk": ["id"],
        "columns": [
            C("id", "Deal ID"), C("campaign_key", "Campaign key"), C("campaign_name", "Campaign"),
            C("login_id", "Login ID", "int"), C("start_date", "Starts", "date"), C("type", "Deal"),
            C("rev", "Rev %", "number"), C("cpa", "CPA", "number"), C("cpl", "CPL", "number"),
        ],
        "extra_columns": ["campaign_id"],
        "search": ["campaign_key", "campaign_name", "type"],
        "default_sort": "campaign_name",
        "refresh": ["campaigns"],
        "ops": {
            "create": {
                "label": "New campaign deal", "kind": "create",
                "api_report": "campaigns", "api_op": "create_deal",
                "fields": [
                    F("fk_login", "Login", "select", integer=True, required=True, options_from="logins"),
                    F("fk_ckey", "Campaign key", one_of="campaign"),
                    F("campaign_optional_id", "Campaign optional ID", one_of="campaign"),
                    F("start_month", "Starts on", "date", required=True, help="Usually the 1st of a month."),
                    F("type", "Deal type", "select", required=True, options=_opts(CAMPAIGN_DEAL_TYPES)),
                    F("REV", "Revshare %", "number", integer=True),
                    F("CPA", "CPA value", "number", integer=True),
                    F("CPL", "CPL value", "number", integer=True),
                ],
            },
            "update": {
                "label": "Edit", "kind": "row",
                "api_report": "campaigns", "api_op": "update_deal",
                "fields": [
                    F("id", "Deal ID", required=True, readonly=True),
                    F("start_month", "Starts on", "date"),
                    F("type", "Deal type", "select", options=_opts(CAMPAIGN_DEAL_TYPES)),
                    F("REV", "Revshare %", "number", integer=True),
                    F("CPA", "CPA value", "number", integer=True),
                    F("CPL", "CPL value", "number", integer=True),
                ],
                "prefill": {"id": "id", "start_month": "start_date", "type": "type",
                            "REV": "rev", "CPA": "cpa", "CPL": "cpl"},
            },
            "delete": {
                "label": "Delete", "kind": "row", "danger": True,
                "confirm": "This deletes the campaign deal in Voonix.",
                "api_report": "campaigns", "api_op": "delete_deal",
                "fields": [F("id", "Deal ID", required=True, readonly=True)],
                "prefill": {"id": "id"},
            },
        },
    },
    "sites": {
        "label": "Sites",
        "noun": "site",
        "table": "voonix_sites",
        "pk": ["id"],
        "columns": [C("id", "ID", "int"), C("name", "Name"), C("group_name", "Group"),
                    C("url", "URL"), C("country", "Country")],
        "extra_columns": [],
        "search": ["name", "group_name", "url", "country"],
        "default_sort": "name",
        "refresh": ["sites"],
        "ops": {
            "create": {
                "label": "New site", "kind": "create",
                "api_report": "sites", "api_op": "create",
                "fields": [
                    F("name", "Name", required=True, help="Must be unique in Voonix."),
                    F("group", "Group"),
                    F("url", "URL"),
                    F("country", "Country code", help="E.g. DK."),
                ],
            },
            "update": {
                "label": "Edit", "kind": "row",
                "api_report": "sites", "api_op": "update",
                "fields": [
                    F("id", "Site ID", "number", integer=True, required=True, readonly=True),
                    F("name", "Name"),
                    F("group", "Group"),
                    F("url", "URL"),
                    F("country", "Country code"),
                ],
                "prefill": {"id": "id", "name": "name", "group": "group_name", "url": "url",
                            "country": "country"},
            },
        },
    },
    "custom_stats": {
        "label": "Custom stats",
        "noun": "custom stat",
        "table": "voonix_custom_stats",
        "pk": ["period_month", "row_no"],
        "columns": [
            C("date", "Date", "date"), C("custom_id", "Stat ID", "int"),
            C("advertiser_name", "Advertiser"), C("login_username", "Login"),
            C("campaign_key", "Campaign key"), C("campaign_name", "Campaign"),
            C("clicks", "Clicks", "int"), C("signups", "Signups", "int"), C("ftd", "FTDs", "int"),
            C("cpa_count", "CPAs", "int"), C("cpa_income", "CPA income", "money"),
            C("rev_income", "Revshare", "money"), C("net_revenue", "Net revenue", "money"),
        ],
        "extra_columns": ["login_id", "unique_clicks", "active_players", "depositors", "deposits",
                          "deposit_value", "bonus", "ndc", "qndc", "extra_fee", "turnover",
                          "gross_revenue"],
        "search": ["advertiser_name", "login_username", "campaign_key", "campaign_name"],
        "default_sort": "date",
        "refresh": ["period:custom_stats", "period:advertiser_earnings"],
        "ops": {
            "create": {
                "label": "New custom stat", "kind": "create",
                "api_report": "customstats", "api_op": "create",
                "fields": [
                    F("fk_login", "Login", "select", integer=True, required=True, options_from="logins"),
                    F("date", "Date", "date", required=True),
                    F("fk_ckey", "Existing campaign key", one_of="campaign",
                      help="Add the stat to this campaign…"),
                    F("camp_name", "…or create a campaign named", one_of="campaign"),
                ] + _metric_fields() + _custom_column_fields(),
            },
            "update": {
                "label": "Edit", "kind": "row",
                "api_report": "customstats", "api_op": "update",
                "fields": [
                    F("cust_id", "Stat ID", "number", integer=True, required=True, readonly=True),
                    F("fk_login", "Login ID", "number", integer=True, required=True, readonly=True),
                    F("fk_ckey", "Campaign key", required=True, readonly=True),
                    F("date", "Date", "date"),
                ] + _metric_fields() + _custom_column_fields(),
                "prefill": {
                    "cust_id": "custom_id", "fk_login": "login_id", "fk_ckey": "campaign_key",
                    "date": "date",
                    **{w: col for w, _l, col, _i in _CUSTOM_STAT_METRICS},
                },
            },
            "delete": {
                "label": "Delete", "kind": "row", "danger": True,
                "confirm": "This deletes the custom stat in Voonix.",
                "api_report": "customstats", "api_op": "delete",
                "fields": [
                    F("cust_id", "Stat ID", "number", integer=True, required=True, readonly=True),
                    F("date", "Date", "date", readonly=True, local_only=True),
                ],
                "prefill": {"cust_id": "custom_id", "date": "date"},
            },
        },
    },
    "payers": {
        "label": "Payers",
        "noun": "payer",
        "table": "voonix_payers",
        "pk": ["id"],
        "columns": [
            C("id", "ID", "int"), C("name", "Name"), C("payer_advertisers", "Advertiser IDs"),
            C("payment_provider", "Provider"), C("payment_method", "Method"),
            C("threshold", "Threshold", "number"), C("city", "City"), C("country", "Country"),
            C("vat", "VAT"),
        ],
        "extra_columns": [],
        "search": ["name", "payment_provider", "payment_method", "country"],
        "default_sort": "name",
        "refresh": [],
        "ops": {},
    },
    "data_validation": {
        "label": "Data validation",
        "noun": "login",
        "table": "voonix_data_validation",
        "pk": ["login_id"],
        "columns": [
            C("login_id", "Login ID", "int"), C("advertiser_name", "Advertiser"),
            C("login_username", "Username"), C("affiliate_system", "Affiliate system"),
            C("data_from_api", "Import method"), C("missing_count", "Missing columns", "int"),
            C("unavailable_count", "Unavailable columns", "int"),
        ],
        "extra_columns": [],
        "search": ["advertiser_name", "login_username", "affiliate_system"],
        "default_sort": "missing_count",
        "refresh": [],
        "ops": {},
    },
    "affiliate_systems": {
        "label": "Affiliate systems",
        "noun": "affiliate system",
        "table": "voonix_affiliate_systems",
        "pk": ["id"],
        "columns": [
            C("id", "ID", "int"), C("name", "Name"), C("has_api", "API", "bool"),
            C("daily", "Daily data", "bool"), C("brand_id_required", "Brand ID required", "bool"),
            C("igaming", "iGaming", "bool"), C("report_names", "Reports"),
        ],
        "extra_columns": [],
        "search": ["name", "report_names"],
        "default_sort": "name",
        "refresh": [],
        "ops": {},
    },
}

# Dropdown sources for `options_from`. Fixed SQL; no user input.
OPTION_SOURCES: dict[str, str] = {
    "advertisers": "SELECT id::text AS value, name AS label FROM voonix_advertisers ORDER BY name LIMIT 5000",
    "logins": (
        "SELECT id::text AS value, concat_ws(' — ', advertiser_name, username, '#' || id::text) AS label "
        "FROM voonix_logins ORDER BY advertiser_name, username LIMIT 5000"
    ),
    "affiliate_systems": "SELECT name AS value, name AS label FROM voonix_affiliate_systems ORDER BY name",
}


def select_columns(resource: str) -> list[str]:
    res = RESOURCES[resource]
    cols: list[str] = []
    for c in (
        [c["key"] for c in res["columns"]]
        + res["extra_columns"]
        + res["pk"]
        + [col for op in res["ops"].values() for col in op.get("prefill", {}).values()]
    ):
        if c not in cols:
            cols.append(c)
    return cols


def resource_schema(resource: str) -> dict[str, Any]:
    res = RESOURCES[resource]
    return {
        "resource": resource,
        "label": res["label"],
        "noun": res["noun"],
        "pk": res["pk"],
        "columns": res["columns"],
        "default_sort": res["default_sort"],
        "ops": {
            key: {k: v for k, v in op.items() if k not in ("api_report", "api_op", "fixed")}
            for key, op in res["ops"].items()
        },
    }


def build_rows_query(
    resource: str, search: str | None, sort: str | None, direction: str | None,
    limit: int, offset: int,
) -> dict[str, Any]:
    if resource not in RESOURCES:
        raise ValueError(f"Unknown resource: {resource}")
    res = RESOURCES[resource]
    cols = select_columns(resource)
    where, params = [], []
    if search:
        where.append("(" + " OR ".join(f"{c}::text ILIKE %s" for c in res["search"]) + ")")
        params.extend([f"%{search}%"] * len(res["search"]))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sort_col = sort if sort in cols else res["default_sort"]
    dir_sql = "DESC" if (direction or "").lower() == "desc" else "ASC"
    pk_order = ", ".join(res["pk"])
    table = res["table"]
    return {
        "params": params,
        "sort": sort_col,
        "dir": dir_sql.lower(),
        "rows_sql": (
            f"SELECT {', '.join(cols)} FROM {table} {where_sql} "
            f"ORDER BY {sort_col} {dir_sql} NULLS LAST, {pk_order} LIMIT %s OFFSET %s"
        ),
        "count_sql": f"SELECT COUNT(*) AS n FROM {table} {where_sql}",
        "limit": limit,
        "offset": offset,
    }


# ── Write validation ─────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^(\d{4}-\d{2})(-\d{2})?$")
SECRET_WRITE_FIELDS = ("password", "key1", "key2")


def _coerce(field: dict[str, Any], raw: Any) -> Any:
    ftype = field["type"]
    if isinstance(raw, str):
        raw = raw.strip()
    if raw is None or raw == "":
        return None
    if ftype in ("date", "month") and str(raw).startswith("0000"):
        return None  # Voonix writes "no date" as 0000-00-00
    if ftype in ("text", "textarea", "password"):
        s = str(raw)
        if len(s) > 5000:
            raise ValueError("is too long")
        return s
    if ftype == "number":
        try:
            d = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            raise ValueError("must be a number") from None
        if not d.is_finite():
            raise ValueError("must be a number")
        integral = d == d.to_integral_value()
        if field.get("integer"):
            if not integral:
                raise ValueError("must be a whole number")
            return int(d)
        return int(d) if integral else float(d)
    if ftype == "toggle":
        on = raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
        return on if field.get("bool_style") == "bool" else (1 if on else 0)
    if ftype == "select":
        s = str(raw)
        options = field.get("options")
        if options and s not in {o["value"] for o in options}:
            raise ValueError("is not one of the allowed choices")
        if field.get("integer"):
            try:
                return int(s)
            except ValueError:
                raise ValueError("must be a whole number") from None
        return s
    if ftype == "date":
        s = str(raw)[:10]
        if not _DATE_RE.match(s):
            raise ValueError("must be a date (YYYY-MM-DD)")
        try:
            date.fromisoformat(s)
        except ValueError:
            raise ValueError("is not a real date") from None
        return s
    if ftype == "month":
        m = _MONTH_RE.match(str(raw))
        if not m or not 1 <= int(m.group(1)[5:7]) <= 12:
            raise ValueError("must be a month (YYYY-MM)")
        return m.group(1)
    raise ValueError(f"has unsupported type {ftype}")


def validate_write(
    resource: str, op_key: str, row: dict[str, Any] | None
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """Return (api_report, api_op, payload, local_context) or raise ValueError.

    Only fields declared on the op reach the payload; everything else in
    `row` is ignored.
    """
    res = RESOURCES.get(resource)
    if res is None:
        raise ValueError(f"Unknown resource: {resource}")
    op = res["ops"].get(op_key)
    if op is None:
        raise ValueError(f"{res['label']} does not support '{op_key}'")
    row = row or {}
    payload: dict[str, Any] = {}
    local: dict[str, Any] = {}
    errors: list[str] = []
    groups: dict[str, list[tuple[dict[str, Any], Any]]] = {}

    for field in op["fields"]:
        name = field["name"]
        try:
            val = _coerce(field, row.get(name))
        except ValueError as e:
            errors.append(f"{field['label']} {e}")
            continue
        if field.get("one_of"):
            groups.setdefault(field["one_of"], []).append((field, val))
        if val is None:
            if field.get("required"):
                errors.append(f"{field['label']} is required")
            continue
        if field.get("send_if_true") and val in (0, False):
            continue
        if field.get("local_only"):
            local[name] = val
        elif field.get("pack"):
            payload.setdefault(field["pack"], {})[name] = val
        else:
            payload[name] = val

    for items in groups.values():
        if all(v is None for _f, v in items):
            errors.append("Provide one of: " + " or ".join(f["label"] for f, _v in items))

    if errors:
        raise ValueError("; ".join(errors))

    payload.update(op.get("fixed", {}))
    if resource == "custom_stats" and op_key == "create" and "fk_ckey" not in payload:
        payload["create_campaign"] = True
    return op["api_report"], op["api_op"], payload, local


def redact(payload: Any) -> Any:
    if isinstance(payload, list):
        return [redact(p) for p in payload]
    if isinstance(payload, dict):
        return {k: ("***" if k in SECRET_WRITE_FIELDS and v not in (None, "") else redact(v))
                for k, v in payload.items()}
    return payload
