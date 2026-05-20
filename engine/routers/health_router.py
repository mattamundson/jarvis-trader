"""
Health and System Status Endpoints

Endpoints for monitoring system health, running preflight checks, and getting
status information about all JARVIS TRADER subsystems.
"""

import logging
import os
import socket
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from api.models import FullHealthResponse, HealthResponse
from config import settings
from middleware.rate_limit import get_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["health", "system"])

# Chrome CDP binds to IPv4 or IPv6 depending on launch flags — try both.
_TV_MCP_CDP_URLS = [
    "http://127.0.0.1:9222/json/version",
    "http://[::1]:9222/json/version",
]
_TV_MCP_CACHE_TTL_SEC = 30.0
_tv_mcp_health_cache: dict = {
    "checked_at": 0.0,
    "healthy": False,
    "details": "not yet probed",
    "status": "connecting",
}

# Cost-DB observability cache + thresholds. The DB lives under engine/data
# regardless of cwd; resolve relative to this file so the endpoint works whether
# the engine was launched from engine/ (pm2/restart_engine path) or repo root.
_LLM_COSTS_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "llm_costs.db"
_LLM_HEALTH_CACHE_TTL_SEC = 30.0
_llm_health_cache: dict = {"checked_at": 0.0, "data": None}
_LLM_LATENCY_P95_WARN_MS = int(os.getenv("LLM_LATENCY_P95_WARN_MS", "30000"))
_LLM_COST_24H_WARN_USD = float(os.getenv("LLM_COST_24H_WARN_USD", "5.0"))

# Brier-calibration surface cache. Recomputing the 30d rolling mean on every
# /health hit would re-scan trade_outcomes per agent — cache for 30s like the
# other diagnostics. Returns None when no agent has enough closed signals.
_BRIER_CACHE_TTL_SEC = 30.0
_brier_cache: dict = {"checked_at": 0.0, "value": None}


def _compute_brier_30d_rolling() -> float | None:
    """Cached 30d rolling Brier surface.

    Calls BrierCalibrationTracker.compute_rolling_brier(), which returns the
    mean across agents with ≥ min_trades closed signals (excludes the cold-start
    BRIER_NEUTRAL sentinel) — or None when no agent has enough data.

    Best-effort: returns None on any import/DB error rather than 5xxing /health.
    """
    now = time.monotonic()
    if now - _brier_cache.get("checked_at", 0.0) < _BRIER_CACHE_TTL_SEC:
        return _brier_cache.get("value")

    try:
        try:
            from engine.analytics.ic_ensemble import BrierCalibrationTracker
        except ImportError:
            from analytics.ic_ensemble import BrierCalibrationTracker
        value = BrierCalibrationTracker().compute_rolling_brier()
        value = round(float(value), 6) if value is not None else None
    except Exception as exc:
        logger.debug("brier_30d_rolling compute failed: %s", exc)
        value = None

    _brier_cache.update(checked_at=now, value=value)
    return value


def _check_tradingview_mcp_health() -> tuple[bool, str | None, str]:
    """Probe TradingView Desktop CDP endpoint. Two-stage: socket port check then HTTP.
    Cached 30s. Returns (healthy, details, status) where status is one of:
      not_running — port 9222 not listening (TV Desktop not launched)
      connecting  — port open but CDP not responding correctly
      healthy     — CDP /json/version returned 200
      degraded    — port open, CDP responded with non-200
    """
    now = time.monotonic()
    cached_at = _tv_mcp_health_cache.get("checked_at", 0.0)
    if now - cached_at < _TV_MCP_CACHE_TTL_SEC:
        return (
            _tv_mcp_health_cache["healthy"],
            _tv_mcp_health_cache["details"],
            _tv_mcp_health_cache.get("status", "connecting"),
        )

    # Stage 1: socket port check (0.5s timeout — instant fail if TV Desktop not running)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        port_result = sock.connect_ex(("127.0.0.1", 9222))
    finally:
        sock.close()

    if port_result != 0:
        details = "port 9222 not listening — TV Desktop is not running"
        _tv_mcp_health_cache.update(
            checked_at=now, healthy=False, details=details, status="not_running"
        )
        return False, details, "not_running"

    # Stage 2: CDP HTTP probe (port is open; Chrome may be still binding)
    details: str | None = None
    healthy = False
    status = "connecting"
    for url in _TV_MCP_CDP_URLS:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    healthy = True
                    details = None
                    status = "healthy"
                    break
                else:
                    details = f"CDP returned HTTP {resp.status}"
                    status = "degraded"
        except urllib.error.URLError as exc:
            details = f"CDP port 9222 unreachable: {exc.reason}"
            status = "connecting"
        except Exception as exc:
            details = f"CDP probe failed: {exc}"
            status = "connecting"

    _tv_mcp_health_cache.update(checked_at=now, healthy=healthy, details=details, status=status)
    return healthy, details, status


# Get limiter instance for rate limiting
limiter = get_limiter()

# Global references (injected from main.py)
_start_time = None
data_manager = None
safety_layer = None
db_manager = None
paper_tracker = None
pnl_monitor = None
trading_pipeline = None
schwab_connector = None


def inject_dependencies(start_time, dm, sl, dbm, pt, pm, tp, schwab=None):
    """Inject global dependencies from main.py"""
    global _start_time, data_manager, safety_layer, db_manager
    global paper_tracker, pnl_monitor, trading_pipeline, schwab_connector
    _start_time = start_time
    data_manager = dm
    safety_layer = sl
    db_manager = dbm
    paper_tracker = pt
    pnl_monitor = pm
    trading_pipeline = tp
    schwab_connector = schwab


def _ib_is_connected(ib) -> bool:
    """Resolve `is_connected` whether it's an attr or a callable."""
    if ib is None:
        return False
    is_conn = getattr(ib, "is_connected", False)
    return is_conn() if callable(is_conn) else bool(is_conn)


async def _get_ib_gateway_health() -> dict:
    """
    Return IB gateway health for the broker path that matters operationally.

    In paper mode, execution is routed through the connector attached to the
    SafetyLayer. The market-data layer may have its own IB object or none at all.
    Prefer the execution connector so `/health` and `/health/full` reflect the
    broker truth path used for paper orders.

    The returned dict always contains `execution_connected` + `data_connected`
    booleans so callers (notably `/health`) can surface per-path state directly,
    not just the OR'd `status`. This matches the contract that `/brokers/positions`
    sees, where only the execution connector matters.
    """
    execution_ib = getattr(safety_layer, "_ib_gateway", None) if safety_layer else None
    data_ib = data_manager.ibkr if data_manager else None
    execution_connected = _ib_is_connected(execution_ib)
    data_connected = _ib_is_connected(data_ib)

    ib_gw = execution_ib or data_ib

    if not ib_gw:
        return {
            "status": "not_configured",
            "mode": "paper_only",
            "execution_connected": False,
            "data_connected": False,
        }

    if hasattr(ib_gw, "health_check"):
        health = await ib_gw.health_check()
    else:
        is_connected = execution_connected if ib_gw is execution_ib else data_connected
        health = {
            "status": "connected" if is_connected else "disconnected",
        }

    health = dict(health)
    if execution_ib is not None and ib_gw is execution_ib:
        health.setdefault("source", "execution_connector")
    elif data_ib is not None and ib_gw is data_ib:
        health.setdefault("source", "market_data_connector")

    health["execution_connected"] = execution_connected
    health["data_connected"] = data_connected

    return health


@router.get(
    "/health",
    response_model=HealthResponse,
    description="Quick health check endpoint returning system status, database connectivity, and kill switch state.",
)
async def health():
    """Quick health check endpoint"""
    try:
        return await _health_inner()
    except Exception as exc:
        logger.exception("Health endpoint error: %s", exc)
        raise HTTPException(status_code=503, detail=f"Health check failed: {exc}") from exc


async def _health_inner() -> dict:
    safety = safety_layer.get_status() if safety_layer else {}

    db_ok = False
    try:
        if db_manager:
            db_manager.health_check()
            db_ok = True
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    ib_health = await _get_ib_gateway_health()

    llm_path_healthy = True
    llm_path_details: dict = {}
    try:
        from llm.client import get_llm_path_state

        llm_state = get_llm_path_state()
        llm_path_healthy = bool(llm_state.get("healthy", True))
        if not llm_path_healthy:
            llm_path_details = {
                "last_failure_ts": llm_state.get("last_failure_ts"),
                "last_failure_agent": llm_state.get("last_failure_agent"),
                "last_failure_reason": llm_state.get("last_failure_reason"),
            }
    except Exception:
        # If the client module hasn't been imported yet, assume healthy
        pass

    tv_mcp_healthy, tv_mcp_details, tv_mcp_status = _check_tradingview_mcp_health()

    status = "ok" if (db_ok and llm_path_healthy) else "degraded"

    response = {
        "status": status,
        "version": "1.1.0",
        "timestamp": now.isoformat(),
        "live_trading": settings.LIVE_TRADING_ENABLED,
        "kill_switch_active": safety.get("kill_switch_active", False),
        "paper_mode": not settings.LIVE_TRADING_ENABLED,
        "database": "connected" if db_ok else "error",
        "ibkr_connected": ib_health.get("status") == "connected",
        "ibkr_execution_connected": ib_health.get("execution_connected", False),
        "ibkr_data_connected": ib_health.get("data_connected", False),
        "schwab_connected": bool(schwab_connector and schwab_connector.is_connected),
        "uptime_seconds": (now - _start_time).total_seconds() if _start_time else 0.0,
        "llm_available": True,
        "llm_path_healthy": llm_path_healthy,
        "tradingview_mcp_healthy": tv_mcp_healthy,
        "tv_mcp_status": tv_mcp_status,
        "brier_30d_rolling": _compute_brier_30d_rolling(),
    }
    if llm_path_details:
        response["llm_path_details"] = llm_path_details
    if tv_mcp_details:
        response["tradingview_mcp_details"] = tv_mcp_details
    return response


@router.post(
    "/data/reconnect",
    description="Reconnect the IBKR market-data connector without restarting the engine. "
    "Safe to call at any time — no-ops if already connected.",
)
async def reconnect_data_connector():
    """Re-establish the IBKR market-data (IBKRDataConnector) connection if it dropped."""
    if data_manager is None:
        raise HTTPException(status_code=503, detail="data_manager not initialized")

    if data_manager.ibkr is not None and data_manager.ibkr.is_connected:
        return {"reconnected": False, "message": "already connected"}

    # Clean up stale connector before replacing it
    if data_manager.ibkr is not None:
        try:
            await data_manager.ibkr.disconnect()
        except Exception:
            pass

    from data.market_data import IBKRDataConnector

    data_manager.ibkr = IBKRDataConnector(
        host=data_manager._config.IBKR_HOST,
        port=data_manager._config.IBKR_PORT,
        client_id=data_manager._config.IBKR_CLIENT_ID,
        # Use a more generous timeout than startup (15s vs 5s) since this is manual recovery
        connect_timeout=max(
            getattr(data_manager._config, "IBKR_CONNECT_TIMEOUT_SECONDS", 5.0), 15.0
        ),
    )
    connected = await data_manager.ibkr.connect()

    if not connected:
        raise HTTPException(
            status_code=503,
            detail="IBKR data reconnect failed — is IB Gateway running on port 4002?",
        )

    logger.info("IBKR data connector reconnected via POST /data/reconnect")
    return {"reconnected": True, "message": "IBKR data connector reconnected"}


@router.get(
    "/health/full",
    response_model=FullHealthResponse,
    description="Comprehensive health check of all JARVIS TRADER subsystems including database, safety layer, circuit breakers, and portfolio status.",
)
async def full_health_check():
    """Comprehensive health check of all JARVIS TRADER subsystems"""
    try:
        return await _full_health_inner()
    except Exception as exc:
        logger.exception("Full health check error: %s", exc)
        raise HTTPException(status_code=503, detail=f"Health check failed: {exc}") from exc


async def _full_health_inner() -> dict:
    status: dict = {}
    overall = "healthy"

    # 1. Database health
    try:
        if db_manager:
            db_health = db_manager.health_check()
            status["database"] = {"status": "ok", "details": db_health}
        else:
            status["database"] = {"status": "not_initialized"}
            overall = "degraded"
    except Exception as e:
        status["database"] = {"status": "error", "error": str(e)}
        overall = "degraded"

    # 2. Safety layer
    try:
        if safety_layer:
            kill_switch = safety_layer._kill_switch_active
            kill_reason = safety_layer._kill_switch_reason
            status["safety_layer"] = {
                "status": "ok",
                "kill_switch_active": kill_switch,
                "kill_switch_reason": kill_reason.value if kill_reason else None,
            }
            if kill_switch:
                overall = "kill_switch_active"
        else:
            status["safety_layer"] = {"status": "not_initialized"}
            overall = "degraded"
    except Exception as e:
        status["safety_layer"] = {"status": "error", "error": str(e)}
        overall = "degraded"

    # 3. IB Gateway (optional)
    try:
        status["ib_gateway"] = await _get_ib_gateway_health()
    except Exception as e:
        status["ib_gateway"] = {"status": "error", "error": str(e)}

    # 4. Circuit breakers
    try:
        if safety_layer and hasattr(safety_layer, "check_circuit_breakers"):
            breakers = safety_layer.check_circuit_breakers()
            all_clear = not breakers.get("daily_limit_breached", False) and not breakers.get(
                "drawdown_breached", False
            )
            status["circuit_breakers"] = {
                "status": "ok" if all_clear else "tripped",
                "details": breakers,
            }
            if not all_clear:
                if overall == "healthy":
                    overall = "circuit_breaker_tripped"
        else:
            status["circuit_breakers"] = {"status": "not_available"}
    except Exception as e:
        status["circuit_breakers"] = {"status": "error", "error": str(e)}

    # 5. Portfolio tracker
    try:
        if paper_tracker:
            positions = paper_tracker.get_open_positions()
            status["portfolio"] = {
                "status": "ok",
                "open_positions": len(positions),
            }
        else:
            status["portfolio"] = {"status": "not_initialized"}
    except Exception as e:
        status["portfolio"] = {"status": "error", "error": str(e)}

    # 6. PnL monitor
    try:
        if pnl_monitor:
            pnl_state = pnl_monitor.get_current_pnl_state()
            status["pnl_monitor"] = {
                "status": "ok",
                "source": pnl_state.source,
                "daily_pnl": round(pnl_monitor.get_daily_pnl(), 4),
                "drawdown_pct": round(pnl_monitor.get_drawdown_pct(), 6),
                "current_balance": round(pnl_state.current_balance, 2),
                "starting_balance": round(pnl_state.starting_balance, 2),
            }
        else:
            status["pnl_monitor"] = {"status": "not_initialized"}
    except Exception as e:
        status["pnl_monitor"] = {"status": "error", "error": str(e)}

    return {
        "overall": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": (
            (datetime.now(timezone.utc) - _start_time).total_seconds() if _start_time else 0
        ),
        "subsystems": status,
        "version": "1.1.0",
        "phase": "paper_trading",
    }


@router.get(
    "/system/preflight",
    description="Run all critical pre-flight checks (database, kill switch, circuit breakers, pipeline, VIX, market session, IB Gateway, portfolio).",
)
@limiter.limit("60/minute")
async def system_preflight(request: Request):
    """
    Run all critical pre-flight checks before accepting trading signals.
    Returns a list of checks with pass/fail/warn status.
    """
    checks = []
    all_pass = True

    def add_check(name: str, status: str, detail: str):
        nonlocal all_pass
        if status == "fail":
            all_pass = False
        checks.append({"name": name, "status": status, "detail": detail})

    try:
        if db_manager is None:
            add_check("Database", "fail", "Not initialized")
        else:
            with db_manager._lock:
                conn = sqlite3.connect(str(db_manager._db_path))
                try:
                    conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()
                    add_check(
                        "Database",
                        "pass",
                        f"SQLite healthy — {str(db_manager._db_path).split('/')[-1]}",
                    )
                finally:
                    conn.close()
    except Exception as e:
        add_check("Database", "fail", str(e))

    try:
        if safety_layer is None:
            add_check("Kill Switch", "warn", "SafetyLayer not initialized")
        else:
            ks = safety_layer._kill_switch_active
            if ks:
                add_check("Kill Switch", "fail", "KILL SWITCH IS ACTIVE — trading blocked")
            else:
                add_check("Kill Switch", "pass", "Kill switch clear")
    except Exception as e:
        add_check("Kill Switch", "warn", f"Could not check: {e}")

    try:
        if safety_layer is not None:
            cb_result = safety_layer.check_circuit_breakers()
            daily_breached = cb_result.get("daily_limit_breached", False)
            drawdown_breached_flag = cb_result.get("drawdown_breached", False)
            if daily_breached or drawdown_breached_flag:
                tripped = []
                if daily_breached:
                    tripped.append("daily_loss_limit")
                if drawdown_breached_flag:
                    tripped.append("drawdown_limit")
                add_check("Circuit Breakers", "fail", f"Tripped: {', '.join(tripped)}")
            else:
                add_check("Circuit Breakers", "pass", "All circuit breakers clear")
        else:
            add_check("Circuit Breakers", "warn", "SafetyLayer not initialized")
    except Exception as e:
        add_check("Circuit Breakers", "warn", f"Could not check: {e}")

    try:
        if trading_pipeline is None:
            add_check("Pipeline", "fail", "TradingPipeline not initialized")
        else:
            add_check("Pipeline", "pass", "TradingPipeline ready")
    except Exception as e:
        add_check("Pipeline", "fail", str(e))

    try:
        from analytics.vix_overlay import fetch_vix_async

        vix_state = await fetch_vix_async(data_manager)
        vix_val = getattr(vix_state, "vix_value", None)
        source = getattr(vix_state, "source", "unknown")
        if vix_val is not None:
            add_check(
                "VIX Data",
                "pass" if source != "error_fallback" else "warn",
                f"VIX={vix_val:.1f} (source: {source})",
            )
        else:
            add_check("VIX Data", "warn", "VIX unavailable — using fallback")
    except Exception as e:
        add_check("VIX Data", "warn", f"VIX check failed: {e}")

    try:
        from datetime import datetime as _dt

        import pytz

        ct_tz = pytz.timezone("America/Chicago")
        now_ct = _dt.now(ct_tz)
        weekday = now_ct.weekday()
        hour = now_ct.hour
        if weekday >= 5:
            add_check("Market Session", "warn", "Weekend — market closed")
        elif 8 <= hour < 15:
            add_check("Market Session", "pass", f"RTH active ({now_ct.strftime('%H:%M')} CT)")
        elif 17 <= hour or hour < 6:
            add_check(
                "Market Session", "pass", f"Futures session active ({now_ct.strftime('%H:%M')} CT)"
            )
        else:
            add_check(
                "Market Session",
                "warn",
                f"Outside primary trading hours ({now_ct.strftime('%H:%M')} CT)",
            )
    except Exception as e:
        add_check("Market Session", "warn", str(e))

    try:
        ib_gw = data_manager.ibkr if data_manager else None
        if ib_gw is None:
            add_check("IB Gateway", "warn", "Not initialized (paper only — optional)")
        else:
            connected = bool(getattr(ib_gw, "is_connected", False))
            if connected:
                add_check("IB Gateway", "pass", "Paper port 4002 connected")
            else:
                add_check("IB Gateway", "warn", "Not connected (paper only — optional)")
    except Exception as e:
        add_check("IB Gateway", "warn", f"Could not check: {e}")

    try:
        if paper_tracker is None:
            add_check("Portfolio Tracker", "fail", "Not initialized")
        else:
            positions = paper_tracker.get_open_positions()
            if pnl_monitor is not None:
                pnl_state = pnl_monitor.get_current_pnl_state()
                balance = round(pnl_state.current_balance, 2)
                add_check(
                    "Portfolio Tracker",
                    "pass",
                    f"Balance: ${balance:,.2f} | {len(positions)} open position(s)",
                )
            else:
                add_check("Portfolio Tracker", "pass", f"{len(positions)} open position(s)")
    except Exception as e:
        add_check("Portfolio Tracker", "fail", str(e))

    return {
        "all_pass": all_pass,
        "check_count": len(checks),
        "pass_count": sum(1 for c in checks if c["status"] == "pass"),
        "fail_count": sum(1 for c in checks if c["status"] == "fail"),
        "warn_count": sum(1 for c in checks if c["status"] == "warn"),
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/system/backup-status",
    description="Get database backup status including retention policy, available backup files, and backup statistics.",
)
async def get_backup_status():
    """
    Get database backup status and available backups.

    Returns backup statistics, retention policy, and list of available backup files.
    """
    try:
        from backup.db_backup import get_backup_manager

        backup_manager = get_backup_manager()
        status = backup_manager.get_status()

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "backup_status": status,
        }
    except Exception as e:
        logger.error(f"Backup status check failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Backup status check failed: {str(e)}"
        ) from None


@router.get(
    "/health/backup-status",
    description="Get nightly backup status: count, last backup path, retention policy.",
)
async def health_backup_status():
    """Return summary backup status from the singleton backup manager."""
    try:
        from backup.db_backup import get_backup_status as _get_status

        return _get_status()
    except Exception as e:
        logger.error(f"Backup status check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Backup status failed: {str(e)}") from None


@router.get(
    "/health/watchdog",
    description="Minimal liveness ping for the engine watchdog. No auth required, no heavy computation.",
    include_in_schema=True,
)
async def health_watchdog():
    """
    Lightweight liveness endpoint polled by watchdog_engine.ps1 every 60 seconds.

    Returns minimal status so the watchdog can distinguish:
      - Engine process alive and responsive  -> status="ok"
      - Engine process dead / port not bound -> HTTP connection error (watchdog treats as DOWN)

    No authentication required. No database queries. No external calls.
    """
    now = datetime.now(timezone.utc)
    uptime = (now - _start_time).total_seconds() if _start_time else 0.0
    return {
        "status": "ok",
        "timestamp": now.isoformat(),
        "uptime_seconds": round(uptime, 1),
        "engine_version": "1.1.0",
    }


@router.get(
    "/health/apis",
    description="Check connectivity to all external data APIs (Polygon, Finnhub, Brave, Anthropic, IBKR). Cached 60s.",
)
async def api_health():
    """Check connectivity to all external data APIs."""
    import httpx

    results = {}

    # Polygon
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                "https://api.polygon.io/v2/aggs/ticker/CL/range/1/day/2026-04-03/2026-04-04",
                params={"limit": 1, "apiKey": settings.POLYGON_API_KEY},
            )
            d = r.json()
            if d.get("resultsCount", 0) > 0:
                close = d["results"][0]["c"]
                results["polygon"] = {"status": "ok", "test": f"CL close: ${close:.2f}"}
            else:
                results["polygon"] = {
                    "status": "no_data",
                    "error": d.get("error", d.get("status", "unknown")),
                }
    except Exception as e:
        results["polygon"] = {"status": "error", "error": str(e)[:100]}

    # Finnhub
    try:
        import finnhub as _fh

        fh_client = _fh.Client(api_key=settings.FINNHUB_API_KEY)
        news = fh_client.general_news("general", min_id=0)
        results["finnhub"] = {"status": "ok", "test": f"{len(news)} news items"}
    except Exception as e:
        results["finnhub"] = {"status": "error", "error": str(e)[:100]}

    # Brave
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/news/search",
                params={"q": "crude oil futures", "count": 3, "country": "us"},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": settings.BRAVE_API_KEY,
                },
            )
            d = r.json()
            count = len(d.get("results", []))
            results["brave"] = {
                "status": "ok" if count > 0 else "no_data",
                "test": f"{count} results",
            }
    except Exception as e:
        results["brave"] = {"status": "error", "error": str(e)[:100]}

    # Anthropic (just check key is set)
    results["anthropic"] = {
        "status": "ok" if settings.ANTHROPIC_API_KEY else "not_configured",
        "note": "key present" if settings.ANTHROPIC_API_KEY else "missing",
    }

    # IBKR
    try:
        from main import app as _app

        ibkr = getattr(_app.state, "ibkr_connector", None)
        if ibkr and getattr(ibkr, "is_connected", False):
            results["ibkr"] = {"status": "ok"}
        else:
            results["ibkr"] = {"status": "disconnected", "note": "normal outside market hours"}
    except Exception:
        results["ibkr"] = {"status": "unknown"}

    overall = (
        "ok"
        if all(v["status"] == "ok" for v in results.values() if v["status"] != "disconnected")
        else "degraded"
    )
    return {
        "status": overall,
        "apis": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/health/pm2",
    description="pm2 process status for jarvis-engine — restart count, uptime, memory.",
)
async def pm2_status():
    """Query pm2 for jarvis-engine process stats. Returns empty on non-pm2 deployments."""
    import asyncio
    import json as _json

    try:
        proc = await asyncio.create_subprocess_shell(
            "pm2 jlist",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        processes = _json.loads(stdout.decode())
        for p in processes:
            if p.get("name") == "jarvis-engine":
                monit = p.get("monit", {})
                pm2_env = p.get("pm2_env", {})
                return {
                    "found": True,
                    "status": pm2_env.get("status"),
                    "restart_count": pm2_env.get("restart_time", 0),
                    "unstable_restarts": pm2_env.get("unstable_restarts", 0),
                    "uptime_ms": pm2_env.get("pm_uptime"),
                    "memory_mb": round(monit.get("memory", 0) / 1_048_576, 1),
                    "cpu_pct": monit.get("cpu", 0),
                    "pid": p.get("pid"),
                }
        return {"found": False, "note": "jarvis-engine not found in pm2 list"}
    except Exception as exc:
        return {"found": False, "error": str(exc)}


@router.get(
    "/health/llm",
    description="LLM call observability: per-model latency p50/p95, 24h cost, "
    "Anthropic-fallback detection. Reads from llm_costs.db. Cached 30s.",
)
async def llm_health():
    """
    Surface what `/health.llm_path_healthy` does NOT — actual call latencies and
    whether we are silently paying Anthropic. Returns:

      - per_model_1h: {model: {count, p50_ms, p95_ms, max_ms, cost_usd, last_call_ts}}
      - per_model_24h: {model: {count, cost_usd}}
      - anthropic_fallback_active: bool — any claude-* call in last hour means
        Ollama hot path failed and the engine fell back. Should be False in
        steady state since the 2026-04-23 cutover.
      - latency_warning: bool — any model with p95 > LLM_LATENCY_P95_WARN_MS (30s default)
      - cost_warning: bool — 24h cost > LLM_COST_24H_WARN_USD ($5/day default)
      - cost_24h_total_usd, thresholds, timestamp
    """
    now = time.monotonic()
    cached = _llm_health_cache.get("data")
    if cached and (now - _llm_health_cache.get("checked_at", 0.0)) < _LLM_HEALTH_CACHE_TTL_SEC:
        return cached

    if not _LLM_COSTS_DB_PATH.exists():
        return {
            "status": "no_db",
            "db_path": str(_LLM_COSTS_DB_PATH),
            "note": "cost-tracker DB not yet initialized; engine has made no LLM calls",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    try:
        conn = sqlite3.connect(str(_LLM_COSTS_DB_PATH))
        cur = conn.cursor()
        # Stored timestamps are ISO with 'T' separator and '+00:00' suffix
        # (e.g. '2026-05-05T16:33:12.999595+00:00'). SQLite's datetime('now')
        # uses a space separator ('2026-05-05 17:38:04'), so naive string
        # comparison silently matches all of today's rows because 'T' > ' '
        # in ASCII. Use strftime to produce a 'T'-prefixed cutoff that lex-sorts
        # correctly against the ISO column.
        cutoff_1h = "strftime('%Y-%m-%dT%H:%M:%S', 'now', '-1 hour')"
        cutoff_24h = "strftime('%Y-%m-%dT%H:%M:%S', 'now', '-24 hours')"
        cur.execute(
            "SELECT model, latency_ms, cost_usd, timestamp "
            f"FROM llm_calls WHERE timestamp > {cutoff_1h}"
        )
        rows_1h = cur.fetchall()
        cur.execute(
            "SELECT model, COUNT(*), COALESCE(SUM(cost_usd), 0.0) "
            f"FROM llm_calls WHERE timestamp > {cutoff_24h} "
            "GROUP BY model"
        )
        rows_24h = cur.fetchall()
        conn.close()
    except sqlite3.DatabaseError as exc:
        return {
            "status": "db_error",
            "error": str(exc)[:200],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    per_model_1h: dict = {}
    for model, latency_ms, cost_usd, ts in rows_1h:
        bucket = per_model_1h.setdefault(model, {"latencies": [], "cost_usd": 0.0, "last_ts": ts})
        bucket["latencies"].append(int(latency_ms or 0))
        bucket["cost_usd"] += float(cost_usd or 0.0)
        if ts and ts > bucket["last_ts"]:
            bucket["last_ts"] = ts

    summary_1h = {}
    anthropic_fallback_active = False
    latency_warning = False
    for model, b in per_model_1h.items():
        latencies = sorted(b["latencies"])
        n = len(latencies)
        if n == 0:
            continue
        p50 = latencies[n // 2]
        p95_idx = max(0, min(n - 1, int(n * 0.95) - 1)) if n > 1 else 0
        p95 = latencies[p95_idx]
        max_lat = latencies[-1]
        if model.startswith("claude-"):
            anthropic_fallback_active = True
        if p95 > _LLM_LATENCY_P95_WARN_MS:
            latency_warning = True
        summary_1h[model] = {
            "count": n,
            "p50_ms": p50,
            "p95_ms": p95,
            "max_ms": max_lat,
            "cost_usd": round(b["cost_usd"], 4),
            "last_call_ts": b["last_ts"],
        }

    summary_24h = {}
    cost_24h_total = 0.0
    for model, count, total_cost in rows_24h:
        cost = float(total_cost or 0.0)
        summary_24h[model] = {"count": int(count), "cost_usd": round(cost, 4)}
        cost_24h_total += cost

    cost_warning = cost_24h_total > _LLM_COST_24H_WARN_USD

    data = {
        "status": "ok",
        "anthropic_fallback_active": anthropic_fallback_active,
        "latency_warning": latency_warning,
        "cost_warning": cost_warning,
        "cost_24h_total_usd": round(cost_24h_total, 4),
        "per_model_1h": summary_1h,
        "per_model_24h": summary_24h,
        "thresholds": {
            "latency_p95_warn_ms": _LLM_LATENCY_P95_WARN_MS,
            "cost_24h_warn_usd": _LLM_COST_24H_WARN_USD,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    _llm_health_cache["checked_at"] = now
    _llm_health_cache["data"] = data
    return data


@router.post(
    "/health/backup-now",
    description="Trigger an immediate database backup outside the nightly schedule.",
)
async def trigger_backup_now():
    """Trigger an on-demand backup of the SQLite database."""
    try:
        from backup.db_backup import run_nightly_backup

        result = await run_nightly_backup(str(settings.SQLITE_DB_PATH))
        return result
    except Exception as e:
        logger.error(f"On-demand backup failed: {e}")
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)}") from None


@router.get(
    "/health/readiness",
    description="Phase-1 live-trading readiness gate. Returns the same 7-criteria "
    "check as `python -m backtest.live_readiness --json`. Sets HTTP 200 "
    "when all blocking checks PASS, 503 otherwise — usable as a "
    "deployment-gate probe by external monitoring or CI.",
)
async def live_readiness_endpoint(strict: bool = False):
    """Aggregate the 7 mission-accomplished criteria into a single response.

    Query params:
      strict — if true, advisory checks (currently only C3 Phase 0) are treated
               as blocking. Default false matches CLI behavior.

    Returns:
      authorized   : bool — True iff all blocking checks PASS
      blocking_pass: int  — number of blocking checks that passed
      blocking_total: int — total number of blocking checks
      results      : list of CheckResult dicts (name, passed, detail, blocking, fix)

    Status codes:
      200 — authorized=True (all blocking checks PASS, live trading authorized)
      503 — authorized=False (one or more blocking checks FAIL — live BLOCKED)
      500 — gate infrastructure error
    """
    from dataclasses import asdict

    from fastapi.responses import JSONResponse

    try:
        from backtest.live_readiness import run_all_checks
    except ImportError as exc:
        logger.error("live_readiness module not importable: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": f"live_readiness import failed: {exc}"},
        )

    try:
        results = run_all_checks()
    except Exception as exc:
        logger.exception("live_readiness check infrastructure failed")
        return JSONResponse(
            status_code=500,
            content={"error": f"check infrastructure failed: {exc}"},
        )

    if strict:
        for r in results:
            r.blocking = True

    authorized = all(r.passed for r in results if r.blocking)
    blocking_pass = sum(1 for r in results if r.passed and r.blocking)
    blocking_total = sum(1 for r in results if r.blocking)

    body = {
        "authorized": authorized,
        "blocking_pass": blocking_pass,
        "blocking_total": blocking_total,
        "results": [asdict(r) for r in results],
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    status_code = 200 if authorized else 503
    return JSONResponse(status_code=status_code, content=body)
