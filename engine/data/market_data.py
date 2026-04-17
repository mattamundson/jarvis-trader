"""
JARVIS TRADER — Market Data Layer
===================================
Unified interface to IBKR, Polygon, and Finnhub.
Data waterfall: IBKR → Polygon → CSV cache → structured None (no silent zeros).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from ib_async import Future
    from execution.schwab_connector import SchwabConnector

import pandas as pd

logger = logging.getLogger(__name__)

# Optional TradingView real-time feed — imported lazily so it never breaks startup
try:
    from data.tradingview_feed import TradingViewFeed as _TradingViewFeed
    _tv_feed = _TradingViewFeed()
except Exception:
    _tv_feed = None  # type: ignore[assignment]

# Continuous contract symbol mappings — single source of truth
# Polygon.io confirmed working symbols (tested 2026-04-05):
#   CL  = $85.41 ✅  (crude oil — proxy for MCL, same price different tick value)
#   NQ/ES/GC/MCL/MNQ/MES/MGC = no data on current plan ❌
# Micro futures use standard contract prices — tick value differs but price is identical.
FUTURES_MAP = {
    "MCL": "CL",   # Micro Crude Oil  → CL (same price, 1/10 contract size)
    "MNQ": "NQ",   # Micro Nasdaq-100 → NQ (same price, 1/10 contract size)
    "MES": "ES",   # Micro E-mini S&P → ES (same price, 1/10 contract size)
    "MGC": "GC",   # Micro Gold       → GC (same price, 1/10 contract size)
    "CL": "CL",
    "NQ": "NQ",
    "ES": "ES",
    "GC": "GC",
}

# ── Polygon Futures Map ─────────────────────────────────────────────────────
# DISABLED 2026-04-16 — incident: Polygon's `CL` ticker is Colgate-Palmolive
# Company stock (NYSE: CL, type=CS), NOT crude oil futures. Same trap exists
# for `NQ`, `ES`, `GC` (different stocks each, all NOT the futures you'd expect).
# The 2026-04-05 audit comment ("CL = $85.41 ✅ crude oil") was wrong — that
# $85.41 was Colgate-Palmolive's stock price, not crude.
#
# Polygon's free plan does NOT include futures data at all (only stocks/ETFs).
# To prevent silent data corruption (consumer-goods stock prices treated as
# crude oil ticks), this map is intentionally empty and callers MUST check
# POLYGON_FUTURES_BLOCKLIST before hitting Polygon.
#
# Re-enable only after subscribing to a Polygon plan that includes futures
# AND verifying the correct ticker format (e.g. `I:CL`, `C:CLF26`).
# See `docs/data-source-audit-2026-04-16.md` for the incident report and
# Task #15 (T1.5) for the backtest-metric contamination audit.
POLYGON_FUTURES_MAP: dict[str, str] = {
    # Empty by design. Adding a futures symbol here without verifying it
    # returns the correct underlying is a CRITICAL safety violation.
}

# Symbols Polygon free plan returns the WRONG asset for.
# Callers MUST check this set and skip Polygon for any match — empty result
# is preferred over silent stock-vs-futures data substitution.
POLYGON_FUTURES_BLOCKLIST: frozenset[str] = frozenset({
    "MCL", "MNQ", "MES", "MGC", "M2K", "MYM",
    "CL",  "NQ",  "ES",  "GC",  "RTY", "YM", "SI", "ZB", "ZN",
})

# Scale factors: micro price == standard price (same underlying price,
# just different notional/tick size), so factor is 1.0 for all.
FUTURES_SCALE_FACTOR = {
    "MCL": 1.0,  # CL and MCL track same crude price
    "MNQ": 1.0,  # NQ and MNQ track same Nasdaq price
    "MES": 1.0,  # ES and MES track same S&P price
    "MGC": 1.0,  # GC and MGC track same gold price
}

# Schwab-specific futures symbol map (Schwab uses slash-prefix)
SCHWAB_FUTURES_MAP = {
    "MCL": "/MCL",
    "MNQ": "/MNQ",
    "MES": "/MES",
    "MGC": "/MGC",
    "CL": "/CL",
    "NQ": "/NQ",
    "ES": "/ES",
    "GC": "/GC",
}

# IBKR exchange map for futures
FUTURES_EXCHANGE = {
    "MCL": "NYMEX",
    "CL": "NYMEX",
    "MNQ": "CME",
    "NQ": "CME",
    "MES": "CME",
    "ES": "CME",
    "MGC": "COMEX",
    "GC": "COMEX",
}


class MarketDataBar:
    """Normalized OHLCV bar regardless of data source"""

    def __init__(
        self,
        symbol: str,
        timestamp: datetime,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        source: str,
    ):
        self.symbol = symbol
        self.timestamp = timestamp
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.source = source


class IBKRDataConnector:
    """
    Connects to IB Gateway via ib_async.
    Paper mode: port 4002. Live: port 4001.
    Download IB Gateway: https://www.interactivebrokers.com/en/trading/ibgateway.php
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 4002, client_id: int = 1):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = None
        self._connected = False

    async def connect(self) -> bool:
        try:
            from ib_async import IB

            self._ib = IB()
            await self._ib.connectAsync(self._host, self._port, clientId=self._client_id)
            self._connected = True
            logger.info(f"IBKR connected {self._host}:{self._port} (paper={self._port == 4002})")
            return True
        except ImportError:
            logger.warning("ib_async not installed. Run: pip install ib_async")
            return False
        except Exception as e:
            logger.warning(f"IBKR connection failed: {e} — start IB Gateway on port {self._port}")
            return False

    async def disconnect(self):
        if self._ib and self._connected:
            self._ib.disconnect()
            self._connected = False

    def _make_contract(self, symbol: str, is_futures: bool):
        from ib_async import Future, Index, Stock

        if symbol.upper() in ("VIX",):
            return Index(symbol, "CBOE")
        if is_futures or symbol.upper() in FUTURES_MAP:
            exchange = FUTURES_EXCHANGE.get(symbol.upper(), "CME")
            return Future(symbol, exchange=exchange, currency="USD")
        return Stock(symbol, "SMART", "USD")

    async def _qualified_contract(self, symbol: str, is_futures: bool):
        """
        Return a contract usable for market-data requests (tickers, historical, streaming).
        IB requires conId for hashing/subscriptions; qualify generic symbols via the API.
        """
        from ib_async import Contract

        exchange = FUTURES_EXCHANGE.get(symbol.upper(), "CME")
        if is_futures or symbol.upper() in FUTURES_MAP:
            c: Contract = await self._resolve_front_month(symbol, exchange)
        else:
            c = self._make_contract(symbol, is_futures)
        cid = getattr(c, "conId", 0) or 0
        if cid > 0:
            return c
        try:
            qualified = await self._ib.qualifyContractsAsync(c)
            if qualified:
                return qualified[0]
        except Exception as e:
            logger.warning(f"qualifyContractsAsync failed for {symbol}: {e}")
        return c

    async def _resolve_front_month(self, symbol: str, exchange: str) -> Future:
        """Resolve futures symbol to the nearest expiry (front month) contract."""
        from ib_async import Future

        generic = Future(symbol, exchange=exchange, currency="USD")
        try:
            details = await self._ib.reqContractDetailsAsync(generic)
            if details:
                # Sort by expiry ascending, return the nearest (front month)
                details.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth)
                return details[0].contract
        except Exception as e:
            logger.warning(f"Could not resolve front month for {symbol}: {e}")
        return generic

    async def get_historical_bars(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "5 mins",
        is_futures: bool = False,
    ) -> pd.DataFrame:
        """Fetch historical OHLCV bars from IBKR."""
        if not self._connected:
            return pd.DataFrame()
        try:
            contract = await self._qualified_contract(symbol, is_futures)
            bars = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=False,
            )
            if not bars:
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {
                        "timestamp": bar.date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    }
                    for bar in bars
                ]
            )
        except Exception as e:
            logger.warning(f"IBKR get_historical_bars failed for {symbol}: {e}")
            return pd.DataFrame()

    async def get_snapshot_price(self, symbol: str, is_futures: bool = False) -> dict:
        """Return a real-time snapshot price dict from IBKR.

        Primary: reqTickersAsync for real-time L1 data.
        Fallback: last historical bar close (1 D / 1 hour bars) when ticker
        subscription is unavailable (IB Error 354 — market data not subscribed).
        Historical bars always work on the paper account.
        """
        if not self._connected:
            return {
                "last_price": None,
                "prev_close": None,
                "change_pct": None,
                "source": "ibkr_not_connected",
            }
        try:
            # For futures symbols, resolve to front month contract; otherwise use standard contract
            if is_futures or symbol.upper() in FUTURES_MAP:
                exchange = FUTURES_EXCHANGE.get(symbol.upper(), "CME")
                contract = await self._resolve_front_month(symbol, exchange)
            else:
                contract = self._make_contract(symbol, is_futures)
            tickers = await self._ib.reqTickersAsync(contract)
            if tickers:
                t = tickers[0]
                last = (
                    t.last
                    if t.last and t.last > 0
                    else (t.close if t.close and t.close > 0 else None)
                )
                prev = t.close if t.close and t.close > 0 else None
                change_pct = ((last - prev) / prev * 100) if last and prev and prev > 0 else None
                if last:
                    return {
                        "last_price": last,
                        "prev_close": prev,
                        "change_pct": change_pct,
                        "source": "ibkr",
                    }
        except Exception as e:
            logger.debug(f"IBKR reqTickersAsync failed for {symbol} (will try historical fallback): {e}")

        # Fallback: use last historical bar close (works even without L1 subscription)
        try:
            logger.info(f"IBKR snapshot fallback: fetching last historical close for {symbol}")
            bars_df = await self.get_historical_bars(
                symbol, duration="1 D", bar_size="1 hour", is_futures=is_futures
            )
            if not bars_df.empty and "close" in bars_df.columns:
                last_close = float(bars_df.iloc[-1]["close"])
                prev_close = float(bars_df.iloc[-2]["close"]) if len(bars_df) >= 2 else None
                change_pct = (
                    ((last_close - prev_close) / prev_close * 100) if prev_close else None
                )
                logger.info(f"IBKR historical fallback price for {symbol}: {last_close}")
                return {
                    "last_price": last_close,
                    "prev_close": prev_close,
                    "change_pct": change_pct,
                    "source": "ibkr_historical",
                }
        except Exception as e2:
            logger.warning(f"IBKR historical fallback also failed for {symbol}: {e2}")

        return {
            "last_price": None,
            "prev_close": None,
            "change_pct": None,
            "source": "ibkr_error",
        }

    async def subscribe_real_time(
        self,
        symbol: str,
        callback: Callable[[MarketDataBar], None],
        is_futures: bool = False,
    ):
        """Subscribe to real-time 5-second streaming bars."""
        if not self._connected:
            logger.error("Not connected to IBKR")
            return
        try:
            contract = await self._qualified_contract(symbol, is_futures)
            bars = self._ib.reqRealTimeBars(contract, 5, "TRADES", False)
            bars.updateEvent += lambda bars, hasNewBar: (
                callback(
                    MarketDataBar(
                        symbol=symbol,
                        timestamp=datetime.fromtimestamp(bars[-1].time),
                        open=bars[-1].open_,
                        high=bars[-1].high,
                        low=bars[-1].low,
                        close=bars[-1].close,
                        volume=bars[-1].volume,
                        source="IBKR",
                    )
                )
                if hasNewBar
                else None
            )
        except Exception as e:
            logger.warning(f"IBKR subscribe_real_time failed for {symbol}: {e}")

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def health_check(self) -> dict:
        return {
            "status": "connected" if self._connected else "disconnected",
            "mode": "live" if self._port == 4001 else "paper",
            "port": self._port,
            "host": self._host,
            "client_id": self._client_id,
        }


class PolygonDataConnector:
    """
    Polygon.io market data — historical OHLCV bars and price snapshots.
    Requires POLYGON_API_KEY in .env. Free tier: 5 API calls/min.
    """

    # Class-level rate limiter shared across all instances
    _call_timestamps: list[float] = []
    _RATE_LIMIT = 4          # conservative (free tier = 5/min)
    _RATE_WINDOW = 60.0
    # Simple sync cache: {key: {"data": ..., "ts": float}}
    _cache: dict[str, dict] = {}
    _CACHE_TTL = 60.0

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = None

    def _check_rate_limit(self) -> bool:
        """Return True if we can make a call. Logs and returns False if throttled."""
        now = time.time()
        self._call_timestamps[:] = [t for t in self._call_timestamps if now - t < self._RATE_WINDOW]
        if len(self._call_timestamps) >= self._RATE_LIMIT:
            wait = self._RATE_WINDOW - (now - self._call_timestamps[0])
            logger.warning(f"[polygon] Rate guard: {len(self._call_timestamps)} calls in 60s, next slot in {wait:.0f}s")
            return False
        self._call_timestamps.append(now)
        return True

    def _cache_get(self, key: str) -> dict | None:
        """Return cached data if within TTL, else None."""
        entry = self._cache.get(key)
        if entry and (time.time() - entry["ts"]) < self._CACHE_TTL:
            return entry["data"]
        return None

    def _cache_get_expired(self, key: str) -> dict | None:
        """Return cached data even if expired (429 fallback)."""
        entry = self._cache.get(key)
        return entry["data"] if entry else None

    def _cache_set(self, key: str, data) -> None:
        self._cache[key] = {"data": data, "ts": time.time()}

    def connect(self):
        try:
            from polygon import RESTClient

            self._client = RESTClient(self._api_key)
            logger.info("Polygon.io connected")
        except ImportError:
            logger.warning("polygon-api-client not installed. Run: pip install polygon-api-client")

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def get_historical_bars(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        timespan: str = "minute",
        multiplier: int = 5,
    ) -> pd.DataFrame:
        """Fetch OHLCV bars. timespan: minute/hour/day. multiplier: 1/5/15/60."""
        if not self._client:
            return pd.DataFrame()

        cache_key = f"bars:{symbol}:{multiplier}:{timespan}:{from_date}:{to_date}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        if not self._check_rate_limit():
            expired = self._cache_get_expired(cache_key)
            if expired is not None:
                logger.info(f"[polygon] Returning expired cache for {symbol} bars (rate limited)")
                return expired
            return pd.DataFrame()

        bars = []
        try:
            for agg in self._client.list_aggs(
                symbol, multiplier, timespan, from_date, to_date, limit=50000
            ):
                bars.append(
                    {
                        "timestamp": datetime.fromtimestamp(agg.timestamp / 1000),
                        "open": agg.open,
                        "high": agg.high,
                        "low": agg.low,
                        "close": agg.close,
                        "volume": agg.volume,
                    }
                )
        except Exception as e:
            error_str = str(e).lower()
            if "429" in str(e) or "too many" in error_str:
                logger.warning(f"[polygon] 429 rate limit for {symbol} bars — returning expired cache")
                expired = self._cache_get_expired(cache_key)
                return expired if expired is not None else pd.DataFrame()
            logger.warning(f"Polygon get_historical_bars failed for {symbol}: {e}")
            return pd.DataFrame()
        result = pd.DataFrame(bars)
        if not result.empty:
            self._cache_set(cache_key, result)
        return result

    def get_last_price(self, symbol: str) -> dict:
        """Get latest price via most recent 1-minute bar. Works for equities and futures."""
        if not self._client:
            return {"last_price": None, "prev_close": None, "change_pct": None, "source": "polygon_unavailable"}

        cache_key = f"price:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return {**cached, "source": "polygon_cache"}

        if not self._check_rate_limit():
            expired = self._cache_get_expired(cache_key)
            if expired:
                return {**expired, "source": "polygon_cache_expired"}
            return {"last_price": None, "prev_close": None, "change_pct": None, "source": "polygon_rate_limited"}

        try:
            today = datetime.now().strftime("%Y-%m-%d")
            two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

            recent_bars = list(
                self._client.list_aggs(symbol, 1, "minute", two_days_ago, today, limit=10)
            )
            if not recent_bars:
                return {"last_price": None, "prev_close": None, "change_pct": None, "source": "polygon_empty"}

            last_price = float(recent_bars[-1].close)
            prev_bars = list(
                self._client.list_aggs(symbol, 1, "day", three_days_ago, two_days_ago, limit=2)
            )
            prev_close = float(prev_bars[-1].close) if prev_bars else None
            change_pct = ((last_price - prev_close) / prev_close * 100) if prev_close else None

            result = {"last_price": last_price, "prev_close": prev_close, "change_pct": change_pct, "source": "polygon"}
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            error_str = str(e).lower()
            if "429" in str(e) or "too many" in error_str:
                logger.warning(f"[polygon] 429 rate limit for {symbol} price — returning expired cache")
                expired = self._cache_get_expired(cache_key)
                if expired:
                    return {**expired, "source": "polygon_cache_expired"}
                return {"last_price": None, "prev_close": None, "change_pct": None, "source": "polygon_rate_limited"}
            logger.warning(f"Polygon get_last_price failed for {symbol}: {e}")
            return {"last_price": None, "prev_close": None, "change_pct": None, "source": "polygon_error"}

    def get_vix_value(self) -> dict:
        """Get VIX index value. Polygon indices use 'I:VIX' ticker."""
        if not self._client:
            return {"value": None, "source": "polygon_unavailable"}
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            bars = list(self._client.list_aggs("I:VIX", 1, "day", yesterday, today, limit=2))
            if bars:
                return {"value": float(bars[-1].close), "source": "polygon"}
        except Exception as e:
            logger.warning(f"Polygon get_vix_value failed: {e}")
        return {"value": None, "source": "polygon_error"}

    def get_options_expirations(self, symbol: str) -> list:
        """List available options expiration dates for an underlying symbol."""
        if not self._client:
            return []
        try:
            contracts = self._client.list_options_contracts(symbol, limit=500)
            expirations = sorted(
                {c.expiration_date for c in contracts if hasattr(c, "expiration_date")}
            )
            return expirations
        except Exception as e:
            logger.warning(f"Polygon get_options_expirations failed for {symbol}: {e}")
            return []


class FinnhubConnector:
    """Finnhub for news and sentiment. Free tier: 60 calls/min."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = None

    def connect(self):
        try:
            import finnhub

            self._client = finnhub.Client(api_key=self._api_key)
            logger.info("Finnhub connected")
        except ImportError:
            logger.warning("finnhub-python not installed. Run: pip install finnhub-python")

    def get_news_sentiment(self, symbol: str) -> dict:
        if not self._client:
            return {}
        try:
            return self._client.news_sentiment(symbol)
        except Exception as e:
            logger.error(f"Finnhub sentiment error for {symbol}: {e}")
            return {}

    def get_company_news(self, symbol: str, from_date: str, to_date: str) -> list:
        if not self._client:
            return []
        try:
            return self._client.company_news(symbol, _from=from_date, to=to_date)
        except Exception as e:
            logger.error(f"Finnhub news error for {symbol}: {e}")
            return []


class RedditSentimentConnector:
    """Reddit sentiment via ApeWisdom API (free, no auth)."""

    APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/{filter}/page/{page}"

    async def get_trending_tickers(self, filter_name: str = "all-stocks") -> list:
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                url = self.APEWISDOM_URL.format(filter=filter_name, page=1)
                resp = await client.get(url, timeout=10)
                return resp.json().get("results", [])
        except Exception as e:
            logger.error(f"ApeWisdom error: {e}")
            return []


class MarketDataManager:
    """
    Unified market data access for all agents.
    Waterfall: IBKR → Polygon → CSV cache → structured None (no silent zeros).
    """

    # Single source of truth for all futures mappings
    FUTURES_MAP = FUTURES_MAP

    def __init__(self, config):
        self._config = config
        self.ibkr: Optional[IBKRDataConnector] = None
        self.schwab: Optional["SchwabConnector"] = None
        self.polygon: Optional[PolygonDataConnector] = None
        self.finnhub: Optional[FinnhubConnector] = None
        self.reddit = RedditSentimentConnector()

    def inject_schwab(self, connector: "SchwabConnector") -> None:
        """Wire in a SchwabConnector at startup (called from main.py after Schwab connects)."""
        self.schwab = connector
        logger.info("MarketDataManager: SchwabConnector injected as Tier 2 data source")

    async def initialize(self):
        """Connect to all available data sources."""
        self.ibkr = IBKRDataConnector(
            host=self._config.IBKR_HOST,
            port=self._config.IBKR_PORT,
            client_id=self._config.IBKR_CLIENT_ID,
        )
        ibkr_connected = await self.ibkr.connect()
        if not ibkr_connected:
            logger.warning(
                "IBKR not connected — start IB Gateway (port 4002 paper, 4001 live). "
                "Data will fall back to Polygon."
            )

        if self._config.POLYGON_API_KEY:
            self.polygon = PolygonDataConnector(self._config.POLYGON_API_KEY)
            self.polygon.connect()
        else:
            logger.warning("POLYGON_API_KEY not set — set it in .env for price data fallback.")

        if self._config.FINNHUB_API_KEY:
            self.finnhub = FinnhubConnector(self._config.FINNHUB_API_KEY)
            self.finnhub.connect()

        logger.info(
            f"Market data initialized: IBKR={'connected' if ibkr_connected else 'offline'}, "
            f"Polygon={'connected' if self.polygon else 'not configured'}"
        )

    async def get_bars(
        self,
        symbol: str,
        lookback_days: int = 30,
        timeframe: str = "5m",
        is_futures: bool = False,
    ) -> pd.DataFrame:
        """
        Get OHLCV bars. Waterfall: IBKR → Polygon → CSV cache.
        Returns empty DataFrame if all sources unavailable.
        """
        is_futures = is_futures or symbol.upper() in FUTURES_MAP

        # Tier 1: IBKR
        if self.ibkr and self.ibkr.is_connected:
            duration_map = [(1, "1 D"), (7, "1 W"), (30, "1 M"), (90, "3 M"), (365, "1 Y")]
            duration = next((v for k, v in duration_map if lookback_days <= k), "1 M")
            bar_size_map = {
                "1m": "1 min",
                "5m": "5 mins",
                "15m": "15 mins",
                "1h": "1 hour",
                "4h": "4 hours",
                "1d": "1 day",
            }
            bar_size = bar_size_map.get(timeframe, "5 mins")
            df = await self.ibkr.get_historical_bars(symbol, duration, bar_size, is_futures)
            if not df.empty:
                logger.info(f"IBKR returned {len(df)} bars for {symbol}")
                return df

        # Tier 2: Polygon — SKIPPED for futures (Polygon free plan returns
        # the wrong asset, e.g. `CL` = Colgate-Palmolive stock, not crude oil).
        # See POLYGON_FUTURES_BLOCKLIST docstring for incident details.
        if self.polygon and symbol.upper() not in POLYGON_FUTURES_BLOCKLIST:
            from_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            to_date = datetime.now().strftime("%Y-%m-%d")
            tf_map = {
                "1m": ("minute", 1),
                "5m": ("minute", 5),
                "15m": ("minute", 15),
                "1h": ("hour", 1),
                "4h": ("hour", 4),
                "1d": ("day", 1),
            }
            timespan, multiplier = tf_map.get(timeframe, ("minute", 5))
            polygon_symbol = POLYGON_FUTURES_MAP.get(symbol.upper(), symbol)
            df = self.polygon.get_historical_bars(
                polygon_symbol, from_date, to_date, timespan, multiplier
            )
            if not df.empty:
                logger.info(f"Polygon returned {len(df)} bars for {symbol}")
                return df
            logger.warning(f"Polygon returned no data for {symbol} ({timespan}/{multiplier})")
        elif self.polygon and symbol.upper() in POLYGON_FUTURES_BLOCKLIST:
            logger.debug(
                f"[market_data] Polygon SKIPPED for {symbol} (futures — see incident 2026-04-16)"
            )

        # Tier 3: CSV backtest cache — staleness guard: reject if last bar > 2 days old
        df = self._load_csv_cache(symbol, timeframe, lookback_days)
        if not df.empty:
            if "timestamp" in df.columns:
                last_ts = pd.to_datetime(df["timestamp"].iloc[-1])
                staleness_days = (datetime.now() - last_ts.replace(tzinfo=None)).days
                if staleness_days > 2:
                    logger.warning(
                        f"[{symbol}] CSV cache for {timeframe} is {staleness_days}d stale "
                        f"(last bar: {last_ts.date()}) — skipping to avoid stale signal contamination"
                    )
                    df = pd.DataFrame()
            if not df.empty:
                return df

        logger.error(
            f"All data sources failed for {symbol} — IBKR offline and Polygon unavailable."
        )
        return pd.DataFrame()

    async def get_current_price(self, symbol: str, is_futures: bool = False) -> dict:
        """
        Get latest price. Returns {last_price, prev_close, change_pct, source}.
        Never returns silent 0.0 — None means genuinely unavailable.
        """
        is_futures = is_futures or symbol.upper() in FUTURES_MAP

        # Tier 1: IBKR
        if self.ibkr and self.ibkr.is_connected:
            result = await self.ibkr.get_snapshot_price(symbol, is_futures)
            if result.get("last_price"):
                return result

        # Tier 2: Schwab (real-time quotes, no historical bars)
        if self.schwab is not None and self.schwab.is_connected:
            try:
                schwab_sym = SCHWAB_FUTURES_MAP.get(symbol.upper(), symbol)
                quotes = await self.schwab.get_quotes([schwab_sym])
                quote = quotes.get(schwab_sym) or quotes.get(symbol)
                if quote:
                    price = quote.get("last") or quote.get("mark")
                    if price:
                        change_pct = quote.get("change_pct")
                        logger.info(f"Schwab Tier 2 price for {symbol} ({schwab_sym}): {price}")
                        return {
                            "last_price": float(price),
                            "prev_close": None,
                            "change_pct": float(change_pct) if change_pct is not None else None,
                            "source": "schwab",
                        }
            except Exception as _schwab_err:
                logger.debug(f"Schwab Tier 2 failed for {symbol}: {_schwab_err}")
        elif self.schwab is not None and not self.schwab.is_connected:
            logger.debug(f"Schwab not connected — skipping Tier 2 for {symbol}")

        # Tier 2.5: TradingView Desktop (optional — only when CDP connected)
        if _tv_feed is not None and _tv_feed.is_available():
            try:
                # Map micro futures to TradingView continuous contract symbols
                tv_symbol_map = {
                    "MCL": "MCL1!", "MNQ": "MNQ1!", "MES": "MES1!", "MGC": "MGC1!",
                    "CL": "CL1!", "NQ": "NQ1!", "ES": "ES1!", "GC": "GC1!",
                }
                tv_symbol = tv_symbol_map.get(symbol.upper(), symbol)
                quote = _tv_feed.get_quote(tv_symbol)
                if quote and quote.get("close"):
                    logger.info(f"TradingView Tier 2.5 price for {symbol}: {quote['close']}")
                    return {
                        "last_price": float(quote["close"]),
                        "prev_close": None,
                        "change_pct": None,
                        "source": "tradingview",
                    }
            except Exception as _tv_err:
                logger.debug(f"TradingView Tier 2.5 failed for {symbol}: {_tv_err}")

        # Tier 3: Polygon — SKIPPED for futures (returns wrong asset on free plan).
        # See POLYGON_FUTURES_BLOCKLIST. Stocks/ETFs still flow through.
        if self.polygon and symbol.upper() not in POLYGON_FUTURES_BLOCKLIST:
            polygon_symbol = POLYGON_FUTURES_MAP.get(symbol.upper(), symbol)
            result = self.polygon.get_last_price(polygon_symbol)
            if result.get("last_price"):
                return result
        elif self.polygon and symbol.upper() in POLYGON_FUTURES_BLOCKLIST:
            logger.debug(
                f"[market_data] Polygon last_price SKIPPED for {symbol} "
                f"(futures — see incident 2026-04-16)"
            )

        # Tier 4: CSV cache last close
        df = self._load_csv_cache(symbol, "1d", 2)
        if not df.empty and "close" in df.columns:
            last_close = float(df.iloc[-1]["close"])
            return {
                "last_price": last_close,
                "prev_close": None,
                "change_pct": None,
                "source": "csv_cache",
            }

        return {"last_price": None, "prev_close": None, "change_pct": None, "source": "unavailable"}

    async def get_batch_prices(self, symbols: list) -> dict:
        """Get current prices for multiple symbols. Returns {symbol: price_dict}."""
        results = {}
        for symbol in symbols:
            results[symbol] = await self.get_current_price(symbol)
        return results

    async def get_vix(self) -> dict:
        """
        Get VIX index value. Returns {value, source}.
        Waterfall: FRED → IBKR → Polygon.
        """
        # Tier 1: FRED (VIXCLS series — most reliable, free)
        try:
            from data.fred_data import FREDDataService

            fred = FREDDataService(getattr(self._config, "FRED_API_KEY", None))
            vix_val = await fred.get_latest_value("VIXCLS")
            if vix_val is not None:
                return {"value": float(vix_val), "source": "fred"}
        except Exception:
            pass

        # Tier 2: IBKR Index("VIX")
        if self.ibkr and self.ibkr.is_connected:
            result = await self.ibkr.get_snapshot_price("VIX", is_futures=False)
            if result.get("last_price"):
                return {"value": result["last_price"], "source": "ibkr"}

        # Tier 3: Polygon I:VIX
        if self.polygon:
            result = self.polygon.get_vix_value()
            if result.get("value"):
                return result

        return {"value": None, "source": "unavailable"}

    async def get_options_expirations(self, symbol: str) -> list:
        """
        Get available options expiration dates for a symbol.
        Waterfall: IBKR → Polygon.
        """
        # Tier 1: IBKR reqSecDefOptParams
        if self.ibkr and self.ibkr.is_connected:
            try:
                from ib_async import Stock

                contract = Stock(symbol, "SMART", "USD")
                chains = await self._ibkr_ib.reqSecDefOptParamsAsync(
                    "", "", contract.secType, contract.conId
                )
                if chains:
                    expirations = sorted(chains[0].expirations)
                    return list(expirations)
            except Exception as e:
                logger.warning(f"IBKR get_options_expirations failed for {symbol}: {e}")

        # Tier 2: Polygon
        if self.polygon:
            return self.polygon.get_options_expirations(symbol)

        return []

    def _load_csv_cache(self, symbol: str, timeframe: str, lookback_days: int) -> pd.DataFrame:
        """Load from CSV backtest cache as offline fallback."""
        try:
            cache_dir = Path(__file__).parent.parent / "backtest" / "cache"
            matches = sorted(cache_dir.glob(f"{symbol}_*_{timeframe}.csv"))
            if not matches:
                return pd.DataFrame()
            df = pd.read_csv(matches[-1])
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.sort_values("timestamp")
            bars_per_day = {"1m": 390, "5m": 78, "15m": 26, "1h": 24, "4h": 6, "1d": 1}.get(timeframe, 24)
            df = df.tail(lookback_days * bars_per_day).copy()
            if not df.empty:
                logger.warning(f"[{symbol}] Using CSV cache: {matches[-1].name} ({len(df)} bars)")
            cols = [
                c
                for c in ["timestamp", "open", "high", "low", "close", "volume"]
                if c in df.columns
            ]
            return df[cols] if cols else pd.DataFrame()
        except Exception as e:
            logger.debug(f"[{symbol}] CSV cache load failed: {e}")
            return pd.DataFrame()
