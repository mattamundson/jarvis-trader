"""
JARVIS TRADER — Social Analyst Agent
======================================
Fetches retail sentiment data from ApeWisdom (Reddit trending tickers) and
optional StockTwits data, then uses an LLM to produce a structured social
sentiment signal.

Refresh interval: every 30 minutes.
Model: Claude Haiku (claude-haiku-4-5-20251001) — lightweight task
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

__all__ = ["SocialAnalystAgent", "SocialReport"]

# ApeWisdom endpoint — no authentication required
APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks"

# Futures-specific subreddit routing
FUTURES_SUBREDDIT_MAP: dict[str, list[str]] = {
    "MES": ["FuturesTrading", "emini", "wallstreetbets"],
    "MNQ": ["FuturesTrading", "emini", "wallstreetbets"],
    "MCL": ["energy", "oilandgas"],
    "MGC": ["investing", "Economics"],
}
DEFAULT_SUBREDDITS = ["investing", "Economics"]

# Futures instrument descriptions for LLM context
FUTURES_DESCRIPTIONS: dict[str, str] = {
    "MES": "Micro E-mini S&P 500 futures (MES) — $5/point, tracks the S&P 500 index",
    "MNQ": "Micro E-mini Nasdaq 100 futures (MNQ) — $2/point, tracks the Nasdaq 100 index",
    "MCL": "Micro WTI Crude Oil futures (MCL) — $100/point, tracks crude oil spot price",
    "MGC": "Micro Gold futures (MGC) — $10/point, tracks gold spot price",
}


@dataclass
class SocialReport:
    """Structured output from the Social Analyst agent"""

    symbol: str
    timestamp: datetime

    # Signal: -1.0 (strongly bearish sentiment) to +1.0 (strongly bullish sentiment)
    signal: float
    confidence: float  # 0.0 to 1.0

    # Social metrics
    mention_count: int
    rank: int  # Rank in trending list; 0 = not found

    # Trend direction based on rank/mention movement
    trend: str  # "rising" | "falling" | "stable"

    summary: str = ""
    reasoning: str = ""

    # Futures/options positioning bias — "bullish" | "bearish" | "neutral" | "unknown"
    contract_bias: str = "unknown"

    # Data quality indicator — "ok" | "partial" | "unavailable"
    data_quality: str = "ok"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "signal": self.signal,
            "confidence": self.confidence,
            "mention_count": self.mention_count,
            "rank": self.rank,
            "trend": self.trend,
            "summary": self.summary,
            "reasoning": self.reasoning,
            "contract_bias": self.contract_bias,
            "data_quality": self.data_quality,
        }


class SocialAnalystAgent:
    """
    Aggregates Reddit (via ApeWisdom) and optional StockTwits retail sentiment
    for a given symbol and synthesizes it into a trading signal via LLM.

    If the symbol is not found in trending data, returns a neutral signal (0.0)
    with low confidence (0.2) — absence of social buzz is itself informative.
    """

    SYSTEM_PROMPT = """You are a retail sentiment analyst for JARVIS TRADER,
an autonomous trading system.

Analyze the provided social media metrics for the given ticker symbol.
Your task:
1. Assess the overall bullish or bearish sentiment implied by the social data
2. Determine whether the trend is rising, falling, or stable
3. Produce a signal score (-1.0 to +1.0) where positive means bullish retail sentiment
4. Assign a confidence score (0.0 to 1.0) — lower if data is sparse or symbol is not trending
5. Estimate contract_bias from any futures/options positioning language in the data
   ("bullish" | "bearish" | "neutral" | "unknown")

Important: High social buzz does NOT always mean bullish. Consider context.
Meme/momentum tickers with very high ranks and rising mentions may indicate
short-squeeze potential (bullish) OR overextension risk (bearish).

For FUTURES instruments, note that equity Reddit sentiment is directionally
relevant but position sizing norms differ from stock trading communities.

Respond with valid JSON only. Do not add any explanation outside the JSON.
"""

    def __init__(self, llm_client, stocktwits_token: Optional[str] = None):
        """
        Args:
            llm_client: Object with .api_key attribute (Anthropic key).
            stocktwits_token: Optional StockTwits OAuth token for additional data.
        """
        self._llm = llm_client
        self._stocktwits_token = stocktwits_token or os.getenv("STOCKTWITS_TOKEN", "")

    async def analyze(self, symbol: str) -> "SocialReport":
        """Full social sentiment analysis pipeline for a symbol"""

        # Determine futures-specific subreddits for context annotation
        subreddits = FUTURES_SUBREDDIT_MAP.get(symbol.upper(), DEFAULT_SUBREDDITS)
        is_futures = symbol.upper() in FUTURES_SUBREDDIT_MAP

        # 1. Fetch trending data from ApeWisdom
        trending_data = await self._fetch_apewisdom()

        # 2. Find symbol in trending list
        symbol_data = self._find_symbol(symbol, trending_data)

        # 3. Optionally enrich with StockTwits
        stocktwits_data = await self._fetch_stocktwits(symbol) if self._stocktwits_token else None

        # 4. Enrich with JARVIS engine reddit sentiment (processed/cached)
        engine_reddit_data = await self._fetch_engine_reddit_sentiment()

        # 5. Fetch news sentiment for this symbol
        news_sentiment = await self._fetch_engine_news_sentiment(symbol)

        # 6. If no data found at all, return neutral
        if symbol_data is None and stocktwits_data is None and not engine_reddit_data and not news_sentiment:
            logger.info(f"{symbol} not found in social trending data — returning neutral")
            return self._neutral_report(symbol)

        # 7. LLM synthesis
        report = await self._llm_synthesize(
            symbol, symbol_data, stocktwits_data, trending_data,
            engine_reddit_data=engine_reddit_data,
            news_sentiment=news_sentiment,
            subreddits=subreddits,
            is_futures=is_futures,
        )
        return report

    async def _fetch_apewisdom(self) -> list[dict]:
        """
        Fetch the ApeWisdom trending stocks list.
        Returns a list of dicts with: ticker, mentions, upvotes, rank, mentions_24h_ago.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(APEWISDOM_URL)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("results", [])
                else:
                    logger.warning(f"ApeWisdom returned status {resp.status_code}")
                    return []
        except Exception as e:
            logger.warning(f"ApeWisdom fetch failed: {e}")
            return []

    def _find_symbol(self, symbol: str, trending: list[dict]) -> Optional[dict]:
        """Find the symbol in the ApeWisdom trending list (case-insensitive)"""
        symbol_upper = symbol.upper()
        for item in trending:
            if item.get("ticker", "").upper() == symbol_upper:
                return item
        return None

    async def _fetch_engine_reddit_sentiment(self) -> dict:
        """
        Fetch JARVIS engine's processed Reddit sentiment (ApeWisdom via data_manager).
        Returns the top-20 trending tickers from the engine's /sentiment/reddit endpoint.
        Falls back gracefully on any error — including HTTP 500 — so the pipeline
        is never blocked. Returns {"_unavailable": True} on server-side errors so
        callers can set data_quality accordingly.
        """
        _api_key = os.environ.get("API_KEY", "")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "http://localhost:8010/sentiment/reddit",
                    headers={"x-api-key": _api_key},
                )
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code >= 500:
                    logger.warning(
                        f"Engine reddit sentiment returned HTTP {resp.status_code} — "
                        "social API unavailable, returning neutral fallback"
                    )
                    return {"_unavailable": True}
                logger.debug(f"Engine reddit sentiment returned {resp.status_code}")
        except Exception as e:
            logger.debug(f"Engine reddit sentiment fetch failed: {e}")
        return {}

    async def _fetch_engine_news_sentiment(self, symbol: str) -> dict:
        """
        Fetch news sentiment for the given symbol from the engine's news endpoint.
        Returns sentiment dict, {"_unavailable": True} on HTTP 5xx, or empty dict on
        connection errors — never raises so the pipeline is always unblocked.
        """
        _api_key = os.environ.get("API_KEY", "")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"http://localhost:8010/sentiment/news/{symbol}",
                    headers={"x-api-key": _api_key},
                )
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code >= 500:
                    logger.warning(
                        f"Engine news sentiment for {symbol} returned HTTP "
                        f"{resp.status_code} — marking unavailable"
                    )
                    return {"_unavailable": True}
                logger.debug(
                    f"Engine news sentiment for {symbol} returned {resp.status_code}"
                )
        except Exception as e:
            logger.debug(f"Engine news sentiment fetch failed for {symbol}: {e}")
        return {}

    async def _fetch_stocktwits(self, symbol: str) -> Optional[dict]:
        """
        Fetch StockTwits symbol stream summary if a token is available.
        Returns sentiment counts or None on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json",
                    params={"access_token": self._stocktwits_token},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Extract bullish/bearish counts from recent messages
                    messages = data.get("messages", [])
                    bull = sum(
                        1
                        for m in messages
                        if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish"
                    )
                    bear = sum(
                        1
                        for m in messages
                        if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish"
                    )
                    return {
                        "bullish_count": bull,
                        "bearish_count": bear,
                        "total_messages": len(messages),
                        "symbol": data.get("symbol", {}).get("symbol", symbol),
                        "watchlist_count": data.get("symbol", {}).get("watchlist_count", 0),
                    }
        except Exception as e:
            logger.debug(f"StockTwits fetch failed for {symbol}: {e}")
        return None

    async def _llm_synthesize(
        self,
        symbol: str,
        symbol_data: Optional[dict],
        stocktwits_data: Optional[dict],
        all_trending: list[dict],
        engine_reddit_data: Optional[dict] = None,
        news_sentiment: Optional[dict] = None,
        subreddits: Optional[list[str]] = None,
        is_futures: bool = False,
    ) -> "SocialReport":
        """Use LLM to synthesize social metrics into a structured signal"""

        # Determine rank context
        total_tickers = len(all_trending)
        rank = int(symbol_data.get("rank", 0)) if symbol_data else 0
        mention_count = int(symbol_data.get("mentions", 0)) if symbol_data else 0
        mentions_24h_ago = int(symbol_data.get("mentions_24h_ago", 0)) if symbol_data else 0
        upvotes = int(symbol_data.get("upvotes", 0)) if symbol_data else 0

        # Determine trend direction from mention change
        if mention_count > mentions_24h_ago * 1.2:
            trend_hint = "rising"
        elif mention_count < mentions_24h_ago * 0.8:
            trend_hint = "falling"
        else:
            trend_hint = "stable"

        # Track whether any source returned a server error
        any_source_unavailable = False

        # Futures instrument context header
        instrument_header = ""
        if is_futures:
            description = FUTURES_DESCRIPTIONS.get(
                symbol.upper(),
                f"{symbol} futures instrument",
            )
            subreddit_list = ", ".join(f"r/{s}" for s in (subreddits or DEFAULT_SUBREDDITS))
            instrument_header = (
                f"INSTRUMENT TYPE: FUTURES\n"
                f"{description}\n"
                f"Social sentiment from equity Reddit is directionally relevant but "
                f"position sizing norms differ from stock trading communities.\n"
                f"Primary sentiment subreddits monitored: {subreddit_list}\n\n"
            )

        # Build social context block
        social_context = f"""{instrument_header}Symbol: {symbol}
Total tickers tracked by ApeWisdom: {total_tickers}

ApeWisdom Reddit Data:
- Rank: {rank if rank else "Not in top trending"}
- Mentions (24h): {mention_count}
- Mentions (48h ago): {mentions_24h_ago}
- Upvotes (24h): {upvotes}
- Mention trend: {trend_hint}
"""
        if stocktwits_data:
            total_st = stocktwits_data["total_messages"]
            bull_pct = (stocktwits_data["bullish_count"] / total_st * 100) if total_st > 0 else 0
            bear_pct = (stocktwits_data["bearish_count"] / total_st * 100) if total_st > 0 else 0
            social_context += f"""
StockTwits Data:
- Recent messages: {total_st}
- Bullish sentiment: {bull_pct:.0f}%
- Bearish sentiment: {bear_pct:.0f}%
- Watchlist count: {stocktwits_data.get("watchlist_count", "N/A")}
"""

        # Engine-processed Reddit sentiment (top trending list)
        if engine_reddit_data and engine_reddit_data.get("_unavailable"):
            any_source_unavailable = True
            social_context += "\nJARVIS Engine Reddit Data: service unavailable (HTTP 5xx)\n"
        elif engine_reddit_data and engine_reddit_data.get("tickers"):
            engine_tickers = engine_reddit_data.get("tickers", [])
            engine_match = next(
                (t for t in engine_tickers if t.get("ticker", "").upper() == symbol.upper()),
                None,
            )
            if engine_match:
                social_context += f"""
JARVIS Engine Reddit Data (processed):
- Engine rank: {engine_match.get("rank", "N/A")}
- Engine mentions: {engine_match.get("mentions", "N/A")}
"""
            else:
                social_context += f"""
JARVIS Engine Reddit Data: {symbol} not in engine's top-{len(engine_tickers)} trending list
"""
        else:
            social_context += "\nJARVIS Engine Reddit Data: unavailable\n"

        # News sentiment
        if news_sentiment and isinstance(news_sentiment, dict) and news_sentiment.get("_unavailable"):
            any_source_unavailable = True
            social_context += f"\nNews Sentiment for {symbol}: service unavailable (HTTP 5xx)\n"
        elif news_sentiment and isinstance(news_sentiment, dict):
            news_signal = news_sentiment.get("signal") or news_sentiment.get("sentiment")
            news_summary = news_sentiment.get("summary") or news_sentiment.get("headline", "")
            if news_signal is not None or news_summary:
                social_context += f"""
News Sentiment for {symbol}:
- Signal: {news_signal if news_signal is not None else "N/A"}
- Summary: {news_summary or "N/A"}
"""
        else:
            social_context += f"\nNews Sentiment for {symbol}: unavailable\n"

        prompt = f"""{social_context}

Respond with JSON in exactly this format:
{{
  "signal": <float -1.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "trend": "<rising|falling|stable>",
  "summary": "<one sentence social sentiment assessment>",
  "reasoning": "<2-3 sentence analysis explaining the signal, mention volume context, and risk factors>",
  "contract_bias": "<bullish|bearish|neutral|unknown>"
}}"""

        data_quality = "partial" if any_source_unavailable else "ok"

        try:
            anthropic_key = getattr(self._llm, "api_key", None) or os.getenv(
                "ANTHROPIC_API_KEY", ""
            )
            _t0 = time.time()

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 500,
                        "system": self.SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                payload = resp.json()

            _latency_ms = int((time.time() - _t0) * 1000)

            # Track cost via JarvisLLMClient if available
            usage = payload.get("usage", {})
            if hasattr(self._llm, "track_raw_call"):
                await self._llm.track_raw_call(
                    model="claude-haiku-4-5-20251001",
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    latency_ms=_latency_ms,
                    agent_name="social_analyst",
                )

            response_text = payload["content"][0]["text"].strip()

            # Strip markdown code blocks if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            result = json.loads(response_text)

            return SocialReport(
                symbol=symbol,
                timestamp=datetime.now(),
                signal=float(result.get("signal", 0.0)),
                confidence=float(result.get("confidence", 0.3)),
                mention_count=mention_count,
                rank=rank,
                trend=result.get("trend", trend_hint),
                summary=result.get("summary", ""),
                reasoning=result.get("reasoning", ""),
                contract_bias=result.get("contract_bias", "unknown"),
                data_quality=data_quality,
            )

        except Exception as e:
            logger.error(f"LLM social synthesis failed for {symbol}: {e}")
            return SocialReport(
                symbol=symbol,
                timestamp=datetime.now(),
                signal=0.0,
                confidence=0.2,
                mention_count=mention_count,
                rank=rank,
                trend=trend_hint,
                summary="LLM synthesis failed",
                reasoning=f"Social data retrieved but LLM analysis failed: {e}",
                contract_bias="unknown",
                data_quality=data_quality,
            )

    def _neutral_report(
        self,
        symbol: str,
        data_quality: str = "ok",
        reason: str = "No Reddit mentions or StockTwits data found. Low social presence; neutral signal assigned.",
    ) -> "SocialReport":
        """Return a neutral low-confidence report when no social data is available.

        data_quality should be set to "unavailable" when the cause is a server error
        (HTTP 5xx) rather than simply no trending data for the symbol.
        """
        return SocialReport(
            symbol=symbol,
            timestamp=datetime.now(),
            signal=0.0,
            confidence=0.2,
            mention_count=0,
            rank=0,
            trend="stable",
            summary=f"{symbol} not found in trending social data",
            reasoning=reason,
            contract_bias="unknown",
            data_quality=data_quality,
        )
