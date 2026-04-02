#!/usr/bin/env python3
"""
P2.2 — One-shot pipeline smoke: POST /pipeline/run with API key.

Does not require Anthropic billing to return 200; engine may return 500 if pipeline
uninitialized — script reports status for session logs.

Usage:
  cd engine
  set JARVIS_API_KEY=your_key
  .venv\\Scripts\\python scripts\\smoke_pipeline.py
"""

from __future__ import annotations

import json
import os
import sys

try:
    import httpx
except ImportError:
    print("pip install httpx", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    base = os.environ.get("JARVIS_VERIFY_BASE", "http://127.0.0.1:8010").rstrip("/")
    key = os.environ.get("JARVIS_API_KEY") or os.environ.get("X_API_KEY") or os.environ.get("API_KEY")
    if not key:
        print("Set JARVIS_API_KEY (or X_API_KEY / API_KEY)", file=sys.stderr)
        return 2
    r = httpx.post(
        f"{base}/pipeline/run",
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        json={"symbol": "MNQ", "is_futures": True},
        timeout=120.0,
    )
    out = {
        "path": "/pipeline/run",
        "status_code": r.status_code,
        "body": r.text[:2000],
    }
    try:
        out["json"] = r.json()
    except Exception:
        pass
    print(json.dumps(out, indent=2))
    return 0 if r.status_code < 500 else 1


if __name__ == "__main__":
    raise SystemExit(main())
