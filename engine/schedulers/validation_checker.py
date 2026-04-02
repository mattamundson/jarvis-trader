"""
ValidationChecker — automated paper trading validation for futures module.
Checks daily if validation targets are met before allowing live trading.

Targets (must all pass for 30 consecutive days):
  PF ≥ 2.0 | Sharpe ≥ 1.5 | WR ≥ 55% | Trades ≥ 60 | Days ≥ 30 | DD ≤ 15%
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger("jarvis_trader.schedulers.validation")

TARGETS = {
    "profit_factor": 2.0,
    "sharpe_ratio": 1.5,
    "win_rate_pct": 55.0,
    "min_trades": 60,
    "min_days": 30,
    "max_drawdown_pct": 15.0,
}


@dataclass
class ValidationSnapshot:
    computed_at: datetime
    days_elapsed: int
    total_trades: int
    win_rate_pct: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    daily_pnl_values: list[float] = field(default_factory=list)

    @property
    def passes(self) -> bool:
        return (
            self.profit_factor >= TARGETS["profit_factor"]
            and self.sharpe_ratio >= TARGETS["sharpe_ratio"]
            and self.win_rate_pct >= TARGETS["win_rate_pct"]
            and self.total_trades >= TARGETS["min_trades"]
            and self.days_elapsed >= TARGETS["min_days"]
            and self.max_drawdown_pct <= TARGETS["max_drawdown_pct"]
        )

    def failing_checks(self) -> list[str]:
        failing = []
        if self.profit_factor < TARGETS["profit_factor"]:
            failing.append(f"PF {self.profit_factor:.2f} < {TARGETS['profit_factor']}")
        if self.sharpe_ratio < TARGETS["sharpe_ratio"]:
            failing.append(f"Sharpe {self.sharpe_ratio:.2f} < {TARGETS['sharpe_ratio']}")
        if self.win_rate_pct < TARGETS["win_rate_pct"]:
            failing.append(f"WR {self.win_rate_pct:.1f}% < {TARGETS['win_rate_pct']}%")
        if self.total_trades < TARGETS["min_trades"]:
            failing.append(f"Trades {self.total_trades} < {TARGETS['min_trades']}")
        if self.days_elapsed < TARGETS["min_days"]:
            failing.append(f"Days {self.days_elapsed} < {TARGETS['min_days']}")
        if self.max_drawdown_pct > TARGETS["max_drawdown_pct"]:
            failing.append(f"DD {self.max_drawdown_pct:.1f}% > {TARGETS['max_drawdown_pct']}%")
        return failing

    def to_dict(self) -> dict:
        return {
            "computed_at": self.computed_at.isoformat(),
            "days_elapsed": self.days_elapsed,
            "total_trades": self.total_trades,
            "win_rate_pct": round(self.win_rate_pct, 2),
            "profit_factor": round(self.profit_factor, 3),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "passes": self.passes,
            "failing_checks": self.failing_checks(),
            "targets": TARGETS,
        }


class ValidationChecker:
    """
    Computes paper trading validation metrics from SQLite.
    Run daily (e.g., via APScheduler) to track progress toward live trading.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def compute(self, lookback_days: int = 30) -> ValidationSnapshot:
        """Compute validation metrics from the last N days of paper trades."""
        cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        with sqlite3.connect(self.db_path) as conn:
            # Get paper trades in window
            rows = conn.execute(
                """
                SELECT exit_price, entry_price, pnl, status
                FROM paper_trades
                WHERE entry_time >= ? AND status = 'closed'
                ORDER BY entry_time ASC
                """,
                (cutoff,),
            ).fetchall()

            # Get daily P&L for Sharpe + drawdown
            daily_rows = conn.execute(
                """
                SELECT date, realized_pnl
                FROM daily_pnl
                WHERE date >= ?
                ORDER BY date ASC
                """,
                (cutoff,),
            ).fetchall()

        if not rows:
            return ValidationSnapshot(
                computed_at=datetime.utcnow(),
                days_elapsed=0,
                total_trades=0,
                win_rate_pct=0.0,
                profit_factor=0.0,
                sharpe_ratio=0.0,
                max_drawdown_pct=0.0,
            )

        # Win rate + profit factor
        wins_pnl = [abs(r[2]) for r in rows if (r[2] or 0) > 0]
        losses_pnl = [abs(r[2]) for r in rows if (r[2] or 0) < 0]

        total = len(rows)
        win_count = len([r for r in rows if (r[2] or 0) > 0])
        win_rate = (win_count / total * 100) if total else 0.0

        gross_profit = sum(wins_pnl)
        gross_loss = sum(losses_pnl)
        profit_factor = (
            (gross_profit / gross_loss)
            if gross_loss > 0
            else (gross_profit if gross_profit > 0 else 0.0)
        )

        # Daily P&L for Sharpe + drawdown
        daily_pnl = [r[1] for r in daily_rows if r[1] is not None]
        days_elapsed = len({r[0] for r in daily_rows})

        sharpe = self._compute_sharpe(daily_pnl)
        max_dd = self._compute_max_drawdown_pct(daily_pnl)

        return ValidationSnapshot(
            computed_at=datetime.utcnow(),
            days_elapsed=days_elapsed,
            total_trades=total,
            win_rate_pct=round(win_rate, 2),
            profit_factor=round(profit_factor, 3),
            sharpe_ratio=round(sharpe, 3),
            max_drawdown_pct=round(max_dd, 2),
            daily_pnl_values=daily_pnl,
        )

    @staticmethod
    def _compute_sharpe(daily_pnl: list[float], risk_free_rate: float = 0.0) -> float:
        if len(daily_pnl) < 2:
            return 0.0
        try:
            import statistics

            mean = statistics.mean(daily_pnl) - risk_free_rate / 252
            std = statistics.stdev(daily_pnl)
            if std == 0:
                return 0.0
            return float((mean / std) * (252**0.5))
        except Exception:
            return 0.0

    @staticmethod
    def _compute_max_drawdown_pct(daily_pnl: list[float]) -> float:
        if not daily_pnl:
            return 0.0
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in daily_pnl:
            equity += pnl
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        return max_dd
