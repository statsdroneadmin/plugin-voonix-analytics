# Voonix API v3 — implementation notes

Written for this plugin. Voonix's own documentation (https://api.voonix.net/v3/) is
not redistributed here; these are the facts the code depends on, in our words, plus
the traps we hit. Check them against the live docs when something behaves oddly.

Companion: [V2_VS_V3.md](V2_VS_V3.md) — how v3 differs from the older v2 API.

## Request shape

- Base URL is per tenant: the address the customer logs in at (e.g. `https://acme.voonix.net`),
  never `api.voonix.net`, which is the documentation site.
- Path is always `/api/?report=<report>&v3&<op>&<params>&key=<API key>`.
- `v3`, `list`, `JSON` and write ops are **valueless flags**, so the query string is
  built by hand (`src/voonix_analytics_client.py`); a params dict would render `v3=`.
- Auth: the key goes in the `key` query parameter. The docs mention a header option
  but never name the header, so the URL form is the only usable one. Because the key
  rides in the URL, every error message is scrubbed before leaving the client.
- Writes accept a JSON array body when `JSON` is in the query, which is what this
  plugin uses for every create/update/delete.

## Reads used

| Report | Flag | Notes |
|---|---|---|
| `affiliatesystems` | none | Full list; also the cheapest auth probe. |
| `advertisers` | `list` | Full list; `limit` only, no offset. |
| `advertiserlogins` | `list` | Paged with `limit` + `offset`. Returns `key1`/`key2` — never stored. |
| `campaigns` | `list` | Default cap 200 rows and no documented offset; see paging traps. |
| `sites`, `payers`, `datavalidation` | `list`/none | `payers` accepts 1–1000 only. |
| `advertiserearnings`, `siteearnings`, `earnings`, `customstats` | `list` | `start`/`end` (Y-m-d) required; `breakdown_period`, `breakdown_level`, `structure`. |
| `payout` | none | BETA. `start`/`end` appear only in the docs' example, not the parameter list. |
| `datamonitor` | none | One `date` per call, so one call per day. |

`brands` is Voonix's global brand database, not customer data, and is deliberately not synced.

## Response shapes (all tolerated by `rows_from`/`flatten`)

- `data` may be a list, an object keyed by id, or grouped by `"YYYY-MM"`.
- Logins come under a `logins` key rather than `data`.
- Numbers arrive as JSON numbers or as strings; dates as `YYYY-MM-DD`, with `0000-00-00`
  meaning "none". Field names vary in case (`FTD`, `CPA_count`, `REV_income`), so lookups
  are case-insensitive.
- Success is signalled by an `http: {code, status}` block, or `success: 1` on some reports.
  Writes answer with `succeeded`/`failed` arrays plus counts.

## Traps worth remembering

- **Campaign paging.** `campaigns&list` defaults to 200 rows with no offset. The sync asks
  for a large limit, and if exactly 200 come back it refetches per login and flags possible
  truncation rather than silently losing campaigns.
- **Restated figures.** Affiliate numbers change after the fact (clawbacks), so each sync
  replaces whole months instead of appending.
- **History depth is unknown** until you try; "Fetch older history" walks 12 months further
  back per click and records whether anything came back.
- **`resume_import`** clears login errors so importing resumes. Voonix warns this can get an
  account banned if the stored credentials are wrong — the UI requires explicit confirmation.
- **Custom stats field names differ between read and write** (`ftds` vs `FTD`, `cpas` vs
  `CPA_count`, `revshare` vs `REV_income`, `fees` vs `Extra_fee`, `cpa_commission` vs
  `CPA_income`). The mapping is asserted in `tests/test_voonix_analytics.py`.
- **Documentation inconsistencies** seen at the time of writing: several response examples
  aren't valid JSON; `custom_columns1` in a parameter list vs `custom_column1` in the
  examples (the examples win, nested under `custom_columns`); the sites update example shows
  `report=advertisers`; an invoiceable-earnings example is keyed `2022-05` for a 2023-05 range.
- **Extra fee** is not documented as income or cost, so `commission` = revshare + CPA + CPL
  income and extra fee is kept as its own column.
