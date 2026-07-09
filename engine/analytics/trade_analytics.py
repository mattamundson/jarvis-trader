"""Trade analytics calculations for JARVIS TRADER."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class TradeAnalytics:
    """Aggregated trade performance metrics."""

    sharpe_ratio: float
    profit_factor: float
    max_drawdown_pct: float
    win_rate: float
    expectancy: float
    total_trades: int
    total_pnl: float
    avg_win: float
    avg_loss: float
    best_trade: float
    worst_trade: float


def calculate_analytics(trades: list[dict]) -> TradeAnalytics:
    """
    Calculate all analytics from a list of trade dicts.
    Each trade dict must have 'pnl' key (P&L in dollars).
    """
    if not trades:
        return TradeAnalytics(
            sharpe_ratio=0.0,
            profit_factor=0.0,
            max_drawdown_pct=0.0,
            win_rate=0.0,
            expectancy=0.0,
            total_trades=0,
            total_pnl=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            best_trade=0.0,
            worst_trade=0.0,
        )

    total_pnl = sum(t.get("pnl", 0) for t in trades)
    total_trades = len(trades)

    pnls = [t.get("pnl", 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    best_trade = max(pnls) if pnls else 0.0
    worst_trade = min(pnls) if pnls else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0
    expectancy = (total_pnl / total_trades) if total_trades > 0 else 0.0

    daily_returns = _calculate_daily_returns(trades)
    sharpe = calculate_sharpe_ratio(daily_returns)

    equity_curve = _build_equity_curve(trades)
    drawdown = calculate_max_drawdown(equity_curve)

    profit_factor = calculate_profit_factor(trades)

    return TradeAnalytics(
        sharpe_ratio=sharpe,
        profit_factor=profit_factor,
        max_drawdown_pct=drawdown,
        win_rate=win_rate,
        expectancy=expectancy,
        total_trades=total_trades,
        total_pnl=total_pnl,
        avg_win=avg_win,
        avg_loss=avg_loss,
        best_trade=best_trade,
        worst_trade=worst_trade,
    )


def calculate_sharpe_ratio(daily_returns: list[float], risk_free_rate: float = 0.0) -> float:
    """
    Annualized Sharpe ratio from daily returns.
    Returns 0.0 if insufficient data or zero std dev.
    """
    if not daily_returns or len(daily_returns) < 2:
        return 0.0

    mean_return = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_return) ** 2 for r in daily_returns) / len(daily_returns)
    std_dev = math.sqrt(variance)

    if std_dev == 0.0:
        # float("inf") is not JSON-serializable via FastAPI's JSONResponse; use sentinel 9999.0
        return 9999.0 if mean_return > 0 else 0.0

    daily_sharpe = (mean_return - risk_free_rate) / std_dev
    annualized_sharpe = daily_sharpe * math.sqrt(252)
    return annualized_sharpe


def calculate_profit_factor(trades: list[dict]) -> float:
    """
    Gross profit / abs(gross loss).
    Returns 9999.0 (sentinel for infinity) if no losses, 0.0 if no wins and has losses.
    float("inf") is not JSON-serializable via FastAPI's JSONResponse, so we cap it.
    """
    if not trades:
        return 0.0

    pnls = [t.get("pnl", 0) for t in trades]
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = sum(p for p in pnls if p < 0)

    if gross_loss == 0.0:
        return 9999.0 if gross_profit > 0 else 0.0

    if gross_profit == 0.0:
        return 0.0

    return abs(gross_profit / gross_loss)


# Fallback starting-capital floor for the max-drawdown denominator. Mirrors
# engine/config.py's INITIAL_CAPITAL (10_000.0 paper-account default) and
# dashboard/lib/honestTrades.ts's DEFAULT_STARTING_CAPITAL. Kept as a local
# constant rather than importing engine.config: this module is intentionally
# dependency-free (stdlib-only), and calculate_analytics()'s equity curve
# (see _build_equity_curve) always starts at cumulative P&L of 0.0, never a
# real account balance, so the denominator needs a sane floor independent of
# settings plumbing.
DEFAULT_STARTING_CAPITAL = 10_000.0


def calculate_max_drawdown(equity_curve: list[float]) -> float:
    """
    Max drawdown as percentage from peak, floored at DEFAULT_STARTING_CAPITAL.

    T0-03 root cause: equity_curve[0] is frequently a trivial value near zero
    (calculate_analytics feeds this a cumulative-P&L curve starting at 0.0,
    not an actual account balance -- see _build_equity_curve). Using that raw
    value as the *denominator* let a small early win (e.g. +$50) understate
    the true capital base, so a later large-dollar loss divided into it
    produced mathematically-valid-but-economically-meaningless percentages
    >1000% (observed 1276%-1982% on live data). The running peak tracker
    itself is untouched (it must reflect the curve's real high-water mark,
    not the floor); only the percentage *denominator* is floored at
    max(peak, DEFAULT_STARTING_CAPITAL), matching the already-reviewed
    dashboard fix in honestTrades.ts. The final percentage is additionally
    clamped to [0, 100] as a hard invariant -- a drawdown can never exceed
    100% of peak equity in a well-formed result.
    Returns 0.0 if no data or monotonic up.
    """
    if not equity_curve or len(equity_curve) < 2:
        return 0.0

    peak = equity_curve[0]
    max_dd = 0.0

    for equity in equity_curve[1:]:
        if equity > peak:
            peak = equity
        denom = max(peak, DEFAULT_STARTING_CAPITAL)
        drawdown = (peak - equity) / denom if denom > 0 else 0.0
        max_dd = max(max_dd, drawdown)

    return min(max_dd * 100, 100.0)


def calculate_win_rate(trades: list[dict]) -> float:
    """
    Percentage of winning trades.
    Returns 0.0 if no trades.
    """
    if not trades:
        return 0.0

    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return (wins / len(trades)) * 100


def calculate_expectancy(trades: list[dict]) -> float:
    """
    Average expected profit per trade.
    Returns 0.0 if no trades.
    """
    if not trades:
        return 0.0

    total_pnl = sum(t.get("pnl", 0) for t in trades)
    return total_pnl / len(trades)


def _calculate_daily_returns(trades: list[dict]) -> list[float]:
    """
    Aggregate trades by date and calculate daily returns.
    Supports 'date', 'timestamp', 'exit_time', or 'entry_time' keys.
    ISO datetime strings are truncated to date-only (YYYY-MM-DD).
    """
    if not trades:
        return []

    daily_pnl: dict[str, float] = {}
    for trade in trades:
        date_key = (
            trade.get("date")
            or trade.get("timestamp")
            or trade.get("exit_time")
            or trade.get("entry_time")
        )
        if date_key:
            if isinstance(date_key, str) and len(date_key) > 10:
                date_key = date_key[:10]  # "2026-04-03T22:12:52+00:00" → "2026-04-03"
            daily_pnl[date_key] = daily_pnl.get(date_key, 0.0) + trade.get("pnl", 0)

    return list(daily_pnl.values())


def _build_equity_curve(trades: list[dict]) -> list[float]:
    """Build cumulative equity curve from trades."""
    if not trades:
        return []

    equity = 0.0
    curve = [equity]
    for trade in trades:
        pnl = trade.get("pnl", 0)
        equity += pnl
        curve.append(equity)
    return curve
