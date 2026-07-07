"""Unit + integration tests — bootstrapped win-rate gate (Initiative 2C, shadow).

Covers:
  * monte_carlo.bootstrap_win_rate — CI bounds, breakeven handling, fail-safe, determinism
  * _gate_v2_trade_metrics.trade_level_win_rate_ci_lower — shared-pnl path + fail-safe
  * _gate_v2_helpers.GATE_WIN_RATE_CI_LOWER is None (uncalibrated — not yet enforced)
  * run_mes_trend_rank11._compute_gate_v2 RECORDS win_rate_ci_lower but does NOT gate on
    it (shadow: changing the win-rate must not change the verdict)

Fixture-free (try/finally) so it runs under pytest or standalone:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_gate_v2_win_rate.py -q
    engine/.venv/Scripts/python.exe engine/tests/test_gate_v2_win_rate.py
"""

import os
import pathlib
import sys
from types import SimpleNamespace

_ENGINE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ENGINE))
os.environ.setdefault("API_KEY", "test-key")

import backtest._gate_v2_helpers as gh  # noqa: E402
import backtest._gate_v2_trade_metrics as tlm  # noqa: E402
import backtest.run_mes_trend_rank11 as mes  # noqa: E402
from backtest.monte_carlo import bootstrap_win_rate  # noqa: E402


def _oos_with_pnls(pnls):
    """One OOS window carrying the given per-trade pnls (concat_oos_trade_pnls reads r.trades[].pnl)."""
    return SimpleNamespace(
        total_trades=len(pnls),
        profit_factor=1.5,
        max_drawdown_pct=2.0,
        trades=[SimpleNamespace(pnl=p) for p in pnls],
    )


# --- bootstrap_win_rate -------------------------------------------------------
def test_all_wins():
    r = bootstrap_win_rate([10.0, 20.0, 30.0, 40.0])
    assert r["win_rate"] == 1.0
    assert r["win_rate_ci_95_low"] == 1.0
    assert r["n_trades"] == 4


def test_all_losses():
    r = bootstrap_win_rate([-10.0, -20.0, -30.0])
    assert r["win_rate"] == 0.0
    assert r["win_rate_ci_95_low"] == 0.0


def test_breakeven_is_not_a_win():
    r = bootstrap_win_rate([0.0, 10.0])
    assert r["win_rate"] == 0.5  # the 0.0 trade is not counted as a win


def test_mixed_ci_low_below_point_estimate():
    pnls = [10.0, -10.0] * 25  # 50 trades, ~50% win rate
    r = bootstrap_win_rate(pnls)
    assert 0.4 <= r["win_rate"] <= 0.6
    assert 0.0 <= r["win_rate_ci_95_low"] <= r["win_rate"]
    assert r["win_rate_ci_95_low"] < r["win_rate_ci_95_high"]


def test_fail_safe_under_two_trades():
    r = bootstrap_win_rate([42.0])
    assert r == {"win_rate": 0.0, "win_rate_ci_95_low": 0.0, "win_rate_ci_95_high": 0.0, "n_trades": 1}


def test_deterministic_same_seed():
    pnls = [5.0, -3.0, 7.0, -2.0, 9.0, -8.0, 1.0]
    assert bootstrap_win_rate(pnls, seed=42) == bootstrap_win_rate(pnls, seed=42)


# --- trade_level_win_rate_ci_lower -------------------------------------------
def test_trade_level_win_rate_shared_path():
    # two windows -> concatenated to [10,-10,10,-10,10,-10] (50% win rate)
    oos = [_oos_with_pnls([10.0, -10.0, 10.0]), _oos_with_pnls([-10.0, 10.0, -10.0])]
    wr = tlm.trade_level_win_rate_ci_lower(oos)
    assert 0.0 <= wr <= 1.0


def test_trade_level_win_rate_fail_safe():
    assert tlm.trade_level_win_rate_ci_lower([_oos_with_pnls([5.0])]) == 0.0
    assert tlm.trade_level_win_rate_ci_lower([]) == 0.0


# --- helpers: uncalibrated, not enforced -------------------------------------
def test_gate_win_rate_ci_lower_is_none():
    assert gh.GATE_WIN_RATE_CI_LOWER is None  # uncalibrated -> intentionally not in any gate


# --- integration: runner records but does NOT gate on win-rate (shadow) ------
def _call_gate(oos_results, win_rate_stub):
    saved = (tlm.trade_level_dsr, tlm.trade_level_mc_95th_dd, tlm.trade_level_win_rate_ci_lower)
    tlm.trade_level_dsr = lambda *a, **k: 1.0
    tlm.trade_level_mc_95th_dd = lambda *a, **k: 0.01
    tlm.trade_level_win_rate_ci_lower = lambda *a, **k: win_rate_stub
    try:
        return mes._compute_gate_v2(
            oos_results,
            n_grid_combos=3,
            fixed_params_metrics={
                "fixed_params_min_pf": 2.0,
                "fixed_params_mean_pf": 2.0,
                "fixed_params_max_pf": 2.0,
            },
            cost_sweep_metrics={"cost_survives_through": "catastrophic"},
        )
    finally:
        tlm.trade_level_dsr, tlm.trade_level_mc_95th_dd, tlm.trade_level_win_rate_ci_lower = saved


def test_runner_records_win_rate_ci_lower():
    g = _call_gate([_oos_with_pnls([10.0, -10.0]) for _ in range(20)], win_rate_stub=0.123)
    assert g["win_rate_ci_lower"] == 0.123


def test_win_rate_does_not_change_verdict_in_shadow():
    oos = [_oos_with_pnls([10.0, -10.0]) for _ in range(20)]
    hi = _call_gate(oos, win_rate_stub=0.99)["verdict"]
    lo = _call_gate(oos, win_rate_stub=0.0)["verdict"]
    assert hi == lo  # shadow: win-rate is recorded, not gated


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
