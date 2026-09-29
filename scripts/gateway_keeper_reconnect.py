#!/usr/bin/env python3
"""Reconnect JARVIS after the paper IB Gateway becomes available.

The API key is read from the local gitignored engine/.env and is never printed.
The command fails unless independent execution-health fields agree that the
Gateway, execution leg, and data leg are healthy and live trading remains off.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / "engine" / ".env"
ENGINE_BASE = os.environ.get("JARVIS_ENGINE_BASE", "http://127.0.0.1:8010").rstrip("/")
VERIFY_DELAY_SECONDS = float(os.environ.get("JARVIS_GATEWAY_VERIFY_DELAY_SECONDS", "5"))
RECONNECT_BUDGET_SECONDS = float(os.environ.get("JARVIS_GATEWAY_RECONNECT_BUDGET_SECONDS", "120"))


def read_api_key(env_path: Path = ENV_PATH) -> str:
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("API_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    raise RuntimeError(f"API_KEY is missing from {env_path}")


def request_json(path: str, method: str = "GET") -> dict[str, Any]:
    request = urllib.request.Request(
        f"{ENGINE_BASE}{path}",
        method=method,
        headers={"X-API-Key": read_api_key()},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed localhost base
        body = response.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def authoritative_checks(health: dict[str, Any]) -> dict[str, bool]:
    return {
        "ibgateway_alive": health.get("ibgateway_alive") is True,
        "execution_connected_verified": health.get("execution_connected_verified") is True,
        "ib_execution_stale": health.get("ib_execution_stale") is False,
        "ibkr_data_connected": health.get("ibkr_data_connected") is True,
        "live_trading": health.get("live_trading") is False,
    }


def main() -> int:
    deadline = time.monotonic() + RECONNECT_BUDGET_SECONDS
    reconnect: dict[str, Any] | None = None
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            reconnect = request_json("/data/reconnect", method="POST")
            break
        except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            time.sleep(3)
    if reconnect is None:
        print(f"Reconnect failed: {type(last_error).__name__ if last_error else 'timeout'}")
        return 1
    print(f"Reconnect: {reconnect.get('status') or reconnect.get('message') or 'requested'}")
    time.sleep(VERIFY_DELAY_SECONDS)
    checks = authoritative_checks(request_json("/health"))
    for name, passed in checks.items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
