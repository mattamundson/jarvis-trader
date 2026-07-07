"""
Pipeline task board — tracks stage execution for dashboard visibility.
In-memory only; resets on each pipeline run.
"""

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class PipelineTask:
    stage: str  # e.g. "technical_analyst"
    status: StageStatus = StageStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    result_summary: Optional[str] = None  # short one-line summary of result


class PipelineTaskBoard:
    """Thread-safe task board for one pipeline run."""

    def __init__(self):
        self._tasks: dict[str, PipelineTask] = {}
        self._lock = threading.Lock()
        self._run_id: Optional[str] = None
        self._symbol: Optional[str] = None
        self._interval: Optional[str] = None
        self._run_started_at: Optional[str] = None

    def start_run(self, run_id: str, symbol: str, interval: str):
        """Initialize the board for a new pipeline run."""
        with self._lock:
            self._run_id = run_id
            self._symbol = symbol
            self._interval = interval
            self._run_started_at = datetime.utcnow().isoformat()
            # Pre-populate all 10 known stages as PENDING
            stages = [
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
            self._tasks = {s: PipelineTask(stage=s) for s in stages}

    def start_stage(self, stage: str):
        with self._lock:
            if stage in self._tasks:
                self._tasks[stage].status = StageStatus.RUNNING
                self._tasks[stage].started_at = datetime.utcnow().isoformat()

    def complete_stage(self, stage: str, result_summary: Optional[str] = None):
        with self._lock:
            if stage in self._tasks:
                t = self._tasks[stage]
                t.status = StageStatus.DONE
                t.completed_at = datetime.utcnow().isoformat()
                t.result_summary = result_summary
                if t.started_at:
                    start = datetime.fromisoformat(t.started_at)
                    t.duration_ms = (datetime.utcnow() - start).total_seconds() * 1000

    def error_stage(self, stage: str, error: str):
        with self._lock:
            if stage in self._tasks:
                t = self._tasks[stage]
                t.status = StageStatus.ERROR
                t.completed_at = datetime.utcnow().isoformat()
                t.error = error
                if t.started_at:
                    start = datetime.fromisoformat(t.started_at)
                    t.duration_ms = (datetime.utcnow() - start).total_seconds() * 1000

    def skip_stage(self, stage: str):
        with self._lock:
            if stage in self._tasks:
                self._tasks[stage].status = StageStatus.SKIPPED

    def get_status(self) -> dict:
        with self._lock:
            return {
                "run_id": self._run_id,
                "symbol": self._symbol,
                "interval": self._interval,
                "run_started_at": self._run_started_at,
                "stages": {
                    name: {
                        "stage": t.stage,
                        "status": t.status.value,
                        "started_at": t.started_at,
                        "completed_at": t.completed_at,
                        "duration_ms": t.duration_ms,
                        "result_summary": t.result_summary,
                        "error": t.error,
                    }
                    for name, t in self._tasks.items()
                },
                "overall": self._overall_status(),
                "total_stages": len(self._tasks),
                "done_count": sum(1 for t in self._tasks.values() if t.status == StageStatus.DONE),
                "error_count": sum(
                    1 for t in self._tasks.values() if t.status == StageStatus.ERROR
                ),
            }

    def _overall_status(self) -> str:
        statuses = {t.status for t in self._tasks.values()}
        if StageStatus.ERROR in statuses:
            return "error"
        if StageStatus.RUNNING in statuses:
            return "running"
        if all(t.status in (StageStatus.DONE, StageStatus.SKIPPED) for t in self._tasks.values()):
            return "complete"
        return "pending"

    def reset(self):
        with self._lock:
            self._tasks = {}
            self._run_id = None
            self._symbol = None
            self._interval = None
            self._run_started_at = None


# Module-level singleton
_task_board: Optional[PipelineTaskBoard] = None


def get_task_board() -> PipelineTaskBoard:
    global _task_board
    if _task_board is None:
        _task_board = PipelineTaskBoard()
    return _task_board


def set_task_board_instance(board: PipelineTaskBoard):
    global _task_board
    _task_board = board
