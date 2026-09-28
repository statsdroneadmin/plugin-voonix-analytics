/// <reference path="./nousviz_widget_types.d.ts" />
/**
 * Shared download helper for VoonixExport and VoonixReport (not a widget —
 * build.sh only bundles *.tsx entry points; esbuild inlines this into each).
 *
 * Fetches with the session token (apiFetch), saves the response as a Blob,
 * and names the file from Content-Disposition. Server error details
 * ({"detail": "..."}) are surfaced as the thrown message.
 */

export async function downloadFile(url: string, fallbackName: string): Promise<Response> {
  const r = await window.NousViz.widgets.apiFetch(url);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const body = await r.json();
      if (body && body.detail) msg = String(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  const cd = r.headers.get("Content-Disposition") || "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = match ? decodeURIComponent(match[1]) : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  return r;
}
