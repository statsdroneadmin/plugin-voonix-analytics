# Voonix API: v2 (api.voonix.net) vs v3 (api.voonix.net/v3/)

Compared 2026-09-15 by reading both published Voonix documentation pages. Voonix's own text isn't reproduced here — this is our summary of the differences, alongside [API_NOTES.md](API_NOTES.md).

## Which is current

- **v3 is current.** The v2 page's header says: *"There is a newer version of the API (V3). Go to V3"*, and the v3 intro links back with *"See our old API 2.0 here."*
- Both use the same host pattern: your own Voonix address + `/api/?report=…`. The plugin uses v3 only.
- Whether v2 still answers is unknown until tested with a key.

## Size

| | v2 | v3 |
|---|---|---|
| Resources | 6 (advertisers, logins, campaigns BETA, custom stats, advertiser earnings, site earnings) | 16 |
| Operations | 11 | ~50 (plus `&JSON` bulk variants of every write) |
| Delete operations | none | advertisers, logins, campaign deals, custom stats, history deals (+ campaign soft-delete) |
| Bulk writes | no | yes — `&JSON` with an array body |

## Only in v3

`affiliatesystems`, `brands`, `datavalidation`, `earnings` (invoiceable), `historydeals` (create/update/delete), `sites` (list/create/update), `payout` (BETA), `payers`, `datamonitor`, `campaigns` update + `create_deal`/`update_deal`/`delete_deal`, `customstats` update/delete, and every delete.

## Changed between versions

| Area | v2 | v3 |
|---|---|---|
| Version flag | none | `&v3` in every URL |
| Logins resource | `report=logins` | `report=advertiserlogins` |
| Auth | `&key` in the URL only | `&key` in the URL "or as a header" (header name not given) |
| Advertiser create/update fields | `operator`, `market`, `currency`, `login_url`, `brand_id`, `brand_extra`, `group`; update keyed by `advertiser` | `affiliate_operator`, `affiliate_market`, `affiliate_system_currency`, `affiliate_login_url`, `affiliate_system_brand`, `affiliate_system_extra`, `affiliate_group`; update keyed by `id`. `affiliate_system`, currency and login URL become required on create. |
| Login create/update keys | `advertiser`, `login` | `advertiser_id` or `advertiser_name`, `id` or `optional_id`; adds `baseline`, `paused`, `lock`, `status`, `resume_import` |
| Login list | `logins`, `errors_only` filters; no paging | adds `advertiser`, sort `column`/`order`, `limit`/`offset`, `exclude[]`/`include[]` |
| History deals in login list | object keyed by start date | array with `start_month` |
| Campaigns list | nested `logins → campaigns → {…}` with `login_meta`/`advertiser_meta`/`site_meta`; filters `advertiser`, `login`, `alias`, `group`, `deleted` | flat `data` array with ids and names; many more filters (`site_id`, `deal_type`, `deals_begin`, `campaign_optional_id`, …); `limit` defaults to 200 |
| Custom stats list | `stats → login → campaign → date`; fields `ftd`, `cpa`, `extra_fee`, `revshare` | `data → month → [rows]` with `FTD`, `CPA_count`, `Extra_fee`, `REV_income`, plus `ndc`, `qndc`, `gross_revenue`; filters by `advertiser_login`, `cust_id`, `fk_ckey`; `start`/`end` now required |
| Custom stats create | `login`, `campaign`, `campaign_name`, `date`; posting an existing login+campaign+date **overwrites** | `fk_login`, `fk_ckey` or `create_campaign` + `camp_name`, `date`; separate update endpoint; full metric set incl. `ndcs`, `qndcs`, `gross_revenue`, `net_revenue`. Overwrite-on-create is not mentioned for v3. |
| Advertiser earnings | rows grouped by month then entity id, names only with `meta`; `REV_income_negatives` field | rows carry names (advertiser, login, campaign); `structure` nested/flat; filters for advertiser/login/campaign groups, `account_status`, `accounts_paused`; no `meta` param |
| Site earnings | `site` filter, `breakdown_period`, `meta` | `breakdown_level` advertiser/site, `account_status`, `accounts_paused`, `export`; no documented `site` filter |
| Response envelope | `success: 1`, `results: N`, top-level keys vary (`advertisers`, `logins`, `stats`) | `http: {code, status}`, `report`, `count`; writes return `succeeded`/`failed` arrays with counts |

## Doc quality notes

- **Invalid JSON in both.** Several examples in both versions have trailing commas or missing quotes.
- **SQL leak in the v2 campaigns example.** It contains a stray `"1": "SELECT * FROM campaign_deals"` debug line.
- **v3 contradicts itself.** `custom_columns1` in the parameter list vs `custom_column1` in the examples; the sites update JSON example shows `report=advertisers`; the invoiceable-earnings example is keyed `2022-05` for a 2023-05 range.

## What this means for the plugin

- **Built on v3 only.** v3 is a superset of v2 for everything the plugin does.
- **v2 shapes are also accepted where cheap.** The mappers take history deals in either the v2 date-keyed object or the v3 array, and they match fields case-insensitively.
- **Nothing in v2 is missing from v3,** except custom stats create's documented overwrite behaviour and the `meta`/`site` earnings parameters. None of those are needed.
