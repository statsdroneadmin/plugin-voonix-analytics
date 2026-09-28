"""
src/voonix_analytics_sync.py — scheduled sync for voonix-analytics.

One run:
  1. Affiliate systems (doubles as the auth probe — a bad URL or key
     fails the run immediately instead of producing 40 identical errors).
  2. Dimensions: advertisers, logins (+ history deals), campaigns
     (+ campaign deals), sites, payers, data validation.
  3. Report months, newest first — see mappers.plan_months:
       first run  → back to `history_months`;
       later runs → last `resync_months` (restatements / clawbacks) plus
                    any gap to a larger `history_months`;
       backfill   → 12 more months below the stored floor (set by the
                    "Fetch older history" action).
     Each month × {advertiser earnings, site earnings, invoiceable
     earnings, payouts, custom stats} is replaced atomically.
  4. Datamonitor issues for the last `datamonitor_days` days.

An endpoint failing does not stop the others; its error is recorded in
voonix_sync_state and the job details. The run only errors outright when
nothing at all succeeded.

Slug-prefixed filename per G-1. Reference: docs/06-sync-and-jobs.md
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nousviz_sdk.sync import BaseSyncScript
from nousviz_sdk.jobs import heartbeat, check_cancelled
from nousviz_sdk import log_event

import voonix_analytics_mappers as mp
import voonix_analytics_store as st
from voonix_analytics_client import VoonixError


PLUGIN_SLUG = "voonix-analytics"
MAX_ERRORS_KEPT = 50


class VoonixAnalyticsSync(BaseSyncScript):
    plugin_id = PLUGIN_SLUG

    def run(self, since: Any = None) -> dict[str, Any]:
        settings = st.load_settings()
        client = st.make_client(settings)
        self._summary: dict[str, Any] = {"steps": {}, "errors": [], "rows": 0, "ok_steps": 0}

        try:
            self._run(client, settings)
        except st.Cancelled:
            log_event("warning", "Voonix sync cancelled by operator")
            self._summary["cancelled"] = True
            return self._summary

        st.set_state("last_sync", {
            "completed_at": st.now_iso(),
            "rows": self._summary["rows"],
            "errors": len(self._summary["errors"]),
        })
        self.log_sync_result(
            rows_synced=self._summary["rows"],
            rows_failed=len(self._summary["errors"]),
            details={"steps": self._summary["steps"], "errors": self._summary["errors"][:10]},
        )
        if self._summary["ok_steps"] == 0:
            raise RuntimeError("Voonix sync: every endpoint failed. First error: "
                               + (self._summary["errors"][0] if self._summary["errors"] else "unknown"))
        log_event("info", "Voonix sync complete", detail={
            "rows": self._summary["rows"], "errors": len(self._summary["errors"]),
        })
        return self._summary

    # ── Steps ────────────────────────────────────────────────────────────

    def _tick(self, progress: dict[str, Any]) -> None:
        heartbeat(progress=progress)
        if check_cancelled():
            raise st.Cancelled()

    def _record(self, name: str, ok: bool, rows: int = 0, error: str | None = None,
                extra: dict[str, Any] | None = None) -> None:
        step = self._summary["steps"].setdefault(name, {"ok": True, "rows": 0, "errors": 0})
        step["rows"] += rows
        self._summary["rows"] += rows
        if ok:
            self._summary["ok_steps"] += 1
        else:
            step["ok"] = False
            step["errors"] += 1
            if len(self._summary["errors"]) < MAX_ERRORS_KEPT:
                self._summary["errors"].append(f"{name}: {error}")
        if extra:
            step.update(extra)

    def _save_step_state(self, name: str) -> None:
        step = self._summary["steps"].get(name, {})
        last_error = next((e for e in reversed(self._summary["errors"]) if e.startswith(f"{name}:")), None)
        st.set_state(f"endpoint:{name}", {**step, "last_error": last_error, "at": st.now_iso()})

    def _run(self, client: Any, settings: dict[str, Any]) -> None:
        # 1. Probe + affiliate systems. Auth failure is fatal.
        self._tick({"phase": "affiliate_systems"})
        try:
            result = st.refresh_affiliate_systems(client)
            self._record("affiliate_systems", True, result["rows"])
        except VoonixError as e:
            self._record("affiliate_systems", False, error=str(e))
            self._save_step_state("affiliate_systems")
            raise RuntimeError(f"Could not reach Voonix: {e}") from None
        self._save_step_state("affiliate_systems")

        # 2. Dimensions.
        for name in ("advertisers", "logins", "campaigns", "sites", "payers", "data_validation"):
            self._tick({"phase": name})
            try:
                result = st.DIMENSION_REFRESHERS[name](client, self._tick)
                self._record(name, True, result.get("rows", 0),
                             extra={k: v for k, v in result.items() if k != "rows"})
            except st.Cancelled:
                raise
            except Exception as e:  # keep going; one resource failing shouldn't block the rest
                self._record(name, False, error=str(e)[:500])
            self._save_step_state(name)

        # 3. Report months.
        floor_state = st.get_state("history_floor") or {}
        floor = mp.to_date(floor_state.get("month"))
        backfill = bool((st.get_state("backfill_request") or {}).get("requested"))
        today = date.today()
        months, target = mp.plan_months(
            today, settings["history_months"], settings["resync_months"], floor, backfill,
        )
        ok_months: set[date] = set()
        older_rows = 0
        older_failures = 0
        for i, month in enumerate(months):
            month_ok = True
            for name in st.PERIOD_ENDPOINTS:
                self._tick({"phase": "reports", "report": name, "month": month.isoformat()[:7],
                            "months_done": i, "months_total": len(months)})
                try:
                    n = st.refresh_period(client, name, month)
                    self._record(name, True, n)
                    if floor and month < floor:
                        older_rows += n
                except st.Cancelled:
                    raise
                except Exception as e:
                    month_ok = False
                    if floor and month < floor:
                        older_failures += 1
                    self._record(name, False, error=f"{month.isoformat()[:7]}: {str(e)[:400]}")
            if month_ok:
                ok_months.add(month)
        for name in st.PERIOD_ENDPOINTS:
            self._save_step_state(name)

        new_floor = mp.advance_floor(floor, target, ok_months, today)
        if new_floor and new_floor != floor:
            st.set_state("history_floor", {"month": new_floor.isoformat(), "updated_at": st.now_iso()})
        if backfill:
            st.set_state("backfill_request", {"requested": False, "cleared_at": st.now_iso()})
            st.set_state("backfill_last", {
                "completed_at": st.now_iso(),
                "requested_from": target.isoformat()[:7],
                "previous_floor": floor.isoformat()[:7] if floor else None,
                "floor_now": new_floor.isoformat()[:7] if new_floor else None,
                "rows_found": older_rows,
                "older_data_found": older_rows > 0,
                # When older months errored, "no data found" isn't a real answer.
                "failed_calls": older_failures,
            })

        # 4. Datamonitor.
        for offset in range(settings["datamonitor_days"]):
            day = today - timedelta(days=offset + 1)
            self._tick({"phase": "datamonitor", "date": day.isoformat()})
            try:
                self._record("datamonitor", True, st.refresh_datamonitor_day(client, day))
            except st.Cancelled:
                raise
            except Exception as e:
                self._record("datamonitor", False, error=f"{day.isoformat()}: {str(e)[:400]}")
        if settings["datamonitor_days"]:
            self._save_step_state("datamonitor")


if __name__ == "__main__":
    VoonixAnalyticsSync().main()
