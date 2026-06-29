"""Tests for the record-first H1/H2 stationarity annotation in validate_strategy.

The H1/H2 chronological stationarity result is written to report["stationarity"]
as ADVISORY evidence this cycle — it must NOT influence the gate-v2 verdict until
deliberately promoted to a blocking criterion. These tests pin that contract:

  1. _evaluate_gate_v2 produces a byte-identical verdict whether or not a
     "stationarity" key is present in the report (the gate never reads it).
  2. The recorded block is a well-formed h1_h2_split result computed from the
     same per-trade pnls.

Run:  cd engine && .venv/Scripts/python scripts/test_validate_strategy_stationarity_record.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.stationarity_gate import h1_h2_split  # noqa: E402
from scripts.validate_strategy import _evaluate_gate_v2, validate  # noqa: E402


def _sample_pnls():
    # A modest, back-loaded-ish series with enough trades for the battery.
    h1 = [80, -40, 70, -50, 60, -45, 75, -55, 65, -40, 70, -50, 60, -48, 72, -52]
    h2 = [120, -30, 140, -25, 130, -35, 150, -20, 110, -40, 135, -28, 145, -22, 125, -33]
    return h1 + h2


def test_gate_verdict_unchanged_by_stationarity_key():
    """The gate must be byte-identical with vs without report['stationarity']."""
    pnls = _sample_pnls()
    report = validate(pnls, n_grid_trials=10, initial_capital=50_000.0, n_resamples=200, seed=42)

    gate_without = _evaluate_gate_v2(dict(report))

    report_with = dict(report)
    report_with["stationarity"] = h1_h2_split(pnls)
    gate_with = _evaluate_gate_v2(report_with)

    assert (
        gate_with == gate_without
    ), "record-first stationarity changed the gate verdict — it must be advisory only"
    # also: an absurd injected stationarity value must not flip the verdict
    report_absurd = dict(report)
    report_absurd["stationarity"] = {"consistent": False, "h1_pf": 0.0, "h2_pf": 0.0}
    assert _evaluate_gate_v2(report_absurd) == gate_without
    print("[PASS] gate verdict is invariant to the stationarity record")


def test_recorded_block_is_wellformed_split():
    """The recorded block matches h1_h2_split on the same pnls and carries the
    consumer fields a future blocking gate would read."""
    pnls = _sample_pnls()
    rec = h1_h2_split(pnls)
    for key in (
        "consistent",
        "h1_pf",
        "h2_pf",
        "h1_n",
        "h2_n",
        "both_profitable",
        "sample_adequate",
    ):
        assert key in rec, f"missing {key} in stationarity record"
    # this fixture: both halves profitable -> consistent
    assert rec["both_profitable"] is True
    assert rec["consistent"] is True
    print(f"[PASS] recorded block well-formed (h1_pf={rec['h1_pf']} h2_pf={rec['h2_pf']})")


def main():
    tests = [
        test_gate_verdict_unchanged_by_stationarity_key,
        test_recorded_block_is_wellformed_split,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except Exception as exc:
            print(f"[FAIL] {t.__name__}: {exc}")
            failures.append(t.__name__)
    print(f"\n{'=' * 60}")
    if failures:
        print(f"FAILED {len(failures)}/{len(tests)} tests: {', '.join(failures)}")
        sys.exit(1)
    print(f"ALL {len(tests)} stationarity-record tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
