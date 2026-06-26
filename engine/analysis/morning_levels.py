"""
JARVIS morning levels — deterministic structural levels for the daily brief.

Phase A of the self-improving morning briefing. Produces Corey-shaped structural
levels (pivot / triggers / ATR-fib targets / overnight range / value area) from
*real* OHLC — no LLM, nothing fabricated. The core math lives in the pure
``compute_levels_from_bars`` so it is unit-testable on fixtures; the async
``compute_morning_levels`` is a thin wrapper that fetches bars via the engine's
MarketDataManager waterfall (TradingView MCP -> IBKR -> cache).

Reuses existing machinery rather than reinventing it:
- ``backtest.indicators.wilder_atr`` / ``atr_fib_levels`` for ATR + fib targets
- ``backtest.tpo_profile.compute_tpo_profile`` for value-area (VAH/VAL/POC)

Display/journal only. Nothing here is imported by ``risk/`` or constructs an
``OrderRequest`` — the hardcoded safety layer never consumes these values.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Optional, Sequence

import pandas as pd

from backtest.indicators import atr_fib_levels, wilder_atr

logger = logging.getLogger(__name__)

# Default ATR-fib target ladder (multiples of ATR off the prior close). The
# calibrator (Phase E) may later override this per symbol via state JSON.
DEFAULT_TARGET_RATIOS: tuple[float, ...] = (0.382, 0.618, 1.0)

# Symbols the morning brief covers. ES/NQ are price-identical to the MES/MNQ
# micros that are actually traded, and match Corey's ES/NQ commentary 1:1.
COVERED_SYMBOLS: tuple[str, ...] = ("ES", "NQ", "MGC")


@dataclass
class MorningLevels:
    """Deterministic structural levels for one symbol on one session."""

    symbol: str
    prior_close: float
    prior_high: float
    prior_low: float
    pivot: float
    r1: float
    s1: float
    r2: float
    s2: float
    atr: float
    target_ratios: list[float]
    targets_up: list[float]
    targets_down: list[float]
    overnight_high: Optional[float] = None
    overnight_low: Optional[float] = None
    overnight_range: Optional[float] = None
    vah: Optional[float] = None
    val: Optional[float] = None
    poc: Optional[float] = None
    va_position: Optional[str] = None

    def to_dict(self) -> dict:
        """JSON-serializable dict (for the forecast journal + JSON backup)."""
        return asdict(self)


def _is_finite(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _round(x, ndigits: int = 4):
    return round(float(x), ndigits) if _is_finite(x) else None


def compute_levels_from_bars(
    symbol: str,
    daily_df: pd.DataFrame,
    intraday_df: Optional[pd.DataFrame] = None,
    atr_period: int = 14,
    target_ratios: Optional[Sequence[float]] = None,
) -> MorningLevels:
    """Compute structural levels from OHLC bars. Pure and deterministic.

    Parameters
    ----------
    symbol : str
        Instrument symbol (ES, NQ, MGC, ...).
    daily_df : DataFrame
        Daily OHLC with columns open/high/low/close (+volume). The LAST row is
        treated as the most recent completed prior session; pivots and ATR are
        derived from it (ATR over the trailing ``atr_period`` rows).
    intraday_df : DataFrame, optional
        Overnight / pre-open intraday bars (DatetimeIndex). When supplied, the
        overnight high/low/range and value-area structure are derived from it.
    atr_period : int
        Wilder ATR lookback (default 14).
    target_ratios : sequence of float, optional
        ATR multiples for the target ladder (defaults to DEFAULT_TARGET_RATIOS).

    Returns
    -------
    MorningLevels
    """
    if daily_df is None or len(daily_df) == 0:
        raise ValueError(f"compute_levels_from_bars: empty daily_df for {symbol}")
    for col in ("high", "low", "close"):
        if col not in daily_df.columns:
            raise ValueError(f"compute_levels_from_bars: daily_df missing '{col}' column")

    ratios = list(target_ratios) if target_ratios is not None else list(DEFAULT_TARGET_RATIOS)

    prior = daily_df.iloc[-1]
    prior_high = float(prior["high"])
    prior_low = float(prior["low"])
    prior_close = float(prior["close"])

    # Classic floor-trader pivots from the prior session.
    pivot = (prior_high + prior_low + prior_close) / 3.0
    r1 = 2.0 * pivot - prior_low
    s1 = 2.0 * pivot - prior_high
    rng = prior_high - prior_low
    r2 = pivot + rng
    s2 = pivot - rng

    # Wilder ATR over the trailing window (NaN if too few bars).
    atr_series = wilder_atr(daily_df["high"], daily_df["low"], daily_df["close"], atr_period)
    atr_val = float(atr_series.iloc[-1]) if len(atr_series) else float("nan")

    targets_up: list[float] = []
    targets_down: list[float] = []
    if _is_finite(atr_val) and atr_val > 0:
        fib = atr_fib_levels(prior_close, atr_val, ratios)
        for r in ratios:
            key = str(r)
            up = fib.get(f"up_{key}")
            dn = fib.get(f"down_{key}")
            if _is_finite(up):
                targets_up.append(round(float(up), 4))
            if _is_finite(dn):
                targets_down.append(round(float(dn), 4))

    overnight_high = overnight_low = overnight_range = None
    vah = val = poc = va_position = None
    if intraday_df is not None and len(intraday_df) > 0:
        if "high" in intraday_df and "low" in intraday_df:
            overnight_high = float(intraday_df["high"].max())
            overnight_low = float(intraday_df["low"].min())
            overnight_range = overnight_high - overnight_low
        vah, val, poc, va_position = _value_area(intraday_df)

    return MorningLevels(
        symbol=symbol,
        prior_close=round(prior_close, 4),
        prior_high=round(prior_high, 4),
        prior_low=round(prior_low, 4),
        pivot=round(pivot, 4),
        r1=round(r1, 4),
        s1=round(s1, 4),
        r2=round(r2, 4),
        s2=round(s2, 4),
        atr=round(atr_val, 4) if _is_finite(atr_val) else float("nan"),
        target_ratios=ratios,
        targets_up=targets_up,
        targets_down=targets_down,
        overnight_high=_round(overnight_high),
        overnight_low=_round(overnight_low),
        overnight_range=_round(overnight_range),
        vah=_round(vah),
        val=_round(val),
        poc=_round(poc),
        va_position=va_position,
    )


def resample_ohlc_to_daily(df: pd.DataFrame, tz: str = "America/New_York") -> pd.DataFrame:
    """Resample intraday OHLCV bars to daily sessions (calendar day in ``tz``).

    The DB stores 1h bars; pivots/ATR need daily sessions. Accepts a DataFrame
    with a 'timestamp' column or a DatetimeIndex. Returns a daily DataFrame
    indexed by date with open/high/low/close/volume; empty if no usable bars.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame()
    work = df.copy()
    if isinstance(work.index, pd.DatetimeIndex):
        idx = work.index
    elif "timestamp" in work.columns:
        idx = pd.DatetimeIndex(pd.to_datetime(work["timestamp"], utc=True))
    else:
        return pd.DataFrame()
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    work = work.set_index(idx.tz_convert(tz))
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in work.columns:
        agg["volume"] = "sum"
    daily = work.resample("1D").agg(agg).dropna(subset=["close"])
    return daily


def _value_area(intraday_df: pd.DataFrame):
    """Best-effort value area from intraday bars. Returns (vah, val, poc, label).

    Reuses backtest.tpo_profile.compute_tpo_profile. Any failure (missing
    DatetimeIndex, FTS/scipy quirk, too few bars) degrades to (None,)*4 — the
    levels engine must never crash the brief over an optional enrichment.
    """
    try:
        if not isinstance(intraday_df.index, pd.DatetimeIndex):
            return None, None, None, None
        from backtest.tpo_profile import compute_tpo_profile

        prof = compute_tpo_profile(intraday_df)
        last = prof.iloc[-1]
        return (
            float(last.get("va_high")) if _is_finite(last.get("va_high")) else None,
            float(last.get("va_low")) if _is_finite(last.get("va_low")) else None,
            float(last.get("vpoc")) if _is_finite(last.get("vpoc")) else None,
            (str(last.get("price_vs_va")) if last.get("price_vs_va") is not None else None),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("value-area computation skipped: %s", exc)
        return None, None, None, None


async def compute_morning_levels(
    symbol: str,
    data_manager,
    atr_period: int = 14,
    target_ratios: Optional[Sequence[float]] = None,
    daily_lookback_days: int = 40,
    intraday_lookback_days: int = 2,
    intraday_timeframe: str = "1h",
) -> Optional[MorningLevels]:
    """Async wrapper: fetch bars via MarketDataManager then compute levels.

    Returns None if no daily bars are available (caller renders a 'no data'
    line rather than failing the whole brief).
    """
    is_fut = symbol.upper() in {"ES", "NQ", "MES", "MNQ", "MGC", "MCL", "GC", "CL"}
    daily_df = await data_manager.get_bars(
        symbol, lookback_days=daily_lookback_days, timeframe="1d", is_futures=is_fut
    )
    if daily_df is None or len(daily_df) == 0:
        logger.warning("compute_morning_levels: no daily bars for %s", symbol)
        return None
    daily_df = _ensure_dt_index(daily_df)

    intraday_df = None
    try:
        intr = await data_manager.get_bars(
            symbol,
            lookback_days=intraday_lookback_days,
            timeframe=intraday_timeframe,
            is_futures=is_fut,
        )
        if intr is not None and len(intr) > 0:
            intraday_df = _ensure_dt_index(intr)
    except Exception as exc:  # pragma: no cover - optional enrichment
        logger.debug("intraday fetch skipped for %s: %s", symbol, exc)

    return compute_levels_from_bars(
        symbol,
        daily_df,
        intraday_df=intraday_df,
        atr_period=atr_period,
        target_ratios=target_ratios,
    )


def _ensure_dt_index(df: pd.DataFrame) -> pd.DataFrame:
    """Promote a 'timestamp'/'datetime' column to a DatetimeIndex if needed."""
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    for col in ("timestamp", "datetime", "date", "time"):
        if col in df.columns:
            out = df.copy()
            out.index = pd.to_datetime(out[col], utc=True)
            return out
    return df
