"""
JARVIS Liveness Watchdog (US-006)
===================================
Standalone external poller — polls ``/health`` on the JARVIS engine and fires
multi-channel alerts when the engine is down or a monitored condition flips.

Does NOT require an engine restart.  Run it in a separate shell or as a
standalone scheduled task.

Trigger conditions (state-change, not every tick)
--------------------------------------------------
- Engine unreachable for N consecutive misses (default 3, configurable via
  ``--misses`` or ``WATCHDOG_MISS_THRESHOLD``).
- ``status != "ok"`` (engine degraded).
- ``ibkr_data_connected`` flips False (was True).
- ``kill_switch_active`` becomes True.

Debounce: alerts on state-change only.  Once a DOWN alert fires, no further
DOWN alerts until the engine comes back up (RECOVERY alert sent on re-entry).

Channels: dispatches to Telegram + Discord via the existing notifier classes
(engine/notifications/).  No tokens are read here — the notifiers own their
own config (``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``,
``DISCORD_WEBHOOK_URL``).  A channel is silently skipped when unconfigured.

Usage
-----
    # Poll every 60 s (default):
    python engine/scripts/liveness_watchdog.py

    # Poll every 30 s, alert after 2 consecutive misses:
    python engine/scripts/liveness_watchdog.py --interval 30 --misses 2

    # One-shot health check (exits 0 = ok, 1 = degraded):
    python engine/scripts/liveness_watchdog.py --once

    # Send a labeled test alert to all configured channels and exit:
    python engine/scripts/liveness_watchdog.py --self-test

Environment
-----------
    WATCHDOG_ENGINE_URL       Base URL for the engine (default http://127.0.0.1:8010)
    WATCHDOG_INTERVAL         Poll interval in seconds (default 60)
    WATCHDOG_MISS_THRESHOLD   Consecutive miss count before DOWN alert (default 3)
    TELEGRAM_BOT_TOKEN        (owned by notifications/telegram.py)
    TELEGRAM_CHAT_ID          (owned by notifications/telegram.py)
    DISCORD_WEBHOOK_URL       (owned by notifications/discord_notifier.py)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

# ── Engine path bootstrap ─────────────────────────────────────────────────────
# Allow running from repo root or from engine/scripts/ without a venv PATH
# tweak.  Adds ``engine/`` to sys.path so notification imports resolve.
_HERE = Path(__file__).resolve().parent
_ENGINE_ROOT = _HERE.parent  # engine/
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))
# Also add parent of engine/ so "from notifications.xxx import" works
_REPO_ROOT = _ENGINE_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── .env bootstrap ────────────────────────────────────────────────────────────
# Load engine/.env before any config/settings import so API_KEY and notifier
# credentials are in the environment.  python-dotenv is already a dep.
try:
    from dotenv import load_dotenv as _load_dotenv

    _dotenv_path = _ENGINE_ROOT / ".env"
    if _dotenv_path.exists():
        _load_dotenv(str(_dotenv_path), override=False)
except Exception:
    pass  # dotenv optional; non-fatal if absent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("jarvis.liveness_watchdog")

# ── Defaults ─────────────────────────────────────────────────────────────────
_DEFAULT_URL = "http://127.0.0.1:8010"
_DEFAULT_INTERVAL = 60
_DEFAULT_MISSES = 3

# ── State tracking ────────────────────────────────────────────────────────────


@dataclass
class WatchdogState:
    """Tracks previous observed values for state-change detection."""

    engine_down: bool = False          # True while consecutive misses >= threshold
    consecutive_misses: int = 0
    last_status: Optional[str] = None  # "ok" / "degraded" / None
    last_ibkr_data: Optional[bool] = None
    last_kill_switch: Optional[bool] = None
    alerted_keys: set[str] = field(default_factory=set)  # for deduplification


# ── Multi-channel dispatch ────────────────────────────────────────────────────


async def _send_telegram(message: str) -> bool:
    """Deliver message to Telegram. Returns True on success."""
    try:
        from notifications.telegram import get_notifier as _tg

        notifier = _tg()
        if not notifier.config_valid:
            logger.debug("[watchdog/telegram] not configured — skipped")
            return False
        ok = await notifier.send(message, parse_mode=None)
        if ok:
            logger.info("[watchdog/telegram] delivered")
        else:
            logger.warning("[watchdog/telegram] send returned falsy")
        return ok
    except Exception as exc:
        logger.warning("[watchdog/telegram] delivery failed (non-fatal): %s", exc)
        return False


async def _send_discord(message: str) -> bool:
    """Deliver message to Discord. Returns True on success."""
    try:
        from notifications.discord_notifier import _send as _disc_send

        ok = await _disc_send(message)
        if ok:
            logger.info("[watchdog/discord] delivered")
        else:
            logger.debug("[watchdog/discord] send returned falsy (not configured or disabled)")
        return ok
    except Exception as exc:
        logger.warning("[watchdog/discord] delivery failed (non-fatal): %s", exc)
        return False


async def broadcast(message: str) -> dict[str, bool]:
    """Fan-out to all configured channels. Returns {channel: success}."""
    tg, disc = await asyncio.gather(
        _send_telegram(message),
        _send_discord(message),
        return_exceptions=False,
    )
    return {"telegram": bool(tg), "discord": bool(disc)}


# ── Health poll ───────────────────────────────────────────────────────────────


async def poll_health(engine_url: str, timeout: float = 8.0) -> Optional[dict]:
    """
    GET {engine_url}/health.  Returns the parsed JSON dict or None on failure.
    Timeout is deliberately generous to handle a slow-starting engine.
    """
    url = engine_url.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("[watchdog] /health returned HTTP %s", resp.status_code)
            return None
    except Exception as exc:
        logger.debug("[watchdog] /health unreachable: %s", exc)
        return None


# ── State-change evaluation ───────────────────────────────────────────────────


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def evaluate(
    health: Optional[dict],
    state: WatchdogState,
    miss_threshold: int,
) -> list[str]:
    """
    Compare latest health snapshot against previous state.
    Returns list of alert message strings to broadcast (empty = no change).
    Updates *state* in-place.
    """
    alerts: list[str] = []

    if health is None:
        # Count the miss
        state.consecutive_misses += 1
        if state.consecutive_misses >= miss_threshold and not state.engine_down:
            state.engine_down = True
            msg = (
                f"[JARVIS ALERT] Engine DOWN\n"
                f"Endpoint unreachable for {state.consecutive_misses} consecutive polls.\n"
                f"URL: {_DEFAULT_URL}\n"
                f"Time: {_ts()}"
            )
            alerts.append(msg)
        return alerts

    # Engine responded — reset miss counter
    was_down = state.engine_down
    state.consecutive_misses = 0
    state.engine_down = False

    if was_down:
        # Recovery
        alerts.append(
            f"[JARVIS ALERT] Engine RECOVERED\n"
            f"Status: {health.get('status', '?')}\n"
            f"Time: {_ts()}"
        )

    # Check status field
    current_status = health.get("status")
    if current_status != "ok" and state.last_status != current_status:
        alerts.append(
            f"[JARVIS ALERT] Engine degraded\n"
            f"Status: {current_status}\n"
            f"Time: {_ts()}"
        )
    state.last_status = current_status

    # Check ibkr_data_connected flip (True → False only)
    current_ibkr = health.get("ibkr_data_connected")
    if (
        current_ibkr is False
        and state.last_ibkr_data is True
    ):
        alerts.append(
            f"[JARVIS ALERT] IBKR data feed disconnected\n"
            f"ibkr_data_connected flipped False.\n"
            f"Time: {_ts()}"
        )
    state.last_ibkr_data = current_ibkr

    # Check kill_switch_active (False/None → True)
    current_ks = health.get("kill_switch_active")
    if current_ks is True and not state.last_kill_switch:
        alerts.append(
            f"[JARVIS ALERT] Kill switch ACTIVATED\n"
            f"All trading halted. Check dashboard.\n"
            f"Time: {_ts()}"
        )
    state.last_kill_switch = current_ks

    return alerts


# ── Main loop ─────────────────────────────────────────────────────────────────


async def run_loop(
    engine_url: str,
    interval: int,
    miss_threshold: int,
) -> None:
    """Poll /health in a loop and broadcast alerts on state change."""
    state = WatchdogState()
    logger.info(
        "[watchdog] starting — url=%s interval=%ds misses=%d",
        engine_url,
        interval,
        miss_threshold,
    )
    while True:
        health = await poll_health(engine_url)
        alerts = evaluate(health, state, miss_threshold)
        for msg in alerts:
            logger.warning("[watchdog] ALERT: %s", msg.replace("\n", " | "))
            results = await broadcast(msg)
            logger.info("[watchdog] broadcast results: %s", results)

        await asyncio.sleep(interval)


async def run_once(engine_url: str, miss_threshold: int = _DEFAULT_MISSES) -> int:
    """Single poll — returns 0 if healthy, 1 if degraded/unreachable."""
    health = await poll_health(engine_url)
    if health is None:
        logger.error("[watchdog --once] engine unreachable at %s", engine_url)
        return 1
    status = health.get("status")
    if status != "ok":
        logger.warning("[watchdog --once] status=%s", status)
        return 1
    logger.info("[watchdog --once] status=ok ibkr_data=%s ks=%s",
                health.get("ibkr_data_connected"),
                health.get("kill_switch_active"))
    return 0


async def run_self_test(engine_url: str) -> None:
    """Send one clearly-labeled test alert to all configured channels and exit."""
    msg = (
        "[JARVIS TEST] liveness watchdog wired\n"
        f"engine_url={engine_url}\n"
        f"sent_at={_ts()}\n"
        "This is a self-test message — no action required."
    )
    logger.info("[watchdog --self-test] broadcasting test alert")
    results = await broadcast(msg)
    channels_sent = [ch for ch, ok in results.items() if ok]
    channels_skipped = [ch for ch, ok in results.items() if not ok]
    logger.info("[watchdog --self-test] delivered to: %s", channels_sent or ["(none)"])
    if channels_skipped:
        logger.info(
            "[watchdog --self-test] skipped (not configured): %s",
            channels_skipped,
        )


# ── CLI entry point ───────────────────────────────────────────────────────────


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="JARVIS liveness watchdog")
    p.add_argument(
        "--url",
        default=os.environ.get("WATCHDOG_ENGINE_URL", _DEFAULT_URL),
        help="Engine base URL (default %(default)s)",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("WATCHDOG_INTERVAL", str(_DEFAULT_INTERVAL))),
        help="Poll interval in seconds (default %(default)s)",
    )
    p.add_argument(
        "--misses",
        type=int,
        default=int(os.environ.get("WATCHDOG_MISS_THRESHOLD", str(_DEFAULT_MISSES))),
        help="Consecutive miss count before DOWN alert (default %(default)s)",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="One-shot poll: exit 0 if healthy, 1 if degraded/unreachable",
    )
    p.add_argument(
        "--self-test",
        dest="self_test",
        action="store_true",
        help="Send a labeled test alert to all configured channels and exit",
    )
    return p.parse_args(argv)


async def _main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    if args.self_test:
        await run_self_test(args.url)
        return 0
    if args.once:
        return await run_once(args.url, args.misses)
    await run_loop(args.url, args.interval, args.misses)
    return 0  # unreachable in normal operation


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
