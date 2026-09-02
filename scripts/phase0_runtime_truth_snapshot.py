#!/usr/bin/env python3
"""Read-only JARVIS Phase-0 runtime truth snapshot.

JARVIS-MIP-1.0 / A-01

Purpose
-------
Capture the small set of *loaded runtime facts* required to close A-01 without
printing or persisting API keys, broker account IDs, tokens, or raw config
payloads.  The script performs GET requests only and never imports engine code,
so running it cannot initialize a broker connector or mutate trading state.

Default usage from repository root::

    python scripts/phase0_runtime_truth_snapshot.py

Windows canonical interpreter when available::

    engine\\.venv\\Scripts\\python scripts\\phase0_runtime_truth_snapshot.py

The output file is intentionally safe-by-construction and contains no raw
secret-bearing string fields.  Review it before committing or sharing anyway.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_ENV = REPO_ROOT / "engine" / ".env"
DEFAULT_ENGINE_URL = "http://127.0.0.1:8010"
DEFAULT_OUTPUT = REPO_ROOT / "phase0_runtime_truth_snapshot.json"

# Only these config fields may enter the artifact.  The source endpoint itself
# redacts strings by default, but this second allowlist prevents a future router
# change from accidentally expanding the snapshot's secret surface.
SAFE_CONFIG_KEYS = {
    "MAX_POSITION_SIZE_PCT",
    "MAX_DAILY_LOSS_PCT",
    "MAX_DAILY_LOSS_USD",
    "MAX_TRADE_LOSS_USD",
    "MAX_DRAWDOWN_PCT",
    "MAX_ORDERS_PER_MINUTE",
    "MAX_CORRELATED_EXPOSURE_PCT",
    "PRICE_COLLAR_PCT",
    "MAX_SINGLE_ORDER_VALUE",
    "MAX_MARGIN_UTILIZATION",
    "MAX_CONTRACTS_PER_INSTRUMENT",
    "MAX_OVERNIGHT_CONTRACTS",
    "CORRELATED_PAIR_MAX_CONTRACTS",
    "LIVE_TRADING_ENABLED",
    "REQUIRE_HUMAN_APPROVAL",
    "PAPER_TRADING",
    "IB_PAPER_BROKER_ENABLED",
    "IBKR_PORT",
    "IBKR_PAPER_MODE",
    "ALLOW_PAPER_SIMULATED_ORDERS",
    "FUTURES_WATCHLIST",
    "OPTIONS_WATCHLIST",
    "JARVIS_LLM_PROVIDER",
}

# Health fields selected recursively by key.  Values are admitted only when
# they are non-string scalars/containers of similarly safe values; free-form
# strings are omitted except for a narrow status/source vocabulary below.
SAFE_HEALTH_KEYS = {
    "status",
    "mode",
    "live_trading",
    "paper_trading",
    "ibkr_connected",
    "ibkr_execution_connected",
    "execution_connected_verified",
    "ib_execution_stale",
    "ibgateway_alive",
    "data_connected",
    "database_connected",
    "database",
    "execution_path",
    "simulated",
    "broker_ack",
    "source",
    "quality",
    "stale",
    "age_seconds",
    "latency_ms",
    "schema_version",
    "backup_count",
    "last_backup_age_hours",
    "healthy",
    "reachable",
    "verified",
}

SAFE_STRING_VALUES = {
    "ok",
    "healthy",
    "degraded",
    "unhealthy",
    "error",
    "unknown",
    "paper",
    "live",
    "simulated",
    "verified",
    "stale",
    "fresh",
    "ibkr",
    "ibkr_delayed",
    "ibkr_historical",
    "polygon",
    "redis",
    "sqlite",
    "connected",
    "disconnected",
    "unavailable",
}


def _parse_env_value(path: Path, name: str) -> str | None:
    """Return one .env value without loading the file into process environment."""
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value or None
    return None


def _api_key() -> str | None:
    # Explicit process environment wins for operators who do not use engine/.env.
    return os.environ.get("JARVIS_API_KEY") or os.environ.get("API_KEY") or _parse_env_value(
        ENGINE_ENV, "API_KEY"
    )


def _get_json(base_url: str, path: str, api_key: str | None, timeout: float) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    headers = {"Accept": "application/json", "User-Agent": "jarvis-phase0-truth-snapshot/1.0"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(url=url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                return {
                    "reachable": True,
                    "http_status": int(response.status),
                    "json": False,
                    "error": "non_json_response",
                }
            return {
                "reachable": True,
                "http_status": int(response.status),
                "json": True,
                "body": body,
            }
    except urllib.error.HTTPError as exc:
        return {"reachable": True, "http_status": int(exc.code), "json": False, "error": "http_error"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "reachable": False,
            "http_status": None,
            "json": False,
            "error": type(exc).__name__,
        }


def _flatten_config(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    categories = payload.get("categories")
    if not isinstance(categories, dict):
        return {}
    result: dict[str, Any] = {}
    for items in categories.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            if key not in SAFE_CONFIG_KEYS:
                continue
            value = item.get("value")
            # A secret-bearing string must never be copied, even if a key is
            # accidentally added to SAFE_CONFIG_KEYS later.  The accepted
            # string config values here are provider/mode names only.
            if isinstance(value, str) and key != "JARVIS_LLM_PROVIDER":
                continue
            if key == "JARVIS_LLM_PROVIDER" and isinstance(value, str):
                value = value.strip().lower()[:40]
            result[str(key)] = value
    return dict(sorted(result.items()))


def _sanitize_health(value: Any, parent_key: str | None = None) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        return value if normalized in SAFE_STRING_VALUES else None
    if isinstance(value, list):
        safe_list = []
        for item in value:
            clean = _sanitize_health(item, parent_key)
            if clean is not None:
                safe_list.append(clean)
        return safe_list
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key not in SAFE_HEALTH_KEYS:
                continue
            clean = _sanitize_health(item, str(key))
            if clean is not None:
                result[str(key)] = clean
        return result
    return None


def _safe_endpoint_result(result: dict[str, Any], kind: str) -> dict[str, Any]:
    base = {
        "reachable": bool(result.get("reachable")),
        "http_status": result.get("http_status"),
        "json": bool(result.get("json")),
    }
    body = result.get("body")
    if not isinstance(body, dict):
        if result.get("error"):
            base["error"] = result["error"]
        return base
    if kind == "config":
        base["safe_config"] = _flatten_config(body)
    elif kind == "eligibility":
        # Eligibility is deliberately summarized instead of persisting the raw
        # response.  Symbol names and boolean verdicts are not secrets.
        instruments = body.get("instruments")
        rows: list[dict[str, Any]] = []
        if isinstance(instruments, list):
            for row in instruments:
                if not isinstance(row, dict):
                    continue
                symbol = row.get("symbol")
                if not isinstance(symbol, str) or not symbol or len(symbol) > 20:
                    continue
                rows.append(
                    {
                        "symbol": symbol.upper(),
                        "overall_pass": bool(row.get("overall_pass", False)),
                    }
                )
        base["instruments"] = rows
        if isinstance(body.get("total"), int):
            base["total"] = body["total"]
    else:
        base["safe_health"] = _sanitize_health(body)
    return base


def _git(*args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_snapshot(engine_url: str, timeout: float) -> dict[str, Any]:
    key = _api_key()
    endpoints = {
        "config_overview": ("/config/overview", "config"),
        "health": ("/health", "health"),
        "health_full": ("/health/full", "health"),
        "safety_status": ("/safety/status", "health"),
        "eligibility": ("/paper/validation/approved-paper-gates", "eligibility"),
        "backup_status": ("/health/backup-status", "health"),
    }
    api: dict[str, Any] = {}
    for name, (path, kind) in endpoints.items():
        result = _get_json(engine_url, path, key, timeout)
        api[name] = _safe_endpoint_result(result, kind)

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    return {
        "artifact": "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT",
        "schema_version": 1,
        "captured_at_utc": now,
        "read_only": True,
        "secrets_included": False,
        "api_key_available_for_probe": bool(key),
        "repository": {
            "head": _git("rev-parse", "HEAD"),
            "branch": _git("branch", "--show-current"),
            "status_porcelain_count": len((_git("status", "--porcelain") or "").splitlines()),
        },
        "ports": {
            "engine_8010_open": _port_open("127.0.0.1", 8010),
            "dashboard_3010_open": _port_open("127.0.0.1", 3010),
            "ib_paper_4002_open": _port_open("127.0.0.1", 4002),
            "ib_live_4001_open": _port_open("127.0.0.1", 4001),
        },
        "engine_base_url": engine_url,
        "api": api,
        "operator_review": {
            "note": "Review before sharing. This artifact intentionally omits raw secret strings and broker account identifiers.",
            "a01_can_close_from_this_artifact_alone": False,
            "reason": "A-01 still requires interpretation/reconciliation of observed values against the contradiction register.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture a read-only, redacted JARVIS Phase-0 runtime truth snapshot.")
    parser.add_argument("--engine-url", default=DEFAULT_ENGINE_URL)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    snapshot = build_snapshot(args.engine_url, max(args.timeout, 0.1))
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"A-01 runtime truth snapshot written to: {output}")
    print(f"Engine reachable: {snapshot['api']['health']['reachable']}")
    print(f"Config probe reachable: {snapshot['api']['config_overview']['reachable']}")
    print(f"IB paper port 4002 open: {snapshot['ports']['ib_paper_4002_open']}")
    print("No API key or broker account ID was written to the artifact.")

    # The command itself is successful even when the engine is offline: offline
    # is a valid A-01 observation. Return nonzero only for an impossible output.
    return 0 if output.exists() else 2


if __name__ == "__main__":
    sys.exit(main())
