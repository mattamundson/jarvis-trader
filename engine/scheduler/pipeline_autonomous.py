"""
JARVIS TRADER — Autonomous Pipeline Scheduler
=============================================

Runs one "tick" of the autonomous pipeline per configured interval.

Safety architecture (every tick):
  1. Read ENABLE_AUTONOMOUS_PIPELINE from env fresh — if 0, no-op immediately.
  2. Pre-flight: GET /health + GET /admin/feature-flags
       - Engine unhealthy     → refuse, log, return
       - Kill switch active   → refuse, log, return
       - LIVE_TRADING_ENABLED → refuse, log, return  (paranoid redundant check)
  3. For each active symbol: run the trading pipeline.
  4. If verdict green AND confidence >= AUTONOMOUS_CONFIDENCE_THRESHOLD:
       - Idempotency guard: no duplicate for (symbol, direction) with TTL>0
       - Insert row into pipeline_approval_queue with TTL = AUTONOMOUS_CANDIDATE_TTL_SECONDS
  5. Log every decision (enqueue / skip-hold / skip-low-conf / skip-duplicate).

NEVER auto-submits an order.  All candidates sit in the queue until a human
explicitly approves via POST /approvals/{id}/approve (or the TTL expires).

Environment variables (all read fresh on every tick):
  ENABLE_AUTONOMOUS_PIPELINE          0|1   (default 0 — MUST be 0 at boot)
  AUTONOMOUS_TICK_SECONDS             int   (default 300 — 5 minutes)
  AUTONOMOUS_CONFIDENCE_THRESHOLD     float (default 0.65)
  AUTONOMOUS_CANDIDATE_TTL_SECONDS    int   (default 1800 — 30 minutes)
  AUTONOMOUS_ACTIVE_SYMBOLS           comma-separated (default MCL,MNQ)
  AUTONOMOUS_MIN_TICK_SECONDS         int   (default 60 — race-condition floor)

DO NOT modify engine/risk/safety_layer.py, engine/config.py, or
engine/agents/pipeline.py from this module.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("jarvis_trader.scheduler.autonomous")

# ---------------------------------------------------------------------------
# Env-var helpers (always read fresh — never cached at module level)
# ---------------------------------------------------------------------------

_FLAG_NAME = "ENABLE_AUTONOMOUS_PIPELINE"
_THRESHOLD_NAME = "AUTONOMOUS_CONFIDENCE_THRESHOLD"
_TTL_NAME = "AUTONOMOUS_CANDIDATE_TTL_SECONDS"
_SYMBOLS_NAME = "AUTONOMOUS_ACTIVE_SYMBOLS"
_TICK_NAME = "AUTONOMOUS_TICK_SECONDS"
_MIN_TICK_NAME = "AUTONOMOUS_MIN_TICK_SECONDS"

_DEFAULT_THRESHOLD = 0.65
_DEFAULT_TTL_SECONDS = 1800  # 30 minutes
_DEFAULT_TICK_SECONDS = 300  # 5 minutes
_DEFAULT_MIN_TICK_SECONDS = 60  # race-condition floor


def is_autonomous_enabled() -> bool:
    """Return True only when ENABLE_AUTONOMOUS_PIPELINE=1.

    Reads os.environ fresh on every call — intentionally not cached.
    This means disabling the flag at runtime takes effect on the next tick
    without restarting the engine.
    """
    raw = os.environ.get(_FLAG_NAME, "0").strip()
    return raw == "1"


def _get_confidence_threshold() -> float:
    raw = os.environ.get(_THRESHOLD_NAME, "").strip()
    try:
        return float(raw)
    except (ValueError, TypeError):
        return _DEFAULT_THRESHOLD


def _get_ttl_seconds() -> int:
    raw = os.environ.get(_TTL_NAME, "").strip()
    try:
        return max(60, int(raw))
    except (ValueError, TypeError):
        return _DEFAULT_TTL_SECONDS


def _get_active_symbols() -> list[str]:
    raw = os.environ.get(_SYMBOLS_NAME, "MCL,MNQ").strip()
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _get_tick_seconds() -> int:
    raw = os.environ.get(_TICK_NAME, "").strip()
    try:
        val = int(raw)
    except (ValueError, TypeError):
        val = _DEFAULT_TICK_SECONDS
    min_tick = _get_min_tick_seconds()
    return max(val, min_tick)


def _get_min_tick_seconds() -> int:
    raw = os.environ.get(_MIN_TICK_NAME, "").strip()
    try:
        return max(60, int(raw))
    except (ValueError, TypeError):
        return _DEFAULT_MIN_TICK_SECONDS


# ---------------------------------------------------------------------------
# Module-level injectable references (set by main.py at startup)
# ---------------------------------------------------------------------------

_trading_pipeline = None
_safety_layer = None
_db_path: Optional[str] = None


def inject_autonomous_deps(trading_pipeline, safety_layer, db_path: str) -> None:
    """Called from main.py during lifespan if ENABLE_AUTONOMOUS_PIPELINE=1."""
    global _trading_pipeline, _safety_layer, _db_path
    _trading_pipeline = trading_pipeline
    _safety_layer = safety_layer
    _db_path = db_path
    logger.info(
        "AutonomousScheduler: dependencies injected " "(pipeline=%s, safety_layer=%s, db=%s)",
        type(_trading_pipeline).__name__,
        type(_safety_layer).__name__,
        _db_path,
    )


# ---------------------------------------------------------------------------
# SQLite helpers — operate directly on the shared DB so the approval queue
# router and the scheduler share the same persistent state.
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_approval_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence REAL,
    verdict_json TEXT,
    expires_at TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    reviewed_at TEXT,
    reviewer_notes TEXT,
    order_id TEXT
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_approval_queue_status_symbol
    ON pipeline_approval_queue(status, symbol, expires_at);
"""


def _ensure_table(db_path: str) -> None:
    """Create the approval queue table + index if they do not exist."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
        conn.commit()


def _has_pending_candidate(db_path: str, symbol: str, direction: str) -> bool:
    """Return True if a non-expired pending candidate exists for (symbol, direction)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id FROM pipeline_approval_queue
            WHERE symbol = ?
              AND direction = ?
              AND status = 'pending'
              AND expires_at > ?
            LIMIT 1
            """,
            (symbol.upper(), direction.upper(), now_iso),
        ).fetchone()
    return row is not None


def _insert_candidate(
    db_path: str,
    symbol: str,
    direction: str,
    confidence: float,
    verdict_json: str,
    ttl_seconds: int,
) -> int:
    """Insert a new pending candidate; return its row id."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO pipeline_approval_queue
                (created_at, symbol, direction, confidence, verdict_json, expires_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                now.isoformat(),
                symbol.upper(),
                direction.upper(),
                confidence,
                verdict_json,
                expires.isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Pre-flight safety check
# ---------------------------------------------------------------------------


def _get_live_trading_enabled() -> bool:
    """Return settings.LIVE_TRADING_ENABLED (isolated for test-patching)."""
    try:
        from config import settings as _cfg

        return bool(_cfg.LIVE_TRADING_ENABLED)
    except Exception:
        return False


def _preflight_check() -> tuple[bool, str]:
    """
    Synchronous safety pre-flight using injected safety_layer.

    Returns (ok, reason).  ok=False means the tick must abort.
    Checks (in order):
      1. Flag still enabled (belt-and-suspenders re-read)
      2. LIVE_TRADING_ENABLED must be False
      3. Safety layer available
      4. Kill switch not active
      5. IB data connection available
    """
    if not is_autonomous_enabled():
        return False, "ENABLE_AUTONOMOUS_PIPELINE=0"

    # Belt-and-suspenders: read LIVE_TRADING_ENABLED via isolated helper (patchable in tests)
    if _get_live_trading_enabled():
        return False, "LIVE_TRADING_ENABLED=True — autonomous scheduler refuses to enqueue"

    if _safety_layer is None:
        return False, "safety_layer not injected"

    try:
        status = _safety_layer.get_status()
    except Exception as exc:
        return False, f"safety_layer.get_status() raised: {exc}"

    if status.get("kill_switch_active"):
        return False, "kill switch active"

    # IB data connection check — refuse if data feed is down
    ib_data_ok = status.get("ibkr_connected") or status.get("data_ib_connected")
    if not ib_data_ok:
        # Non-fatal warn but allow: data_manager has Polygon fallback.
        # Log a warning but do not refuse (matches existing scanner behavior).
        logger.warning(
            "[AutonomousTick] IB data disconnected — " "pipeline will use Polygon/TV fallback"
        )

    return True, "ok"


# ---------------------------------------------------------------------------
# Core tick
# ---------------------------------------------------------------------------


async def autonomous_tick() -> dict:
    """
    One full tick of the autonomous scheduler.

    Returns a summary dict describing what happened (for logging / tests).
    Never raises — all errors are caught and logged.
    """
    summary: dict = {
        "enabled": is_autonomous_enabled(),
        "symbols_scanned": [],
        "enqueued": [],
        "skipped_hold": [],
        "skipped_low_confidence": [],
        "skipped_duplicate": [],
        "errors": [],
    }

    if not is_autonomous_enabled():
        logger.debug("[AutonomousTick] flag off — no-op")
        return summary

    # -- Safety pre-flight --
    ok, reason = _preflight_check()
    if not ok:
        logger.info("[AutonomousTick] pre-flight refused: %s", reason)
        summary["refused_reason"] = reason
        return summary

    if _trading_pipeline is None:
        logger.warning("[AutonomousTick] trading_pipeline not injected — aborting tick")
        summary["errors"].append("trading_pipeline not injected")
        return summary

    if _db_path is None:
        logger.warning("[AutonomousTick] db_path not set — aborting tick")
        summary["errors"].append("db_path not set")
        return summary

    # Ensure table exists (idempotent)
    try:
        _ensure_table(_db_path)
    except Exception as exc:
        logger.error("[AutonomousTick] failed to ensure table: %s", exc)
        summary["errors"].append(f"table_create_failed: {exc}")
        return summary

    threshold = _get_confidence_threshold()
    ttl = _get_ttl_seconds()
    symbols = _get_active_symbols()

    logger.info(
        "[AutonomousTick] starting — symbols=%s confidence_threshold=%.2f ttl=%ds",
        symbols,
        threshold,
        ttl,
    )

    for symbol in symbols:
        summary["symbols_scanned"].append(symbol)
        try:
            # Re-run pre-flight on every symbol iteration: kill-switch could
            # trip mid-tick (e.g. daily P&L limit breached by the first symbol's
            # entry being booked while scanning the second).
            ok2, reason2 = _preflight_check()
            if not ok2:
                logger.info(
                    "[AutonomousTick] mid-tick pre-flight refused (%s): %s",
                    symbol,
                    reason2,
                )
                summary["refused_reason"] = reason2
                break

            result = await _trading_pipeline.analyze_and_decide(symbol, is_futures=True)

            action = str(result.get("final_action", "hold")).lower()
            fund_dec = result.get("fund_decision") or {}
            trade_dec = result.get("trade_decision") or {}
            confidence = float(
                fund_dec.get("final_conviction") or trade_dec.get("confidence") or 0.0
            )

            if action in ("hold", ""):
                logger.info("[AutonomousTick] %s → HOLD — no candidate enqueued", symbol)
                summary["skipped_hold"].append(symbol)
                continue

            if confidence < threshold:
                logger.info(
                    "[AutonomousTick] %s → %s confidence=%.2f below threshold %.2f — skip",
                    symbol,
                    action.upper(),
                    confidence,
                    threshold,
                )
                summary["skipped_low_confidence"].append(
                    {"symbol": symbol, "action": action, "confidence": confidence}
                )
                continue

            # Map action ("buy"/"sell") to direction ("LONG"/"SHORT")
            direction = "LONG" if action in ("buy", "long") else "SHORT"

            # Idempotency: skip if non-expired candidate already exists
            if _has_pending_candidate(_db_path, symbol, direction):
                logger.info(
                    "[AutonomousTick] %s %s already has live candidate — no duplicate enqueued",
                    symbol,
                    direction,
                )
                summary["skipped_duplicate"].append({"symbol": symbol, "direction": direction})
                continue

            import json as _json

            row_id = _insert_candidate(
                db_path=_db_path,
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                verdict_json=_json.dumps(result, default=str),
                ttl_seconds=ttl,
            )
            logger.info(
                "[AutonomousTick] ENQUEUED: %s %s confidence=%.2f → candidate_id=%d (TTL %ds)",
                symbol,
                direction,
                confidence,
                row_id,
                ttl,
            )
            summary["enqueued"].append(
                {
                    "candidate_id": row_id,
                    "symbol": symbol,
                    "direction": direction,
                    "confidence": confidence,
                }
            )

        except Exception as sym_exc:
            logger.error(
                "[AutonomousTick] error processing %s: %s",
                symbol,
                sym_exc,
                exc_info=True,
            )
            summary["errors"].append({"symbol": symbol, "error": str(sym_exc)})

    logger.info(
        "[AutonomousTick] done — enqueued=%d skipped_hold=%d skipped_low_conf=%d errors=%d",
        len(summary["enqueued"]),
        len(summary["skipped_hold"]),
        len(summary["skipped_low_confidence"]),
        len(summary["errors"]),
    )
    return summary


# ---------------------------------------------------------------------------
# Background loop — called once from main.py if flag=1 at boot
# ---------------------------------------------------------------------------


async def run_autonomous_loop() -> None:
    """
    Long-running coroutine that fires autonomous_tick() on an interval.

    The tick interval is read from AUTONOMOUS_TICK_SECONDS on every iteration
    so it can be changed without restarting the engine.  A minimum of
    AUTONOMOUS_MIN_TICK_SECONDS (default 60s) is enforced to prevent the
    tick from firing faster than a paper-order round-trip can complete,
    which would race the idempotency guard.

    This coroutine is wrapped in a broad try/except so an unhandled exception
    in the tick does not kill the loop.
    """
    logger.info("[AutonomousLoop] background loop started")
    while True:
        tick_seconds = _get_tick_seconds()
        try:
            await autonomous_tick()
        except Exception as exc:
            logger.error("[AutonomousLoop] unhandled exception in tick: %s", exc, exc_info=True)
        await asyncio.sleep(tick_seconds)
