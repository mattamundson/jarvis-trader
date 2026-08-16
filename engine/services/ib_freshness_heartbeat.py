"""
IB Market-Data Freshness Heartbeat
==================================
``/system/data-integrity`` and the real-money-readiness ``feeds_live`` gate read
``datasource:*:last_update`` Redis keys to decide whether the price picture is
trustworthy. Historically only the TV Desktop scraper wrote such a key, so once
that GUI-scrape died the integrity panel showed nothing but stale TV corpses
even while IB served live prices on demand.

The ``MarketDataManager`` now publishes a ``datasource:ib_gateway:last_update``
heartbeat every time IB serves fresh data (``_record_ibkr_freshness``). But that
only fires when *something* asks for a price, and the only always-on price poller
-- ``TrailingStopManager`` -- returns early when no position is open. So on a
flat day nothing refreshes the heartbeat and ``feeds_live`` would falsely fail
even with IB perfectly connected.

This service closes that gap: it pulls one IB snapshot on a fixed cadence,
independent of open positions, and lets the data manager stamp the heartbeat. It
is deliberately a standalone loop rather than a hook inside ``IBDataWatchdog`` so
it cannot perturb that service's tested reconnect state machine.

It is *honest*: the heartbeat is stamped only when IB actually returns a price.
A socket that is up but serving no data leaves the heartbeat to age, so the
integrity panel and the gate see the real staleness.

Tunables are read at use-site via ``os.getenv`` (matching ``IBDataWatchdog``):

  IBKR_HEARTBEAT_ENABLED    default on     ("0"/"false"/"no"/"off" disables)
  IBKR_HEARTBEAT_INTERVAL   default 60     poll seconds (floored at 15)
  IBKR_HEARTBEAT_SYMBOL     default MES    instrument probed each beat
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


class IBFreshnessHeartbeat:
    """Background task that keeps the IB data-freshness heartbeat current."""

    def __init__(self, data_manager):
        self.data = data_manager
        self.enabled = _env_flag("IBKR_HEARTBEAT_ENABLED", True)
        self.interval = max(15.0, _env_float("IBKR_HEARTBEAT_INTERVAL", 60.0))
        self._symbol = (os.getenv("IBKR_HEARTBEAT_SYMBOL") or "MES").strip() or "MES"
        self._running = False
        self._task: asyncio.Task | None = None
        self.last_beat_ts: float | None = None      # epoch of last successful stamp
        self.last_attempt_ts: float | None = None    # epoch of last probe attempt
        self._consecutive_probe_failures = 0          # 2026-08-15: see _beat()

    async def start(self) -> None:
        if self._running:
            return
        if not self.enabled:
            logger.info("[IBHeartbeat] disabled via IBKR_HEARTBEAT_ENABLED")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "💓 IBFreshnessHeartbeat started (interval=%.0fs, symbol=%s)",
            self.interval, self._symbol,
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
                await self._beat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[IBHeartbeat] loop error: %s", e)
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break

    async def _beat(self) -> None:
        """Pull one IB snapshot and, on a real price, stamp the freshness
        heartbeat. Market-hours gated to match ``IBDataWatchdog._is_stale`` so
        the two services agree on when a quiet feed is expected vs. broken. Any
        failure is swallowed -- the heartbeat simply ages, which is the honest
        signal that IB is not serving data."""
        ibkr = getattr(self.data, "ibkr", None)
        if not (ibkr is not None and ibkr.is_connected):
            return
        try:
            from health.ib_monitor import is_market_hours

            if not is_market_hours():
                return
        except Exception:
            # Can't establish market hours -> don't stamp a possibly-closed feed.
            return

        self.last_attempt_ts = time.time()
        try:
            result = await asyncio.wait_for(
                ibkr.get_snapshot_price(self._symbol, True), timeout=8.0
            )
        except Exception as e:
            # 2026-08-15 incident: this was the ONE component honestly detecting
            # a wedged Gateway (socket up, API not answering -- is_connected
            # can't see it) and it logged the fact at DEBUG, where nobody looks.
            # The heartbeat aging is still the correct signal for feeds_live/the
            # integrity panel (see class docstring) -- this only fixes the
            # human-visible diagnostic, not the gating behavior. WARNING on the
            # first failure and every 5th thereafter so a real outage is loud
            # without flooding the log every `interval` seconds.
            self._consecutive_probe_failures += 1
            if self._consecutive_probe_failures == 1 or self._consecutive_probe_failures % 5 == 0:
                logger.warning(
                    "[IBHeartbeat] snapshot probe failed (%s consecutive): %s",
                    self._consecutive_probe_failures, e,
                )
            else:
                logger.debug("[IBHeartbeat] snapshot probe failed: %s", e)
            return
        self._consecutive_probe_failures = 0

        if result and result.get("last_price"):
            rec = getattr(self.data, "_record_ibkr_freshness", None)
            if callable(rec):
                rec()
            else:  # pragma: no cover - defensive against an older data manager
                try:
                    self.data._last_ibkr_data_ts = time.time()
                except Exception:
                    return
            self.last_beat_ts = time.time()

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "running": self._running,
            "interval_s": self.interval,
            "symbol": self._symbol,
            "last_attempt_ts": self.last_attempt_ts,
            "last_beat_ts": self.last_beat_ts,
        }
