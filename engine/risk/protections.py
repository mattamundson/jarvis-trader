"""
Advanced Risk Protections
=========================
Port of Freqtrade's "Protections" system.
Ensures the engine stays safe during extreme volatility or poor performance.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List

logger = logging.getLogger("jarvis_trader.risk.protections")

class RiskProtections:
    def __init__(self, db_manager):
        self.db = db_manager
        self.cooldown_periods: Dict[str, datetime] = {} # symbol -> expiry_time

    def check_cooldown(self, symbol: str) -> bool:
        """Check if a symbol is in cooldown after a loss."""
        if symbol in self.cooldown_periods:
            if datetime.now() < self.cooldown_periods[symbol]:
                logger.info(f"🛡️ Protection: {symbol} in cooldown until {self.cooldown_periods[symbol]}")
                return True
            else:
                del self.cooldown_periods[symbol]
        return False

    def activate_cooldown(self, symbol: str, minutes: int = 60):
        """Put a symbol in cooldown."""
        self.cooldown_periods[symbol] = datetime.now() + timedelta(minutes=minutes)
        logger.info(f"🛡️ Protection: Activated {minutes}m cooldown for {symbol}")

    def check_max_drawdown(self, pnl_history: List[float], max_drawdown_pct: float = 0.10) -> bool:
        """
        Check if the current drawdown exceeds the threshold.
        pnl_history should be a list of equity values.
        """
        if not pnl_history:
            return False

        peak = pnl_history[0]
        max_dd = 0.0

        for val in pnl_history:
            if val > peak:
                peak = val
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd

        if max_dd > max_drawdown_pct:
            logger.warning(f"🚨 Protection: Max Drawdown ({max_dd:.2%}) exceeded limit ({max_drawdown_pct:.2%})")
            return True
        return False

    def check_consecutive_losses(self, last_trades: List[Dict], limit: int = 3) -> bool:
        """Check for too many consecutive losses."""
        if len(last_trades) < limit:
            return False

        consecutive = 0
        for trade in last_trades[:limit]:
            if trade.get('pnl', 0) < 0:
                consecutive += 1
            else:
                break

        if consecutive >= limit:
            logger.warning(f"🚨 Protection: {consecutive} consecutive losses detected.")
            return True
        return False
