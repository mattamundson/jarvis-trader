"""Pipeline performance profiler for multi-stage trading analysis."""

import asyncio
import logging
import time
from collections import deque

logger = logging.getLogger(__name__)

__all__ = ["PipelineProfiler"]


class PipelineProfiler:
    """
    Tracks per-stage execution times for the 5-stage trading pipeline.
    Thread-safe with asyncio.Lock. Stores bounded history (default 100 runs).
    """

    def __init__(self, max_history: int = 100):
        """Args: max_history: Maximum number of run reports to store."""
        self.max_history = max_history
        self._current_run = {}
        self._history = deque(maxlen=max_history)
        self._lock = None

    def _get_lock(self) -> asyncio.Lock:
        """Get or create asyncio lock (lazy init for event loop)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def start_stage(self, stage_name: str) -> None:
        """Record start time for a pipeline stage."""
        async with self._get_lock():
            if stage_name not in self._current_run:
                self._current_run[stage_name] = {}
            self._current_run[stage_name]["start"] = time.perf_counter()

    async def end_stage(self, stage_name: str) -> float:
        """Record end time and return duration. Returns 0.0 if not started."""
        async with self._get_lock():
            if stage_name not in self._current_run:
                return 0.0
            end_time = time.perf_counter()
            start_time = self._current_run[stage_name].get("start")
            if start_time is None:
                return 0.0
            duration = end_time - start_time
            self._current_run[stage_name]["duration"] = duration
            return duration

    def _build_report(self) -> dict:
        """Build report without lock (caller must hold lock)."""
        stages, total_time, slowest = {}, 0.0, None
        max_duration = 0.0
        for stage_name, data in self._current_run.items():
            duration = data.get("duration", 0.0)
            stages[stage_name] = round(duration, 4)
            total_time += duration
            if duration > max_duration:
                max_duration = duration
                slowest = (stage_name, duration)
        return {
            "stages": stages,
            "total_time": round(total_time, 4),
            "slowest_stage": slowest,
        }

    async def get_report(self) -> dict:
        """Get performance report for current run."""
        async with self._get_lock():
            return self._build_report()

    async def finish_run(self) -> None:
        """Store current run in history and reset for next run."""
        async with self._get_lock():
            self._history.append(self._build_report())
            self._current_run = {}

    async def get_average_times(self, last_n: int = 100) -> dict:
        """Get rolling average execution times per stage."""
        async with self._get_lock():
            if not self._history:
                return {}
            runs = list(self._history)[-last_n:]
            stage_totals, stage_counts = {}, {}
            for run_report in runs:
                for stage_name, duration in run_report.get("stages", {}).items():
                    stage_totals[stage_name] = stage_totals.get(stage_name, 0.0) + duration
                    stage_counts[stage_name] = stage_counts.get(stage_name, 0) + 1
            return {
                stage: round(stage_totals[stage] / stage_counts[stage], 4) for stage in stage_totals
            }

    async def get_history(self, last_n: int = 10) -> list:
        """Get recent run reports (most recent last)."""
        async with self._get_lock():
            return list(self._history)[-last_n:]

    async def get_max_history(self) -> int:
        """Get maximum history size."""
        return self.max_history

    async def get_history_size(self) -> int:
        """Get current number of stored runs."""
        async with self._get_lock():
            return len(self._history)
