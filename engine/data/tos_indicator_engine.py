"""
TOS Indicator Engine — computes derivatives from live RTD prices.

Mirrors the ThinkScript studies on Matt's TOS /ES chart:
  - ATR (14) — Average True Range, the foundation of his volatility bands
  - Keltner Channels (20, 3.5) — dynamic support/resistance
  - Multi-timeframe S/R — 5m / 15m / 30m rolling tops & bottoms
  - Day-range-as-pct-ATR — the compression gauge

Everything is computed from the LAST price feed; no RTD study subscription
required.  The feed already delivers sub-second prices via push-notify;
the indicator engine samples those prices and updates derivatives on the
same cadence.

WHY NOT RTD STUDIES?
ThinkOrSwim's RTD server only answers native quote topics
(LAST / BID / ASK / CLOSE).  ThinkScript study outputs
(ATRTrailingStopLE, KeltnerChannels, AA_CoreyTscorev2) are NOT
exposed unless the user adds them as custom-quote columns in a TOS
watchlist.  For the user's chart, that's a one-time 2‑min TOS config
step.  Until then, the indicators below deliver the same analytics
from the raw price.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────


def _tr(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _ema(series: list[float], period: int) -> list[float]:
    """Exponential moving average.  Returns same length as input."""
    if not series:
        return []
    k = 2.0 / (period + 1)
    out = [series[0]]
    for v in series[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


# ── bar ring ─────────────────────────────────────────────────────────────────


@dataclass
class Bar:
    open: float
    high: float
    low: float
    close: float


class BarRing:
    """Fixed-size rolling window of bars.  Thread-safe for a single writer."""

    def __init__(self, maxlen: int) -> None:
        self._buf: deque[Bar] = deque(maxlen=maxlen)

    def append(self, bar: Bar) -> None:
        self._buf.append(bar)

    @property
    def last(self) -> Optional[Bar]:
        return self._buf[-1] if self._buf else None

    def to_list(self) -> list[Bar]:
        return list(self._buf)

    def closes(self) -> list[float]:
        return [b.close for b in self._buf]

    def highs(self) -> list[float]:
        return [b.high for b in self._buf]

    def lows(self) -> list[float]:
        return [b.low for b in self._buf]

    def __len__(self) -> int:
        return len(self._buf)


# ── indicators ───────────────────────────────────────────────────────────────


@dataclass
class ATRResult:
    value: Optional[float] = None
    period: int = 14
    bars_used: int = 0


@dataclass
class KeltnerResult:
    upper: Optional[float] = None
    mid: Optional[float] = None
    lower: Optional[float] = None
    ema_period: int = 20
    atr_multiplier: float = 3.5


@dataclass
class SRLevels:
    tf_minutes: int
    top: Optional[float] = None
    bottom: Optional[float] = None


@dataclass
class DayRangeGauge:
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    day_range: Optional[float] = None
    atr: Optional[float] = None
    range_pct: Optional[float] = None  # day_range / atr * 100


@dataclass
class IndicatorSnapshot:
    symbol: str
    last_price: Optional[float] = None
    atr: ATRResult = field(default_factory=ATRResult)
    keltner: KeltnerResult = field(default_factory=lambda: KeltnerResult(
        ema_period=20, atr_multiplier=3.5))
    sr_levels: list[SRLevels] = field(default_factory=list)
    day_range: DayRangeGauge = field(default_factory=DayRangeGauge)
    as_of: float = 0.0


class IndicatorEngine:
    """Per-symbol indicator state machine.

    Feed it prices.  It builds bars, then computes ATR, Keltner Channels,
    multi-timeframe support/resistance, and the day-range compression gauge.

    All computation is O(1) per tick — no array re-scan.  Designed to run
    inline with the RTD poll loop so dashboard consumers always read the latest
    snapshot.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        # The longest lookback we need: Keltner EMA(20) + ATR(14) warm-up.
        self._atr_bars = BarRing(maxlen=15)   # 14 + 1 for prev-close TR
        self._keltner_bars = BarRing(maxlen=21)  # 20 + 1
        self._sr_5m = BarRing(maxlen=60)   # enough for 5m window
        self._sr_15m = BarRing(maxlen=60)
        self._sr_30m = BarRing(maxlen=60)

        # Day-range tracking — reset at the session open.
        self._day_high: Optional[float] = None
        self._day_low: Optional[float] = None

        # Last-computed snapshot
        self._snap = IndicatorSnapshot(symbol=symbol)

    # ── feed ──────────────────────────────────────────────────────────────

    def ingest(self, bar: Bar) -> IndicatorSnapshot:
        """Push one completed bar through the engine, return the new snapshot."""
        self._atr_bars.append(bar)
        self._keltner_bars.append(bar)
        self._sr_5m.append(bar)
        self._sr_15m.append(bar)
        self._sr_30m.append(bar)

        # Day range
        if self._day_high is None or bar.high > self._day_high:
            self._day_high = bar.high
        if self._day_low is None or bar.low < self._day_low:
            self._day_low = bar.low

        self._snap = self._compute(bar.close)
        return self._snap

    def tick(self, price: float) -> IndicatorSnapshot:
        """Lightweight update on every price tick (no bar close).

        Only recomputes the fields that change on a tick: last_price and
        day-range (since the running high/low may update).  Full bar-based
        indicators (ATR, Keltner, S/R) only refresh on ``ingest()``.
        """
        if self._day_high is None or price > self._day_high:
            self._day_high = price
        if self._day_low is None or price < self._day_low:
            self._day_low = price

        snap = self._snap  # shallow — update in place
        snap.last_price = price
        snap.day_range.day_high = self._day_high
        snap.day_range.day_low = self._day_low
        if self._day_high is not None and self._day_low is not None:
            snap.day_range.day_range = self._day_high - self._day_low
        snap.as_of = time.time()
        return snap

    @property
    def snapshot(self) -> IndicatorSnapshot:
        return self._snap

    # ── compute ───────────────────────────────────────────────────────────

    def _compute(self, close: float) -> IndicatorSnapshot:
        """Rebuild every derivative.  Called on bar close only."""
        now = time.time()
        snap = IndicatorSnapshot(symbol=self.symbol, last_price=close, as_of=now)

        # ── ATR(14) ─────────────────────────────────────────────────────
        bars = self._atr_bars.to_list()
        if len(bars) >= 2:
            trs: list[float] = []
            for i in range(1, len(bars)):
                trs.append(_tr(bars[i].high, bars[i].low, bars[i - 1].close))
            if trs:
                snap.atr = ATRResult(
                    value=round(sum(trs) / len(trs), 2),
                    period=14,
                    bars_used=len(trs),
                )

        # ── Keltner Channels (20, 3.5) ──────────────────────────────────
        kb = self._keltner_bars.closes()
        if len(kb) >= 20:
            ema20 = _ema(kb, 20)
            mid = round(ema20[-1], 2)
            if snap.atr.value:
                band = round(snap.atr.value * 3.5, 2)
                snap.keltner = KeltnerResult(
                    upper=mid + band,
                    mid=mid,
                    lower=mid - band,
                )

        # ── Multi-timeframe S/R ─────────────────────────────────────────
        for ring, tf_min in [(self._sr_5m, 5), (self._sr_15m, 15), (self._sr_30m, 30)]:
            bar_list = ring.to_list()
            if bar_list:
                tops = [b.high for b in bar_list[-tf_min:]]
                bots = [b.low for b in bar_list[-tf_min:]]
                snap.sr_levels.append(SRLevels(
                    tf_minutes=tf_min,
                    top=max(tops),
                    bottom=min(bots),
                ))

        # ── Day Range Gauge ─────────────────────────────────────────────
        if self._day_high is not None and self._day_low is not None:
            dr = self._day_high - self._day_low
            atr_val = snap.atr.value
            pct = round((dr / atr_val * 100), 1) if atr_val and atr_val > 0 else None
            snap.day_range = DayRangeGauge(
                day_high=self._day_high,
                day_low=self._day_low,
                day_range=dr,
                atr=atr_val,
                range_pct=pct,
            )

        return snap

    def reset_day_range(self) -> None:
        """Call at market open to zero the day-range accumulator."""
        self._day_high = None
        self._day_low = None


# ── multi-symbol registry ────────────────────────────────────────────────────


class IndicatorRegistry:
    """Holds one ``IndicatorEngine`` per symbol.  Thread-safe for read."""

    def __init__(self) -> None:
        self._engines: dict[str, IndicatorEngine] = {}

    def get(self, symbol: str) -> IndicatorEngine:
        key = symbol.upper()
        if key not in self._engines:
            self._engines[key] = IndicatorEngine(key)
        return self._engines[key]

    def snapshot(self, symbol: str) -> IndicatorSnapshot:
        return self.get(symbol).snapshot

    def all_snapshots(self) -> dict[str, IndicatorSnapshot]:
        return {sym: e.snapshot for sym, e in self._engines.items()}
