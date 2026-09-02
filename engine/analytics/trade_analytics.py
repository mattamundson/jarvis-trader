"""Trade analytics calculations for JARVIS TRADER."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone


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
    # C3 metric-honesty pass (2026-08-18): annualization transparency. The
    # Sharpe above is annualized by the strategy's OBSERVED trade frequency
    # (not a fixed 252) whenever the trade timestamps support it; these fields
    # record what factor was used and the honest CAGR over the actual span.
    annualization_trades_per_year: float = 252.0
    cagr: float = 0.0


# Fallback annualization factor, matching engine/backtest/metrics.py
# DEFAULT_ANNUALIZATION_TRADES_PER_YEAR. Used only when the trade timestamps
# cannot support an honest observed-frequency estimate (missing dates or a
# window shorter than MIN_ANNUALIZATION_WINDOW_DAYS).
DEFAULT_ANNUALIZATION_TRADES_PER_YEAR = 252.0
MIN_ANNUALIZATION_WINDOW_DAYS = 90.0
MAX_ANNUALIZATION_TRADES_PER_YEAR = 2520.0


def _observed_annualization_trades_per_year(trades: list[dict]) -> float:
    """Observed trades-per-year from the trade dates, or the 252 fallback.

    Mirrors engine/backtest/metrics.py `_annualization_factor`: uses the
    calendar span of the trade records (n_trades / elapsed_years), falls back
    to DEFAULT_ANNUALIZATION_TRADES_PER_YEAR when the window is missing,
    unparseable, or shorter than MIN_ANNUALIZATION_WINDOW_DAYS (a sub-90-day
    record cannot be honestly annualized), and caps at
    MAX_ANNUALIZATION_TRADES_PER_YEAR.
    """
    parsed = []
    for trade in trades:
        raw = (
            trade.get("exit_time")
            or trade.get("entry_time")
            or trade.get("timestamp")
            or trade.get("date")
        )
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError):
            continue
        # Normalize to UTC-aware: the live record mixes naive and tz-aware
        # timestamps (naive rows are treated as UTC); comparing mixed naive /
        # aware datetimes raises TypeError, which crashed the honest-metrics
        # path on the real paper-trade DB (2026-08-18, verify_honest_metrics.py).
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        parsed.append(dt)
    if len(parsed) < 2:
        return DEFAULT_ANNUALIZATION_TRADES_PER_YEAR
    span_days = (max(parsed) - min(parsed)).total_seconds() / 86400.0
    if span_days < MIN_ANNUALIZATION_WINDOW_DAYS:
        return DEFAULT_ANNUALIZATION_TRADES_PER_YEAR
    tpy = len(parsed) / (span_days / 365.25)
    if tpy <= 0:
        return DEFAULT_ANNUALIZATION_TRADES_PER_YEAR
    return float(min(tpy, MAX_ANNUALIZATION_TRADES_PER_YEAR))


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

    # C3 metric-honesty pass: annualize by the OBSERVED trade frequency, not a
    # fixed 252. A strategy that closes trades on ~60 days a year was
    # previously overstated by sqrt(252/60) ≈ 2.05x.
    ann_tpy = _observed_annualization_trades_per_year(trades)
    # Sharpe over PER-TRADE returns (same convention as backtest/metrics.py
    # and dashboard/lib/honestAnnualized.ts), annualized by sqrt(trades/yr).
    # The old path fed daily-bucketed sums into a trades-per-year factor —
    # mixed denominators that inflated the live record (88 trades on ~40
    # distinct days): engine 2.59 vs honest 1.63 (2026-08-18 verification).
    trade_returns = [t.get("pnl", 0) for t in trades]
    sharpe = calculate_sharpe_ratio(
        trade_returns,
        annualization_trades_per_year=ann_tpy,
    )

    # Honest CAGR over the actual elapsed calendar span of the trade record.
    # Compounding uses (1 + total_return)^(1/years) - 1 with years derived from
    # the first/last trade timestamps, not 252 fixed periods per year.
    cagr = _calculate_cagr(trades, ann_tpy)

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
        annualization_trades_per_year=round(ann_tpy, 4),
        cagr=round(cagr, 6),
    )


def _calculate_cagr(trades: list[dict], annualization_trades_per_year: float) -> float:
    """Honest CAGR from per-trade returns over the record's actual span.

    total_return = sum(pnl) / DEFAULT_STARTING_CAPITAL (the paper-account
    notional convention used across the engine); years = n_trades /
    annualization_trades_per_year when the observed frequency is usable, else
    the 252 fallback. Returns 0.0 when the record cannot support the math
    (no trades, no capital base, or total return <= -100%).
    """
    if not trades:
        return 0.0
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    if DEFAULT_STARTING_CAPITAL <= 0:
        return 0.0
    total_return = total_pnl / DEFAULT_STARTING_CAPITAL
    if total_return <= -1.0:
        return 0.0
    n = len(trades)
    years = (
        n / annualization_trades_per_year
        if annualization_trades_per_year > 0
        else 0.0
    )
    if years <= 0:
        return 0.0
    cagr = (1.0 + total_return) ** (1.0 / years) - 1.0
    return float(cagr) if math.isfinite(cagr) else 0.0


def calculate_sharpe_ratio(
    daily_returns: list[float],
    risk_free_rate: float = 0.0,
    annualization_trades_per_year: float = DEFAULT_ANNUALIZATION_TRADES_PER_YEAR,
) -> float:
    """
    Annualized Sharpe ratio from per-period returns.

    The annualization factor is the strategy's OBSERVED periods-per-year, not
    a fixed 252 — annualizing a low-frequency series by 252 overstated Sharpe
    by sqrt(252 / actual) (C3 metric-honesty pass, 2026-08-18; mirrors
    engine/backtest/metrics.py `compute_sharpe_sortino`).
    Returns 0.0 if insufficient data or zero std dev.
    """
    if not daily_returns or len(daily_returns) < 2:
        return 0.0

    mean_return = sum(daily_returns) / len(daily_returns)
    # Sample variance (ddof=1) — matches backtest/metrics.py (`std(ddof=1)`)
    # and dashboard/lib/honestAnnualized.ts, so engine and display agree on
    # the same trade series (C3 metric-honesty pass).
    variance = sum((r - mean_return) ** 2 for r in daily_returns) / (
        len(daily_returns) - 1
    )
    std_dev = math.sqrt(variance)

    if std_dev == 0.0:
        # float("inf") is not JSON-serializable via FastAPI's JSONResponse; use sentinel 9999.0
        return 9999.0 if mean_return > 0 else 0.0

    periods = (
        annualization_trades_per_year
        if annualization_trades_per_year > 0
        else DEFAULT_ANNUALIZATION_TRADES_PER_YEAR
    )
    per_period_sharpe = (mean_return - risk_free_rate) / std_dev
    annualized_sharpe = per_period_sharpe * math.sqrt(periods)
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
                date_key = date_key[:10]  # ISO datetime -> YYYY-MM-DD
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
