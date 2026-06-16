"""
IB Data-Leg Auto-Reconnect Watchdog
===================================
The execution leg already self-heals via ``IBGatewayConnector._heartbeat()``; the
market-data leg did not. If IB Gateway drops mid-session (its daily auto-restart /
logout, or a network blip) the data connector silently degraded to lower-tier
sources until someone called ``POST /data/reconnect`` by hand. This watchdog polls
the data connection and reconnects with capped exponential backoff, mirroring the
``TrailingStopManager`` / ``CanaryManager`` background-service pattern.

It also catches the "socket up but data dead" failure a pure socket check misses:
if IBKR reports connected but has served no fresh data within ``stale_seconds``
*during market hours*, it forces a reconnect.

Tunables are read at use-site via ``os.getenv`` (not ``config.py``) so this stays
outside the safety-invariant CI gate, matching ``resolve_data_client_id``:

  IBKR_DATA_WATCHDOG_ENABLED      default on     ("0"/"false"/"no"/"off" disables)
  IBKR_DATA_WATCHDOG_INTERVAL     default 30     poll seconds (floored at 5)
  IBKR_DATA_WATCHDOG_MAX_BACKOFF  default 300    reconnect-spacing cap seconds
  IBKR_DATA_STALE_SECONDS         default 180    stale-data → reconnect (0 disables)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class IBDataWatchdog:
    """Background task that keeps the market-data IB leg connected."""

    def __init__(self, data_manager):
        self.data = data_manager
        self.enabled = _env_flag("IBKR_DATA_WATCHDOG_ENABLED", True)
        self.interval = max(5.0, _env_float("IBKR_DATA_WATCHDOG_INTERVAL", 30.0))
        self._max_backoff = max(
            self.interval, _env_float("IBKR_DATA_WATCHDOG_MAX_BACKOFF", 300.0)
        )
        self.stale_seconds = _env_float("IBKR_DATA_STALE_SECONDS", 180.0)

        self._running = False
        self._task: asyncio.Task | None = None
        self.consecutive_failures = 0
        self.last_attempt_ts: float | None = None   # epoch of last reconnect attempt
        self.last_success_ts: float | None = None   # epoch of last successful reconnect
        self._next_eligible = 0.0                    # monotonic gate for backoff spacing
        self._alert_cooldown = 3600.0
        self._last_alert = 0.0

    async def start(self) -> None:
        if self._running:
            return
        # Let /health read our status without changing inject_dependencies().
        try:
            self.data._watchdog = self
        except Exception:
            pass
        if not self.enabled:
            logger.info("[IBDataWatchdog] disabled via IBKR_DATA_WATCHDOG_ENABLED")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "🐕 IBDataWatchdog started (interval=%.0fs, max_backoff=%.0fs, stale=%.0fs)",
            self.interval, self._max_backoff, self.stale_seconds,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[IBDataWatchdog] loop error: %s", e)
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break

    def _is_stale(self) -> bool:
        """Connected socket but no fresh IBKR data within the window during RTH."""
        if self.stale_seconds <= 0:
            return False
        last = getattr(self.data, "_last_ibkr_data_ts", None)
        if last is None:
            # Nothing fetched yet — don't churn a quiet-but-healthy socket.
            return False
        try:
            from health.ib_monitor import is_market_hours

            if not is_market_hours():
                return False
        except Exception:
            return False
        return (time.time() - last) > self.stale_seconds

    async def _tick(self) -> None:
        ibkr = getattr(self.data, "ibkr", None)
        connected = bool(ibkr is not None and ibkr.is_connected)

        if connected and not self._is_stale():
            if self.consecutive_failures:
                self.consecutive_failures = 0
                self._next_eligible = 0.0
            return

        # Respect backoff spacing after repeated failures (don't hammer IB during
        # the daily Gateway-restart window).
        if time.monotonic() < self._next_eligible:
            return

        reason = "drop" if not connected else "stale-data"
        logger.warning("[IBDataWatchdog] data leg unhealthy (%s) — reconnecting", reason)
        self.last_attempt_ts = time.time()
        try:
            ok = await self.data.reconnect_ibkr(timeout=15.0)
        except Exception as e:
            logger.error("[IBDataWatchdog] reconnect raised: %s", e)
            ok = False

        if ok:
            self.consecutive_failures = 0
            self.last_success_ts = time.time()
            self._next_eligible = 0.0
            logger.info("[IBDataWatchdog] data leg reconnected")
        else:
            self.consecutive_failures += 1
            backoff = min(self._max_backoff, self.interval * (2 ** self.consecutive_failures))
            self._next_eligible = time.monotonic() + backoff
            logger.warning(
                "[IBDataWatchdog] reconnect failed (#%d) — next attempt in %.0fs",
                self.consecutive_failures, backoff,
            )
            if self.consecutive_failures >= 3:
                self._maybe_alert()

    def _maybe_alert(self) -> None:
        """Best-effort, cooldown- and market-hours-gated reuse of the existing notifier."""
        now = time.time()
        if now - self._last_alert < self._alert_cooldown:
            return
        try:
            from health.ib_monitor import is_market_hours

            if not is_market_hours():
                return
            from notifications.openclaw_notifier import notify_ib_disconnect

            asyncio.create_task(notify_ib_disconnect())
            self._last_alert = now
            logger.error("[IBDataWatchdog] data leg down %dx — alert dispatched",
                         self.consecutive_failures)
        except Exception as e:
            logger.warning("[IBDataWatchdog] alert dispatch failed: %s", e)

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "running": self._running,
            "consecutive_failures": self.consecutive_failures,
            "last_attempt_ts": self.last_attempt_ts,
            "last_reconnect_ts": self.last_success_ts,
            "interval_s": self.interval,
            "stale_seconds": self.stale_seconds,
        }
