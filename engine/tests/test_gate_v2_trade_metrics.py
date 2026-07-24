"""Tests for trade-level gate-v2 metrics (correct drawdown MC + Deflated Sharpe).

Pins the centralised helpers to the canonical primitives
(`monte_carlo.permute_max_dd`, `deflated_sharpe.deflated_sharpe_from_returns`)
that `scripts/validate_strategy.py` already uses, and proves they consume the
real per-trade sequence rather than window-level aggregates.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from backtest._gate_v2_trade_metrics import (
    concat_oos_trade_pnls,
    trade_level_cvar,
    trade_level_dsr,
    trade_level_mc_95th_dd,
    trade_level_p_edge,
    trade_level_pf_ci_lower,
    trade_level_probability_of_ruin,
    trade_level_var,
)
from backtest.deflated_sharpe import deflated_sharpe_from_returns
from backtest.monte_carlo import (
    bootstrap_pf,
    compute_cvar,
    compute_var,
    moving_block_bootstrap,
    permute_max_dd,
)
from backtest.monte_carlo import probability_of_ruin as mc_probability_of_ruin

CAP = 50_000.0


def _trade(pnl: float) -> SimpleNamespace:
    return SimpleNamespace(pnl=pnl)


def _window(pnls, max_drawdown_pct=0.0, sharpe_ratio=0.0, total_trades=None):
    return SimpleNamespace(
        trades=[_trade(p) for p in pnls],
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        total_trades=len(pnls) if total_trades is None else total_trades,
    )


class TestConcatOosTradePnls:
    def test_flattens_in_sequence(self):
        windows = [_window([100.0, -50.0]), _window([25.0]), _window([-10.0, 5.0])]
        assert concat_oos_trade_pnls(windows) == [100.0, -50.0, 25.0, -10.0, 5.0]

    def test_skips_empty_windows(self):
        windows = [_window([100.0]), _window([]), _window([-20.0])]
        assert concat_oos_trade_pnls(windows) == [100.0, -20.0]

    def test_handles_missing_trades_attr(self):
        windows = [SimpleNamespace(), _window([7.0])]
        assert concat_oos_trade_pnls(windows) == [7.0]


class TestTradeLevelMc95thDd:
    def test_matches_canonical_primitive_as_fraction(self):
        """The helper must equal permute_max_dd on the concatenated trade list,
        converted from the primitive's 0-100 scale to a fraction."""
        pnls = [200.0, -150.0, -120.0, 90.0, -200.0, 60.0, -80.0, 140.0]
        windows = [_window(pnls[:3]), _window(pnls[3:6]), _window(pnls[6:])]
        expected = (
            permute_max_dd(pnls, initial_capital=CAP, n_resamples=10_000, seed=42)["mc_95th"]
            / 100.0
        )
        assert trade_level_mc_95th_dd(windows, initial_capital=CAP) == expected

    def test_returns_fraction_scale(self):
        pnls = [-500.0] * 6 + [100.0] * 6
        windows = [_window(pnls)]
        dd = trade_level_mc_95th_dd(windows, initial_capital=CAP)
        assert 0.0 < dd < 1.0  # a fraction, not a 0-100 percentage

    def test_failsafe_when_too_few_trades(self):
        assert trade_level_mc_95th_dd([_window([42.0])], initial_capital=CAP) == 1.0
        assert trade_level_mc_95th_dd([_window([])], initial_capital=CAP) == 1.0

    def test_sees_cross_window_drawdown_window_level_misses(self):
        """Regression: a losing streak spread across windows that each show a
        small per-window DD must surface as a large trade-level DD."""
        streak = [_window([-400.0, -400.0], max_drawdown_pct=0.005) for _ in range(3)]
        window_level_p95 = float(np.percentile([w.max_drawdown_pct for w in streak], 95.0))
        trade_level = trade_level_mc_95th_dd(streak, initial_capital=CAP)
        assert window_level_p95 == 0.005
        assert trade_level > window_level_p95  # the real tail is bigger


class TestTradeLevelDsr:
    def test_matches_canonical_primitive(self):
        pnls = [300.0, -100.0, 250.0, -80.0, 400.0, -120.0, 180.0, -60.0, 220.0]
        windows = [_window(pnls[:5]), _window(pnls[5:])]
        returns = (np.asarray(pnls) / CAP).tolist()
        expected = deflated_sharpe_from_returns(returns=returns, n_trials=3, ann_factor=252.0)[
            "dsr"
        ]
        assert trade_level_dsr(windows, n_grid_combos=3, initial_capital=CAP) == expected

    def test_failsafe_when_empty(self):
        assert trade_level_dsr([_window([])], n_grid_combos=8, initial_capital=CAP) == 0.0

    def test_in_unit_interval(self):
        rng = np.random.default_rng(0)
        pnls = (rng.normal(50, 300, size=60)).tolist()
        windows = [_window(pnls)]
        dsr = trade_level_dsr(windows, n_grid_combos=8, initial_capital=CAP)
        assert 0.0 <= dsr <= 1.0


class TestTradeLevelVar:
    def test_matches_canonical_primitive(self):
        """Report-only diagnostic -- must equal compute_var on the concatenated
        OOS trade list (same delegate pattern as trade_level_mc_95th_dd)."""
        pnls = [200.0, -150.0, -120.0, 90.0, -200.0, 60.0, -80.0, 140.0]
        windows = [_window(pnls[:3]), _window(pnls[3:6]), _window(pnls[6:])]
        expected = compute_var(pnls, confidence=0.95, n_resamples=10_000, seed=42)["var_pct"]
        assert trade_level_var(windows, initial_capital=CAP) == expected

    def test_failsafe_when_too_few_trades(self):
        assert trade_level_var([_window([42.0])], initial_capital=CAP) == 0.0
        assert trade_level_var([_window([])], initial_capital=CAP) == 0.0


class TestTradeLevelCvar:
    def test_matches_canonical_primitive(self):
        pnls = [200.0, -150.0, -120.0, 90.0, -200.0, 60.0, -80.0, 140.0]
        windows = [_window(pnls[:3]), _window(pnls[3:6]), _window(pnls[6:])]
        expected = compute_cvar(pnls, confidence=0.95, n_resamples=10_000, seed=42)["cvar"]
        assert trade_level_cvar(windows, initial_capital=CAP) == expected

    def test_failsafe_when_too_few_trades(self):
        assert trade_level_cvar([_window([42.0])], initial_capital=CAP) == 0.0
        assert trade_level_cvar([_window([])], initial_capital=CAP) == 0.0


class TestTradeLevelProbabilityOfRuin:
    def test_matches_canonical_primitive(self):
        pnls = [500.0, 500.0, -8000.0, 500.0]
        windows = [_window(pnls[:2]), _window(pnls[2:])]
        expected = mc_probability_of_ruin(
            pnls, initial_capital=CAP, ruin_threshold_pct=0.5, n_resamples=10_000, seed=42
        )["probability_of_ruin"]
        assert (
            trade_level_probability_of_ruin(windows, initial_capital=CAP, ruin_threshold_pct=0.5)
            == expected
        )

    def test_failsafe_when_too_few_trades_returns_zero_not_one(self):
        assert trade_level_probability_of_ruin([_window([42.0])], initial_capital=CAP) == 0.0
        assert trade_level_probability_of_ruin([_window([])], initial_capital=CAP) == 0.0
class TestTradeLevelPfCiLower:
    def test_matches_canonical_primitive(self):
        pnls = [300.0, -100.0, 250.0, -80.0, 400.0, -120.0, 180.0, -60.0, 220.0]
        windows = [_window(pnls[:5]), _window(pnls[5:])]
        expected = moving_block_bootstrap(pnls, n_resamples=10_000, seed=42)["pf_ci_95_low"]
        assert trade_level_pf_ci_lower(windows) == expected

    def test_failsafe_when_too_few_trades(self):
        """Found 2026-07-10: a single winning trade must not report a
        confident pf_ci_95_low (moving_block_bootstrap would return +inf for
        a zero-loss sample) -- fail-safe to 0.0, same as the sibling
        trade-level metrics."""
        assert trade_level_pf_ci_lower([_window([42.0])]) == 0.0
        assert trade_level_pf_ci_lower([_window([])]) == 0.0

    def test_sees_cross_window_serial_correlation(self):
        """Sanity: a non-degenerate multi-window sample returns a finite,
        non-negative lower bound."""
        pnls = [100.0, -40.0, 120.0, -50.0, 90.0, -30.0, 110.0, -45.0]
        windows = [_window(pnls[:4]), _window(pnls[4:])]
        result = trade_level_pf_ci_lower(windows)
        assert result >= 0.0 and result != float("inf")


class TestTradeLevelPEdge:
    def test_matches_canonical_primitive(self):
        pnls = [300.0, -100.0, 250.0, -80.0, 400.0, -120.0, 180.0, -60.0, 220.0]
        windows = [_window(pnls[:5]), _window(pnls[5:])]
        expected = bootstrap_pf(pnls, n_resamples=10_000, seed=42)["p_positive_edge"]
        assert trade_level_p_edge(windows) == expected

    def test_failsafe_when_too_few_trades(self):
        """Found 2026-07-10: a single winning trade must not report a
        confident p_edge=1.0 (every IID resample of one win is "positive
        edge") -- fail-safe to 0.0, same as the sibling trade-level metrics."""
        assert trade_level_p_edge([_window([42.0])]) == 0.0
        assert trade_level_p_edge([_window([])]) == 0.0

    def test_in_unit_interval(self):
        rng = np.random.default_rng(0)
        pnls = (rng.normal(50, 300, size=60)).tolist()
        windows = [_window(pnls)]
        p_edge = trade_level_p_edge(windows)
        assert 0.0 <= p_edge <= 1.0
