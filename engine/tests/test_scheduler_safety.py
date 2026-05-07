"""Tests for engine/utils/scheduler_safety.py.

Covers the three-gate scheduler safety contract:

1. ``staggered_offset`` is deterministic and bounded.
2. ``in_quiet_hours`` handles same-day and wrap-around windows.
3. ``StaggeredCronRunner.wrap`` enforces quiet-hours + dedupe + passes
   through args/return values cleanly.
4. Env parsing returns safe ``None`` defaults on bad input.

No APScheduler dependency — runners are tested with direct awaits.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from datetime import time as dtime
from unittest import mock

import pytest

from utils.scheduler_safety import (
    StaggeredCronRunner,
    in_quiet_hours,
    quiet_hours_from_env,
    staggered_offset,
)

# ---------------------------------------------------------------------------
# staggered_offset
# ---------------------------------------------------------------------------


def test_staggered_offset_deterministic():
    # Same input → same output, every time.
    a = staggered_offset("eod_snapshot", spread_minutes=5)
    b = staggered_offset("eod_snapshot", spread_minutes=5)
    assert a == b


def test_staggered_offset_within_bounds():
    for job_id in ("eod_snapshot", "weekly_review", "vix_alert", "morning_brief"):
        off = staggered_offset(job_id, spread_minutes=5)
        assert 0 <= off < 5


def test_staggered_offset_zero_spread_returns_zero():
    assert staggered_offset("eod_snapshot", spread_minutes=0) == 0


def test_staggered_offset_differentiates_jobs():
    # Four common jobs should not all collide on the same minute — at
    # spread=5 collisions are probabilistically possible but the set of
    # offsets must have at least 2 distinct values across 4 inputs.
    offsets = {
        staggered_offset("eod_snapshot", 5),
        staggered_offset("weekly_review", 5),
        staggered_offset("vix_alert_check", 5),
        staggered_offset("morning_briefing", 5),
    }
    assert len(offsets) >= 2


# ---------------------------------------------------------------------------
# in_quiet_hours
# ---------------------------------------------------------------------------


def _ct_at(hour: int, minute: int = 0) -> datetime:
    """Return a UTC datetime that corresponds to HH:MM in America/Chicago."""
    from zoneinfo import ZoneInfo

    return datetime(2026, 4, 17, hour, minute, tzinfo=ZoneInfo("America/Chicago")).astimezone(
        timezone.utc
    )


def test_in_quiet_hours_none_bounds_never_quiet():
    now = _ct_at(3, 0)
    assert in_quiet_hours(now, None, None) is False
    assert in_quiet_hours(now, dtime(22, 0), None) is False
    assert in_quiet_hours(now, None, dtime(6, 0)) is False


def test_in_quiet_hours_same_day_window():
    start = dtime(13, 0)
    end = dtime(14, 0)
    assert in_quiet_hours(_ct_at(13, 30), start, end) is True
    assert in_quiet_hours(_ct_at(14, 0), start, end) is False  # end is exclusive
    assert in_quiet_hours(_ct_at(12, 59), start, end) is False


def test_in_quiet_hours_wrap_around_midnight():
    start = dtime(22, 0)
    end = dtime(6, 0)
    assert in_quiet_hours(_ct_at(23, 0), start, end) is True
    assert in_quiet_hours(_ct_at(2, 0), start, end) is True
    assert in_quiet_hours(_ct_at(5, 59), start, end) is True
    assert in_quiet_hours(_ct_at(6, 0), start, end) is False
    assert in_quiet_hours(_ct_at(9, 0), start, end) is False
    assert in_quiet_hours(_ct_at(21, 59), start, end) is False


# ---------------------------------------------------------------------------
# StaggeredCronRunner.wrap
# ---------------------------------------------------------------------------


async def _probe(calls: list, value: int = 0) -> int:
    calls.append(value)
    return value


async def test_wrap_runs_job_when_no_gate_fires():
    runner = StaggeredCronRunner(
        job_id="test_job",
        respect_quiet_hours=False,
        dedupe_seconds=0.0,
    )
    calls: list = []
    wrapped = runner.wrap(lambda: _probe(calls, 42))
    result = await wrapped()
    assert result == 42
    assert calls == [42]


async def test_wrap_skips_in_quiet_hours():
    # Force "always in quiet hours" by widening the window to the full day.
    runner = StaggeredCronRunner(
        job_id="quiet_job",
        respect_quiet_hours=True,
        quiet_start=dtime(0, 0),
        quiet_end=dtime(23, 59),
        quiet_tz="UTC",
        dedupe_seconds=0.0,
    )
    calls: list = []
    wrapped = runner.wrap(lambda: _probe(calls, 1))
    result = await wrapped()
    assert result is None
    assert calls == []


async def test_wrap_ignores_quiet_hours_when_opted_out():
    runner = StaggeredCronRunner(
        job_id="critical_job",
        respect_quiet_hours=False,
        quiet_start=dtime(0, 0),
        quiet_end=dtime(23, 59),
        quiet_tz="UTC",
        dedupe_seconds=0.0,
    )
    calls: list = []
    wrapped = runner.wrap(lambda: _probe(calls, 7))
    assert await wrapped() == 7
    assert calls == [7]


async def test_wrap_dedupes_rapid_reentry():
    runner = StaggeredCronRunner(
        job_id="dedup_job",
        respect_quiet_hours=False,
        dedupe_seconds=60.0,
    )
    calls: list = []
    wrapped = runner.wrap(lambda: _probe(calls, 1))
    assert await wrapped() == 1
    # Second call inside dedupe window is skipped.
    assert await wrapped() is None
    assert calls == [1]


async def test_wrap_allows_reentry_after_dedupe_window():
    runner = StaggeredCronRunner(
        job_id="dedup_window_job",
        respect_quiet_hours=False,
        dedupe_seconds=0.01,
    )
    calls: list = []
    wrapped = runner.wrap(lambda: _probe(calls, 2))
    assert await wrapped() == 2
    # Sleep past the dedupe window, then re-run.
    await asyncio.sleep(0.02)
    assert await wrapped() == 2
    assert calls == [2, 2]


async def test_wrap_propagates_exceptions():
    runner = StaggeredCronRunner(
        job_id="throwing_job", respect_quiet_hours=False, dedupe_seconds=0.0
    )

    async def _boom() -> None:
        raise RuntimeError("boom")

    wrapped = runner.wrap(_boom)
    with pytest.raises(RuntimeError, match="boom"):
        await wrapped()


def test_wrap_preserves_callable_name():
    runner = StaggeredCronRunner(job_id="named", respect_quiet_hours=False, dedupe_seconds=0.0)

    async def run_eod_snapshot() -> str:
        return "ok"

    wrapped = runner.wrap(run_eod_snapshot)
    assert wrapped.__name__ == "run_eod_snapshot"


def test_should_skip_returns_reason_strings():
    runner = StaggeredCronRunner(
        job_id="skip_reason",
        respect_quiet_hours=True,
        quiet_start=dtime(0, 0),
        quiet_end=dtime(23, 59),
        quiet_tz="UTC",
        dedupe_seconds=5.0,
    )
    # Quiet hours skip reason.
    assert runner.should_skip() == "quiet_hours"


# ---------------------------------------------------------------------------
# quiet_hours_from_env
# ---------------------------------------------------------------------------


def test_quiet_hours_from_env_unset_returns_none():
    with mock.patch.dict(os.environ, {}, clear=False):
        for k in ("JARVIS_QUIET_HOURS_START", "JARVIS_QUIET_HOURS_END"):
            os.environ.pop(k, None)
        start, end, tz = quiet_hours_from_env()
        assert start is None
        assert end is None
        assert tz == "America/Chicago"


def test_quiet_hours_from_env_parses_valid_values():
    with mock.patch.dict(
        os.environ,
        {
            "JARVIS_QUIET_HOURS_START": "22:00",
            "JARVIS_QUIET_HOURS_END": "06:30",
            "JARVIS_QUIET_HOURS_TZ": "UTC",
        },
    ):
        start, end, tz = quiet_hours_from_env()
        assert start == dtime(22, 0)
        assert end == dtime(6, 30)
        assert tz == "UTC"


def test_quiet_hours_from_env_malformed_falls_back_to_none():
    with mock.patch.dict(
        os.environ,
        {"JARVIS_QUIET_HOURS_START": "not-a-time", "JARVIS_QUIET_HOURS_END": ""},
    ):
        start, end, _ = quiet_hours_from_env()
        assert start is None
        assert end is None
