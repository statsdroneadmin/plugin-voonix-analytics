# voonix-analytics

> **Unofficial.** Not affiliated with, endorsed by, or supported by Voonix. "Voonix" is the
> trademark of its owner, used here only to describe what this plugin connects to. The plugin
> calls Voonix's documented API with the account holder's own API key and reads only that
> account's own data. Check your own agreement with Voonix before using it.

NousViz plugin that mirrors a Voonix account into NousViz through the Voonix API v3, and lets admins create, edit and delete Voonix records from NousViz.

Built against the Voonix API v3 (https://api.voonix.net/v3/). Voonix's documentation isn't copied into this repo; `docs-voonix-api/API_NOTES.md` records what the plugin relies on, and `docs-voonix-api/V2_VS_V3.md` compares v3 with the older v2 API at https://api.voonix.net/.

MIT licensed. Copyright (c) 2026 John Wright.

---

## What it pulls

| Voonix endpoint | Table | How |
|---|---|---|
| `affiliatesystems` | `voonix_affiliate_systems` | full list (also the connection probe) |
| `advertisers&list` | `voonix_advertisers` | full list |
| `advertiserlogins&list` | `voonix_logins`, `voonix_login_history_deals` | `limit`/`offset` pages of 500 |
| `campaigns&list` | `voonix_campaigns`, `voonix_campaign_deals` | one bulk call; per-login calls if the bulk call looks capped at 200 |
| `sites&list` | `voonix_sites` | full list |
| `payers` | `voonix_payers` | up to 1,000 (API maximum) |
| `datavalidation&list` | `voonix_data_validation` | full list |
| `advertiserearnings&list` | `voonix_advertiser_earnings` | per month, daily × campaign |
| `siteearnings&list` | `voonix_site_earnings` | per month, daily |
| `earnings&list` | `voonix_invoice_earnings` | per month |
| `payout` (BETA) | `voonix_payouts` | per month, all statuses |
| `customstats&list` | `voonix_custom_stats` | per month, daily × campaign |
| `datamonitor` | `voonix_datamonitor` | one call per day |

Not pulled: `brands` (Voonix's global brand database, not account data).

Never stored: login passwords and `key1`/`key2`.

## What it can change (admins, when "Allow changes in Voonix" is on)

| Tab | Create | Edit | Delete |
|---|---|---|---|
| Advertisers | ✓ | ✓ | ✓ |
| Logins & deals — logins | ✓ | ✓ (incl. password, keys, pause, lock, resume import) | ✓ |
| Logins & deals — history deals | ✓ | ✓ | ✓ |
| Campaigns & deals — campaigns | — (Voonix API has no create) | alias, group, note | ✓ (marks deleted) |
| Campaigns & deals — campaign deals | ✓ | ✓ | ✓ |
| Sites | ✓ | ✓ | — (Voonix API has no delete) |
| Custom stats | ✓ | ✓ | ✓ |

Every write is validated server-side against the field catalog in `src/voonix_analytics_catalog.py`, needs typed confirmation for deletes, is recorded in `voonix_write_log` (secrets redacted), and refreshes the affected local data from Voonix.

## Export

**Export tab** — every table, in one download:

| Format | File | Best for |
|---|---|---|
| Excel | `.xlsx`, one sheet per table + "Export info" (tables over ~1M rows continue on extra sheets) | Business users |
| CSV | `.zip` of one CSV per table + README | Spreadsheets, BI tools |
| SQLite | `.sqlite` with every table + `_export_info` | Querying locally, moving to another tool |
| PostgreSQL SQL | `.zip` containing `voonix-export.sql` (CREATE TABLE IF NOT EXISTS + INSERT … ON CONFLICT DO NOTHING) | Loading into your own database: `psql -d fresh_db -f voonix-export.sql` |
| JSON Lines | `.zip` of one `.jsonl` per table | Scripts and pipelines |

- The date range applies to report tables and the change log. Account tables are always exported in full.
- Raw Voonix records are excluded unless "Include raw Voonix records" is ticked.
- Limit: 3,000,000 rows per export; the tab shows the row count before you download.

**Report tabs** — the current view (filters, grouping, sort) as Excel, CSV or JSON, up to 200,000 rows. Report CSVs escape text that would run as a spreadsheet formula.

Exports never contain passwords or affiliate keys, because the plugin never stores them.

## History

- First sync: back to **History to fetch** months (default 24).
- Every sync: re-fetches the last **Months to re-check** (default 3) and replaces those months, so restated or clawed-back numbers are corrected.
- **Fetch older history** (page header): the next sync goes 12 months below the current floor. The Sync tab shows whether anything older was found.

## Setup

1. Install via "Install from Git" with `git@github.com:statsdroneadmin/plugin-voonix-analytics.git` (add a per-repo deploy key first, B204).
2. Click **Trust this plugin**, then hard-refresh.
3. Settings: **Voonix address** (the address you log in at, e.g. `https://yourcompany.voonix.net`) and **API key** → Save.
4. **Test connection** → **Run sync**.

## Unverified until tested against a live account

- Auth uses `&key=` in the URL (the only documented form).
- Real response shapes — the docs' examples are hand-written and partly invalid JSON.
- Whether `campaigns&list` honours a large `limit` (Sync tab → campaigns → Complete).
- Write request/response shapes for each resource.
- Whether "Extra fee" is income or a cost (Commission currently excludes it).

## Development

```bash
python3 tests/test_voonix_analytics.py            # offline tests (no SDK needed)
cd widget && npm install && npm run typecheck && ./build.sh
~/devhub/sdk-plugins/scripts/smoke-test.sh
~/devhub/sdk-plugins/scripts/preflight.sh
```

Troubleshooting: sync errors per endpoint are on the Sync tab; full traces at `/system/logs?source=sync&plugin_id=voonix-analytics` and `/system/logs?source=plugin_route`.
