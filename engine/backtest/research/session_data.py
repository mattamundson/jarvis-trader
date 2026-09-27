"""Pure session/data utilities for paper-only MES intraday research.

No runtime configuration, broker, order-routing, or live-engine imports are allowed here.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

CT = "America/Chicago"
RTH_START = time(8, 30)
IB_END = time(9, 30)
RTH_END = time(15, 0)
GLOBEX_START = time(17, 0)
TICK_SIZE = 0.25
MES_MULTIPLIER = 5.0
INITIAL_CAPITAL = 10_000.0
ROUND_TRIP_FEES = 1.42


@dataclass(frozen=True)
class SessionSlice:
    trade_date: date
    overnight: pd.DataFrame
    rth: pd.DataFrame
    ib: pd.DataFrame
    post_ib: pd.DataFrame


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_mes_csv(path: str | Path) -> pd.DataFrame:
    """Load an OHLCV CSV into a unique, monotonic UTC DatetimeIndex."""
    path = Path(path)
    df = pd.read_csv(path)
    timestamp_col = next(
        (c for c in df.columns if c.lower() in {"timestamp", "datetime", "date", "time"}),
        df.columns[0],
    )
    idx = pd.to_datetime(df.pop(timestamp_col), utc=True, errors="raise")
    df.index = idx
    df.index.name = "timestamp"
    df.columns = [str(c).lower() for c in df.columns]
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    if df.index.has_duplicates:
        raise ValueError("duplicate timestamps")
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()
    if df[list(required)].isna().any().any():
        raise ValueError("OHLCV contains NaN")
    bad = (df["high"] < df[["open", "close", "low"]].max(axis=1)) | (
        df["low"] > df[["open", "close", "high"]].min(axis=1)
    )
    if bool(bad.any()):
        raise ValueError(f"OHLC invariant violations: {int(bad.sum())}")
    return df


def cache_provenance(path: str | Path, df: pd.DataFrame) -> dict:
    path = Path(path)
    ct = df.index.tz_convert(CT)
    rth_mask = np.array([RTH_START <= ts.time() < RTH_END for ts in ct])
    rth_dates = pd.Index(ct[rth_mask].date)
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "rows": int(len(df)),
        "first_utc": df.index.min().isoformat(),
        "last_utc": df.index.max().isoformat(),
        "span_years": round((df.index.max() - df.index.min()).total_seconds() / (365.25 * 86400), 6),
        "rth_rows": int(rth_mask.sum()),
        "rth_sessions": int(rth_dates.nunique()),
        "rth_first_date": str(rth_dates.min()),
        "rth_last_date": str(rth_dates.max()),
        "duplicate_timestamps": int(df.index.duplicated().sum()),
        "nan_cells": int(df.isna().sum().sum()),
        "session_policy": "RTH 08:30<=bar_start<15:00 America/Chicago; IB 08:30<=bar_start<09:30; overnight prior 17:00<=bar_start<08:30",
    }


def add_session_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add causal Chicago time, futures trade date, and week key.

    A bar starting at/after 17:00 CT belongs to the next futures trade date. The
    week key is that trade date's Monday, so Sunday Globex bars reset the week.
    """
    out = df.copy()
    local = out.index.tz_convert(CT)
    trade_dates = [
        ts.date() + timedelta(days=1) if ts.time() >= GLOBEX_START else ts.date()
        for ts in local
    ]
    out["local_ct"] = local
    out["trade_date"] = trade_dates
    out["week_key"] = [d - timedelta(days=d.weekday()) for d in trade_dates]
    out["is_rth"] = [RTH_START <= ts.time() < RTH_END for ts in local]
    out["is_ib"] = [RTH_START <= ts.time() < IB_END for ts in local]
    out["is_post_ib"] = [IB_END <= ts.time() < RTH_END for ts in local]
    out["is_overnight"] = [ts.time() >= GLOBEX_START or ts.time() < RTH_START for ts in local]
    return out


def build_sessions(df: pd.DataFrame, *, min_ib_bars: int = 12, min_rth_bars: int = 60) -> tuple[list[SessionSlice], dict]:
    """Return complete causal sessions and explicit exclusion counts."""
    tagged = add_session_columns(df)
    sessions: list[SessionSlice] = []
    excluded = {
        "no_overnight": 0,
        "short_ib": 0,
        "short_rth": 0,
        "no_post_ib": 0,
    }
    for trade_date, group in tagged.groupby("trade_date", sort=True):
        overnight = group[group["is_overnight"]]
        rth = group[group["is_rth"]]
        ib = group[group["is_ib"]]
        post_ib = group[group["is_post_ib"]]
        if overnight.empty:
            excluded["no_overnight"] += 1
            continue
        if len(ib) < min_ib_bars:
            excluded["short_ib"] += 1
            continue
        if len(rth) < min_rth_bars:
            excluded["short_rth"] += 1
            continue
        if post_ib.empty:
            excluded["no_post_ib"] += 1
            continue
        sessions.append(SessionSlice(trade_date, overnight, rth, ib, post_ib))
    return sessions, excluded


def profit_factor(pnls: Iterable[float]) -> float:
    values = np.asarray(list(pnls), dtype=float)
    wins = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses == 0:
        return math.inf if wins > 0 else 0.0
    return wins / losses


def max_drawdown_pct(pnls: Iterable[float], initial_capital: float = INITIAL_CAPITAL) -> float:
    values = np.asarray(list(pnls), dtype=float)
    equity = initial_capital + np.cumsum(values)
    if equity.size == 0:
        return 0.0
    curve = np.concatenate([[initial_capital], equity])
    peak = np.maximum.accumulate(curve)
    dd = (curve - peak) / peak
    return float(-dd.min() * 100.0)


def strategy_metrics(
    pnls: Iterable[float],
    dates: Iterable[date],
    *,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict:
    values = np.asarray(list(pnls), dtype=float)
    dts = list(dates)
    if len(values) != len(dts):
        raise ValueError("PnL/date length mismatch")
    if values.size == 0:
        return {
            "n_trades": 0,
            "net_pnl": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "expectancy": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "observed_frequency_sharpe": 0.0,
            "trades_per_year": 0.0,
        }
    span_years = max((max(dts) - min(dts)).days / 365.25, 1.0 / 365.25)
    final_capital = initial_capital + float(values.sum())
    cagr = (
        (final_capital / initial_capital) ** (1.0 / span_years) - 1.0
        if final_capital > 0
        else -1.0
    )
    tpy = len(values) / span_years
    std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    sharpe = float(values.mean() / std * math.sqrt(tpy)) if std > 0 else 0.0
    return {
        "n_trades": int(len(values)),
        "net_pnl": round(float(values.sum()), 6),
        "profit_factor": round(profit_factor(values), 6),
        "win_rate": round(float((values > 0).mean()), 6),
        "expectancy": round(float(values.mean()), 6),
        "final_capital": round(final_capital, 6),
        "cagr_pct": round(cagr * 100.0, 6),
        "max_drawdown_pct": round(max_drawdown_pct(values, initial_capital), 6),
        "observed_frequency_sharpe": round(sharpe, 6),
        "trades_per_year": round(tpy, 6),
        "span_years": round(span_years, 6),
    }


def paired_block_bootstrap_ci(
    diffs_by_date: pd.Series,
    *,
    n_resamples: int = 5000,
    block_size: int = 10,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Moving-block paired CI clustered by signal date; positive means arm A wins."""
    stats = paired_block_bootstrap_stats(
        diffs_by_date,
        n_resamples=n_resamples,
        block_size=block_size,
        seed=seed,
    )
    return stats["mean"], stats["ci95_low"], stats["ci95_high"]


def paired_block_bootstrap_stats(
    diffs_by_date: pd.Series,
    *,
    n_resamples: int = 5000,
    block_size: int = 10,
    seed: int = 42,
) -> dict[str, float]:
    """Paired block-bootstrap mean, CI, and one-sided p for mean improvement > 0."""
    arr = np.asarray(diffs_by_date.sort_index(), dtype=float)
    n = len(arr)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "p_one_sided": 1.0}
    block_size = min(max(1, block_size), n)
    starts_max = n - block_size + 1
    n_blocks = int(math.ceil(n / block_size))
    rng = np.random.default_rng(seed)
    means = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        starts = rng.integers(0, starts_max, size=n_blocks)
        sample = np.concatenate([arr[s : s + block_size] for s in starts])[:n]
        means[i] = sample.mean()
    # Add-one correction prevents a zero p-value from a finite Monte Carlo draw.
    p_one_sided = (1.0 + float((means <= 0.0).sum())) / (n_resamples + 1.0)
    return {
        "mean": float(arr.mean()),
        "ci95_low": float(np.percentile(means, 2.5)),
        "ci95_high": float(np.percentile(means, 97.5)),
        "p_one_sided": p_one_sided,
    }
