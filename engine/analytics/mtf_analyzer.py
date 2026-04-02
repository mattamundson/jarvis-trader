"""
Multi-Timeframe STC Confirmation Analyzer

Checks STC (Schaff Trend Cycle) signal alignment across 1h, 4h, and daily
timeframes. Uses yfinance with a 30-minute per-timeframe cache.

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

_SYMBOL_MAP = {
    "MES": "ES=F",
    "MNQ": "NQ=F",
    "MCL": "CL=F",
    "SPY": "SPY",
    "QQQ": "QQQ",
}


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


def _fetch_tf(yf_sym: str, tf: str) -> TFSignal:
    key = f"{yf_sym}_{tf}"
    now = time.time()
    ttl = _CACHE_TTL.get(tf, 1800)

    hit = _cache.get(key)
    if hit and (now - hit["ts"]) < ttl:
        s = hit["sig"]
        return TFSignal(s.timeframe, s.stc_value, s.stc_signal, s.price, "cache")

    try:
        import yfinance as yf

        period, interval = {"1h": ("60d", "1h"), "4h": ("120d", "1h"), "1d": ("365d", "1d")}[tf]
        hist = yf.Ticker(yf_sym).history(period=period, interval=interval)
        if hist.empty or len(hist) < 60:
            raise ValueError(f"Only {len(hist)} bars")
        closes = hist["Close"].tolist()
        if tf == "4h":
            closes = [closes[i] for i in range(3, len(closes), 4)]
        stc_val = _compute_stc(closes)
        sig = TFSignal(tf, stc_val, _to_signal(stc_val), round(float(closes[-1]), 2), "live")
        _cache[key] = {"sig": sig, "ts": now}
        return sig
    except Exception as e:
        return TFSignal(tf, 50.0, "NEUTRAL", 0.0, "stub", str(e)[:80])


def analyze_mtf(symbol: str) -> MTFState:
    yf_sym = _SYMBOL_MAP.get(symbol.upper(), symbol)
    signals = [_fetch_tf(yf_sym, tf) for tf in ("1h", "4h", "1d")]
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
