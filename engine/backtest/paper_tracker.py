"""
JARVIS TRADER — MGC Paper Trading Performance Tracker
======================================================
Tracks paper trades for walk-forward validated strategies, computes rolling
performance metrics, and enforces kill thresholds to halt trading when the
strategy degrades below acceptable levels.

Storage: JSON file at engine/backtest/results/paper_trades_MGC.json
Kill conditions checked after every trade close.

Usage:
    from backtest.paper_tracker import PaperTradeTracker
    from backtest.paper_config import MGC_PAPER_CONFIG

    tracker = PaperTradeTracker(MGC_PAPER_CONFIG)
    tracker.add_trade({
        "entry_date": "2026-03-29",
        "exit_date": "2026-04-01",
        "entry_price": 2350.0,
        "exit_price": 2375.0,
        "side": "long",
        "contracts": 1,
        "exit_reason": "target_1",
        "regime_type": "trending",
    })
    metrics = tracker.get_metrics()
    should_kill, reason = tracker.check_kill_conditions()
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("jarvis_trader.paper_tracker")

# Default storage directory
_RESULTS_DIR = Path(__file__).parent / "results"


class PaperTradeTracker:
    """
    Paper trading performance tracker with kill-threshold enforcement.

    Parameters
    ----------
    config : dict
        Paper trading configuration (e.g., MGC_PAPER_CONFIG from paper_config.py).
        Must contain: symbol, initial_capital, kill_threshold, multiplier,
        commission_per_contract, slippage_ticks, tick_size.
    store_path : Path, optional
        Override the default JSON storage path.
    """

    def __init__(self, config: dict, store_path: Optional[Path] = None):
        self._config = config
        self._symbol = config["symbol"]
        self._initial_capital = config["initial_capital"]
        self._multiplier = config.get("multiplier", 10.0)
        self._commission = config.get("commission_per_contract", 2.50)
        self._slippage_ticks = config.get("slippage_ticks", 1)
        self._tick_size = config.get("tick_size", 0.10)
        self._kill_threshold = config.get("kill_threshold", {})

        # Storage
        if store_path is not None:
            self._store_path = store_path
        else:
            _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            self._store_path = _RESULTS_DIR / f"paper_trades_{self._symbol}.json"

        # Load existing trades
        self._trades: List[dict] = self._load_trades()

        logger.info(
            "PaperTradeTracker initialized for %s — %d existing trades, store=%s",
            self._symbol,
            len(self._trades),
            self._store_path,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def add_trade(self, trade_dict: dict) -> None:
        """
        Append a completed trade and persist to disk.

        Required keys in trade_dict:
            entry_date      : str (YYYY-MM-DD or ISO-8601)
            exit_date        : str
            entry_price     : float
            exit_price      : float
            side            : str ("long" or "short")
            contracts       : int (default 1)
            exit_reason     : str (e.g., "target_1", "stop_loss", "eod_exit", "signal_reversal")
            regime_type     : str (e.g., "trending", "ranging", "volatile")

        Computed fields added automatically:
            pnl             : float (net of commission and slippage)
            pnl_pct         : float (% of initial capital)
            recorded_at     : str (ISO-8601 timestamp)
        """
        trade = dict(trade_dict)  # defensive copy

        # Defaults
        trade.setdefault("contracts", 1)
        trade.setdefault("side", "long")
        trade.setdefault("exit_reason", "unknown")
        trade.setdefault("regime_type", "unknown")

        # Compute P&L
        entry = float(trade["entry_price"])
        exit_ = float(trade["exit_price"])
        contracts = int(trade["contracts"])
        side = trade["side"].lower()

        if side == "long":
            raw_pnl = (exit_ - entry) * self._multiplier * contracts
        else:
            raw_pnl = (entry - exit_) * self._multiplier * contracts

        # Subtract commission and slippage
        slippage_cost = self._slippage_ticks * self._tick_size * self._multiplier * contracts
        total_cost = (self._commission * contracts) + slippage_cost
        net_pnl = raw_pnl - total_cost

        trade["pnl"] = round(net_pnl, 2)
        trade["pnl_pct"] = round((net_pnl / self._initial_capital) * 100, 4)
        trade["recorded_at"] = datetime.now().isoformat()

        self._trades.append(trade)
        self._save_trades()

        logger.info(
            "[PAPER-MGC] Trade recorded: %s %s entry=%.2f exit=%.2f pnl=$%.2f (%+.2f%%) reason=%s regime=%s",
            side.upper(),
            self._symbol,
            entry,
            exit_,
            net_pnl,
            trade["pnl_pct"],
            trade["exit_reason"],
            trade["regime_type"],
        )

        # Check kill conditions after every trade
        should_kill, reason = self.check_kill_conditions()
        if should_kill:
            logger.critical(
                "[PAPER-MGC] KILL THRESHOLD BREACHED: %s — Paper trading should be halted.",
                reason,
            )

    def get_metrics(self) -> dict:
        """
        Return current performance metrics across all recorded trades.

        Returns
        -------
        dict with keys:
            total_trades     : int
            total_pnl        : float
            total_pnl_pct    : float (% of initial capital)
            win_rate         : float (0-1)
            profit_factor    : float or None (if no losses)
            avg_win          : float
            avg_loss         : float
            max_drawdown     : float (negative or 0)
            max_drawdown_pct : float
            best_trade       : float
            worst_trade      : float
            avg_trade        : float
            current_equity   : float
            regime_breakdown : dict {regime: {trades, win_rate, avg_pnl}}
            exit_reason_breakdown : dict {reason: count}
        """
        if not self._trades:
            return self._empty_metrics()

        pnls = [t["pnl"] for t in self._trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

        # Max drawdown from equity curve
        peak = 0.0
        equity = 0.0
        max_dd = 0.0
        for p in pnls:
            equity += p
            if equity > peak:
                peak = equity
            dd = equity - peak
            if dd < max_dd:
                max_dd = dd

        # Regime breakdown
        regime_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"trades": 0, "wins": 0, "total_pnl": 0.0}
        )
        for t in self._trades:
            regime = t.get("regime_type", "unknown")
            regime_stats[regime]["trades"] += 1
            regime_stats[regime]["total_pnl"] += t["pnl"]
            if t["pnl"] > 0:
                regime_stats[regime]["wins"] += 1

        regime_breakdown = {}
        for regime, stats in regime_stats.items():
            regime_breakdown[regime] = {
                "trades": stats["trades"],
                "win_rate": round(stats["wins"] / stats["trades"], 4)
                if stats["trades"] > 0
                else 0.0,
                "avg_pnl": round(stats["total_pnl"] / stats["trades"], 2)
                if stats["trades"] > 0
                else 0.0,
            }

        # Exit reason breakdown
        exit_reasons: Dict[str, int] = defaultdict(int)
        for t in self._trades:
            exit_reasons[t.get("exit_reason", "unknown")] += 1

        return {
            "total_trades": len(pnls),
            "total_pnl": round(sum(pnls), 2),
            "total_pnl_pct": round((sum(pnls) / self._initial_capital) * 100, 4),
            "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
            "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round((max_dd / self._initial_capital) * 100, 4),
            "best_trade": round(max(pnls), 2) if pnls else 0.0,
            "worst_trade": round(min(pnls), 2) if pnls else 0.0,
            "avg_trade": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
            "current_equity": round(self._initial_capital + sum(pnls), 2),
            "regime_breakdown": dict(regime_breakdown),
            "exit_reason_breakdown": dict(exit_reasons),
        }

    def check_kill_conditions(self) -> Tuple[bool, str]:
        """
        Check whether paper trading should be halted based on kill thresholds.

        Returns
        -------
        (should_kill, reason)
            should_kill : bool — True if a kill threshold is breached
            reason      : str  — human-readable explanation (empty if no kill)
        """
        if not self._trades:
            return False, ""

        monthly = self.monthly_summary()
        if not monthly:
            return False, ""

        # ── Check 1: Consecutive months underperforming ───────────────────
        max_consecutive = self._kill_threshold.get("consecutive_months_underperform", 3)
        underperform_pct = self._kill_threshold.get("monthly_underperform_vs_is_pct", 0.50)

        # IS baseline: avg 7.6% per 3-month window = ~2.53% per month
        is_monthly_baseline = 7.6 / 3.0  # percent per month

        sorted_months = sorted(monthly.keys())
        consecutive_under = 0
        for month_key in sorted_months:
            month_return = monthly[month_key]
            threshold = is_monthly_baseline * (1.0 - underperform_pct)
            if month_return < threshold:
                consecutive_under += 1
            else:
                consecutive_under = 0

            if consecutive_under >= max_consecutive:
                return True, (
                    f"KILL: {consecutive_under} consecutive months below "
                    f"{threshold:.1f}% return threshold "
                    f"(50% of IS baseline {is_monthly_baseline:.1f}%/month). "
                    f"Months: {sorted_months[-max_consecutive:]}"
                )

        # ── Check 2: Rolling WFE minimum ──────────────────────────────────
        # This requires external WFE calculation; we approximate by checking
        # if cumulative return has decayed severely relative to IS expectations
        wfe_min = self._kill_threshold.get("rolling_wfe_minimum", 0.15)
        if len(sorted_months) >= 3:
            # Use last 3 months as a rolling window
            last_3 = [monthly[m] for m in sorted_months[-3:]]
            avg_oos_return = sum(last_3) / len(last_3)
            # Approximate WFE = OOS / IS
            approx_wfe = avg_oos_return / is_monthly_baseline if is_monthly_baseline > 0 else 0.0

            if approx_wfe < wfe_min:
                return True, (
                    f"KILL: Rolling 3-month WFE approximation {approx_wfe:.2f} "
                    f"below minimum threshold {wfe_min:.2f}. "
                    f"Last 3 months avg return: {avg_oos_return:.2f}% "
                    f"vs IS baseline {is_monthly_baseline:.2f}%/month."
                )

        # ── Check 3: Max drawdown circuit breaker ─────────────────────────
        pnls = [t["pnl"] for t in self._trades]
        peak = 0.0
        equity = 0.0
        max_dd = 0.0
        for p in pnls:
            equity += p
            if equity > peak:
                peak = equity
            dd = equity - peak
            if dd < max_dd:
                max_dd = dd

        max_dd_pct = abs(max_dd / self._initial_capital) * 100
        if max_dd_pct > 10.0:
            return True, (
                f"KILL: Max drawdown {max_dd_pct:.1f}% exceeds 10% circuit breaker. "
                f"Drawdown: ${max_dd:.2f} on ${self._initial_capital:.0f} capital."
            )

        return False, ""

    def monthly_summary(self) -> Dict[str, float]:
        """
        Return monthly return percentages.

        Returns
        -------
        dict of {YYYY-MM: return_pct}
            return_pct is the sum of trade P&L for that month as a % of initial capital.
        """
        if not self._trades:
            return {}

        monthly_pnl: Dict[str, float] = defaultdict(float)
        for t in self._trades:
            # Use exit_date for attribution (when the P&L was realized)
            exit_date = t.get("exit_date", t.get("entry_date", ""))
            if not exit_date:
                continue
            # Extract YYYY-MM
            month_key = exit_date[:7]  # "2026-03" from "2026-03-29"
            monthly_pnl[month_key] += t["pnl"]

        # Convert to percentages of initial capital
        return {
            month: round((pnl / self._initial_capital) * 100, 4)
            for month, pnl in sorted(monthly_pnl.items())
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_trades(self) -> List[dict]:
        """Load trades from the JSON store file."""
        if not self._store_path.exists():
            return []
        try:
            with self._store_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "trades" in data:
                    return data["trades"]
                else:
                    logger.warning(
                        "Unexpected JSON structure in %s, starting fresh", self._store_path
                    )
                    return []
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load paper trades from %s: %s", self._store_path, exc)
            return []

    def _save_trades(self) -> None:
        """Persist all trades to the JSON store file."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "symbol": self._symbol,
            "config": {
                "initial_capital": self._initial_capital,
                "risk_per_trade": self._config.get("risk_per_trade"),
                "adaptive_regime": self._config.get("adaptive_regime"),
                "interval": self._config.get("interval"),
            },
            "updated_at": datetime.now().isoformat(),
            "total_trades": len(self._trades),
            "trades": self._trades,
        }
        try:
            with self._store_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
        except OSError as exc:
            logger.error("Failed to save paper trades to %s: %s", self._store_path, exc)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _empty_metrics(self) -> dict:
        """Return zeroed-out metrics dict when no trades exist."""
        return {
            "total_trades": 0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "win_rate": 0.0,
            "profit_factor": None,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "avg_trade": 0.0,
            "current_equity": self._initial_capital,
            "regime_breakdown": {},
            "exit_reason_breakdown": {},
        }

    def __repr__(self) -> str:
        metrics = self.get_metrics()
        return (
            f"PaperTradeTracker({self._symbol}, "
            f"trades={metrics['total_trades']}, "
            f"pnl=${metrics['total_pnl']:.2f}, "
            f"wr={metrics['win_rate']:.0%})"
        )
