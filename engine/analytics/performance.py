"""
JARVIS TRADER — Performance Analytics
Calculates forward-test metrics from SQLite trade history.
Target thresholds: PF > 2.0, Sharpe > 1.5
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.analytics")

# ── Validation thresholds ─────────────────────────────────────────────────────

PROFIT_FACTOR_TARGET = 2.0
SHARPE_TARGET = 1.5
MIN_TRADES_REQUIRED = 10  # Minimum closed trades to produce a meaningful result

# ── Backtest reference values (from JARVIS backtest run) ─────────────────────
# MES 1h bars, 2023-2024 full-year backtest

BACKTEST_PROFIT_FACTOR = 5.27
BACKTEST_SHARPE = 4.16
BACKTEST_WIN_RATE = 0.68  # 68 %
BACKTEST_MAX_DRAWDOWN = -0.082  # -8.2 %
BACKTEST_TOTAL_RETURN = 0.472  # +47.2 %
BACKTEST_SYMBOL = "MES"
BACKTEST_TIMEFRAME = "1h"
BACKTEST_PERIOD = "2023-2024"

# ── Validation thresholds for live/paper readiness ───────────────────────────

MIN_TRADING_DAYS_REQUIRED = 30  # calendar days of live data needed


# ── PerformanceMetrics dataclass ──────────────────────────────────────────────


@dataclass
class PerformanceMetrics:
    """
    Snapshot of forward-test performance metrics computed from closed paper trades
    and daily P&L records stored in SQLite.
    """

    profit_factor: float  # sum(wins) / abs(sum(losses)); inf if no losses
    sharpe_ratio: float  # annualized: sqrt(252) * mean_return / std_return
    win_rate: float  # winning_trades / total_closed_trades (0–1)
    avg_win: float  # average P&L of winning trades (positive)
    avg_loss: float  # average P&L of losing trades (negative)
    max_drawdown: float  # maximum peak-to-trough drawdown as a fraction (negative)
    total_trades: int  # count of closed trades in the analysis window
    total_pnl: float  # sum of all closed trade P&L values
    meets_paper_threshold: bool  # True if PF > 2.0 AND Sharpe > 1.5
    period_days: int  # calendar days spanned by the data window

    def as_dict(self) -> Dict[str, Any]:
        """Return all fields as a plain dict, safe for JSON serialisation."""
        return asdict(self)


# ── PerformanceCalculator ─────────────────────────────────────────────────────


class PerformanceCalculator:
    """
    Compute forward-test performance metrics from SQLite trade history.

    Parameters
    ----------
    db_manager:
        A ``DatabaseManager`` instance (from ``database.schema``).
        Must expose ``get_closed_trades()`` and ``get_daily_pnl()``.
    """

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    # ── Public API ────────────────────────────────────────────────────────

    def calculate(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> PerformanceMetrics:
        """
        Compute all performance metrics for the specified window.

        Parameters
        ----------
        start_date:
            ISO date string ``YYYY-MM-DD``.  Only trades closed on or after
            this date are included.  ``None`` means no lower bound.
        end_date:
            ISO date string ``YYYY-MM-DD``.  Only trades closed on or before
            this date are included.  ``None`` means no upper bound.
        symbol:
            Filter by ticker symbol (e.g. ``"SPY"``).  ``None`` means all symbols.

        Returns
        -------
        PerformanceMetrics
        """
        # ── Fetch closed trades ───────────────────────────────────────────
        raw_trades = self._db.get_closed_trades(
            symbol=symbol.upper() if symbol else None,
            limit=10_000,
        )

        # Apply date filters (exit_time is ISO-8601; string comparison works for
        # the YYYY-MM-DDTHH:MM:SS format used throughout the project).
        if start_date:
            raw_trades = [t for t in raw_trades if t.get("exit_time", "") >= start_date]
        if end_date:
            cutoff = end_date + "T23:59:59"
            raw_trades = [t for t in raw_trades if t.get("exit_time", "") <= cutoff]

        # ── Fetch daily P&L records ───────────────────────────────────────
        daily_rows = self._db.get_daily_pnl(
            start_date=start_date,
            end_date=end_date,
        )
        daily_pnl_list = [r.get("realized_pnl", 0.0) for r in daily_rows]

        # ── Derived calculations ──────────────────────────────────────────
        total_trades = len(raw_trades)
        total_pnl = sum(t.get("pnl", 0.0) or 0.0 for t in raw_trades)

        profit_factor = self.calculate_profit_factor(raw_trades)
        sharpe = self.calculate_sharpe(daily_pnl_list)
        max_dd = self.calculate_max_drawdown(daily_pnl_list)

        wins = [t for t in raw_trades if (t.get("pnl") or 0.0) > 0.0]
        losses = [t for t in raw_trades if (t.get("pnl") or 0.0) <= 0.0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0.0

        period_days = len(daily_rows) if daily_rows else 0

        meets = (profit_factor >= PROFIT_FACTOR_TARGET) and (sharpe >= SHARPE_TARGET)

        logger.info(
            f"[Analytics] calculate() trades={total_trades} PF={profit_factor:.2f} "
            f"Sharpe={sharpe:.2f} WR={win_rate:.1%} MaxDD={max_dd:.2%} "
            f"meets_threshold={meets}"
        )

        # Sanitize non-finite floats — float('inf') and float('nan') cannot
        # be JSON-serialised by FastAPI's default encoder.
        if not math.isfinite(profit_factor):
            profit_factor = 9999.0

        return PerformanceMetrics(
            profit_factor=round(profit_factor, 4),
            sharpe_ratio=round(sharpe, 4),
            win_rate=round(win_rate, 4),
            avg_win=round(avg_win, 4),
            avg_loss=round(avg_loss, 4),
            max_drawdown=round(max_dd, 4),
            total_trades=total_trades,
            total_pnl=round(total_pnl, 4),
            meets_paper_threshold=meets,
            period_days=period_days,
        )

    # ── Metric helpers ────────────────────────────────────────────────────

    @staticmethod
    def calculate_profit_factor(trades: List[Dict]) -> float:
        """
        Profit Factor = gross_profit / abs(gross_loss).

        Returns ``0.0`` if there are no winning trades, ``float('inf')`` if there
        are winning trades but no losing trades (all trades profitable).

        Parameters
        ----------
        trades:
            List of trade dicts each containing a ``pnl`` key (may be None).
        """
        gross_profit = sum(t.get("pnl", 0.0) or 0.0 for t in trades if (t.get("pnl") or 0.0) > 0.0)
        gross_loss = abs(
            sum(t.get("pnl", 0.0) or 0.0 for t in trades if (t.get("pnl") or 0.0) < 0.0)
        )

        if gross_profit == 0.0:
            return 0.0
        if gross_loss == 0.0:
            return float("inf")
        return gross_profit / gross_loss

    @staticmethod
    def calculate_sharpe(daily_pnl_list: List[float]) -> float:
        """
        Annualized Sharpe ratio using daily P&L values.

        Formula: sqrt(252) * mean(daily_pnl) / std(daily_pnl)

        Returns ``0.0`` when there are fewer than 2 data points or when the
        standard deviation is zero (flat equity curve).

        Parameters
        ----------
        daily_pnl_list:
            Ordered list of daily realized P&L values (floats).
        """
        n = len(daily_pnl_list)
        if n < 2:
            return 0.0

        mean = sum(daily_pnl_list) / n
        variance = sum((x - mean) ** 2 for x in daily_pnl_list) / (n - 1)
        std = math.sqrt(variance)

        # A flat series can leave `std` as float dust (~1e-18) rather than exactly
        # 0.0, from cancellation in the sum-of-squares above (e.g. [0.1, 0.1, 0.1]
        # -> std ~3e-18). An `== 0.0` check misses that and blows Sharpe up to
        # ~1e17 — which would falsely clear SHARPE_TARGET in the validation gate.
        # Any sub-nanodollar std is a flat curve.
        if std < 1e-9:
            return 0.0

        return math.sqrt(252) * mean / std

    @staticmethod
    def calculate_max_drawdown(daily_pnl_list: List[float]) -> float:
        """
        Maximum peak-to-trough drawdown expressed as a fraction of the peak
        equity value (always <= 0).

        Equity starts at 0 and accumulates daily P&L.  Returns ``0.0`` if
        there are no data points or no drawdown occurred.

        Parameters
        ----------
        daily_pnl_list:
            Ordered list of daily realized P&L values (floats).
        """
        if not daily_pnl_list:
            return 0.0

        equity = 0.0
        peak = 0.0
        max_dd = 0.0

        for daily in daily_pnl_list:
            equity += daily
            if equity > peak:
                peak = equity
            if peak > 0.0:
                dd = (equity - peak) / peak
                if dd < max_dd:
                    max_dd = dd

        return max_dd

    def calculate_rolling(self, days: int = 30) -> dict:
        """Calculate performance metrics for the last N calendar days."""
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        try:
            trades = self._db.get_trade_history(limit=500)
            # Filter to only trades closed within the window
            recent = []
            for t in trades:
                exit_time = t.get("exit_time", "")
                if exit_time and exit_time >= cutoff:
                    recent.append(t)

            if not recent:
                return {
                    "days": days,
                    "trade_count": 0,
                    "profit_factor": None,
                    "sharpe_ratio": None,
                    "win_rate": None,
                    "gross_pnl": 0.0,
                    "max_drawdown": 0.0,
                    "avg_pnl_per_trade": None,
                    "best_trade": None,
                    "worst_trade": None,
                    "window_start": cutoff[:10],
                    "window_end": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }

            pnls = [float(t.get("pnl", 0) or 0) for t in recent]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]

            gross_pnl = sum(pnls)
            win_rate = len(wins) / len(pnls) if pnls else None

            gross_wins = sum(wins)
            gross_losses = abs(sum(losses))
            profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else None

            # Simple Sharpe (annualized from daily returns if we have enough data)
            import statistics

            avg_pnl = statistics.mean(pnls) if pnls else 0
            std_pnl = statistics.stdev(pnls) if len(pnls) >= 2 else None
            sharpe = (avg_pnl / std_pnl * (252**0.5)) if std_pnl and std_pnl > 0 else None

            # Max drawdown within the window
            running = 0.0
            peak = 0.0
            max_dd = 0.0
            for p in pnls:
                running += p
                if running > peak:
                    peak = running
                dd = (running - peak) / max(abs(peak), 1)
                if dd < max_dd:
                    max_dd = dd

            return {
                "days": days,
                "trade_count": len(recent),
                "profit_factor": round(profit_factor, 2) if profit_factor else None,
                "sharpe_ratio": round(sharpe, 2) if sharpe else None,
                "win_rate": round(win_rate, 3) if win_rate is not None else None,
                "gross_pnl": round(gross_pnl, 2),
                "max_drawdown": round(max_dd, 4),
                "avg_pnl_per_trade": round(avg_pnl, 2) if pnls else None,
                "best_trade": round(max(pnls), 2) if pnls else None,
                "worst_trade": round(min(pnls), 2) if pnls else None,
                "window_start": cutoff[:10],
                "window_end": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }
        except Exception as e:
            return {"days": days, "error": str(e), "trade_count": 0}

    # ── Reporting ─────────────────────────────────────────────────────────

    def get_validation_report(self) -> Dict[str, Any]:
        """
        Run ``calculate()`` over all available history and return a structured
        report suitable for the ``/analytics/validation-report`` endpoint.

        Status values
        -------------
        ``"PASS"``              Both PF > 2.0 AND Sharpe > 1.5.
        ``"FAIL"``              At least one metric is below threshold.
        ``"INSUFFICIENT_DATA"`` Fewer than ``MIN_TRADES_REQUIRED`` closed trades.

        Returns
        -------
        dict with keys:
            metrics         — the PerformanceMetrics as a dict
            status          — "PASS" | "FAIL" | "INSUFFICIENT_DATA"
            recommendation  — human-readable next-action string
            thresholds      — the target values for reference
        """
        metrics = self.calculate()

        # Determine status
        if metrics.total_trades < MIN_TRADES_REQUIRED:
            status = "INSUFFICIENT_DATA"
            recommendation = (
                f"Only {metrics.total_trades} closed trade(s) recorded. "
                f"At least {MIN_TRADES_REQUIRED} are required for a statistically "
                f"meaningful evaluation. Continue paper trading to accumulate history."
            )
        elif metrics.meets_paper_threshold:
            status = "PASS"
            recommendation = (
                f"Forward-test PASSED both thresholds "
                f"(PF={metrics.profit_factor:.2f} >= {PROFIT_FACTOR_TARGET}, "
                f"Sharpe={metrics.sharpe_ratio:.2f} >= {SHARPE_TARGET}). "
                f"Consider increasing position size or moving toward live testing."
            )
        else:
            failing = []
            if metrics.profit_factor < PROFIT_FACTOR_TARGET:
                failing.append(f"PF={metrics.profit_factor:.2f} (target >= {PROFIT_FACTOR_TARGET})")
            if metrics.sharpe_ratio < SHARPE_TARGET:
                failing.append(f"Sharpe={metrics.sharpe_ratio:.2f} (target >= {SHARPE_TARGET})")
            status = "FAIL"
            recommendation = (
                f"Forward-test FAILED: {'; '.join(failing)}. "
                f"Review signal quality, tighten stop-losses, or adjust position sizing "
                f"before advancing to live trading."
            )

        return {
            "status": status,
            "metrics": metrics.as_dict(),
            "thresholds": {
                "profit_factor": PROFIT_FACTOR_TARGET,
                "sharpe_ratio": SHARPE_TARGET,
                "min_trades_required": MIN_TRADES_REQUIRED,
            },
            "recommendation": recommendation,
        }

    def compare_to_backtest(
        self,
        backtest_pf: float = BACKTEST_PROFIT_FACTOR,
        backtest_sharpe: float = BACKTEST_SHARPE,
        backtest_win_rate: float = BACKTEST_WIN_RATE,
        backtest_max_drawdown: float = BACKTEST_MAX_DRAWDOWN,
        backtest_total_return: float = BACKTEST_TOTAL_RETURN,
    ) -> Dict[str, Any]:
        """
        Compare current live/paper metrics against the reference backtest results.

        Returns the structured comparison response expected by the dashboard:

        {
          "backtest":              { confirmed backtest values + metadata },
          "live_paper":            { current forward-test metrics from SQLite },
          "validation_thresholds": { per-metric pass/fail vs required minimums },
          "ready_for_live":        bool,
          "degradation_factor":    { live / backtest ratio per metric, null when no live data }
        }
        """
        metrics = self.calculate()

        # ── Live paper block ───────────────────────────────────────────────
        trading_days = metrics.period_days
        total_return_live = (
            round(metrics.total_pnl / 10_000.0, 4)  # fraction of a $10k notional
            if metrics.total_pnl != 0.0
            else 0.0
        )

        live_paper = {
            "profit_factor": metrics.profit_factor,
            "sharpe_ratio": metrics.sharpe_ratio,
            "win_rate": metrics.win_rate,
            "max_drawdown": metrics.max_drawdown,
            "total_return_pct": total_return_live,
            "trade_count": metrics.total_trades,
            "trading_days": trading_days,
        }

        # ── Validation thresholds ──────────────────────────────────────────
        pf_met = metrics.profit_factor >= PROFIT_FACTOR_TARGET
        sharpe_met = metrics.sharpe_ratio >= SHARPE_TARGET
        days_met = trading_days >= MIN_TRADING_DAYS_REQUIRED

        validation_thresholds = {
            "profit_factor": {
                "required": PROFIT_FACTOR_TARGET,
                "met": pf_met,
            },
            "sharpe_ratio": {
                "required": SHARPE_TARGET,
                "met": sharpe_met,
            },
            "min_trading_days": {
                "required": MIN_TRADING_DAYS_REQUIRED,
                "current": trading_days,
                "met": days_met,
            },
        }

        ready_for_live = pf_met and sharpe_met and days_met

        # ── Degradation factors (live / backtest ratio) ────────────────────
        has_live_data = metrics.total_trades > 0

        if has_live_data and backtest_pf > 0.0 and metrics.profit_factor > 0.0:
            deg_pf: Optional[float] = round(metrics.profit_factor / backtest_pf, 4)
        else:
            deg_pf = None

        if has_live_data and backtest_sharpe > 0.0 and metrics.sharpe_ratio > 0.0:
            deg_sharpe: Optional[float] = round(metrics.sharpe_ratio / backtest_sharpe, 4)
        else:
            deg_sharpe = None

        degradation_note = "No live data yet" if not has_live_data else None

        degradation_factor: Dict[str, Any] = {
            "profit_factor": deg_pf,
            "sharpe_ratio": deg_sharpe,
        }
        if degradation_note:
            degradation_factor["note"] = degradation_note

        logger.info(
            f"[Analytics] compare_to_backtest() trades={metrics.total_trades} "
            f"trading_days={trading_days} ready_for_live={ready_for_live}"
        )

        return {
            "backtest": {
                "profit_factor": backtest_pf,
                "sharpe_ratio": backtest_sharpe,
                "win_rate": backtest_win_rate,
                "max_drawdown": backtest_max_drawdown,
                "total_return_pct": backtest_total_return,
                "symbol": BACKTEST_SYMBOL,
                "timeframe": BACKTEST_TIMEFRAME,
                "period": BACKTEST_PERIOD,
            },
            "live_paper": live_paper,
            "validation_thresholds": validation_thresholds,
            "ready_for_live": ready_for_live,
            "degradation_factor": degradation_factor,
        }
