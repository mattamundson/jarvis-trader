#!/usr/bin/env python3
"""
Rotate the local JARVIS dev API key used between engine and dashboard.

Writes:
  - engine/.env          -> API_KEY=<new>
  - dashboard/.env.local -> ENGINE_API_KEY=<same>
  - dashboard/.env.local -> NEXT_PUBLIC_ENGINE_API_KEY=<same> legacy/local alias

If engine/.env is missing, it is created by copying engine/.env.example first.

Usage (repo root):
    python scripts/rotate_dev_api_key.py

Never commit .env or .env.local. See docs/setup-guides/DEV_API_KEY_ROTATION.md.
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_ENV = ROOT / "engine" / ".env"
DASH_LOCAL = ROOT / "dashboard" / ".env.local"
ENV_EXAMPLE = ROOT / "engine" / ".env.example"


def _set_or_append_kv(content: str, key: str, value: str) -> str:
    """Replace KEY=... line or append KEY=value."""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(content):
        return pattern.sub(line, content, count=1)
    if content and not content.endswith("\n"):
        content += "\n"
    return content + line + "\n"


def main() -> int:
    if not ENV_EXAMPLE.is_file():
        print(f"ERROR: missing {ENV_EXAMPLE}", file=sys.stderr)
        return 1

    new_key = secrets.token_urlsafe(32)

    if not ENGINE_ENV.is_file():
        print(f"Creating {ENGINE_ENV} from .env.example …")
        ENGINE_ENV.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    eng = ENGINE_ENV.read_text(encoding="utf-8")
    eng = _set_or_append_kv(eng, "API_KEY", new_key)
    ENGINE_ENV.write_text(eng, encoding="utf-8")
    print(f"Updated API_KEY in {ENGINE_ENV}")

    dash = DASH_LOCAL.read_text(encoding="utf-8") if DASH_LOCAL.is_file() else ""
    if not dash.strip():
        dash = (
            "# Synced with engine/.env API_KEY by scripts/rotate_dev_api_key.py\n"
            "# Do not commit this file.\n"
        )
    dash = _set_or_append_kv(dash, "ENGINE_API_KEY", new_key)
    dash = _set_or_append_kv(dash, "NEXT_PUBLIC_ENGINE_API_KEY", new_key)
    DASH_LOCAL.write_text(dash, encoding="utf-8")
    print(f"Updated ENGINE_API_KEY and NEXT_PUBLIC_ENGINE_API_KEY in {DASH_LOCAL}")

    print("\nNext: restart engine (restart_engine.ps1) and dashboard (pnpm dev).")
    print("Verify: curl -s http://localhost:8010/safety/status -H \"X-API-Key: <paste from engine/.env>\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
