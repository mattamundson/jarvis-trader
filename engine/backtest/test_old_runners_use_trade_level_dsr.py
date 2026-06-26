"""Regression test: the two legacy MGC runners must compute DSR from real
per-trade returns (trade_level_dsr), NOT the mean-of-window-Sharpes hack.

D1 Part B. `run_mgc_trend_rv_filter_rank1._compute_gate_v2` and
`study_wfo_runner._compute_gate_v2` historically fed the Bailey/Lopez de Prado
deflation the arithmetic MEAN of per-window Sharpes (a 1-2 trade window yields a
Sharpe of 80+), with n_obs floored at 30 and Gaussian skew/kurt -> Phi(z) that
rounds to 1.0 and auto-passes both gate floors. The centralised, tested
`_gate_v2_trade_metrics.trade_level_dsr` computes the honest DSR from the actual
concatenated per-trade return series. These runners must use it.

The contract asserted here: _compute_gate_v2(...)["dsr"] == trade_level_dsr(
oos_results, n_grid, CAPITAL) -- i.e. the runner is wired to the correct path.
The fixture's huge per-window Sharpes would drive the OLD path to ~1.0, so a
pass also proves the mean-of-window-Sharpes artifact is gone.

Run:  cd engine && .venv/Scripts/python backtest/test_old_runners_use_trade_level_dsr.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from backtest._gate_v2_trade_metrics import trade_level_dsr


class _FakeTrade:
    __slots__ = ("pnl",)

    def __init__(self, pnl: float):
        self.pnl = float(pnl)


class _FakeResult:
    """Minimal stand-in for a BacktestResult used by _compute_gate_v2."""

    def __init__(self, pnls, profit_factor, max_drawdown_pct, sharpe_ratio):
        self.trades = [_FakeTrade(p) for p in pnls]
        self.total_trades = len(pnls)
        self.profit_factor = float(profit_factor)
        self.max_drawdown_pct = float(max_drawdown_pct)
        # Deliberately HUGE per-window Sharpe: this is what the old mean-of-window
        # path would deflate to ~1.0. The honest trade-level DSR ignores it.
        self.sharpe_ratio = float(sharpe_ratio)


def _fixture():
    """Two OOS windows with near-zero-mean per-trade PnLs (low REAL Sharpe) but
    giant per-window Sharpes. The old mean-of-window-Sharpes path deflates the
    82.3/15.4 to ~1.0; the honest per-trade DSR sees a coin-flip edge -> well
    below the gate floor. The gap is the whole point of the migration."""
    w1 = _FakeResult(
        pnls=[50.0, -45.0, 55.0, -50.0, 48.0, -47.0],
        profit_factor=1.05,
        max_drawdown_pct=0.012,
        sharpe_ratio=82.3,
    )
    w2 = _FakeResult(
        pnls=[40.0, -38.0, 42.0, -41.0, 39.0, -37.0],
        profit_factor=1.04,
        max_drawdown_pct=0.009,
        sharpe_ratio=15.4,
    )
    return [w1, w2]


_FIXED = {"fixed_params_min_pf": 1.5, "fixed_params_mean_pf": 1.7, "fixed_params_max_pf": 2.0}
_COST = {"cost_survives_through": "realistic", "tier_results": {}}


def test_rv_filter_runner_uses_trade_level_dsr():
    from backtest import run_mgc_trend_rv_filter_rank1 as rv

    oos = _fixture()
    n_grid = 3
    expected = trade_level_dsr(oos, n_grid_combos=n_grid, initial_capital=rv.CAPITAL)
    gate = rv._compute_gate_v2(oos, n_grid, _FIXED, _COST)
    assert abs(gate["dsr"] - round(expected, 6)) < 1e-6, (
        f"rv_filter _compute_gate_v2 dsr={gate['dsr']} != trade_level_dsr={expected}. "
        "Runner is still on the mean-of-window-Sharpes path."
    )
    assert (
        gate["dsr"] < 0.95
    ), f"honest trade-level DSR should not auto-pass at ~1.0 here, got {gate['dsr']}"
    print(f"[PASS] rv_filter uses trade_level_dsr: dsr={gate['dsr']} (was ~1.0).")


def test_study_wfo_runner_uses_trade_level_dsr():
    from backtest import study_wfo_runner as sw

    oos = _fixture()
    n_grid = 2
    expected = trade_level_dsr(oos, n_grid_combos=n_grid, initial_capital=sw.CAPITAL)
    gate = sw._compute_gate_v2(oos, n_grid, _FIXED, _COST)
    assert abs(gate["dsr"] - round(expected, 6)) < 1e-6, (
        f"study_wfo_runner _compute_gate_v2 dsr={gate['dsr']} != trade_level_dsr={expected}. "
        "Runner is still on the mean-of-window-Sharpes path."
    )
    assert (
        gate["dsr"] < 0.95
    ), f"honest trade-level DSR should not auto-pass at ~1.0 here, got {gate['dsr']}"
    print(f"[PASS] study_wfo_runner uses trade_level_dsr: dsr={gate['dsr']} (was ~1.0).")


def main():
    tests = [
        test_rv_filter_runner_uses_trade_level_dsr,
        test_study_wfo_runner_uses_trade_level_dsr,
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
    print(f"ALL {len(tests)} legacy-runner trade-level-DSR tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
