"""Pipeline profiling router — exposes profiler metrics for performance analysis."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/pipeline/profiling", tags=["profiling"])

# Global reference to the profiler instance (injected from main.py)
_profiler_instance = None


def set_profiler_instance(profiler):
    """Set the global profiler instance (called from main.py)."""
    global _profiler_instance
    _profiler_instance = profiler


@router.get("/summary")
async def get_profiling_summary():
    """Get current pipeline run performance summary."""
    if _profiler_instance is None:
        raise HTTPException(status_code=503, detail="Profiler not available")

    report = await _profiler_instance.get_report()
    return {
        "status": "ok",
        "current_run": report,
    }


@router.get("/averages")
async def get_profiling_averages(last_n: int = 100):
    """Get rolling average execution times per stage."""
    if _profiler_instance is None:
        raise HTTPException(status_code=503, detail="Profiler not available")

    averages = await _profiler_instance.get_average_times(last_n=last_n)
    return {
        "status": "ok",
        "rolling_averages": averages,
        "period": f"last {last_n} runs",
    }


@router.get("/history")
async def get_profiling_history(last_n: int = 10):
    """Get recent pipeline run reports."""
    if _profiler_instance is None:
        raise HTTPException(status_code=503, detail="Profiler not available")

    history = await _profiler_instance.get_history(last_n=last_n)
    history_size = await _profiler_instance.get_history_size()
    max_history = await _profiler_instance.get_max_history()

    return {
        "status": "ok",
        "history": history,
        "retrieved_count": len(history),
        "total_stored": history_size,
        "max_capacity": max_history,
    }


@router.get("/stats")
async def get_profiling_stats():
    """Get profiler statistics and capacity."""
    if _profiler_instance is None:
        raise HTTPException(status_code=503, detail="Profiler not available")

    history_size = await _profiler_instance.get_history_size()
    max_history = await _profiler_instance.get_max_history()
    current_report = await _profiler_instance.get_report()
    averages = await _profiler_instance.get_average_times(last_n=100)

    return {
        "status": "ok",
        "profiler_enabled": True,
        "max_history": max_history,
        "stored_runs": history_size,
        "utilization_pct": round((history_size / max_history) * 100, 1),
        "current_run": current_report,
        "stage_averages": averages,
    }
