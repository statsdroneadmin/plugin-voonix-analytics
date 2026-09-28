"""
src/voonix_analytics_client.py — Voonix API v3 HTTP client.

URL shape (docs-voonix-api/API_NOTES.md):
  GET  {base}/api/?report=<report>&v3&list&<filters>&key=<API key>
  POST {base}/api/?report=<report>&v3&<op>&JSON&key=<API key>   body: JSON array

`v3`, `list`, `JSON` and the op are bare flags (no value), so the query
string is assembled by hand — a params dict would render `v3=`.

Auth: the docs say the key goes in `&key` "or as a header" but never name
the header, so the URL form is the only documented one. Because the key is
in the URL, every error message is scrubbed before it leaves this module.

GETs retry on 429/5xx. POSTs never retry: a create that timed out may have
succeeded, and a blind retry would create it twice.

**Standard library only.** v0.2.0 used `requests` and failed to load on a
real NousViz host with ModuleNotFoundError; the SDK's own guidance is that
plugin runtime deps are the host env's business and plugins don't ship a
runtime requirements.txt (01-getting-started.md:110). urllib is always
there. No SDK imports either, so this stays testable outside the worker.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote


USER_AGENT = "nousviz-plugin-voonix-analytics/0.2.3"
RETRY_STATUS = {429, 500, 502, 503, 504}


class VoonixError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def normalise_base_url(url: str | None) -> str:
    """Accepts 'yourcompany.voonix.net', 'https://yourcompany.voonix.net/',
    or a pasted endpoint like 'https://x.voonix.net/api/?report=…'."""
    u = (url or "").strip()
    if not u:
        raise VoonixError("Voonix URL is not configured. Save it on the Settings tab.")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    u = u.split("?", 1)[0].rstrip("/")
    if u.endswith("/api"):
        u = u[: -len("/api")]
    return u


class VoonixClient:
    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        timeout: int = 120,
        min_interval: float = 0.35,
        max_retries: int = 3,
    ):
        if not api_key:
            raise VoonixError("Voonix API key is not configured. Save it on the Settings tab.")
        self._base = normalise_base_url(base_url)
        self._key = api_key
        self._timeout = timeout
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_call = 0.0
        # No cookie/redirect surprises: a plain opener, one per client.
        self._opener = urllib.request.build_opener()

    @property
    def base_url(self) -> str:
        return self._base

    # ── Internals ────────────────────────────────────────────────────────

    def _scrub(self, value: Any) -> str:
        s = str(value)
        for secret in {self._key, quote(self._key, safe="")}:
            if secret:
                s = s.replace(secret, "***")
        return s

    def _url(self, report: str, flags: tuple[str, ...], params: dict[str, Any] | None) -> str:
        parts = [f"report={quote(report, safe='')}"]
        parts += [quote(f, safe="") for f in flags]
        for k, v in (params or {}).items():
            if v is None or v is False:
                continue
            if v is True:
                parts.append(quote(k, safe=""))
            else:
                parts.append(f"{quote(k, safe='')}={quote(str(v), safe=',')}")
        parts.append(f"key={quote(self._key, safe='')}")
        return f"{self._base}/api/?" + "&".join(parts)

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @staticmethod
    def _read(response: Any) -> str:
        raw = response.read()
        if (response.headers.get("Content-Encoding") or "").lower() == "gzip":
            raw = gzip.decompress(raw)
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")

    def _decode(self, body: str, status: int, report: str) -> Any:
        try:
            data = json.loads(body.lstrip("﻿").strip())
        except ValueError:
            raise VoonixError(
                f"Voonix returned something that isn't JSON for report={report} "
                f"(HTTP {status}): {self._scrub(body[:200])}",
                status,
                self._scrub(body[:1000]),
            ) from None
        if isinstance(data, dict):
            http = data.get("http") if isinstance(data.get("http"), dict) else {}
            try:
                code = int(str(http.get("code")).strip()) if http.get("code") is not None else None
            except ValueError:
                code = None
            if code is not None and code >= 400:
                detail = data.get("error") or data.get("message") or http.get("status") or ""
                raise VoonixError(
                    f"Voonix error {code} for report={report}: {self._scrub(detail)}",
                    code,
                    self._scrub(body[:1000]),
                )
            if data.get("success") in (0, "0", False) and not data.get("data"):
                detail = data.get("error") or data.get("message") or "success=0"
                raise VoonixError(
                    f"Voonix reported failure for report={report}: {self._scrub(detail)}",
                    status,
                    self._scrub(body[:1000]),
                )
        return data

    def _send(
        self,
        method: str,
        report: str,
        flags: tuple[str, ...],
        params: dict[str, Any] | None = None,
        body: Any = None,
    ) -> Any:
        url = self._url(report, flags, params)
        data = json.dumps(body, default=str).encode("utf-8") if body is not None else None
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        attempts = self._max_retries + 1 if method == "GET" else 1

        for attempt in range(attempts):
            last = attempt == attempts - 1
            self._throttle()
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with self._opener.open(request, timeout=self._timeout) as response:
                    return self._decode(self._read(response), response.status, report)
            except urllib.error.HTTPError as e:
                status = e.code
                try:
                    text = self._read(e)
                except Exception:
                    text = ""
                if status in RETRY_STATUS and not last:
                    retry_after = (e.headers.get("Retry-After") or "").strip()
                    wait = int(retry_after) if retry_after.isdigit() else 3 * (attempt + 1)
                    time.sleep(min(wait, 60))
                    continue
                if status in (401, 403):
                    raise VoonixError(
                        f"Voonix rejected the request (HTTP {status}). Check the API key "
                        "and that the Voonix URL is your own account's address.",
                        status,
                        self._scrub(text[:1000]),
                    ) from None
                raise VoonixError(
                    f"HTTP {status} from Voonix report={report}: {self._scrub(text[:300])}",
                    status,
                    self._scrub(text[:1000]),
                ) from None
            except urllib.error.URLError as e:
                if not last:
                    time.sleep(2 * (attempt + 1))
                    continue
                # `from None`: the chained error can carry the URL (and the key).
                raise VoonixError(
                    f"Network error calling Voonix report={report}: {self._scrub(e.reason)}"
                ) from None
            except TimeoutError:
                if not last:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise VoonixError(
                    f"Voonix timed out after {self._timeout}s for report={report}"
                ) from None
        raise VoonixError(f"Voonix report={report} failed after retries")  # unreachable

    # ── Public ───────────────────────────────────────────────────────────

    def get(self, report: str, flag: str | None = "list", **params: Any) -> Any:
        flags = ("v3", flag) if flag else ("v3",)
        return self._send("GET", report, flags, params)

    def write(self, report: str, op: str, rows: list[dict[str, Any]]) -> Any:
        return self._send("POST", report, ("v3", op, "JSON"), body=rows)

    def probe(self) -> Any:
        """Cheapest read that proves URL + key: the affiliate-systems list."""
        return self.get("affiliatesystems", flag=None)
