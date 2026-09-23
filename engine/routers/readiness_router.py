"""
Phase 3 programmatic readiness router — GET /readiness/phase3
=============================================================
Returns a structured GO / WAIT / NO-GO report based on the 10 codified
criteria in engine/readiness/phase3_criteria.py.

Also exposes GET /readiness/gate-v2-calibration for the Bayesian
threshold calibrator (read-only recommendations; never auto-applied).

This router is INFORMATIONAL ONLY.  It never reads or writes
LIVE_TRADING_ENABLED, safety_layer.py, or engine/.env.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from middleware.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/readiness", tags=["readiness", "phase3"])


<<<<<<< HEAD
=======
def _status_rank(status: str) -> int:
    return {"pass": 0, "warn": 1, "fail": 2}.get(status, 2)


def _overall_status(checks: list[dict]) -> str:
    if any(check["required"] and check["status"] == "fail" for check in checks):
        return "blocked"
    if any(_status_rank(check["status"]) > 0 for check in checks):
        return "degraded"
    return "ready"


def _check(name: str, passed: bool, detail: str, *, required: bool = True) -> dict:
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "detail": detail,
        "required": required,
    }


def _warn(name: str, passed: bool, detail: str) -> dict:
    return {
        "name": name,
        "status": "pass" if passed else "warn",
        "detail": detail,
        "required": False,
    }


def _paper_instrument_state() -> dict:
    from backtest.paper_config import ACTIVE_INSTRUMENTS, PAPER_CONFIGS
    from backtest.signals import DEFAULT_BRIEFING_SYMBOLS, DO_NOT_TRADE_SYMBOLS

    active_symbols = sorted({str(sym).upper() for sym in ACTIVE_INSTRUMENTS})
    halted_symbols = sorted({str(sym).upper() for sym in DO_NOT_TRADE_SYMBOLS})
    enabled_config_symbols = sorted(
        str(sym).upper() for sym, cfg in PAPER_CONFIGS.items() if cfg.get("enabled", False)
    )
    default_briefing_symbols = sorted({str(sym).upper() for sym in DEFAULT_BRIEFING_SYMBOLS})
    return {
        "active_symbols": active_symbols,
        "halted_symbols": halted_symbols,
        "enabled_config_symbols": enabled_config_symbols,
        "default_briefing_symbols": default_briefing_symbols,
    }


def build_paper_pipeline_readiness(health: dict, instruments: dict | None = None) -> dict:
    """Reduce live /health truth into paper-pipeline readiness.

    This is a read-only contract: it reshapes existing probes and static paper
    config; it never reconnects brokers, mutates safety settings, or probes the
    live IB port.
    """
    instrument_state = instruments or _paper_instrument_state()
    active_symbols = instrument_state["active_symbols"]
    halted_symbols = instrument_state["halted_symbols"]
    enabled_config_symbols = instrument_state["enabled_config_symbols"]
    default_briefing_symbols = instrument_state["default_briefing_symbols"]
    halted_active = sorted(set(active_symbols) & set(halted_symbols))
    stale_symbols = sorted(health.get("market_data_stale_symbols") or [])
    pending = health.get("pending_approvals") or {}

    paper_mode = bool(health.get("paper_mode"))
    live_trading = bool(health.get("live_trading"))
    ib_data_connected = bool(health.get("ibkr_data_connected"))
    tv_mcp_healthy = bool(health.get("tradingview_mcp_healthy"))
    source_ready = ib_data_connected or tv_mcp_healthy
    source_name = (
        "ibkr"
        if ib_data_connected
        else "tradingview_mcp"
        if tv_mcp_healthy
        else "none"
    )

    checks = [
        _check(
            "paper_mode_only",
            paper_mode and not live_trading,
            f"paper_mode={paper_mode} live_trading={live_trading}",
        ),
        _check(
            "kill_switch_inactive",
            not bool(health.get("kill_switch_active", True)),
            f"kill_switch_active={health.get('kill_switch_active')}",
        ),
        _check(
            "database_connected",
            health.get("database") == "connected",
            f"database={health.get('database')}",
        ),
        _check(
            "execution_path_verified",
            bool(health.get("execution_connected_verified")),
            (
                f"execution_connected_verified={health.get('execution_connected_verified')} "
                f"ibgateway_alive={health.get('ibgateway_alive')} "
                f"ib_execution_stale={health.get('ib_execution_stale')}"
            ),
        ),
        _check(
            "broker_probe_ok",
            bool(health.get("ibkr_broker_probe_ok", True)),
            f"ibkr_broker_probe_ok={health.get('ibkr_broker_probe_ok')}",
        ),
        _check(
            "market_data_source_available",
            source_ready,
            f"source={source_name} ibkr_data_connected={ib_data_connected} tv_mcp_healthy={tv_mcp_healthy}",
        ),
        _check(
            "market_data_fresh",
            bool(health.get("market_data_fresh", False)),
            f"market_data_fresh={health.get('market_data_fresh')} stale_symbols={stale_symbols}",
        ),
        _check(
            "llm_path_healthy",
            bool(health.get("llm_path_healthy", False)),
            f"llm_path_healthy={health.get('llm_path_healthy')}",
        ),
        _check(
            "active_symbols_unhalted",
            bool(active_symbols) and not halted_active,
            f"active_symbols={active_symbols} halted_active={halted_active}",
        ),
        _check(
            "paper_config_matches_active_symbols",
            active_symbols == enabled_config_symbols,
            f"active_symbols={active_symbols} enabled_config_symbols={enabled_config_symbols}",
        ),
        _warn(
            "default_briefing_covers_active_symbols",
            set(active_symbols).issubset(default_briefing_symbols),
            f"default_briefing_symbols={default_briefing_symbols} active_symbols={active_symbols}",
        ),
        _warn(
            "approval_queue_clear",
            int(pending.get("count", 0) or 0) == 0,
            f"pending_count={pending.get('count', 0)} oldest_age_min={pending.get('oldest_age_min')}",
        ),
    ]

    status = _overall_status(checks)
    failed_required = [check["name"] for check in checks if check["required"] and check["status"] == "fail"]
    warnings = [check["name"] for check in checks if check["status"] == "warn"]
    return {
        "status": status,
        "timestamp": health.get("timestamp"),
        "summary": {
            "ready": status == "ready",
            "failed_required": failed_required,
            "warnings": warnings,
            "active_symbols": active_symbols,
            "halted_symbols": halted_symbols,
            "market_data_source": source_name,
        },
        "runtime": {
            "paper_mode": paper_mode,
            "live_trading": live_trading,
            "kill_switch_active": bool(health.get("kill_switch_active", True)),
            "pending_approvals": pending,
        },
        "broker": {
            "ibgateway_alive": bool(health.get("ibgateway_alive")),
            "ibgateway_port": health.get("ibgateway_port"),
            "ibkr_execution_connected": health.get("ibkr_execution_connected"),
            "execution_connected_verified": health.get("execution_connected_verified"),
            "ib_execution_stale": health.get("ib_execution_stale"),
            "ibkr_data_connected": health.get("ibkr_data_connected"),
            "ibkr_broker_probe_ok": health.get("ibkr_broker_probe_ok"),
            "ibkr_degraded_reason": health.get("ibkr_degraded_reason"),
            "schwab_connected": bool(health.get("schwab_connected")),
        },
        "market_data": {
            "source": source_name,
            "market_data_fresh": health.get("market_data_fresh"),
            "market_data_stale_symbols": stale_symbols,
            "tradingview_mcp_healthy": health.get("tradingview_mcp_healthy"),
            "tv_mcp_status": health.get("tv_mcp_status"),
        },
        "instruments": instrument_state,
        "checks": checks,
        "note": (
            "Read-only paper-pipeline readiness. Uses /health runtime truth plus "
            "static paper instrument eligibility; never mutates broker, safety, or env state."
        ),
    }


>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
def _default_db_path() -> str:
    return os.environ.get(
        "DB_PATH",
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "jarvis_trader.db",
        ),
    )


@router.get(
    "/phase3",
    summary="Phase 3 live-trading readiness — GO / WAIT / NO-GO",
    response_model=None,
    response_description=(
        "Structured readiness report with per-criterion results and overall verdict. "
        "Use ?format=markdown for a human-readable version."
    ),
)
async def get_phase3_readiness(
    format: Annotated[
        Optional[str],
        Query(description="Set to 'markdown' for human-readable output"),
    ] = None,
    edge_mode: Annotated[
        Optional[str],
        Query(
            description=(
                "Override readiness edge mode for inspection only: "
                "'paper_accrual' (default) or 'wfo_plus_fidelity'. Read-only; "
                "never persisted. When omitted, READINESS_EDGE_MODE env is honored."
            )
        ),
    ] = None,
    _api_key: str = Depends(verify_api_key),
):
    """
    Run all 10 Phase 3 readiness criteria and return the result.

    **Overall verdict logic:**
    - **GO** — all blocker criteria pass AND at most 1 warning fails
    - **WAIT** — all blockers pass but >1 warning fails
    - **NO-GO** — any blocker criterion fails

    This endpoint is read-only and informational.  It does not modify any
    config flags, trading state, or safety layer parameters.

    **Edge mode:** the response includes an `edge_mode` key. By default the
    server honors `READINESS_EDGE_MODE` (default `paper_accrual`, the legacy
    10-criterion set). Pass `?edge_mode=wfo_plus_fidelity` to inspect the
    walk-forward-edge + execution-fidelity verdict without changing any env
    or persisted state; while `ALLOW_PAPER_SIMULATED_ORDERS=False` that mode
    is inert (yields NO-GO until real fills accrue).

    Add `?format=markdown` to receive a Markdown-formatted report
    (Content-Type: text/plain) suitable for copy-paste into a PR description.
    """
    from readiness.phase3_criteria import _render_markdown, evaluate_with_edge_mode

    db_path = _default_db_path()

    try:
        # mode=None -> honors READINESS_EDGE_MODE env (default paper_accrual,
        # byte-identical to the legacy evaluate_all_criteria plus an edge_mode key).
        # An explicit ?edge_mode= overrides for read-only inspection; never persisted.
        report = evaluate_with_edge_mode(db_path, mode=edge_mode)
    except Exception as exc:
        logger.error("Phase3 readiness evaluation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Readiness evaluation failed: {exc}") from exc

    if format and format.lower() == "markdown":
        md = _render_markdown(report)
        return PlainTextResponse(content=md, media_type="text/markdown")

    return report


@router.get(
<<<<<<< HEAD
=======
    "/paper-pipeline",
    summary="Paper-trading pipeline readiness — read-only runtime contract",
    response_model=None,
    response_description=(
        "Structured ready/degraded/blocked report for the current paper pipeline. "
        "Uses /health runtime truth and static paper instrument eligibility."
    ),
)
async def get_paper_pipeline_readiness(_api_key: str = Depends(verify_api_key)):
    """
    Return paper-pipeline readiness without changing runtime state.

    This is intentionally narrower than Phase 3 live readiness: it answers
    whether the active paper pipeline can currently collect evidence with
    honest market data, verified paper execution, and unhalted instruments.
    """
    from routers.health_router import _health_cached

    try:
        health = await _health_cached()
        return build_paper_pipeline_readiness(health)
    except Exception as exc:
        logger.error("Paper pipeline readiness failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Paper pipeline readiness failed: {exc}"
        ) from exc


@router.get(
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    "/gate-v2-calibration",
    summary="Bayesian gate-v2 threshold calibration — recommended values only",
    response_model=None,
    response_description=(
        "Recommended thresholds based on accumulated verdict history. "
        "NEVER auto-applied — human review required. "
        "Use ?format=markdown for a vault-ingestible report."
    ),
)
async def get_gate_v2_calibration(
    days: Annotated[
        Optional[int],
        Query(
            ge=7,
            le=730,
            description="Lookback window in days (default 90)",
        ),
    ] = 90,
    format: Annotated[
        Optional[str],
        Query(description="Set to 'markdown' for vault-ingestible output"),
    ] = None,
    _api_key: str = Depends(verify_api_key),
):
    """
    Run the Bayesian gate-v2 threshold calibrator and return recommended values.

    **This endpoint is strictly read-only.**  It analyses accumulated verdict
    history and paper-trade outcomes to suggest whether gate thresholds should
    be tightened or loosened.  It does NOT modify ``GATE_V2_*`` env vars,
    ``engine/.env``, or any config file.

    **Recommendation strength:**
    - ``weak`` — n < 50 verdicts; prior dominates; treat as directional only
    - ``moderate`` — 50–199 verdicts; credible signal; review with intuition
    - ``strong`` — >= 200 verdicts; data dominates; worth considering change

    **When to act on recommendations:**  Only when strength is "strong" AND
    the direction aligns with current market-regime intuition.  See
    ``docs/runbooks/GATE_V2_CALIBRATOR_RUNBOOK.md`` for the full workflow.
    """
    from analytics.gate_v2_calibrator import (
        collect_historical_verdicts,
        diff_vs_current,
        recommended_thresholds,
        render_vault_markdown,
    )

    db_path = _default_db_path()
    lookback = days or 90

    try:
        verdicts_df = collect_historical_verdicts(db_path=db_path, lookback_days=lookback)
        rec = recommended_thresholds(verdicts_df)
        diff = diff_vs_current(rec)
    except Exception as exc:
        logger.error("Gate-v2 calibration failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Calibration failed: {exc}") from exc

    if format and format.lower() == "markdown":
        md = render_vault_markdown(rec, diff)
        return PlainTextResponse(content=md, media_type="text/markdown")

    return {
        "recommended_thresholds": {
            k: v
            for k, v in rec.items()
            if k not in {"sample_size", "confidence", "recommendation_strength"}
        },
        "sample_size": rec["sample_size"],
        "confidence": rec["confidence"],
        "recommendation_strength": rec["recommendation_strength"],
        "diff_vs_current": diff,
        "lookback_days": lookback,
        "note": (
            "Read-only. Recommendations never auto-applied. "
            "See docs/runbooks/GATE_V2_CALIBRATOR_RUNBOOK.md."
        ),
    }
