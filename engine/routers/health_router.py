"""
Health and System Status Endpoints

Endpoints for monitoring system health, running preflight checks, and getting
status information about all JARVIS TRADER subsystems.
"""

import logging
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from api.models import FullHealthResponse, HealthResponse
from config import settings
from middleware.rate_limit import get_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["health", "system"])

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
    status = "ok" if db_ok else "degraded"

    return {
        "status": status,
        "version": "1.1.0",
        "timestamp": now.isoformat(),
        "live_trading": settings.LIVE_TRADING_ENABLED,
        "kill_switch_active": safety.get("kill_switch_active", False),
        "paper_mode": not settings.LIVE_TRADING_ENABLED,
        "database": "connected" if db_ok else "error",
        "ibkr_connected": bool(getattr(data_manager.ibkr, "is_connected", False))
        if data_manager and data_manager.ibkr
        else False,
        "schwab_connected": bool(schwab_connector and schwab_connector.is_connected),
        "uptime_seconds": (now - _start_time).total_seconds() if _start_time else 0.0,
        "llm_available": True,
    }


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
        ib_gw = data_manager.ibkr if data_manager else None
        if ib_gw:
            ib_health = await ib_gw.health_check()
            status["ib_gateway"] = ib_health
        else:
            status["ib_gateway"] = {"status": "not_configured", "mode": "paper_only"}
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
        "uptime_seconds": (datetime.now(timezone.utc) - _start_time).total_seconds()
        if _start_time
        else 0,
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
