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

Cited against the local core checkout at `~/devhub/nousviz-0.9` (v0.9.5.1, 2026-04-27). Line
numbers may have moved in the deployed build, but the behaviour matches the observed error.

**The frontend deliberately withholds the URL in public mode** —
`apps/web/src/pages/InstallPluginPage.tsx:124-125`:

```ts
const body: Record<string, string> = {};
if (method !== "public") body.repository_url = repoUrl.trim();
```

So a public-mode install posts `{}`. The API then takes the "no explicit URL" path and, finding
no official/community stub for the slug, raises at
`apps/api/src/routes/plugins.py:1088-1093`:

```python
elif not explicit_repo_url:
    # Neither official nor community stub — require explicit URL
    raise HTTPException(
        404,
        f"Plugin '{plugin_id}' not found in official or community registry. "
        "Provide a repository_url in the request body to install a private plugin.",
    )
```

The UI shows the parsed URL and derived plugin ID, so the value exists client-side and is thrown
away before the request. Classic read/write asymmetry (appendix-gotchas G-8).

**The API already supports exactly what's needed.** `PluginInstallRequest.repository_url`
(`plugins.py:141-142`) is accepted from any caller, `_validate_repo_url` enforces the SSRF
blocklist, and the GitHub token is injected only when one is configured
(`plugins.py:133-136`):

```python
github_token = os.environ.get("GITHUB_TOKEN", "").strip()
if github_token and host and "github.com" in host and "@" not in (parsed.netloc or ""):
    url = url.replace("https://github.com", f"https://{github_token}@github.com")
```

With no token set, the public HTTPS URL is cloned as-is — anonymously. Verified out-of-band:
`GIT_TERMINAL_PROMPT=0 git -c credential.helper= ls-remote <public https url>` succeeds.

## Why a plugin can't fix this

It is entirely core-side: the install request is built by NousViz's frontend and handled by
core's install route. No manifest field changes it — `visibility: public`, a public HTTPS
`repository:` URL and a matching tag are all already set on this plugin.

## Suggested fix

One line, frontend only — `apps/web/src/pages/InstallPluginPage.tsx:125`:

```diff
  const body: Record<string, string> = {};
- if (method !== "public") body.repository_url = repoUrl.trim();
+ if (repoUrl.trim()) body.repository_url = repoUrl.trim();
```

Send whatever URL the operator typed, in every mode. The API needs no change: it validates the
URL, clones anonymously when no `GITHUB_TOKEN` is set, and an explicit URL already takes
precedence over a registry stub. Registry-listed installs are unaffected — they submit no URL,
so the body stays empty and Tier 1/Tier 2 resolution runs as before.

Optional follow-ups, not required for the fix:

- Make the 404 actionable: if the request has no `repository_url` but the caller is a browser
  form that had one, say which mode to use rather than "Provide a repository_url in the request
  body".
- Consider renaming the modes by *credential*, not repo visibility ("No credentials", "SSH key",
  "Token") — the current labels imply a public repo must use the public mode, which is the trap
  this ticket describes.

## Operator impact

Until this ships, any plugin not in the official/community registry can only be installed through
a "Private" mode, even when its repo is public and needs no credentials. That is friction for
every plugin an operator wants to share (this one is being shared with several people).
