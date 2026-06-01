"""
Options Backtester API Router
==============================
Wires the existing `engine/backtest/options_backtester.py` into the engine
as a callable HTTP endpoint with persistent JSON output.

Scope decision (2026-05-20)
---------------------------
Initial usable end-to-end path: **SPY options** (most chain data, no Tier-3
implications, no live-trading hooks). MES / MNQ / MCL options-equivalents
are deferred until a historical chain provider is wired for futures
(`engine/options/chain_fetcher.py` is currently live-only).

This router is OBSERVATIONAL — it never touches:
* `engine/risk/` (safety layer)
* `engine/agents/trader.py` (sizing)
* `engine/execution/kill_switch.py`
* `engine/.env` or `engine/config.py`

Endpoints
---------
* POST /backtest/options/run            — kick off a backtest, returns job_id
* GET  /backtest/options/jobs/{job_id}  — poll job status
* GET  /backtest/options/results        — paginate prior result files

Persistence layout
------------------
engine/data/options_backtests/
├── _jobs.json                                  (durable job registry)
└── <YYYY-MM-DD>/
    └── <symbol>_<strategy>_<job_id_short>.json (per-run result)
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest/options", tags=["backtest-options"])

# ── Persistence paths ────────────────────────────────────────────────────────
# Override-able for tests via `set_output_dir()`. Default resolves to
# engine/data/options_backtests at runtime.
_DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "options_backtests"
_output_dir: Path = _DEFAULT_OUTPUT_DIR
_jobs_file: Path = _output_dir / "_jobs.json"

# In-memory job registry. Capped at MAX_JOBS_IN_MEMORY — the on-disk
# `_jobs.json` is the durable store.
MAX_JOBS_IN_MEMORY = 50
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()

# Hook used by tests to substitute a mocked runner.
_runner_override = None


# ── Configuration helpers ────────────────────────────────────────────────────


def set_output_dir(path: Path) -> None:
    """Override the output directory (used by tests)."""
    global _output_dir, _jobs_file
    _output_dir = Path(path)
    _jobs_file = _output_dir / "_jobs.json"
    _output_dir.mkdir(parents=True, exist_ok=True)


def set_runner_override(runner) -> None:
    """Inject a callable to replace the default backtest runner (test hook)."""
    global _runner_override
    _runner_override = runner


def reset_state() -> None:
    """Reset in-memory state. Used by tests to ensure isolation."""
    global _jobs, _runner_override
    with _jobs_lock:
        _jobs = {}
    _runner_override = None


# ── Schemas ──────────────────────────────────────────────────────────────────


class RunBacktestRequest(BaseModel):
    symbol: str = Field(..., description="Underlying symbol (e.g. SPY)")
    strategy: str = Field(
        ...,
        description="Strategy identifier — currently 'vertical_spread' is the only wired strategy.",
    )
    start_date: str = Field(..., description="ISO date (YYYY-MM-DD)")
    end_date: str = Field(..., description="ISO date (YYYY-MM-DD)")
    params: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Strategy params. Supported keys for vertical_spread: target_dte, "
            "target_delta, width_strikes, contracts_per_signal, slippage_bps."
        ),
    )


class JobResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    symbol: str
    strategy: str
    start_date: str
    end_date: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result_path: Optional[str] = None
    error_message: Optional[str] = None


class ResultListItem(BaseModel):
    filename: str
    date: str
    symbol: str
    strategy: str
    path: str


class ResultListResponse(BaseModel):
    items: list[ResultListItem]
    total: int
    limit: int
    offset: int


# ── Job persistence ──────────────────────────────────────────────────────────


def _ensure_output_dir() -> None:
    _output_dir.mkdir(parents=True, exist_ok=True)


def _persist_jobs() -> None:
    """Write the in-memory registry to disk."""
    _ensure_output_dir()
    # Snapshot under lock, write outside lock to keep the critical section short.
    with _jobs_lock:
        snapshot = list(_jobs.values())
    # Keep only the MAX_JOBS_IN_MEMORY most-recent jobs (by created_at).
    snapshot.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    snapshot = snapshot[:MAX_JOBS_IN_MEMORY]
    tmp = _jobs_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    tmp.replace(_jobs_file)


def load_jobs_from_disk() -> None:
    """Read the on-disk job registry into memory. Idempotent."""
    global _jobs
    if not _jobs_file.exists():
        return
    try:
        data = json.loads(_jobs_file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            logger.warning("[options-backtest] _jobs.json malformed (not a list); ignoring")
            return
        with _jobs_lock:
            _jobs = {j["job_id"]: j for j in data if isinstance(j, dict) and "job_id" in j}
        logger.info("[options-backtest] Loaded %d jobs from disk", len(_jobs))
    except Exception as exc:
        logger.warning("[options-backtest] Failed to load _jobs.json: %s", exc)


def _update_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        if job_id not in _jobs:
            return
        _jobs[job_id].update(fields)
    _persist_jobs()


# ── Default runner (wraps OptionsBacktester) ─────────────────────────────────


def _default_runner(job: dict[str, Any]) -> dict[str, Any]:
    """
    Default backtest runner. Wraps OptionsBacktester without modifying it.

    This is intentionally minimal: it constructs the backtester with sane
    defaults from `params`, but does NOT provide a historical ChainProvider
    or SignalSource. Without real data adapters, runs against SPY return a
    zero-trade result and surface the gap in `n_signals_consumed`.

    A follow-up PR will wire `engine/options/chain_fetcher.py` historical
    mode + a SignalSource adapter so this returns real trades.
    """
    from backtest.options_backtester import OptionsBacktester  # local import — heavy

    params = job.get("params") or {}

    class _EmptyChainProvider:
        def get_chain(self, symbol, as_of, target_dte):
            return None

    class _EmptySignalSource:
        def signals(self):
            return []

    backtester = OptionsBacktester(
        chain_provider=_EmptyChainProvider(),
        signal_source=_EmptySignalSource(),
        target_dte=int(params.get("target_dte", 30)),
        target_delta=float(params.get("target_delta", 0.30)),
        width_strikes=int(params.get("width_strikes", 1)),
        contracts_per_signal=int(params.get("contracts_per_signal", 1)),
    )
    result = backtester.run(underlying_prices_at_expiry={})
    summary = result.to_dict()

    return {
        "summary": summary,
        "metrics": {
            "profit_factor": summary.get("profit_factor"),
            "win_rate": summary.get("win_rate"),
            "total_pnl": summary.get("total_pnl"),
            "n_trades": summary.get("n_trades"),
        },
        "trades": [],
        "notes": (
            "Default runner uses empty adapters — wire a historical ChainProvider "
            "and SignalSource to produce real trades."
        ),
    }


def _run_backtest_job(job_id: str) -> None:
    """Background-task body. Runs the configured runner, writes result file."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        logger.warning("[options-backtest] job %s vanished before run", job_id)
        return

    _update_job(
        job_id,
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        runner = _runner_override or _default_runner
        runner_output = runner(job)

        today = date.today().isoformat()
        date_dir = _output_dir / today
        date_dir.mkdir(parents=True, exist_ok=True)

        short_id = job_id[:8]
        fname = f"{job['symbol']}_{job['strategy']}_{short_id}.json"
        out_path = date_dir / fname

        payload = {
            "job_id": job_id,
            "input": {
                "symbol": job["symbol"],
                "strategy": job["strategy"],
                "start_date": job["start_date"],
                "end_date": job["end_date"],
                "params": job.get("params") or {},
            },
            "summary": runner_output.get("summary", {}),
            "metrics": runner_output.get("metrics", {}),
            "trades": runner_output.get("trades", []),
            "notes": runner_output.get("notes"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

        _update_job(
            job_id,
            status="done",
            finished_at=datetime.now(timezone.utc).isoformat(),
            result_path=str(out_path),
        )
        logger.info("[options-backtest] job %s done → %s", job_id, out_path.name)
    except Exception as exc:
        logger.exception("[options-backtest] job %s failed", job_id)
        _update_job(
            job_id,
            status="error",
            finished_at=datetime.now(timezone.utc).isoformat(),
            error_message=str(exc),
        )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "/run",
    response_model=JobResponse,
    description="Queue an options backtest. Returns immediately with a job_id.",
)
async def run_options_backtest(
    request: RunBacktestRequest,
    background_tasks: BackgroundTasks,
) -> JobResponse:
    # Light validation — defer deep param checks to the runner.
    try:
        datetime.strptime(request.start_date, "%Y-%m-%d")
        datetime.strptime(request.end_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(400, f"Invalid date format (expected YYYY-MM-DD): {exc}") from exc

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    job = {
        "job_id": job_id,
        "status": "queued",
        "symbol": request.symbol,
        "strategy": request.strategy,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "params": request.params or {},
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "result_path": None,
        "error_message": None,
    }
    with _jobs_lock:
        _jobs[job_id] = job
    _persist_jobs()

    background_tasks.add_task(_run_backtest_job, job_id)
    return JobResponse(job_id=job_id, status="queued")


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    description="Return status for one options backtest job.",
)
async def get_options_backtest_job(job_id: str) -> JobStatusResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"job_id not found: {job_id}")
    return JobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        symbol=job["symbol"],
        strategy=job["strategy"],
        start_date=job["start_date"],
        end_date=job["end_date"],
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
        result_path=job.get("result_path"),
        error_message=job.get("error_message"),
    )


@router.get(
    "/results",
    response_model=ResultListResponse,
    description="List persisted options backtest result files, newest first.",
)
async def list_options_backtest_results(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ResultListResponse:
    _ensure_output_dir()
    all_files: list[tuple[Path, str]] = []
    # Walk one level deep: _output_dir/<YYYY-MM-DD>/*.json
    if _output_dir.exists():
        for date_dir in sorted(
            (p for p in _output_dir.iterdir() if p.is_dir()),
            reverse=True,
        ):
            for f in sorted(date_dir.glob("*.json"), reverse=True):
                all_files.append((f, date_dir.name))

    total = len(all_files)
    window = all_files[offset : offset + limit]

    items: list[ResultListItem] = []
    for path, date_str in window:
        # filename format: <symbol>_<strategy>_<short_id>.json
        stem = path.stem
        parts = stem.split("_")
        symbol = parts[0] if parts else "?"
        strategy = parts[1] if len(parts) > 1 else "?"
        items.append(
            ResultListItem(
                filename=path.name,
                date=date_str,
                symbol=symbol,
                strategy=strategy,
                path=str(path),
            )
        )
    return ResultListResponse(items=items, total=total, limit=limit, offset=offset)


# ── Startup hook ─────────────────────────────────────────────────────────────


def init_router() -> None:
    """Idempotent init — call from main.py lifespan or on first import."""
    _ensure_output_dir()
    load_jobs_from_disk()


# Auto-init at import time so the router is functional even without an
# explicit lifespan hook (tests rely on this).
init_router()
