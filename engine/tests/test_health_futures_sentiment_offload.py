"""SOTA plan P0.5: `_health_inner`'s futures-sentiment read must not block the
event loop.

`get_futures_sentiment_staleness` / `get_bias_extraction_health` each open a
synchronous `sqlite3.connect(...)` and run a query. Before this fix, `_health_
inner` called them inline inside an `async def`, so a slow read (DB
contention, a large WAL, disk pressure) would stall EVERY other in-flight
coroutine on the single event-loop thread for the duration of the call — the
same class of hazard already fixed for `db_manager.ping` and `get_pending_
approval_stats` (see the block comment above `_HEALTH_SNAPSHOT_TTL_SEC` in
health_router.py). This pins that the futures-sentiment read now runs via
`asyncio.to_thread`, so a slow/blocking underlying call cannot starve a
concurrent lightweight coroutine.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import discord.commentary_processor as commentary_processor
from routers import health_router

# Long enough that an inline (non-offloaded) blocking call is trivially
# distinguishable from event-loop scheduling jitter, short enough to keep the
# test fast.
_BLOCK_SEC = 0.35


def _slow_staleness(*_args, **_kwargs) -> dict:
    """Stand-in for a blocking SQLite read under contention."""
    time.sleep(_BLOCK_SEC)
    return {
        "quality": "fresh",
        "age_days": 1,
        "latest_timestamp": "2026-07-09T08:00:00-05:00",
        "threshold_days": 3,
    }


def _fast_bias_health(*_args, **_kwargs) -> dict:
    return {"extraction_quality": "unknown", "lag_days": None, "latest_bias_date": None}


def _inject_minimal_deps() -> None:
    """No live db/IB needed — _health_inner degrades gracefully when they're
    None, and this test only cares about the futures-sentiment call site."""
    health_router.inject_dependencies(
        start_time=datetime.now(timezone.utc),
        dm=None,
        sl=None,
        dbm=None,
        pt=None,
        pm=None,
        tp=None,
        schwab=None,
    )


@pytest.mark.asyncio
async def test_slow_futures_sentiment_read_does_not_stall_event_loop(monkeypatch):
    monkeypatch.setattr(
        commentary_processor, "get_futures_sentiment_staleness", _slow_staleness
    )
    monkeypatch.setattr(commentary_processor, "get_bias_extraction_health", _fast_bias_health)
    _inject_minimal_deps()

    ticks = {"n": 0}
    stop = asyncio.Event()

    async def _ticker() -> None:
        """A lightweight coroutine that should keep making progress
        concurrently with _health_inner() -- NOT starved until it finishes.

        Note: `_health_inner()` has no other genuine `await`-suspension point
        before the futures-sentiment call in this minimal-deps configuration
        (db_manager/safety_layer/data_manager are all None here), so if the
        futures-sentiment read runs inline (not offloaded), the health task
        never yields to the loop at all and this ticker gets ZERO ticks
        before the health task finishes -- regardless of the ticker's own
        sleep interval. That is the failure mode this test pins.
        """
        while not stop.is_set():
            await asyncio.sleep(0.01)
            ticks["n"] += 1

    with patch.object(health_router, "_compute_brier_30d_rolling", return_value=None):
        ticker_task = asyncio.create_task(_ticker())
        health_task = asyncio.create_task(health_router._health_inner())
        await asyncio.wait_for(health_task, timeout=5.0)
        ticks_while_health_pending = ticks["n"]
        stop.set()
        await ticker_task

    # If the blocking call ran inline on the event loop, `_health_inner()` has
    # no other real suspension point in this config, so it hogs the single
    # event-loop thread for its ENTIRE synchronous run (including the mocked
    # `_BLOCK_SEC` sleep) and the ticker gets no chance to run until it's
    # done -> ticks_while_health_pending == 0. Offloaded via asyncio.to_thread,
    # awaiting the thread genuinely yields control back to the loop, so the
    # ticker accumulates several ticks while the thread pool handles the sleep.
    assert ticks_while_health_pending > 0, (
        "ticker made zero progress while _health_inner() was pending -- the "
        "futures-sentiment read is blocking the event loop instead of "
        "running via asyncio.to_thread"
    )


@pytest.mark.asyncio
async def test_futures_sentiment_result_shape_unchanged_after_offload(monkeypatch):
    """Functional correctness: moving the call behind asyncio.to_thread must
    not change the returned data."""

    def _staleness(*_a, **_kw) -> dict:
        return {
            "quality": "stale",
            "age_days": 5,
            "latest_timestamp": "2026-07-01T08:00:00-05:00",
            "threshold_days": 3,
        }

    def _bias_health(*_a, **_kw) -> dict:
        return {"extraction_quality": "degraded", "lag_days": 4, "latest_bias_date": "2026-07-01"}

    monkeypatch.setattr(commentary_processor, "get_futures_sentiment_staleness", _staleness)
    monkeypatch.setattr(commentary_processor, "get_bias_extraction_health", _bias_health)
    _inject_minimal_deps()

    with patch.object(health_router, "_compute_brier_30d_rolling", return_value=None):
        result = await health_router._health_inner()

    fs = result["futures_sentiment"]
    assert fs["quality"] == "stale"
    assert fs["age_days"] == 5
    assert fs["latest_timestamp"] == "2026-07-01T08:00:00-05:00"
    assert fs["threshold_days"] == 3
    assert fs["extraction_quality"] == "degraded"
    assert fs["extraction_lag_days"] == 4
    assert fs["latest_bias_date"] == "2026-07-01"


@pytest.mark.asyncio
async def test_futures_sentiment_exception_falls_back_to_unknown(monkeypatch):
    """The try/except around the offloaded call must still swallow failures
    from inside the worker thread, same as the prior inline behavior."""

    def _raise_staleness(*_a, **_kw):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(commentary_processor, "get_futures_sentiment_staleness", _raise_staleness)
    _inject_minimal_deps()

    with patch.object(health_router, "_compute_brier_30d_rolling", return_value=None):
        result = await health_router._health_inner()

    assert result["futures_sentiment"] == {"quality": "unknown", "age_days": None}
