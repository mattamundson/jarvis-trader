"""
Paper Trading Validation Metrics
=================================
Computes Sharpe ratio, max drawdown, win rate, and progress toward
30-day validation targets directly from the SQLite paper_trades table.

This module is intentionally standalone — no dependency on the paper.*
validation tracker chain, so it always reflects ground-truth DB state.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "jarvis_trader.db"

# Canonical targets (aligned with paper.validation_gate_config.PAPER_VALIDATION_GATES)
TARGETS = {
    "min_days": 30,
    "min_sharpe": 1.5,
    "max_drawdown_pct": 15.0,   # expressed as positive %; passes when drawdown <= this
    "min_win_rate_pct": 55.0,   # percent (55.0 = 55%)
    "min_profit_factor": 2.0,
    "min_trades": 60,
}


class ValidationMetrics:
    """Compute validation dashboard metrics from SQLite paper_trades."""

    def __init__(self, db_path: Path = DB_PATH):
        self._db = db_path

    def compute(self) -> dict:
        """Compute all validation metrics. Returns full status dict."""
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(str(self._db))
            conn.row_factory = sqlite3.Row
            return self._compute(conn)
        except Exception as e:
            logger.error(f"ValidationMetrics.compute failed: {e}", exc_info=True)
            return {"error": str(e)}
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # ── internal ─────────────────────────────────────────────────────────────

    def _compute(self, conn: sqlite3.Connection) -> dict:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]

        # Locate trade table
        trade_table: Optional[str] = None
        for candidate in ["paper_trades", "trades", "trade_log", "paper_trade_log"]:
            if candidate in tables:
                trade_table = candidate
                break

        if not trade_table:
            return {
                "status": "no_trades",
                "message": "No trade table found — execution loop may not be recording yet",
                "targets": TARGETS,
                "tables_found": tables,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Fetch closed trades only
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM {trade_table}
                WHERE LOWER(status) IN ('closed', 'filled', 'done')
                ORDER BY entry_time ASC
                """
            ).fetchall()
        except Exception:
            # Fallback — fetch all and filter nothing
            rows = conn.execute(
                f"SELECT * FROM {trade_table} ORDER BY entry_time ASC"
            ).fetchall()

        if not rows:
            return {
                "status": "no_trades",
                "message": "Trade table exists but has no closed trades yet",
                "targets": TARGETS,
                "trade_table": trade_table,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        trades = [dict(r) for r in rows]
        total_trades = len(trades)

        # ── PnL field detection ───────────────────────────────────────────
        pnl_field: Optional[str] = next(
            (k for k in trades[0].keys() if "pnl" in k.lower() or "profit" in k.lower()),
            None,
        )
        if pnl_field:
            pnls = [float(t[pnl_field]) for t in trades if t[pnl_field] is not None]
        else:
            # Derive from entry/exit price if available
            pnls = []
            for t in trades:
                ep = t.get("entry_price")
                xp = t.get("exit_price")
                qty = t.get("quantity") or 1
                if ep is not None and xp is not None:
                    pnls.append((float(xp) - float(ep)) * float(qty))

        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        win_rate = wins / len(pnls) if pnls else 0.0
        win_rate_pct = win_rate * 100.0
        total_pnl = sum(pnls)

        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = sum(abs(p) for p in pnls if p < 0)
        profit_factor = (
            (gross_profit / gross_loss)
            if gross_loss > 0
            else (9999.0 if gross_profit > 0 else 0.0)
        )

        # ── Sharpe ratio (annualized, daily P&L grouping) ────────────────
        sharpe = self._compute_sharpe(trades) if total_trades >= 2 else None

        # ── Max drawdown ─────────────────────────────────────────────────
        max_drawdown_pct = self._compute_max_drawdown_pct(pnls)

        # ── Days elapsed ─────────────────────────────────────────────────
        days_elapsed = self._compute_days_elapsed(trades)

        # ── Targets met ──────────────────────────────────────────────────
        targets_met = {
            "days_30":            days_elapsed >= TARGETS["min_days"],
            "sharpe_1_5":         (sharpe or 0.0) >= TARGETS["min_sharpe"],
            "drawdown_15pct":     max_drawdown_pct <= TARGETS["max_drawdown_pct"],
            "win_rate_55pct":     win_rate_pct >= TARGETS["min_win_rate_pct"],
            "profit_factor_2_0":  profit_factor >= TARGETS["min_profit_factor"],
            "min_trades_60":      total_trades >= TARGETS["min_trades"],
        }
        all_targets_met = all(targets_met.values())
        targets_met_count = sum(targets_met.values())

        return {
            "status": "validated" if all_targets_met else "in_progress",
            "all_targets_met": all_targets_met,
            "targets_met": targets_met,
            "targets_met_count": f"{targets_met_count}/{len(targets_met)}",
            "metrics": {
                "days_elapsed":      days_elapsed,
                "days_remaining":    max(0, TARGETS["min_days"] - days_elapsed),
                "total_trades":      total_trades,
                "winning_trades":    wins,
                "losing_trades":     losses,
                "win_rate":          round(win_rate, 4),
                "win_rate_pct":      f"{win_rate_pct:.1f}%",
                "profit_factor":     round(profit_factor, 3),
                "sharpe_ratio":      round(sharpe, 3) if sharpe is not None else None,
                "max_drawdown_pct":  round(max_drawdown_pct, 2),
                "total_pnl":         round(total_pnl, 2),
                "gross_profit":      round(gross_profit, 2),
                "gross_loss":        round(gross_loss, 2),
                "avg_trade_pnl":     round(total_pnl / total_trades, 2) if total_trades else 0,
            },
            "targets": TARGETS,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trade_table": trade_table,
        }

    def _compute_sharpe(
        self,
        trades: list[dict],
        risk_free_rate: float = 0.04,
    ) -> Optional[float]:
        """Annualized Sharpe ratio from daily P&L buckets."""
        daily: defaultdict[date, float] = defaultdict(float)

        pnl_field: Optional[str] = next(
            (k for k in trades[0].keys() if "pnl" in k.lower() or "profit" in k.lower()),
            None,
        ) if trades else None

        for t in trades:
            # Use exit_time for daily bucketing (realized P&L date)
            ts_str = t.get("exit_time") or t.get("entry_time") or ""
            if not ts_str:
                continue
            try:
                dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                day = dt.date()
            except (ValueError, TypeError):
                continue

            if pnl_field and t.get(pnl_field) is not None:
                daily[day] += float(t[pnl_field])
            else:
                ep = t.get("entry_price")
                xp = t.get("exit_price")
                qty = t.get("quantity") or 1
                if ep is not None and xp is not None:
                    daily[day] += (float(xp) - float(ep)) * float(qty)

        returns = list(daily.values())
        if len(returns) < 2:
            return None

        n = len(returns)
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0:
            return None

        # Annualize
        annual_return = mean * 252
        annual_std = std * math.sqrt(252)
        sharpe = (annual_return - risk_free_rate) / annual_std
        return max(0.0, sharpe)

    def _compute_max_drawdown_pct(self, pnls: list[float]) -> float:
        """Max peak-to-trough drawdown as a positive percentage of starting capital."""
        if not pnls:
            return 0.0
        starting_capital = 10_000.0
        peak = starting_capital
        cumulative = starting_capital
        max_dd = 0.0
        for pnl in pnls:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            if peak > 0:
                dd = (peak - cumulative) / peak * 100.0
                if dd > max_dd:
                    max_dd = dd
        return round(max_dd, 2)

    def _compute_days_elapsed(self, trades: list[dict]) -> int:
        """Days from first trade entry_time to today."""
        if not trades:
            return 0
        first_ts = trades[0].get("entry_time") or trades[0].get("exit_time") or ""
        try:
            dt = datetime.fromisoformat(str(first_ts).replace("Z", "+00:00"))
            return (date.today() - dt.date()).days
        except (ValueError, TypeError):
            return 0
