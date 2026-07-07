"""
KAIROS — Watchers
==================
Pure-Python rule-based market observation classes.
ZERO LLM calls. All watchers are tolerant of missing data.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# ── Data Structures ────────────────────────────────────────────────────────


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Observation:
    timestamp: str
    watcher: str
    severity: Severity
    message: str
    data: dict = field(default_factory=dict)
    notify: bool = False  # Should trigger WhatsApp notification?
    symbol: Optional[str] = None


# ── Base Watcher ABC ───────────────────────────────────────────────────────


class BaseWatcher(ABC):
    name: str = "base"

    @abstractmethod
    async def check(self, market_snapshot: dict) -> list[Observation]:
        """Run check, return observations (may be empty list)."""

    def _obs(
        self,
        severity: Severity,
        message: str,
        data: dict = None,
        notify: bool = False,
        symbol: str = None,
    ) -> Observation:
        """Helper to create an observation."""
        return Observation(
            timestamp=datetime.now().isoformat(),
            watcher=self.name,
            severity=severity,
            message=message,
            data=data or {},
            notify=notify,
            symbol=symbol,
        )


# ── 1. RegimeChangeWatcher ─────────────────────────────────────────────────


class RegimeChangeWatcher(BaseWatcher):
    """
    Fires WARNING + notify=True when a symbol's market regime transitions.
    Reads market_snapshot["symbols"][symbol]["regime"].
    """

    name = "regime_change"

    def __init__(self) -> None:
        self._last_regimes: dict[str, str] = {}

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        symbols = market_snapshot.get("symbols", {})

        for symbol, data in symbols.items():
            if not isinstance(data, dict):
                continue
            current_regime = data.get("regime")
            if current_regime is None:
                continue

            last = self._last_regimes.get(symbol)
            if last is not None and last != current_regime:
                observations.append(
                    self._obs(
                        severity=Severity.WARNING,
                        message=(f"{symbol} regime changed: {last} → {current_regime}"),
                        data={"symbol": symbol, "from": last, "to": current_regime},
                        notify=True,
                        symbol=symbol,
                    )
                )
                logger.info(f"RegimeChangeWatcher: {symbol} {last} → {current_regime}")

            self._last_regimes[symbol] = current_regime

        return observations


# ── 2. STCCrossoverWatcher ─────────────────────────────────────────────────


class STCCrossoverWatcher(BaseWatcher):
    """
    Detects STC crossing the OS=15 (oversold) or OB=83 (overbought) thresholds.
    Reads market_snapshot["symbols"][symbol]["stc"].
    Per-instrument OB thresholds from signals.py INSTRUMENT_PARAMS.
    """

    name = "stc_crossover"

    # Per-symbol OB thresholds matching INSTRUMENT_PARAMS in signals.py
    _OB_THRESHOLDS: dict[str, float] = {
        "MNQ": 92.0,
        "MCL": 83.0,
        "MGC": 88.0,
        "SPY": 88.0,
        "MES": 83.0,
    }
    _DEFAULT_OB = 83.0
    _OS = 15.0

    def __init__(self) -> None:
        self._last_stc: dict[str, float] = {}

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        symbols = market_snapshot.get("symbols", {})

        for symbol, data in symbols.items():
            if not isinstance(data, dict):
                continue
            current_stc = data.get("stc")
            if current_stc is None:
                continue

            try:
                current_stc = float(current_stc)
            except (TypeError, ValueError):
                continue

            ob_threshold = self._OB_THRESHOLDS.get(symbol, self._DEFAULT_OB)
            last = self._last_stc.get(symbol)

            if last is not None:
                # Crossed into oversold territory (above OS → below OS)
                if last >= self._OS and current_stc < self._OS:
                    observations.append(
                        self._obs(
                            severity=Severity.WARNING,
                            message=(
                                f"{symbol} STC crossed into oversold: "
                                f"{last:.1f} → {current_stc:.1f} (threshold={self._OS})"
                            ),
                            data={
                                "symbol": symbol,
                                "stc_prev": last,
                                "stc_current": current_stc,
                                "threshold": self._OS,
                                "direction": "oversold",
                            },
                            notify=True,
                            symbol=symbol,
                        )
                    )
                # Crossed into overbought territory (below OB → above OB)
                elif last <= ob_threshold and current_stc > ob_threshold:
                    observations.append(
                        self._obs(
                            severity=Severity.WARNING,
                            message=(
                                f"{symbol} STC crossed into overbought: "
                                f"{last:.1f} → {current_stc:.1f} (threshold={ob_threshold})"
                            ),
                            data={
                                "symbol": symbol,
                                "stc_prev": last,
                                "stc_current": current_stc,
                                "threshold": ob_threshold,
                                "direction": "overbought",
                            },
                            notify=True,
                            symbol=symbol,
                        )
                    )

            self._last_stc[symbol] = current_stc

        return observations


# ── 3. RiskLimitWatcher ────────────────────────────────────────────────────


class RiskLimitWatcher(BaseWatcher):
    """
    Monitors approaching risk limits from SafetyLayer.get_status().
    Reads market_snapshot["risk_status"].
    Fields expected: daily_pnl, daily_loss_limit, drawdown_pct, max_drawdown_pct.
    """

    name = "risk_limit"

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        risk = market_snapshot.get("risk_status", {})
        if not isinstance(risk, dict) or not risk:
            return observations

        daily_pnl = risk.get("daily_pnl")
        daily_loss_limit = risk.get("daily_loss_limit")
        drawdown_pct = risk.get("drawdown_pct")

        # Daily loss limit checks
        if daily_pnl is not None and daily_loss_limit is not None:
            try:
                pnl = float(daily_pnl)
                limit = float(daily_loss_limit)
                if limit < 0 and pnl < 0:
                    utilization = pnl / limit  # both negative → ratio 0..1+
                    if utilization >= 0.90:
                        observations.append(
                            self._obs(
                                severity=Severity.CRITICAL,
                                message=(
                                    f"Daily loss at {utilization*100:.1f}% of limit "
                                    f"(PnL={pnl:.2f}, limit={limit:.2f})"
                                ),
                                data={
                                    "daily_pnl": pnl,
                                    "daily_loss_limit": limit,
                                    "utilization_pct": round(utilization * 100, 1),
                                },
                                notify=True,
                            )
                        )
                    elif utilization >= 0.80:
                        observations.append(
                            self._obs(
                                severity=Severity.WARNING,
                                message=(
                                    f"Daily loss approaching limit: {utilization*100:.1f}% used "
                                    f"(PnL={pnl:.2f}, limit={limit:.2f})"
                                ),
                                data={
                                    "daily_pnl": pnl,
                                    "daily_loss_limit": limit,
                                    "utilization_pct": round(utilization * 100, 1),
                                },
                                notify=False,
                            )
                        )
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        # Drawdown check
        if drawdown_pct is not None:
            try:
                dd = float(drawdown_pct)
                if dd > 5.0:
                    observations.append(
                        self._obs(
                            severity=Severity.INFO,
                            message=(f"Portfolio drawdown exceeds 5%: current={dd:.1f}%"),
                            data={"drawdown_pct": dd},
                            notify=False,
                        )
                    )
            except (TypeError, ValueError):
                pass

        return observations


# ── 4. VIXSpikeWatcher ─────────────────────────────────────────────────────


class VIXSpikeWatcher(BaseWatcher):
    """
    Fires on rapid VIX movements within a rolling 15-minute window.
    Reads market_snapshot["vix"] (float or None).
    WARNING: >1.5 pt move in 15 min.
    CRITICAL: >3.0 pt move in 15 min.
    """

    name = "vix_spike"
    _WINDOW_MINUTES = 15
    _WARN_MOVE = 1.5
    _CRITICAL_MOVE = 3.0

    def __init__(self) -> None:
        # Deque of (datetime, float) pairs — rolling 15-min history
        self._vix_history: deque[tuple[datetime, float]] = deque()

    def _prune(self) -> None:
        """Remove entries older than 15 minutes."""
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(minutes=self._WINDOW_MINUTES)
        while self._vix_history and self._vix_history[0][0] < cutoff:
            self._vix_history.popleft()

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        vix_raw = market_snapshot.get("vix")
        if vix_raw is None:
            return observations

        try:
            vix = float(vix_raw)
        except (TypeError, ValueError):
            return observations

        now = datetime.now()
        self._prune()
        self._vix_history.append((now, vix))

        if len(self._vix_history) < 2:
            return observations

        oldest_vix = self._vix_history[0][1]
        move = abs(vix - oldest_vix)

        if move >= self._CRITICAL_MOVE:
            observations.append(
                self._obs(
                    severity=Severity.CRITICAL,
                    message=(
                        f"VIX spike CRITICAL: moved {move:.2f} pts in "
                        f"{self._WINDOW_MINUTES} min "
                        f"({oldest_vix:.2f} → {vix:.2f})"
                    ),
                    data={
                        "vix_current": vix,
                        "vix_15min_ago": oldest_vix,
                        "move": round(move, 2),
                        "window_minutes": self._WINDOW_MINUTES,
                    },
                    notify=True,
                )
            )
        elif move >= self._WARN_MOVE:
            observations.append(
                self._obs(
                    severity=Severity.WARNING,
                    message=(
                        f"VIX spike WARNING: moved {move:.2f} pts in "
                        f"{self._WINDOW_MINUTES} min "
                        f"({oldest_vix:.2f} → {vix:.2f})"
                    ),
                    data={
                        "vix_current": vix,
                        "vix_15min_ago": oldest_vix,
                        "move": round(move, 2),
                        "window_minutes": self._WINDOW_MINUTES,
                    },
                    notify=True,
                )
            )

        return observations


# ── 5. VolumeAnomalyWatcher ────────────────────────────────────────────────


class VolumeAnomalyWatcher(BaseWatcher):
    """
    Detects unusual volume relative to rolling average.
    Reads market_snapshot["symbols"][symbol]["volume"].
    INFO: >1.5x average. WARNING + notify: >2.5x average.
    """

    name = "volume_anomaly"
    _INFO_MULT = 1.5
    _WARN_MULT = 2.5
    _WINDOW = 20  # bars used for rolling average

    def __init__(self) -> None:
        # Rolling volume history per symbol
        self._vol_history: dict[str, deque[float]] = {}
        self._avg_volumes: dict[str, float] = {}

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        symbols = market_snapshot.get("symbols", {})

        for symbol, data in symbols.items():
            if not isinstance(data, dict):
                continue
            vol_raw = data.get("volume")
            if vol_raw is None:
                continue
            try:
                volume = float(vol_raw)
            except (TypeError, ValueError):
                continue

            if symbol not in self._vol_history:
                self._vol_history[symbol] = deque(maxlen=self._WINDOW)

            self._vol_history[symbol].append(volume)

            if len(self._vol_history[symbol]) < 3:
                continue  # Need at least a few bars to compute average

            avg = sum(self._vol_history[symbol]) / len(self._vol_history[symbol])
            self._avg_volumes[symbol] = avg

            if avg <= 0:
                continue

            ratio = volume / avg

            if ratio >= self._WARN_MULT:
                observations.append(
                    self._obs(
                        severity=Severity.WARNING,
                        message=(
                            f"{symbol} volume anomaly: {ratio:.1f}x average "
                            f"(current={volume:,.0f}, avg={avg:,.0f})"
                        ),
                        data={
                            "symbol": symbol,
                            "volume": volume,
                            "avg_volume": round(avg, 2),
                            "ratio": round(ratio, 2),
                        },
                        notify=True,
                        symbol=symbol,
                    )
                )
            elif ratio >= self._INFO_MULT:
                observations.append(
                    self._obs(
                        severity=Severity.INFO,
                        message=(
                            f"{symbol} elevated volume: {ratio:.1f}x average "
                            f"(current={volume:,.0f}, avg={avg:,.0f})"
                        ),
                        data={
                            "symbol": symbol,
                            "volume": volume,
                            "avg_volume": round(avg, 2),
                            "ratio": round(ratio, 2),
                        },
                        notify=False,
                        symbol=symbol,
                    )
                )

        return observations


# ── 6. SpreadWideningWatcher ───────────────────────────────────────────────


class SpreadWideningWatcher(BaseWatcher):
    """
    Fires WARNING when bid-ask spread widens beyond 2x the established baseline.
    Reads market_snapshot["symbols"][symbol]["spread"] (float).
    Baseline is established as rolling median of first N observations.
    """

    name = "spread_widening"
    _WARN_MULT = 2.0
    _BASELINE_WINDOW = 10  # number of bars to establish baseline

    def __init__(self) -> None:
        self._spread_history: dict[str, deque[float]] = {}
        self._normal_spreads: dict[str, float] = {}

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        symbols = market_snapshot.get("symbols", {})

        for symbol, data in symbols.items():
            if not isinstance(data, dict):
                continue
            spread_raw = data.get("spread")
            if spread_raw is None:
                continue
            try:
                spread = float(spread_raw)
            except (TypeError, ValueError):
                continue
            if spread <= 0:
                continue

            if symbol not in self._spread_history:
                self._spread_history[symbol] = deque(maxlen=self._BASELINE_WINDOW)

            self._spread_history[symbol].append(spread)

            if len(self._spread_history[symbol]) < self._BASELINE_WINDOW:
                # Still calibrating baseline
                continue

            # Use median of history as normal spread
            sorted_history = sorted(self._spread_history[symbol])
            mid = len(sorted_history) // 2
            normal = sorted_history[mid]
            self._normal_spreads[symbol] = normal

            if normal <= 0:
                continue

            ratio = spread / normal

            if ratio >= self._WARN_MULT:
                observations.append(
                    self._obs(
                        severity=Severity.WARNING,
                        message=(
                            f"{symbol} spread widening: {ratio:.1f}x normal "
                            f"(spread={spread:.4f}, normal={normal:.4f})"
                        ),
                        data={
                            "symbol": symbol,
                            "spread": spread,
                            "normal_spread": round(normal, 6),
                            "ratio": round(ratio, 2),
                        },
                        notify=False,
                        symbol=symbol,
                    )
                )

        return observations


# ── 7. CorrelationBreakWatcher ─────────────────────────────────────────────


class CorrelationBreakWatcher(BaseWatcher):
    """
    Monitors MES/MNQ price correlation.
    Normally these move together (correlation > 0.8).
    Fires WARNING when 15-min returns diverge by >1.5%.
    """

    name = "correlation_break"
    _DIVERGE_THRESHOLD = 0.015  # 1.5% divergence in returns
    _SYMBOL_A = "MES"
    _SYMBOL_B = "MNQ"
    _WINDOW = 3  # bars in rolling window for return calculation

    def __init__(self) -> None:
        self._prices_a: deque[float] = deque(maxlen=self._WINDOW + 1)
        self._prices_b: deque[float] = deque(maxlen=self._WINDOW + 1)

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        symbols = market_snapshot.get("symbols", {})

        data_a = symbols.get(self._SYMBOL_A, {})
        data_b = symbols.get(self._SYMBOL_B, {})

        if not isinstance(data_a, dict) or not isinstance(data_b, dict):
            return observations

        price_a_raw = data_a.get("price")
        price_b_raw = data_b.get("price")

        if price_a_raw is None or price_b_raw is None:
            return observations

        try:
            price_a = float(price_a_raw)
            price_b = float(price_b_raw)
        except (TypeError, ValueError):
            return observations

        self._prices_a.append(price_a)
        self._prices_b.append(price_b)

        if len(self._prices_a) < 2 or len(self._prices_b) < 2:
            return observations

        # Compute simple return from oldest to newest price in window
        prev_a = list(self._prices_a)[0]
        prev_b = list(self._prices_b)[0]

        if prev_a <= 0 or prev_b <= 0:
            return observations

        return_a = (price_a - prev_a) / prev_a
        return_b = (price_b - prev_b) / prev_b
        divergence = abs(return_a - return_b)

        if divergence >= self._DIVERGE_THRESHOLD:
            observations.append(
                self._obs(
                    severity=Severity.WARNING,
                    message=(
                        f"Correlation break: {self._SYMBOL_A}/{self._SYMBOL_B} "
                        f"returns diverged by {divergence*100:.2f}% "
                        f"({self._SYMBOL_A}={return_a*100:.2f}%, "
                        f"{self._SYMBOL_B}={return_b*100:.2f}%)"
                    ),
                    data={
                        "symbol_a": self._SYMBOL_A,
                        "symbol_b": self._SYMBOL_B,
                        "return_a": round(return_a, 6),
                        "return_b": round(return_b, 6),
                        "divergence": round(divergence, 6),
                        "price_a": price_a,
                        "price_b": price_b,
                    },
                    notify=False,
                )
            )

        return observations
