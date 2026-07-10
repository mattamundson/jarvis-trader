"""
Strategy-enhancement overlay CANDIDATES for the live SMA trend strategy
(engine/backtest/trend_signals.py: SMA(fast,slow) golden/death cross +
ATR trailing stop, currently SMA(50,200)+2.0xATR on MES 1h /
SMA(50,120)+2.0xATR on MGC 1h).

BUILD-AND-BACKTEST ONLY. Nothing here is imported by the live signal path
(engine/agents/*.py) or by trend_signals.py itself, and none of the three
functions below mutate SMA_TREND_PARAMS or any other live parameter. Each
is a standalone, independently backtestable layer that could later be wired
in with minimal glue (see run_strategy_overlay_backtest.py for the harness
that measures each overlay's marginal effect against the unmodified
baseline on the same historical MES 1h data used to validate the live
strategy).

Provenance: derived from a 793-record trading-alpha bookmark dossier swept
2026-07-07 (see memory/project_xbookmark_pipeline_fix_2026_07_06.md). Three
candidates, ranked as concrete evidence-based extensions of primitives
already live in this codebase:

  1. apply_regime_filter()     -- macro trend confirmation. Only take a
                                   golden-cross LONG entry when price is
                                   also above a longer-horizon (default
                                   200-session) SMA. Pure post-filter on
                                   entry_signal -- output stays compatible
                                   with Backtester.run() unchanged.

  2. rank_by_payout_ratio()    -- re-scores a set of already-backtested
                                   strategy variants by payoff_ratio
                                   (avg_win / avg_loss) rather than
                                   win_rate. Dossier evidence: top-decile
                                   systematic traders had LOWER win rates
                                   but 3.5-6x better payout ratios. Payoff
                                   ratio is already a computed field on
                                   BacktestResult (trade_manager.py) -- this
                                   is a ranking function over existing
                                   results, not a new metric.

  3. simulate_atr_extension_trim() -- systematic partial profit-take when
                                   price extends more than N x ATR beyond
                                   the fast SMA (SMA50 for the champion
                                   config). Reuses the ATR primitive already
                                   computed for the stop-loss calc; adds a
                                   second, independent use of it. Backtester
                                   has no notion of a dynamic (non-entry-
                                   anchored) partial-exit trigger, so this
                                   ships as a small self-contained bar-by-bar
                                   simulator that mirrors trend_signals'
                                   entry/exit formulas exactly and produces
                                   a standard trade_manager.BacktestResult
                                   (via metrics.calculate_metrics) so its
                                   output is directly comparable to the
                                   Backtester-produced baseline.

No look-ahead: the regime SMA is computed from daily closes and shifted one
session before being forward-filled onto intraday bars (a session's own
close isn't known until it ends); the ATR-extension simulator fills entries
at the NEXT bar's open after a signal bar, matching Backtester's own
pending-entry convention (see backtester.py:_process_pending_entry).
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from backtest.metrics import calculate_metrics
from backtest.trade_manager import BacktestResult, Trade
from backtest.trend_signals import _wilder_atr

__all__ = [
    "compute_regime_sma",
    "apply_regime_filter",
    "rank_by_payout_ratio",
    "simulate_atr_extension_trim",
]


# ---------------------------------------------------------------------------
# 1. 200-session SMA regime overlay
# ---------------------------------------------------------------------------


def compute_regime_sma(df: pd.DataFrame, window: int = 200) -> pd.Series:
    """Macro-horizon SMA (default 200 sessions -- "200-day SMA") resampled
    from the strategy's native (intraday) timeframe and point-in-time
    aligned back onto df's index.

    Point-in-time discipline: a session's close-derived SMA is not knowable
    until that session ends, so the daily SMA series is shifted forward one
    session (`.shift(1)`) before being merged back onto intraday bars via
    an as-of backward join. A bar at 10:00 on day T therefore sees the SMA
    computed through day T-1's close, never day T's own (still-forming) close.
    """
    daily_close = df["close"].resample("1D").last().dropna()
    regime_sma = daily_close.rolling(window).mean().shift(1)
    regime_sma.name = "regime_sma"

    daily_df = regime_sma.reset_index()
    daily_df.columns = ["ts", "regime_sma"]
    bars = pd.DataFrame({"ts": df.index})

    merged = pd.merge_asof(
        bars.sort_values("ts"),
        daily_df.sort_values("ts"),
        on="ts",
        direction="backward",
    )
    return pd.Series(merged["regime_sma"].to_numpy(), index=df.index, name="regime_sma")


def apply_regime_filter(
    df_sig: pd.DataFrame,
    regime_window: int = 200,
    entry_col: str = "entry_signal",
) -> pd.DataFrame:
    """Post-filter a trend_signals.generate_sma_trend_signals() output:
    suppress ENTRY_NOW -> NO_TRADE on any bar where price is below the
    macro-horizon regime SMA. Layered on top of the existing signal, not a
    replacement -- every other column (exit_signal, trailing_stop, atr,
    bias, regime) is left untouched, so the golden-cross timing and ATR
    trailing-stop exit logic are identical to the unfiltered baseline.

    Returns a copy of df_sig fully compatible with Backtester.run().

    Fail-safe default: bars where the regime SMA isn't yet defined
    (insufficient warmup, < regime_window sessions of history) suppress
    entries rather than allow them -- "no macro confirmation" reads as
    "no confirmed regime," matching the conservative posture of every other
    NO_TRADE gate in signals.py (_force_no_trade convention).
    """
    df_out = df_sig.copy()
    regime_sma = compute_regime_sma(df_out, window=regime_window)
    df_out["regime_sma"] = regime_sma

    is_entry = df_out[entry_col] == "ENTRY_NOW"
    regime_confirmed = (df_out["close"] > df_out["regime_sma"]).fillna(False)
    suppress = is_entry & ~regime_confirmed

    df_out.loc[suppress, entry_col] = "NO_TRADE"
    for col in ("stop_level", "target_1", "target_2", "target_3"):
        if col in df_out.columns:
            df_out.loc[suppress, col] = np.nan

    return df_out


# ---------------------------------------------------------------------------
# 2. Payout-ratio-over-win-rate ranking
# ---------------------------------------------------------------------------


def rank_by_payout_ratio(variants: Dict[str, BacktestResult]) -> List[dict]:
    """Re-rank a set of already-backtested strategy variants by
    payoff_ratio (avg_win / avg_loss, BacktestResult.payoff_ratio) instead
    of win_rate.

    Dossier evidence (793-record bookmark sweep, 2026-07-07): top-decile
    systematic traders had LOWER win rates but 3.5-6x better payout ratios
    than the median trader -- selecting for "wins big when right, loses
    small when wrong" beats selecting for "right more often." This function
    doesn't compute a new metric (payoff_ratio is already populated by
    metrics.calculate_metrics on every BacktestResult); it re-orders an
    existing set of results and exposes the win-rate vs payout-ratio rank
    delta so a reversal (a variant that wins on payout despite losing on
    win rate) is visible at a glance.

    Args:
        variants: {variant_name: BacktestResult}, e.g. the baseline and
            each overlay's backtest output from run_strategy_overlay_backtest.py,
            or any other set of already-computed strategy variant results
            (parameter-sweep ranks, family comparisons, etc).

    Returns: list of dicts, one per variant, sorted by payout_rank (best
        payoff_ratio first). Each row carries both win_rate_rank and
        payout_rank plus rank_delta = win_rate_rank - payout_rank (positive
        = this variant is undervalued by a win-rate-only ranking).
    """
    rows = []
    for name, result in variants.items():
        rows.append(
            {
                "variant": name,
                "trades": result.total_trades,
                "win_rate": round(result.win_rate, 4),
                "payoff_ratio": round(result.payoff_ratio, 3),
                "profit_factor": round(result.profit_factor, 3),
                "expectancy": round(result.expectancy, 2),
                "sharpe_ratio": round(result.sharpe_ratio, 3),
                "max_drawdown_pct": round(result.max_drawdown_pct, 4),
                "total_return_pct": round(result.total_return_pct, 4),
            }
        )

    if not rows:
        return []

    for i, r in enumerate(sorted(rows, key=lambda r: r["win_rate"], reverse=True), start=1):
        r["win_rate_rank"] = i
    for i, r in enumerate(sorted(rows, key=lambda r: r["payoff_ratio"], reverse=True), start=1):
        r["payout_rank"] = i

    for r in rows:
        r["rank_delta"] = r["win_rate_rank"] - r["payout_rank"]

    return sorted(rows, key=lambda r: r["payout_rank"])


# ---------------------------------------------------------------------------
# 3. ATR-extension profit-trim
# ---------------------------------------------------------------------------


def simulate_atr_extension_trim(
    df: pd.DataFrame,
    symbol: str,
    multiplier: float,
    fast: int = 50,
    slow: int = 200,
    atr_trail_mult: float = 2.0,
    trim_atr_mult: float = 3.0,
    trim_pct: float = 0.5,
    initial_capital: float = 50_000.0,
    risk_per_trade: float = 0.01,
    commission_per_contract: float = 0.62,
    slippage_ticks: float = 2.0,
    tick_size: float = 0.25,
    atr_period: int = 14,
) -> BacktestResult:
    """Self-contained long-only bar-by-bar simulator: identical entry timing
    (golden cross, SMA(fast,slow)) and identical ATR trailing-stop exit
    logic to trend_signals.generate_sma_trend_signals(), PLUS a systematic
    partial profit-take: the first time price extends >= trim_atr_mult x
    ATR beyond the fast SMA while a trade is open, trim_pct of the position
    is closed at that extension level, and the remainder continues to ride
    the same ATR trailing stop to its normal exit.

    Reimplemented as a standalone loop (not routed through Backtester)
    because Backtester's target exits are static price levels fixed at
    entry time (target_1/2/3 = entry +/- N*ATR); this overlay's trigger is
    dynamic and re-evaluated every bar (current SMA + current ATR), which
    the existing target-exit machinery has no way to express. Entry/exit
    formulas below intentionally mirror trend_signals.py's SMA/ATR/cross
    logic bar-for-bar so the two are apples-to-apples comparable; only the
    exit/sizing state machine differs (partial-exit support).

    No look-ahead: a golden-cross signal detected at bar i is filled at bar
    i+1's open (same convention as backtester.py:_process_pending_entry).
    The extension trigger and the trailing-stop/death-cross exit are each
    evaluated using only that bar's own high/low/close -- never a future bar.

    Returns a trade_manager.BacktestResult with all metrics (profit_factor,
    win_rate, payoff_ratio, sharpe_ratio, max_drawdown_pct, ...) filled in
    via metrics.calculate_metrics(), directly comparable to Backtester.run()
    output for the unmodified baseline.
    """
    df = df.copy()
    sma_f = df["close"].rolling(fast).mean()
    sma_s = df["close"].rolling(slow).mean()
    atr = _wilder_atr(df["high"], df["low"], df["close"], atr_period)

    above = (sma_f > sma_s).fillna(False).to_numpy()
    prev_above = np.roll(above, 1)
    prev_above[0] = False
    prev_sma_s_valid = sma_s.shift(1).notna().to_numpy()
    cross_up = above & ~prev_above & prev_sma_s_valid
    cross_dn = ~above & prev_above & prev_sma_s_valid

    idx = df.index
    n = len(df)
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    sma_f_arr = sma_f.to_numpy(dtype=float)
    atr_arr = atr.to_numpy(dtype=float)

    trades: List[Trade] = []
    equity = initial_capital
    equity_curve: List[float] = []

    pending_entry = False  # signal fired on prior bar, fill at this bar's open
    in_trade = False
    entry_price = 0.0
    stop_price = 0.0
    current_trail = 0.0
    total_contracts = 0
    remaining_contracts = 0
    trimmed = False
    trade_pnl = 0.0
    entry_date = None
    entry_bar = 0
    entry_atr = 0.0

    for i in range(n):
        ts = idx[i]

        if pending_entry and not in_trade:
            pending_entry = False
            raw_entry = opens[i]
            fill_entry = raw_entry + slippage_ticks * tick_size  # long entry pays up
            sig_atr = entry_atr
            init_stop = fill_entry - atr_trail_mult * sig_atr
            stop_dist = fill_entry - init_stop
            if stop_dist > 0 and not pd.isna(sig_atr):
                risk_dollars = equity * risk_per_trade
                contracts = max(1, min(int(risk_dollars / (stop_dist * multiplier)), 50))
                entry_price = fill_entry
                stop_price = init_stop
                current_trail = init_stop
                total_contracts = contracts
                remaining_contracts = contracts
                trimmed = False
                trade_pnl = 0.0
                entry_date = ts
                entry_bar = i
                in_trade = True

        elif in_trade:
            atr_i = atr_arr[i]
            sma_f_i = sma_f_arr[i]
            high_i = highs[i]
            low_i = lows[i]
            close_i = closes[i]

            # Update trailing stop (only moves up) -- identical formula to trend_signals.
            if not pd.isna(atr_i):
                new_trail = close_i - atr_trail_mult * atr_i
                if new_trail > current_trail:
                    current_trail = new_trail

            # Extension trim: fire once, at the touch price, if untouched so far.
            if not trimmed and not pd.isna(atr_i) and not pd.isna(sma_f_i) and remaining_contracts > 1:
                trigger_level = sma_f_i + trim_atr_mult * atr_i
                if high_i >= trigger_level:
                    trim_contracts = max(1, int(round(total_contracts * trim_pct)))
                    trim_contracts = min(trim_contracts, remaining_contracts - 1)
                    if trim_contracts > 0:
                        pnl = trim_contracts * (trigger_level - entry_price) * multiplier
                        cost = commission_per_contract * trim_contracts
                        trade_pnl += pnl - cost
                        equity += pnl - cost
                        remaining_contracts -= trim_contracts
                        trimmed = True

            stop_touched = low_i <= current_trail
            death_cross = bool(cross_dn[i])
            if stop_touched or death_cross:
                exit_price = current_trail if stop_touched else close_i
                pnl = remaining_contracts * (exit_price - entry_price) * multiplier
                cost = commission_per_contract * remaining_contracts
                trade_pnl += pnl - cost
                equity += pnl - cost

                trades.append(
                    Trade(
                        entry_date=entry_date,
                        symbol=symbol,
                        direction="long",
                        entry_price=round(entry_price, 4),
                        stop_price=round(stop_price, 4),
                        target_1=round(entry_price + trim_atr_mult * entry_atr, 4)
                        if not pd.isna(entry_atr)
                        else entry_price,
                        target_2=entry_price,
                        contracts=total_contracts,
                        multiplier=multiplier,
                        exit_date=ts,
                        exit_price=round(exit_price, 4),
                        pnl=trade_pnl,
                        exit_reason="atr_trim+trail" if trimmed else ("trailing_stop" if stop_touched else "death_cross"),
                        holding_bars=i - entry_bar,
                        regime="TRENDING_BULL",
                        bias="STRONG_BULL",
                    )
                )
                in_trade = False
                remaining_contracts = 0

        # Queue next entry off this bar's cross (evaluated after any exit processing above,
        # so a same-bar death-cross-then-golden-cross flip is not both entered and exited).
        if not in_trade and not pending_entry and cross_up[i]:
            pending_entry = True
            entry_atr = atr_arr[i]

        equity_curve.append(equity)

    result = BacktestResult(
        symbol=symbol,
        start_date=str(df.index.min().date()),
        end_date=str(df.index.max().date()),
        initial_capital=initial_capital,
        final_capital=equity,
        trades=trades,
        equity_curve=equity_curve,
    )
    return calculate_metrics(result)
