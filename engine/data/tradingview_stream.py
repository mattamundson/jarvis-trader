"""
JARVIS TRADER — TradingView WebSocket Streamer (Phase 2)
=========================================================
Connects to TradingView WebSocket, streams real-time ticks to Redis,
and persists high-frequency data to QuestDB.

Implements Roadmap P2.1 (Real-Time Data Fabric).
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from config import settings

logger = logging.getLogger("jarvis_trader.tv_stream")

class TVStreamer:
    """
    Manages WebSocket connection to TradingView and dispatches data.
    """

    def __init__(self, symbols: List[str], greeks_symbols: Optional[List[str]] = None):
        self.symbols = [s.upper() for s in symbols]
        self.greeks_symbols = [s.upper() for s in greeks_symbols] if greeks_symbols else []
        self.redis_client = None
        self._running = False
        self._task = None
        self._greeks_task = None

    async def connect_redis(self):
        """Initialise Redis connection for streaming."""
        try:
            self.redis_client = redis.from_url(
                settings.REDIS_URL or "redis://localhost:6379/0",
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis_client.ping()
            logger.info("✅ TVStreamer: Redis connection established")
        except Exception as e:
            logger.error(f"❌ TVStreamer: Redis connection failed: {e}")
            self.redis_client = None

    async def _stream_to_redis(self, symbol: str, data: Dict[str, Any]):
        """Publish tick to Redis channel and update latest key."""
        if not self.redis_client:
            return

        try:
            # Channel: market:ticks:{symbol}
            # Latest: market:latest:{symbol}
            payload = json.dumps(data)
            await self.redis_client.publish(f"market:ticks:{symbol}", payload)
            await self.redis_client.set(f"market:latest:{symbol}", payload)

            # Freshness tracking (Phase 2.6)
            now_ts = datetime.now(timezone.utc).isoformat()
            await self.redis_client.set(f"datasource:ticks:{symbol}:last_update", now_ts)
            await self.redis_client.set("datasource:tv_stream:last_update", now_ts)
        except Exception as e:
            logger.debug(f"Redis stream error for {symbol}: {e}")

    async def _stream_greeks(self, symbol: str, data_manager):
        """
        Fetch Greeks from IBKR and publish to Redis.
        """
        if not self.redis_client or not data_manager:
            return

        try:
            greeks = await data_manager.get_options_greeks(symbol)
            if "error" not in greeks:
                payload = json.dumps(greeks)
                await self.redis_client.publish(f"market:greeks:{symbol}", payload)
                await self.redis_client.set(f"market:greeks:latest:{symbol}", payload)

                # Freshness tracking (Phase 2.6)
                now_ts = datetime.now(timezone.utc).isoformat()
                await self.redis_client.set(f"datasource:greeks:{symbol}:last_update", now_ts)

                logger.debug(f"[TVStreamer] Streamed Greeks for {symbol}")
        except Exception as e:
            logger.debug(f"[TVStreamer] Greeks stream error for {symbol}: {e}")

    async def _persist_to_questdb(self, symbol: str, data: Dict[str, Any]):
        """
        Send tick to QuestDB via InfluxDB Line Protocol (TCP/UDP).
        QuestDB expected on port 9000 (HTTP/REST) or 9009 (ILP).
        We use the ILP sender for high-frequency performance.
        """
        try:
            from questdb.ingress import Sender, TimestampNanos

            host = settings.QUESTDB_HOST or "localhost"
            # ILP typically uses 9009, but config says 9000.
            # We'll try 9009 first as it's the standard for ILP.
            port = 9009

            with Sender(host, port) as sender:
                sender.row(
                    "market_ticks",
                    symbols={"symbol": symbol},
                    columns={
                        "open": float(data.get("open", 0)),
                        "high": float(data.get("high", 0)),
                        "low": float(data.get("low", 0)),
                        "close": float(data.get("close", 0)),
                        "volume": float(data.get("volume", 0)),
                    },
                    at=TimestampNanos.now()
                )
                sender.flush()
        except Exception as e:
            logger.debug(f"[TVStreamer] QuestDB persistence error: {e}")

    async def start(self, data_manager=None):
        """Start the streaming loop."""
        if self._running:
            return

        self._running = True
        await self.connect_redis()

        logger.info(f"🚀 TVStreamer: Starting real-time stream for {self.symbols}")
        self._task = asyncio.create_task(self._run_loop())

        if self.greeks_symbols and data_manager:
            logger.info(f"🚀 TVStreamer: Starting Greeks stream for {self.greeks_symbols}")
            self._greeks_task = asyncio.create_task(self._greeks_loop(data_manager))

    async def stop(self):
        """Gracefully stop the streamer."""
        self._running = False
        if self._task:
            self._task.cancel()
        if self._greeks_task:
            self._greeks_task.cancel()
        if self.redis_client:
            await self.redis_client.close()
        logger.info("🛑 TVStreamer: Stopped")

    async def _greeks_loop(self, data_manager):
        """
        Periodically poll Greeks for active options.
        """
        while self._running:
            try:
                for symbol in self.greeks_symbols:
                    await self._stream_greeks(symbol, data_manager)
                await asyncio.sleep(10)  # Refresh Greeks every 10s
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TVStreamer] Greeks loop error: {e}")
                await asyncio.sleep(10)

    async def _run_loop(self):
        """
        Main loop: launches tradingview-mcp CLI and pipes output to Redis.
        """
        # Multi-symbol stream using 'tv stream all'
        base_dir = Path(__file__).parent.parent.parent
        cli_path = base_dir / "tradingview-mcp" / "src" / "cli" / "index.js"

        if not cli_path.exists():
            logger.error(f"[TVStreamer] CLI not found at {cli_path}")
            return

        cmd = ["node", str(cli_path), "stream", "all", "-i", "500"]

        while self._running:
            proc = None
            try:
                logger.info(f"[TVStreamer] Launching TV stream: {' '.join(cmd)}")
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                async def log_stderr(stderr):
                    while True:
                        line = await stderr.readline()
                        if not line:
                            break
                        text = line.decode().strip()
                        if not text:
                            continue
                        # TV CLI floods stderr with routine chatter
                        # (_chartWidgetCollection, ~5/min). Only surface genuine
                        # errors at WARNING; route the rest to DEBUG to avoid the
                        # ~85k-line spam flood. (de-spam 2026-06-18)
                        low = text.lower()
                        if any(k in low for k in ("error", "exception", "traceback", "fatal", "failed")):
                            logger.warning(f"[TVStreamer:CLI] {text}")
                        else:
                            logger.debug(f"[TVStreamer:CLI] {text}")

                asyncio.create_task(log_stderr(proc.stderr))

                while self._running:
                    line = await proc.stdout.readline()
                    if not line:
                        break

                    try:
                        data = json.loads(line.decode().strip())

                        # Handle multi-pane format (stream all)
                        if "panes" in data:
                            for pane in data["panes"]:
                                symbol = pane.get("symbol")
                                if symbol:
                                    clean_sym = symbol.split(":")[-1]
                                    await self._stream_to_redis(clean_sym, pane)
                                    await self._persist_to_questdb(clean_sym, pane)

                        # Handle single quote format (stream quote)
                        elif "symbol" in data:
                            symbol = data["symbol"]
                            clean_sym = symbol.split(":")[-1]
                            await self._stream_to_redis(clean_sym, data)
                            await self._persist_to_questdb(clean_sym, data)

                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.debug(f"[TVStreamer] Parse error: {e}")

                if proc.returncode is None:
                    proc.terminate()
                    await proc.wait()

                logger.warning("[TVStreamer] Stream process exited, restarting in 5s...")
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"[TVStreamer] Loop error: {e}")
                if proc and proc.returncode is None:
                    proc.terminate()
                await asyncio.sleep(5)

def get_tv_streamer(
    symbols: Optional[List[str]] = None, greeks_symbols: Optional[List[str]] = None
) -> TVStreamer:
    """Factory for TVStreamer singleton."""
    _symbols = symbols or ["MES", "MNQ", "MGC", "MCL"]
    return TVStreamer(_symbols, greeks_symbols)
