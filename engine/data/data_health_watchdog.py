"""
Data-leg health watchdog — JARVIS TRADER
========================================
Detects a *mid-session* drop of the IB **data** connection (distinct from the
execution leg, which ``execution/ib_gateway_connector.py`` already auto-reconnects),
attempts a single bounded reconnect, and emits a throttled alert when the data
leg is down — or when its bars have gone stale while the socket is nominally
connected.

Background: PR #34 fixed the *startup* clientId collision on the data leg. This
closes the remaining *mid-session* gap: after a successful connect, if the data
leg drops, ``MarketDataManager.get_bars`` silently serves Polygon/CSV with no
alarm and no reconnect attempt.

Behaviour
---------
* Only acts during market hours (reuses ``health.ib_monitor.is_market_hours``).
* ``ibkr is None`` (data subsystem not yet initialised) is treated as "skip",
  not "down", to avoid false alarms during startup.
* On disconnect: one ``connect(retries=1)`` attempt (unless reconnect disabled).
* Alerts are throttled by ``alert_cooldown`` so a sustained outage notifies once.

Config (env)
------------
* ``JARVIS_DATA_WATCHDOG``           enable the loop (default "1" / on)
* ``JARVIS_DATA_WATCHDOG_RECONNECT`` attempt auto-reconnect (default "1" / on)
* ``JARVIS_DATA_WATCHDOG_INTERVAL``  seconds between checks (default 45)
* ``JARVIS_DATA_WATCHDOG_COOLDOWN``  seconds between alerts (default 900)
* ``JARVIS_DATA_WATCHDOG_STALENESS`` max bar age while connected (default 600)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Awaitable, Callable, Optional

from health.ib_monitor import is_market_hours as _default_is_market_hours

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip())
    except (TypeError, ValueError):
        return default


def watchdog_enabled() -> bool:
    """True unless explicitly disabled via JARVIS_DATA_WATCHDOG=0."""
    return _env_bool("JARVIS_DATA_WATCHDOG", True)


async def _default_alert(message: str) -> None:
    """Best-effort alert via whatever notifier is configured. Never raises."""
    text = f"[JARVIS data watchdog] {message}"
    try:
        from notifications.telegram import TelegramNotifier

        await TelegramNotifier().send(text)
        return
    except Exception as exc:  # noqa: BLE001 — fall through to log
        logger.debug("[DataWatchdog] telegram alert failed: %s", exc)
    logger.error("[DataWatchdog] ALERT (no notifier delivered): %s", message)


class DataHealthWatchdog:
    """Periodic health check for the IB market-data connection."""

    def __init__(
        self,
        market_data_manager,
        *,
        check_interval: Optional[float] = None,
        alert_cooldown: Optional[float] = None,
        staleness_limit: Optional[float] = None,
        reconnect_enabled: Optional[bool] = None,
        alert_cb: Optional[Callable[[str], Awaitable[None]]] = None,
        now_fn: Optional[Callable[[], float]] = None,
        is_market_hours_fn: Callable[[], bool] = _default_is_market_hours,
    ):
        self.mdm = market_data_manager
        self.check_interval = (
            check_interval
            if check_interval is not None
            else _env_float("JARVIS_DATA_WATCHDOG_INTERVAL", 45.0)
        )
        self.alert_cooldown = (
            alert_cooldown
            if alert_cooldown is not None
            else _env_float("JARVIS_DATA_WATCHDOG_COOLDOWN", 900.0)
        )
        self.staleness_limit = (
            staleness_limit
            if staleness_limit is not None
            else _env_float("JARVIS_DATA_WATCHDOG_STALENESS", 600.0)
        )
        self.reconnect_enabled = (
            reconnect_enabled
            if reconnect_enabled is not None
            else _env_bool("JARVIS_DATA_WATCHDOG_RECONNECT", True)
        )
        self._alert_cb = alert_cb or _default_alert
        self._now = now_fn or time.time
        self._is_market_hours = is_market_hours_fn
        self._last_alert_ts: float = 0.0

    def _connector(self):
        return getattr(self.mdm, "ibkr", None)

    def _last_ok_ts(self) -> Optional[float]:
        ts = getattr(self.mdm, "ib_data_last_ok", None)
        return float(ts) if ts is not None else None

    async def tick(self) -> Optional[str]:
        """Run one health evaluation. Returns the alert reason if one fired, else None."""
        if not self._is_market_hours():
            return None

        conn = self._connector()
        if conn is None:
            # Data subsystem not initialised yet — not a drop.
            return None

        try:
            connected = bool(conn.is_connected)
        except Exception as exc:  # noqa: BLE001 — treat unreadable state as down
            logger.warning("[DataWatchdog] is_connected read failed: %s", exc)
            connected = False

        if not connected and self.reconnect_enabled:
            try:
                connected = bool(await conn.connect(retries=1))
                if connected:
                    logger.info("[DataWatchdog] data leg reconnected")
            except Exception as exc:  # noqa: BLE001 — reconnect is best-effort
                logger.warning("[DataWatchdog] reconnect attempt failed: %s", exc)

        now = self._now()
        last_ok = self._last_ok_ts()
        stale = (
            connected and last_ok is not None and (now - last_ok) > self.staleness_limit
        )

        if connected and not stale:
            return None

        if not connected:
            reason = "IB data leg DOWN during market hours — serving fallback data"
        else:
            reason = f"IB data bars stale ({int(now - last_ok)}s) while connected"

        if now - self._last_alert_ts < self.alert_cooldown:
            logger.debug("[DataWatchdog] problem on cooldown, not alerting: %s", reason)
            return None

        self._last_alert_ts = now
        try:
            await self._alert_cb(reason)
        except Exception as exc:  # noqa: BLE001 — never let alerting break the loop
            logger.warning("[DataWatchdog] alert callback failed: %s", exc)
        return reason

    async def monitor_loop(self) -> None:
        logger.info(
            "[DataWatchdog] started (interval=%.0fs cooldown=%.0fs staleness=%.0fs reconnect=%s)",
            self.check_interval,
            self.alert_cooldown,
            self.staleness_limit,
            self.reconnect_enabled,
        )
        while True:
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001 — a bad tick must not kill the loop
                logger.warning("[DataWatchdog] tick error: %s", exc)
            await asyncio.sleep(self.check_interval)
