"""Sharpe/Sortino annualization regression tests (2026-08-17 fix).

Locks the correction of a defect where `ANNUALIZATION_TRADES_PER_YEAR = 252` was applied
unconditionally to per-trade returns, assuming every strategy trades ~daily. Low-frequency
strategies were overstated by sqrt(252 / actual_trades_per_year).

Real measured inflation on the MES deep-cache campaign (7.27y, 2019-05-05..2026-08-14):
    55/200/2.0 : 128 trades = 17.60/yr -> engine 2.0878 vs honest 0.5517  (3.78x)
    50/200/2.0 :  85 trades = 11.68/yr -> engine -0.4621 vs honest -0.0995 (4.64x)
    MRB best   :  22 trades =  3.02/yr -> engine 2.2458 vs honest 0.2460  (9.13x)
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from backtest.metrics import (
    DEFAULT_ANNUALIZATION_TRADES_PER_YEAR,
    MAX_ANNUALIZATION_TRADES_PER_YEAR,
    _annualization_factor,
    calculate_metrics,
)
from backtest.trade_manager import BacktestResult, Trade


def _trade(pnl: float, i: int) -> Trade:
    entry = datetime(2020, 1, 1) + timedelta(days=i)
    return Trade(
        entry_date=entry,
        symbol="TEST",
        direction="long" if pnl >= 0 else "short",
        entry_price=100.0,
        stop_price=98.0,
        target_1=104.0,
        target_2=106.0,
        contracts=1,
        multiplier=5.0,
        exit_date=entry + timedelta(hours=6),
        exit_price=100.0 + pnl / 10.0,
        pnl=pnl,
        exit_reason="target_1" if pnl >= 0 else "stop",
    )


def _result(pnls, start="2019-05-05", end="2026-08-14", initial=50_000.0) -> BacktestResult:
    equity, running = [initial], initial
    for p in pnls:
        running += p
        equity.append(running)
    return BacktestResult(
        symbol="TEST",
        start_date=start,
        end_date=end,
        initial_capital=initial,
        final_capital=equity[-1],
        equity_curve=equity,
        trades=[_trade(p, i) for i, p in enumerate(pnls)],
    )


class TestAnnualizationFactor:
    def test_uses_observed_trade_frequency(self):
        """128 trades over 7.27 years must annualize by ~17.6, not 252."""
        r = _result([100.0] * 128)
        assert _annualization_factor(r, 128) == pytest.approx(17.60, rel=0.02)

    def test_low_frequency_strategy_not_inflated(self):
        """22 trades over 7.27y -> ~3.0/yr. The old code used 252 (9.1x overstatement)."""
        r = _result([50.0] * 22)
        assert _annualization_factor(r, 22) == pytest.approx(3.03, rel=0.02)

    def test_missing_dates_falls_back_to_default(self):
        """Fixtures built without dates keep the legacy factor (comparability)."""
        r = _result([10.0, -5.0, 8.0], start="", end="")
        assert _annualization_factor(r, 3) == float(DEFAULT_ANNUALIZATION_TRADES_PER_YEAR)

    def test_unparseable_dates_fall_back_to_default(self):
        r = _result([10.0, -5.0], start="not-a-date", end="also-bad")
        assert _annualization_factor(r, 2) == float(DEFAULT_ANNUALIZATION_TRADES_PER_YEAR)

    def test_short_window_falls_back_to_default(self):
        """A sub-90-day window cannot be honestly annualized."""
        r = _result([10.0] * 5, start="2024-01-01", end="2024-02-01")
        assert _annualization_factor(r, 5) == float(DEFAULT_ANNUALIZATION_TRADES_PER_YEAR)

    def test_factor_is_capped(self):
        """A hyperactive strategy cannot produce an absurd multiplier."""
        r = _result([1.0] * 100_000, start="2024-01-01", end="2025-01-01")
        assert _annualization_factor(r, 100_000) == MAX_ANNUALIZATION_TRADES_PER_YEAR


class TestSharpeUsesObservedFrequency:
    def test_mes_champion_sharpe_is_not_inflated(self):
        """Regression: the 55/200/2.0 shape must not report a ~2.0 Sharpe.

        Uses a synthetic series matched to the real trade count and window. The
        pre-fix code returned sqrt(252/17.6) = 3.78x this value.
        """
        rng = np.random.default_rng(42)
        pnls = list(rng.normal(57.0, 435.0, 128))  # ~ real per-trade mean/std
        r = _result(pnls)
        calculate_metrics(r)

        assert r.annualization_trades_per_year == pytest.approx(17.60, rel=0.02)
        # Honest Sharpe for this shape is well under 1.0; pre-fix it exceeded 2.
        assert abs(r.sharpe_ratio) < 1.5, (
            f"Sharpe {r.sharpe_ratio} looks inflated — annualization regression?"
        )

    def test_sharpe_scales_as_sqrt_of_frequency(self):
        """Same PnL distribution over a 2x longer window => Sharpe / sqrt(2)."""
        pnls = [100.0, -60.0, 140.0, -50.0, 90.0, -70.0, 120.0, -40.0] * 8
        short = _result(pnls, start="2020-01-01", end="2022-01-01")  # 2y
        long = _result(pnls, start="2020-01-01", end="2024-01-01")  # 4y
        calculate_metrics(short)
        calculate_metrics(long)
        assert short.sharpe_ratio == pytest.approx(long.sharpe_ratio * np.sqrt(2), rel=0.02)

    def test_annualization_factor_is_recorded(self):
        """The factor must be auditable on the result object."""
        r = _result([100.0, -50.0, 80.0] * 20)
        calculate_metrics(r)
        assert r.annualization_trades_per_year > 0
        assert r.annualization_trades_per_year < 252

    def test_sign_invariant_preserved(self):
        """The 2026-04-20 invariant must survive: PF<1 => Sharpe<0."""
        r = _result([-200.0, -180.0, -220.0, -190.0, -210.0, -200.0, 100.0] * 10)
        calculate_metrics(r)
        assert r.profit_factor < 1.0
        assert r.sharpe_ratio < 0

    def test_sortino_uses_same_factor(self):
        r = _result([100.0, -60.0, 140.0, -50.0, 90.0] * 20)
        calculate_metrics(r)
        assert r.sortino_ratio != 0.0
        # Sortino uses downside std <= total std, so |sortino| >= |sharpe|
        assert abs(r.sortino_ratio) >= abs(r.sharpe_ratio)
