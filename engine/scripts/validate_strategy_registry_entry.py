#!/usr/bin/env python
"""Validate a JARVIS strategy registry entry without third-party dependencies.

This intentionally implements the subset of JSON Schema discipline JARVIS needs for
research-gate checks, so it can run in lightweight CI and from local scripts even
when optional schema libraries are unavailable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_TOP_LEVEL = {
    "strategy_id",
    "hypothesis",
    "status",
    "owner",
    "created_at",
    "instruments",
    "timeframes",
    "data_contract",
    "research_lineage",
    "backtest",
    "robustness",
    "risk_envelope",
    "promotion_gate",
}
ALLOWED_STATUS = {
    "idea",
    "research",
    "backtest",
    "walk_forward",
    "paper_shadow",
    "paper_candidate",
    "production_candidate",
    "approved",
    "halted",
    "rejected",
}
ALLOWED_VERDICTS = {"not_started", "blocked", "fail", "pass", "approved"}
STRATEGY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,80}$")
TIMEFRAME_RE = re.compile(r"^[0-9]+[mhdw]$")
INSTRUMENT_RE = re.compile(r"^[A-Z0-9._/-]{1,12}$")


def _require_mapping(value: Any, path: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected object")
        return {}
    return value


def _require_non_empty_list(value: Any, path: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list) or not value:
        errors.append(f"{path}: expected non-empty array")
        return []
    return value


def validate_entry(entry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_TOP_LEVEL - set(entry))
    if missing:
        errors.append(f"missing required top-level fields: {', '.join(missing)}")

    strategy_id = entry.get("strategy_id")
    if not isinstance(strategy_id, str) or not STRATEGY_ID_RE.fullmatch(strategy_id):
        errors.append("strategy_id: expected lowercase slug matching ^[a-z0-9][a-z0-9_-]{2,80}$")

    hypothesis = entry.get("hypothesis")
    if not isinstance(hypothesis, str) or len(hypothesis.strip()) < 20:
        errors.append("hypothesis: expected at least 20 meaningful characters")

    status = entry.get("status")
    if status not in ALLOWED_STATUS:
        errors.append(f"status: expected one of {sorted(ALLOWED_STATUS)}")

    for item in _require_non_empty_list(entry.get("instruments"), "instruments", errors):
        if not isinstance(item, str) or not INSTRUMENT_RE.fullmatch(item):
            errors.append(f"instruments: invalid symbol {item!r}")

    for item in _require_non_empty_list(entry.get("timeframes"), "timeframes", errors):
        if not isinstance(item, str) or not TIMEFRAME_RE.fullmatch(item):
            errors.append(f"timeframes: invalid timeframe {item!r}")

    data_contract = _require_mapping(entry.get("data_contract"), "data_contract", errors)
    _require_non_empty_list(data_contract.get("sources"), "data_contract.sources", errors)
    _require_non_empty_list(data_contract.get("leakage_controls"), "data_contract.leakage_controls", errors)

    backtest = _require_mapping(entry.get("backtest"), "backtest", errors)
    metrics = _require_mapping(backtest.get("metrics"), "backtest.metrics", errors)
    for metric in ("profit_factor", "max_drawdown_pct", "trade_count"):
        if metric not in metrics:
            errors.append(f"backtest.metrics.{metric}: required")
    if "trade_count" in metrics and (not isinstance(metrics["trade_count"], int) or metrics["trade_count"] < 0):
        errors.append("backtest.metrics.trade_count: expected non-negative integer")

    risk = _require_mapping(entry.get("risk_envelope"), "risk_envelope", errors)
    _require_non_empty_list(risk.get("kill_switch_dependencies"), "risk_envelope.kill_switch_dependencies", errors)

    gate = _require_mapping(entry.get("promotion_gate"), "promotion_gate", errors)
    verdict = gate.get("current_verdict")
    if verdict not in ALLOWED_VERDICTS:
        errors.append(f"promotion_gate.current_verdict: expected one of {sorted(ALLOWED_VERDICTS)}")
    _require_non_empty_list(gate.get("required_evidence"), "promotion_gate.required_evidence", errors)
    if gate.get("human_approval_required") is not True:
        errors.append("promotion_gate.human_approval_required: must be true before any production promotion")

    if status in {"production_candidate", "approved"} and verdict not in {"pass", "approved"}:
        errors.append("promotion_gate: production_candidate/approved strategies require pass or approved verdict")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entry", type=Path, help="Path to strategy registry entry JSON")
    args = parser.parse_args(argv)
    try:
        entry = json.loads(args.entry.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"invalid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(entry, dict):
        print("entry root must be a JSON object", file=sys.stderr)
        return 2
    errors = validate_entry(entry)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"valid strategy registry entry: {entry['strategy_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
