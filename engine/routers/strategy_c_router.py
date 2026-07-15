"""
JARVIS TRADER — Strategy C+ Router
=====================================
Exposes the weekly Strategy C+ signal via the jarvis-trader engine API.

Endpoints:
    GET  /v1/strategy_c/signal        — Latest live signal (JSON)
    GET  /v1/strategy_c/status        — Signal health / age check
    GET  /v1/strategy_c/metrics       — Full backtest metrics
    GET  /v1/strategy_c/allocation_history — Weekly allocation CSV data
    POST /v1/strategy_c/refresh       — Re-run live_signal.py (background)

All endpoints require X-API-Key authentication (engine middleware).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/strategy_c", tags=["strategy_c"])

# ── Paths ────────────────────────────────────────────────────────────────────

_OUTPUT_DIR = Path(__file__).parent.parent / "strategy_c" / "output"
_SIGNAL_FILE = _OUTPUT_DIR / "strategy_c_plus_live_signal.json"
_METRICS_FILE = _OUTPUT_DIR / "strategy_c_plus_metrics.json"
_ALLOC_LOG = _OUTPUT_DIR / "allocation_log.csv"
_EQUITY_CURVE = _OUTPUT_DIR / "equity_curve.csv"

# ── Response Models ──────────────────────────────────────────────────────────


class SignalStatus(BaseModel):
    available: bool
    signal_age_hours: Optional[float]
    generated_at: Optional[str]
    effective_date: Optional[str]
    regime: Optional[str]
    combined_scale: Optional[float]
    holdings_count: int
    stale: bool  # True if > 7 days old


class RefreshResponse(BaseModel):
    status: str
    message: str
    triggered_at: str


# ── Helpers ──────────────────────────────────────────────────────────────────


def _load_json(path: Path) -> dict[str, Any]:
    """Load JSON file, return empty dict on any error."""
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {path.name}. Run: python -m engine.strategy_c.live_signal"
        )
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Corrupt signal file: {exc}") from exc


def _signal_age_hours(signal: dict) -> Optional[float]:
    generated_at = signal.get("generated_at", "")
    if not generated_at:
        return None
    try:
        sig_time = datetime.fromisoformat(generated_at)
        return (datetime.now() - sig_time).total_seconds() / 3600
    except Exception:
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/signal", summary="Latest Strategy C+ live signal")
async def get_signal() -> dict[str, Any]:
    """
    Return the latest Strategy C+ weekly signal.

    Generated every Friday at 4:05pm CT by the scheduled cron job.
    Includes full layer breakdown (momentum, vol targeting, VIX, macro).
    Execute Monday MOO per T+1 lag rule.
    """
    signal = _load_json(_SIGNAL_FILE)
    age = _signal_age_hours(signal)

    # Add derived fields for convenience
    signal["_meta"] = {
        "signal_age_hours": round(age, 1) if age is not None else None,
        "stale": age is not None and age > 168,  # > 7 days
        "execution_timing": "MOO Monday (T+1 lag from Friday signal)",
        "account": "DUP662235",
        "mode": "PAPER",
    }
    return signal


@router.get("/status", summary="Signal health check", response_model=SignalStatus)
async def get_status() -> SignalStatus:
    """
    Quick health check — signal age, regime, and staleness flag.
    Use this to verify the Friday cron ran successfully.
    """
    if not _SIGNAL_FILE.exists():
        return SignalStatus(
            available=False,
            signal_age_hours=None,
            generated_at=None,
            effective_date=None,
            regime=None,
            combined_scale=None,
            holdings_count=0,
            stale=True,
        )

    signal = _load_json(_SIGNAL_FILE)
    age = _signal_age_hours(signal)
    layers = signal.get("layers", {})
    regime = layers.get("momentum_signal", {}).get("risk_regime")
    holdings = signal.get("holdings", {})

    return SignalStatus(
        available=True,
        signal_age_hours=round(age, 1) if age is not None else None,
        generated_at=signal.get("generated_at"),
        effective_date=signal.get("effective_date"),
        regime=regime,
        combined_scale=signal.get("combined_scale"),
        holdings_count=len([k for k, v in holdings.items() if v > 0.005]),
        stale=age is not None and age > 168,
    )


@router.get("/metrics", summary="Full backtest metrics for Strategy C+")
async def get_metrics() -> dict[str, Any]:
    """
    Full Strategy C+ backtest performance metrics, mapped to the dashboard contract.

    The on-disk metrics file stores percent fields already scaled ×100
    (``cagr`` / ``ann_vol`` / ``max_dd_close_pct`` / ``win_rate_pct``) under the
    keys ``full`` / ``is_period`` / ``oos_period``. The dashboard's ``fmtPct``
    multiplies by 100, so this endpoint emits FRACTIONS (÷100) under the frontend
    key names (``full_period`` / ``in_sample`` / ``out_of_sample``) with the
    renamed sub-fields (``max_dd_close_pct``→``max_drawdown``, ``ann_vol``→
    ``volatility``, ``win_rate_pct``→``win_rate``). Without this mapping the UI
    both mislabels keys and double-scales percentages (e.g. CAGR 17.09 → 1709%).
    ``final_multiple_x`` (equity growth multiple, e.g. 4.12x) is forwarded
    as-is alongside the raw dollar ``final_equity`` — the dashboard displays
    the multiple, not the dollar figure, to avoid a nonsensical "$412306.24x".
    404s cleanly (via _load_json) when no backtest has been run yet.
    """
    raw = _load_json(_METRICS_FILE)  # 404s cleanly if no backtest has run

    def _pct(v: Any) -> Optional[float]:
        """Percent (0-100 from disk) -> fraction (0-1) for the frontend's fmtPct."""
        return round(float(v) / 100.0, 6) if isinstance(v, (int, float)) else None

    def _num(v: Any) -> Optional[float]:
        return float(v) if isinstance(v, (int, float)) else None

    def _core(block: dict) -> dict:
        block = block or {}
        return {
            "cagr": _pct(block.get("cagr")),
            "sharpe": _num(block.get("sharpe")),
            "sortino": _num(block.get("sortino")),
            "calmar": _num(block.get("calmar")),
            "max_drawdown": _pct(block.get("max_dd_close_pct")),
            "volatility": _pct(block.get("ann_vol")),
            "win_rate": _pct(block.get("win_rate_pct")),
            "final_equity": _num(block.get("final_equity")),
            "final_multiple_x": _num(block.get("final_multiple_x")),
            "n_weeks": block.get("n_weeks"),
        }

    is_period = raw.get("is_period", {}) or {}
    oos_period = raw.get("oos_period", {}) or {}
    retention = raw.get("oos_retention", {}) or {}

    return {
        "full_period": _core(raw.get("full", {})),
        "in_sample": {
            "cagr": _pct(is_period.get("cagr")),
            "sharpe": _num(is_period.get("sharpe")),
            "max_drawdown": _pct(is_period.get("max_dd_close_pct")),
            "start": None,
            "end": None,
        },
        "out_of_sample": {
            "cagr": _pct(oos_period.get("cagr")),
            "sharpe": _num(oos_period.get("sharpe")),
            "max_drawdown": _pct(oos_period.get("max_dd_close_pct")),
            "sharpe_retention": _pct(retention.get("sharpe_retention_pct")),
            "cagr_retention": _pct(retention.get("cagr_retention_pct")),
            "start": None,
            "end": None,
        },
        "deflated_sharpe": raw.get("deflated_sharpe"),
        "vol_stats": raw.get("vol_stats"),
    }


@router.get("/allocation_history", summary="Weekly allocation history (JSON)")
async def get_allocation_history(limit: int = 52) -> dict[str, Any]:
    """
    Return the last N weeks of allocation history.

    Parameters
    ----------
    limit : int
        Number of weeks to return (default 52 = 1 year). Max 468.
    """
    if not _ALLOC_LOG.exists():
        raise HTTPException(status_code=404, detail="allocation_log.csv not found")

    import csv
    rows = []
    with open(_ALLOC_LOG, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # Return last N weeks
    limit = min(limit, 468)
    recent = rows[-limit:] if len(rows) > limit else rows

    return {
        "total_weeks": len(rows),
        "returned_weeks": len(recent),
        "allocations": recent,
    }


@router.get("/equity_curve", summary="Weekly equity curve data")
async def get_equity_curve(limit: int = 260) -> dict[str, Any]:
    """
    Return the last N weeks of equity curve data.

    Parameters
    ----------
    limit : int
        Weeks to return (default 260 = 5 years).
    """
    if not _EQUITY_CURVE.exists():
        raise HTTPException(status_code=404, detail="equity_curve.csv not found")

    import csv
    rows = []
    with open(_EQUITY_CURVE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    limit = min(limit, 468)
    recent = rows[-limit:] if len(rows) > limit else rows

    return {
        "total_weeks": len(rows),
        "returned_weeks": len(recent),
        "curve": recent,
    }


@router.post("/refresh", summary="Re-generate live signal in background", response_model=RefreshResponse)
async def refresh_signal(background_tasks: BackgroundTasks) -> RefreshResponse:
    """
    Trigger a fresh live signal run in the background.

    This is the same operation the Friday cron performs.
    Useful for manual refreshes outside the weekly schedule.
    Results available at /v1/strategy_c/signal within ~30 seconds.
    """
    def _run_signal():
        try:
            # Use the engine's .venv Python to run the module
            venv_python = Path(__file__).parent.parent / ".venv" / "Scripts" / "python.exe"
            if not venv_python.exists():
                # Linux/Mac fallback
                venv_python = Path(__file__).parent.parent / ".venv" / "bin" / "python"
            if not venv_python.exists():
                venv_python = sys.executable

            engine_root = Path(__file__).parent.parent
            result = subprocess.run(
                [str(venv_python), "-m", "engine.strategy_c.live_signal"],
                cwd=str(engine_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.error(
                    "live_signal refresh failed: %s", result.stderr[-500:]
                )
            else:
                logger.info("live_signal refresh completed successfully")
        except Exception as exc:
            logger.error("live_signal refresh error: %s", exc)

    background_tasks.add_task(_run_signal)

    return RefreshResponse(
        status="triggered",
        message="Signal refresh running in background. Check /v1/strategy_c/status in ~30 seconds.",
        triggered_at=datetime.now().isoformat(),
    )
