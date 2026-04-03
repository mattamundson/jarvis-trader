"""
Multi-Timeframe Confirmation Module
Phase 3 feature — confirms 1h signals against 4h and daily bar alignment.

Currently a stub. Will be expanded when multi-timeframe data feed is available.
The 1h pipeline already runs. This module adds optional higher-timeframe gates.

Design:
  1h signal (LONG/SHORT) → check 4h STC → check Daily STC → confirmed signal
  If any higher timeframe disagrees, signal is SKIPPED or DOWNGRADED.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Literal, Optional

logger = logging.getLogger(__name__)

Timeframe = Literal["1h", "4h", "1d"]
Bias = Literal["BULL", "BEAR", "NEUTRAL"]


@dataclass
class TimeframeSignal:
    """STC signal state for a single timeframe."""

    timeframe: Timeframe
    symbol: str
    stc_os: Optional[float] = None  # STC value (< 20 = bullish)
    stc_ob: Optional[float] = None  # STC value (> 80 = bearish)
    bias: Bias = "NEUTRAL"
    regime: Optional[str] = None
    timestamp: Optional[datetime] = None

    @property
    def is_bullish(self) -> bool:
        return self.stc_os is not None and self.stc_os < 20

    @property
    def is_bearish(self) -> bool:
        return self.stc_ob is not None and self.stc_ob > 80


@dataclass
class MTFConfirmationResult:
    """Result of multi-timeframe confirmation check."""

    symbol: str
    base_signal: str  # LONG, SHORT, HOLD
    confirmed: bool
    confirmation_level: int  # 1 = 1h only, 2 = 1h+4h, 3 = all three
    timeframe_signals: Dict[str, TimeframeSignal] = field(default_factory=dict)
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MTFConfirmationFilter:
    """
    Multi-timeframe confirmation filter.

    Phase 3 feature — currently pass-through mode (all signals pass).
    Will require 4h + daily alignment when live data feed is available.

    Usage:
        filter = MTFConfirmationFilter(require_4h=True, require_daily=False)
        result = filter.check(symbol="MES", base_signal="LONG", stc_1h=12.5)
        if result.confirmed:
            # proceed with trade

    Configuration:
        require_4h: bool — if True, 4h bar must agree with 1h signal
        require_daily: bool — if True, daily bar must agree with 1h signal
        strict: bool — if True, NEUTRAL on higher TF blocks the signal
    """

    def __init__(
        self,
        require_4h: bool = False,
        require_daily: bool = False,
        strict: bool = False,
    ):
        self.require_4h = require_4h
        self.require_daily = require_daily
        self.strict = strict
        self._enabled = False  # Disabled until Phase 3
        self._cache: Dict[str, Dict[str, TimeframeSignal]] = {}
        logger.info(
            f"MTFConfirmationFilter initialized (stub mode — Phase 3 feature). "
            f"require_4h={require_4h}, require_daily={require_daily}"
        )

    def check(
        self,
        symbol: str,
        base_signal: str,
        stc_1h: Optional[float] = None,
        stc_4h: Optional[float] = None,
        stc_daily: Optional[float] = None,
    ) -> MTFConfirmationResult:
        """
        Check if a 1h signal is confirmed by higher timeframes.
        In stub mode, all signals pass through (confirmed=True).
        """
        if not self._enabled:
            return MTFConfirmationResult(
                symbol=symbol,
                base_signal=base_signal,
                confirmed=True,
                confirmation_level=1,
                reason="MTF filter disabled (stub mode — Phase 3 feature)",
            )

        # Phase 3: Real implementation will check stc_4h and stc_daily
        confirmed = True
        level = 1
        reason_parts = [f"1h signal: {base_signal}"]

        if self.require_4h and stc_4h is not None:
            if base_signal == "LONG" and stc_4h >= 20:
                confirmed = False if self.strict else confirmed
                reason_parts.append(f"4h STC={stc_4h:.1f} NOT bullish (<20 required)")
            elif base_signal == "SHORT" and stc_4h <= 80:
                confirmed = False if self.strict else confirmed
                reason_parts.append(f"4h STC={stc_4h:.1f} NOT bearish (>80 required)")
            else:
                level = max(level, 2)
                reason_parts.append(f"4h confirmed (STC={stc_4h:.1f})")

        if self.require_daily and stc_daily is not None:
            if base_signal == "LONG" and stc_daily >= 20:
                confirmed = False if self.strict else confirmed
                reason_parts.append(f"Daily STC={stc_daily:.1f} NOT bullish")
            elif base_signal == "SHORT" and stc_daily <= 80:
                confirmed = False if self.strict else confirmed
                reason_parts.append(f"Daily STC={stc_daily:.1f} NOT bearish")
            else:
                level = max(level, 3)
                reason_parts.append(f"Daily confirmed (STC={stc_daily:.1f})")

        return MTFConfirmationResult(
            symbol=symbol,
            base_signal=base_signal,
            confirmed=confirmed,
            confirmation_level=level,
            reason=" | ".join(reason_parts),
        )

    def update_cache(self, symbol: str, timeframe: Timeframe, signal: TimeframeSignal):
        """Update the cached signal for a symbol/timeframe pair."""
        if symbol not in self._cache:
            self._cache[symbol] = {}
        self._cache[symbol][timeframe] = signal

    def get_cached(self, symbol: str, timeframe: Timeframe) -> Optional[TimeframeSignal]:
        """Get the last cached signal for a symbol/timeframe."""
        return self._cache.get(symbol, {}).get(timeframe)

    def health_check(self) -> dict:
        return {
            "enabled": self._enabled,
            "mode": "stub",
            "phase": "paper_trading",
            "require_4h": self.require_4h,
            "require_daily": self.require_daily,
            "strict": self.strict,
            "cached_symbols": list(self._cache.keys()),
            "note": "MTF confirmation will be enabled in Phase 3",
        }
