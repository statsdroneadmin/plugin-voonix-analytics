-- 001_voonix_core_down.sql — reverses 001_voonix_core.sql ("Uninstall with Remove data").

DROP TABLE IF EXISTS voonix_write_log;
DROP TABLE IF EXISTS voonix_sync_state;
DROP TABLE IF EXISTS voonix_datamonitor;
DROP TABLE IF EXISTS voonix_custom_stats;
DROP TABLE IF EXISTS voonix_payouts;
DROP TABLE IF EXISTS voonix_invoice_earnings;
DROP TABLE IF EXISTS voonix_site_earnings;
DROP TABLE IF EXISTS voonix_advertiser_earnings;
DROP TABLE IF EXISTS voonix_data_validation;
DROP TABLE IF EXISTS voonix_payers;
DROP TABLE IF EXISTS voonix_sites;
DROP TABLE IF EXISTS voonix_campaign_deals;
DROP TABLE IF EXISTS voonix_campaigns;
DROP TABLE IF EXISTS voonix_login_history_deals;
DROP TABLE IF EXISTS voonix_logins;
DROP TABLE IF EXISTS voonix_advertisers;
DROP TABLE IF EXISTS voonix_affiliate_systems;
