"""
Jarvis-Trader Performance Metrics — Agent Scoring Calculator

Computes Sharpe ratio, maximum drawdown, win rate, average win/loss,
and profit factor from a sequence of trade returns.

Usage (per-agent or per-tier):

    from engine.backtest.perf_metrics import compute_performance, AgentReport

    returns = [0.012, -0.005, 0.008, ...]  # realized R per trade
    stats = compute_performance(returns)
    print(stats.sharpe, stats.win_rate, stats.max_drawdown)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Core stats dataclass
# ---------------------------------------------------------------------------

@dataclass
class PerformanceStats:
    sharpe: float
    max_drawdown: float        # negative value in same units as returns
    win_rate: float            # 0.0 – 1.0
    profit_factor: float       # gross_profit / abs(gross_loss)
    avg_return: float
    avg_win: float
    avg_loss: float
    trades: int
    gross_profit: float = 0.0
    gross_loss: float = 0.0


@dataclass
class AgentReport:
    agent_id: str
    tier: str
    stats: PerformanceStats
    returns: List[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core calculator
# ---------------------------------------------------------------------------

def compute_performance(
    returns: Sequence[float],
    annualization_factor: float = 252.0,
) -> PerformanceStats:
    """
    Compute performance statistics from a list of per-trade returns.

    Parameters
    ----------
    returns : sequence of float
        Realized R-multiples or % returns per completed trade.
    annualization_factor : float
        252 for daily bars, 52 for weekly, 12 for monthly.
        Default 252 assumes one signal per trading day.

    Returns
    -------
    PerformanceStats
    """
    arr = np.array(returns, dtype=float)
    trades = len(arr)

    if trades == 0:
        return PerformanceStats(
            sharpe=0.0, max_drawdown=0.0, win_rate=0.0,
            profit_factor=0.0, avg_return=0.0, avg_win=0.0,
            avg_loss=0.0, trades=0,
        )

    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if trades > 1 else 0.0
    sharpe = (mean / std * np.sqrt(annualization_factor)) if std > 0 else 0.0

    # Equity curve for drawdown
    equity = np.cumsum(arr)
    peak = np.maximum.accumulate(equity)
    max_dd = float((equity - peak).min())

    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    win_rate = float(len(wins) / trades)
    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0
    gross_profit = float(wins.sum()) if len(wins) > 0 else 0.0
    gross_loss = float(losses.sum()) if len(losses) > 0 else 0.0
    profit_factor = (
        gross_profit / abs(gross_loss)
        if gross_loss != 0
        else float("inf") if gross_profit > 0 else 0.0
    )

    return PerformanceStats(
        sharpe=round(sharpe, 4),
        max_drawdown=round(max_dd, 6),
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 4),
        avg_return=round(mean, 6),
        avg_win=round(avg_win, 6),
        avg_loss=round(avg_loss, 6),
        trades=trades,
        gross_profit=round(gross_profit, 6),
        gross_loss=round(gross_loss, 6),
    )


# ---------------------------------------------------------------------------
# Per-agent scoring (groups alerts by agent_id / tier tag)
# ---------------------------------------------------------------------------

def compute_agent_reports(
    trade_log: List[Dict],
    group_by: str = "tier",
) -> Dict[str, AgentReport]:
    """
    Aggregate trade log into per-agent or per-tier performance reports.

    Parameters
    ----------
    trade_log : list of dict
        Each dict must have ``realized_return`` (float) and the ``group_by``
        key (e.g. ``tier`` or ``agent_id``).
    group_by : str
        Key to group on — ``'tier'`` (default) or ``'agent_id'``.

    Returns
    -------
    dict mapping group key → AgentReport
    """
    groups: Dict[str, List[float]] = {}
    for trade in trade_log:
        key = str(trade.get(group_by, "UNKNOWN"))
        groups.setdefault(key, []).append(float(trade.get("realized_return", 0.0)))

    reports: Dict[str, AgentReport] = {}
    for key, rets in groups.items():
        stats = compute_performance(rets)
        reports[key] = AgentReport(
            agent_id=key,
            tier=key if group_by == "tier" else "N/A",
            stats=stats,
            returns=rets,
        )
    return reports


def print_report_table(reports: Dict[str, AgentReport]) -> None:
    """Pretty-print a summary table to stdout."""
    header = f"{'Group':<15} {'Trades':>7} {'Sharpe':>8} {'WinRate':>8} {'MaxDD':>10} {'PF':>8}"
    print(header)
    print("-" * len(header))
    for key, r in sorted(reports.items()):
        s = r.stats
        print(
            f"{key:<15} {s.trades:>7} {s.sharpe:>8.3f} "
            f"{s.win_rate:>8.1%} {s.max_drawdown:>10.4f} {s.profit_factor:>8.3f}"
        )
