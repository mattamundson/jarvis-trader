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
_AUTO_APPROVE_PAPER_NAME = "AUTONOMOUS_AUTO_APPROVE_PAPER"

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


def _warn_blocked_active_symbols() -> None:
    """Loud WARN if any AUTONOMOUS_ACTIVE_SYMBOLS member is in
    DO_NOT_TRADE_SYMBOLS. Such a config can never trade (the gate forces
    NO_TRADE), so the autonomous loop silently no-ops on it — exactly the
    MCL,MNQ default, where both symbols are blocked and the loop is
    dead-configured. Fired once at injection so it can't recur silently."""
    try:
        from backtest.signals import DO_NOT_TRADE_SYMBOLS
    except Exception:
        return
    active = _get_active_symbols()
    blocked = [s for s in active if s in DO_NOT_TRADE_SYMBOLS]
    if blocked:
        logger.warning(
            "AUTONOMOUS_ACTIVE_SYMBOLS contains DO_NOT_TRADE symbols %s — the "
            "autonomous loop can never trade these (gated to NO_TRADE). Active "
            "set=%s. Set %s to tradeable symbols (e.g. MES) to activate.",
            blocked,
            active,
            _SYMBOLS_NAME,
        )


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
_data_manager = None


def inject_autonomous_deps(trading_pipeline, safety_layer, db_path: str, data_manager=None) -> None:
    """Called from main.py during lifespan if ENABLE_AUTONOMOUS_PIPELINE=1."""
    global _trading_pipeline, _safety_layer, _db_path, _data_manager
    _trading_pipeline = trading_pipeline
    _safety_layer = safety_layer
    _db_path = db_path
    _data_manager = data_manager
    logger.info(
        "AutonomousScheduler: dependencies injected "
        "(pipeline=%s, safety_layer=%s, db=%s, data_manager=%s)",
        type(_trading_pipeline).__name__,
        type(_safety_layer).__name__,
        _db_path,
        type(_data_manager).__name__ if _data_manager is not None else "None",
    )
    _warn_blocked_active_symbols()


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


def _auto_approve_paper_enabled() -> bool:
    """Read AUTONOMOUS_AUTO_APPROVE_PAPER fresh from env (module convention)."""
    return os.getenv(_AUTO_APPROVE_PAPER_NAME, "0").strip().lower() in ("1", "true", "yes")


async def _maybe_auto_approve_paper(candidate_id: int) -> bool:
    """
    Auto-approve a freshly-enqueued candidate in PAPER mode, if enabled.

    Returns True iff auto-approval was attempted (regardless of the submit
    result), False if the feature is off or live trading is enabled.

    Safety: this is purely a programmatic press of the same approve button a
    human would use — it routes through routers.approval_queue_router.approve_candidate,
    which re-checks the kill switch + live guard, the VALIDATION_ONLY_STRATEGIES
    block, entry-price sanity, and submits via safety_layer.submit_paper_order.
    It NEVER runs when LIVE_TRADING_ENABLED is True, so the autonomous path's
    documented "never auto-submit for live" guarantee is preserved.
    """
    if not _auto_approve_paper_enabled():
        return False
    if _get_live_trading_enabled():  # paranoid redundant guard — never auto-approve live
        logger.warning(
            "[AutonomousTick] AUTO_APPROVE_PAPER set but LIVE_TRADING_ENABLED — refusing (live-safe)."
        )
        return False
    try:
        from routers.approval_queue_router import approve_candidate

        await approve_candidate(candidate_id)
        logger.info("[AutonomousTick] AUTO-APPROVED (paper): candidate %d", candidate_id)
    except Exception as exc:  # never let auto-approve break the tick loop
        logger.warning(
            "[AutonomousTick] auto-approve failed for candidate %d: %s", candidate_id, exc
        )
    return True


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

            # Entry price sanity check — early rejection of corrupted verdicts.
            # Prevents phantom trades (e.g. 2026-05-09: stop_loss copied into entry_price).
            # Runs at enqueue so corrupted candidates never reach the approval queue at all.
            _entry_price_for_check = None
            try:
                _trade_dec = result.get("trade_decision") or {}
                if isinstance(_trade_dec, str):
                    _trade_dec = _json.loads(_trade_dec)
                _ep_raw = _trade_dec.get("entry_price") or result.get("entry_price") or 0
                _entry_price_for_check = float(_ep_raw) if _ep_raw else None
            except Exception:
                pass

            if _entry_price_for_check is not None and _data_manager is not None:
                try:
                    from risk.entry_price_sanity import (
                        check_entry_price_sanity,
                        is_entry_price_sanity_enabled,
                    )

                    if is_entry_price_sanity_enabled():
                        _is_sane, _sanity_reason = await check_entry_price_sanity(
                            symbol=symbol,
                            entry_price=_entry_price_for_check,
                            data_manager=_data_manager,
                        )
                        if not _is_sane:
                            logger.error(
                                "[AutonomousTick][ENTRY_PRICE_SANITY] %s enqueue rejected: %s",
                                symbol,
                                _sanity_reason,
                            )
                            summary["errors"].append(
                                {
                                    "symbol": symbol,
                                    "error": f"entry_price_sanity: {_sanity_reason}",
                                }
                            )
                            continue
                except Exception as _sanity_exc:
                    # Fail CLOSED: an error verifying the entry price must not let a
                    # possibly-corrupted candidate through to the approval queue.
                    logger.critical(
                        "[AutonomousTick][ENTRY_PRICE_SANITY] check raised for %s: %s — "
                        "rejecting candidate (fail-closed)",
                        symbol,
                        _sanity_exc,
                    )
                    summary["errors"].append(
                        {
                            "symbol": symbol,
                            "error": f"entry_price_sanity_error: {_sanity_exc}",
                        }
                    )
                    continue

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
            enqueued_entry = {
                "candidate_id": row_id,
                "symbol": symbol,
                "direction": direction,
                "confidence": confidence,
            }
            summary["enqueued"].append(enqueued_entry)

            # Opt-in paper-only auto-approve (default OFF). Never affects live —
            # _maybe_auto_approve_paper() refuses when LIVE_TRADING_ENABLED is True
            # and routes through the same approve_candidate() gate a human uses.
            try:
                if await _maybe_auto_approve_paper(row_id):
                    enqueued_entry["auto_approved_paper"] = True
            except Exception as _aa_exc:
                logger.warning(
                    "[AutonomousTick] auto-approve hook raised (non-fatal) for %d: %s",
                    row_id,
                    _aa_exc,
                )

            # Fire-and-forget Discord notification — never blocks the enqueue path
            try:
                from notifications.discord_webhook import post_approval_candidate

                _candidate_dict = {
                    "id": row_id,
                    "symbol": symbol,
                    "direction": direction,
                    "confidence": confidence,
                    "ttl_seconds": ttl,
                    "verdict_json": _json.dumps(result, default=str),
                }
                asyncio.create_task(post_approval_candidate(_candidate_dict))
            except Exception as _wh_exc:
                logger.warning(
                    "[AutonomousTick] Discord webhook task creation failed (non-fatal): %s",
                    _wh_exc,
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
