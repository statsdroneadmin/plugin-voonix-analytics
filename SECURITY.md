# Security

## Reporting a vulnerability

Open a private security advisory on this repository (Security → Report a vulnerability),
or open an issue with no sensitive detail and ask for a private channel.

## What this plugin handles

- A **Voonix API key**, stored encrypted by NousViz (declared `type: password`) and never
  written to logs. The key travels in the query string because that is the only
  authentication Voonix documents; every error message is scrubbed of it before it is
  logged or returned.
- **Affiliate login passwords and keys (`key1`/`key2`)** returned by Voonix are discarded
  and never stored — not in tables, not in the raw JSON copies, not in exports.
- **Write access to a live Voonix account** is off by default (`allow_writes`), restricted
  to admins, requires typed confirmation for deletes, and is recorded in `voonix_write_log`
  with secrets redacted.

## Scope

This plugin runs inside NousViz and trusts its authentication. Findings about NousViz core
belong to the NousViz project, not here.
