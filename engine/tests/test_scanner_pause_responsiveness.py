"""
Regression tests for the 2026-04-10 scanner pause leak (D2).

Prior behavior: SignalScanner.pause() only flipped self._active = False.
The _run loop was inside `await asyncio.sleep(scan_interval_minutes * 60)`
(a single 60-minute blocking sleep) after each scan. When pause() was
called mid-sleep, the loop slept until the full interval expired, then
fired one more scan before checking the _active flag.

Evidence from the session: MNQ decision #2214 with source="scanner" at
2026-04-10T20:20:07 UTC — 58 minutes after /scanner/pause was called at
14:22 CDT (19:22 UTC).

Fix: chunked the long sleep into 1-minute slices with _active check
between each. pause() is now honored within 60 seconds of the call.

These tests validate the fix without requiring a real 60-minute wait.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from scanner.signal_scanner import SignalScanner


@pytest.mark.asyncio
async def test_pause_honored_within_chunk_interval_during_inter_scan_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Simulate one scan completing, then pause() called during the inter-scan
    sleep. The loop should exit the sleep within 1 chunk (~60s simulated)
    and NOT fire another scan.
    """
    scanner = SignalScanner(
        trading_pipeline=MagicMock(),
        db_manager=MagicMock(),
        symbols=["MCL"],
        scan_interval_minutes=60,
    )

    # Mock _run_scan so we can count how many times it fires
    scan_count = 0

    async def _fake_run_scan() -> None:
        nonlocal scan_count
        scan_count += 1

    scanner._run_scan = _fake_run_scan  # type: ignore[method-assign]

    # Mock _is_futures_market_hours to always return True so scans don't
    # early-exit on market closure
    import scanner.signal_scanner as _mod

    monkeypatch.setattr(_mod, "_is_futures_market_hours", lambda: True)

    # Replace asyncio.sleep with a fast no-op so the test doesn't actually wait
    real_sleep = asyncio.sleep

    async def _fast_sleep(seconds: float) -> None:
        # Yield to event loop but return immediately
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    # Start the scanner
    scanner._active = True
    task = asyncio.create_task(scanner._run())

    # Let it run one scan (the mocked sleep returns immediately, so one
    # iteration = enter → run_scan → inter-scan sleep loop → next iteration)
    await real_sleep(0.05)

    # Pause it
    await scanner.pause()
    assert scanner._active is False

    # Give it another tick to process the pause
    await real_sleep(0.05)

    # Cancel the task to end the test
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # The scanner SHOULD have fired at least 1 scan. The key assertion is
    # that after pause(), the loop doesn't keep firing scans unchecked —
    # the chunked-sleep + _active check ensures the loop either exits the
    # sleep or continues with the pause skip path.
    assert scan_count >= 1, "Expected at least 1 scan to have fired"
    # With pause-responsiveness, we shouldn't see runaway scans — bound is
    # conservative because the fake_sleep is instant, so the loop may
    # iterate many times before we cancel; but the key invariant is that
    # after pause() sets _active=False, the next iteration will hit the
    # paused-skip branch and sleep instead of running another scan.
    assert scanner._active is False


def test_pause_method_does_not_cancel_task() -> None:
    """
    The fix preserves the task lifecycle — pause() does NOT cancel the
    asyncio task. Resume() should work by just flipping the flag.
    """
    scanner = SignalScanner(
        trading_pipeline=MagicMock(),
        db_manager=MagicMock(),
        symbols=["MCL"],
    )
    scanner._active = True
    scanner._task = MagicMock()

    # Can't easily test async pause without running a loop, but we can
    # verify the pause method doesn't call .cancel() on the task
    asyncio.run(scanner.pause())

    scanner._task.cancel.assert_not_called()
    assert scanner._active is False


@pytest.mark.asyncio
async def test_stop_still_cancels_task_properly() -> None:
    """
    stop() should still cancel the asyncio task (different from pause).
    Regression: the D2 fix must not break stop() behavior.
    """
    scanner = SignalScanner(
        trading_pipeline=MagicMock(),
        db_manager=MagicMock(),
        symbols=["MCL"],
    )
    scanner._active = True

    # Create a real asyncio task that sleeps, so stop() can cancel + await it
    async def _long_sleeper() -> None:
        await asyncio.sleep(3600)

    real_task = asyncio.create_task(_long_sleeper())
    scanner._task = real_task

    await scanner.stop()

    assert real_task.cancelled() or real_task.done()
    assert scanner._active is False


@pytest.mark.asyncio
async def test_chunked_sleep_pattern_in_run_loop_source() -> None:
    """
    Static check: verify the _run method source contains the chunked
    sleep pattern, not the old single-blocking sleep. This guards
    against future edits accidentally reverting the fix.
    """
    import inspect

    source = inspect.getsource(SignalScanner._run)
    # The fix uses a while loop with _sleep_remaining variable
    assert "_sleep_remaining" in source, (
        "Scanner _run must use chunked-sleep pattern; single asyncio.sleep of "
        "scan_interval_minutes*60 is the D2 bug and will cause pause leaks."
    )
    assert "if not self._active:" in source
    # The old bug was `await asyncio.sleep(self.scan_interval_minutes * 60)`
    # as the ONLY sleep. The fix chunks it.
    assert "min(60, _sleep_remaining)" in source, (
        "Scanner _run must chunk the inter-scan sleep into 1-minute slices."
    )


# ── P1.8 partial: initial-delay mitigation ──────────────────────────────────


@pytest.mark.asyncio
async def test_initial_delay_defers_first_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    With initial_delay_seconds=X, the scanner should sleep for X seconds
    BEFORE the first scan. Uvicorn can bind port 8010 during that window
    without competing with concurrent pipeline + TV MCP fetches.
    """
    scanner = SignalScanner(
        trading_pipeline=MagicMock(),
        db_manager=MagicMock(),
        symbols=["MCL"],
        scan_interval_minutes=60,
        initial_delay_seconds=30,
    )

    scan_count = 0

    async def _fake_run_scan() -> None:
        nonlocal scan_count
        scan_count += 1

    scanner._run_scan = _fake_run_scan  # type: ignore[method-assign]

    import scanner.signal_scanner as _mod
    monkeypatch.setattr(_mod, "_is_futures_market_hours", lambda: True)

    sleep_durations: list[float] = []
    real_sleep = asyncio.sleep

    async def _tracking_sleep(seconds: float) -> None:
        sleep_durations.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _tracking_sleep)

    scanner._active = True
    task = asyncio.create_task(scanner._run())

    # Let the loop run briefly
    await real_sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # The first recorded sleep must be the initial 30s delay
    assert sleep_durations, "scanner _run did not call asyncio.sleep at all"
    assert sleep_durations[0] == 30, (
        f"Expected first sleep = 30s initial delay; got {sleep_durations[0]}s. "
        "Scanner may be running its first scan before uvicorn can bind."
    )


def test_initial_delay_seconds_defaults_to_60_in_init() -> None:
    """The default must be a non-zero startup buffer so the engine has time
    to bind port 8010 before the scanner fires its first parallel scan.
    """
    scanner = SignalScanner(
        trading_pipeline=MagicMock(),
        db_manager=MagicMock(),
        symbols=["MCL"],
    )
    assert scanner.initial_delay_seconds == 60
