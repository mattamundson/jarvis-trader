"""Offline JSONL runner for attested historical JARVIS decision observations.

Never queries a broker, database, exchange, remote service, or live trading
pipeline. A successful run is a descriptive study, not evidence of net alpha.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.agent_evidence_research import compare_agent_to_baseline
from agents.jarvis_decision_evidence import (
    HistoricalEvidence,
    _timestamp,
    observation_from_stored_decision,
)


def evaluate_export(document: list[dict[str, Any]], *, evaluation_at: datetime) -> dict[str, Any]:
    observations = []
    horizon: str | None = None
    for number, entry in enumerate(document, start=1):
        if not isinstance(entry, dict) or not isinstance(entry.get("decision"), dict):
            raise ValueError(f"line {number}: missing decision")
        source = entry.get("evidence")
        if not isinstance(source, dict):
            raise ValueError(f"line {number}: missing evidence")
        try:
            evidence = HistoricalEvidence(
                symbol=source["symbol"],
                input_available_at=_timestamp(source["input_available_at"], "input_available_at"),
                baseline_action=source["baseline_action"],
                baseline_available_at=_timestamp(
                    source["baseline_available_at"], "baseline_available_at"
                ),
                baseline_identity=source["baseline_identity"],
                forward_return=float(source["forward_return"]),
                outcome_available_at=_timestamp(
                    source["outcome_available_at"], "outcome_available_at"
                ),
                outcome_identity=source["outcome_identity"],
                horizon=source["horizon"],
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"line {number}: invalid evidence: {exc}") from exc
        if horizon is not None and horizon != evidence.horizon:
            raise ValueError("mixed forward horizons are not comparable")
        horizon = evidence.horizon
        observations.append(observation_from_stored_decision(entry["decision"], evidence))
    result = compare_agent_to_baseline(observations, evaluation_at=evaluation_at)
    return {
        "status": "DESCRIPTIVE_ONLY_UNVERIFIED_INPUT_ATTESTATIONS",
        "horizon": horizon,
        "comparison": asdict(result),
        "limitations": [
            "Not trade P&L or option P&L",
            "No costs, fills, slippage, or statistical significance test",
            "Input availability and outcome lineage require independent certification",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="read-only JSONL file")
    parser.add_argument("--evaluation-at", required=True, help="timezone-aware ISO timestamp")
    args = parser.parse_args(argv)
    try:
        evaluation_at = _timestamp(args.evaluation_at, "evaluation_at")
        with args.input.open(encoding="utf-8") as handle:
            entries = [json.loads(line) for line in handle if line.strip()]
        result = evaluate_export(entries, evaluation_at=evaluation_at)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "NOT_EVALUATED", "error": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
