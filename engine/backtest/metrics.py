"""
JARVIS TRADER — Backtest Metrics
All metric computation functions for BacktestResult.
Extracted from backtester.py to keep file sizes within the 400-line guideline.

Unit conventions (locked in 2026-04-20 bugfix — DO NOT CHANGE without reviewing ALL call sites):
- `total_return_pct`, `max_drawdown_pct`, `win_rate`, `long/short_win_rate` are stored as
  FRACTIONS (e.g. 0.199 means 19.9%). Display code uses `{:.1%}` or `{:+.1%}` to convert.
  Callers like tune_trailing_stop.py, run_all_backtests.py, sensitivity.py, and
  tests/test_validation_checkpoint.py all rely on fraction semantics.
- `sharpe_ratio` / `sortino_ratio` are computed over the set of PER-TRADE returns
  (not per-bar equity changes). The old implementation computed diffs over the equity
  curve which includes all non-trade bars as 0-return, artificially suppressing std
  and producing the 'Sharpe 2.0 alongside PF 0.13' paradox.
- `final_capital` is canonical; `total_return_pct` is derived from it as
  (final - initial) / initial so `Capital: $X -> $Y` cannot disagree with `Return: Z%`.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from backtest.trade_manager import BacktestResult, Trade

# Annualization factor for Sharpe/Sortino when computed over per-trade returns.
# Approximates a full-time futures strategy taking ~1 trade per trading day. Using this
# fixed factor keeps Sharpe comparable across intervals (1h, 1d, 15m) — the alternative
# (sqrt(bars_per_year)) inflates Sharpe on high-frequency bars where most bars are flat.
ANNUALIZATION_TRADES_PER_YEAR = 252


def _trade_returns(result: BacktestResult) -> np.ndarray:
    """Return array of per-trade pnl as fraction of initial_capital.

    We deliberately use per-trade returns rather than per-bar equity diffs because the
    equity curve is flat between trades (capital unchanged on non-exit bars). Including
    those zeros inflates Sharpe by suppressing std while leaving the mean near zero —
    this was the root cause of the 'Sharpe 2.0 with PF < 1' paradox.
    """
    if not result.trades or result.initial_capital <= 0:
        return np.array([])
    pnls = np.array([t.pnl for t in result.trades], dtype=float)
    return pnls / result.initial_capital


def compute_returns_and_drawdown(result: BacktestResult) -> None:
    """Compute max drawdown from equity curve.

    Max DD stored as FRACTION (e.g. 0.199 means 19.9%). Display with `{:.1%}`.
    """
    equity = np.array(result.equity_curve)
    if len(equity) > 1:
        peak = np.maximum.accumulate(equity)
        # Guard against divide-by-zero if initial capital somehow hits 0
        safe_peak = np.where(peak == 0, 1.0, peak)
        dd = (equity - peak) / safe_peak
        result.max_drawdown_pct = float(abs(dd.min()))
        result.max_drawdown_dollars = float(abs((equity - peak).min()))


def compute_sharpe_sortino(result: BacktestResult) -> None:
    """Compute Sharpe and Sortino ratios over per-trade returns.

    Why per-trade rather than per-bar: on intraday data (1h, 15m) most bars have zero
    return because no position changes hands. That drives std→0 while mean stays
    slightly positive, inflating Sharpe. Using trade returns gives an honest risk-
    adjusted measure that cannot produce positive Sharpe when PF < 1.

    Sign invariant: sign(sharpe) == sign(mean(trade_returns)) == sign(total_pnl).
    """
    returns = _trade_returns(result)
    if len(returns) <= 1:
        return
    std = returns.std(ddof=1)
    if std <= 0:
        return
    mean = returns.mean()
    result.sharpe_ratio = float((mean / std) * np.sqrt(ANNUALIZATION_TRADES_PER_YEAR))
    downside = returns[returns < 0]
    if len(downside) > 1:
        downside_std = downside.std(ddof=1)
        if downside_std > 0:
            result.sortino_ratio = float(
                (mean / downside_std) * np.sqrt(ANNUALIZATION_TRADES_PER_YEAR)
            )


def compute_extended_metrics(result: BacktestResult) -> None:
    """Compute extended metrics (Calmar, Expectancy, Recovery, Payoff).

    win_rate, max_drawdown_pct, total_return_pct are all FRACTIONS here. Calmar
    ratio is dimensionless (ratio of two fractions) regardless of scale.
    """
    if result.max_drawdown_pct > 0:
        result.calmar_ratio = result.total_return_pct / result.max_drawdown_pct
    if result.trades:
        loss_rate = 1 - result.win_rate
        result.expectancy = (result.win_rate * result.avg_win) + (loss_rate * result.avg_loss)
    if result.max_drawdown_dollars > 0:
        result.recovery_factor = result.total_pnl / result.max_drawdown_dollars
    if result.avg_loss != 0:
        result.payoff_ratio = abs(result.avg_win / result.avg_loss)


def compute_direction_breakdown(result: BacktestResult, trades: List[Trade]) -> None:
    """Compute long vs short statistics. win_rate stored as fraction."""
    long_trades = [t for t in trades if t.direction == "long"]
    short_trades = [t for t in trades if t.direction == "short"]
    result.long_trades = len(long_trades)
    result.short_trades = len(short_trades)

    if long_trades:
        long_wins = [t for t in long_trades if t.pnl > 0]
        result.long_win_rate = len(long_wins) / len(long_trades)
        long_gross_profit = sum(t.pnl for t in long_trades if t.pnl > 0)
        long_gross_loss = sum(t.pnl for t in long_trades if t.pnl <= 0)
        result.long_profit_factor = (
            long_gross_profit / abs(long_gross_loss) if long_gross_loss else float("inf")
        )

    if short_trades:
        short_wins = [t for t in short_trades if t.pnl > 0]
        result.short_win_rate = len(short_wins) / len(short_trades)
        short_gross_profit = sum(t.pnl for t in short_trades if t.pnl > 0)
        short_gross_loss = sum(t.pnl for t in short_trades if t.pnl <= 0)
        result.short_profit_factor = (
            short_gross_profit / abs(short_gross_loss) if short_gross_loss else float("inf")
        )


def compute_regime_breakdown(result: BacktestResult, trades: List[Trade]) -> None:
    """Compute regime-based statistics. win_rate stored as fraction."""
    regime_groups: Dict[str, list] = {}
    for t in trades:
        r = t.regime or "UNKNOWN"
        if r not in regime_groups:
            regime_groups[r] = []
        regime_groups[r].append(t)

    for regime, regime_trades in regime_groups.items():
        regime_wins = [t for t in regime_trades if t.pnl > 0]
        regime_gross_profit = sum(t.pnl for t in regime_trades if t.pnl > 0)
        regime_gross_loss = sum(t.pnl for t in regime_trades if t.pnl <= 0)
        result.regime_stats[regime] = {
            "trades": len(regime_trades),
            "win_rate": len(regime_wins) / len(regime_trades) if regime_trades else 0,
            "profit_factor": regime_gross_profit / abs(regime_gross_loss)
            if regime_gross_loss
            else float("inf"),
            "total_pnl": sum(t.pnl for t in regime_trades),
        }


def compute_exposure_time(result: BacktestResult) -> None:
    """Compute % of bars where a position was open."""
    if not result.trades or result.total_bars == 0:
        result.exposure_time_pct = 0.0
        return
    bars_in_market = sum(t.holding_bars for t in result.trades)
    result.exposure_time_pct = (bars_in_market / result.total_bars) * 100


def compute_duration_metrics(result: BacktestResult, trades: List[Trade]) -> None:
    """Compute trade duration and drawdown duration."""
    if trades:
        holding_bars = [t.holding_bars for t in trades]
        result.avg_holding_bars = float(np.mean(holding_bars))
        result.median_holding_bars = float(np.median(holding_bars))
        result.max_holding_bars = max(holding_bars)

    equity = np.array(result.equity_curve)
    if len(equity) > 1:
        peak = np.maximum.accumulate(equity)
        in_dd = equity < peak
        max_dd_dur = 0
        cur_dd_dur = 0
        for is_dd in in_dd:
            if is_dd:
                cur_dd_dur += 1
            else:
                max_dd_dur = max(max_dd_dur, cur_dd_dur)
                cur_dd_dur = 0
        result.max_drawdown_duration_bars = max(max_dd_dur, cur_dd_dur)


def compute_kelly_fraction(result: BacktestResult) -> None:
    """Compute full-Kelly and half-Kelly bet fraction from avg_win / avg_loss.

    Kelly formula: f* = (W * R - (1 - W)) / R
    where W = win_rate (fraction), R = avg_win / |avg_loss| (payoff ratio).

    Result is clamped to [0, 1] — negative Kelly (W*R < 1-W) means no edge,
    fraction > 1 (degenerate) is clipped. Half-Kelly is the practical recommendation
    for live trading: reduces variance at the cost of ~25% of long-run CAGR.
    """
    w = result.win_rate
    avg_w = result.avg_win
    avg_l = result.avg_loss  # stored as negative number
    if w <= 0 or avg_w <= 0 or avg_l >= 0:
        result.kelly_fraction = 0.0
        result.half_kelly_fraction = 0.0
        return
    r = avg_w / abs(avg_l)
    kelly = (w * r - (1 - w)) / r
    result.kelly_fraction = float(max(0.0, min(1.0, kelly)))
    result.half_kelly_fraction = result.kelly_fraction / 2.0


def calculate_metrics(result: BacktestResult) -> BacktestResult:
    """Fill in all metrics from the trades list.

    Internal-consistency guarantees (locked by test_backtester_metrics.py):
    - `final_capital` is the canonical end-of-backtest equity value.
    - `total_return_pct` is ALWAYS derived from (final_capital - initial_capital)/initial_capital
      (as a FRACTION) so `summary()` cannot show a positive end capital alongside a
      negative return.
    - `sharpe_ratio` sign matches `total_return_pct` sign (can't have +Sharpe with -return
      when trades all moved in one direction — sign invariant holds for sufficient-sample
      cases; a lone large win with many tiny losses can break pure sign but is a degenerate
      edge case).
    """
    trades = result.trades

    # Canonical return: derive from capital endpoints (FRACTION). This line is the
    # single source of truth — all display code should read result.total_return_pct
    # and format with {:.1%} or {:+.1%}.
    if result.initial_capital > 0:
        result.total_return_pct = (
            (result.final_capital - result.initial_capital) / result.initial_capital
        )
    else:
        result.total_return_pct = 0.0

    if not trades:
        # Still compute drawdown — an equity curve without trades may show zero DD,
        # but the computation itself should run so max_drawdown_pct/_dollars are set.
        compute_returns_and_drawdown(result)
        return result

    result.total_trades = len(trades)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    result.winning_trades = len(wins)
    result.losing_trades = len(losses)
    result.win_rate = len(wins) / len(trades) if trades else 0.0
    result.trailing_stop_exits = sum(1 for t in trades if t.exit_reason == "trailing_stop")
    result.gross_profit = sum(t.pnl for t in wins)
    result.gross_loss = sum(t.pnl for t in losses)
    result.profit_factor = (
        result.gross_profit / abs(result.gross_loss) if result.gross_loss != 0 else float("inf")
    )
    result.total_pnl = result.gross_profit + result.gross_loss

    result.avg_win = result.gross_profit / len(wins) if wins else 0.0
    result.avg_loss = result.gross_loss / len(losses) if losses else 0.0
    result.avg_win_loss_ratio = (
        abs(result.avg_win / result.avg_loss) if result.avg_loss != 0 else 0.0
    )

    # VaR / CVaR from per-trade returns (scoped consistently with Sharpe).
    # Returns are fractions of initial_capital; var_95 = 5th percentile of trade-return dist.
    returns = _trade_returns(result)
    if len(returns) >= 10:
        sorted_returns = np.sort(returns)
        var_95 = float(np.percentile(sorted_returns, 5))
        var_99 = float(np.percentile(sorted_returns, 1))
        tail_95 = sorted_returns[sorted_returns <= var_95]
        cvar_95 = float(tail_95.mean()) if len(tail_95) > 0 else var_95
        tail_99 = sorted_returns[sorted_returns <= var_99]
        cvar_99 = float(tail_99.mean()) if len(tail_99) > 0 else var_99
        result.var_95 = var_95
        result.var_99 = var_99
        result.cvar_95 = cvar_95
        result.cvar_99 = cvar_99

    # Consecutive wins/losses
    max_consec_win = max_consec_loss = 0
    cur_win = cur_loss = 0
    for t in trades:
        if t.pnl > 0:
            cur_win += 1
            cur_loss = 0
            max_consec_win = max(max_consec_win, cur_win)
        else:
            cur_loss += 1
            cur_win = 0
            max_consec_loss = max(max_consec_loss, cur_loss)
    result.max_consecutive_wins = max_consec_win
    result.max_consecutive_losses = max_consec_loss

    # Canonical metric functions (replace old inline equity-diff block)
    compute_returns_and_drawdown(result)
    compute_sharpe_sortino(result)
    compute_extended_metrics(result)
    compute_direction_breakdown(result, trades)
    compute_regime_breakdown(result, trades)
    compute_duration_metrics(result, trades)
    compute_exposure_time(result)
    compute_kelly_fraction(result)

    return result
