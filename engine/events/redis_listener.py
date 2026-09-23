"""
JARVIS TRADER — Redis Event Listener (Phase 2.2 / 5.1)
=====================================================
Listens for real-time ticks on Redis and triggers the trading pipeline.
Implements event-driven signal generation.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Dict, List

import redis.asyncio as redis

from config import settings

logger = logging.getLogger("jarvis_trader.redis_listener")

class RedisSignalTrigger:
    """
    Subscribes to market:ticks:* and triggers a callback when a bar closes.
    """

    def __init__(self, pipeline_callback: Callable, symbols: List[str]):
        self.callback = pipeline_callback
        self.symbols = [s.upper() for s in symbols]
        self.redis_client = None
        self._running = False
        self._task = None
        self._last_bar_hour: Dict[str, int] = dict.fromkeys(symbols, -1)

    async def start(self):
        """Start the listener loop."""
        if self._running:
            return

        self._running = True
        self.redis_client = redis.from_url(
            settings.REDIS_URL or "redis://localhost:6379/0",
            encoding="utf-8",
<<<<<<< HEAD
            decode_responses=True
        )
=======
            decode_responses=True,
            # Bounded (2026-08-17): a wedged Redis that accepts TCP but never
            # responds must not hang the boot path.
            socket_connect_timeout=3.0,
            socket_timeout=3.0,
        )
        try:
            await asyncio.wait_for(self.redis_client.ping(), timeout=3.0)
        except Exception as exc:
            logger.warning("📡 RedisListener: Redis unreachable at start (%s) — retries will degrade", exc)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

        logger.info(f"📡 RedisListener: Subscribing to ticks for {self.symbols}")
        self._task = asyncio.create_task(self._listen())

    async def stop(self):
        """Stop the listener."""
        self._running = False
        if self._task:
            self._task.cancel()
        if self.redis_client:
            await self.redis_client.close()
        logger.info("🛑 RedisListener: Stopped")

    async def _listen(self):
        """Main pub/sub loop."""
        pubsub = self.redis_client.pubsub()
        channels = [f"market:ticks:{s}" for s in self.symbols]
        await pubsub.subscribe(*channels)

        async for message in pubsub.listen():
            if not self._running:
                break

            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])
                symbol = data.get("symbol", "").split(":")[-1]
                timestamp_sec = data.get("time") # Unix timestamp from TradingView

                if not symbol or not timestamp_sec:
                    continue

                # ── Bar-Close Detection (1h) ──────────────────────────────
                dt = datetime.fromtimestamp(timestamp_sec, tz=timezone.utc)
                hour = dt.hour

                if self._last_bar_hour[symbol] != -1 and hour != self._last_bar_hour[symbol]:
                    logger.info(f"🔔 [BarClose] {symbol} 1h bar closed at {dt.isoformat()}")
                    # Trigger the full pipeline analysis
                    asyncio.create_task(self.callback(symbol))

                self._last_bar_hour[symbol] = hour

            except Exception as e:
                logger.error(f"[RedisListener] Error: {e}")

async def default_pipeline_trigger(symbol: str):
    """
    Default callback to trigger the engine's main pipeline.
    Injected from main.py.
    """
    logger.info(f"🚀 [Event] Triggering pipeline for {symbol}")
    # This will be replaced by the actual TradingPipeline.analyze_and_decide call
    pass
