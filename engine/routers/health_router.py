"""
Health and System Status Endpoints

Endpoints for monitoring system health, running preflight checks, and getting
status information about all JARVIS TRADER subsystems.
"""

import asyncio
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

# SOTA P1.6 — TV MCP health-flap fix.
#
# Before this: a single missed CDP probe (Chrome momentarily busy, one dropped
# packet) flipped `tradingview_mcp_healthy` False for up to _TV_MCP_CACHE_TTL_SEC,
# which the dashboard renders as a hard red dot (EngineHealthWidget.tsx) — so a
# TV Desktop that is actually up and fine appeared to flap between red and green
# every poll. Meanwhile "TV Desktop not installed" (port 9222 never listening —
# a steady, expected condition for Amo, who doesn't always run TV Desktop) was
# indistinguishable from that transient case at the boolean level.
#
# Fix: a *grace* cache remembers the last genuinely-good CDP probe. A transient
# post-port-open failure (status connecting/degraded) within the grace window is
# treated as a blip and masked behind the last-known-good result, so top-line
# health doesn't oscillate on it. `not_running` (port closed) is NEVER masked —
# it is reported immediately every time, because it is steady/expected, not an
# error to paper over, and masking it would hide real information. The grace
# memory is cleared whenever the state goes to not_running so a later relaunch's
# own startup blips aren't compared against a long-dead session.
_TV_MCP_GRACE_TTL_SEC = 120.0
_tv_mcp_last_good: dict = {"at": 0.0, "details": None}

# Background refresher: probes run in a thread on a faster cadence than
# _TV_MCP_CACHE_TTL_SEC so /health almost always serves an already-warm cache
# entry instead of making a blocking urllib call inline on the request path.
# Started lazily (idempotent) from _health_inner on first use, since an
# APIRouter has no lifespan hook of its own to wire this at app startup.
_TV_MCP_REFRESH_INTERVAL_SEC = 10.0
_tv_mcp_refresher_task: "asyncio.Task | None" = None

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

# IB Gateway process-liveness cache. This is a *port* probe (is the Gateway
# accepting TCP on the configured IB port?), deliberately distinct from the
# connector-state booleans (ibkr_*_connected). The Gateway being down — not the
# connector dropping — is what silently disabled stop enforcement for ~13h on
# 2026-06-01 (trade #178). Cached 30s like the TV-CDP probe so /health stays cheap.
_IBGW_CACHE_TTL_SEC = 30.0
_ibgw_health_cache: dict = {"checked_at": 0.0, "alive": False, "port": None}

# ---------------------------------------------------------------------------
# /health single-flight snapshot cache (resilience under load spikes).
#
# The sub-diagnostics above are each 30s-cached, but `_health_inner` still makes
# several *uncached* synchronous SQLite calls (db_manager.ping, get_pending_
# approval_stats, futures-sentiment staleness) inside an async handler. Left
# un-offloaded, those block the event loop. When the dashboard polls /health many
# times per second AND the box is under contention (multiple engines/sessions
# hammering the 325MB SQLite DB), N concurrent blocking computes pile up on the
# single event-loop thread and latency compounds — a warm 20ms call can spike to
# 5-12s. port_guardian probes /health with an 8s timeout; a spike past that trips
# a force-restart, which adds load — a self-amplifying cascade (4 such restarts
# on 2026-07-06 22:11-22:40 UTC). SOTA plan P0.5: each of those three call sites
# now runs via asyncio.to_thread so even a cache-miss recompute can't block the
# loop — the single-flight cache below caps *how often* the blocking work runs;
# to_thread caps *whether it blocks* when it does run.
#
# Single-flight fix: at most ONE recompute per TTL window regardless of request
# volume. A polling storm collapses to one blocking compute/sec instead of N, so
# the event-loop pileup cannot form. Response shape is byte-identical; the only
# effect is `timestamp`/`uptime_seconds` may be up to TTL seconds stale, which is
# well within a health endpoint's tolerance. TTL is env-tunable; 0 disables the
# cache (always live) for callers that need it. The FIRST call after boot is
# always live (cold cache), so port_guardian readiness stays truthful.
# ---------------------------------------------------------------------------
_HEALTH_SNAPSHOT_TTL_SEC = float(os.getenv("HEALTH_SNAPSHOT_TTL_SEC", "1.0"))
_health_snapshot: dict = {"computed_at": 0.0, "payload": None}
_health_refresh_lock = asyncio.Lock()


async def _health_cached() -> dict:
    """Single-flight wrapper around _health_inner().

    Serves a cached payload if computed within _HEALTH_SNAPSHOT_TTL_SEC; otherwise
    recomputes under a lock so concurrent callers share one compute rather than
    each triggering their own blocking DB pass. TTL<=0 always recomputes.
    """
    if _HEALTH_SNAPSHOT_TTL_SEC <= 0:
        return await _health_inner()

    now = time.monotonic()
    payload = _health_snapshot["payload"]
    if payload is not None and (now - _health_snapshot["computed_at"]) < _HEALTH_SNAPSHOT_TTL_SEC:
        return payload

    async with _health_refresh_lock:
        # Double-check: a peer coroutine may have refreshed while we waited.
        now2 = time.monotonic()
        payload = _health_snapshot["payload"]
        if payload is not None and (now2 - _health_snapshot["computed_at"]) < _HEALTH_SNAPSHOT_TTL_SEC:
            return payload
        fresh = await _health_inner()
        _health_snapshot["payload"] = fresh
        _health_snapshot["computed_at"] = time.monotonic()
        return fresh


def _check_ibgateway_alive() -> tuple[bool, int]:
    """Probe whether IB Gateway is accepting TCP connections on the IB port.

    Uses 127.0.0.1 explicitly (never 'localhost' — it resolves to ::1 first on
    Windows and the Gateway binds IPv4). 0.5s timeout, cached 30s. Returns
    (alive, port). A True here with ibkr_data_connected=False means the connector
    dropped but the Gateway is up (recover via POST /data/reconnect); a False
    means the Gateway process itself is down (needs a relaunch + login).
    """
    port = int(getattr(settings, "IBKR_PORT", 4002) or 4002)
    now = time.monotonic()
    if now - _ibgw_health_cache.get("checked_at", 0.0) < _IBGW_CACHE_TTL_SEC:
        return _ibgw_health_cache["alive"], _ibgw_health_cache.get("port") or port

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        alive = sock.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        alive = False
    finally:
        sock.close()

    _ibgw_health_cache.update(checked_at=now, alive=alive, port=port)
    return alive, port


# ---------------------------------------------------------------------------
# PRB-24 — pm2-vs-reality process-supervision cross-check.
#
# Root cause this guards against: pm2 jlist (what pm2 BELIEVES it is
# supervising) and a raw TCP port probe (what is ACTUALLY listening) can
# independently disagree, and nothing before this cross-checked the two. A
# WinError 10048 port-bind race left a healthy-but-pm2-unsupervised orphan
# process serving :8010 for a stretch (2026-07-28/29 incident), and a
# separate 2026-07-28 audit found pm2 believed jarvis-dashboard/jarvis-engine
# were errored/stopped while orphan processes actually served both ports. A
# human had to run `pm2 jlist` AND hit /health AND check the port side-by-side
# to ever notice — this makes that comparison automatic and a MISMATCH a
# first-class, unambiguous signal instead of something buried in raw JSON.
#
# Port-liveness probe pattern mirrors _check_ibgateway_alive above: 127.0.0.1
# explicit (never 'localhost' — Windows resolves it to ::1 first), short
# timeout, cached. Must NEVER raise / crash /health — pm2 missing from PATH,
# a timed-out shell-out, or a malformed netstat parse all degrade to
# "supervision check unavailable" rather than a 500.
# ---------------------------------------------------------------------------
_SUPERVISED_APPS: dict[str, int] = {
    "jarvis-engine": 8010,
    "jarvis-dashboard": 3010,
    "jarvis-bridge-api": 8020,
}
_SUPERVISION_CACHE_TTL_SEC = 30.0
_supervision_cache: dict = {"checked_at": 0.0, "payload": None}
_supervision_port_cache: dict[int, dict] = {}


async def _run_pm2_jlist() -> tuple[list[dict] | None, str | None]:
    """Shell out to `pm2 jlist`. Returns (processes, error) — error is None on success.

    Never raises: pm2 missing from PATH, a timeout, a non-zero exit, or
    malformed JSON all resolve to (None, "<reason>") so callers can degrade
    gracefully to "supervision check unavailable" instead of a 500.
    """
    import json

    try:
        proc = await asyncio.create_subprocess_shell(
            "pm2 jlist",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode != 0:
            reason = stderr.decode(errors="replace")[:200] if stderr else "no output"
            return None, f"pm2 jlist exited {proc.returncode}: {reason}"
        return json.loads(stdout.decode()), None
    except FileNotFoundError:
        return None, "pm2 not found on PATH"
    except asyncio.TimeoutError:
        return None, "pm2 jlist timed out after 5s"
    except Exception as exc:
        return None, f"pm2 jlist failed: {exc}"


def _parse_netstat_listening_pid(output: str, port: int) -> int | None:
    """Parse `netstat -ano` text for the PID LISTENING on the given port.

    Pure function (no subprocess) so it's directly unit-testable against fixed
    fixture text. Matches any local address ending in ':<port>' (covers
    127.0.0.1, 0.0.0.0, and IPv6 '[::]' forms) with state LISTENING. The
    leading colon in the match anchor prevents a numeric-suffix false match
    (e.g. port 10 never matches a ':8010' row). Returns None if no row matches
    or the row is malformed.
    """
    needle = f":{port}"
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "TCP":
            continue
        local_addr, state = parts[1], parts[3]
        if state != "LISTENING" or not local_addr.endswith(needle):
            continue
        try:
            return int(parts[-1])
        except ValueError:
            continue
    return None


async def _get_port_owner_pid(port: int) -> int | None:
    """Best-effort actual TCP port-owner PID via `netstat -ano` (Windows).

    Never raises — any subprocess/parse failure yields None ("can't confirm
    owner"), which the cross-check treats as unknown rather than asserting a
    hard mismatch it can't actually back up.
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            "netstat -ano",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        return _parse_netstat_listening_pid(stdout.decode(errors="replace"), port)
    except Exception as exc:
        logger.debug("supervision: netstat probe for port %s failed: %s", port, exc)
        return None


def _check_port_alive(port: int) -> bool:
    """TCP liveness probe for an arbitrary port — same pattern/timeout as
    _check_ibgateway_alive, generalized and cached per-port."""
    now = time.monotonic()
    cached = _supervision_port_cache.get(port)
    if cached and now - cached["checked_at"] < _SUPERVISION_CACHE_TTL_SEC:
        return cached["alive"]

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        alive = sock.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        alive = False
    finally:
        sock.close()

    _supervision_port_cache[port] = {"checked_at": now, "alive": alive}
    return alive


async def _compute_supervision_status() -> dict:
    """Cross-check pm2's believed state for each supervised app against the
    actual TCP port owner. See module-level PRB-24 comment above for the
    incident this guards against.

    Returns:
      available     : bool  — False only when pm2 itself couldn't be queried
      supervision_ok: bool | None — None when unavailable; True iff every app
                       agrees; False if any app has a mismatch_reason
      error         : str | None — populated only when unavailable
      checked_at    : ISO timestamp
      apps          : {name: {port, pm2_found, pm2_status, pm2_pid, port_alive,
                        actual_pid, mismatch_reason}}
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    processes, pm2_error = await _run_pm2_jlist()

    if processes is None:
        return {
            "available": False,
            "supervision_ok": None,
            "error": pm2_error,
            "checked_at": now_iso,
            "apps": {},
        }

    by_name = {p.get("name"): p for p in processes if isinstance(p, dict)}
    apps: dict[str, dict] = {}
    all_ok = True

    for app_name, port in _SUPERVISED_APPS.items():
        entry = by_name.get(app_name)
        pm2_status = entry.get("pm2_env", {}).get("status") if entry else None
        pm2_pid = (entry.get("pid") if entry else None) or None  # pm2 uses 0 for stopped

        port_alive = _check_port_alive(port)
        actual_pid = await _get_port_owner_pid(port) if port_alive else None

        mismatch_reason: str | None = None
        pm2_believes_up = pm2_status == "online"

        if entry is None and port_alive:
            mismatch_reason = (
                f"pm2 has no '{app_name}' entry at all, but port {port} is live "
                f"(actual_pid={actual_pid}) — an unsupervised/orphan process is serving it"
            )
        elif pm2_believes_up and not port_alive:
            mismatch_reason = (
                f"pm2 reports '{app_name}' status=online (pid={pm2_pid}) but port {port} "
                "is not accepting connections"
            )
        elif entry is not None and not pm2_believes_up and port_alive:
            mismatch_reason = (
                f"pm2 reports '{app_name}' status={pm2_status!r} but port {port} is live "
                f"(actual_pid={actual_pid}) — an orphan process is serving it under pm2's back"
            )
        elif (
            pm2_believes_up
            and port_alive
            and actual_pid is not None
            and pm2_pid is not None
            and actual_pid != pm2_pid
        ):
            mismatch_reason = (
                f"pid mismatch on '{app_name}': pm2 believes pid={pm2_pid} but port {port} "
                f"is actually owned by pid={actual_pid}"
            )

        if mismatch_reason is not None:
            all_ok = False

        apps[app_name] = {
            "port": port,
            "pm2_found": entry is not None,
            "pm2_status": pm2_status,
            "pm2_pid": pm2_pid,
            "port_alive": port_alive,
            "actual_pid": actual_pid,
            "mismatch_reason": mismatch_reason,
        }

    return {
        "available": True,
        "supervision_ok": all_ok,
        "error": None,
        "checked_at": now_iso,
        "apps": apps,
    }


async def _supervision_cached() -> dict:
    """TTL-cached wrapper around _compute_supervision_status — avoids shelling
    out to pm2/netstat on every /health/full or /health/supervision hit."""
    now = time.monotonic()
    payload = _supervision_cache["payload"]
    if payload is not None and (now - _supervision_cache["checked_at"]) < _SUPERVISION_CACHE_TTL_SEC:
        return payload

    fresh = await _compute_supervision_status()
    _supervision_cache["payload"] = fresh
    _supervision_cache["checked_at"] = now
    return fresh


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

    A transient post-port-open failure (connecting/degraded) within
    _TV_MCP_GRACE_TTL_SEC of the last genuinely-good probe is masked and reported
    as the last-known-good state instead — see the P1.6 comment above the cache
    declarations. `not_running` is never masked; it always reports immediately.
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
        # Steady, expected condition (Amo doesn't always run TV Desktop) — report
        # it immediately and drop any stale grace memory from a prior session.
        details = "port 9222 not listening — TV Desktop is not running"
        _tv_mcp_health_cache.update(
            checked_at=now, healthy=False, details=details, status="not_running"
        )
        _tv_mcp_last_good.update(at=0.0, details=None)
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

    if healthy:
        _tv_mcp_last_good.update(at=now, details=None)
    elif now - _tv_mcp_last_good.get("at", 0.0) < _TV_MCP_GRACE_TTL_SEC:
        # Port is open (TV Desktop IS running) but this one probe failed, and we
        # had a real success inside the grace window — treat it as a blip, not a
        # real outage, so top-line health doesn't flap on it. Preserve the raw
        # failure in `details` so it's still observable, just not alarm-worthy.
        details = f"CDP transient blip masked by grace cache (raw: {details})"
        healthy, status = True, "healthy"

    _tv_mcp_health_cache.update(checked_at=now, healthy=healthy, details=details, status=status)
    return healthy, details, status


async def _tv_mcp_background_refresh_loop() -> None:
    """Keep the TV-MCP health cache warm off the request path.

    Probes at _TV_MCP_REFRESH_INTERVAL_SEC (faster than _TV_MCP_CACHE_TTL_SEC) so
    a /health request almost always hits an already-warm cache entry instead of
    making a blocking urllib call inline on the event loop. Runs forever once
    started; exceptions from a single probe are swallowed (best effort) so one
    bad probe never kills the loop.
    """
    while True:
        try:
            await asyncio.to_thread(_check_tradingview_mcp_health)
        except Exception as exc:  # pragma: no cover - defensive, probe itself never raises
            logger.debug("tv_mcp background refresh failed: %s", exc)
        await asyncio.sleep(_TV_MCP_REFRESH_INTERVAL_SEC)


def _ensure_tv_mcp_background_refresher() -> None:
    """Start the TV-MCP background refresher once, idempotently.

    Safe to call on every /health request (e.g. from _health_inner) — a no-op
    after the first successful start. health_router is a plain APIRouter with no
    lifespan hook of its own, so the task is started lazily on first use instead
    of at app startup. Never raises; if there is no running event loop (e.g. a
    sync test context) it silently skips.
    """
    global _tv_mcp_refresher_task
    if _tv_mcp_refresher_task is not None and not _tv_mcp_refresher_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _tv_mcp_refresher_task = loop.create_task(_tv_mcp_background_refresh_loop())
    except RuntimeError:
        pass


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
        # Bounded: health_check() has no internal timeout of its own, so with IB
        # Gateway down (wrong port, not logged in, dead process) this can block on
        # the connector's internal connect timeout -- observed 30s+ hang 2026-08-03,
        # which stalls /health, /health/full, and /ib/connection-test outright.
        # A bounded, degraded read beats an unusable liveness signal.
        try:
            health = await asyncio.wait_for(ib_gw.health_check(), timeout=3.0)
        except asyncio.TimeoutError:
            health = {"status": "timeout", "error": "health_check exceeded 3s budget"}
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

    # Data-leg round-trip verification, independent of which connector `ib_gw`
    # resolved to above -- the shallow `_ib_is_connected()` flag stays True
    # through a wedge (socket open, API dead), which is exactly what let
    # `ibkr_data_connected` report true for hours during the 2026-08-15
    # incident. `data_ib.health_check()` now does a bounded round-trip probe
    # (`data/market_data.py`); consult it here instead of trusting the shallow
    # flag alone. Bounded + best-effort: any failure here silently keeps the
    # pre-existing shallow signal rather than 500ing /health. Only probes when
    # the shallow flag is already True — no wedge to detect otherwise.
    if data_connected and data_ib is not None and hasattr(data_ib, "health_check"):
        try:
            data_probe = await asyncio.wait_for(data_ib.health_check(), timeout=3.0)
            if "connected" in data_probe:
                data_connected = bool(data_probe["connected"])
        except Exception:
            pass

    health["execution_connected"] = execution_connected
    health["data_connected"] = data_connected
    # A2: surface broker-probe honesty. health_check() sets these; the no-
    # health_check fallback (and a fully-disconnected broker) defaults to safe
    # values so a disconnected paper broker does NOT read as "degraded".
    health.setdefault("broker_probe_ok", execution_connected or data_connected)
    health.setdefault("degraded_reason", None)

    # Data-leg observability — which tier is actually serving data, and the
    # auto-reconnect watchdog state, so silent degrade is visible (north-star).
    if data_manager is not None:
        health["data_source"] = getattr(data_manager, "_last_bar_source", None)
        health["last_ibkr_data_ts"] = getattr(data_manager, "_last_ibkr_data_ts", None)
        # Per-symbol staleness: {symbol: seconds_since_last_served}. Empty until
        # the first serve; absent only on an older engine build (defensive read).
        freshness_fn = getattr(data_manager, "symbol_freshness", None)
        if callable(freshness_fn):
            try:
                health["per_symbol_freshness"] = freshness_fn()
            except Exception:
                pass
        wd = getattr(data_manager, "_watchdog", None)
        if wd is not None:
            try:
                health["watchdog"] = wd.status()
            except Exception:
                pass

    return health



# P3-1 (roadmap-drain): this was a bare `10` with no citation, wildly tighter
# than the tolerance the system actually enforces -- a source 15-30s old (a
# normal blip, well within bounds) read "stale" here while the real-money-
# readiness gate (gates.py FEED_STALE_SEC) and every dashboard consumer of
# this endpoint's `status` field treated 900s as the honest fresh/stale line.
# Two disagreeing staleness lies for the same underlying data is the bug this
# closes -- match the one place that threshold is actually decided, so the
# badge Amo looks at and the gate that decides fundability agree.
DATA_INTEGRITY_STALE_AFTER_S = 900.0

# P3-1 (roadmap-drain, actual): /system/data-integrity above reports staleness
# but never affected /health's own `status` -- a `market:latest:MES` entry
# could go stale (or the whole Redis fabric could die) for days with /health
# still reading "ok". Reuses the SAME 900s threshold as /system/data-integrity
# (not a third, divergent number) so /health and the readiness gate agree.
MARKET_DATA_STALE_AFTER_S = DATA_INTEGRITY_STALE_AFTER_S


@router.get("/system/data-integrity")
async def get_data_integrity():
    """
    Returns real-time data freshness metrics from Redis.
    Pattern: datasource:*:last_update
    """
    try:
        import redis.asyncio as redis

        r = redis.from_url(
            settings.REDIS_URL or "redis://localhost:6379/0",
            decode_responses=True,
            socket_connect_timeout=3.0,
            socket_timeout=3.0,
        )

        keys = await r.keys("datasource:*:last_update")
        results = []
        now = datetime.now(timezone.utc)

        for key in keys:
            val = await r.get(key)
            try:
                last_update = datetime.fromisoformat(val)
                latency = (now - last_update).total_seconds()
                results.append(
                    {
                        "source": key.replace("datasource:", "").replace(":last_update", ""),
                        "last_update": val,
                        "latency_sec": round(latency, 2),
                        "status": "healthy" if latency < DATA_INTEGRITY_STALE_AFTER_S else "stale",
                    }
                )
            except Exception:
                continue

        await r.close()
        return {"timestamp": now.isoformat(), "sources": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Data integrity check failed: {e}")
        return {"error": str(e), "sources": [], "count": 0}


@router.get(
    "/health",
    response_model=HealthResponse,
    description="Quick health check endpoint returning system status, database connectivity, and kill switch state.",
)
async def health():
    """Quick health check endpoint"""
    try:
        return await _health_cached()
    except Exception as exc:
        logger.exception("Health endpoint error: %s", exc)
        raise HTTPException(status_code=503, detail=f"Health check failed: {exc}") from exc


async def _health_inner() -> dict:
    safety = safety_layer.get_status() if safety_layer else {}

    db_ok = False
    try:
        if db_manager:
            # Cheap liveness (SELECT 1), not the 8-COUNT(*) health_check whose counts
            # /health discards — and run it off the event loop so even the once-per-
            # TTL cache-miss recompute can't block the async loop under contention.
            # DatabaseManager opens a fresh connection per call, so to_thread is safe.
            await asyncio.to_thread(db_manager.ping)
            db_ok = True
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    ib_health = await _get_ib_gateway_health()

    llm_path_healthy = True
    llm_path_details: dict = {}
    llm_providers: dict = {}
    vertex_failover_count = 0
    google_fallback_count = 0
    try:
        from llm.client import get_llm_path_state, get_llm_provider_summary

        llm_state = get_llm_path_state()
        llm_path_healthy = bool(llm_state.get("healthy", True))
        vertex_failover_count = int(llm_state.get("vertex_failover_count", 0) or 0)
        google_fallback_count = int(llm_state.get("google_fallback_count", 0) or 0)
        if not llm_path_healthy:
            llm_path_details = {
                "last_failure_ts": llm_state.get("last_failure_ts"),
                "last_failure_agent": llm_state.get("last_failure_agent"),
                "last_failure_reason": llm_state.get("last_failure_reason"),
            }
        # Provider-redundancy: which leg is serving + whether one failure goes dark.
        llm_providers = get_llm_provider_summary()
    except Exception:
        # If the client module hasn't been imported yet, assume healthy
        pass

    _ensure_tv_mcp_background_refresher()
    tv_mcp_healthy, tv_mcp_details, tv_mcp_status = _check_tradingview_mcp_health()
    ibgateway_alive, ibgateway_port = _check_ibgateway_alive()

    # Execution-connector honesty. `ibkr_execution_connected` comes from the
    # execution connector's *cached* `is_connected` boolean (execution/
    # ib_gateway_connector.py `_connected`) which is NOT reconciled against the
    # live port probe — in paper mode it stays True even after the Gateway logs
    # out, so /health can report execution-ready while `ibgateway_alive=false`.
    # That stale True is the 2026-06-01 stop-enforcement-believed-connected class.
    # Surface a reconciled truth (AND the live port probe) plus an explicit stale
    # flag so consumers (stop enforcement, dashboard trust-pane) key off verified
    # state, not the cached belief. Raw field kept for back-compat. Paging on a
    # logged-out Gateway is already handled by IBDataWatchdog's notify_ib_disconnect;
    # this only stops /health from *lying*, it does not re-alert.
    _exec_connected_raw = bool(ib_health.get("execution_connected", False))
    execution_connected_verified = _exec_connected_raw and bool(ibgateway_alive)
    ib_execution_stale = _exec_connected_raw and not bool(ibgateway_alive)

    # Approval-queue visibility: a candidate that queues but is never approved
    # (e.g. because outbound notifications are silently failing) stalls the whole
    # live-fill path. Surface count + oldest age so a stuck queue is observable.
    pending_approvals = {"count": 0, "oldest_age_min": None}
    try:
        if db_manager:
            stats = await asyncio.to_thread(db_manager.get_pending_approval_stats)
            oldest = stats.get("oldest_created_at")
            age_min = None
            if oldest:
                try:
                    ots = datetime.fromisoformat(str(oldest).replace("Z", "+00:00"))
                    if ots.tzinfo is None:
                        ots = ots.replace(tzinfo=timezone.utc)
                    age_min = round((now - ots).total_seconds() / 60.0, 1)
                except Exception:
                    age_min = None
            pending_approvals = {"count": int(stats.get("count", 0)), "oldest_age_min": age_min}
    except Exception:
        pass

    # Futures-sentiment freshness: Corey #market-updates is the SOLE sanctioned
    # futures-sentiment source; its feed has silently frozen before (revoked
    # Discord token). Surface age + quality so a stale feed is observable.
    #
    # Both underlying reads (get_futures_sentiment_staleness, get_bias_extraction_
    # health) open a synchronous sqlite3 connection and run a query — offload via
    # asyncio.to_thread like the db_manager calls above so a cache-miss health
    # check can't block the event loop on SQLite I/O (SOTA plan P0.5).
    futures_sentiment = {"quality": "unknown", "age_days": None}
    try:

        def _fetch_futures_sentiment_sync() -> dict:
            from discord.commentary_processor import (
                get_bias_extraction_health,
                get_futures_sentiment_staleness,
            )

            st = get_futures_sentiment_staleness()
            ext = get_bias_extraction_health()
            return {
                "quality": st.get("quality", "unknown"),
                "age_days": st.get("age_days"),
                "latest_timestamp": st.get("latest_timestamp"),
                "threshold_days": st.get("threshold_days"),
                # LLM structured-bias extraction health — distinct from the ingestion
                # freshness above. 'degraded' = extraction has fallen behind commentary
                # (e.g. the 2026-06-29 Anthropic credit-exhaustion outage that ran two
                # days undetected because ingestion still looked fresh). Cache-only —
                # no LLM call. Surfaced as a field; does not flip top-level status
                # (the live engine has its own Vertex-backed extraction path).
                "extraction_quality": ext.get("extraction_quality", "unknown"),
                "extraction_lag_days": ext.get("lag_days"),
                "latest_bias_date": ext.get("latest_bias_date"),
            }

        futures_sentiment = await asyncio.to_thread(_fetch_futures_sentiment_sync)
    except Exception:
        pass

    # Batch jobs (Anthropic Message Batches). Non-blocking observability only —
    # batches are async by design, so this never contributes to `status` below.
    # get_batch_health_summary() does sync sqlite3 I/O, so offload it like the
    # other DB-backed reads above.
    batch_jobs_health: dict = {}
    try:
        from llm.batch_client import JarvisBatchClient

        batch_jobs_health = await asyncio.to_thread(
            JarvisBatchClient().get_batch_health_summary
        )
    except Exception:
        pass

    # Market-data freshness (P3-1): a `market:latest:{symbol}` Redis fabric
    # entry that goes stale (or the whole fabric dying) previously had zero
    # effect on /health -- this endpoint would read "ok" indefinitely while
    # the badge fed from this same source silently served an old price.
    # Checked only for the currently-authorized/tradeable symbol set (derives
    # from the single canonical backtest.signals authority, never a hardcoded
    # list here) so a halted instrument's dead feed can't page anyone.
    market_data_fresh = True
    market_data_stale_symbols: list[str] = []
    try:
        from backtest.signals import DO_NOT_TRADE_SYMBOLS, TREND_INSTRUMENTS

        active_symbols = sorted(TREND_INSTRUMENTS - DO_NOT_TRADE_SYMBOLS)
        if data_manager is not None and active_symbols:
            freshness = await data_manager.check_redis_fabric_freshness(
                active_symbols, stale_after_s=MARKET_DATA_STALE_AFTER_S
            )
            market_data_stale_symbols = sorted(
                sym for sym, v in freshness.items() if v.get("stale")
            )
            market_data_fresh = not market_data_stale_symbols
    except Exception:
        # Can't prove it's stale -- and this signal is defense-in-depth on top
        # of ibgateway_alive/tv_mcp_healthy/llm_path_healthy, not the only
        # liveness signal /health has. Fail open here, not closed.
        pass

    # A2 (branch 1353bdb): a broker that reports connected but whose RPC probes
    # failed is "degraded", not "ok" — it must not read green with
    # latency=null/net_liq=0. A fully-disconnected broker (no `connected` key)
    # is the known paper-hours state and does NOT degrade /health here.
    broker_degraded = bool(ib_health.get("connected")) and not ib_health.get(
        "broker_probe_ok", True
    )
    status = (
        "ok"
        if (
            db_ok
            and llm_path_healthy
            and market_data_fresh
            and not broker_degraded
        )
        else "degraded"
    )

    # Defensive read: a config missing this flag must never report live trading
    # (default False = paper). Also keeps /health resilient to a settings object
    # of an unexpected shape rather than 503-ing the whole endpoint.
    live_trading = bool(getattr(settings, "LIVE_TRADING_ENABLED", False))

    response = {
        "status": status,
        "version": "1.1.0",
        "timestamp": now.isoformat(),
        "live_trading": live_trading,
        # SafetyLayer.get_status() exposes the kill-switch state under "is_killed";
        # there is no "kill_switch_active" key, so the old read silently defaulted to
        # False ALWAYS — /health reported the switch OFF even when trading was halted,
        # and every dashboard widget reading health.kill_switch_active showed green.
        "kill_switch_active": safety.get("is_killed", False),
        "paper_mode": not live_trading,
        "database": "connected" if db_ok else "error",
        "ibkr_connected": ib_health.get("status") == "connected",
        "ibkr_execution_connected": ib_health.get("execution_connected", False),
        # Reconciled against the live port probe — the field consumers should trust.
        "execution_connected_verified": execution_connected_verified,
        # True when the connector believes it's connected but the Gateway port is
        # dead (logged out) — a silent stop-enforcement hazard made observable.
        "ib_execution_stale": ib_execution_stale,
        "ibkr_data_connected": ib_health.get("data_connected", False),
        "ibkr_broker_probe_ok": ib_health.get("broker_probe_ok", True),
        "ibkr_degraded_reason": ib_health.get("degraded_reason"),
        "ibgateway_alive": ibgateway_alive,
        "ibgateway_port": ibgateway_port,
        "schwab_connected": bool(schwab_connector and schwab_connector.is_connected),
        "uptime_seconds": (now - _start_time).total_seconds() if _start_time else 0.0,
        "llm_available": True,
        "llm_path_healthy": llm_path_healthy,
        "llm_providers": llm_providers,
        "vertex_failover_count": vertex_failover_count,
        "google_fallback_count": google_fallback_count,
        "tradingview_mcp_healthy": tv_mcp_healthy,
        "tv_mcp_status": tv_mcp_status,
        "brier_30d_rolling": _compute_brier_30d_rolling(),
        "pending_approvals": pending_approvals,
        "futures_sentiment": futures_sentiment,
        "batch_jobs_health": batch_jobs_health,
        "market_data_fresh": market_data_fresh,
        "market_data_stale_symbols": market_data_stale_symbols,
    }
    if llm_path_details:
        response["llm_path_details"] = llm_path_details
    if tv_mcp_details:
        response["tradingview_mcp_details"] = tv_mcp_details
    return response


# MR-3.6 (roadmap-drain): a real subsystem probe backs every assertion below --
# this derives from the same _health_cached() payload /health itself returns,
# not a second set of re-probed values, so it can never disagree with /health
# about the same underlying reality (see P3-1's fix, same failure class: two
# signals for one truth drifting apart). A stuck-pending-approval hazard has
# no documented threshold anywhere else in the codebase; 60 minutes is a
# first-pass value chosen here, not derived from an existing constant --
# revisit if it proves too tight/loose in practice.
PENDING_APPROVAL_STUCK_AFTER_MIN = 60.0


def _derive_health_assertions(health: dict) -> list[dict]:
    """Reduce the rich /health payload to named pass/fail assertions.

    Absence of evidence fails closed, not open -- mirrors gates.py's own
    "UNKNOWN counts as NO-GO" philosophy (real-money-readiness loop) rather
    than inventing a third truth value here.
    """
    pending = health.get("pending_approvals") or {}
    oldest_age_min = pending.get("oldest_age_min")
    sentiment = health.get("futures_sentiment") or {}
    brier = health.get("brier_30d_rolling")

    checks: list[tuple[str, bool, str]] = [
        (
            "database_connected",
            health.get("database") == "connected",
            f"database={health.get('database')}",
        ),
        (
            "kill_switch_inactive",
            not health.get("kill_switch_active", True),
            f"kill_switch_active={health.get('kill_switch_active')}",
        ),
        (
            "ib_gateway_alive",
            bool(health.get("ibgateway_alive")),
            f"ibgateway_alive={health.get('ibgateway_alive')}",
        ),
        (
            "ib_execution_not_stale",
            not health.get("ib_execution_stale", False),
            "cached-connected but Gateway port is dead"
            if health.get("ib_execution_stale")
            else "verified or genuinely disconnected",
        ),
        (
            "llm_path_healthy",
            bool(health.get("llm_path_healthy")),
            f"llm_path_healthy={health.get('llm_path_healthy')}",
        ),
        (
            "tradingview_mcp_healthy",
            bool(health.get("tradingview_mcp_healthy")),
            f"tradingview_mcp_healthy={health.get('tradingview_mcp_healthy')}",
        ),
        (
            "no_stuck_pending_approvals",
            oldest_age_min is None or oldest_age_min < PENDING_APPROVAL_STUCK_AFTER_MIN,
            f"oldest_age_min={oldest_age_min} (count={pending.get('count', 0)})",
        ),
        (
            "forecasts_beat_coinflip",
            brier is not None and brier < 0.25,
            f"brier_30d_rolling={brier}" if brier is not None else "no rolling Brier data yet",
        ),
        (
            "futures_sentiment_fresh",
            sentiment.get("quality") == "fresh",
            f"quality={sentiment.get('quality')} age_days={sentiment.get('age_days')}",
        ),
        (
            "execution_path_verified",
            bool(health.get("execution_connected_verified")),
            f"execution_connected_verified={health.get('execution_connected_verified')}",
        ),
    ]
    return [{"name": name, "passed": passed, "detail": detail} for name, passed, detail in checks]


@router.get("/health/assertions")
async def get_health_assertions():
    """Single-pane-of-glass health: N named pass/fail assertions, one glance.

    Aggregates the ~10 scattered /health* and /system/* routes this project
    has accumulated (data-integrity, execution status, LLM path, TV MCP,
    kill switch, pending approvals, Brier calibration, futures sentiment)
    into one list a dashboard badge or Amo can read without cross-referencing
    endpoints by hand. Every assertion maps to a real probe already computed
    by /health -- this is a read-only reshape, not a new probe surface.
    """
    health = await _health_cached()
    assertions = _derive_health_assertions(health)
    failed = [a["name"] for a in assertions if not a["passed"]]
    return {
        "timestamp": health.get("timestamp"),
        "all_passed": len(failed) == 0,
        "failed": failed,
        "assertions": assertions,
    }


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

    # Delegate to the shared, lock-guarded reconnect so this route and the
    # IBDataWatchdog never rebuild two IB() sockets on the same clientId at once.
    connected = await data_manager.reconnect_ibkr(timeout=15.0)

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


# GT-51 ordering-bug fix. Each subsystem check below used to escalate `overall`
# with its own `if overall == "healthy": overall = <state>` guard. That pattern
# is only safe if every check that can set a *more* severe state always runs
# *before* every check that can set a *less* severe one — which stopped being
# true the moment `ib_gateway` (step 3, escalates to "degraded") started
# running ahead of `circuit_breakers` (step 4, escalates to
# "circuit_breaker_tripped"): an ib_gateway exception flipped overall to
# "degraded" first, so circuit_breakers's `== "healthy"` guard went false and
# a real circuit-breaker trip could never escalate past "degraded" — silently
# downgrading a more actionable trading-safety state. Rank-based escalation
# fixes this for the current order AND makes any future reordering of these
# checks safe by construction: a candidate state only ever wins if it is
# strictly more severe than whatever is already recorded, regardless of which
# check ran first.
_OVERALL_SEVERITY = {
    "healthy": 0,
    "degraded": 1,
    "circuit_breaker_tripped": 2,
    "kill_switch_active": 3,
}


def _escalate_overall(current: str, candidate: str) -> str:
    """Return whichever of `current`/`candidate` is the more severe `overall` state.

    Unknown state strings rank as 0 (== "healthy") so a typo'd/legacy value
    can't accidentally block a real escalation.
    """
    if _OVERALL_SEVERITY.get(candidate, 0) > _OVERALL_SEVERITY.get(current, 0):
        return candidate
    return current


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
            overall = _escalate_overall(overall, "degraded")
    except Exception as e:
        status["database"] = {"status": "error", "error": str(e)}
        overall = _escalate_overall(overall, "degraded")

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
                overall = _escalate_overall(overall, "kill_switch_active")
        else:
            status["safety_layer"] = {"status": "not_initialized"}
            overall = _escalate_overall(overall, "degraded")
    except Exception as e:
        status["safety_layer"] = {"status": "error", "error": str(e)}
        overall = _escalate_overall(overall, "degraded")

    # 3. IB Gateway (optional)
    try:
        status["ib_gateway"] = await _get_ib_gateway_health()
    except Exception as e:
        status["ib_gateway"] = {"status": "error", "error": str(e)}
        overall = _escalate_overall(overall, "degraded")

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
                overall = _escalate_overall(overall, "circuit_breaker_tripped")
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
        overall = _escalate_overall(overall, "degraded")

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
        overall = _escalate_overall(overall, "degraded")

    # 7. LLM path — which provider is serving + whether we're on a fallback leg.
    # Sustained gemini/openai fallback has been a recurring silent degrade, so
    # surface provider + fallback_active here for the dashboard badge. Reuses the
    # existing llm.client snapshot helpers (no new LLM logic). Defensive: any
    # failure yields status "unknown" rather than degrading the whole endpoint.
    try:
        from llm.client import get_llm_path_state, get_llm_provider_summary

        path_state = get_llm_path_state()
        summary = get_llm_provider_summary()
        healthy = bool(path_state.get("healthy", True))
        active = summary.get("active_provider")
        primary = summary.get("primary_provider")
        provider = active or primary
        fallback_active = active is not None and primary is not None and active != primary
        llm_status = "degraded" if (not healthy or fallback_active) else "ok"
        status["llm"] = {
            "status": llm_status,
            "provider": provider,
            "fallback_active": fallback_active,
            "healthy": healthy,
            "primary_provider": primary,
            "active_provider": active,
            "providers_available": summary.get("providers_available"),
            "single_leg_warning": summary.get("single_leg_warning", False),
            "google_fallback_count": int(path_state.get("google_fallback_count", 0) or 0),
            "vertex_failover_count": int(path_state.get("vertex_failover_count", 0) or 0),
        }
        if llm_status == "degraded":
            overall = _escalate_overall(overall, "degraded")
    except Exception as e:
        status["llm"] = {"status": "unknown", "error": str(e)}

    # 8. Process supervision cross-check (PRB-24) — pm2 belief vs TCP-port
    # reality for jarvis-engine/jarvis-dashboard/jarvis-bridge-api. Reuses the
    # 30s-cached compute so /health/full never adds its own extra pm2/netstat
    # shell-out latency. supervision_ok=False (a real mismatch) escalates
    # overall to "degraded" — unavailable (pm2 not on PATH) does not, since
    # that's an environment fact, not a live incident.
    try:
        supervision = await _supervision_cached()
        ok = supervision.get("supervision_ok")
        sup_status = "ok" if ok else ("unavailable" if ok is None else "mismatch")
        status["process_supervision"] = {"status": sup_status, "details": supervision}
        if ok is False:
            overall = _escalate_overall(overall, "degraded")
    except Exception as e:
        status["process_supervision"] = {"status": "error", "error": str(e)}

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


def classify_pm2_one_shot(pm2_env: dict) -> bool:
    """True iff this pm2 app is a one-shot cron job, not a long-lived daemon.

    (Phase 4.4 / P4-4) A pm2 app configured with `cron_restart` + `autorestart:
    false` is DESIGNED to sit `status: "stopped"` between cron fires — that is
    its correct idle state, not a failure. `jarvis-health-check`,
    `jarvis-morning-brief`, `jarvis-eod-summary`, `jarvis-rolling-wfe`,
    `jarvis-weekly-tearsheet`, `jarvis-discord-export`, the `jarvis-vault-*`
    jobs, and `down-alert` are all this shape (see engine/ecosystem.config.js).
    Naively reading raw pm2 `status` for these produces a false "X is dead"
    report — confirmed 2026-08-01 for `down-alert` (it was healthy the whole
    time; its log showed `OK (HTTP 200)` every minute while pm2 correctly
    reported `stopped` between cron fires). Any consumer of pm2 status for a
    one-shot app must check log recency instead of `status == "online"`.
    """
    return bool(pm2_env.get("cron_restart")) and pm2_env.get("autorestart") is False


def _log_age_seconds(log_path: str | None) -> float | None:
    """Seconds since `log_path` was last written, or None if missing/unreadable.

    Pure/cheap (single stat call) so it's safe to call per-request without a
    cache — mirrors the mtime-staleness check down-alert-watchdog/run.ps1
    already uses for down-alert.mjs specifically; this generalizes the same
    pattern to any pm2 app so future watchdogs don't have to reinvent it.
    """
    if not log_path:
        return None
    try:
        return max(0.0, time.time() - os.path.getmtime(log_path))
    except OSError:
        return None


@router.get(
    "/health/pm2",
    description="pm2 process status for a named app (default jarvis-engine) — "
    "restart count, uptime, memory, and one-shot/log-recency classification "
    "for cron_restart apps so callers don't misread a correctly-idle "
    "one-shot job's pm2 `status:stopped` as dead (Phase 4.4).",
)
async def pm2_status(name: str = "jarvis-engine"):
    """Query pm2 for `name`'s process stats. Returns empty on non-pm2 deployments.

    For a one-shot app (`cron_restart` set + `autorestart:false`), `status`
    alone does NOT indicate health — `stopped` is its correct resting state
    between cron fires. Callers must use `is_one_shot` + `log_age_seconds`
    (how long since its log file last got a write) rather than
    `status == "online"` to judge whether it's actually dead vs. just idle.
    """
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
            if p.get("name") == name:
                monit = p.get("monit", {})
                pm2_env = p.get("pm2_env", {})
                is_one_shot = classify_pm2_one_shot(pm2_env)
                log_path = pm2_env.get("pm_out_log_path")
                return {
                    "found": True,
                    "status": pm2_env.get("status"),
                    "restart_count": pm2_env.get("restart_time", 0),
                    "unstable_restarts": pm2_env.get("unstable_restarts", 0),
                    "uptime_ms": pm2_env.get("pm_uptime"),
                    "memory_mb": round(monit.get("memory", 0) / 1_048_576, 1),
                    "cpu_pct": monit.get("cpu", 0),
                    "pid": p.get("pid"),
                    # One-shot classification (Phase 4.4) — a one-shot app sitting
                    # "stopped" is HEALTHY, not dead. Consumers must gate any
                    # "is this dead" verdict on is_one_shot before trusting
                    # status == "online"; for one-shot apps, check log recency
                    # (log_age_seconds) against that app's own cron cadence instead.
                    "is_one_shot": is_one_shot,
                    "cron_restart": pm2_env.get("cron_restart"),
                    "log_path": log_path,
                    "log_age_seconds": _log_age_seconds(log_path),
                }
        return {"found": False, "note": f"{name} not found in pm2 list"}
    except Exception as exc:
        return {"found": False, "error": str(exc)}


@router.get(
    "/health/supervision",
    description="Cross-check pm2's believed process state against actual TCP "
    "port liveness and the real port-owner PID (PRB-24). Never raises — pm2 "
    "unavailable degrades to available=false rather than a 500.",
)
async def health_supervision():
    """pm2-vs-reality process supervision cross-check.

    Independently probes each supervised app's TCP port and (when the port is
    live) the actual owning PID via `netstat -ano`, then compares against
    pm2's believed status+pid from `pm2 jlist`. A MISMATCH — pm2 says one
    thing, the OS says another — is the specific failure class from the
    2026-07-28/29 incidents (an orphan process serving a port pm2 thinks is
    dead, or pm2 believing a port is up when nothing is actually listening).
    """
    try:
        return await _supervision_cached()
    except Exception as exc:
        logger.exception("health/supervision endpoint error: %s", exc)
        return {
            "available": False,
            "supervision_ok": None,
            "error": f"supervision check crashed: {exc}",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "apps": {},
        }


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
    "/health/predictive",
    description=(
        "Predictive maintenance: latest degradation score, signal breakdown, "
        "and last-hour sample history. Returns 501 when ENABLE_PREDICTIVE_MAINTENANCE=0."
    ),
)
async def health_predictive():
    """
    Return the most recent predictive-maintenance sample + degradation score.

    Degradation score components (each 0.0–1.0, weighted sum ≤ 1.0):
      memory_growth_rate  0.30
      ib_reconnect_spike  0.30
      llm_latency_creep   0.20
      pm2_restart_delta   0.20

    Requires ENABLE_PREDICTIVE_MAINTENANCE=1 to return live data.
    """
    from fastapi.responses import JSONResponse

    try:
        from monitoring.predictive_maintenance import (
            HealthMonitor,
            is_predictive_maintenance_enabled,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail=f"predictive_maintenance not importable: {exc}"
        ) from exc

    if not is_predictive_maintenance_enabled():
        return JSONResponse(
            status_code=501,
            content={
                "enabled": False,
                "note": (
                    "Predictive maintenance is disabled. "
                    "Set ENABLE_PREDICTIVE_MAINTENANCE=1 in .env to activate."
                ),
            },
        )

    # Collect a fresh sample for the response (lightweight — does not advance the loop)
    monitor = HealthMonitor()
    try:
        sample = await monitor.sample_now()
    except Exception as exc:
        logger.warning("health/predictive: sample_now failed: %s", exc)
        sample = {}

    score = monitor.degradation_score(sample, [])
    history_summary = monitor.get_history_summary()

    return {
        "enabled": True,
        "degradation_score": score,
        "threshold": monitor.score_threshold,
        "alert_only": not bool(
            __import__("os").environ.get("PREDICTIVE_MAINTENANCE_ALLOW_RESTART", "0").strip() == "1"
        ),
        "latest_sample": sample,
        "history_summary": history_summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


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


@router.get("/ib/connection-test")
async def ib_connection_test():
    """Live IB connection probe for the dashboard connection cards.

    Shape consumed by ConnectionHealthCard / IbGatewayDetailCard /
    IBGatewayStatus: {connected, port, mode, latency_ms, account_id, error}.
    """
    import time as _time

    start = _time.perf_counter()
    try:
        health = await _get_ib_gateway_health()
    except Exception as exc:
        return {
            "connected": False,
            "port": None,
            "mode": "unknown",
            "latency_ms": None,
            "account_id": None,
            "error": str(exc),
        }
    connected = bool(health.get("execution_connected") or health.get("data_connected"))

    execution_ib = getattr(safety_layer, "_ib_gateway", None) if safety_layer else None
    data_ib = data_manager.ibkr if data_manager else None
    ib_gw = execution_ib or data_ib

    port = next(
        (v for v in (getattr(ib_gw, a, None) for a in ("port", "_port")) if isinstance(v, int)),
        None,
    )
    if port is None and connected:
        # Some connector instances expose connection state but not their port. The
        # live TCP probe is the authoritative paper/live boundary already used by
        # /health, so only backfill the dashboard-facing port when that probe is
        # currently alive. This avoids connected=true/port=null ambiguity without
        # overstating a dead gateway as usable.
        try:
            alive, probed_port = _check_ibgateway_alive()
            if alive and isinstance(probed_port, int):
                port = probed_port
        except Exception:
            pass
    latency_ms = round((_time.perf_counter() - start) * 1000.0, 1)
    account_id = next(
        (
            v
            for v in (getattr(ib_gw, a, None) for a in ("account_id", "_account_id", "account"))
            if isinstance(v, str) and v
        ),
        None,
    )
    mode = (
        "paper" if port == 4002 else "live" if port == 4001 else str(health.get("mode", "unknown"))
    )
    return {
        "connected": connected,
        "port": port,
        "mode": mode,
        "latency_ms": latency_ms,
        "account_id": account_id,
        "error": None if connected else str(health.get("status", "disconnected")),
    }
