"""
Tilt Detection System — adapted from Claude Code's "frustration detection."
Detects revenge trading, rapid position changes, and behavioral patterns
that indicate the trader is operating emotionally rather than systematically.
Pure Python rules — NO LLM in detection path.
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TiltState:
    is_tilted: bool
    tilt_score: float  # 0.0 (calm) to 1.0 (full tilt)
    tilt_indicators: list[str]  # Which indicators are firing
    position_size_multiplier: float  # 1.0 normal → 0.75 → 0.5 → 0.25 → 0.0 halted
    cooldown_until: Optional[datetime] = None
    severity: str = "none"  # "none" | "caution" | "warning" | "critical"


class TiltDetector:
    """
    Detects emotional/behavioral trading patterns that indicate tilt.

    Tilt indicators (each adds to tilt_score):
    1. Consecutive losses: 3+ → 0.2, 5+ → 0.4, 7+ → halt
    2. Rapid position changes: 5+ trades in 30 min → 0.3
    3. Revenge sizing: position size increased after a loss → 0.25
    4. Rapid re-entry: re-entered same symbol < 5 min after stop-out → 0.25
    5. Risk override: risk manager vetoed 2+ times in 4h → 0.2
    6. Drawdown acceleration: drawdown rate increasing → 0.2

    Position size multiplier:
    - score < 0.3: 1.0 (normal)
    - score 0.3-0.5: 0.75 (caution)
    - score 0.5-0.7: 0.5 (warning)
    - score 0.7-0.85: 0.25 (tilt)
    - score > 0.85: 0.0 (halted — must cool down for 1 hour)
    """

    # Time windows for detection
    RAPID_TRADE_WINDOW_MINUTES = 30
    RAPID_TRADE_THRESHOLD = 5
    REVENGE_REENTRY_MINUTES = 5
    RISK_OVERRIDE_WINDOW_HOURS = 4
    DRAWDOWN_WINDOW_MINUTES = 60

    def __init__(self, config=None, loss_tracker=None):
        self._config = config
        self._loss_tracker = loss_tracker

        # Trade history (rolling window)
        # Each entry: {"timestamp": datetime, "symbol": str, "direction": str,
        #              "size": int, "entry_price": float, "pnl": float|None}
        self._recent_trades: deque = deque(maxlen=100)
        # Stop-out records: {"timestamp": datetime, "symbol": str}
        self._stop_outs: deque = deque(maxlen=20)
        # Risk veto records: {"timestamp": datetime}
        self._risk_vetoes: deque = deque(maxlen=10)

        # Drawdown tracking: {"timestamp": datetime, "drawdown_pct": float}
        self._drawdown_history: deque = deque(maxlen=120)

        # Cooldown state
        self._cooldown_until: Optional[datetime] = None

    # ── Recording API ──────────────────────────────────────────────────────

    def record_trade(
        self,
        symbol: str,
        direction: str,
        size: int,
        entry_price: float,
        pnl: Optional[float] = None,
        is_stop_out: bool = False,
    ) -> None:
        """Record a completed or entered trade for tilt analysis."""
        entry = {
            "timestamp": datetime.now(),
            "symbol": symbol,
            "direction": direction,
            "size": size,
            "entry_price": entry_price,
            "pnl": pnl,
        }
        self._recent_trades.append(entry)
        if is_stop_out or (pnl is not None and pnl < 0):
            self._stop_outs.append({"timestamp": datetime.now(), "symbol": symbol})

    def record_risk_veto(self) -> None:
        """Record that the risk manager vetoed a trade order."""
        self._risk_vetoes.append({"timestamp": datetime.now()})

    def update_drawdown(self, drawdown_pct: float) -> None:
        """Update drawdown tracking. Call this periodically with current drawdown %."""
        self._drawdown_history.append({"timestamp": datetime.now(), "drawdown_pct": drawdown_pct})

    # ── Core Check ────────────────────────────────────────────────────────

    def check(self) -> TiltState:
        """
        Evaluate all tilt indicators and return current tilt state.
        This is the primary entry point — called by safety layer on every order.
        """
        # If currently in cooldown, return halted state immediately
        if self._cooldown_until and datetime.now() < self._cooldown_until:
            return TiltState(
                is_tilted=True,
                tilt_score=1.0,
                tilt_indicators=["cooldown_active"],
                position_size_multiplier=0.0,
                cooldown_until=self._cooldown_until,
                severity="critical",
            )
        elif self._cooldown_until:
            # Cooldown expired — clear it
            self._cooldown_until = None

        indicators: list[str] = []
        tilt_score = 0.0

        # 1. Consecutive losses
        consecutive = self._get_consecutive_losses()

        if consecutive >= 7:
            tilt_score += 0.6
            indicators.append(f"consecutive_losses_{consecutive}")
            # Auto-start cooldown for extreme streak
            if not self._cooldown_until:
                self._cooldown_until = datetime.now() + timedelta(hours=1)
        elif consecutive >= 5:
            tilt_score += 0.4
            indicators.append(f"consecutive_losses_{consecutive}")
        elif consecutive >= 3:
            tilt_score += 0.2
            indicators.append(f"consecutive_losses_{consecutive}")

        # 2. Rapid position changes (churning)
        rapid_count = self._count_rapid_trades()
        if rapid_count >= self.RAPID_TRADE_THRESHOLD:
            tilt_score += 0.3
            indicators.append(f"rapid_trades_{rapid_count}_in_30min")

        # 3. Revenge sizing (increased position size after a loss)
        if self._detect_revenge_sizing():
            tilt_score += 0.25
            indicators.append("revenge_sizing")

        # 4. Rapid re-entry after stop-out on same symbol
        if self._detect_rapid_reentry():
            tilt_score += 0.25
            indicators.append("rapid_reentry_after_stop")

        # 5. Multiple risk manager vetoes in last 4 hours
        veto_count = self._count_recent_vetoes()
        if veto_count >= 2:
            tilt_score += 0.2
            indicators.append(f"risk_overrides_{veto_count}")

        # 6. Drawdown acceleration (rate of loss increasing)
        if self._detect_drawdown_acceleration():
            tilt_score += 0.2
            indicators.append("drawdown_accelerating")

        tilt_score = min(tilt_score, 1.0)
        is_tilted = tilt_score >= 0.3

        # Determine severity and position size multiplier
        if tilt_score < 0.3:
            severity = "none"
            multiplier = 1.0
        elif tilt_score < 0.5:
            severity = "caution"
            multiplier = 0.75
        elif tilt_score < 0.7:
            severity = "warning"
            multiplier = 0.5
        elif tilt_score < 0.85:
            severity = "critical"
            multiplier = 0.25
        else:
            severity = "critical"
            multiplier = 0.0
            if not self._cooldown_until:
                self._cooldown_until = datetime.now() + timedelta(hours=1)

        state = TiltState(
            is_tilted=is_tilted,
            tilt_score=round(tilt_score, 3),
            tilt_indicators=indicators,
            position_size_multiplier=multiplier,
            cooldown_until=self._cooldown_until,
            severity=severity,
        )

        if is_tilted:
            logger.warning(
                "Tilt detected: score=%.2f, indicators=%s, multiplier=%.2f",
                tilt_score,
                indicators,
                multiplier,
            )

        return state

    def get_position_multiplier(self) -> float:
        """Quick accessor — returns just the multiplier for wiring into the safety layer."""
        return self.check().position_size_multiplier

    # ── Status / Reset ────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return full tilt status dict suitable for an API endpoint."""
        state = self.check()
        return {
            "is_tilted": state.is_tilted,
            "tilt_score": state.tilt_score,
            "severity": state.severity,
            "tilt_indicators": state.tilt_indicators,
            "position_size_multiplier": state.position_size_multiplier,
            "cooldown_until": state.cooldown_until.isoformat() if state.cooldown_until else None,
            "recent_trade_count": len(self._recent_trades),
            "consecutive_losses": self._get_consecutive_losses(),
            "rapid_trades_30min": self._count_rapid_trades(),
            "recent_vetoes": self._count_recent_vetoes(),
        }

    def reset(self) -> None:
        """Manually reset all tilt state (for testing or human override)."""
        self._recent_trades.clear()
        self._stop_outs.clear()
        self._risk_vetoes.clear()
        self._drawdown_history.clear()
        self._cooldown_until = None
        logger.info("TiltDetector: state reset manually")

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_consecutive_losses(self) -> int:
        """
        Return consecutive loss count, preferring the loss_tracker if available
        (which has persisted state across restarts).
        """
        if self._loss_tracker is not None and hasattr(self._loss_tracker, "get_consecutive_losses"):
            try:
                return int(self._loss_tracker.get_consecutive_losses())
            except Exception:
                pass
        return self._count_consecutive_losses()

    def _count_consecutive_losses(self) -> int:
        """Count trailing consecutive losses from in-memory trade history."""
        count = 0
        for trade in reversed(list(self._recent_trades)):
            pnl = trade.get("pnl")
            if pnl is not None and pnl < 0:
                count += 1
            elif pnl is not None:
                break
            # trades with pnl=None (open) are skipped
        return count

    def _count_rapid_trades(self) -> int:
        """Count how many trades occurred in the last 30 minutes."""
        cutoff = datetime.now() - timedelta(minutes=self.RAPID_TRADE_WINDOW_MINUTES)
        return sum(1 for t in self._recent_trades if t["timestamp"] > cutoff)

    def _detect_revenge_sizing(self) -> bool:
        """
        Return True when the most recent trade increased position size after a loss.
        Classic revenge-trading signature: lose → bet bigger to get it back.
        """
        recent = list(self._recent_trades)
        if len(recent) < 2:
            return False
        last = recent[-1]
        second_last = recent[-2]
        second_last_pnl = second_last.get("pnl")
        return (
            second_last_pnl is not None
            and second_last_pnl < 0
            and last.get("size", 0) > second_last.get("size", 0)
        )

    def _detect_rapid_reentry(self) -> bool:
        """
        Return True if a trade was placed on the same symbol within 5 minutes
        of being stopped out on that symbol.
        """
        cutoff = datetime.now() - timedelta(minutes=self.REVENGE_REENTRY_MINUTES)
        recent_stops = [s for s in self._stop_outs if s["timestamp"] > cutoff]
        if not recent_stops:
            return False
        recent_trade_symbols = {t["symbol"] for t in self._recent_trades if t["timestamp"] > cutoff}
        stop_symbols = {s["symbol"] for s in recent_stops}
        return bool(recent_trade_symbols & stop_symbols)

    def _count_recent_vetoes(self) -> int:
        """Count risk manager vetoes in the last 4 hours."""
        cutoff = datetime.now() - timedelta(hours=self.RISK_OVERRIDE_WINDOW_HOURS)
        return sum(1 for v in self._risk_vetoes if v["timestamp"] > cutoff)

    def _detect_drawdown_acceleration(self) -> bool:
        """
        Return True if the drawdown rate is accelerating (getting worse faster).
        Compares the average drawdown in the first half of the window vs the second half.
        A 20% increase in the second half vs first half is considered acceleration.
        """
        window_start = datetime.now() - timedelta(minutes=self.DRAWDOWN_WINDOW_MINUTES)
        recent_dd = [d for d in self._drawdown_history if d["timestamp"] > window_start]
        if len(recent_dd) < 4:
            return False
        mid = len(recent_dd) // 2
        first_half = recent_dd[:mid]
        second_half = recent_dd[mid:]
        first_avg = sum(d["drawdown_pct"] for d in first_half) / len(first_half)
        second_avg = sum(d["drawdown_pct"] for d in second_half) / len(second_half)
        # Drawdown is expressed as a positive percentage (e.g. 3.5 = 3.5% down).
        # Increasing means it's getting worse — flag when second half is 20% worse.
        return second_avg > first_avg * 1.2
