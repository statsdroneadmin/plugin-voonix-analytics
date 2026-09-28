"""
tests/test_voonix_analytics.py — offline tests for the pure modules.

Fixtures are the response examples from docs-voonix-api/API_NOTES.md,
hand-corrected where the docs' JSON is invalid (trailing commas, a missing
quote). They are the only fixtures until a live account is available.

Run:  python3 tests/test_voonix_analytics.py     (no pytest, no SDK needed)
"""

from __future__ import annotations

import sys
import traceback
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import voonix_analytics_catalog as cat  # noqa: E402
import voonix_analytics_mappers as mp  # noqa: E402
from voonix_analytics_client import VoonixClient, VoonixError, normalise_base_url  # noqa: E402


def keys_match(row: dict, table: str) -> None:
    assert tuple(row.keys()) == mp.TABLE_COLUMNS[table], (
        f"{table}: mapper keys {tuple(row.keys())} != TABLE_COLUMNS"
    )


# ── Envelopes ────────────────────────────────────────────────────────────────


def test_flatten_shapes():
    assert mp.rows_from({"data": [{"id": "1"}]}) == [{"id": "1"}]
    assert mp.rows_from({"data": {"3": {"id": "3"}, "4": {"id": "4"}}}) == [{"id": "3"}, {"id": "4"}]
    assert mp.rows_from({"data": {"2022-03": [{"a": 1}], "2022-04": [{"a": 2}]}}) == [{"a": 1}, {"a": 2}]
    assert mp.rows_from({"logins": {"1": {"id": "1"}}}, "logins", "data") == [{"id": "1"}]
    assert mp.rows_from({"data": {}}) == []
    assert mp.rows_from({"http": {"code": 200}}) == []


def test_scalars():
    assert mp.num("3071.0010") == Decimal("3071.0010")
    assert mp.num("") is None and mp.num("abc") is None
    assert mp.to_int("371") == 371 and mp.to_int("custom_3122") is None
    assert mp.to_date("0000-00-00") is None
    assert mp.to_date("2024-12") == date(2024, 12, 1)
    assert mp.to_ts("0000-00-00 00:00:00") is None
    assert mp.to_bool("0") is False and mp.to_bool("1") is True


# ── Mappers against doc examples ─────────────────────────────────────────────


def test_login_strips_secrets_and_maps_deals():
    doc = {"logins": {"1": {
        "id": "1", "optional_id": "#ABC1234", "username": "Voonix", "group": "Anna",
        "status": "Confirmed", "key1": "jdk261sjo54dkpsdl91425", "key2": "2345353sdfsdfs",
        "currency": "JPY", "note": "Notes", "cosmetic_deal": "150CPA + 20CPL", "locked": "2025-01-01",
        "paused": "1", "baseline": "1", "created_at": "2025-10-15 15:03:15",
        "updated_at": "0000-00-00 00:00:00", "error": "0",
        "deal": {"type": "REV-CPA", "rev": "100", "cpa": "150", "cpl": "0"},
        "history_deal": [{"start_month": "2019-01-01", "type": "CPL", "cpl": "20"},
                         {"start_month": "2020-04-01", "type": "CPA", "cpa": "150"}],
        "advertiser_id": "1", "advertiser_name": "10Bet", "advertiser_affiliate_system": "Omarsys",
    }}}
    raw = mp.rows_from(doc, "logins", "data")[0]
    row, history = mp.map_login(raw)
    keys_match(row, "voonix_logins")
    assert "jdk261" not in row["raw"] and "2345353" not in row["raw"]
    assert row["deal_type"] == "REV-CPA" and row["deal_cpa"] == Decimal("150")
    assert row["paused"] is True and row["error"] is False and row["voonix_updated_at"] is None
    assert [h["start_month"] for h in history] == [date(2019, 1, 1), date(2020, 4, 1)]
    keys_match(history[0], "voonix_login_history_deals")


def test_login_v2_style_history_dict():
    _row, history = mp.map_login({"id": "5", "history_deal": {"2019-01-01": {"type": "REV", "rev": "30"}}})
    assert history[0]["start_month"] == date(2019, 1, 1) and history[0]["rev"] == Decimal("30")


def test_campaign_and_deals():
    doc = {"data": [{
        "id": "2", "key": "535249", "name": "DE stream", "login_id": "1121", "username": "matchempirehyb001",
        "advertiser_id": "788", "advertiser_name": "MioMedia MyEmpire MV", "campaign_optional_id": "test",
        "sites": {"site_id": "1", "site_name": "Test site"},
        "campaign_deals": [{"id": "1", "start_date": "2024-04-01", "type": "CPA", "CPA": "150"}],
        "alias": "testing ", "group": "testing ", "note": "testing",
    }]}
    row, deals = mp.map_campaign(mp.rows_from(doc)[0])
    keys_match(row, "voonix_campaigns")
    assert row["site_name"] == "Test site" and row["alias"] == "testing"
    assert deals[0]["cpa"] == Decimal("150") and deals[0]["start_date"] == date(2024, 4, 1)
    keys_match(deals[0], "voonix_campaign_deals")


def test_advertiser_earnings_flat():
    doc = {"data": {"2022-03": [{
        "advertiser": 319, "advertiser_name": "advertiser", "advertiserlogin": 416,
        "advertiserlogin_username": "username", "campaignkey": "Voonix", "campaignname": "Campaign name",
        "date": "2022-03-21", "clicks": 1, "signups": 0, "active_players": 0, "deposits": 0, "FTD": 0,
        "CPA_count": 0, "unique_clicks": 0, "depositors": 0, "deposit_value": 0, "REV_income": 12.5,
        "bonus": 0, "netrevenue": 0, "turnover": 0, "CPA_income": 100, "CPL_income": 0, "Extra_fee": "0",
    }]}}
    row = mp.map_adv_earning(mp.rows_from(doc)[0], date(2022, 3, 1), 0)
    keys_match(row, "voonix_advertiser_earnings")
    assert row["rev_income"] == Decimal("12.5") and row["cpa_income"] == Decimal("100")
    assert row["login_id"] == 416 and row["campaign_key"] == "Voonix"


def test_site_earnings():
    r = {"site": 123, "site_name": "Site name", "site_group": "Group name", "advertiser": 123,
         "advertiser_name": "Advertiser name", "date": "2022-03-01", "clicks": 52, "FTD": 20,
         "REV_income": 241.8753, "custom_column1": 0, "Extra_fee": 88.7782}
    row = mp.map_site_earning(r, date(2022, 3, 1), 7)
    keys_match(row, "voonix_site_earnings")
    assert row["ftd"] == Decimal("20") and row["row_no"] == 7


def test_invoice_earnings_currency_object():
    r = {"host": "example.com", "username": "user@example.com", "brand": "Good Brand",
         "campaign": "Summer2023", "payment_id": 1000, "currency": {"code": "USD", "exchange": 0.92},
         "product": "Bingo", "reward_plan": "80% Rev", "date": "2023-05-02", "base_currency": "EUR",
         "total": 9.2, "raw_total": 10, "deduction": 9.2}
    row = mp.map_invoice_earning(r, date(2023, 5, 1), 0)
    keys_match(row, "voonix_invoice_earnings")
    assert row["currency_code"] == "USD" and row["exchange_rate"] == Decimal("0.92")
    assert row["payment_id"] == "1000"


def test_payout():
    r = {"host": "voonix.net", "username": "user_name", "brand": "brand_name", "campaign": "campaign_key",
         "currency": "EUR", "base_currency": "EUR", "exchange_rate": 1, "total": 456.789, "raw_total": 880.28934723}
    row = mp.map_payout(r, date(2022, 10, 1), 0)
    keys_match(row, "voonix_payouts")
    assert row["currency_code"] == "EUR" and row["total"] == Decimal("456.789")


def test_custom_stat_list_mapping_matches_doc_values():
    # Docs' list example: values 1..18 line up with the create body's fields.
    r = {"advertiser": 113, "advertiser_name": "Betwaypartners raketech", "advertiserlogin": "116",
         "advertiserlogin_username": "Casinofeber_Betway", "campaignkey": "custom_6748",
         "campaignname": "Test campaign creation", "date": "2022-09-01", "custom_id": "100",
         "clicks": "1", "signups": "3", "active_players": "4", "deposits": "6", "deposit_value": "7",
         "ndc": "9", "qndc": "10", "FTD": "11", "CPA_count": "12", "unique_clicks": "2", "depositors": "5",
         "REV_income": "18", "bonus": "8", "netrevenue": "17", "turnover": "15", "gross_revenue": "16",
         "CPA_income": "13", "Extra_fee": "14"}
    row = mp.map_custom_stat(r, date(2022, 9, 1), 0)
    keys_match(row, "voonix_custom_stats")
    prefill = cat.RESOURCES["custom_stats"]["ops"]["update"]["prefill"]
    expected = {"clicks": 1, "unique_clicks": 2, "signups": 3, "active_players": 4, "depositors": 5,
                "deposits": 6, "deposit_value": 7, "bonus": 8, "ndcs": 9, "qndcs": 10, "ftds": 11,
                "cpas": 12, "cpa_commission": 13, "fees": 14, "turnover": 15, "gross_revenue": 16,
                "net_revenue": 17, "revshare": 18}
    for write_field, value in expected.items():
        assert row[prefill[write_field]] == Decimal(value), write_field


def test_other_dimensions():
    keys_match(mp.map_advertiser({"id": "371", "name": "X", "group": "Voonix", "url_error": "0"}), "voonix_advertisers")
    keys_match(mp.map_site({"id": "3", "name": "Casinohat.no"}), "voonix_sites")
    keys_match(mp.map_payer({"id": "1", "threshold": "1000"}), "voonix_payers")
    keys_match(mp.map_affiliate_system({"afsy_id": "2", "afsy_system": "Omarsys", "afsy_api": "1"}),
               "voonix_affiliate_systems")
    dv = mp.map_data_validation({"advertiser": 1209, "advertiserlogin": 4166, "affiliate_system": "Netrefer",
                                 "clicks": "Clicks", "deposits": "unavailable", "bonus": "unavailable",
                                 "qndcs": "missing"})
    keys_match(dv, "voonix_data_validation")
    assert dv["unavailable_count"] == 2 and dv["missing_count"] == 1


def test_datamonitor_one_row_per_metric():
    r = {"advertiser_id": 1234, "advertiser": "Testing Affiliates", "tracker_login_id": 123,
         "username": "testusername", "campaign_key": "1234abcd",
         "deposit_value": {"current": "2120", "backup": 2119, "difference": 1},
         "FTD": {"current": "5", "backup": 5, "difference": 0}}
    rows = mp.map_datamonitor(r, date(2026, 4, 30), 3)
    assert [x["metric"] for x in rows] == ["deposit_value", "FTD"] and [x["row_no"] for x in rows] == [3, 4]
    keys_match(rows[0], "voonix_datamonitor")


# ── History planning ─────────────────────────────────────────────────────────


def test_plan_first_run():
    months, target = mp.plan_months(date(2026, 9, 15), 24, 3, None)
    assert len(months) == 24 and months[0] == date(2026, 9, 1) and months[-1] == date(2024, 10, 1)
    assert target == date(2024, 10, 1)


def test_plan_resync_only():
    months, _ = mp.plan_months(date(2026, 9, 15), 24, 3, date(2024, 10, 1))
    assert months == [date(2026, 9, 1), date(2026, 8, 1), date(2026, 7, 1)]


def test_plan_backfill_adds_12_older_months():
    months, target = mp.plan_months(date(2026, 9, 15), 24, 3, date(2024, 10, 1), backfill=True)
    assert target == date(2023, 10, 1)
    assert len(months) == 3 + 12 and date(2024, 9, 1) in months and date(2024, 10, 1) not in months


def test_plan_larger_history_fills_gap():
    months, target = mp.plan_months(date(2026, 9, 15), 36, 3, date(2024, 10, 1))
    assert target == date(2023, 10, 1) and len(months) == 15


def test_advance_floor_stops_at_hole():
    ok = {date(2024, 9, 1), date(2024, 8, 1), date(2024, 6, 1)}
    assert mp.advance_floor(date(2024, 10, 1), date(2024, 6, 1), ok, date(2026, 9, 1)) == date(2024, 8, 1)
    assert mp.advance_floor(None, date(2026, 7, 1), set(), date(2026, 9, 15)) is None


# ── Catalog ──────────────────────────────────────────────────────────────────


def test_catalog_columns_exist_in_tables():
    for name, res in cat.RESOURCES.items():
        table_cols = set(mp.TABLE_COLUMNS[res["table"]]) | {"commission", "synced_at"}
        for col in cat.select_columns(name):
            assert col in table_cols, f"{name}: column {col} not in {res['table']}"
    for name, rep in cat.REPORTS.items():
        table_cols = set(mp.TABLE_COLUMNS[rep["table"]]) | {"commission"}
        for m in rep["measures"]:
            if len(m) == 3:
                assert m[0] in table_cols, f"report {name}: measure {m[0]}"
        assert rep["default_sort"] in set(rep["dims"]) | {m[0] for m in rep["measures"]}


def test_validate_write_advertiser_create():
    report, op, payload, _ = cat.validate_write("advertisers", "create", {
        "name": "Test", "affiliate_system": "Omarsys", "affiliate_system_currency": "EUR",
        "affiliate_login_url": "https://voonix.net", "evil": "dropped", "contact_note": "  ",
    })
    assert (report, op) == ("advertisers", "create")
    assert "evil" not in payload and "contact_note" not in payload


def test_validate_write_errors():
    for bad in ({"name": "x"}, {}):
        try:
            cat.validate_write("advertisers", "create", bad)
        except ValueError as e:
            assert "required" in str(e)
        else:
            raise AssertionError("expected ValueError")
    try:
        cat.validate_write("history_deals", "create", {"id": "1", "start_month": "2023-13", "type": "REV"})
    except ValueError as e:
        assert "month" in str(e)
    else:
        raise AssertionError("expected month error")
    try:
        cat.validate_write("logins", "create", {"advertiser_id": "1", "username": "u", "type": "NOPE"})
    except ValueError as e:
        assert "allowed" in str(e)
    else:
        raise AssertionError("expected select error")


def test_validate_write_login_update_resume_import_only_when_true():
    _r, _o, payload, _ = cat.validate_write("logins", "update", {"id": "7", "paused": False, "resume_import": False})
    assert payload == {"id": 7, "paused": 0}, payload
    _r, _o, payload, _ = cat.validate_write("logins", "update", {"id": "7", "lock": "0000-00"})
    assert payload == {"id": 7}, payload
    _r, _o, payload, _ = cat.validate_write("logins", "update", {"id": "7", "resume_import": True})
    assert payload["resume_import"] is True


def test_validate_write_campaign_mark_deleted_and_deal_one_of():
    _r, op, payload, _ = cat.validate_write("campaigns", "mark_deleted", {"id": "241"})
    assert op == "update" and payload == {"id": "241", "deleted": 1}
    try:
        cat.validate_write("campaign_deals", "create", {"fk_login": "34", "start_month": "2022-01-01", "type": "CPA"})
    except ValueError as e:
        assert "Provide one of" in str(e)
    else:
        raise AssertionError("expected one_of error")


def test_validate_write_custom_stats_packing():
    _r, _o, payload, _ = cat.validate_write("custom_stats", "create", {
        "fk_login": "116", "date": "2022-09-01", "camp_name": "New", "clicks": "3000",
        "deposit_value": "1000.5", "custom_column1": "1",
    })
    assert payload["create_campaign"] is True and payload["custom_columns"] == {"custom_column1": 1}
    assert payload["clicks"] == 3000 and payload["deposit_value"] == 1000.5
    _r, _o, payload, local = cat.validate_write("custom_stats", "delete", {"cust_id": "98", "date": "2022-09-01"})
    assert payload == {"cust_id": 98} and local == {"date": "2022-09-01"}


def test_redact():
    assert cat.redact([{"password": "p", "key1": "k", "username": "u"}]) == [
        {"password": "***", "key1": "***", "username": "u"}]


def test_report_query_whitelists():
    q = cat.build_report_query("advertiser_earnings", date(2026, 9, 1), None,
                               ["advertiser", "x; DROP TABLE"], "commission; --", "asc", "bet", 50, 0)
    assert q["dims"] == ["advertiser"] and q["sort"] == "commission"
    assert "DROP" not in q["rows_sql"] and "--" not in q["rows_sql"]
    assert q["params"] == [date(2026, 9, 1), "%bet%"]
    q = cat.build_rows_query("logins", None, "username; DELETE", "desc", 10, 0)
    assert q["sort"] == "advertiser_name" and "DELETE" not in q["rows_sql"]


# ── Client (no network) ──────────────────────────────────────────────────────


def test_client_url_and_scrub():
    assert normalise_base_url("acme.voonix.net/api/?report=x") == "https://acme.voonix.net"
    c = VoonixClient("https://acme.voonix.net/", "SECRET&KEY")
    url = c._url("advertiserearnings", ("v3", "list"), {"start": "2026-09-01", "structure": "flat", "errors_only": True})
    assert url.startswith("https://acme.voonix.net/api/?report=advertiserearnings&v3&list&start=2026-09-01")
    assert "&errors_only&" in url and url.endswith("key=SECRET%26KEY")
    assert "SECRET" not in c._scrub(f"boom {url}")
    try:
        VoonixClient("https://acme.voonix.net", "")
    except VoonixError:
        pass
    else:
        raise AssertionError("empty key must raise")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
