"""Regression tests for the 2026-08-17 deep->shallow cache contamination (E2).

Root cause: ``_find_latest_cache(prefer_complete=True)`` vetoed the holed 7.3y
deep cache (``MES_2015-01-01_2026-08-16_1h.csv``, true span 2019-05-05 ->
2026-08-14) because ``US_MARKET_HOLIDAYS`` only whitelisted 2024-2026, so every
2019-2023 holiday gap was misjudged as an "unexplained missing weekday". The
picker silently fell back to a 2.3y shallow cache
(``MES_2024-04-26_2026-08-14_1h.csv``), producing fake 'deep' verdicts at
n_windows=20 instead of 82.

The fix has two layers:
1. ``cache_completeness.US_MARKET_HOLIDAYS`` / ``US_MARKET_EARLY_CLOSES`` now
   cover 2019-2023, so the deep cache is no longer falsely "holed" and IS
   selected (deep-cache selection when a deep file exists with holiday gaps).
2. ``_find_latest_cache`` logs a WARNING naming the exact cache chosen + reason
   when a material deep->shallow demotion would occur, and raises when
   ``GATE_V2_ENFORCE_DEEP_CACHE=1``.
"""
import os
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest._gate_v2_helpers import _find_latest_cache  # noqa: E402
from backtest.cache_completeness import (  # noqa: E402
    US_MARKET_EARLY_CLOSES,
    US_MARKET_HOLIDAYS,
)


def _write_hourly_cache(path, start, end, *, drop_dates=()):
    """Write a synthetic hourly bar cache; optionally drop whole calendar days.

    ``drop_dates`` are ISO date strings (e.g. '2020-03-09'). Dropping an
    unexplained mid-week day creates a REAL hole; dropping a whitelisted
    holiday creates the benign gap a deep cache legitimately carries.
    """
    import pandas as pd

    idx = pd.date_range(start, end, freq="1h", tz="UTC")
    if drop_dates:
        drop = {pd.Timestamp(d, tz="UTC").normalize() for d in drop_dates}
        idx = idx[[t.normalize() not in drop for t in idx]]
    pd.DataFrame({"timestamp": idx, "close": 1.0}).to_csv(path, index=False)


_DEEP = "MES_2015-01-01_2026-08-16_1h.csv"  # filename span ~11.6y (deep standard)
_SHALLOW = "MES_2024-04-26_2026-08-14_1h.csv"  # 2.3y shallow cache


@pytest.fixture()
def cache_dir(tmp_path):
    return tmp_path


def _holiday_gaps():
    """All whitelisted full-closure holidays within the deep span (2019-2023)."""
    return [d.isoformat() for d in US_MARKET_HOLIDAYS | US_MARKET_EARLY_CLOSES if d.year < 2024]


def test_deep_cache_selected_when_only_holiday_gaps(cache_dir, caplog):
    """Deep cache with 2019-2023 holiday gaps must WIN over a clean shallow cache.

    This is the exact 2026-08-17 contamination scenario: before the calendar
    fix the deep cache was vetoed as 'holed' and the shallow cache was silently
    used (fake 'deep' verdicts, n_windows=20). After the fix the deep cache is
    selected and NO demotion warning fires.
    """
    _write_hourly_cache(
        cache_dir / _DEEP,
        "2019-05-05",
        "2026-08-14",
        drop_dates=_holiday_gaps(),
    )
    _write_hourly_cache(cache_dir / _SHALLOW, "2024-04-26", "2026-08-14")

    with caplog.at_level("WARNING", logger="backtest._gate_v2_helpers"):
        chosen = _find_latest_cache(cache_dir, "MES")

    assert chosen.name == _DEEP, f"deep cache must be selected, got {chosen.name}"
    assert "DEEP->SHALLOW demotion" not in caplog.text


def test_deep_cache_with_real_hole_logs_loud_demotion(cache_dir, caplog):
    """A REAL unexplained hole in the deep cache must demote LOUDLY, not silently.

    The deep cache carries a genuine missing weekday (2020-03-09..13, no
    holiday). The completeness picker prefers the clean shallow cache, but
    ``_find_latest_cache`` must log a WARNING naming the exact cache chosen +
    reason so a 'deep' verdict can never silently run on 2.3y of data.
    """
    _write_hourly_cache(
        cache_dir / _DEEP,
        "2019-05-05",
        "2026-08-14",
        drop_dates=("2020-03-09", "2020-03-10", "2020-03-11", "2020-03-12", "2020-03-13"),
    )
    _write_hourly_cache(cache_dir / _SHALLOW, "2024-04-26", "2026-08-14")

    with caplog.at_level("WARNING", logger="backtest._gate_v2_helpers"):
        chosen = _find_latest_cache(cache_dir, "MES")

    assert "DEEP->SHALLOW demotion" in caplog.text
    assert _DEEP in caplog.text
    assert _SHALLOW in caplog.text
    assert chosen.name == _SHALLOW  # historical behavior: still returns chosen


def test_deep_cache_demotion_fails_fast_when_enforced(cache_dir, monkeypatch):
    """GATE_V2_ENFORCE_DEEP_CACHE=1 turns the demotion into a hard error."""
    _write_hourly_cache(
        cache_dir / _DEEP,
        "2019-05-05",
        "2026-08-14",
        drop_dates=("2020-03-09", "2020-03-10", "2020-03-11", "2020-03-12", "2020-03-13"),
    )
    _write_hourly_cache(cache_dir / _SHALLOW, "2024-04-26", "2026-08-14")

    monkeypatch.setenv("GATE_V2_ENFORCE_DEEP_CACHE", "1")
    with pytest.raises(RuntimeError, match="GATE_V2_ENFORCE_DEEP_CACHE"):
        _find_latest_cache(cache_dir, "MES")


def test_latest_end_refresh_pull_is_not_a_demotion(cache_dir, caplog):
    """Same-span refreshed pulls must NOT trip the demotion guard.

    The benign case the guard must preserve: two pulls of the SAME ~2.3y window
    with different end dates (2026-07-30 vs 2026-08-14). The later one wins via
    latest-end; no DEEP->SHALLOW warning.
    """
    _write_hourly_cache(cache_dir / "MES_2024-04-26_2026-07-30_1h.csv", "2024-04-26", "2026-07-30")
    _write_hourly_cache(cache_dir / "MES_2024-04-26_2026-08-14_1h.csv", "2024-04-26", "2026-08-14")

    with caplog.at_level("WARNING", logger="backtest._gate_v2_helpers"):
        chosen = _find_latest_cache(cache_dir, "MES")

    assert chosen.name == "MES_2024-04-26_2026-08-14_1h.csv"
    assert "DEEP->SHALLOW demotion" not in caplog.text


def test_single_deep_cache_no_completeness_scan(cache_dir, caplog):
    """A single deep cache is returned directly (zero inspection cost path)."""
    _write_hourly_cache(cache_dir / _DEEP, "2019-05-05", "2026-08-14")

    with caplog.at_level("WARNING", logger="backtest._gate_v2_helpers"):
        chosen = _find_latest_cache(cache_dir, "MES")

    assert chosen.name == _DEEP
    assert "DEEP->SHALLOW demotion" not in caplog.text
