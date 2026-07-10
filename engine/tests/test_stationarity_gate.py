"""Tests for the H1/H2 chronological stationarity gate.

The campaign's single most important lesson: a pooled moving-block bootstrap
PF-CI passes BACK-LOADED, non-stationary edges. The canonical example is the
ES-NQ spread -- pooled it looked great, but chronologically H1 PF 0.91 (loses)
and H2 PF 7.96 (100% of the profit). A pooled gate would authorize an edge that
only worked in the second half of the sample. The fix is a mandatory
first-half/second-half check: BOTH halves must be profitable (and each must hold
enough trades to mean anything).

Run:  cd engine && .venv/Scripts/python backtest/test_stationarity_gate.py
"""

from __future__ import annotations

import math
import sys

sys.path.insert(0, ".")

from backtest.stationarity_gate import h1_h2_split


def test_stationary_edge_is_consistent():
    """Both halves clearly profitable -> consistent."""
    pnls = [100, -40, 120, -50, 90, -30] + [110, -45, 130, -40, 95, -35]
    r = h1_h2_split(pnls, min_trades_per_half=5, min_pf=1.0)
    assert r["h1_pf"] > 1.0 and r["h2_pf"] > 1.0
    assert r["sample_adequate"] is True
    assert r["both_profitable"] is True
    assert r["consistent"] is True
    print(f"[PASS] stationary edge consistent: h1_pf={r['h1_pf']:.2f} h2_pf={r['h2_pf']:.2f}")


def test_backloaded_edge_is_not_consistent():
    """The ES-NQ failure mode: H1 loses, H2 carries 100% of the profit."""
    # H1: net loser (PF < 1). H2: huge winner.
    h1 = [50, -60, 40, -55, 45, -70]  # losses dominate -> PF < 1
    h2 = [300, -10, 280, -15, 350, -5]  # massive winner
    r = h1_h2_split(h1 + h2, min_trades_per_half=5, min_pf=1.0)
    assert r["h1_pf"] < 1.0, f"setup invalid: h1 should lose, got {r['h1_pf']}"
    assert r["h2_pf"] > 5.0
    assert r["both_profitable"] is False
    assert r["consistent"] is False, (
        "a back-loaded edge (H1 loses, H2 carries everything) must FAIL the "
        "stationarity gate -- this is the whole point."
    )
    print(f"[PASS] back-loaded edge rejected: h1_pf={r['h1_pf']:.2f} h2_pf={r['h2_pf']:.2f}")


def test_insufficient_trades_per_half_not_consistent():
    """Too few trades in a half -> not enough evidence -> not consistent (default-deny)."""
    pnls = [100, -40, 120, -50]  # 2 per half at mid=2
    r = h1_h2_split(pnls, min_trades_per_half=5, min_pf=1.0)
    assert r["sample_adequate"] is False
    assert r["consistent"] is False
    print(f"[PASS] sparse split default-denies: h1_n={r['h1_n']} h2_n={r['h2_n']}")


def test_all_wins_gives_inf_pf_and_consistent():
    """No losses in a half -> PF = +inf (profitable), still consistent."""
    pnls = [10, 20, 30, 40, 50, 60] + [15, 25, 35, 45, 55, 65]
    r = h1_h2_split(pnls, min_trades_per_half=5, min_pf=1.0)
    assert math.isinf(r["h1_pf"]) and math.isinf(r["h2_pf"])
    assert r["consistent"] is True
    print("[PASS] all-wins halves -> inf PF, consistent.")


def test_empty_is_not_consistent():
    """Empty / degenerate input default-denies rather than raising."""
    r = h1_h2_split([], min_trades_per_half=5, min_pf=1.0)
    assert r["consistent"] is False and r["sample_adequate"] is False
    print("[PASS] empty input default-denies.")


def test_min_pf_floor_is_configurable():
    """A stricter floor (e.g. 1.10) rejects a barely-profitable half."""
    # H1 PF ~1.05, H2 strong. Default 1.0 -> consistent; floor 1.10 -> not.
    h1 = [100, -95, 100, -95, 100, -90]  # PF ~ 300/280 = 1.07
    h2 = [200, -50, 220, -40, 240, -45]
    lenient = h1_h2_split(h1 + h2, min_trades_per_half=5, min_pf=1.0)
    strict = h1_h2_split(h1 + h2, min_trades_per_half=5, min_pf=1.10)
    assert lenient["consistent"] is True
    assert strict["consistent"] is False
    print(f"[PASS] configurable floor: h1_pf={lenient['h1_pf']:.3f} (1.0 ok, 1.10 fails).")


class _FakeTrade:
    __slots__ = ("pnl",)

    def __init__(self, pnl):
        self.pnl = float(pnl)


class _FakeResult:
    def __init__(self, pnls):
        self.trades = [_FakeTrade(p) for p in pnls]
        self.total_trades = len(pnls)


def test_trade_level_wrapper_concatenates_chronologically():
    """trade_level_stationarity flattens per-window OOS trades in sequence, then
    runs the H1/H2 split. A back-loaded set of windows must be rejected."""
    from backtest._gate_v2_trade_metrics import trade_level_stationarity

    # Window order is chronological; early windows lose, late windows carry it.
    losing = [_FakeResult([40, -60, 45, -55]), _FakeResult([50, -70, 30, -65])]
    winning = [_FakeResult([300, -10, 280, -20]), _FakeResult([350, -5, 260, -15])]
    r = trade_level_stationarity(losing + winning, min_trades_per_half=5, min_pf=1.0)
    assert r["h1_pf"] < 1.0 and r["h2_pf"] > 5.0
    assert r["consistent"] is False
    print(
        f"[PASS] wrapper rejects back-loaded windows: h1_pf={r['h1_pf']:.2f} h2_pf={r['h2_pf']:.2f}"
    )


def test_trade_level_wrapper_passes_stationary():
    from backtest._gate_v2_trade_metrics import trade_level_stationarity

    windows = [_FakeResult([100, -40, 110, -45]) for _ in range(4)]
    r = trade_level_stationarity(windows, min_trades_per_half=5, min_pf=1.0)
    assert r["consistent"] is True
    print(
        f"[PASS] wrapper passes stationary windows: h1_pf={r['h1_pf']:.2f} h2_pf={r['h2_pf']:.2f}"
    )


def main():
    tests = [
        test_stationary_edge_is_consistent,
        test_backloaded_edge_is_not_consistent,
        test_insufficient_trades_per_half_not_consistent,
        test_all_wins_gives_inf_pf_and_consistent,
        test_empty_is_not_consistent,
        test_min_pf_floor_is_configurable,
        test_trade_level_wrapper_concatenates_chronologically,
        test_trade_level_wrapper_passes_stationary,
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
    print(f"ALL {len(tests)} stationarity-gate tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
