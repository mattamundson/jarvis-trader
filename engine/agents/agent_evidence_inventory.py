"""Read-only inventory of JARVIS decision clocks; never evaluates a trading edge.

No broker, API, runtime configuration or credential access. The SQLite connection
uses mode=ro and query_only, and only reads decision metadata plus pipeline JSON.
It does not infer an offset for legacy naive timestamps or attest market inputs.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

_SYMBOLS = ("MES", "SPY", "QQQ", "VIX")


def _clock(value: Any, label: str) -> datetime:
    """Mirror the comparison adapter's strict timezone rule without engine imports."""
    try:
        ts = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} missing or not an ISO timestamp") from exc
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"{label} must have timezone")
    return ts


def _clock_reason(row: sqlite3.Row) -> str:
    try:
        decision_at = _clock(row["timestamp"], "decision.timestamp")
    except ValueError as exc:
        return str(exc)
    try:
        pipeline: Any = json.loads(row["full_pipeline_json"])
    except (ValueError, TypeError):
        return "missing_or_invalid_pipeline_json"
    if not isinstance(pipeline, dict):
        return "missing_or_invalid_pipeline_json"
    debate = pipeline.get("debate_result")
    if not isinstance(debate, dict):
        return "missing_debate_result"
    for role in ("bull", "bear"):
        report = debate.get(f"{role}_report")
        if not isinstance(report, dict):
            return f"missing_{role}_report"
        try:
            report_at = _clock(report.get("timestamp"), f"{role}_report.timestamp")
        except ValueError as exc:
            return str(exc)
        if report_at > decision_at:
            return "report_after_decision"
    try:
        debate_at = _clock(debate.get("timestamp"), "debate.timestamp")
    except ValueError as exc:
        return str(exc)
    if debate_at > decision_at:
        return "debate_after_decision"
    return "clocks_structurally_ready_not_certified"


def _nested_clock_counts(row: sqlite3.Row, counts: Counter[str]) -> None:
    """Count independent nested blockers even when the decision clock is naive."""
    try:
        pipeline: Any = json.loads(row["full_pipeline_json"])
    except (ValueError, TypeError):
        return
    if not isinstance(pipeline, dict):
        return
    counts["pipeline_dict"] += 1
    debate = pipeline.get("debate_result")
    if not isinstance(debate, dict):
        return
    counts["debate_dict"] += 1
    for role in ("bull", "bear"):
        report = debate.get(f"{role}_report")
        if isinstance(report, dict):
            counts[f"{role}_report_dict"] += 1
            try:
                _clock(report.get("timestamp"), f"{role}_report.timestamp")
            except ValueError:
                pass
            else:
                counts[f"{role}_report_aware"] += 1
    try:
        _clock(debate.get("timestamp"), "debate.timestamp")
    except ValueError:
        pass
    else:
        counts["debate_aware"] += 1


def inventory(db_path: Path) -> dict[str, Any]:
    """Count every in-scope row once, reporting the first clock blocker only.

    A clock-ready row is NOT comparison-eligible: baseline, input availability,
    outcome vintages, costs and human/risk-veto attribution remain unverified.
    """
    if not db_path.is_file():
        raise ValueError("database file not found")
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        columns = {r[1] for r in connection.execute("PRAGMA table_info(decisions)")}
        if not {"id", "symbol", "timestamp", "full_pipeline_json"} <= columns:
            raise ValueError("decisions table with pipeline JSON not found")
        total = connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        scoped = connection.execute(
            "SELECT COUNT(*) FROM decisions WHERE symbol IN (?, ?, ?, ?)", _SYMBOLS
        ).fetchone()[0]
        reasons: Counter[str] = Counter()
        nested: Counter[str] = Counter()
        for row in connection.execute(
            "SELECT id, timestamp, full_pipeline_json FROM decisions "
            "WHERE symbol IN (?, ?, ?, ?) ORDER BY id", _SYMBOLS
        ):
            reasons[_clock_reason(row)] += 1
            _nested_clock_counts(row, nested)
    assert sum(reasons.values()) == scoped
    return {
        "status": "CLOCK_INVENTORY_ONLY_NOT_CERTIFIED",
        "total_decisions_all_symbols": total,
        "scoped_decisions": scoped,
        "symbols_in_scope": list(_SYMBOLS),
        "first_blocker_counts": dict(sorted(reasons.items())),
        "independent_nested_counts": {
            key: nested[key] for key in (
                "pipeline_dict", "debate_dict", "bull_report_dict", "bear_report_dict",
                "bull_report_aware", "bear_report_aware", "debate_aware",
            )
        },
        "comparison_eligible_certified": 0,
        "limitations": [
            "No input-vintage, independent baseline, or forward-outcome attestation read",
            "One first blocker per row; later blockers may also exist",
            "Clock readiness is necessary, never sufficient, for an evaluation",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="SQLite decisions database (read-only)")
    args = parser.parse_args(argv)
    try:
        result = inventory(args.db)
    except (ValueError, sqlite3.Error) as exc:
        print(json.dumps({"status": "NOT_EVALUATED", "error": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
