#!/usr/bin/env python3
"""Collect and evaluate evidence for a 24-hour unattended JARVIS paper soak.

No trading actions are performed. The probe reads health, TCP liveness, the
Mission Control page, and persisted Hermes cron state. Secrets are never stored.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_ENV = REPO_ROOT / "engine" / ".env"
CRON_JOBS = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "hermes/cron/jobs.json"
STATE_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "hermes/cache/jarvis_unattended_soak"
CONFIG_PATH = STATE_ROOT / "config.json"
DEFAULT_OUTPUT_ROOT = Path.home() / "Desktop"

CRITICAL_JOBS = {
    "uptime": "1943208fc3fe",
    "dashboard": "cbfe76234cc8",
    "pm2": "f1ec41c7a4ec",
    "bar_freshness": "6ffe17ed55fc",
    "premarket": "088cb95bc145",
    "premarket_t5": "fcc8e89834b4",
    "engine_fidelity": "24110fa295bd",
    "dashboard_build": "425318a64a33",
    "brief_score": "d6d2d249d8f3",
    "brief_deadman": "773907cc76bb",
    "brief_publish": "979290f06e7b",
    "brief_freshness": "f18094d484a5",
    "position_watchdog": "6e9ea1827214",
    "alert_bridge": "acac0c39aa64",
    "backup": "9eb7f33570bd",
    "cron_freshness": "f4ce8c394417",
}

HEALTH_FIELDS = (
    "status",
    "live_trading",
    "kill_switch_active",
    "ibgateway_alive",
    "execution_connected_verified",
    "ib_execution_stale",
    "ibkr_data_connected",
    "market_data_fresh",
    "tos_rtd_connected",
    "uptime_seconds",
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def read_api_key() -> str:
    for line in ENGINE_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def request(url: str, *, api_key: str = "", timeout: float = 8.0) -> tuple[int | None, bytes, str | None]:
    req = urllib.request.Request(url)
    if api_key:
        req.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - fixed local URLs
            return response.status, response.read(), None
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, b"", f"{type(exc).__name__}: {exc}"


def port_open(port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def cron_job_health(job: dict[str, Any] | None) -> dict[str, Any]:
    if job is None:
        return {"present": False, "healthy": False, "reasons": ["missing"]}
    reasons: list[str] = []
    if not job.get("enabled") or job.get("state") != "scheduled":
        reasons.append("disabled_or_not_scheduled")
    if job.get("last_status") == "error":
        reasons.append("last_status_error")
    if job.get("last_error"):
        reasons.append("last_error_present")
    if job.get("last_delivery_error"):
        reasons.append("delivery_error_present")
    return {
        "present": True,
        "healthy": not reasons,
        "reasons": reasons,
        "id": job.get("id"),
        "name": job.get("name"),
        "enabled": job.get("enabled"),
        "state": job.get("state"),
        "schedule": job.get("schedule_display"),
        "last_run_at": job.get("last_run_at"),
        "last_status": job.get("last_status"),
        "last_error": job.get("last_error"),
        "last_delivery_error": job.get("last_delivery_error"),
        "failure_streak": job.get("failure_streak"),
    }


def load_cron_jobs() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(CRON_JOBS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(job.get("id")): job for job in payload.get("jobs", [])}


def collect_sample() -> dict[str, Any]:
    api_key = read_api_key()
    health_status, health_body, health_error = request(
        "http://127.0.0.1:8010/health", api_key=api_key
    )
    health: dict[str, Any] = {}
    if health_body:
        try:
            decoded = json.loads(health_body)
            health = {field: decoded.get(field) for field in HEALTH_FIELDS}
        except json.JSONDecodeError:
            health_error = "health_bad_json"

    dashboard_status, dashboard_body, dashboard_error = request(
        "http://127.0.0.1:3010/mission-control"
    )
    cron_jobs = load_cron_jobs()
    cron = {
        category: cron_job_health(cron_jobs.get(job_id))
        for category, job_id in CRITICAL_JOBS.items()
    }
    ports = {str(port): port_open(port) for port in (3010, 4001, 4002, 8010)}
    checks = {
        "engine_http": health_status == 200 and health_error is None,
        "dashboard_http": dashboard_status == 200 and dashboard_error is None,
        "dashboard_body": b"MISSION CONTROL" in dashboard_body.upper(),
        "paper_mode": health.get("live_trading") is False,
        "paper_gateway": ports["4002"] and health.get("ibgateway_alive") is True,
        "live_gateway_closed": not ports["4001"],
        "execution_verified": health.get("execution_connected_verified") is True,
        "execution_not_stale": health.get("ib_execution_stale") is False,
        "data_connected": health.get("ibkr_data_connected") is True,
    }
    return {
        "timestamp": now_utc().isoformat(),
        "checks": checks,
        "health": health,
        "health_http_status": health_status,
        "health_error": health_error,
        "dashboard_http_status": dashboard_status,
        "dashboard_error": dashboard_error,
        "ports": ports,
        "cron": cron,
    }


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def command_start(output_dir: str | None) -> int:
    start = now_utc()
    run_id = start.strftime("%Y%m%dT%H%M%SZ")
    target = Path(output_dir) if output_dir else DEFAULT_OUTPUT_ROOT / f"JARVIS-unattended-readiness-{run_id}"
    config = {
        "run_id": run_id,
        "start_at": start.isoformat(),
        "expected_end_at": (start + timedelta(hours=24)).isoformat(),
        "output_dir": str(target.resolve()),
        "sample_interval_minutes": 15,
        "expected_samples": 97,
    }
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(CONFIG_PATH, config)
    write_json(target / "soak-config.json", config)
    print(json.dumps(config, indent=2))
    return command_sample()


def command_sample() -> int:
    config = load_config()
    output_dir = Path(config["output_dir"])
    sample = collect_sample()
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "samples.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sample, sort_keys=True) + "\n")
    write_json(output_dir / "latest.json", sample)
    print(
        f"soak-sample timestamp={sample['timestamp']} "
        f"checks={sum(sample['checks'].values())}/{len(sample['checks'])}"
    )
    return 0 if all(sample["checks"].values()) else 1


def command_evaluate() -> int:
    config = load_config()
    output_dir = Path(config["output_dir"])
    sample_path = output_dir / "samples.jsonl"
    samples = [json.loads(line) for line in sample_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    start = parse_dt(config["start_at"])
    expected_end = parse_dt(config["expected_end_at"])
    timestamps = [parse_dt(sample.get("timestamp")) for sample in samples]
    timestamps = [stamp for stamp in timestamps if stamp is not None]
    elapsed_hours = 0.0
    if timestamps:
        elapsed_hours = (max(timestamps) - min(timestamps)).total_seconds() / 3600.0

    failed_samples = [
        {"timestamp": sample["timestamp"], "failed": [k for k, passed in sample["checks"].items() if not passed]}
        for sample in samples
        if not all(sample["checks"].values())
    ]
    latest = samples[-1] if samples else {}
    category_runs: dict[str, bool] = {}
    for category in CRITICAL_JOBS:
        state = (latest.get("cron") or {}).get(category) or {}
        last_run = parse_dt(state.get("last_run_at"))
        category_runs[category] = bool(last_run and start and last_run >= start)

    soak_complete = bool(expected_end and now_utc() >= expected_end and elapsed_hours >= 23.0)
    criteria = {
        "soak_complete": soak_complete,
        "sample_count_at_least_90": len(samples) >= 90,
        "elapsed_at_least_23h": elapsed_hours >= 23.0,
        "no_failed_service_samples": not failed_samples,
        "paper_mode_never_violated": all(s.get("checks", {}).get("paper_mode") is True for s in samples),
        "live_gateway_never_open": all(s.get("checks", {}).get("live_gateway_closed") is True for s in samples),
        "all_expected_cron_categories_ran": all(category_runs.values()),
        "latest_cron_states_healthy": all(
            state.get("healthy") is True for state in (latest.get("cron") or {}).values()
        ),
    }
    ready = all(criteria.values())
    result = {
        "evaluated_at": now_utc().isoformat(),
        "verdict": "READY FOR AN UNATTENDED PAPER-TRADING DAY" if ready else "NOT READY",
        "criteria": criteria,
        "sample_count": len(samples),
        "elapsed_hours": round(elapsed_hours, 3),
        "failed_samples": failed_samples,
        "cron_category_ran_since_start": category_runs,
        "remaining_single_points_of_failure": [
            "IBKR can require human 2FA after session expiry or Gateway restart.",
            "Windows host power/network loss has no independent failover host.",
        ],
    }
    write_json(output_dir / "final-verdict.json", result)
    lines = [
        "# JARVIS unattended paper-trading soak verdict",
        "",
        f"**{result['verdict']}**",
        "",
        f"- Evaluated: `{result['evaluated_at']}`",
        f"- Samples: `{result['sample_count']}`",
        f"- Observed span: `{result['elapsed_hours']:.3f} hours`",
        "",
        "## Criteria",
        "",
    ]
    lines.extend(f"- {'PASS' if passed else 'FAIL'} — `{name}`" for name, passed in criteria.items())
    lines.extend(["", "## Remaining single points of failure", ""])
    lines.extend(f"- {item}" for item in result["remaining_single_points_of_failure"])
    (output_dir / "final-verdict.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result["verdict"])
    return 0 if ready else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--output-dir")
    sub.add_parser("sample")
    sub.add_parser("evaluate")
    args = parser.parse_args()
    if args.command == "start":
        return command_start(args.output_dir)
    if args.command == "sample":
        return command_sample()
    return command_evaluate()


if __name__ == "__main__":
    raise SystemExit(main())
