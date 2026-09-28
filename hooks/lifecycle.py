"""
hooks/lifecycle.py — lifecycle hooks for voonix-analytics.

Hooks run in their own subprocess with the credential broker available.
Reference: docs/06-sync-and-jobs.md "Lifecycle hooks"
"""

from __future__ import annotations

import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from nousviz_sdk.hooks import HookContext, HookResult

import voonix_analytics_mappers as mp
import voonix_analytics_store as st
from voonix_analytics_client import VoonixError


def on_credentials_saved(ctx: HookContext) -> HookResult:
    """Probe Voonix right after the operator saves the URL + key. A failure
    doesn't undo the save — the message tells them what to fix."""
    try:
        client = st.make_client()
        systems = len(mp.rows_from(client.probe()))
    except VoonixError as e:
        return HookResult(ok=False, message=f"Saved, but Voonix didn't accept it: {str(e)[:200]}")
    except Exception as e:
        return HookResult(ok=False, message=f"Saved, but the check failed: {e.__class__.__name__}: {e}")
    return HookResult(
        ok=True,
        message=f"Connected to Voonix ({systems} affiliate systems visible). Click 'Run sync' to import your data.",
        data={"affiliate_systems": systems},
    )


def on_first_run_success(ctx: HookContext) -> HookResult:
    return HookResult(
        ok=True,
        message="Voonix data imported. The Sync tab shows what each report returned; "
                "use 'Fetch older history' to look further back.",
    )
