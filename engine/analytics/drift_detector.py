"""
JARVIS TRADER — Strategy Drift Detector (Phase 7.2)
===================================================
Tracks live/paper performance against backtest baselines.
If a strategy's Profit Factor (PF) degrades below 60% of baseline
for 3 consecutive weeks, it triggers a 'shadow-mode' demotion alert.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("jarvis_trader.analytics.drift")

# Baseline PF source: Gate v2 Verdicts
VERDICTS_DIR = Path("data/gate_v2_verdicts")

class DriftDetector:
    def __init__(self, db_manager):
        self.db = db_manager
        self.drift_state_file = Path("data/drift_state.json")
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        self.drift_state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.drift_state_file.exists():
            self.drift_state_file.write_text("{}", encoding="utf-8")

    def _load_state(self) -> dict:
        try:
            return json.loads(self.drift_state_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, state: dict):
        self.drift_state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _get_baseline_pf(self, symbol: str) -> float:
        """Fetch baseline min_pf from the latest Gate v2 verdict."""
        try:
            # Find latest file for symbol
            files = list(VERDICTS_DIR.glob(f"{symbol.upper()}_*.json"))
            if not files:
                return 1.2 # Default floor

            # Sort by modification time to get latest
            latest_file = max(files, key=os.path.getmtime)
            data = json.loads(latest_file.read_text(encoding="utf-8"))

            # Try to get fixed_params_min_pf or similar
            metrics = data.get("gate_v2_metrics", {})
            return float(metrics.get("fixed_params_min_pf", 1.2))
        except Exception as e:
            logger.debug(f"[Drift] Failed to load baseline for {symbol}: {e}")
            return 1.2

    async def check_drift(self, symbol: str) -> dict:
        """
        Evaluate PF drift for the given symbol over the last 7 days.
        """
        logger.info(f"[Drift] Checking performance drift for {symbol}")

        baseline_pf = self._get_baseline_pf(symbol)
        threshold_pf = baseline_pf * 0.60

        # 1. Calculate Live PF for last 7 days
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        sql = """
            SELECT
                SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END) as gross_profit,
                SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END) as gross_loss,
                COUNT(*) as trade_count
            FROM paper_trades
            WHERE symbol = ? AND exit_time >= ? AND status = 'closed'
        """

        try:
            row = self.db.fetch_one(sql, (symbol.upper(), seven_days_ago))

            if not row or row["trade_count"] < 3:
                return {"status": "insufficient_data", "symbol": symbol}

            gross_profit = float(row["gross_profit"] or 0.0)
            gross_loss = float(row["gross_loss"] or 0.0)
            live_pf = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 1.0)

            # 2. Update Drift State
            state = self._load_state()
            sym_state = state.get(symbol, {"consecutive_weeks": 0, "history": []})

            is_drifting = live_pf < threshold_pf

            if is_drifting:
                sym_state["consecutive_weeks"] += 1
            else:
                sym_state["consecutive_weeks"] = 0

            sym_state["history"].append({
                "date": datetime.now(timezone.utc).isoformat(),
                "pf": round(live_pf, 3),
                "baseline": baseline_pf,
                "is_below_60pct": is_drifting
            })

            # Keep history manageable
            sym_state["history"] = sym_state["history"][-12:]
            state[symbol] = sym_state
            self._save_state(state)

            # 3. Decision
            alert = False
            if sym_state["consecutive_weeks"] >= 3:
                alert = True
                logger.critical(
                    f"🚨 [DRIFT ALERT] {symbol} PF ({live_pf:.2f}) < 60% of baseline ({baseline_pf:.2f}) "
                    f"for 3 consecutive weeks! Strategy eligible for demotion."
                )

            return {
                "symbol": symbol,
                "live_pf": round(live_pf, 3),
                "baseline_pf": round(baseline_pf, 3),
                "threshold_pf": round(threshold_pf, 3),
                "consecutive_fail_weeks": sym_state["consecutive_weeks"],
                "trigger_alert": alert
            }

        except Exception as e:
            logger.error(f"[Drift] Check failed for {symbol}: {e}")
            return {"error": str(e)}
