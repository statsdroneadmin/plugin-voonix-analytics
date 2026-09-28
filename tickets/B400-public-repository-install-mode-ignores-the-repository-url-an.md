# B400 — "Public Repository" install mode ignores the repository URL and fails registry lookup (target: v?.?.?)

**Severity:** Medium — public/open-source plugins cannot be installed through the mode named for them. Workaround exists (use a "Private" mode), so not blocking.
**Type:** Frontend rendering / install API contract
**Filed by:** voonix-analytics v0.2.3
**Filed on:** 2026-09-28

## Repro

1. Publish a plugin repo publicly on GitHub, with a git tag matching `plugin.yaml` `version:`
   (here: `https://github.com/statsdroneadmin/plugin-voonix-analytics.git`, tag `v0.2.3`,
   `visibility: public` in the manifest). Anonymous clone works:
   `GIT_TERMINAL_PROMPT=0 git -c credential.helper= ls-remote <https url>` succeeds.
2. NousViz → Install Plugin → choose **Public Repository**.
3. Paste the HTTPS repository URL. The form accepts it and shows `Plugin ID: voonix-analytics`,
   so the UI clearly parsed the URL.
4. Click **Install Plugin**.

**Expected:** NousViz clones the public repo at its latest tag and installs it, as the mode's
own description implies ("Open-source plugin on GitHub/GitLab").

**Actual:** install fails with

> Plugin 'voonix-analytics' not found in official or community registry.
> Provide a repository_url in the request body to install a private plugin.

The same repo installs fine through **Private (SSH Key)** / **Private (Token)**, which do send
the URL. (Operator confirms the earlier private-repo installs of this plugin worked.)

## Root cause

Not cited to file:line — this plugin repo deliberately has no NousViz core checkout
(per the authoring guide's "You don't need a NousViz core checkout").

Inferred from the error text plus the UI state: in **Public Repository** mode the frontend posts
only the derived `plugin_id` and omits `repository_url`, so the install handler falls back to a
registry lookup; the plugin isn't in the official/community registry, so it 404s. The error
message then asks for the very field the form collected but didn't send. This is the classic
read/write asymmetry in appendix-gotchas G-8: the UI gathers a value that the request path drops.

## Why a plugin can't fix this

It is entirely core-side: the install request is built by NousViz's frontend and handled by
core's install route. No manifest field changes it — `visibility: public`, a public HTTPS
`repository:` URL and a matching tag are all already set on this plugin.

## Suggested fix

Either:

1. **Send the URL in this mode too** — have Public Repository mode post `repository_url`
   alongside `plugin_id`, exactly as the Private modes do, and clone anonymously (no
   credentials). Cheapest fix, matches what the mode's description promises; or
2. **Relabel the mode** if it is meant only for registry-listed plugins (e.g. "From NousViz
   registry"), hide the URL box in that mode, and point non-registry repos at a "From Git URL"
   option that doesn't imply credentials are required.

Also worth making the error actionable: when a URL is present in the form, say which mode to use
rather than "Provide a repository_url in the request body".
