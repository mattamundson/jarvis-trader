"""
Tests for engine/agents/task_board.py
Covers thread safety, all status transitions, counters, and edge cases.
"""

import threading
import time

import pytest

from agents.task_board import (
    PipelineTask,
    PipelineTaskBoard,
    StageStatus,
    get_task_board,
    set_task_board_instance,
)

KNOWN_STAGES = [
    "technical_analyst",
    "news_analyst",
    "social_analyst",
    "fundamentalist",
    "bull_researcher",
    "bear_researcher",
    "debate_orchestrator",
    "trader",
    "risk_manager",
    "fund_manager",
]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def board() -> PipelineTaskBoard:
    """Return a fresh PipelineTaskBoard with a started run."""
    b = PipelineTaskBoard()
    b.start_run(run_id="test-run-1", symbol="MES", interval="1h")
    return b


@pytest.fixture
def empty_board() -> PipelineTaskBoard:
    """Return a fresh PipelineTaskBoard with NO run started."""
    return PipelineTaskBoard()


# ── start_run ─────────────────────────────────────────────────────────────────


def test_start_run_initializes_all_10_stages(board):
    status = board.get_status()
    assert len(status["stages"]) == 10
    assert set(status["stages"].keys()) == set(KNOWN_STAGES)


def test_start_run_all_stages_pending(board):
    status = board.get_status()
    for name, stage_info in status["stages"].items():
        assert stage_info["status"] == StageStatus.PENDING.value, f"{name} should be PENDING"


def test_start_run_sets_metadata(board):
    status = board.get_status()
    assert status["run_id"] == "test-run-1"
    assert status["symbol"] == "MES"
    assert status["interval"] == "1h"
    assert status["run_started_at"] is not None


# ── start_stage ───────────────────────────────────────────────────────────────


def test_start_stage_transitions_to_running(board):
    board.start_stage("trader")
    status = board.get_status()
    assert status["stages"]["trader"]["status"] == StageStatus.RUNNING.value


def test_start_stage_sets_started_at(board):
    board.start_stage("risk_manager")
    status = board.get_status()
    assert status["stages"]["risk_manager"]["started_at"] is not None


def test_start_stage_unknown_stage_is_noop(board):
    """Calling start_stage with a nonexistent stage name must not raise."""
    board.start_stage("nonexistent_stage")  # should not raise
    status = board.get_status()
    assert "nonexistent_stage" not in status["stages"]


# ── complete_stage ────────────────────────────────────────────────────────────


def test_complete_stage_transitions_to_done(board):
    board.start_stage("trader")
    board.complete_stage("trader")
    status = board.get_status()
    assert status["stages"]["trader"]["status"] == StageStatus.DONE.value


def test_complete_stage_sets_duration_ms(board):
    board.start_stage("trader")
    time.sleep(0.05)  # ensure measurable duration
    board.complete_stage("trader")
    status = board.get_status()
    assert status["stages"]["trader"]["duration_ms"] is not None
    assert status["stages"]["trader"]["duration_ms"] >= 0


def test_complete_stage_sets_result_summary(board):
    board.start_stage("trader")
    board.complete_stage("trader", result_summary="action=BUY qty=2")
    status = board.get_status()
    assert status["stages"]["trader"]["result_summary"] == "action=BUY qty=2"


def test_complete_stage_without_start_sets_no_duration(board):
    """complete_stage on a stage that was never started — duration_ms stays None."""
    board.complete_stage("fund_manager")
    status = board.get_status()
    assert status["stages"]["fund_manager"]["duration_ms"] is None


# ── error_stage ───────────────────────────────────────────────────────────────


def test_error_stage_transitions_to_error(board):
    board.start_stage("news_analyst")
    board.error_stage("news_analyst", "Connection timeout")
    status = board.get_status()
    assert status["stages"]["news_analyst"]["status"] == StageStatus.ERROR.value


def test_error_stage_sets_error_message(board):
    board.start_stage("news_analyst")
    board.error_stage("news_analyst", "Connection timeout")
    status = board.get_status()
    assert status["stages"]["news_analyst"]["error"] == "Connection timeout"


def test_error_stage_sets_duration_ms_when_started(board):
    board.start_stage("social_analyst")
    time.sleep(0.02)
    board.error_stage("social_analyst", "boom")
    status = board.get_status()
    assert status["stages"]["social_analyst"]["duration_ms"] is not None


# ── skip_stage ────────────────────────────────────────────────────────────────


def test_skip_stage_transitions_to_skipped(board):
    board.skip_stage("fund_manager")
    status = board.get_status()
    assert status["stages"]["fund_manager"]["status"] == StageStatus.SKIPPED.value


# ── overall_status ────────────────────────────────────────────────────────────


def test_overall_status_running_when_any_running(board):
    board.start_stage("technical_analyst")
    status = board.get_status()
    assert status["overall"] == "running"


def test_overall_status_error_when_any_error(board):
    board.start_stage("technical_analyst")
    board.error_stage("technical_analyst", "err")
    status = board.get_status()
    assert status["overall"] == "error"


def test_overall_status_error_takes_priority_over_running(board):
    board.start_stage("technical_analyst")
    board.error_stage("technical_analyst", "err")
    board.start_stage("news_analyst")  # still running
    status = board.get_status()
    assert status["overall"] == "error"


def test_overall_status_complete_when_all_done_or_skipped(board):
    for stage in KNOWN_STAGES[:-1]:  # all but last
        board.start_stage(stage)
        board.complete_stage(stage)
    board.skip_stage(KNOWN_STAGES[-1])
    status = board.get_status()
    assert status["overall"] == "complete"


def test_overall_status_pending_when_all_pending(board):
    # After start_run all stages are PENDING
    status = board.get_status()
    assert status["overall"] == "pending"


def test_overall_status_complete_for_empty_board(empty_board):
    """An empty board (no stages) returns 'complete' — all() of empty is True."""
    status = empty_board.get_status()
    # This is Python's vacuous truth: all() over empty iterable → True.
    # A board with no stages has trivially "nothing left to do".
    assert status["overall"] == "complete"


# ── counters ──────────────────────────────────────────────────────────────────


def test_done_count_is_correct(board):
    for stage in KNOWN_STAGES[:3]:
        board.start_stage(stage)
        board.complete_stage(stage)
    status = board.get_status()
    assert status["done_count"] == 3


def test_error_count_is_correct(board):
    board.start_stage("news_analyst")
    board.error_stage("news_analyst", "oops")
    board.start_stage("social_analyst")
    board.error_stage("social_analyst", "oops2")
    status = board.get_status()
    assert status["error_count"] == 2


def test_total_stages_is_10(board):
    status = board.get_status()
    assert status["total_stages"] == 10


# ── reset ─────────────────────────────────────────────────────────────────────


def test_reset_clears_all_state(board):
    board.start_stage("trader")
    board.reset()
    status = board.get_status()
    assert status["run_id"] is None
    assert status["symbol"] is None
    assert status["interval"] is None
    assert status["run_started_at"] is None
    assert status["stages"] == {}


def test_reset_makes_run_id_none(board):
    board.reset()
    assert board.get_status()["run_id"] is None


def test_reset_resets_done_and_error_counts(board):
    board.start_stage("trader")
    board.complete_stage("trader")
    board.reset()
    status = board.get_status()
    assert status["done_count"] == 0
    assert status["error_count"] == 0


# ── singleton helpers ─────────────────────────────────────────────────────────


def test_get_task_board_returns_same_instance():
    b1 = get_task_board()
    b2 = get_task_board()
    assert b1 is b2


def test_set_task_board_instance_replaces_singleton():
    original = get_task_board()
    new_board = PipelineTaskBoard()
    set_task_board_instance(new_board)
    assert get_task_board() is new_board
    # Restore original for test isolation
    set_task_board_instance(original)


# ── thread safety ─────────────────────────────────────────────────────────────


def test_concurrent_start_stage_does_not_raise(board):
    """Hammering start_stage from multiple threads must not raise."""
    errors: list[Exception] = []

    def worker(stage: str):
        try:
            for _ in range(50):
                board.start_stage(stage)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(s,)) for s in KNOWN_STAGES]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread errors: {errors}"


def test_concurrent_mixed_operations_do_not_raise(board):
    """Mixed operations from many threads must complete without exceptions."""
    errors: list[Exception] = []

    def worker(stage: str, idx: int):
        try:
            board.start_stage(stage)
            if idx % 3 == 0:
                board.complete_stage(stage, result_summary="ok")
            elif idx % 3 == 1:
                board.error_stage(stage, "err")
            else:
                board.skip_stage(stage)
            board.get_status()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=worker, args=(KNOWN_STAGES[i % len(KNOWN_STAGES)], i))
        for i in range(40)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread errors: {errors}"
