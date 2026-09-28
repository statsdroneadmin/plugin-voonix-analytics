-- 001_voonix_core.sql — voonix-analytics schema.
--
-- No serial/identity columns: fact tables key on (period_month, row_no)
-- because each month is replaced wholesale by the sync, and the plugin
-- role is not guaranteed USAGE on sequences.
-- Every table is listed in plugin.yaml databases.postgres.tables (grant manifest).

-- ── Dimensions ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS voonix_affiliate_systems (
    id                 bigint PRIMARY KEY,
    name               text,
    has_api            boolean,
    daily              boolean,
    brand_id_required  boolean,
    igaming            boolean,
    report_names       text,
    raw                jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS voonix_advertisers (
    id                    bigint PRIMARY KEY,
    optional_id           text,
    name                  text,
    description           text,
    market                text,
    affiliate_system      text,
    login_url             text,
    group_name            text,
    currency              text,
    brand_id              text,
    brand_extra           text,
    operator              text,
    url_error             boolean,
    brand_split_possible  boolean,
    contact_name          text,
    contact_email         text,
    contact_skype         text,
    contact_note          text,
    raw                   jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at             timestamptz NOT NULL DEFAULT now()
);

-- Passwords and key1/key2 are never stored (stripped before insert, raw included).
CREATE TABLE IF NOT EXISTS voonix_logins (
    id                 bigint PRIMARY KEY,
    optional_id        text,
    advertiser_id      bigint,
    advertiser_name    text,
    affiliate_system   text,
    username           text,
    group_name         text,
    status             text,
    currency           text,
    note               text,
    extra_note         text,
    cosmetic_deal      text,
    locked             text,
    paused             boolean,
    baseline           boolean,
    error              boolean,
    deal_type          text,
    deal_rev           numeric,
    deal_cpa           numeric,
    deal_cpl           numeric,
    voonix_created_at  timestamp,
    created_by_name    text,
    voonix_updated_at  timestamp,
    updated_by_name    text,
    raw                jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS voonix_logins_advertiser_idx ON voonix_logins (advertiser_id);

CREATE TABLE IF NOT EXISTS voonix_login_history_deals (
    login_id         bigint NOT NULL,
    start_month      date NOT NULL,
    login_username   text,
    advertiser_name  text,
    type             text,
    rev              numeric,
    cpa              numeric,
    cpl              numeric,
    synced_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (login_id, start_month)
);

CREATE TABLE IF NOT EXISTS voonix_campaigns (
    id                      text PRIMARY KEY,
    key                     text,
    name                    text,
    login_id                bigint,
    login_optional_id       text,
    username                text,
    advertiser_id           bigint,
    advertiser_optional_id  text,
    advertiser_name         text,
    campaign_optional_id    text,
    site_id                 text,
    site_name               text,
    alias                   text,
    group_name              text,
    note                    text,
    raw                     jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS voonix_campaigns_login_idx ON voonix_campaigns (login_id);

CREATE TABLE IF NOT EXISTS voonix_campaign_deals (
    id             text PRIMARY KEY,
    campaign_id    text,
    campaign_key   text,
    campaign_name  text,
    login_id       bigint,
    start_date     date,
    type           text,
    rev            numeric,
    cpa            numeric,
    cpl            numeric,
    synced_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS voonix_campaign_deals_campaign_idx ON voonix_campaign_deals (campaign_id);

CREATE TABLE IF NOT EXISTS voonix_sites (
    id          bigint PRIMARY KEY,
    name        text,
    group_name  text,
    url         text,
    country     text,
    raw         jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS voonix_payers (
    id                 bigint PRIMARY KEY,
    name               text,
    payer_advertisers  text,
    payment_provider   text,
    payment_method     text,
    threshold          numeric,
    address            text,
    zip                text,
    city               text,
    country            text,
    vat                text,
    raw                jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS voonix_data_validation (
    login_id           bigint PRIMARY KEY,
    advertiser_id      bigint,
    advertiser_name    text,
    login_username     text,
    affiliate_system   text,
    data_from_api      text,
    columns            jsonb NOT NULL DEFAULT '{}'::jsonb,
    missing_count      integer,
    unavailable_count  integer,
    synced_at          timestamptz NOT NULL DEFAULT now()
);

-- ── Facts (one calendar month per API call, replaced atomically) ────────────

CREATE TABLE IF NOT EXISTS voonix_advertiser_earnings (
    period_month     date NOT NULL,
    row_no           integer NOT NULL,
    date             date,
    advertiser_id    bigint,
    advertiser_name  text,
    login_id         bigint,
    login_username   text,
    campaign_key     text,
    campaign_name    text,
    clicks           numeric,
    unique_clicks    numeric,
    signups          numeric,
    active_players   numeric,
    depositors       numeric,
    deposits         numeric,
    deposit_value    numeric,
    ftd              numeric,
    cpa_count        numeric,
    rev_income       numeric,
    cpa_income       numeric,
    cpl_income       numeric,
    extra_fee        numeric,
    bonus            numeric,
    net_revenue      numeric,
    turnover         numeric,
    -- Commission = revshare + CPA + CPL income. Extra fee is kept separate:
    -- the docs don't say whether it is income or a cost. VERIFY with a live account.
    commission       numeric GENERATED ALWAYS AS
                       (COALESCE(rev_income, 0) + COALESCE(cpa_income, 0) + COALESCE(cpl_income, 0)) STORED,
    raw              jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (period_month, row_no)
);
CREATE INDEX IF NOT EXISTS voonix_adv_earn_date_idx ON voonix_advertiser_earnings (date);
CREATE INDEX IF NOT EXISTS voonix_adv_earn_advertiser_idx ON voonix_advertiser_earnings (advertiser_id, date);

CREATE TABLE IF NOT EXISTS voonix_site_earnings (
    period_month     date NOT NULL,
    row_no           integer NOT NULL,
    date             date,
    site_id          bigint,
    site_name        text,
    site_group       text,
    advertiser_id    bigint,
    advertiser_name  text,
    clicks           numeric,
    unique_clicks    numeric,
    signups          numeric,
    active_players   numeric,
    depositors       numeric,
    deposits         numeric,
    deposit_value    numeric,
    ftd              numeric,
    cpa_count        numeric,
    rev_income       numeric,
    cpa_income       numeric,
    cpl_income       numeric,
    extra_fee        numeric,
    bonus            numeric,
    net_revenue      numeric,
    turnover         numeric,
    commission       numeric GENERATED ALWAYS AS
                       (COALESCE(rev_income, 0) + COALESCE(cpa_income, 0) + COALESCE(cpl_income, 0)) STORED,
    raw              jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (period_month, row_no)
);
CREATE INDEX IF NOT EXISTS voonix_site_earn_date_idx ON voonix_site_earnings (date);

CREATE TABLE IF NOT EXISTS voonix_invoice_earnings (
    period_month   date NOT NULL,
    row_no         integer NOT NULL,
    date           date,
    host           text,
    username       text,
    brand          text,
    campaign       text,
    payment_id     text,
    product        text,
    reward_plan    text,
    currency_code  text,
    exchange_rate  numeric,
    base_currency  text,
    deposit_value  numeric,
    rev_income     numeric,
    cpa_income     numeric,
    extra_fee      numeric,
    bonus          numeric,
    net_revenue    numeric,
    gross_revenue  numeric,
    turnover       numeric,
    deduction      numeric,
    total          numeric,
    raw_total      numeric,
    raw            jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (period_month, row_no)
);
CREATE INDEX IF NOT EXISTS voonix_inv_earn_date_idx ON voonix_invoice_earnings (date);

CREATE TABLE IF NOT EXISTS voonix_payouts (
    period_month   date NOT NULL,
    row_no         integer NOT NULL,
    host           text,
    username       text,
    brand          text,
    campaign       text,
    currency_code  text,
    exchange_rate  numeric,
    base_currency  text,
    deposit_value  numeric,
    rev_income     numeric,
    cpa_income     numeric,
    extra_fee      numeric,
    bonus          numeric,
    net_revenue    numeric,
    gross_revenue  numeric,
    turnover       numeric,
    deduction      numeric,
    total          numeric,
    raw_total      numeric,
    raw            jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (period_month, row_no)
);

CREATE TABLE IF NOT EXISTS voonix_custom_stats (
    period_month     date NOT NULL,
    row_no           integer NOT NULL,
    date             date,
    custom_id        bigint,
    advertiser_id    bigint,
    advertiser_name  text,
    login_id         bigint,
    login_username   text,
    campaign_key     text,
    campaign_name    text,
    clicks           numeric,
    unique_clicks    numeric,
    signups          numeric,
    active_players   numeric,
    depositors       numeric,
    deposits         numeric,
    deposit_value    numeric,
    ndc              numeric,
    qndc             numeric,
    ftd              numeric,
    cpa_count        numeric,
    rev_income       numeric,
    cpa_income       numeric,
    extra_fee        numeric,
    bonus            numeric,
    net_revenue      numeric,
    turnover         numeric,
    gross_revenue    numeric,
    raw              jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (period_month, row_no)
);
CREATE INDEX IF NOT EXISTS voonix_custom_stats_date_idx ON voonix_custom_stats (date);

CREATE TABLE IF NOT EXISTS voonix_datamonitor (
    date           date NOT NULL,
    row_no         integer NOT NULL,
    advertiser_id  bigint,
    advertiser     text,
    login_id       bigint,
    username       text,
    campaign_key   text,
    metric         text,
    current_value  numeric,
    backup_value   numeric,
    difference     numeric,
    synced_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (date, row_no)
);

-- ── Plugin bookkeeping ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS voonix_sync_state (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Every create/update/delete sent to Voonix. Secrets are redacted before insert.
CREATE TABLE IF NOT EXISTS voonix_write_log (
    id               text PRIMARY KEY,
    created_at       timestamptz NOT NULL DEFAULT now(),
    actor            text,
    resource         text NOT NULL,
    op               text NOT NULL,
    row_count        integer,
    ok               boolean,
    succeeded_count  integer,
    failed_count     integer,
    request          jsonb,
    response         jsonb,
    error            text
);
CREATE INDEX IF NOT EXISTS voonix_write_log_created_idx ON voonix_write_log (created_at DESC);
