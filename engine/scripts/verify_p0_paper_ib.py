#!/usr/bin/env python3
"""
P0 paper + IB verification helper (automates Sections 2–4 of the runbook where possible).

Usage (engine running on BASE, with API key in env):
  cd engine
  .venv\\Scripts\\python scripts\\verify_p0_paper_ib.py

Env:
  JARVIS_VERIFY_BASE   — default http://127.0.0.1:8010
  JARVIS_API_KEY / X_API_KEY / API_KEY — must match engine API_KEY for protected routes
  CHECK_IB_PORT        — if set to 1, try TCP connect to IBKR_HOST:IBKR_PORT (default 127.0.0.1:4002 paper Gateway)
"""

from __future__ import annotations

import json
import os
import socket
import sys
from typing import Any

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx", file=sys.stderr)
    sys.exit(2)


def _key() -> str:
    return (
        os.environ.get("JARVIS_API_KEY")
        or os.environ.get("X_API_KEY")
        or os.environ.get("API_KEY")
        or ""
    )


def _check_tcp(host: str, port: int, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"TCP {host}:{port} open"
    except OSError as e:
        return False, f"TCP {host}:{port} failed: {e}"


def main() -> int:
    base = os.environ.get("JARVIS_VERIFY_BASE", "http://127.0.0.1:8010").rstrip("/")
    key = _key()
    results: dict[str, Any] = {"base": base, "checks": []}

    if os.environ.get("CHECK_IB_PORT", "").strip() in ("1", "true", "yes"):
        host = os.environ.get("IBKR_HOST", "127.0.0.1")
        port = int(os.environ.get("IBKR_PORT", "4002"))
        ok, msg = _check_tcp(host, port)
        results["checks"].append({"name": "ib_tcp_port", "ok": ok, "detail": msg})
        print(msg)

    # Public health (no key) — paper-IB verifier cares about the execution path
    # specifically, so prefer ibkr_execution_connected and fall back to the
    # legacy ibkr_connected (OR of execution + data) for older engines.
    try:
        r = httpx.get(f"{base}/health", timeout=10.0)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        ok = r.status_code == 200
        ib_exec = body.get("ibkr_execution_connected")
        ib_data = body.get("ibkr_data_connected")
        ib_legacy = body.get("ibkr_connected")
        ib = ib_exec if ib_exec is not None else ib_legacy
        results["checks"].append(
            {
                "name": "GET /health",
                "ok": ok,
                "status_code": r.status_code,
                "ibkr_execution_connected": ib_exec,
                "ibkr_data_connected": ib_data,
                "ibkr_connected": ib_legacy,
            }
        )
        print(
            f"GET /health -> {r.status_code} "
            f"execution={ib_exec} data={ib_data} legacy={ib_legacy} (effective={ib})"
        )
    except Exception as e:
        results["checks"].append({"name": "GET /health", "ok": False, "error": str(e)})
        print(f"GET /health FAILED: {e}")

    if key:
        headers = {"X-API-Key": key}
        for path in (
            "/health/full",
            "/safety/status",
            "/safety/circuit-breakers",
            "/portfolio/paper/positions",
        ):
            try:
                r = httpx.get(f"{base}{path}", headers=headers, timeout=15.0)
                results["checks"].append(
                    {
                        "name": f"GET {path}",
                        "ok": r.status_code in (200, 503),
                        "status_code": r.status_code,
                    }
                )
                print(f"GET {path} -> {r.status_code}")
            except Exception as e:
                results["checks"].append({"name": f"GET {path}", "ok": False, "error": str(e)})
                print(f"GET {path} FAILED: {e}")
    else:
        print("No JARVIS_API_KEY — skipped authenticated routes (set key to match engine).")
        results["checks"].append(
            {
                "name": "authenticated_routes",
                "ok": True,
                "detail": "skipped — missing API key env",
            }
        )

    all_ok = all(c.get("ok") for c in results["checks"])

    print(json.dumps(results, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
