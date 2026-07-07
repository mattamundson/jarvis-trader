#!/usr/bin/env python3
# ============================================================================
# Event:      PostToolUse (matcher: Edit|Write)
# Purpose:    Auto-format Python files with black (engine/.venv) and TS/JS
#             files with prettier (pnpm). Permit + log; never blocks.
# Pattern:    affaan-m__everything-claude-code (script-based post-edit hook)
#             shanraisshan__claude-code-best-practice (PostToolUse formatting)
# Cost:       Only runs on single-file edits; typically <500ms.
# Disable:    Remove from settings.local.json hooks.PostToolUse[], or
#             `chmod -x` this file. Exit is always 0; formatter failure
#             is logged to stderr but never blocks the agent.
# ============================================================================
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
PY_VENV = PROJECT / "engine" / ".venv" / "Scripts" / "python.exe"

# Files we refuse to auto-format — safety-critical trading logic.
# Changes here should be human-reviewed; auto-format can hide diffs.
SKIP_PATHS = (
    "engine/config.py",
    "engine/agents/safety_layer.py",
    "engine/execution/kill_switch.py",
)


def read_payload():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def get_edited_path(payload):
    # Claude Code PostToolUse payload shape: {"tool_input": {"file_path": ...}}
    ti = payload.get("tool_input") or {}
    return ti.get("file_path") or ti.get("path") or ""


def main():
    payload = read_payload()
    fp = get_edited_path(payload)
    if not fp:
        return 0

    path = Path(fp)
    if not path.is_file():
        return 0

    rel = str(path).replace("\\", "/")
    for skip in SKIP_PATHS:
        if rel.endswith(skip) or skip in rel:
            print(f"[auto-format] skip (trading-critical): {rel}", file=sys.stderr)
            return 0

    suffix = path.suffix.lower()
    try:
        if suffix == ".py" and PY_VENV.exists():
            subprocess.run(
                [str(PY_VENV), "-m", "black", "--quiet", str(path)],
                timeout=15,
                check=False,
            )
        elif suffix in (".ts", ".tsx", ".js", ".jsx", ".json", ".md"):
            # pnpm prettier — writes in place. Silent on success.
            subprocess.run(
                ["pnpm", "exec", "prettier", "--write", "--log-level", "warn", str(path)],
                timeout=20,
                check=False,
                cwd=str(PROJECT),
                shell=False,
            )
    except Exception as e:
        print(f"[auto-format] formatter error (ignored): {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
