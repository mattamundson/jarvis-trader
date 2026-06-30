"""
JARVIS TRADER — GreenStar2-style Pine Screener filters
======================================================
Point-in-time screener filter chain that reduces a candidate universe (e.g.
the read-only IB scanner movers list) to real-time focus names, mirroring the
"GreenStar2 PineScreen Filters" TradingView screener
(tradingview.com/script/jLtn2SYq, credited to GreenStar2 / Jeff Sun style).

The original is a closed-source Pine screener; this is a faithful port of the
*column definitions* documented on the script page, not the Pine code. Each
metric below cites how it is computed.

Columns / filters
-----------------
  * ``atr_pct``        — 14-day ATR as a percentage of price. Volatility band
                         filter ("filter out low/high ATR names").
  * ``rvol``           — relative volume: current volume / rolling-average
                         volume. The TradingView original uses "relative volume
                         at time of day"; with daily bars we approximate it as
                         today's volume over the trailing average. Filter ``> 1``.
  * ``x_from_50``      — multiple of ATR the price sits above its 50-period SMA:
                         ``(close - SMA50) / ATR`` (Jeff Sun "xFrom50"). Filter
                         keeps names ``0..4`` (extended, not parabolic).
  * ``x_from_lod_pct`` — distance of price above the low of day measured in
                         hundredths-of-an-ATR: ``(close - LoD) / ATR * 100``.
                         Filter ``< 70`` ≈ within 0.7 ATR of the low — the
                         near-LoD entry that "removes runaways". The ``* 100``
                         mirrors the screener note that scan filters cannot use
                         decimals (so 0.70 ATR is expressed as 70).
  * ``chg_pct``        — daily change ``(close - prev_close) / prev_close * 100``.
                         Filter ``> 0`` (up on the day).
  * ``chg_open_pct``   — change from the session open ``(close - open) / open * 100``.
  * ``mm_score``       — Minervini trend-template criteria passed as a single
                         number ``0..8`` (the screener's "MM" / "Minervini"
                         column), computed via :func:`analytics.sepa_trend_template.evaluate_sepa`.

No look-ahead (point-in-time discipline)
----------------------------------------
Every metric for the decision bar ``t`` uses only bars ``<= t``. The last row of
the supplied frame is treated as the current (possibly still-forming) session
bar: its low/high are the low/high of day, its volume is the volume so far. All
rolling/shift operations look strictly backward — no centered windows, no
``shift(-n)``. This keeps the live screener and the backtest harness on
identical math (see ``.claude/rules/testing.md``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from backtest.indicators import wilder_atr

logger = logging.getLogger(__name__)

# Default lookback periods (match the TradingView screener columns).
ATR_PERIOD = 14
SMA_PERIOD = 50
VOL_PERIOD = 20

# Canonical OHLCV column names expected on input frames (lowercase).
_REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def _last_float(series: pd.Series) -> float:
    """Return the last finite value of a series, or NaN if none."""
    if series is None or len(series) == 0:
        return float("nan")
    val = series.iloc[-1]
    try:
        return float(val) if np.isfinite(val) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


# ---------------------------------------------------------------------------
# Individual metric functions (pure, point-in-time)
# ---------------------------------------------------------------------------


def atr_pct(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ATR_PERIOD) -> float:
    """14-day ATR as a percentage of the latest close.

    ``ATR(period) / close * 100``. Returns NaN when there is insufficient
    history or the latest close is non-positive.
    """
    last_close = _last_float(close)
    if not np.isfinite(last_close) or last_close <= 0:
        return float("nan")
    atr = _last_float(wilder_atr(high, low, close, period=period))
    if not np.isfinite(atr):
        return float("nan")
    return atr / last_close * 100.0


def x_from_50(close: pd.Series, atr: float, period: int = SMA_PERIOD) -> float:
    """Multiple of ATR the latest close sits above its ``period``-SMA.

    ``(close - SMA50) / ATR``. Positive = above the average, negative = below.
    Returns NaN with insufficient history or a non-positive ATR.
    """
    if not np.isfinite(atr) or atr <= 0 or len(close) < period:
        return float("nan")
    sma = _last_float(close.rolling(period).mean())
    last_close = _last_float(close)
    if not np.isfinite(sma) or not np.isfinite(last_close):
        return float("nan")
    return (last_close - sma) / atr


def x_from_lod_pct(close_now: float, low_of_day: float, atr: float) -> float:
    """Distance above the low of day in hundredths-of-an-ATR.

    ``(close - LoD) / ATR * 100``. A value of 70 means price is 0.70 ATR above
    the session low. Returns NaN for a non-positive ATR.
    """
    if not np.isfinite(atr) or atr <= 0:
        return float("nan")
    if not (np.isfinite(close_now) and np.isfinite(low_of_day)):
        return float("nan")
    return (close_now - low_of_day) / atr * 100.0


def relative_volume(volume: pd.Series, period: int = VOL_PERIOD) -> float:
    """Latest volume divided by the average of the ``period`` bars before it.

    Approximates TradingView's "relative volume at time of day" on daily bars:
    current participation versus the trailing baseline, with the current bar
    excluded from the baseline (otherwise a volume spike dilutes its own
    denominator). Values ``> 1`` indicate above-average participation. Returns
    NaN with insufficient history or a non-positive baseline.
    """
    if len(volume) < period + 1:
        return float("nan")
    last_vol = float(volume.iloc[-1])
    baseline = float(volume.iloc[-(period + 1) : -1].mean())
    if not (np.isfinite(last_vol) and np.isfinite(baseline)) or baseline <= 0:
        return float("nan")
    return last_vol / baseline


def chg_pct(close: pd.Series) -> float:
    """Daily change percentage ``(close - prev_close) / prev_close * 100``."""
    if len(close) < 2:
        return float("nan")
    prev = float(close.iloc[-2])
    last = float(close.iloc[-1])
    if not (np.isfinite(prev) and np.isfinite(last)) or prev == 0:
        return float("nan")
    return (last - prev) / prev * 100.0


def chg_open_pct(open_now: float, close_now: float) -> float:
    """Change from the session open ``(close - open) / open * 100``."""
    if not (np.isfinite(open_now) and np.isfinite(close_now)) or open_now == 0:
        return float("nan")
    return (close_now - open_now) / open_now * 100.0


def minervini_score(close: pd.Series, high: pd.Series, low: pd.Series) -> int:
    """Minervini trend-template criteria passed as a single number ``0..8``.

    Delegates to :func:`analytics.sepa_trend_template.evaluate_sepa` and returns
    its ``passed_count``. Criteria that lack sufficient history are simply not
    counted (matching SEPA's own data-availability handling).
    """
    from analytics.sepa_trend_template import evaluate_sepa

    result = evaluate_sepa(close, high=high, low=low)
    return int(result.passed_count)


# ---------------------------------------------------------------------------
# Metrics container + filter config
# ---------------------------------------------------------------------------


@dataclass
class ScreenerMetrics:
    """All screener metrics computed for a single symbol at one decision bar."""

    symbol: Optional[str] = None
    last_price: float = float("nan")
    atr_pct: float = float("nan")
    rvol: float = float("nan")
    x_from_50: float = float("nan")
    x_from_lod_pct: float = float("nan")
    chg_pct: float = float("nan")
    chg_open_pct: float = float("nan")
    mm_score: int = 0
    bars_used: int = 0

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "last_price": self.last_price,
            "atr_pct": self.atr_pct,
            "rvol": self.rvol,
            "x_from_50": self.x_from_50,
            "x_from_lod_pct": self.x_from_lod_pct,
            "chg_pct": self.chg_pct,
            "chg_open_pct": self.chg_open_pct,
            "mm_score": self.mm_score,
            "bars_used": self.bars_used,
        }


@dataclass
class ScreenerFilters:
    """Threshold configuration for the screener.

    Defaults mirror the GreenStar2 screenshot: ``xFrom50`` in ``[0, 4]``,
    ``RVOL > 1``, ``%fromLoD < 70``, ``Chg% > 0``. A bound left as ``None`` is
    not applied, so callers enable only the columns they care about.
    """

    x_from_50_min: Optional[float] = 0.0
    x_from_50_max: Optional[float] = 4.0
    rvol_min: Optional[float] = 1.0
    x_from_lod_max: Optional[float] = 70.0
    chg_pct_min: Optional[float] = 0.0
    chg_open_pct_min: Optional[float] = None
    atr_pct_min: Optional[float] = None
    atr_pct_max: Optional[float] = None
    mm_min: Optional[int] = None


@dataclass
class ScreenResult:
    """Outcome of applying :class:`ScreenerFilters` to one symbol's metrics."""

    metrics: ScreenerMetrics
    passed: bool
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {**self.metrics.as_dict(), "passed": self.passed, "reasons": self.reasons}


# ---------------------------------------------------------------------------
# Compute + filter
# ---------------------------------------------------------------------------


def compute_metrics(
    df: pd.DataFrame,
    *,
    symbol: Optional[str] = None,
    atr_period: int = ATR_PERIOD,
    sma_period: int = SMA_PERIOD,
    vol_period: int = VOL_PERIOD,
) -> ScreenerMetrics:
    """Compute all screener metrics from an OHLCV frame.

    The frame must carry lowercase ``open/high/low/close/volume`` columns in
    chronological order. The **last row** is the current decision bar; its low
    and high are the low/high of day. Only bars ``<= t`` are read — see the
    module docstring on point-in-time discipline.
    """
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"compute_metrics: frame missing columns {missing}")
    if len(df) == 0:
        return ScreenerMetrics(symbol=symbol)

    high, low, close = df["high"], df["low"], df["close"]
    open_now = float(df["open"].iloc[-1])
    close_now = float(close.iloc[-1])
    low_of_day = float(low.iloc[-1])

    atr_abs = _last_float(wilder_atr(high, low, close, period=atr_period))

    return ScreenerMetrics(
        symbol=symbol,
        last_price=close_now,
        atr_pct=atr_pct(high, low, close, period=atr_period),
        rvol=relative_volume(df["volume"], period=vol_period),
        x_from_50=x_from_50(close, atr_abs, period=sma_period),
        x_from_lod_pct=x_from_lod_pct(close_now, low_of_day, atr_abs),
        chg_pct=chg_pct(close),
        chg_open_pct=chg_open_pct(open_now, close_now),
        mm_score=minervini_score(close, high, low),
        bars_used=len(df),
    )


def _check_range(
    value: float, low: Optional[float], high: Optional[float], label: str, reasons: list[str]
) -> bool:
    """Range check for a single metric; appends a reason on failure. NaN fails
    whenever a bound is active (we cannot confirm the name is in range)."""
    if low is None and high is None:
        return True
    if not np.isfinite(value):
        reasons.append(f"{label}=NaN (insufficient data)")
        return False
    if low is not None and value < low:
        reasons.append(f"{label}={value:.2f} < {low}")
        return False
    if high is not None and value > high:
        reasons.append(f"{label}={value:.2f} > {high}")
        return False
    return True


def passes(metrics: ScreenerMetrics, filters: ScreenerFilters) -> ScreenResult:
    """Apply ``filters`` to ``metrics``; return pass/fail with per-filter reasons."""
    reasons: list[str] = []
    ok = True
    ok &= _check_range(
        metrics.x_from_50, filters.x_from_50_min, filters.x_from_50_max, "xFrom50", reasons
    )
    ok &= _check_range(metrics.rvol, filters.rvol_min, None, "RVOL", reasons)
    ok &= _check_range(metrics.x_from_lod_pct, None, filters.x_from_lod_max, "%fromLoD", reasons)
    ok &= _check_range(metrics.chg_pct, filters.chg_pct_min, None, "Chg%", reasons)
    ok &= _check_range(metrics.chg_open_pct, filters.chg_open_pct_min, None, "ChgOpen%", reasons)
    ok &= _check_range(metrics.atr_pct, filters.atr_pct_min, filters.atr_pct_max, "ATR%", reasons)
    ok &= _check_range(
        float(metrics.mm_score),
        None if filters.mm_min is None else float(filters.mm_min),
        None,
        "MM",
        reasons,
    )
    return ScreenResult(metrics=metrics, passed=bool(ok), reasons=reasons)


# A bar provider maps a symbol to its OHLCV frame (or None when unavailable).
BarProvider = Callable[[str], Optional[pd.DataFrame]]


def screen_candidates(
    symbols: list[str],
    bar_provider: BarProvider,
    filters: Optional[ScreenerFilters] = None,
    *,
    atr_period: int = ATR_PERIOD,
    sma_period: int = SMA_PERIOD,
    vol_period: int = VOL_PERIOD,
) -> list[ScreenResult]:
    """Run a candidate universe through the filter chain.

    ``bar_provider`` is injected so this stays pure and testable: the endpoint
    passes a yfinance-backed provider, tests pass synthetic frames. Symbols whose
    bars cannot be fetched are skipped (logged at debug). Results are returned
    sorted by RVOL descending (mirroring the screener's default sort), passing
    names first.
    """
    filters = filters or ScreenerFilters()
    results: list[ScreenResult] = []
    for symbol in symbols:
        try:
            df = bar_provider(symbol)
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not abort the scan
            logger.debug("[Screener] bar provider failed for %s: %s", symbol, exc)
            continue
        if df is None or len(df) == 0:
            logger.debug("[Screener] no bars for %s — skipping", symbol)
            continue
        metrics = compute_metrics(
            df,
            symbol=symbol,
            atr_period=atr_period,
            sma_period=sma_period,
            vol_period=vol_period,
        )
        results.append(passes(metrics, filters))

    def _sort_key(r: ScreenResult) -> tuple[int, float]:
        rvol = r.metrics.rvol if np.isfinite(r.metrics.rvol) else float("-inf")
        return (0 if r.passed else 1, -rvol)

    results.sort(key=_sort_key)
    return results
