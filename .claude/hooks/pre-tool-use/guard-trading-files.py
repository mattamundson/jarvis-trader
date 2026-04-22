#!/usr/bin/env python3
# ============================================================================
# Event:      PreToolUse (matcher: Edit|Write)
# Purpose:    EXPANSION of the existing TIER 3 inline guard. Extends the
#             safety-critical file list to include execution/kill_switch.py,
#             agents/trader.py sizing bounds, and engine/.env. Emits a
#             permissionDecision:"ask" JSON payload so Matt must confirm.
# Pattern:    Existing jarvis-trader TIER 3 matcher (already in settings.json)
#             generalized to a script so the list is editable in one place.
# IMPORTANT:  This ADDS paths; it does NOT replace the two existing inline
#             echo hooks for safety_layer.py and config.py. Both can coexist —
#             Claude Code runs all PreToolUse hooks matching the event.
# Disable:    Remove from settings.local.json hooks.PreToolUse[], or
#             `chmod -x` this file. Default behavior = permit (exit 0 silent).
# ============================================================================
import json
import os
import sys
from pathlib import Path

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())

# Tier 3: requires explicit human ack before Edit/Write.
# Keep list short and load-bearing — false positives burn Matt's patience.
TIER3_SUFFIXES = (
    "engine/execution/kill_switch.py",
    "engine/execution/order_router.py",
    "engine/notifications/openclaw_notifier.py",
    "engine/.env",
    ".claude/settings.local.json",
    ".claude/settings.json",
    "restart_engine.ps1",
    "restart_engine_admin.ps1",
)


def read_payload():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def get_target_path(payload):
    ti = payload.get("tool_input") or {}
    return (ti.get("file_path") or ti.get("path") or "").replace("\\", "/")


def main():
    payload = read_payload()
    fp = get_target_path(payload)
    if not fp:
        return 0

    for suffix in TIER3_SUFFIXES:
        if fp.endswith(suffix):
            reason = (
                f"TIER 3: {suffix} controls live trading or kill-switch behavior. "
                "Explicit confirmation required before Edit/Write."
            )
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": reason,
                }
            }
            print(json.dumps(out))
            return 0

    # Default: permit silently.
    return 0


if __name__ == "__main__":
    sys.exit(main())
