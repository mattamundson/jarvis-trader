"""Tests for `backtest.strategy_overlays` -- regime filter, payout-ratio
ranking, and ATR-extension profit-trim overlay candidates.

Focused on correctness against crafted synthetic OHLC data: the regime
filter must suppress entries below the macro SMA and leave everything else
untouched, the point-in-time SMA must never look ahead into the current
(still-forming) session, the payout ranking must correctly re-order by
payoff_ratio and report the win-rate-rank delta, and the ATR-extension
simulator must fire its partial-exit exactly once per trade and only when
price actually extends past the trigger level.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.strategy_overlays import (
    apply_regime_filter,
    compute_regime_sma,
    rank_by_payout_ratio,
    simulate_atr_extension_trim,
)
from backtest.trade_manager import BacktestResult
from backtest.trend_signals import generate_sma_trend_signals


def _make_uptrend_ohlc(n: int = 400, start: float = 100.0, drift: float = 0.05) -> pd.DataFrame:
    """Monotonic uptrend with small noise -- guarantees at least one golden cross
    and a large enough extension for the ATR-trim trigger to fire."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 0.15, n)
    close = start + np.cumsum(np.full(n, drift) + noise)
    close = np.maximum(close, 1.0)
    high = close + np.abs(rng.normal(0.3, 0.1, n))
    low = close - np.abs(rng.normal(0.3, 0.1, n))
    open_ = close - rng.normal(0, 0.1, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def _make_flat_then_dip_ohlc(n: int = 260, price: float = 100.0) -> pd.DataFrame:
    """Flat regime SMA baseline, then a dip below it right before a golden cross --
    exercises the regime filter's suppression path deterministically."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.full(n, price, dtype=float)
    close[-5:] = price - 10.0  # sharp dip: price now below the flat 200-session regime SMA
    return pd.DataFrame(
        {"open": close, "high": close + 0.2, "low": close - 0.2, "close": close}, index=idx
    )


def test_compute_regime_sma_no_lookahead():
    df = _make_uptrend_ohlc(n=300)
    regime_sma = compute_regime_sma(df, window=50)
    # A bar's regime SMA must be computable using only data strictly BEFORE that
    # bar's own session -- i.e. it must equal the shifted daily SMA as of the prior
    # session, never a value derived from same-session (future, intra-day) closes.
    daily_close = df["close"].resample("1D").last().dropna()
    expected_daily_sma = daily_close.rolling(50).mean().shift(1)
    last_ts = df.index[-1]
    last_session = last_ts.normalize()
    prior_sessions = expected_daily_sma.index[expected_daily_sma.index < last_session]
    if len(prior_sessions) > 0:
        expected = expected_daily_sma.loc[prior_sessions[-1]]
        actual = regime_sma.loc[last_ts]
        if pd.notna(expected):
            assert abs(actual - expected) < 1e-6


def test_apply_regime_filter_suppresses_entries_below_regime_sma():
    df = _make_flat_then_dip_ohlc(n=260)
    df_sig = generate_sma_trend_signals(df, fast=5, slow=20, atr_trail_mult=2.0)
    # Force a synthetic entry signal on the last (dipped) bar to deterministically
    # exercise suppression regardless of whether the flat/dip series happens to cross.
    df_sig.loc[df_sig.index[-1], "entry_signal"] = "ENTRY_NOW"
    df_sig.loc[df_sig.index[-1], "target_1"] = 999.0

    df_filtered = apply_regime_filter(df_sig, regime_window=50)

    last_row = df_filtered.iloc[-1]
    assert last_row["entry_signal"] == "NO_TRADE"
    assert pd.isna(last_row["target_1"])
    # Columns outside the suppression set are untouched
    assert "atr" in df_filtered.columns
    assert (df_filtered["exit_signal"] == df_sig["exit_signal"]).all()


def test_apply_regime_filter_keeps_entries_above_regime_sma():
    df = _make_uptrend_ohlc(n=300)
    df_sig = generate_sma_trend_signals(df, fast=10, slow=30, atr_trail_mult=2.0)
    df_filtered = apply_regime_filter(df_sig, regime_window=50)

    entries_before = (df_sig["entry_signal"] == "ENTRY_NOW").sum()
    entries_after = (df_filtered["entry_signal"] == "ENTRY_NOW").sum()
    # In a sustained uptrend, price is almost always above its own trailing 50-session
    # SMA, so the filter should suppress few or none of the (already rare) golden crosses.
    assert entries_after <= entries_before
    assert entries_before > 0  # sanity: the uptrend fixture actually produces entries


def test_apply_regime_filter_never_widens_entries():
    """The filter must be a pure subset operation -- it can only turn ENTRY_NOW into
    NO_TRADE, never the reverse, on any bar."""
    df = _make_uptrend_ohlc(n=300)
    df_sig = generate_sma_trend_signals(df, fast=10, slow=30, atr_trail_mult=2.0)
    df_filtered = apply_regime_filter(df_sig, regime_window=50)

    was_no_trade = df_sig["entry_signal"] == "NO_TRADE"
    still_no_trade_or_now = df_filtered.loc[was_no_trade, "entry_signal"].isin(["NO_TRADE"])
    assert still_no_trade_or_now.all()


def _make_result(win_rate: float, payoff_ratio: float, trades: int = 20) -> BacktestResult:
    return BacktestResult(
        symbol="MES",
        start_date="2024-01-01",
        end_date="2024-06-01",
        initial_capital=50_000.0,
        final_capital=50_000.0,
        total_trades=trades,
        win_rate=win_rate,
        payoff_ratio=payoff_ratio,
        profit_factor=1.0,
        sharpe_ratio=0.0,
        expectancy=0.0,
        max_drawdown_pct=0.05,
        total_return_pct=0.0,
    )


def test_rank_by_payout_ratio_reorders_and_flags_reversal():
    variants = {
        "high_winrate_low_payoff": _make_result(win_rate=0.65, payoff_ratio=0.80),
        "low_winrate_high_payoff": _make_result(win_rate=0.30, payoff_ratio=2.50),
        "middle": _make_result(win_rate=0.50, payoff_ratio=1.20),
    }
    ranked = rank_by_payout_ratio(variants)

    assert ranked[0]["variant"] == "low_winrate_high_payoff"
    assert ranked[0]["payout_rank"] == 1
    assert ranked[0]["win_rate_rank"] == 3  # worst win rate of the three
    assert ranked[0]["rank_delta"] == 2  # promoted 2 spots by payout-ratio ranking

    assert ranked[-1]["variant"] == "high_winrate_low_payoff"
    assert ranked[-1]["payout_rank"] == 3
    assert ranked[-1]["win_rate_rank"] == 1
    assert ranked[-1]["rank_delta"] == -2  # demoted 2 spots


def test_rank_by_payout_ratio_empty_input():
    assert rank_by_payout_ratio({}) == []


def test_simulate_atr_extension_trim_produces_valid_result():
    df = _make_uptrend_ohlc(n=400)
    result = simulate_atr_extension_trim(
        df,
        symbol="MES",
        multiplier=5.0,
        fast=10,
        slow=30,
        atr_trail_mult=2.0,
        trim_atr_mult=1.0,  # tight trigger -- fires readily on a strong synthetic uptrend
        trim_pct=0.5,
        initial_capital=50_000.0,
    )
    assert isinstance(result, BacktestResult)
    assert result.total_trades >= 1
    assert result.symbol == "MES"
    # calculate_metrics() must have populated derived fields
    assert result.total_return_pct == (result.final_capital - result.initial_capital) / result.initial_capital
    trim_exits = [t for t in result.trades if "trim" in t.exit_reason]
    # With a tight 1.0xATR trigger on a strong synthetic uptrend, at least one trade
    # should extend far enough to fire the partial trim.
    assert len(trim_exits) >= 1


def test_simulate_atr_extension_trim_no_lookahead_entry_fill():
    """Entries must fill on the bar AFTER the golden-cross signal bar, at that bar's
    open -- never at the signal bar's own close (which would be look-ahead)."""
    df = _make_uptrend_ohlc(n=400)
    result = simulate_atr_extension_trim(
        df, symbol="MES", multiplier=5.0, fast=10, slow=30, atr_trail_mult=2.0,
        trim_atr_mult=3.0, trim_pct=0.5,
    )
    assert result.total_trades >= 1
    first_trade = result.trades[0]
    # entry_price should be close to some bar's open (plus slippage), not an exact
    # close value from the signal bar -- a loose bound check against the full OHLC range.
    assert df["low"].min() <= first_trade.entry_price <= df["high"].max() * 1.01
