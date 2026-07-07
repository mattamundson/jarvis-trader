"""
Sentiment Bridge
================
Polled caching layer that connects News Analyst (LLM) to
Execution Strategies (Low Latency).
Updates sentiment scores periodically so strategies stay current
without blocking on LLM calls.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict

logger = logging.getLogger("jarvis_trader.orchestrator.sentiment_bridge")

class SentimentBridge:
    def __init__(self, news_analyst, ttl_minutes: int = 30):
        self.analyst = news_analyst
        self.ttl = ttl_minutes
        self.cache: Dict[str, Dict] = {} # symbol -> {"score": float, "expiry": datetime}

    async def get_sentiment(self, symbol: str) -> float:
        """
        Get the current sentiment score for a symbol.
        If expired or missing, trigger an async update.
        """
        now = datetime.now()

        if symbol in self.cache:
            if now < self.cache[symbol]["expiry"]:
                return self.cache[symbol]["score"]
            else:
                logger.info(f"Sentiment for {symbol} expired. refreshing...")

        # Fresh fetch (Blocking for this call, but usually run in background)
        try:
            report = await self.analyst.analyze(symbol)
            score = report.signal
            self.cache[symbol] = {
                "score": score,
                "expiry": now + timedelta(minutes=self.ttl)
            }
            logger.info(f"Bridge Cloud Update: {symbol} Sentiment={score}")
            return score
        except Exception as e:
            logger.error(f"Failed to refresh sentiment bridge for {symbol}: {e}")
            return 0.0 # Neutral fallback

    def get_cached_sentiment(self, symbol: str) -> float:
        """Non-blocking, local cache only."""
        if symbol in self.cache:
            return self.cache[symbol]["score"]
        return 0.0
