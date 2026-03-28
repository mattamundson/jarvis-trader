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
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

__all__ = ["SocialAnalystAgent", "SocialReport"]

# ApeWisdom endpoint — no authentication required
APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks"


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

Important: High social buzz does NOT always mean bullish. Consider context.
Meme/momentum tickers with very high ranks and rising mentions may indicate
short-squeeze potential (bullish) OR overextension risk (bearish).

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

        # 1. Fetch trending data from ApeWisdom
        trending_data = await self._fetch_apewisdom()

        # 2. Find symbol in trending list
        symbol_data = self._find_symbol(symbol, trending_data)

        # 3. Optionally enrich with StockTwits
        stocktwits_data = await self._fetch_stocktwits(symbol) if self._stocktwits_token else None

        # 4. If no data found at all, return neutral
        if symbol_data is None and stocktwits_data is None:
            logger.info(f"{symbol} not found in social trending data — returning neutral")
            return self._neutral_report(symbol)

        # 5. LLM synthesis
        report = await self._llm_synthesize(symbol, symbol_data, stocktwits_data, trending_data)
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
                    bull = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish")
                    bear = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish")
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

        # Build social context block
        social_context = f"""Symbol: {symbol}
Total tickers tracked by ApeWisdom: {total_tickers}

ApeWisdom Reddit Data:
- Rank: {rank if rank else 'Not in top trending'}
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
- Watchlist count: {stocktwits_data.get('watchlist_count', 'N/A')}
"""

        prompt = f"""{social_context}

Respond with JSON in exactly this format:
{{
  "signal": <float -1.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "trend": "<rising|falling|stable>",
  "summary": "<one sentence social sentiment assessment>",
  "reasoning": "<2-3 sentence analysis explaining the signal, mention volume context, and risk factors>"
}}"""

        try:
            anthropic_key = getattr(self._llm, "api_key", None) or os.getenv("ANTHROPIC_API_KEY", "")

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
            )

    def _neutral_report(self, symbol: str) -> "SocialReport":
        """Return a neutral low-confidence report when no social data is available"""
        return SocialReport(
            symbol=symbol,
            timestamp=datetime.now(),
            signal=0.0,
            confidence=0.2,
            mention_count=0,
            rank=0,
            trend="stable",
            summary=f"{symbol} not found in trending social data",
            reasoning="No Reddit mentions or StockTwits data found. Low social presence; neutral signal assigned.",
        )
