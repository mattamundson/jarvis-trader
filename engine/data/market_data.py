"""
JARVIS TRADER — Market Data Layer
===================================
Unified interface to IBKR, Schwab, Polygon, and Finnhub.
All streaming goes through Redis for agent consumption.
"""
import logging
from datetime import datetime, timedelta
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class MarketDataBar:
    """Normalized OHLCV bar regardless of data source"""
    def __init__(self, symbol: str, timestamp: datetime, open: float, high: float,
                 low: float, close: float, volume: float, source: str):
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
    Requires IB Gateway or TWS running on localhost.
    Paper mode: port 4002. Live: port 4001.
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
            logger.info(f"✅ IBKR connected to {self._host}:{self._port} (paper={self._port == 4002})")
            return True
        except ImportError:
            logger.warning("ib_async not installed. Run: pip install ib_async")
            return False
        except Exception as e:
            logger.error(f"❌ IBKR connection failed: {e}")
            logger.info("Ensure IB Gateway is running. Download from: https://www.interactivebrokers.com/en/trading/ibgateway.php")
            return False

    async def disconnect(self):
        if self._ib and self._connected:
            self._ib.disconnect()
            self._connected = False

    async def get_historical_bars(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "5 mins",
        is_futures: bool = False,
        exchange: str = "CME",
    ) -> pd.DataFrame:
        """Fetch historical OHLCV bars from IBKR"""
        if not self._connected:
            return pd.DataFrame()

        from ib_async import Future, Stock

        if is_futures:
            contract = Future(symbol, exchange=exchange)
        else:
            contract = Stock(symbol, "SMART", "USD")

        bars = await self._ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
        )

        if not bars:
            return pd.DataFrame()

        return pd.DataFrame([{
            "timestamp": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        } for bar in bars])

    async def subscribe_real_time(
        self,
        symbol: str,
        callback: Callable[[MarketDataBar], None],
        is_futures: bool = False,
    ):
        """Subscribe to real-time streaming bars"""
        if not self._connected:
            logger.error("Not connected to IBKR")
            return

        from ib_async import Future, Stock

        if is_futures:
            contract = Future(symbol, exchange="CME")
        else:
            contract = Stock(symbol, "SMART", "USD")

        bars = self._ib.reqRealTimeBars(contract, 5, "TRADES", False)
        bars.updateEvent += lambda bars, hasNewBar: (
            callback(MarketDataBar(
                symbol=symbol,
                timestamp=datetime.fromtimestamp(bars[-1].time),
                open=bars[-1].open_,
                high=bars[-1].high,
                low=bars[-1].low,
                close=bars[-1].close,
                volume=bars[-1].volume,
                source="IBKR",
            )) if hasNewBar else None
        )

    @property
    def is_connected(self) -> bool:
        return self._connected


class PolygonDataConnector:
    """
    Polygon.io market data — historical and real-time.
    Requires POLYGON_API_KEY in .env
    """

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = None

    def connect(self):
        try:
            from polygon import RESTClient
            self._client = RESTClient(self._api_key)
            logger.info("✅ Polygon.io connected")
        except ImportError:
            logger.warning("polygon-api-client not installed. Run: pip install polygon-api-client")

    def get_historical_bars(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        timespan: str = "minute",
        multiplier: int = 5,
    ) -> pd.DataFrame:
        """Fetch OHLCV bars. timespan: minute/hour/day. multiplier: 1/5/15/60"""
        if not self._client:
            return pd.DataFrame()

        bars = []
        try:
            for agg in self._client.list_aggs(
                symbol,
                multiplier,
                timespan,
                from_date,
                to_date,
                limit=50000,
            ):
                bars.append({
                    "timestamp": datetime.fromtimestamp(agg.timestamp / 1000),
                    "open": agg.open,
                    "high": agg.high,
                    "low": agg.low,
                    "close": agg.close,
                    "volume": agg.volume,
                })
        except Exception as e:
            logger.warning(f"Polygon request failed for {symbol}: {e}. Falling back to next source.")
            return pd.DataFrame()

        return pd.DataFrame(bars)


class FinnhubConnector:
    """Finnhub for news and sentiment. Free tier available."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = None

    def connect(self):
        try:
            import finnhub
            self._client = finnhub.Client(api_key=self._api_key)
            logger.info("✅ Finnhub connected")
        except ImportError:
            logger.warning("finnhub-python not installed. Run: pip install finnhub-python")

    def get_news_sentiment(self, symbol: str) -> dict:
        """Get news sentiment score for a symbol"""
        if not self._client:
            return {}
        try:
            return self._client.news_sentiment(symbol)
        except Exception as e:
            logger.error(f"Finnhub sentiment error for {symbol}: {e}")
            return {}

    def get_company_news(self, symbol: str, from_date: str, to_date: str) -> list[dict]:
        """Get recent news articles for a symbol"""
        if not self._client:
            return []
        try:
            return self._client.company_news(symbol, _from=from_date, to=to_date)
        except Exception as e:
            logger.error(f"Finnhub news error for {symbol}: {e}")
            return []


class RedditSentimentConnector:
    """
    Reddit sentiment via ApeWisdom API (free, no auth required).
    Tracks r/wallstreetbets, r/stocks, r/options, r/investing mentions.
    """

    APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/{filter}/page/{page}"

    async def get_trending_tickers(self, filter_name: str = "all-stocks") -> list[dict]:
        """
        Get trending stock tickers from Reddit.
        filter_name: 'all-stocks', 'wallstreetbets', 'stocks', 'options'
        Returns list of {ticker, mentions, upvotes, rank, rank_24h_ago}
        """
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                url = self.APEWISDOM_URL.format(filter=filter_name, page=1)
                resp = await client.get(url, timeout=10)
                data = resp.json()
                return data.get("results", [])
        except Exception as e:
            logger.error(f"ApeWisdom error: {e}")
            return []


class MarketDataManager:
    """
    Unified market data access point for all agents.
    Handles connection lifecycle and data normalization.
    """

    def __init__(self, config):
        self._config = config
        self.ibkr: Optional[IBKRDataConnector] = None
        self.polygon: Optional[PolygonDataConnector] = None
        self.finnhub: Optional[FinnhubConnector] = None
        self.reddit = RedditSentimentConnector()

    async def initialize(self):
        """Connect to all available data sources"""
        # IBKR (primary — requires IB Gateway running)
        self.ibkr = IBKRDataConnector(
            host=self._config.IBKR_HOST,
            port=self._config.IBKR_PORT,
            client_id=self._config.IBKR_CLIENT_ID,
        )
        ibkr_connected = await self.ibkr.connect()
        if not ibkr_connected:
            logger.warning(
                "IBKR not connected. Start IB Gateway first.\n"
                "  Paper mode: port 4002\n"
                "  Live mode:  port 4001\n"
                "  Download:   https://www.interactivebrokers.com/en/trading/ibgateway.php"
            )

        # Polygon.io (historical + real-time streaming)
        if self._config.POLYGON_API_KEY:
            self.polygon = PolygonDataConnector(self._config.POLYGON_API_KEY)
            self.polygon.connect()

        # Finnhub (news + sentiment)
        if self._config.FINNHUB_API_KEY:
            self.finnhub = FinnhubConnector(self._config.FINNHUB_API_KEY)
            self.finnhub.connect()

        logger.info(f"Market data initialized. IBKR={'✅' if ibkr_connected else '⚠️ (not connected)'}")

    async def get_bars(
        self,
        symbol: str,
        lookback_days: int = 30,
        timeframe: str = "5m",
        is_futures: bool = False,
    ) -> pd.DataFrame:
        """
        Get OHLCV bars. Tries IBKR first, falls back to Polygon.
        """
        # Try IBKR first
        if self.ibkr and self.ibkr.is_connected:
            duration_map = {1: "1 D", 7: "1 W", 30: "1 M", 90: "3 M", 365: "1 Y"}
            bar_size_map = {"1m": "1 min", "5m": "5 mins", "15m": "15 mins", "1h": "1 hour", "1d": "1 day"}
            duration = next((v for k, v in duration_map.items() if lookback_days <= k), "1 M")
            bar_size = bar_size_map.get(timeframe, "5 mins")
            df = await self.ibkr.get_historical_bars(symbol, duration, bar_size, is_futures)
            if not df.empty:
                return df

        # Fall back to Polygon
        if self.polygon:
            from_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            to_date = datetime.now().strftime("%Y-%m-%d")
            tf_map = {"1m": ("minute", 1), "5m": ("minute", 5), "15m": ("minute", 15),
                      "1h": ("hour", 1), "1d": ("day", 1)}
            timespan, multiplier = tf_map.get(timeframe, ("minute", 5))
            df = self.polygon.get_historical_bars(symbol, from_date, to_date, timespan, multiplier)
            if not df.empty:
                return df

        # Last resort: yfinance (free, delayed)
        logger.warning(f"Using yfinance for {symbol} (delayed data)")
        try:
            import yfinance as yf
            period_map = {7: "7d", 30: "1mo", 90: "3mo", 365: "1y"}
            period = next((v for k, v in period_map.items() if lookback_days <= k), "1mo")
            interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1d": "1d"}
            yf_interval = interval_map.get(timeframe, "5m")
            ticker = yf.Ticker(symbol)

            # Try requested interval first; fall back to daily if rate-limited
            df = ticker.history(period=period, interval=yf_interval)
            if df.empty and yf_interval != "1d":
                logger.warning(f"yfinance rate-limited for {yf_interval} — falling back to 1d")
                df = ticker.history(period="1y", interval="1d")

            if df.empty:
                return pd.DataFrame()

            df = df.reset_index().rename(columns={
                "Datetime": "timestamp", "Date": "timestamp",
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume"
            })
            cols = [c for c in ["timestamp", "open", "high", "low", "close", "volume"] if c in df.columns]
            return df[cols]
        except Exception as e:
            logger.error(f"yfinance fallback failed for {symbol}: {e}")
            return pd.DataFrame()
