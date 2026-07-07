"""
Multi-Timeframe STC Confirmation Analyzer

Checks STC (Schaff Trend Cycle) signal alignment across 1h, 4h, and daily
timeframes. Uses MarketDataManager with a 30-minute per-timeframe cache.

Fallback: stub data (50 / NEUTRAL) when network unavailable.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

# STC parameters matching engine config
_STC_FAST = 23
_STC_SLOW = 50
_STC_LEN = 10
_STC_OS = 15.0
_STC_OB = 83.0

_CACHE_TTL = {"1h": 1800, "4h": 3600, "1d": 14400}
_cache: dict = {}

# Futures symbols recognized as is_futures=True
_FUTURES_SYMBOLS = {"MES", "MNQ", "MCL", "MGC", "MHG", "MYM", "M2K"}


@dataclass
class TFSignal:
    timeframe: str
    stc_value: float
    stc_signal: str  # BULLISH | BEARISH | NEUTRAL
    price: float
    source: str  # live | cache | stub
    error: Optional[str] = None


@dataclass
class MTFState:
    symbol: str
    signals: list[TFSignal] = field(default_factory=list)
    alignment: str = "NEUTRAL"  # BULLISH | BEARISH | MIXED | NEUTRAL
    confidence: float = 0.0
    aligned_timeframes: int = 0
    total_timeframes: int = 3
    recommendation: str = "WAIT"  # BUY | SELL | WAIT
    source: str = "stub"


def _ema(data: list[float], period: int) -> list[float]:
    if not data:
        return []
    k = 2.0 / (period + 1)
    result = [data[0]]
    for v in data[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _stoch(data: list[float], period: int) -> list[float]:
    result = []
    for i in range(len(data)):
        window = data[max(0, i - period + 1) : i + 1]
        lo, hi = min(window), max(window)
        result.append((data[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    return result


def _compute_stc(closes: list[float]) -> float:
    if len(closes) < _STC_SLOW + _STC_LEN + 10:
        return 50.0
    ema1 = _ema(closes, _STC_FAST)
    ema2 = _ema(closes, _STC_SLOW)
    macd = [a - b for a, b in zip(ema1, ema2, strict=False)]
    d1 = _ema(_stoch(macd, _STC_LEN), 3)
    d2 = _ema(_stoch(d1, _STC_LEN), 3)
    return round(d2[-1], 2) if d2 else 50.0


def _to_signal(v: float) -> str:
    if v <= _STC_OS:
        return "BULLISH"
    if v >= _STC_OB:
        return "BEARISH"
    return "NEUTRAL"


async def _fetch_tf_async(symbol: str, tf: str, data_manager=None) -> TFSignal:
    """Fetch bars for a single timeframe via data_manager and compute STC."""
    key = f"{symbol}_{tf}"
    now = time.time()
    ttl = _CACHE_TTL.get(tf, 1800)

    hit = _cache.get(key)
    if hit and (now - hit["ts"]) < ttl:
        s = hit["sig"]
        return TFSignal(s.timeframe, s.stc_value, s.stc_signal, s.price, "cache")

    if data_manager is None:
        return TFSignal(tf, 50.0, "NEUTRAL", 0.0, "stub", "data_manager not available")

    try:
        # For 4h we fetch 1h bars and downsample; 1d fetches daily bars
        fetch_tf = "1h" if tf in ("1h", "4h") else "1d"
        lookback = {"1h": 60, "4h": 120, "1d": 365}[tf]
        is_futures = symbol.upper() in _FUTURES_SYMBOLS

        hist = await data_manager.get_bars(
            symbol, lookback_days=lookback, timeframe=fetch_tf, is_futures=is_futures
        )
        if hist is None or hist.empty or len(hist) < 60:
            raise ValueError(f"Only {len(hist) if hist is not None else 0} bars")

        hist.columns = [c.lower() for c in hist.columns]
        closes = hist["close"].tolist()
        if tf == "4h":
            closes = [closes[i] for i in range(3, len(closes), 4)]
        stc_val = _compute_stc(closes)
        sig = TFSignal(tf, stc_val, _to_signal(stc_val), round(float(closes[-1]), 2), "live")
        _cache[key] = {"sig": sig, "ts": now}
        return sig
    except Exception as e:
        return TFSignal(tf, 50.0, "NEUTRAL", 0.0, "stub", str(e)[:80])


async def analyze_mtf(symbol: str, data_manager=None) -> MTFState:
    """Analyze multi-timeframe STC alignment for a symbol."""
    signals = []
    for tf in ("1h", "4h", "1d"):
        sig = await _fetch_tf_async(symbol, tf, data_manager)
        signals.append(sig)

    live = [s for s in signals if s.source != "stub"]
    bull = sum(1 for s in live if s.stc_signal == "BULLISH")
    bear = sum(1 for s in live if s.stc_signal == "BEARISH")
    n = len(signals)
    if bull >= 2:
        alignment, conf, rec = "BULLISH", bull / n, "BUY"
    elif bear >= 2:
        alignment, conf, rec = "BEARISH", bear / n, "SELL"
    else:
        alignment = "MIXED" if (bull + bear) >= 2 else "NEUTRAL"
        conf, rec = 0.0, "WAIT"
    return MTFState(
        symbol=symbol,
        signals=signals,
        alignment=alignment,
        confidence=round(conf, 2),
        aligned_timeframes=max(bull, bear),
        total_timeframes=n,
        recommendation=rec,
        source="stub" if all(s.source == "stub" for s in signals) else "live",
    )
