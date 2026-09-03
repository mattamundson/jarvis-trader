#!/usr/bin/env python3
"""Assess a redacted A-01 runtime snapshot without granting authorization.

This script is intentionally read-only. It validates the snapshot envelope, checks
whether the required observation surfaces are present and fresh, and highlights
safety-relevant contradictions for an operator to disposition. It can never close
A-01, authorize trading, or mutate runtime state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

ARTIFACT = "JARVIS_A01_RUNTIME_TRUTH_SNAPSHOT"
SCHEMA_VERSION = 1
DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[1] / "phase0_runtime_truth_snapshot.json"
REQUIRED_ENDPOINTS = (
    "config_overview",
    "health",
    "health_full",
    "safety_status",
    "eligibility",
    "backup_status",
)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _safe_config(snapshot: dict[str, Any]) -> dict[str, Any]:
    api = snapshot.get("api")
    if not isinstance(api, dict):
        return {}
    row = api.get("config_overview")
    if not isinstance(row, dict):
        return {}
    config = row.get("safe_config")
    return config if isinstance(config, dict) else {}


def _endpoint(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    api = snapshot.get("api")
    if not isinstance(api, dict):
        return {}
    value = api.get(name)
    return value if isinstance(value, dict) else {}


def _health_value(snapshot: dict[str, Any], endpoint: str, key: str) -> Any:
    safe = _endpoint(snapshot, endpoint).get("safe_health")
    if not isinstance(safe, dict):
        return None
    if key in safe:
        return safe[key]
    subsystems = safe.get("subsystems")
    if isinstance(subsystems, dict):
        for value in subsystems.values():
            if isinstance(value, dict) and key in value:
                return value[key]
    return None


def _add(findings: list[dict[str, str]], severity: str, code: str, message: str) -> None:
    findings.append({"severity": severity, "code": code, "message": message})


def assess_snapshot(
    snapshot: dict[str, Any],
    *,
    now: dt.datetime | None = None,
    max_age_minutes: int = 15,
) -> dict[str, Any]:
    """Return a deterministic, non-authorizing assessment."""
    findings: list[dict[str, str]] = []
    now = (now or _utc_now()).astimezone(dt.timezone.utc)

    if snapshot.get("artifact") != ARTIFACT:
        _add(findings, "BLOCKER", "INVALID_ARTIFACT", "Unexpected artifact marker.")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        _add(findings, "BLOCKER", "INVALID_SCHEMA", "Unsupported snapshot schema version.")
    if snapshot.get("read_only_runtime_probe") is not True:
        _add(findings, "BLOCKER", "PROBE_NOT_READ_ONLY", "Snapshot does not assert read-only collection.")
    if snapshot.get("secrets_included") is not False:
        _add(findings, "BLOCKER", "SECRET_BOUNDARY_UNKNOWN", "Snapshot does not assert secrets_included=false.")

    captured = _parse_timestamp(snapshot.get("captured_at_utc"))
    age_seconds: float | None = None
    if captured is None:
        _add(findings, "BLOCKER", "INVALID_TIMESTAMP", "captured_at_utc is missing or invalid.")
    else:
        age_seconds = max(0.0, (now - captured).total_seconds())
        if captured > now + dt.timedelta(minutes=2):
            _add(findings, "BLOCKER", "CLOCK_SKEW", "Snapshot timestamp is materially in the future.")
        elif age_seconds > max_age_minutes * 60:
            _add(
                findings,
                "BLOCKER",
                "STALE_SNAPSHOT",
                f"Snapshot age exceeds {max_age_minutes} minutes.",
            )

    for name in REQUIRED_ENDPOINTS:
        row = _endpoint(snapshot, name)
        if not row:
            _add(findings, "BLOCKER", "ENDPOINT_MISSING", f"Required observation {name} is absent.")
        elif row.get("reachable") is not True:
            _add(findings, "BLOCKER", "ENDPOINT_UNREACHABLE", f"Required observation {name} is unreachable.")

    repository = snapshot.get("repository")
    if not isinstance(repository, dict) or not repository.get("head"):
        _add(findings, "BLOCKER", "REPO_HEAD_UNKNOWN", "Running repository HEAD was not observed.")
    elif repository.get("status_porcelain_count") not in (0, None):
        _add(
            findings,
            "WARN",
            "DIRTY_WORKTREE",
            f"Runtime repository reports {repository.get('status_porcelain_count')} uncommitted path(s).",
        )

    ports = snapshot.get("ports") if isinstance(snapshot.get("ports"), dict) else {}
    if ports.get("ib_live_4001_open") is True:
        _add(findings, "WARN", "IB_LIVE_PORT_OPEN", "IB live port 4001 is reachable and requires operator disposition.")
    if ports.get("ib_live_4001_open") is True and ports.get("ib_paper_4002_open") is True:
        _add(findings, "WARN", "BOTH_IB_PORTS_OPEN", "Both IB live and paper ports are reachable.")

    config = _safe_config(snapshot)
    if not config:
        _add(findings, "BLOCKER", "CONFIG_UNOBSERVED", "Safe runtime config values were not observed.")
    else:
        if config.get("LIVE_TRADING_ENABLED") is True:
            _add(findings, "BLOCKER", "LIVE_ENABLED", "Loaded config reports LIVE_TRADING_ENABLED=true.")
        if config.get("PAPER_TRADING") is not True:
            _add(findings, "BLOCKER", "PAPER_DISABLED", "Loaded config does not report PAPER_TRADING=true.")
        if config.get("IBKR_PAPER_MODE") is False:
            _add(findings, "BLOCKER", "IBKR_NOT_PAPER", "Loaded config reports IBKR_PAPER_MODE=false.")
        if config.get("IBKR_PORT") == 4001:
            _add(findings, "BLOCKER", "IBKR_LIVE_PORT_CONFIGURED", "Loaded config points IBKR_PORT at 4001.")

    for endpoint in ("health", "health_full"):
        if _health_value(snapshot, endpoint, "live_trading") is True:
            _add(findings, "BLOCKER", "HEALTH_LIVE_MODE", f"{endpoint} reports live_trading=true.")

    kill_switch = _health_value(snapshot, "safety_status", "kill_switch_active")
    hard_halt = _health_value(snapshot, "safety_status", "hard_halt")
    halted = _health_value(snapshot, "safety_status", "halted")
    if kill_switch is True or hard_halt is True or halted is True:
        _add(findings, "BLOCKER", "SAFETY_HALTED", "Safety state currently blocks exposure-increasing execution.")

    verified = _health_value(snapshot, "safety_status", "safety_state_verified")
    state = _health_value(snapshot, "safety_status", "safety_state")
    if verified is False or str(state).lower() == "state_unknown":
        _add(findings, "BLOCKER", "SAFETY_STATE_UNKNOWN", "Persisted safety state is not verified.")

    eligibility = _endpoint(snapshot, "eligibility")
    summary = eligibility.get("summary") if isinstance(eligibility.get("summary"), dict) else {}
    if isinstance(summary, dict) and summary.get("disagreements", 0) not in (0, None):
        _add(findings, "BLOCKER", "ELIGIBILITY_DISAGREEMENT", "Eligibility summary reports config/verdict disagreement.")

    blocker_count = sum(item["severity"] == "BLOCKER" for item in findings)
    warning_count = sum(item["severity"] == "WARN" for item in findings)
    status = "BLOCKED" if blocker_count else "READY_FOR_OPERATOR_REVIEW"

    return {
        "assessment": "JARVIS_A01_RUNTIME_SNAPSHOT_ASSESSMENT",
        "schema_version": 1,
        "status": status,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "snapshot_age_seconds": age_seconds,
        "findings": findings,
        "authorization": {
            "a01_auto_close_allowed": False,
            "trading_authorized": False,
            "operator_disposition_required": True,
            "note": "This assessment is evidence triage only; it grants no PAPER or LIVE authority.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess a redacted JARVIS A-01 runtime snapshot.")
    parser.add_argument("snapshot", type=Path, nargs="?", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--max-age-minutes", type=int, default=15)
    parser.add_argument("--json", action="store_true", help="Emit the assessment as JSON.")
    args = parser.parse_args(argv)
    if args.max_age_minutes < 1 or args.max_age_minutes > 1440:
        parser.error("--max-age-minutes must be between 1 and 1440")

    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read snapshot: {exc}")
    if not isinstance(snapshot, dict):
        parser.error("snapshot root must be a JSON object")

    assessment = assess_snapshot(snapshot, max_age_minutes=args.max_age_minutes)
    if args.json:
        print(json.dumps(assessment, indent=2, sort_keys=True))
    else:
        print(f"A-01 assessment: {assessment['status']}")
        print(f"Blockers: {assessment['blocker_count']}  Warnings: {assessment['warning_count']}")
        for item in assessment["findings"]:
            print(f"[{item['severity']}] {item['code']}: {item['message']}")
        print("A-01 auto-close: NEVER. Operator disposition is required.")
    return 0 if assessment["status"] == "READY_FOR_OPERATOR_REVIEW" else 2


if __name__ == "__main__":
    sys.exit(main())
