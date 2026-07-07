"""Unit tests for the ES-NQ spread mean-reversion backtester (backtest/spread_backtest.py).

Pins the pure logic the empirical result rests on:
  - compute_spread_z: log-spread + no-look-ahead rolling z-score (NaN warm-up, zero-var -> 0)
  - generate_positions: the entry/exit/stop state machine
  - run_backtest: held = desired.shift(1) (no look-ahead), dollar-neutral return, per-leg cost
  - _trade_pnls / compute_metrics: trade grouping + PF / Sharpe / DD / win-rate

If these are wrong, the gate-v2 verdict on the strategy is meaningless. Pure math; no
network, no cache, not on the trading path.
"""

from __future__ import annotations

import numpy as np

from backtest import spread_backtest as sb

# --- compute_spread_z ------------------------------------------------------


def test_spread_z_warmup_is_nan():
    a = np.array([10.0, 11.0, 12.0, 13.0])
    b = np.ones(4)
    _, z = sb.compute_spread_z(a, b, window=3)
    assert np.isnan(z[0]) and np.isnan(z[1])
    assert not np.isnan(z[2])


def test_spread_z_hand_computed():
    # b = 1 so spread = ln(a). window=2: at t=1 spread=[ln(e^1),ln(e^3)]=[1,3]
    # mean=2, std(ddof=0)=1 -> z=(3-2)/1 = 1.0
    a = np.array([np.e**1, np.e**3])
    b = np.ones(2)
    _, z = sb.compute_spread_z(a, b, window=2)
    assert abs(z[1] - 1.0) < 1e-9


def test_spread_z_zero_variance_is_zero_not_inf():
    a = np.full(5, 7.0)  # constant spread -> std 0
    b = np.ones(5)
    _, z = sb.compute_spread_z(a, b, window=3)
    assert z[4] == 0.0  # guarded, not inf/nan


def test_spread_is_log_difference():
    a = np.array([2.0, 4.0, 8.0])
    b = np.array([1.0, 2.0, 4.0])
    spread, _ = sb.compute_spread_z(a, b, window=2)
    # ln(2)-ln(1)=ln2 ; ln(4)-ln(2)=ln2 ; ln(8)-ln(4)=ln2
    assert np.allclose(spread, np.log(2.0))


# --- generate_positions ----------------------------------------------------


def test_positions_entry_exit_cycle():
    z = np.array([np.nan, 2.5, 1.0, 0.3, -2.5, 0.0])
    pos = sb.generate_positions(z, entry=2.0, exit_=0.5, stop=4.0)
    assert list(pos) == [0, -1, -1, 0, 1, 0]


def test_positions_hard_stop_on_divergence():
    z = np.array([np.nan, 2.5, 4.5])
    pos = sb.generate_positions(z, entry=2.0, exit_=0.5, stop=4.0)
    assert list(pos) == [0, -1, 0]  # stopped out when |z|>stop


def test_positions_nan_holds_current():
    z = np.array([np.nan, -2.5, np.nan, np.nan])
    pos = sb.generate_positions(z, entry=2.0, exit_=0.5, stop=4.0)
    assert list(pos) == [0, 1, 1, 1]  # nan -> hold the open position


def test_positions_below_entry_stays_flat():
    z = np.array([1.9, -1.9, 0.0])
    pos = sb.generate_positions(z, entry=2.0, exit_=0.5, stop=4.0)
    assert list(pos) == [0, 0, 0]


# --- run_backtest ----------------------------------------------------------


def test_backtest_no_lookahead_first_bar_zero():
    a = np.array([100.0, 101.0, 102.0])
    b = np.array([100.0, 100.0, 100.0])
    desired = np.array([1, 1, 1])
    net = sb.run_backtest(a, b, desired, cost_bps_per_leg=0.0)
    assert net[0] == 0.0  # held[0]=0, nothing earned on the first bar


def test_backtest_long_spread_earns_a_minus_b_return():
    # held into bars 1,2 = desired[0],desired[1] = +1. spread_ret = dlogA - dlogB.
    a = np.array([100.0, 110.0, 110.0])  # +~9.53% then flat
    b = np.array([100.0, 100.0, 105.0])  # flat then +~4.88%
    desired = np.array([1, 1, 1])
    net = sb.run_backtest(a, b, desired, cost_bps_per_leg=0.0)
    assert abs(net[1] - (np.log(110 / 100) - np.log(100 / 100))) < 1e-9
    assert abs(net[2] - (np.log(110 / 110) - np.log(105 / 100))) < 1e-9


def test_backtest_charges_cost_on_position_change():
    a = np.array([100.0, 100.0, 100.0])
    b = np.array([100.0, 100.0, 100.0])
    desired = np.array([1, 1, 0])  # held = [0,1,1]; change at bar1 (0->1)
    net = sb.run_backtest(a, b, desired, cost_bps_per_leg=2.0)
    # bar1: |held1-held0|=1 -> cost = 1 * 2 legs * 2bp = 4bp = 4e-4
    assert abs(net[1] - (-4e-4)) < 1e-12
    assert net[2] == 0.0  # held[2]=held[1]=1, no change, flat prices


# --- _trade_pnls / compute_metrics -----------------------------------------


def test_trade_pnls_groups_runs():
    held = np.array([0, 1, 1, 0, -1, -1, 0])
    net = np.array([0.0, 0.5, 0.3, 0.0, -0.2, 0.4, 0.0])
    trades = sb._trade_pnls(held, net)
    assert trades == [0.8, 0.2]  # run1: .5+.3 ; run2: -.2+.4


def test_metrics_profit_factor_and_winrate():
    # construct desired so held has two trades: one +, one -
    # desired -> held=shift1. Want held = [0,1,1,0,-1,0]
    desired = np.array([1, 1, 0, -1, 0, 0])
    net = np.array([0.0, 1.0, 0.5, 0.0, -0.5, 0.0])
    m = sb.compute_metrics(net, desired, periods_per_year=252)
    # trade1 (held +1 at bars1,2): 1.0+0.5 = 1.5 win ; trade2 (held -1 at bar4): -0.5 loss
    assert m["n_trades"] == 2
    assert m["win_rate"] == 0.5
    assert m["pf"] == round(1.5 / 0.5, 3)


def test_metrics_all_wins_infinite_pf():
    desired = np.array([1, 0])
    net = np.array([0.0, 0.7])
    m = sb.compute_metrics(net, desired, periods_per_year=252)
    assert m["pf"] == float("inf")
    assert m["win_rate"] == 1.0


def test_metrics_max_drawdown():
    # net cumsum: 1, 0, -1, 0  -> peak 1 then trough -1 -> maxDD = 2
    desired = np.array([1, 1, 1, 1, 0])
    net = np.array([0.0, 1.0, -1.0, -1.0, 1.0])
    m = sb.compute_metrics(net, desired, periods_per_year=252)
    assert m["max_dd"] == 2.0


# --- _pf / bootstrap_eval --------------------------------------------------


def test_pf_basic_and_edge_cases():
    assert sb._pf([2.0, -1.0]) == 2.0
    assert sb._pf([1.0, 2.0]) == float("inf")  # no losers
    assert sb._pf([-1.0, -2.0]) == 0.0  # no winners
    assert sb._pf([]) == 0.0


def test_bootstrap_eval_deterministic_and_detects_strong_edge():
    pnls = [1.0] * 40 + [-0.2] * 10  # clearly profitable, low loss
    a = sb.bootstrap_eval(pnls, n_boot=1000, seed=7)
    b = sb.bootstrap_eval(pnls, n_boot=1000, seed=7)
    assert a == b  # deterministic for fixed seed
    assert a["n_trades"] == 50
    assert a["p_edge"] == 1.0  # mean always > 0 under resampling
    assert a["pf_ci_lower"] > 1.10


def test_bootstrap_eval_no_edge_has_low_p_edge():
    pnls = [1.0, -1.0] * 25  # zero expectancy
    out = sb.bootstrap_eval(pnls, n_boot=2000, seed=3)
    assert 0.3 < out["p_edge"] < 0.7  # coin-flip-ish, not a real edge
    assert out["pf_ci_lower"] < 1.10


def test_bootstrap_eval_too_few_trades_is_safe():
    out = sb.bootstrap_eval([1.0], n_boot=100, seed=1)
    assert out["n_trades"] == 1
    assert out["p_edge"] == 0.0
