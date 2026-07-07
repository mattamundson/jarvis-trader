"""
JARVIS TRADER — Backtester Metrics Regression Tests (2026-04-20)

Locks the three bug-class fixes applied 2026-04-20:
1. Max DD > 0 when equity actually drew down (was reported as 0.0% in composite runs).
2. Sharpe sign matches return sign when trades all move in one direction — cannot
   produce positive Sharpe with PF < 1.
3. final_capital and total_return_pct internally consistent via
   total_return_pct = (final - initial) / initial.

Background: a prior composite MES/MCL/MNQ/MGC run reported:
    Capital: $10,000 -> $184,734   (+1747%)
    Return: -19.9%                  (self-contradiction)
    Max DD: 0.0%                    (mathematically impossible)
    Sharpe: 2.06  |  PF: 0.13       (paradox — cannot be both)

Root causes:
    (A) run_composite_backtest.py read result['max_drawdown'] (never existed) instead
        of 'max_drawdown_pct'. to_dict() only exposes max_drawdown_pct.
    (B) Sharpe computed over per-bar equity diffs: on 1h data most bars show 0-return
        (no position change), inflating Sharpe by suppressing std near zero.
    (C) total_return_pct computed from gross_pnl / initial_capital, while final_capital
        included transaction costs and slippage — the two diverged.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from backtest.metrics import calculate_metrics
from backtest.trade_manager import BacktestResult, Trade

# ─── Helpers ────────────────────────────────────────────────────────────────


def _trade(pnl: float, day_offset: int = 0, direction: str = "long") -> Trade:
    """Construct a minimal Trade with the given pnl."""
    base = datetime(2024, 1, 1)
    return Trade(
        entry_date=base + timedelta(days=day_offset),
        exit_date=base + timedelta(days=day_offset, hours=1),
        symbol="TEST",
        direction=direction,
        entry_price=100.0,
        stop_price=99.0,
        target_1=102.0,
        target_2=104.0,
        contracts=1,
        multiplier=1.0,
        exit_price=100.0 + (1.0 if pnl > 0 else -1.0),
        pnl=pnl,
        exit_reason="target_1" if pnl > 0 else "stop",
        holding_bars=1,
    )


def _build_equity_curve(initial: float, trade_pnls: list) -> list:
    """Build an equity curve that walks through the trade pnls with a few flat
    bars between each trade (simulates intraday bars where no trade exits)."""
    equity = [initial]
    running = initial
    flat_bars_between_trades = 20  # simulate 20 no-position bars per trade
    for pnl in trade_pnls:
        # Flat bars (no change)
        for _ in range(flat_bars_between_trades):
            equity.append(running)
        running += pnl
        equity.append(running)
    return equity


# ─── Bug 1: Max Drawdown must be non-zero when equity drops ─────────────────


class TestMaxDrawdownBug:
    def test_max_dd_nonzero_on_losing_streak(self):
        """A streak of losses must register as a drawdown > 0."""
        initial = 10_000.0
        trade_pnls = [-500.0, -500.0, -500.0, 500.0]  # peak→trough $1500, recover $500
        equity = _build_equity_curve(initial, trade_pnls)
        trades = [_trade(pnl, i) for i, pnl in enumerate(trade_pnls)]

        result = BacktestResult(
            symbol="TEST",
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_capital=initial,
            final_capital=equity[-1],
            equity_curve=equity,
            trades=trades,
        )
        calculate_metrics(result)

        # Peak was $10k, trough was $8.5k → DD = 15%
        assert result.max_drawdown_pct > 0, "Max DD must be > 0 on a losing streak"
        assert result.max_drawdown_pct == pytest.approx(0.15, rel=0.01), (
            f"Expected ~15% DD, got {result.max_drawdown_pct:.4f}"
        )
        assert result.max_drawdown_dollars == pytest.approx(1500.0, rel=0.01)

    def test_max_dd_zero_only_on_monotonic_uptrend(self):
        """Max DD == 0 is ONLY valid when every bar strictly >= running peak."""
        initial = 10_000.0
        trade_pnls = [100.0, 200.0, 300.0, 50.0]  # all wins
        equity = _build_equity_curve(initial, trade_pnls)
        trades = [_trade(pnl, i) for i, pnl in enumerate(trade_pnls)]

        result = BacktestResult(
            symbol="TEST",
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_capital=initial,
            final_capital=equity[-1],
            equity_curve=equity,
            trades=trades,
        )
        calculate_metrics(result)

        # Monotonic up — DD should be 0
        assert result.max_drawdown_pct == 0.0

    def test_max_dd_key_exposed_in_to_dict(self):
        """to_dict() must expose 'max_drawdown_pct' (not 'max_drawdown') — this was
        the root cause of the composite runner showing 0.0%."""
        result = BacktestResult(
            symbol="TEST",
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_capital=10_000.0,
            final_capital=8_000.0,
            equity_curve=[10_000.0, 9_000.0, 8_000.0],
            trades=[_trade(-1000.0, 0), _trade(-1000.0, 1)],
        )
        calculate_metrics(result)
        d = result.to_dict()
        assert "max_drawdown_pct" in d, "to_dict must expose max_drawdown_pct"
        assert d["max_drawdown_pct"] > 0


# ─── Bug 2: Sharpe sign must match return sign ──────────────────────────────


class TestSharpeSignBug:
    def test_negative_return_cannot_produce_positive_sharpe(self):
        """If total PnL is negative, Sharpe must be negative (or zero).

        This is the 'Sharpe 2.0 with PF 0.13' paradox — it happened because Sharpe
        was computed over per-bar equity diffs where most bars were flat zeros.
        """
        initial = 10_000.0
        # Many small losses, one tiny win → PF < 1
        trade_pnls = [-200.0, -180.0, -220.0, -190.0, -210.0,
                      -200.0, -180.0, -220.0, -190.0, 100.0]
        equity = _build_equity_curve(initial, trade_pnls)
        trades = [_trade(pnl, i) for i, pnl in enumerate(trade_pnls)]

        result = BacktestResult(
            symbol="TEST",
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_capital=initial,
            final_capital=equity[-1],
            equity_curve=equity,
            trades=trades,
        )
        calculate_metrics(result)

        assert result.profit_factor < 1.0, f"Setup error: expected PF<1, got {result.profit_factor}"
        assert result.total_return_pct < 0, "Return must be negative"
        assert result.sharpe_ratio < 0, (
            f"Sharpe must be NEGATIVE when PF<1 and return<0, got {result.sharpe_ratio}"
        )

    def test_positive_return_produces_positive_sharpe(self):
        """Sanity: a winning strategy should yield positive Sharpe."""
        initial = 10_000.0
        # Consistent wins with small losses → PF > 2
        trade_pnls = [300.0, 300.0, 300.0, 300.0, 300.0,
                      -100.0, 300.0, 300.0, -100.0, 300.0]
        equity = _build_equity_curve(initial, trade_pnls)
        trades = [_trade(pnl, i) for i, pnl in enumerate(trade_pnls)]

        result = BacktestResult(
            symbol="TEST",
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_capital=initial,
            final_capital=equity[-1],
            equity_curve=equity,
            trades=trades,
        )
        calculate_metrics(result)

        assert result.profit_factor > 2.0
        assert result.sharpe_ratio > 0
        # Total pnl = 300*8 - 100*2 = 2200 → 22% return
        assert result.total_return_pct == pytest.approx(0.22, rel=0.01)

    def test_sharpe_uses_per_trade_returns_not_equity_bars(self):
        """Sharpe must NOT be computed over per-bar equity diffs.

        If it were, an equity curve with many flat bars between trades would have
        artificially low std (most returns = 0) and inflated Sharpe. With two
        different curves containing identical trade pnls but different numbers of
        flat bars between, the Sharpe should be IDENTICAL (trade-scope) not
        different (bar-scope).
        """
        initial = 10_000.0
        trade_pnls = [100.0, -50.0, 200.0, -80.0, 150.0]
        trades = [_trade(pnl, i) for i, pnl in enumerate(trade_pnls)]

        # Curve A: few flat bars
        equity_a = [initial]
        running = initial
        for pnl in trade_pnls:
            for _ in range(2):
                equity_a.append(running)
            running += pnl
            equity_a.append(running)

        # Curve B: many flat bars (simulates intraday with long no-position gaps)
        equity_b = [initial]
        running = initial
        for pnl in trade_pnls:
            for _ in range(200):
                equity_b.append(running)
            running += pnl
            equity_b.append(running)

        result_a = BacktestResult(
            symbol="TEST", start_date="", end_date="",
            initial_capital=initial, final_capital=equity_a[-1],
            equity_curve=equity_a, trades=list(trades),
        )
        result_b = BacktestResult(
            symbol="TEST", start_date="", end_date="",
            initial_capital=initial, final_capital=equity_b[-1],
            equity_curve=equity_b, trades=list(trades),
        )
        calculate_metrics(result_a)
        calculate_metrics(result_b)

        # Both must have SAME Sharpe since trade pnls are identical.
        # (Would fail pre-fix when Sharpe was bar-scoped.)
        assert result_a.sharpe_ratio == pytest.approx(result_b.sharpe_ratio, rel=1e-6), (
            f"Sharpe should be identical regardless of flat-bar count: "
            f"A={result_a.sharpe_ratio}, B={result_b.sharpe_ratio}"
        )


# ─── Bug 3: Capital vs Return internal consistency ──────────────────────────


class TestCapitalReturnConsistency:
    def test_final_capital_matches_derived_return(self):
        """Display: Capital: $X -> $Y  must agree with Return: Z%."""
        initial = 10_000.0
        trade_pnls = [500.0, -200.0, 300.0, -100.0]
        equity = _build_equity_curve(initial, trade_pnls)
        trades = [_trade(pnl, i) for i, pnl in enumerate(trade_pnls)]

        result = BacktestResult(
            symbol="TEST", start_date="", end_date="",
            initial_capital=initial, final_capital=equity[-1],
            equity_curve=equity, trades=trades,
        )
        calculate_metrics(result)

        # Derived return from display
        derived = (result.final_capital - result.initial_capital) / result.initial_capital
        assert result.total_return_pct == pytest.approx(derived, rel=1e-9), (
            f"total_return_pct={result.total_return_pct} vs derived={derived}"
        )

        # Invariant: final = initial × (1 + return)
        reconstructed_final = result.initial_capital * (1 + result.total_return_pct)
        assert reconstructed_final == pytest.approx(result.final_capital, rel=1e-9)

    def test_summary_string_internally_consistent(self):
        """summary() should not emit [WARN: disagreement] flag under normal flow."""
        initial = 10_000.0
        trade_pnls = [-500.0, -500.0, -500.0, 500.0]
        equity = _build_equity_curve(initial, trade_pnls)
        trades = [_trade(pnl, i) for i, pnl in enumerate(trade_pnls)]

        result = BacktestResult(
            symbol="TEST", start_date="", end_date="",
            initial_capital=initial, final_capital=equity[-1],
            equity_curve=equity, trades=trades,
        )
        calculate_metrics(result)
        summary = result.summary()
        assert "[WARN" not in summary, (
            f"summary() flagged capital/return disagreement: {summary}"
        )

    def test_summary_warns_when_values_drift(self):
        """If a caller manually mutates final_capital without re-running metrics,
        the warning flag should surface to help diagnose the drift."""
        result = BacktestResult(
            symbol="TEST", start_date="", end_date="",
            initial_capital=10_000.0, final_capital=10_000.0,
            equity_curve=[10_000.0, 11_000.0, 12_000.0],
            trades=[_trade(1000.0, 0), _trade(1000.0, 1)],
        )
        calculate_metrics(result)
        # Now simulate a bug: mutate final_capital after metrics ran
        result.final_capital = 50_000.0
        summary = result.summary()
        assert "[WARN" in summary, "summary() must warn on capital/return drift"


# ─── Combined sanity: all three bugs can't coexist after fix ────────────────


class TestFullPipelineConsistency:
    def test_losing_strategy_all_metrics_consistent(self):
        """A clearly losing strategy must show: negative return, positive DD, PF<1,
        and Sharpe<0 — all consistent with each other."""
        initial = 10_000.0
        trade_pnls = [-300.0] * 8 + [100.0] * 2  # 8 losses, 2 small wins → PF ≈ 0.08
        equity = _build_equity_curve(initial, trade_pnls)
        trades = [_trade(pnl, i) for i, pnl in enumerate(trade_pnls)]

        result = BacktestResult(
            symbol="TEST", start_date="", end_date="",
            initial_capital=initial, final_capital=equity[-1],
            equity_curve=equity, trades=trades,
        )
        calculate_metrics(result)

        # All three must agree on direction
        assert result.total_return_pct < 0
        assert result.profit_factor < 1.0
        assert result.sharpe_ratio < 0
        assert result.max_drawdown_pct > 0

        # Sharpe sign matches return sign
        assert np.sign(result.sharpe_ratio) == np.sign(result.total_return_pct)

        # DD magnitude at most equal to |return| when return is negative (can be less if
        # trough happened before final bar, but must be >= |return| when final bar is trough)
        assert result.max_drawdown_pct >= abs(result.total_return_pct) - 1e-9

        # Final capital reconstructs from return
        reconstructed = result.initial_capital * (1 + result.total_return_pct)
        assert reconstructed == pytest.approx(result.final_capital, rel=1e-9)

    def test_winning_strategy_all_metrics_consistent(self):
        """Mirror: winning strategy → positive return, positive Sharpe, PF>1."""
        initial = 10_000.0
        trade_pnls = [300.0] * 8 + [-100.0] * 2  # 8 wins, 2 small losses → PF = 12
        equity = _build_equity_curve(initial, trade_pnls)
        trades = [_trade(pnl, i) for i, pnl in enumerate(trade_pnls)]

        result = BacktestResult(
            symbol="TEST", start_date="", end_date="",
            initial_capital=initial, final_capital=equity[-1],
            equity_curve=equity, trades=trades,
        )
        calculate_metrics(result)

        assert result.total_return_pct > 0
        assert result.profit_factor > 1.0
        assert result.sharpe_ratio > 0
        assert np.sign(result.sharpe_ratio) == np.sign(result.total_return_pct)
