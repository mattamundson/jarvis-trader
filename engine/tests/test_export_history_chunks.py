"""
Unit tests for the WS3 deep-history chunk planner in
engine/backtest/export_ibkr_history.py.

Pure / offline -- no IB connection, no network. Exercises plan_history_chunks,
the IB endDateTime formatter, and the filename-contract fix that lets 5m/15m
intraday caches actually persist.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backtest.export_ibkr_history import (
    CACHE_FILENAME_CONTRACT,
    INTERVAL_CHUNK_DAYS,
    INTERVAL_DEPTH_DAYS,
    _ib_enddate,
    plan_history_chunks,
)

_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)


def _total_days(plan):
    return sum(int(dur.split()[0]) for _, dur in plan)


# ── filename contract now accepts intraday 'm' intervals ──────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "MES_2024-01-01_2026-03-28_1h.csv",
        "MNQ_2021-06-01_2026-06-01_1d.csv",
        "MES_2021-01-01_2026-01-01_5m.csv",
        "M2K_2021-01-01_2026-01-01_15m.csv",
    ],
)
def test_contract_accepts_valid_names(name):
    assert CACHE_FILENAME_CONTRACT.match(name)


@pytest.mark.parametrize(
    "name",
    [
        "MES_2024-01-01_2026-03-28.csv",       # missing interval
        "MES_2024-01-01_2026-03-28_1x.csv",    # bad unit
        "mes_2024-01-01_2026-03-28_1h.csv",    # lowercase symbol
        "MES_20240101_2026-03-28_1h.csv",      # non-ISO date
    ],
)
def test_contract_rejects_bad_names(name):
    assert not CACHE_FILENAME_CONTRACT.match(name)


# ── _ib_enddate ───────────────────────────────────────────────────────────────


def test_ib_enddate_utc_format():
    assert _ib_enddate(_NOW) == "20260616 12:00:00 UTC"


def test_ib_enddate_converts_to_utc():
    from datetime import timedelta

    est = timezone(timedelta(hours=-5))
    dt = datetime(2026, 6, 16, 7, 0, 0, tzinfo=est)  # == 12:00 UTC
    assert _ib_enddate(dt) == "20260616 12:00:00 UTC"


# ── plan_history_chunks ───────────────────────────────────────────────────────


def test_daily_single_request():
    plan = plan_history_chunks("1d", now=_NOW)
    assert len(plan) == 1
    assert plan[0] == ("", "3650 D")  # 10y daily, one call
    assert _total_days(plan) == INTERVAL_DEPTH_DAYS["1d"]


def test_5m_chunks_monthly_over_5y():
    plan = plan_history_chunks("5m", now=_NOW)
    # ceil(1825 / 30) == 61 chunks
    assert len(plan) == 61
    assert plan[0][0] == ""  # newest chunk = now
    assert plan[0][1] == "30 D"
    # last chunk holds the remainder: 1825 - 60*30 = 25
    assert plan[-1][1] == "25 D"
    # total coverage is exactly the target depth (no truncation, no overrun)
    assert _total_days(plan) == 1825


def test_chunks_walk_enddate_backwards():
    plan = plan_history_chunks("1h", now=_NOW, depth_days=730)
    assert len(plan) == 2  # ceil(730/365)
    assert plan[0] == ("", "365 D")
    # second chunk ends 365 days before now
    assert plan[1][0] == "20250616 12:00:00 UTC"
    assert plan[1][1] == "365 D"


def test_non_divisible_depth_remainder():
    plan = plan_history_chunks("1h", now=_NOW, depth_days=400)
    assert [d for _, d in plan] == ["365 D", "35 D"]
    assert _total_days(plan) == 400


def test_incremental_gap_only():
    last = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)  # 10 days ago
    plan = plan_history_chunks("1h", now=_NOW, last_bar=last)
    # gap = 10 + 2 buffer = 12 days, well under one 365-day chunk
    assert plan == [("", "12 D")]


def test_unknown_interval_raises():
    with pytest.raises(ValueError):
        plan_history_chunks("3m", now=_NOW)


def test_depth_default_matches_config():
    for interval in INTERVAL_CHUNK_DAYS:
        plan = plan_history_chunks(interval, now=_NOW)
        assert _total_days(plan) == INTERVAL_DEPTH_DAYS[interval]
