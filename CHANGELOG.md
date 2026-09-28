# Changelog

All notable changes to this plugin are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed — v0.2.2: MIT licence
- The plugin is now MIT licensed (LICENSE file included), published by John Wright.
- Voonix's own documentation is no longer copied into this repo. `docs-voonix-api/API_NOTES.md` records what the plugin relies on.
- **Changes in Voonix are now off by default.** Turn on "Allow changes in Voonix" in Settings to create, edit or delete Voonix records. Existing installs: re-enable it after updating if you use it.
- Added an "unofficial, not affiliated with Voonix" notice and a SECURITY.md.

### Fixed — v0.2.1: Plugin failed to load on some servers
- The plugin now uses only Python's built-in libraries. On servers whose Python lacks the `requests` library, v0.2.0 showed "This plugin failed to load — No module named 'requests'" and no button or sync worked. Nothing else changed, and there is nothing to install on the server.

### Added — v0.2.0: Export your data
- New **Export** tab: download every table the plugin stores as an **Excel workbook**, **CSV files**, a **SQLite database**, a **PostgreSQL SQL dump** or **JSON Lines**.
- Choose which tables, limit report tables to a date range, and see the row count before downloading.
- Raw Voonix records are left out by default; tick "Include raw Voonix records" to add them.
- Report tabs can now download the current view as **Excel, CSV or JSON** (previously CSV only, capped at 5,000 rows; now up to 200,000 rows).
- Exports never contain passwords or affiliate keys — they are never stored.

**After updating:** click **Trust this plugin** if prompted, then hard-refresh.

## [0.1.0] — 2026-09-15

### Added — v0.1.0: Voonix Analytics
- Connects to your Voonix account (your Voonix address + API key) and mirrors your data into NousViz every 6 hours, with a manual "Run sync" button.
- Pulls advertisers, affiliate logins and their deals, campaigns and campaign deals, sites, payers, advertiser earnings, site earnings, invoiceable earnings, payouts, custom stats, data validation and datamonitor issues.
- Fetches up to 24 months on the first sync (configurable) and re-fetches the last 3 months every sync so restated or clawed-back figures stay correct.
- "Fetch older history" pulls another 12 months further back each time; the Sync tab shows whether Voonix had older data.
- Overview dashboard plus a tab per report, each with a date range, grouping, sorting and CSV export.
- Admins can create, edit and delete advertisers, logins, history deals, campaign deals, custom stats and sites, and edit or delete campaigns, directly in Voonix. Deletes need typed confirmation, every change is listed on the Sync tab, and "Allow changes in Voonix" in Settings turns this off.
- Passwords and affiliate-program keys are never stored.

**After install:** click **Trust this plugin**, then hard-refresh the page.

---

## [0.1.0] — Initial scaffold

### Added

- Plugin manifest declaring connection (api_key + base_url), database (`voon_items`), navigation, dashboards, sync, hooks, actions, setup checklist, and one frontend widget.
- One Postgres migration creating `voon_items` and `voon_sync_state`.
- Sync script subclassing `BaseSyncScript` — populates `voon_items` from a fixture (replace with real fetch).
- HTTP routes: `/health-check`, `/test-connection`, `/sync-now`, `/overview`, `/items`, `/items/filters`.
- Lifecycle hooks: `on_credentials_saved`, `on_first_run_success`.
- Overview dashboard with one stat KPI, one bar chart, one custom-widget panel, one declarative table.
- One custom React widget (`VoonixAnalyticsKpiCard`) demonstrating the v0.9.4.7+ build pipeline (alias + external for `react` and `react/jsx-runtime`).

### Plugin author release checklist (every release)

1. Bump `version:` in `plugin.yaml` to match this CHANGELOG entry's heading.
2. Commit code: `git commit -m "feat/fix: ..."`.
3. Push code: `git push origin main`.
4. **Tag the release**: `git tag -a v0.1.0 -m "v0.1.0 — ..."`.
5. **Push the tag**: `git push origin v0.1.0`. (`git push` alone doesn't push tags.)
6. Only then tell operators to install / Update.

NousViz pulls the latest semver tag — without step 4+5, install fails with `Plugin not found at tag vX.Y.Z`.

### Operator workflow on first install

- Install plugin → click **Trust this plugin** when the consent banner appears → hard-refresh the page once.
- Configure credentials on the Settings tab → click **Test connection** → click **Run sync**.
- Setup checklist guides you through the four steps; once all four are checked, the plugin is fully operational.
