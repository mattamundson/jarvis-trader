#!/usr/bin/env python3
"""Capture a read-only, redacted JARVIS A-01 runtime snapshot.

The script performs loopback-only HTTP GET requests and TCP reachability probes.
It never imports engine modules or invokes a mutation endpoint. The generated
JSON is an observation artifact, not proof that A-01 is complete.
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
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_ENV = REPO_ROOT / "engine" / ".env"
DEFAULT_ENGINE_URL = "http://127.0.0.1:8010"
DEFAULT_OUTPUT = REPO_ROOT / "phase0_runtime_truth_snapshot.json"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

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

SAFE_HEALTH_KEYS = {
    "overall",
    "subsystems",
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
    "kill_switch_active",
    "paper_mode",
    "daily_pnl",
    "daily_pnl_pct",
    "daily_limit",
    "daily_limit_pct",
    "daily_limit_breached",
    "drawdown_pct",
    "drawdown_limit_pct",
    "drawdown_limit_breached",
    "consecutive_losses",
    "orders_last_minute",
    "orders_last_minute_limit",
    "hard_halt",
    "halted",
    "safety_state",
    "safety_state_verified",
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
    "verified_safe",
    "verified_halted",
    "state_unknown",
    "not_configured",
    "circuit_breaker_tripped",
}

ENDPOINTS = {
    "config_overview": ("/config/overview", "config"),
    "health": ("/health", "health"),
    "health_full": ("/health/full", "health"),
    "safety_status": ("/safety/status", "health"),
    "eligibility": ("/trading-status", "eligibility"),
    "backup_status": ("/health/backup-status", "health"),
}


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward an authenticated loopback request to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _parse_env_value(path: Path, name: str) -> str | None:
    """Return one .env value without loading the file into the environment."""
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
    return os.environ.get("JARVIS_API_KEY") or os.environ.get("API_KEY") or _parse_env_value(
        ENGINE_ENV, "API_KEY"
    )


def _validate_engine_url(value: str) -> str:
    """Return a normalized loopback engine URL or raise ValueError.

    The API key must never be sent to an operator-supplied remote host. Userinfo,
    paths, queries, and fragments are disallowed for the same reason.
    """
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("engine URL scheme must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("engine URL must not contain credentials")
    host = (parsed.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise ValueError("engine URL must use localhost, 127.0.0.1, or ::1")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("engine URL must not contain a path, query, or fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("engine URL contains an invalid port") from exc
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


def _get_json(base_url: str, path: str, api_key: str | None, timeout: float) -> dict[str, Any]:
    if path not in {endpoint for endpoint, _ in ENDPOINTS.values()}:
        raise ValueError(f"endpoint is not allowlisted: {path}")
    url = base_url.rstrip("/") + path
    headers = {"Accept": "application/json", "User-Agent": "jarvis-a01-snapshot/1.0"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(url=url, headers=headers, method="GET")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectRedirects(),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
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
        return {
            "reachable": True,
            "http_status": int(exc.code),
            "json": False,
            "error": "http_error",
        }
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
            if isinstance(value, str) and key != "JARVIS_LLM_PROVIDER":
                continue
            if key == "JARVIS_LLM_PROVIDER" and isinstance(value, str):
                value = value.strip().lower()[:40]
            if isinstance(value, (dict, list)) and key not in {
                "FUTURES_WATCHLIST",
                "OPTIONS_WATCHLIST",
            }:
                continue
            result[str(key)] = value
    return dict(sorted(result.items()))


def _sanitize_health(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized if normalized in SAFE_STRING_VALUES else None
    if isinstance(value, list):
        return [clean for item in value if (clean := _sanitize_health(item)) is not None]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key not in SAFE_HEALTH_KEYS:
                continue
            if key == "subsystems" and isinstance(item, dict):
                subsystems: dict[str, Any] = {}
                for label, subsystem in item.items():
                    if not isinstance(label, str) or not label.replace("_", "").isalnum():
                        continue
                    clean = _sanitize_health(subsystem)
                    if clean not in (None, {}, []):
                        subsystems[label[:50]] = clean
                result[key] = subsystems
                continue
            clean = _sanitize_health(item)
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
        rows: list[dict[str, Any]] = []
        symbols = body.get("symbols")
        if isinstance(symbols, list):
            for row in symbols:
                if not isinstance(row, dict):
                    continue
                symbol = row.get("symbol")
                if not isinstance(symbol, str) or not symbol or len(symbol) > 20:
                    continue
                rows.append(
                    {
                        "symbol": symbol.upper(),
                        "enabled": bool(row.get("enabled", False)),
                        "authorized": bool(row.get("authorized", False)),
                        "tradeable": bool(row.get("tradeable", False)),
                        "config_agrees": bool(row.get("config_agrees", False)),
                        "verdict": (
                            str(row["verdict"]).upper()[:40]
                            if row.get("verdict") is not None
                            else None
                        ),
                        "verdict_age_days": (
                            row.get("verdict_age_days")
                            if isinstance(row.get("verdict_age_days"), (int, float))
                            else None
                        ),
                    }
                )
        base["symbols"] = rows
        summary = body.get("summary")
        if isinstance(summary, dict):
            base["summary"] = {
                key: summary[key]
                for key in ("total", "tradeable", "enabled", "disagreements")
                if isinstance(summary.get(key), int)
            }
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
    return completed.stdout.strip()


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_snapshot(engine_url: str, timeout: float) -> dict[str, Any]:
    engine_url = _validate_engine_url(engine_url)
    key = _api_key()
    api: dict[str, Any] = {}
    for name, (path, kind) in ENDPOINTS.items():
        api[name] = _safe_endpoint_result(_get_json(engine_url, path, key, timeout), kind)

    status = _git("status", "--porcelain")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    return {
        "artifact": "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT",
        "schema_version": 1,
        "captured_at_utc": now,
        "read_only_runtime_probe": True,
        "secrets_included": False,
        "api_key_available_for_probe": bool(key),
        "repository": {
            "head": _git("rev-parse", "HEAD"),
            "branch": _git("branch", "--show-current"),
            "status_porcelain_count": None if status is None else len(status.splitlines()),
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
            "note": (
                "Review before sharing. Raw secret strings and broker account identifiers "
                "are omitted."
            ),
            "a01_can_close_from_this_artifact_alone": False,
            "reason": "A-01 requires interpretation and contradiction disposition.",
        },
    }


def _write_snapshot(path: Path, snapshot: dict[str, Any], *, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    if not force:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
        return
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture a read-only, redacted JARVIS A-01 snapshot."
    )
    parser.add_argument("--engine-url", default=DEFAULT_ENGINE_URL)
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-endpoint timeout in seconds; defaults above the engine's 3s IB health budget.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing output artifact atomically.",
    )
    args = parser.parse_args(argv)

    try:
        snapshot = build_snapshot(args.engine_url, max(args.timeout, 0.1))
        output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
        _write_snapshot(output, snapshot, force=args.force)
    except (FileExistsError, ValueError) as exc:
        parser.error(str(exc))

    print(f"A-01 runtime truth snapshot written to: {output}")
    print(f"Engine reachable: {snapshot['api']['health']['reachable']}")
    print(f"Config probe reachable: {snapshot['api']['config_overview']['reachable']}")
    print(f"IB paper port 4002 open: {snapshot['ports']['ib_paper_4002_open']}")
    print("No API key or broker account ID was written to the artifact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
