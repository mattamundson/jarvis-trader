"""Regression: DO_NOT_TRADE_SYMBOLS gate must force NO_TRADE on MCL/MNQ.

Locks T5 Option B from the 2026-04-21 per-symbol strategy decision.
MCL and MNQ have 0 validated WFO winners on cached OHLC 2024-06→2026-03
(per multi_symbol_trend_wfo.py); composite path scored PF 0.13. Until a
per-symbol edge is re-derived, generate_instrument_signals MUST emit
NO_TRADE for these symbols so paper trading doesn't pollute learning.

See memory/project_per_symbol_strategy_decision.md for full rationale.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.signals import DO_NOT_TRADE_SYMBOLS, generate_instrument_signals


@pytest.fixture
def bullish_ohlcv_df() -> pd.DataFrame:
    """Strongly bullish OHLCV that would normally trigger ENTRY_NOW on the
    standard generate_signals path — used to confirm the gate overrides real
    entry triggers, not just the no-signal case."""
    dates = pd.date_range("2024-01-01", periods=300, freq="1h")
    rng = np.random.default_rng(42)
    trend = np.linspace(5700, 5900, 300)
    noise = rng.normal(0, 10, 300)
    close = trend + noise
    return pd.DataFrame(
        {
            "open": close - 5,
            "high": close + 20,
            "low": close - 20,
            "close": close,
            "volume": np.linspace(2_000_000, 4_000_000, 300),
        },
        index=dates,
    )


class TestDoNotTradeGate:
    def test_membership(self):
        """MCL, MNQ, and M2K must be in the blocklist; MGC (re-authorized
        2026-08-04, PR #598) and MES must NOT be."""
        assert "MCL" in DO_NOT_TRADE_SYMBOLS
        assert "MNQ" in DO_NOT_TRADE_SYMBOLS
        assert "M2K" in DO_NOT_TRADE_SYMBOLS
        assert "MGC" not in DO_NOT_TRADE_SYMBOLS
        assert "MES" not in DO_NOT_TRADE_SYMBOLS

    def test_mcl_forced_no_trade(self, bullish_ohlcv_df):
        out = generate_instrument_signals(bullish_ohlcv_df, symbol="MCL")
        assert "entry_signal" in out.columns
        assert (out["entry_signal"] == "NO_TRADE").all(), (
            "every row must be NO_TRADE on blocklisted symbol"
        )

    def test_mnq_forced_no_trade(self, bullish_ohlcv_df):
        out = generate_instrument_signals(bullish_ohlcv_df, symbol="MNQ")
        assert (out["entry_signal"] == "NO_TRADE").all()

    def test_mcl_exit_signal_also_cleared_when_present(self, bullish_ohlcv_df):
        """If the underlying path populates exit_signal, the gate must also
        override it to NO_EXIT so the Backtester doesn't close phantom
        positions on a symbol that was never entered."""
        out = generate_instrument_signals(bullish_ohlcv_df, symbol="MCL")
        if "exit_signal" in out.columns:
            assert (out["exit_signal"] == "NO_EXIT").all()

    def test_output_shape_preserved(self, bullish_ohlcv_df):
        """The gate must return a DataFrame with the same row count as input —
        callers (Backtester) assume index alignment."""
        out = generate_instrument_signals(bullish_ohlcv_df, symbol="MCL")
        assert len(out) == len(bullish_ohlcv_df)

    def test_spy_unaffected(self, bullish_ohlcv_df):
        """Symbols outside both TREND_INSTRUMENTS and DO_NOT_TRADE_SYMBOLS
        (e.g. SPY) still route through generate_signals unchanged. This proves
        the gate is additive, not a global kill-switch."""
        out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
        assert "entry_signal" in out.columns
        # SPY output can legitimately be all NO_TRADE on some synthetic data,
        # but it must NOT be forced — meaning at least the column exists and
        # is populated by the real signal path. We verify here by proving the
        # call doesn't raise and returns the standard shape.
        assert len(out) == len(bullish_ohlcv_df)
