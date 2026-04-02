"""
JARVIS TRADER — Backtest Metrics
All metric computation functions for BacktestResult.
Extracted from backtester.py to keep file sizes within the 400-line guideline.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from backtest.trade_manager import BacktestResult, Trade


def compute_returns_and_drawdown(result: BacktestResult) -> None:
    """Compute basic return metrics and max drawdown."""
    equity = np.array(result.equity_curve)
    if len(equity) > 1:
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / peak
        result.max_drawdown_pct = float(abs(dd.min()))
        result.max_drawdown_dollars = float(abs((equity - peak).min()))


def compute_sharpe_sortino(result: BacktestResult) -> None:
    """Compute Sharpe and Sortino ratios from equity curve."""
    equity = np.array(result.equity_curve)
    if len(equity) <= 2:
        return
    daily_returns = np.diff(equity) / equity[:-1]
    daily_returns = daily_returns[~np.isnan(daily_returns)]
    if len(daily_returns) <= 1 or daily_returns.std() <= 0:
        return
    result.sharpe_ratio = float((daily_returns.mean() / daily_returns.std()) * np.sqrt(252))
    downside = daily_returns[daily_returns < 0]
    if len(downside) > 1:
        downside_std = downside.std()
        if downside_std > 0:
            result.sortino_ratio = float((daily_returns.mean() / downside_std) * np.sqrt(252))


def compute_extended_metrics(result: BacktestResult) -> None:
    """Compute extended metrics (Calmar, Expectancy, Recovery, Payoff)."""
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
    """Compute long vs short statistics."""
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
    """Compute regime-based statistics."""
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


def calculate_metrics(result: BacktestResult) -> BacktestResult:
    """Fill in all metrics from the trades list."""
    trades = result.trades
    if not trades:
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
    result.total_return_pct = result.total_pnl / result.initial_capital

    result.avg_win = result.gross_profit / len(wins) if wins else 0.0
    result.avg_loss = result.gross_loss / len(losses) if losses else 0.0
    result.avg_win_loss_ratio = (
        abs(result.avg_win / result.avg_loss) if result.avg_loss != 0 else 0.0
    )

    # Max drawdown from equity curve
    equity = np.array(result.equity_curve)
    if len(equity) > 1:
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / peak
        result.max_drawdown_pct = float(abs(dd.min()))
        result.max_drawdown_dollars = float(abs((equity - peak).min()))

    # Sharpe and Sortino from daily equity curve returns
    if len(equity) > 2:
        daily_returns = np.diff(equity) / equity[:-1]
        daily_returns = daily_returns[~np.isnan(daily_returns)]

        if len(daily_returns) > 1 and daily_returns.std() > 0:
            result.sharpe_ratio = float((daily_returns.mean() / daily_returns.std()) * np.sqrt(252))
            downside = daily_returns[daily_returns < 0]
            if len(downside) > 1:
                downside_std = downside.std()
                if downside_std > 0:
                    result.sortino_ratio = float(
                        (daily_returns.mean() / downside_std) * np.sqrt(252)
                    )

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

    # Delegate to helper functions
    compute_returns_and_drawdown(result)
    compute_sharpe_sortino(result)
    compute_extended_metrics(result)
    compute_direction_breakdown(result, trades)
    compute_regime_breakdown(result, trades)
    compute_duration_metrics(result, trades)

    return result
