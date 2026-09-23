"""Family-wide tz probe: keep the whole VIX-gated research family measurable.

Why this exists (2026-09-17)
----------------------------
`MES_sma_trend_vix_pctile_blockCrisis_v1` produced no verdict at all because every
walk-forward window raised `TypeError: Cannot compare dtypes datetime64[s] and
datetime64[us, UTC]`. The cause was a **mixed-tz comparison**: a tz-naive daily VIX
index (yfinance) against a tz-aware bar index (deep-cache timestamps carry `+00:00`
offsets). pandas >= 3.0 raises on that instead of silently comparing unequal.

The failure was **family-wide and silent**: ten-plus modules pass `vix_df` into the
shared signal path, and four more performed their own `ffill` reindex. A single
unit test on one module would not have caught it — nothing exercised a tz-aware bar
index at all.

This module is the standing probe for that class of blindness:
  1. a static invariant — no `backtest/*.py` may feed a bare `.normalize()` index
     straight into `reindex(...)`, which is exactly the mixed-tz trap;
  2. positive assertions that the modules that DO reindex daily VIX/regime data
     route through the shared `_daily_date_index` helper;
  3. a live call of one of those family call sites with a tz-aware bar index;
  4. an integration probe against the real deep cache when it is present.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BACKTEST_DIR = Path(__file__).resolve().parent.parent / "backtest"

#: Modules that reindex daily VIX / daily-regime data onto a bar index.
#: Each must normalise both sides through the shared helper.
FAMILY_REINDEXERS = (
    "trend_signals.py",
    "composite_strategies.py",
    "run_spy_qqq_options_vertical.py",
    "run_mgc_trend_mtf_rank1.py",
)

#: The mixed-tz trap: a bare `.normalize()` expression used as a reindex target.
BARE_NORMALIZE_IN_REINDEX = re.compile(r"reindex\(\s*[^,)]*\.normalize\(\)")

DEEP_CACHE = "MES_2019-05-05_2026-08-26_1h.csv"


def _source(name: str) -> str:
    return (BACKTEST_DIR / name).read_text(encoding="utf-8")


def test_no_bare_normalize_index_feeds_a_reindex():
    """Static invariant: the mixed-tz trap must not exist anywhere in backtest/."""
    offenders = []
    for path in sorted(BACKTEST_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if BARE_NORMALIZE_IN_REINDEX.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Mixed-tz reindex target found; route both sides through "
        "trend_signals._daily_date_index instead:\n" + "\n".join(offenders)
    )


def test_scan_is_not_vacuous_python_source_is_reachable():
    """Guard the guard: the scan must actually be reading real source files."""
    py_files = list(BACKTEST_DIR.glob("*.py"))
    assert len(py_files) > 20
    assert "reindex" in _source("trend_signals.py")


@pytest.mark.parametrize("name", FAMILY_REINDEXERS)
def test_family_reindexers_use_the_shared_tz_helper(name: str):
    text = _source(name)
    assert "_daily_date_index" in text, (
        f"{name} reindexes daily VIX/regime data without the shared tz helper; "
        "this is the mixed-tz trap that aborted all 82 windows on 2026-09-17"
    )


def _bars(n: int = 200, tz: str | None = "UTC") -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz=tz)
    close = pd.Series(np.linspace(100.0, 120.0, n), index=idx)
    return pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5, "close": close},
                        index=idx)


def _vix(days: int = 40) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=days, freq="D")
    return pd.DataFrame({"close": np.linspace(12.0, 28.0, days)}, index=idx)


def test_composite_family_call_site_survives_tz_aware_bars():
    """Live call of a real family call site with a tz-aware bar index."""
    from backtest.composite_strategies import _vix_series_and_tiers

    vix_series, tiers = _vix_series_and_tiers(
        _bars(tz="UTC"), _vix(), 0.0, 999.0, ("Crisis",), 20
    )
    assert vix_series is not None
    assert vix_series.notna().any(), "VIX never populated onto the bar index"
    assert len(vix_series) == len(_bars(tz="UTC"))


def test_composite_family_call_site_is_tz_invariant():
    """Tz-aware and tz-naive bar indexes must give identical VIX levels."""
    from backtest.composite_strategies import _vix_series_and_tiers

    aware, _ = _vix_series_and_tiers(_bars(tz="UTC"), _vix(), 0.0, 999.0, None, 20)
    naive, _ = _vix_series_and_tiers(_bars(tz=None), _vix(), 0.0, 999.0, None, 20)
    assert np.array_equal(aware.to_numpy(dtype=float), naive.to_numpy(dtype=float), equal_nan=True)


def test_deep_cache_is_tz_aware_and_measurable_when_present():
    """Integration probe against the real deep cache (skipped when absent).

    Locks the condition that triggered the original bug: the deep cache IS
    tz-aware, so any code path that compares it to a naive daily index must go
    through the shared helper.
    """
    cache = BACKTEST_DIR / "cache" / DEEP_CACHE
    if not cache.exists():
        pytest.skip(f"deep cache not present in this worktree: {DEEP_CACHE}")

    df = pd.read_csv(cache)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    assert df.index.tz is not None, "deep cache is expected to be tz-aware (+00:00 offsets)"

    from backtest.trend_signals import generate_sma_trend_signals

    sample = df.iloc[:600]
    # VIX fixture must cover the SAMPLE's own dates (the deep cache starts 2019),
    # otherwise the ffill legitimately returns all-NaN and the assertion is vacuous.
    days = pd.date_range(str(sample.index.min().date()), str(sample.index.max().date()), freq="D")
    assert days.tz is None, "fixture must be naive to mirror the yfinance daily index"
    vix_daily = pd.DataFrame({"close": np.linspace(12.0, 28.0, len(days))}, index=days)
    assert vix_daily.index.tz is None, "fixture mirrors the naive yfinance index"

    out = generate_sma_trend_signals(sample, fast=10, slow=30, vix_df=vix_daily)
    assert out["vix_level"].notna().any(), "tz-aware deep cache produced no VIX levels"
