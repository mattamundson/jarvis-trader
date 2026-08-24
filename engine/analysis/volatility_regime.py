"""Volatility-regime research primitives for SPY/QQQ/VIX options.

Pure/read-only computations only: no broker, DB, router, LLM, or execution side
effects. The module turns daily OHLCV + optional VIX/VIX3M series into a regime
frame that can be used to test defined-risk options payoff structures by market
state rather than by raw direction alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

TRADING_DAYS = 252
REALIZED_VOL_WINDOWS = (5, 10, 20, 60)
FORWARD_RETURN_HORIZONS = (1, 3, 5)


@dataclass(frozen=True)
class RegimeThresholds:
    """Conservative default thresholds for daily index-regime labeling."""

    low_rv20: float = 0.12
    high_rv20: float = 0.24
    high_vix_percentile: float = 0.80
    extreme_vix_percentile: float = 0.90
    rich_iv_rv_spread: float = 0.04
    cheap_iv_rv_spread: float = -0.02
    term_flat_band: float = 0.005


def _date_index(df: pd.DataFrame) -> pd.DataFrame:
    """Return df indexed by normalized daily timestamp.

    Accepts either `timestamp` or `date`. Raises ValueError for missing columns so
    callers fail loudly in tests/CLI rather than silently mixing bad data.
    """

    out = df.copy()
    if "timestamp" in out.columns:
        ts = pd.to_datetime(out["timestamp"], errors="coerce", utc=True).dt.tz_convert(None)
    elif "date" in out.columns:
        ts = pd.to_datetime(out["date"], errors="coerce", utc=True).dt.tz_convert(None)
    else:
        raise ValueError("expected a timestamp or date column")
    out = out.assign(date=ts.dt.normalize()).dropna(subset=["date"])
    out = out.sort_values("date").drop_duplicates("date", keep="last")
    return out.set_index("date")


def prepare_price_frame(df: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    """Normalize daily OHLCV input to a research-ready close/return frame."""

    out = _date_index(df)
    if "close" not in out.columns:
        raise ValueError(f"{symbol}: expected close column")
    close = pd.to_numeric(out["close"], errors="coerce")
    frame = pd.DataFrame({"symbol": symbol.upper(), "close": close}, index=out.index)
    frame = frame.dropna(subset=["close"])
    frame["log_return"] = np.log(frame["close"] / frame["close"].shift(1))
    frame["return_1d"] = frame["close"].pct_change()
    return frame


def add_realized_vol(frame: pd.DataFrame, windows: Iterable[int] = REALIZED_VOL_WINDOWS) -> pd.DataFrame:
    """Add annualized close-to-close realized-vol columns: `rv_{window}d`."""

    out = frame.copy()
    for window in windows:
        out[f"rv_{window}d"] = out["log_return"].rolling(window).std() * np.sqrt(TRADING_DAYS)
    return out


def add_trend_state(frame: pd.DataFrame, *, fast: int = 20, slow: int = 60) -> pd.DataFrame:
    """Add simple trend state from daily moving averages."""

    out = frame.copy()
    out[f"sma_{fast}"] = out["close"].rolling(fast).mean()
    out[f"sma_{slow}"] = out["close"].rolling(slow).mean()
    conditions = [
        (out["close"] > out[f"sma_{fast}"]) & (out[f"sma_{fast}"] > out[f"sma_{slow}"]),
        (out["close"] < out[f"sma_{fast}"]) & (out[f"sma_{fast}"] < out[f"sma_{slow}"]),
    ]
    out["trend_state"] = np.select(conditions, ["trend_up", "trend_down"], default="chop")
    return out


def prepare_vix_frame(vix: pd.DataFrame, *, value_name: str = "vix") -> pd.DataFrame:
    """Normalize VIX-like daily data into one decimal-vol-index column."""

    out = _date_index(vix)
    value_col = "close" if "close" in out.columns else value_name
    if value_col not in out.columns:
        raise ValueError(f"expected close or {value_name} column")
    result = pd.DataFrame({value_name: pd.to_numeric(out[value_col], errors="coerce")}, index=out.index)
    return result.dropna(subset=[value_name])


def add_vix_context(
    frame: pd.DataFrame,
    vix: pd.DataFrame | None = None,
    vix3m: pd.DataFrame | None = None,
    *,
    percentile_window: int = 252,
) -> pd.DataFrame:
    """Join VIX/VIX3M context and compute percentile, slope, and IV/RV proxy spread."""

    out = frame.copy()
    if vix is not None and not vix.empty:
        out = out.join(prepare_vix_frame(vix, value_name="vix"), how="left")
        out["vix_percentile"] = out["vix"].rolling(percentile_window, min_periods=60).rank(pct=True)
        out["vix_iv_proxy"] = out["vix"] / 100.0
        if "rv_20d" in out.columns:
            out["iv_rv_spread"] = out["vix_iv_proxy"] - out["rv_20d"]
    if vix3m is not None and not vix3m.empty:
        out = out.join(prepare_vix_frame(vix3m, value_name="vix3m"), how="left")
    if "vix" in out.columns and "vix3m" in out.columns:
        out["vix_term_slope"] = out["vix3m"] / 100.0 - out["vix"] / 100.0
        out["term_state"] = out["vix_term_slope"].map(classify_term_state)
    else:
        out["term_state"] = "unknown"
    return out


def classify_term_state(slope: float | None, thresholds: RegimeThresholds = RegimeThresholds()) -> str:
    """Classify VIX3M - VIX slope, using decimal-vol units."""

    if slope is None or pd.isna(slope):
        return "unknown"
    if slope > thresholds.term_flat_band:
        return "contango"
    if slope < -thresholds.term_flat_band:
        return "backwardation"
    return "flat"


def classify_premium_state(row: pd.Series, thresholds: RegimeThresholds = RegimeThresholds()) -> str:
    """Label premium richness from IV proxy minus realized volatility."""

    spread = row.get("iv_rv_spread")
    if spread is None or pd.isna(spread):
        return "unknown"
    if spread >= thresholds.rich_iv_rv_spread:
        return "premium_rich"
    if spread <= thresholds.cheap_iv_rv_spread:
        return "premium_cheap"
    return "premium_fair"


def _classify_one_row(row: pd.Series, thresholds: RegimeThresholds) -> str:
    """Classify one daily row into a coarse volatility/options regime."""

    trend = row.get("trend_state", "chop")
    rv20 = row.get("rv_20d")
    vix_pct = row.get("vix_percentile")
    term = row.get("term_state", "unknown")
    premium = classify_premium_state(row, thresholds)

    high_vix = vix_pct is not None and not pd.isna(vix_pct) and float(vix_pct) >= thresholds.high_vix_percentile
    extreme_vix = (
        vix_pct is not None and not pd.isna(vix_pct) and float(vix_pct) >= thresholds.extreme_vix_percentile
    )
    low_vol = rv20 is not None and not pd.isna(rv20) and float(rv20) <= thresholds.low_rv20
    high_vol = rv20 is not None and not pd.isna(rv20) and float(rv20) >= thresholds.high_rv20

    if extreme_vix or (term == "backwardation" and trend == "trend_down"):
        return "crash_risk"
    if term == "backwardation" and premium == "premium_rich" and trend != "trend_down":
        return "vol_crush_candidate"
    if premium == "premium_rich" and not high_vix:
        return "premium_rich"
    if premium == "premium_cheap" and trend == "trend_up":
        return "premium_cheap_trend_up"
    if trend == "trend_up" and low_vol:
        return "trend_up_low_vol"
    if trend == "trend_up" and high_vol:
        return "trend_up_high_vol"
    if trend == "trend_down" and high_vol:
        return "trend_down_high_vol"
    if trend == "trend_down" and low_vol:
        return "trend_down_low_vol"
    if premium == "premium_cheap":
        return "premium_cheap"
    if term == "contango" and high_vix:
        return "contango_high_vix"
    return "neutral"


def classify_regime(
    frame: pd.Series | pd.DataFrame,
    thresholds: RegimeThresholds = RegimeThresholds(),
) -> str | pd.DataFrame:
    """Classify rows into a coarse volatility/options regime.

    Accepts a single Series (returns the regime label string) or a DataFrame
    (returns a copy with a new ``regime`` column).
    """

    if isinstance(frame, pd.Series):
        return _classify_one_row(frame, thresholds)

    out = frame.copy()
    out["regime"] = out.apply(lambda row: _classify_one_row(row, thresholds), axis=1)
    return out


def add_regime_labels(frame: pd.DataFrame, thresholds: RegimeThresholds = RegimeThresholds()) -> pd.DataFrame:
    """Add `premium_state` and `regime` labels."""

    out = frame.copy()
    out["premium_state"] = out.apply(lambda row: classify_premium_state(row, thresholds), axis=1)
    out["regime"] = out.apply(lambda row: classify_regime(row, thresholds), axis=1)
    return out


def add_forward_outcomes(
    frame: pd.DataFrame,
    horizons: Iterable[int] = FORWARD_RETURN_HORIZONS,
    *,
    forward_vol_window: int = 5,
) -> pd.DataFrame:
    """Add forward returns and forward realized-vol change columns."""

    out = frame.copy()
    for horizon in horizons:
        out[f"fwd_return_{horizon}d"] = out["close"].shift(-horizon) / out["close"] - 1.0
    fwd_rv = out["log_return"].shift(-1).rolling(forward_vol_window).std() * np.sqrt(TRADING_DAYS)
    out[f"fwd_rv_{forward_vol_window}d"] = fwd_rv.shift(-(forward_vol_window - 1))
    if "rv_20d" in out.columns:
        out[f"fwd_rv_{forward_vol_window}d_change"] = out[f"fwd_rv_{forward_vol_window}d"] - out["rv_20d"]
    return out


def build_regime_frame(
    underlying: pd.DataFrame,
    *,
    symbol: str,
    vix: pd.DataFrame | None = None,
    vix3m: pd.DataFrame | None = None,
    thresholds: RegimeThresholds = RegimeThresholds(),
) -> pd.DataFrame:
    """Full daily regime frame for one underlying."""

    frame = prepare_price_frame(underlying, symbol=symbol)
    frame = add_realized_vol(frame)
    frame = add_trend_state(frame)
    frame = add_vix_context(frame, vix=vix, vix3m=vix3m)
    frame = add_regime_labels(frame, thresholds)
    frame = add_forward_outcomes(frame)
    return frame


def summarize_by_regime(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate forward-return/volatility outcomes by regime."""

    metric_cols = [
        "fwd_return_1d",
        "fwd_return_3d",
        "fwd_return_5d",
        "fwd_rv_5d_change",
        "rv_20d",
        "iv_rv_spread",
    ]
    available = [c for c in metric_cols if c in frame.columns]
    if "regime" not in frame.columns:
        raise ValueError("frame must contain regime column")
    rows = []
    for regime, grp in frame.dropna(subset=["regime"]).groupby("regime"):
        entry = {"regime": regime, "n_days": int(len(grp))}
        for col in available:
            s = pd.to_numeric(grp[col], errors="coerce").dropna()
            entry[f"{col}_mean"] = float(s.mean()) if len(s) else None
            entry[f"{col}_median"] = float(s.median()) if len(s) else None
            if col.startswith("fwd_return"):
                entry[f"{col}_win_rate"] = float((s > 0).mean()) if len(s) else None
        rows.append(entry)
    return pd.DataFrame(rows).sort_values(["n_days", "regime"], ascending=[False, True]).reset_index(drop=True)


def latest_regime_snapshot(frame: pd.DataFrame) -> dict:
    """Return a compact JSON-safe latest-row snapshot."""

    row = frame.dropna(subset=["close"]).iloc[-1]
    keys = [
        "symbol",
        "close",
        "trend_state",
        "rv_5d",
        "rv_10d",
        "rv_20d",
        "rv_60d",
        "vix",
        "vix3m",
        "vix_percentile",
        "term_state",
        "iv_rv_spread",
        "premium_state",
        "regime",
    ]
    out = {"date": row.name.date().isoformat()}
    for key in keys:
        val = row.get(key)
        if val is None or pd.isna(val):
            out[key] = None
        elif isinstance(val, (np.integer, np.floating)):
            out[key] = float(val)
        else:
            out[key] = val
    return out
