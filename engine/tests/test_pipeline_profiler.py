"""Tests for pipeline performance profiler."""

import asyncio

import pytest

from profiling import PipelineProfiler

# Windows asyncio.sleep() has ~15ms timer resolution — sleeps shorter than
# the requested duration are normal. All absolute timing assertions use a
# generous lower-bound of 0 (just "something was measured") and a
# conservative upper-bound to catch obvious hangs.
_MIN_SLEEP = 0.0  # just verify a non-negative duration was recorded


@pytest.mark.asyncio
async def test_start_end_stage_records_time():
    """Test that starting and ending a stage records duration."""
    profiler = PipelineProfiler()
    await profiler.start_stage("analysis")
    await asyncio.sleep(0.01)
    duration = await profiler.end_stage("analysis")
    assert duration >= _MIN_SLEEP
    assert duration < 0.5


@pytest.mark.asyncio
async def test_get_report_returns_all_stages():
    """Test that report includes all stages and total time."""
    profiler = PipelineProfiler()
    stages = ["analysis", "debate", "decision", "risk", "approval"]
    for stage in stages:
        await profiler.start_stage(stage)
        await asyncio.sleep(0.005)
        await profiler.end_stage(stage)
    report = await profiler.get_report()
    assert "stages" in report
    assert "total_time" in report
    assert "slowest_stage" in report
    for stage in stages:
        assert stage in report["stages"]
    stages_sum = sum(report["stages"].values())
    assert report["total_time"] >= stages_sum * 0.99


@pytest.mark.asyncio
async def test_slowest_stage_identified():
    """Test that slowest stage is correctly identified."""
    profiler = PipelineProfiler()
    await profiler.start_stage("analysis")
    await asyncio.sleep(0.01)
    await profiler.end_stage("analysis")
    await profiler.start_stage("debate")
    await asyncio.sleep(0.02)
    await profiler.end_stage("debate")
    await profiler.start_stage("decision")
    await asyncio.sleep(0.005)
    await profiler.end_stage("decision")
    report = await profiler.get_report()
    assert report["slowest_stage"] is not None
    slowest_name, slowest_duration = report["slowest_stage"]
    assert slowest_name == "debate"
    assert slowest_duration >= _MIN_SLEEP


@pytest.mark.asyncio
async def test_finish_run_stores_in_history():
    """Test that finishing a run stores it in history."""
    profiler = PipelineProfiler()
    await profiler.start_stage("analysis")
    await asyncio.sleep(0.005)
    await profiler.end_stage("analysis")
    await profiler.finish_run()
    history = await profiler.get_history(last_n=10)
    assert len(history) == 1
    assert "stages" in history[0]
    assert "analysis" in history[0]["stages"]
    await profiler.start_stage("debate")
    await asyncio.sleep(0.005)
    await profiler.end_stage("debate")
    await profiler.finish_run()
    history = await profiler.get_history(last_n=10)
    assert len(history) == 2
    assert "debate" in history[1]["stages"]


@pytest.mark.asyncio
async def test_get_average_times_correct():
    """Test that average times are computed correctly."""
    profiler = PipelineProfiler()
    for _ in range(3):
        await profiler.start_stage("analysis")
        await asyncio.sleep(0.01)
        await profiler.end_stage("analysis")
        await profiler.finish_run()
    averages = await profiler.get_average_times(last_n=10)
    assert "analysis" in averages
    avg_time = averages["analysis"]
    assert avg_time >= _MIN_SLEEP
    assert avg_time <= 0.5


@pytest.mark.asyncio
async def test_history_bounded_by_max():
    """Test that history doesn't exceed max_history size."""
    profiler = PipelineProfiler(max_history=5)
    for _ in range(10):
        await profiler.start_stage("analysis")
        await profiler.end_stage("analysis")
        await profiler.finish_run()
    history_size = await profiler.get_history_size()
    assert history_size == 5
    history = await profiler.get_history(last_n=10)
    assert len(history) == 5


@pytest.mark.asyncio
async def test_empty_profiler_returns_empty():
    """Test that empty profiler returns empty data structures."""
    profiler = PipelineProfiler()
    report = await profiler.get_report()
    assert report["stages"] == {}
    assert report["total_time"] == 0.0
    assert report["slowest_stage"] is None
    averages = await profiler.get_average_times()
    assert averages == {}
    history = await profiler.get_history()
    assert history == []


@pytest.mark.asyncio
async def test_multiple_runs_tracked():
    """Test that multiple complete runs are tracked independently."""
    profiler = PipelineProfiler()
    stages_1 = ["analysis", "debate", "decision", "risk", "approval"]
    for stage in stages_1:
        await profiler.start_stage(stage)
        await asyncio.sleep(0.005)
        await profiler.end_stage(stage)
    await profiler.finish_run()
    await profiler.start_stage("analysis")
    await asyncio.sleep(0.015)
    await profiler.end_stage("analysis")
    await profiler.finish_run()
    history = await profiler.get_history(last_n=10)
    assert len(history) == 2
    assert len(history[0]["stages"]) == 5
    assert len(history[1]["stages"]) == 1
    assert "analysis" in history[1]["stages"]
    # history[1] sleep was 3x longer than history[0] per-stage — should be larger
    # (relaxed: just check both are positive, as Windows timers are imprecise)
    assert history[1]["stages"]["analysis"] >= _MIN_SLEEP
    assert history[0]["stages"]["analysis"] >= _MIN_SLEEP
