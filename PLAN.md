# PLAN.md

The SOP for this plugin. Every change goes through these gates **before** code is written:

1. **Ticket** — what's broken / what's missing, with specific evidence
2. **Plan** — 3-5 lines of how
3. **Test plan** — what success looks like (operator-visible checks — see `docs/11-verification-spec.md` in the parent guide for the template)
4. **CHANGELOG stub** — draft the user-facing entry

If any gate is missing, you don't have permission to write code. Same applies to Claude Code — it refuses without these gates filled in.

For a brand-new plugin: walk through the eight intake questions in `docs/00-conversation-starter.md` (parent guide) before filling in the v0.1.0 ticket below. The intake answers BECOME the ticket + plan + test plan.

Reference: see `docs/08-sop-and-discipline.md` in the parent `nousviz-plugin-authoring` guide.

---

## Implementation phases

### v0.2.3 — Install/update over HTTPS

**STATUS: built 2026-09-28.**

**Ticket.** Operator hit `Plugin 'voonix-analytics' not found in official or community registry.
Provide a repository_url in the request body to install a private plugin.` The registry is
NousViz's curated list and this plugin isn't in it, so it must be installed via the repo-URL
form. Separately the manifest still declared the SSH `repository:` and `visibility: fully_private`
after the repo went public — and the marketplace clones from `repository:` on install
(`docs/02-plugin-contract.md:66`), which would keep demanding a deploy key on update.

**Plan.** Point `repository:` at the public HTTPS URL, set `visibility: public`, document the
install route in the README and long_description, bump to 0.2.3.

**Test plan.**
- [ ] Install from Git with the HTTPS URL succeeds with no deploy key
- [ ] `/health-check` reports 0.2.3
- [ ] Update (not reinstall) works on a later tag without a key

**CHANGELOG stub.** See `CHANGELOG.md` [Unreleased].

### v0.2.2 — MIT licence, and Voonix's documentation out of the repo

**STATUS: built 2026-09-28.**

**Ticket.** Operator wants the plugin MIT licensed and Voonix's copied documentation removed,
keeping only what we need. Both are prerequisites for ever making the repo public (the third,
the operator's personal email in the first two commits, is handled by republishing the history —
tracked separately, needs the operator's go-ahead because it deletes and recreates the GitHub repo).

Evidence: `docs-voonix-api/voonix-api-v3.txt` (3,569 lines) and `voonix-api-v2-legacy.txt` are
Voonix's own text, republishing rights unclear, and they carry Voonix's example keys which secret
scanners flag. Nothing loads them at runtime — only comments and docstrings referenced them.

**Plan.**
1. Replace both vendored texts with `docs-voonix-api/API_NOTES.md`, written here: request shape,
   the reads used, response shapes, and the traps (campaign paging cap, restatements, custom-stat
   read/write field mapping, doc inconsistencies). Keep `V2_VS_V3.md` (our own comparison).
2. Gitignore `docs-voonix-api/*.txt` alongside `*.html` so local copies stay for reference.
3. Repoint every code/doc reference at API_NOTES.md.
4. `license: MIT` in the manifest + a LICENSE file (© John Wright); publisher "John Wright".
5. Version 0.2.2 across manifest, routes and the client User-Agent.

**Test plan.**
- [ ] `git ls-files docs-voonix-api/` lists only API_NOTES.md and V2_VS_V3.md
- [ ] `grep -rn "voonix-api-v3.txt" .` finds nothing tracked
- [ ] LICENSE present; `license: MIT` in plugin.yaml; publisher reads "StatsDrone Inc"
- [ ] Offline suites, smoke-test and preflight still pass; `/health-check` reports 0.2.2

**CHANGELOG stub.** See `CHANGELOG.md` [Unreleased].

### v0.2.1 — Fix: plugin failed to load on the host (no `requests` module)

**STATUS: built 2026-09-28, awaiting the operator's re-test on the server.**

**Ticket.** v0.2.0 installed on the operator's NousViz server and the plugin page showed
`This plugin failed to load. ModuleNotFoundError: No module named 'requests'`, so every
declared action endpoint 404s and no data can sync. Evidence: operator screenshot of the
plugin page (2026-09-28) plus the banner's own message.

Root cause: `src/voonix_analytics_client.py` imported the third-party `requests` library,
which isn't in that host's Python env. The SDK's own guidance is that plugin runtime deps
belong to the host env and "Plugins don't ship a runtime `requirements.txt`"
(`docs/01-getting-started.md:110` in the parent guide) — so a plugin that needs a
non-stdlib import is betting on a host that may not have it. Two sibling plugins
(ahrefs-data, cloudflare-analytics) ship `requirements.txt` with httpx and one
(casino-complaints) claims core pip-installs it, but that contract is undocumented and
plainly did not apply here.

**Plan.**
1. Rewrite `VoonixClient` on stdlib `urllib.request` — same public surface (`get`,
   `write`, `probe`, `VoonixError`, `normalise_base_url`), same throttle, same GET-only
   retry policy, same key scrubbing, plus gzip and charset handling urllib doesn't do for you.
2. No `requirements.txt`: keep the plugin dependency-free so it can't fail this way on any host.
3. Bump version to 0.2.1 in plugin.yaml, routes PLUGIN_VERSION and the client User-Agent.
4. Re-run both offline suites, smoke-test and preflight; no widget change, bundles untouched.

**Test plan.**
- [ ] `grep -rn "import requests" src/ api/ hooks/` returns nothing
- [ ] Plugin page no longer shows "This plugin failed to load"
- [ ] `/api/plugins/voonix-analytics` shows `load_status.routes_registered: true`
- [ ] `/health-check` reports version 0.2.1
- [ ] Test connection succeeds against the real Voonix account
- [ ] Run sync imports rows; Sync tab shows per-endpoint results
- [ ] Custom widgets render after Trust + hard refresh (no "Unknown custom component")

**CHANGELOG stub.** See `CHANGELOG.md` [Unreleased].

### v0.2.0 — Data export in multiple formats

**STATUS: approved 2026-09-15 (operator answered scope questions). Built; not yet live-tested.**

**Ticket.** Operator wants plugin users to download their data "in multiple formats to make this whole thing easier for them". Decisions: full dump of every table; formats CSV, Excel, SQLite, PostgreSQL SQL dump (operator asked if SQL could work — yes, PostgreSQL dialect), JSON Lines; per-report downloads in CSV/Excel/JSON; any logged-in user may export ("whoever has this plugin has their own API key so this is their data"); raw Voonix records excluded by default with an option to include.

Evidence / constraints:
- SDK docs only say "Export to CSV → custom widget + a download route" (00-conversation-starter.md:75); no documented file-download contract.
- Five existing plugins ship downloads the same way (route returns an attachment; widget `apiFetch` → Blob → `a.download`): statsdrone-analytics, ahrefs-data, affiliatetrack-scraper, github-analysis, nous-crm. All stdlib `csv`; none ships openpyxl/pyarrow → **stdlib only** (Parquet dropped).
- Browser holds the whole file as a Blob, and the API/proxy timeout on the host is unknown → date-range filter, live row estimate, server-side row cap.

**Plan.**
1. `src/voonix_analytics_export.py` (pure, no SDK): schema parsed from the plugin's own migrations; writers for CSV zip, JSON Lines zip, hand-written SpreadsheetML .xlsx (sheet split at Excel's 1,048,576-row limit), SQLite, PostgreSQL SQL zip (CREATE TABLE IF NOT EXISTS + batched INSERT … ON CONFLICT DO NOTHING); single-table report writer with spreadsheet-formula guard on CSV text cells.
2. Routes (analyst): `GET /export/options`, `GET /export/estimate`, `GET /export` (server-side cursor → temp file → FileResponse, temp file deleted after send; 3,000,000-row cap), `GET /report/{name}/export` (200,000-row cap, `X-Voonix-Truncated` header).
3. Widgets: new `VoonixExport` (Export tab); `VoonixReport` export button gains a format picker and uses the server route.
4. Tests: every writer round-tripped with an independent reader (csv/json/sqlite3/openpyxl); SQL dump loaded into a real throwaway PostgreSQL 16.

**Test plan.**
- [ ] Export tab lists 5 formats and 17 tables in 3 groups; row counts appear per table
- [ ] Excel download opens in Excel/Numbers/Sheets with one sheet per table + "Export info"
- [ ] CSV zip, JSON Lines zip, SQLite file open and contain the same row counts as the estimate
- [ ] `psql -d fresh_db -f voonix-export.sql` loads without errors; counts match
- [ ] "Last 12 months" reduces report-table counts but not account tables
- [ ] Include raw off → no `raw` column; on → `raw` present
- [ ] Report tab: Excel/CSV/JSON downloads match the on-screen grouping and totals
- [ ] `/health-check` reports version 0.2.0; smoke-test + preflight pass; tag v0.2.0 on remote

**CHANGELOG stub.** See `CHANGELOG.md` [Unreleased].

### v0.1.0 — Voonix API v3 ingestion + writes + Overview + per-report tabs

**STATUS: approved 2026-09-15 with two scope changes from the operator (below). Built; not yet live-tested.**

**Scope changes (operator, 2026-09-15):**
1. **Writes are in scope.** Every create/update/delete the v3 API offers is exposed: advertisers (C/U/D), logins (C/U/D incl. password/keys/pause/lock/resume_import), history deals (C/U/D), campaigns (update alias/group/note, mark deleted), campaign deals (C/U/D), custom stats (C/U/D), sites (C/U). Safety: admin-only routes (`_require_admin`), "Allow changes in Voonix" toggle, server-side field allowlist per operation (`src/voonix_analytics_catalog.py`), typed DELETE confirmation for destructive ops, explicit confirmation for `resume_import`, no POST retries (a timed-out create may have succeeded), `voonix_write_log` audit with secrets redacted, targeted re-fetch after a successful write.
2. **Backfill.** Operator can't know how much history Voonix holds until testing, so a "Fetch older history" action pulls 12 more months below the stored floor per click; Sync tab reports whether older data came back.

The operator will test live with their own key (not shared with Claude). Everything below marked VERIFY is confirmed by that test.

**Ticket.** Operator wants every piece of their Voonix data (affiliate stats
aggregator) mirrored into NousViz: one consolidated Overview plus one tab per
Voonix report. Source docs: `docs-voonix-api/API_NOTES.md` (vendored
2026-09-15 from https://api.voonix.net/v3/, read end to end).

Evidence / constraints from the docs:
- 14 read (GET) endpoints; ~36 write endpoints (create/update/delete). **v0.1.0 is read-only** — no write endpoint is ever called.
- Base URL is per-tenant ("your personalised Voonix URL"), not api.voonix.net.
- Auth: docs say `&key=` in the URL "or as a header" but never name the header. v0.1.0 uses `&key=` (the only documented form) and never logs request URLs.
- Paging is inconsistent: logins have `limit`+`offset`; campaigns default to 200 with no documented offset; payers capped at 1000, no offset. Truncation must be detected, not assumed away.
- Example responses are hand-written: some invalid JSON, mixed list-vs-keyed-object `data`, logins under `logins` not `data`, numbers as strings. Parsers must accept both shapes and coerce numerics.
- No documented rate limit, no documented max date range, no documented history depth.
- Login rows include `key1`/`key2` (the operator's affiliate-program API keys) — **never stored**.

Intake answers (docs/00-conversation-starter.md):
1. Source: Voonix API v3 (external API).
2. Credentials: API key (secret) + tenant base URL (non-secret). Operator has no key yet.
3. Row shapes: see schema below.
4. See: one consolidated Overview + individual report tabs.
5. Do: view, filter by date range, manual "Run sync", "Test connection". No writes.
6. Freshness: every 6 hours + manual button.
7. Who: any analyst (`_require_analyst` on every data route).
8. Success: see test plan.

**Plan.**
1. Manifest: connection fields `base_url` (url, https, required) + `api_key` (password). Settings `history_months` (default 24) and `resync_months` (default 3 — affiliate data gets restated/clawed back, so the trailing window is re-pulled every run and upserted).
2. `src/voonix_analytics_client.py`: one `VoonixClient` — builds `{base_url}/api/?report=X&v3&list&key=…`, retries 429/5xx with backoff, self-throttles, normalises `data` (list or id-keyed dict), coerces numeric strings, raises on non-200 `http.code`. Paging helper: logins via offset; campaigns split per login (one call per `advertiser_login`) with a truncation warning if any call returns exactly the limit.
3. Migration `001_voonix_core.sql` (+ `_down`), prefix `voonix_`:
   - Dimensions: `voonix_advertisers`, `voonix_logins` (deal + history/campaign deals as jsonb; NO key1/key2/password), `voonix_campaigns`, `voonix_sites`, `voonix_payers`, `voonix_affiliate_systems`.
   - Facts: `voonix_advertiser_earnings` (daily, campaign level; PK login+campaign_key+date), `voonix_site_earnings` (daily; PK site+advertiser+date), `voonix_invoice_earnings` (from `earnings`; PK row hash), `voonix_payouts` (PK row hash), `voonix_custom_stats` (PK cust_id+date), `voonix_data_validation` (PK login), `voonix_datamonitor` (PK date+login+campaign+metric).
   - `voonix_sync_state`, and `raw jsonb` on every table so nothing the API returns is lost.
   - Brands (Voonix's global 1,869-brand reference DB) deliberately excluded — not operator data.
4. `src/voonix_analytics_sync.py` (BaseSyncScript, async, 6-hourly): dimensions → earnings reports month-by-month (backfill `history_months` on first run, then `resync_months`) → datamonitor day-by-day over the resync window. Heartbeat + `check_cancelled()` between every call; per-endpoint errors recorded without aborting the other endpoints.
5. Routes (`api/routes.py`, all `_require_analyst`): `/health-check`, `/test-connection` (calls `affiliatesystems` — cheapest read), `/sync-now`, `/overview`, `/report/{name}` (date range + group-by + sort + paging, whitelisted columns only), `/report/{name}/filters`.
6. Dashboards: **Overview** (TrendCards: commission, FTDs, CPAs, clicks, signups, net revenue, deposits, payouts paid; commission trend; top advertisers; top campaigns; data issues count) + tabs **Advertiser earnings, Site earnings, Invoiceable earnings, Payouts, Campaigns, Accounts (advertisers + logins), Payers, Custom stats, Data quality (validation + datamonitor), Sync**.
7. Widgets: port `TrendCards` + `DataTable` from plugin-instantly-ai; new `VoonixReport` (date-range picker + group-by + sortable paginated table, driven by `/report/{name}`). Remove skeleton `VoonixAnalyticsKpiCard`.
8. `smoke-test.sh` + `preflight.sh` clean. Offline parser tests against every doc response example (they are the only fixtures until a key exists).
9. **Before tag:** live probe with a real key — confirm auth form, real response shapes, campaign paging, earliest month with data. Everything unverified is marked `# VERIFY` in code.

**Test plan.**

#### Install + first launch
- [ ] Install completes; sidebar shows "Voonix Analytics" with Overview + 10 report tabs
- [ ] Every tab renders empty states (no SQL errors) before credentials are saved
- [ ] No browser console errors

#### Settings
- [ ] Form shows Base URL (plain text) and API key (●●●●●●●●)
- [ ] Wrong key → "Test connection" shows a clear error toast, not a stack trace
- [ ] Correct key → success toast naming the affiliate-system count

#### Sync
- [ ] "Run sync" completes; `/system/jobs` shows per-endpoint row counts
- [ ] Earliest month in `voonix_advertiser_earnings` = earliest month Voonix has (or `history_months` back)
- [ ] Commission total for one month matches the Voonix UI advertiser-earnings report for the same month (±0.01)
- [ ] Campaign count matches Voonix UI; no truncation warning in the sync log
- [ ] Re-running sync does not duplicate rows (counts unchanged)
- [ ] `SELECT count(*) FROM voonix_logins WHERE raw::text ILIKE '%key1%'` = 0

#### Dashboards
- [ ] Overview TrendCards show numbers (no NaN), MoM deltas present
- [ ] Each report tab: changing the date range changes totals; group-by and sort work; paging works

#### Pre-tag verification
- [ ] `git ls-remote --tags origin` shows `v0.1.0`
- [ ] `plugin.yaml` `version:` = `0.1.0`
- [ ] `scripts/smoke-test.sh` passes
- [ ] `scripts/preflight.sh` passes

**CHANGELOG stub.** See `CHANGELOG.md` [Unreleased].

---

<!--
Template for subsequent versions — copy-paste and fill in:

### vX.Y.Z — <one-line summary>

**Ticket.** What's broken / what's missing. Cite specific evidence (error
message, log entry, file:line). Why this needs fixing now vs later.

**Plan.**
1. First step.
2. Second step.

**Test plan.** Use the template from `docs/11-verification-spec.md`. The
full template covers install, settings, configure/test/sync, dashboards,
custom-widget interactions, update flow, and "what the operator should
NOT see." For a small change, include just the sections affected.

- [ ] `git ls-remote --tags origin` shows the new tag (not just local)
- [ ] `plugin.yaml` `version:` matches the tag
- [ ] `scripts/smoke-test.sh` passes
- [ ] `scripts/preflight.sh` passes
- [ ] Operator-visible check 1 (specific to this version's change)
- [ ] Operator-visible check 2
- [ ] No regression on X
- [ ] No browser console errors

**CHANGELOG stub.**
\```
### Fixed/Added/Changed — vX.Y.Z: <summary>
- Bullet 1
\```
-->