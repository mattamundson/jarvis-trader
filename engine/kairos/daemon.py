"""
KAIROS — Proactive Monitoring Daemon
======================================
Always-on background task running inside the FastAPI lifespan.

Design rules:
- ZERO LLM calls in the monitoring loop — pure Python watchers only.
- Tick interval: 60 s during market hours (CT 8:30–16:00 weekdays), 300 s off-hours.
- Each tick builds a market snapshot, runs all registered watchers, logs and emits
  any observations, and optionally sends notifications.
- Tolerant of missing dependencies: data_manager=None, safety_layer=None, etc.
  all produce graceful degradation rather than errors.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .observation_log import ObservationLog
from .watchers import BaseWatcher

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Module-level singleton ─────────────────────────────────────────────────

_kairos_instance: Optional["KairosDaemon"] = None


def get_kairos() -> Optional["KairosDaemon"]:
    """Return the active KairosDaemon singleton (or None if not started)."""
    return _kairos_instance


def set_kairos_instance(daemon: "KairosDaemon") -> None:
    """Register the global KairosDaemon singleton."""
    global _kairos_instance
    _kairos_instance = daemon


# ── KairosDaemon ──────────────────────────────────────────────────────────


class KairosDaemon:
    """
    KAIROS: Always-on proactive monitoring daemon.

    Runs as an asyncio background task within FastAPI lifespan.
    Tick-based cycle: 60 s market hours, 300 s off-hours.
    ZERO LLM calls in monitoring loop — pure Python rules via watchers.
    """

    def __init__(
        self,
        config,
        data_manager=None,
        safety_layer=None,
        ws_manager=None,
        notifier=None,
    ) -> None:
        self._config = config
        self._data = data_manager
        self._safety = safety_layer
        self._ws = ws_manager
        self._notifier = notifier
        self._running = False
        self._tick_count = 0
        self._start_time: Optional[datetime] = None
        self._last_tick_time: Optional[datetime] = None
        self._watchers: list[BaseWatcher] = []
        self._log = ObservationLog()
        self._task: Optional[asyncio.Task] = None
        self._error_count = 0

    # ── Watcher registration ───────────────────────────────────────────────

    def register_watcher(self, watcher: BaseWatcher) -> None:
        """Add a watcher to the monitoring loop."""
        self._watchers.append(watcher)
        logger.info(f"KAIROS: registered watcher '{watcher.name}'")

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._running:
            logger.warning("KAIROS: already running — ignoring duplicate start()")
            return
        self._running = True
        self._start_time = datetime.now()
        self._task = asyncio.create_task(self._run_loop(), name="kairos_daemon")
        logger.info(f"KAIROS: daemon started with {len(self._watchers)} watchers registered")

    async def stop(self) -> None:
        """Stop the background monitoring loop and clean up."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("KAIROS: daemon stopped")

    # ── Main loop ─────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Infinite monitoring loop — ticks and sleeps until stopped."""
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._error_count += 1
                logger.error(f"KAIROS tick error (total errors={self._error_count}): {exc}")

            interval = self._get_tick_interval()
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise

    def _get_tick_interval(self) -> int:
        """
        Return tick interval in seconds.
        Market hours (America/Chicago): Mon-Fri 08:30-16:00 → 60 s.
        Off-hours or weekends → 300 s.
        Falls back to simple UTC hour check if pytz is unavailable.
        """
        config_fast = getattr(self._config, "KAIROS_TICK_SECONDS", 60)
        config_slow = getattr(self._config, "KAIROS_OFF_HOURS_TICK_SECONDS", 300)

        try:
            from datetime import time as dt_time

            import pytz

            tz = pytz.timezone("America/Chicago")
            now = datetime.now(tz)
            is_weekday = now.weekday() < 5
            market_open = dt_time(8, 30)
            market_close = dt_time(16, 0)
            is_market_hours = market_open <= now.time() <= market_close
            if is_weekday and is_market_hours:
                return config_fast
            return config_slow

        except ImportError:
            # Fallback: rough UTC check (CT market hours ≈ 14:30–22:00 UTC)
            from datetime import timezone as tz_module

            now_utc = datetime.now(tz_module.utc)
            is_weekday = now_utc.weekday() < 5
            is_rough_market = 14 <= now_utc.hour < 22
            if is_weekday and is_rough_market:
                return config_fast
            return config_slow

    # ── Single tick ────────────────────────────────────────────────────────

    async def tick(self) -> None:
        """Execute one monitoring cycle: build snapshot → run watchers → emit."""
        self._tick_count += 1
        self._last_tick_time = datetime.now()

        snapshot = await self._build_snapshot()

        severity_order = {"info": 0, "warning": 1, "critical": 2}
        min_notify_severity = getattr(self._config, "KAIROS_NOTIFY_SEVERITY", "warning")
        min_level = severity_order.get(min_notify_severity, 1)

        for watcher in self._watchers:
            try:
                obs_list = await watcher.check(snapshot)
            except Exception as exc:
                logger.error(f"KAIROS watcher '{watcher.name}' raised an exception: {exc}")
                continue

            for obs in obs_list:
                # Always log to JSONL file
                self._log.append(obs)

                # Emit via WebSocket if manager is available
                if self._ws:
                    try:
                        await self._ws.broadcast(
                            {
                                "type": "kairos_observation",
                                "data": {
                                    "watcher": obs.watcher,
                                    "severity": obs.severity.value,
                                    "message": obs.message,
                                    "symbol": obs.symbol,
                                    "timestamp": obs.timestamp,
                                },
                            }
                        )
                    except Exception as ws_exc:
                        logger.debug(f"KAIROS WebSocket broadcast failed: {ws_exc}")

                # Send notification for qualifying observations
                obs_level = severity_order.get(obs.severity.value, 0)
                if obs.notify and obs_level >= min_level and self._notifier:
                    try:
                        await self._notifier.send_alert(
                            f"KAIROS [{obs.severity.value.upper()}] {obs.watcher}\n"
                            f"{obs.message}"
                        )
                    except Exception as notify_exc:
                        logger.debug(f"KAIROS notifier failed: {notify_exc}")

    # ── Snapshot builder ───────────────────────────────────────────────────

    async def _build_snapshot(self) -> dict:
        """
        Assemble the market snapshot dict passed to every watcher.

        Structure:
          snapshot["timestamp"]         — ISO string
          snapshot["risk_status"]       — dict from SafetyLayer.get_status()
          snapshot["vix"]               — float | None
          snapshot["symbols"][symbol]   — {"price", "volume", "stc", "regime", "spread"}
        """
        snapshot: dict = {
            "timestamp": datetime.now().isoformat(),
            "symbols": {},
            "risk_status": {},
            "vix": None,
        }

        # Risk status from SafetyLayer
        if self._safety is not None:
            try:
                if hasattr(self._safety, "get_status"):
                    snapshot["risk_status"] = self._safety.get_status()
            except Exception as exc:
                logger.debug(f"KAIROS snapshot: SafetyLayer.get_status() failed: {exc}")

        # Market data per symbol
        if self._data is not None:
            watchlist = getattr(self._config, "FUTURES_WATCHLIST", ["MES", "MNQ"])
            if isinstance(watchlist, str):
                watchlist = [s.strip() for s in watchlist.split(",") if s.strip()]

            for symbol in watchlist:
                try:
                    symbol_data: dict = {}

                    if hasattr(self._data, "get_bars"):
                        bars = await self._data.get_bars(symbol, interval="5m", limit=50)
                        if bars is not None and hasattr(bars, "iloc") and len(bars) > 0:
                            symbol_data["price"] = float(bars["close"].iloc[-1])
                            if "volume" in bars.columns:
                                symbol_data["volume"] = float(bars["volume"].iloc[-1])
                            if "regime" in bars.columns:
                                symbol_data["regime"] = str(bars["regime"].iloc[-1])
                            # STC is computed on-demand if signals available
                            symbol_data["stc"] = None

                    snapshot["symbols"][symbol] = symbol_data

                except Exception as exc:
                    logger.debug(f"KAIROS snapshot: data for {symbol} failed: {exc}")
                    snapshot["symbols"][symbol] = {}

        return snapshot

    # ── Status & inspection ────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return a JSON-serialisable status dict for the /kairos/status endpoint."""
        uptime_seconds: Optional[float] = None
        if self._start_time:
            uptime_seconds = (datetime.now() - self._start_time).total_seconds()

        return {
            "running": self._running,
            "tick_count": self._tick_count,
            "watcher_count": len(self._watchers),
            "watchers": [w.name for w in self._watchers],
            "uptime_seconds": uptime_seconds,
            "last_tick": (self._last_tick_time.isoformat() if self._last_tick_time else None),
            "error_count": self._error_count,
            "today_observation_count": len(self._log.read_today()),
        }

    def get_today_observations(self) -> list[dict]:
        """Return all observations logged today."""
        return self._log.read_today()

    def get_recent_observations(self, minutes: int = 60) -> list[dict]:
        """Return observations from the last N minutes."""
        return self._log.get_recent(minutes=minutes)
