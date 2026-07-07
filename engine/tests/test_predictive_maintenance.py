"""
Tests for engine/monitoring/predictive_maintenance.py

Covers:
  - Default-off flag behaviour
  - sample_now() dict shape (mocked psutil / subprocess)
  - degradation_score() boundary cases (healthy, memory growth, IB reconnect)
  - should_restart_preemptively() cooldown logic
  - Auto-restart gated behind PREDICTIVE_MAINTENANCE_ALLOW_RESTART
  - monitor_loop() swallows sample errors and keeps running
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Allow both `cd engine && pytest` and `pytest engine/tests/` invocation styles
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_sample(
    *,
    memory_mb: float | None = 300.0,
    ib_reconnects_1h: int | None = 0,
    llm_p95_ms: float | None = 2000.0,
    uptime_seconds: float | None = 3600.0,
    pm2_restart_count: int | None = 0,
    ts: str | None = None,
) -> dict[str, Any]:
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat()
    return {
        "ts": ts,
        "memory_mb": memory_mb,
        "ib_reconnects_1h": ib_reconnects_1h,
        "llm_p95_ms": llm_p95_ms,
        "uptime_seconds": uptime_seconds,
        "pm2_restart_count": pm2_restart_count,
    }


def _make_history_with_mem(start_mb: float, end_mb: float, n: int = 6) -> list[dict]:
    """Build synthetic history with linear memory growth for scoring tests."""
    now = time.time()
    history = []
    for i in range(n):
        age_seconds = (n - 1 - i) * 600  # 10-min spacing, oldest first
        ts = datetime.fromtimestamp(now - age_seconds, tz=timezone.utc).isoformat()
        mem = start_mb + (end_mb - start_mb) * i / max(n - 1, 1)
        history.append(_make_sample(memory_mb=mem, ts=ts))
    return history


# ── Flag tests ────────────────────────────────────────────────────────────────


class TestFlags:
    def test_disabled_by_default(self, monkeypatch):
        """ENABLE_PREDICTIVE_MAINTENANCE must be absent or '0' → disabled."""
        monkeypatch.delenv("ENABLE_PREDICTIVE_MAINTENANCE", raising=False)
        monkeypatch.delenv("PREDICTIVE_MAINTENANCE_ALLOW_RESTART", raising=False)

        from monitoring.predictive_maintenance import (
            is_auto_restart_allowed,
            is_predictive_maintenance_enabled,
        )

        assert is_predictive_maintenance_enabled() is False
        assert is_auto_restart_allowed() is False

    def test_enable_flag_activates_monitor(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREDICTIVE_MAINTENANCE", "1")
        monkeypatch.delenv("PREDICTIVE_MAINTENANCE_ALLOW_RESTART", raising=False)

        from monitoring.predictive_maintenance import (
            is_auto_restart_allowed,
            is_predictive_maintenance_enabled,
        )

        assert is_predictive_maintenance_enabled() is True
        assert is_auto_restart_allowed() is False  # restart still off

    def test_auto_restart_requires_both_flags(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREDICTIVE_MAINTENANCE", "1")
        monkeypatch.setenv("PREDICTIVE_MAINTENANCE_ALLOW_RESTART", "1")

        from monitoring.predictive_maintenance import is_auto_restart_allowed

        assert is_auto_restart_allowed() is True

    def test_auto_restart_off_when_only_restart_flag_set(self, monkeypatch):
        monkeypatch.delenv("ENABLE_PREDICTIVE_MAINTENANCE", raising=False)
        monkeypatch.setenv("PREDICTIVE_MAINTENANCE_ALLOW_RESTART", "1")

        from monitoring.predictive_maintenance import is_auto_restart_allowed

        assert is_auto_restart_allowed() is False


# ── sample_now() shape tests ──────────────────────────────────────────────────


class TestSampleNow:
    @pytest.mark.asyncio
    async def test_sample_now_returns_required_keys(self):
        """sample_now() must return dict with all six required keys."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor()

        # Mock all I/O: psutil, log reads, http call, subprocess
        with (
            patch(
                "monitoring.predictive_maintenance.HealthMonitor._count_ib_reconnects_1h",
                return_value=0,
            ),
            patch(
                "monitoring.predictive_maintenance.HealthMonitor._read_llm_p95_ms",
                return_value=1500.0,
            ),
            patch(
                "monitoring.predictive_maintenance.HealthMonitor._read_engine_uptime",
                new_callable=AsyncMock,
                return_value=3600.0,
            ),
            patch(
                "monitoring.predictive_maintenance.HealthMonitor._read_pm2_restart_count",
                return_value=2,
            ),
            patch("psutil.Process") as mock_proc,
        ):
            mock_proc.return_value.memory_info.return_value.rss = 314572800  # 300 MB
            sample = await monitor.sample_now()

        required_keys = {
            "ts",
            "memory_mb",
            "ib_reconnects_1h",
            "llm_p95_ms",
            "uptime_seconds",
            "pm2_restart_count",
        }
        assert required_keys.issubset(
            sample.keys()
        ), f"Missing keys: {required_keys - sample.keys()}"

    @pytest.mark.asyncio
    async def test_sample_now_handles_psutil_error_gracefully(self):
        """If psutil raises, memory_mb is None and no exception propagates."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor()

        with (
            patch(
                "monitoring.predictive_maintenance.HealthMonitor._count_ib_reconnects_1h",
                return_value=0,
            ),
            patch(
                "monitoring.predictive_maintenance.HealthMonitor._read_llm_p95_ms",
                return_value=None,
            ),
            patch(
                "monitoring.predictive_maintenance.HealthMonitor._read_engine_uptime",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "monitoring.predictive_maintenance.HealthMonitor._read_pm2_restart_count",
                return_value=None,
            ),
            patch("psutil.Process", side_effect=RuntimeError("psutil broken")),
        ):
            sample = await monitor.sample_now()

        assert "memory_mb" in sample
        assert sample["memory_mb"] is None


# ── degradation_score() tests ─────────────────────────────────────────────────


class TestDegradationScore:
    def test_score_low_when_healthy(self):
        """Healthy sample with stable memory → score < 0.2."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor()
        sample = _make_sample(
            memory_mb=300.0, ib_reconnects_1h=0, llm_p95_ms=2000.0, pm2_restart_count=0
        )
        history = _make_history_with_mem(295.0, 300.0)  # trivial growth

        score = monitor.degradation_score(sample, history)
        assert score < 0.2, f"Expected healthy score < 0.2, got {score}"

    def test_score_high_on_memory_growth(self):
        """Rapid memory growth should contribute the full 0.30 weight component."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor(mem_growth_threshold_mb_per_hour=200.0)
        # 2h history: 100 MB → 900 MB (400 MB/hour = 2× threshold → full 0.30 contribution)
        history = _make_history_with_mem(100.0, 700.0, n=12)  # 12 samples × 10min = 2h
        sample = _make_sample(memory_mb=900.0, ib_reconnects_1h=0, pm2_restart_count=0)

        score = monitor.degradation_score(sample, history)
        # Memory growth alone maxes at 0.30; verify it's contributing fully
        assert score >= 0.28, f"Expected score >= 0.28 from memory growth signal, got {score}"

        # Also verify that combining with IB reconnect spike pushes above 0.6
        sample_with_reconnects = _make_sample(
            memory_mb=900.0, ib_reconnects_1h=10, pm2_restart_count=0
        )
        score_combined = monitor.degradation_score(sample_with_reconnects, history)
        assert (
            score_combined >= 0.6
        ), f"Expected score >= 0.6 with memory growth + IB reconnects, got {score_combined}"

    def test_score_high_on_ib_reconnect_spike(self):
        """IB reconnects > threshold with no other signals → score == 0.30."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor(ib_reconnect_threshold=5)
        sample = _make_sample(
            memory_mb=300.0, ib_reconnects_1h=10, llm_p95_ms=2000.0, pm2_restart_count=0
        )
        history = _make_history_with_mem(298.0, 300.0)  # stable memory

        score = monitor.degradation_score(sample, history)
        assert score >= 0.30, f"Expected at least 0.30 from IB reconnects, got {score}"

    def test_score_max_when_all_signals_fire(self):
        """All four signals firing → score == 1.0."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor(
            mem_growth_threshold_mb_per_hour=100.0,
            ib_reconnect_threshold=3,
            llm_latency_baseline_ms=1000.0,
        )
        # Memory growth > threshold
        history = _make_history_with_mem(100.0, 500.0, n=12)
        # Add a historical entry with lower pm2 count so delta fires
        older_ts = datetime.fromtimestamp(time.time() - 300, tz=timezone.utc).isoformat()
        history.append(_make_sample(memory_mb=480.0, pm2_restart_count=2, ts=older_ts))

        sample = _make_sample(
            memory_mb=900.0,
            ib_reconnects_1h=10,  # > threshold=3
            llm_p95_ms=5000.0,  # > 2× baseline=1000
            pm2_restart_count=5,  # increased vs history entry=2
        )
        score = monitor.degradation_score(sample, history)
        assert score >= 0.99, f"Expected score ~1.0 when all signals fire, got {score}"

    def test_score_zero_without_history(self):
        """No history means memory-growth and pm2-delta components cannot fire."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor()
        sample = _make_sample(
            memory_mb=1000.0, ib_reconnects_1h=0, llm_p95_ms=2000.0, pm2_restart_count=0
        )
        score = monitor.degradation_score(sample, [])
        assert score == 0.0, f"Expected 0.0 with empty history, got {score}"

    def test_none_inputs_do_not_raise(self):
        """None values in sample must contribute 0, not raise."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor()
        sample = _make_sample(
            memory_mb=None, ib_reconnects_1h=None, llm_p95_ms=None, pm2_restart_count=None
        )
        score = monitor.degradation_score(sample, [])
        assert score == 0.0


# ── should_restart_preemptively() tests ──────────────────────────────────────


class TestShouldRestart:
    def test_requires_score_above_threshold(self):
        """Score < threshold → False even with no recent restarts."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor(score_threshold=0.7)
        monitor._last_restart_ts = 0.0  # no prior restart

        assert monitor.should_restart_preemptively(0.5, []) is False

    def test_requires_cooldown_elapsed(self):
        """Score > threshold BUT last restart was 5 min ago → False (cooldown active)."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor(score_threshold=0.7, restart_cooldown_seconds=3600)
        monitor._last_restart_ts = time.time() - 300  # 5 min ago, well within 1h cooldown

        assert monitor.should_restart_preemptively(0.9, []) is False

    def test_true_when_score_high_and_cooldown_elapsed(self):
        """Score > threshold AND last restart > 1h ago → True."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor(score_threshold=0.7, restart_cooldown_seconds=3600)
        monitor._last_restart_ts = time.time() - 7200  # 2h ago

        assert monitor.should_restart_preemptively(0.9, []) is True

    def test_first_ever_run_counts_as_cooldown_elapsed(self):
        """_last_restart_ts defaults to 0.0 so first alert can fire."""
        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor(score_threshold=0.7, restart_cooldown_seconds=3600)
        # Default _last_restart_ts is 0.0 (epoch) — far in the past
        assert monitor.should_restart_preemptively(0.9, []) is True


# ── Auto-restart flag gate tests ──────────────────────────────────────────────


class TestAutoRestartFlag:
    @pytest.mark.asyncio
    async def test_auto_restart_requires_explicit_flag(self, monkeypatch):
        """
        Even with high score and ENABLE_PREDICTIVE_MAINTENANCE=1, if
        PREDICTIVE_MAINTENANCE_ALLOW_RESTART is 0 (default), no subprocess
        pm2 call is made.
        """
        monkeypatch.setenv("ENABLE_PREDICTIVE_MAINTENANCE", "1")
        monkeypatch.setenv("PREDICTIVE_MAINTENANCE_ALLOW_RESTART", "0")

        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor(score_threshold=0.1, restart_cooldown_seconds=0)
        monitor._last_restart_ts = 0.0

        with patch("monitoring.predictive_maintenance.subprocess.run") as mock_run:
            # Build a high-scoring sample; patch sample_now to return it deterministically
            high_sample = _make_sample(ib_reconnects_1h=10, pm2_restart_count=0)
            with (
                patch.object(
                    monitor, "sample_now", new_callable=AsyncMock, return_value=high_sample
                ),
                patch.object(monitor, "degradation_score", return_value=0.9),
                patch.object(monitor, "should_restart_preemptively", return_value=True),
                patch.object(monitor, "_send_webhook_alert", new_callable=AsyncMock),
                patch.object(monitor, "_log_sample"),
            ):
                # Run one loop iteration
                async def _one_iter():
                    await asyncio.sleep(0)  # yield
                    sample = await monitor.sample_now()
                    history_list = list(monitor._history)
                    score = monitor.degradation_score(sample, history_list)
                    monitor._history.append(sample)
                    monitor._log_sample(sample, score)
                    from monitoring.predictive_maintenance import is_auto_restart_allowed

                    if score > monitor.score_threshold:
                        await monitor._send_webhook_alert(score, sample)
                        if is_auto_restart_allowed() and monitor.should_restart_preemptively(
                            score, history_list
                        ):
                            monitor._trigger_pm2_restart()

                await _one_iter()

            mock_run.assert_not_called()  # pm2 restart must NOT have been invoked


# ── monitor_loop() error resilience ──────────────────────────────────────────


class TestMonitorLoop:
    @pytest.mark.asyncio
    async def test_monitor_loop_skips_sample_on_error(self, monkeypatch):
        """
        If sample_now() raises, the loop swallows the error and continues.
        We verify by letting it run two iterations: first raises, second succeeds.
        Loop exits because we cancel the task after two iterations.
        """
        monkeypatch.setenv("ENABLE_PREDICTIVE_MAINTENANCE", "1")

        from monitoring.predictive_maintenance import HealthMonitor

        monitor = HealthMonitor()

        call_count = 0
        successes = 0

        async def _flaky_sample():
            nonlocal call_count, successes
            call_count += 1
            if call_count == 1:
                raise RuntimeError("synthetic failure")
            successes += 1
            return _make_sample()

        with (
            patch.object(monitor, "sample_now", side_effect=_flaky_sample),
            patch.object(monitor, "_log_sample"),
            patch.object(monitor, "degradation_score", return_value=0.0),
        ):
            task = asyncio.create_task(monitor.monitor_loop(interval_seconds=0))
            # Give the loop time to run 2 iterations
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # At least one successful sample was taken after the error
        assert successes >= 1, "Loop should continue after sample_now() error"
