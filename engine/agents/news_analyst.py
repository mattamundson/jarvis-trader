"""
JARVIS TRADER — News Analyst Agent
====================================
Fetches recent news headlines from Finnhub and available data manager feeds,
then uses an LLM to identify sentiment, detect material events, and produce
a structured news signal.

Refresh interval: every 5 minutes during market hours.
Model: Claude Sonnet 4.6
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

__all__ = ["NewsAnalystAgent", "NewsReport"]


@dataclass
class NewsReport:
    """Structured output from the News Analyst agent"""

    symbol: str
    timestamp: datetime

    # Signal: -1.0 (strongly bearish news) to +1.0 (strongly bullish news)
    signal: float
    confidence: float  # 0.0 to 1.0

    # Material event classification
    event_type: str  # "earnings", "fda", "m&a", "legal", "macro", "none", "mixed"

    # Key catalysts identified by the LLM
    catalysts_bull: list[str] = field(default_factory=list)
    catalysts_bear: list[str] = field(default_factory=list)

    # Metadata
    headline_count: int = 0
    summary: str = ""
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "signal": self.signal,
            "confidence": self.confidence,
            "event_type": self.event_type,
            "catalysts_bull": self.catalysts_bull,
            "catalysts_bear": self.catalysts_bear,
            "headline_count": self.headline_count,
            "summary": self.summary,
            "reasoning": self.reasoning,
        }


class NewsAnalystAgent:
    """
    Fetches news headlines from Finnhub and synthesizes them via LLM into a
    structured trading signal.

    Two-stage approach:
    1. Fetch 10-20 recent headlines from Finnhub (and optional data manager feed)
    2. LLM identifies per-headline sentiment, material events, and overall signal
    """

    FINNHUB_BASE = "https://finnhub.io/api/v1"

    SYSTEM_PROMPT = """You are a professional financial news analyst for JARVIS TRADER,
an autonomous trading system.

Analyze the provided news headlines for the given symbol.
Your task:
1. Assign a sentiment score (-1 to +1) to each headline
2. Detect any material events: earnings, FDA decisions, M&A activity, legal/regulatory actions, macro events, or none
3. Identify specific bullish catalysts (positive for price)
4. Identify specific bearish catalysts (negative for price)
5. Produce an overall news signal (-1.0 to +1.0) weighted by recency and materiality
6. Assign a confidence score (0.0 to 1.0) — lower if news is ambiguous or sparse

Respond with valid JSON only. Do not add any explanation outside the JSON.
"""

    def __init__(self, llm_client, data_manager=None, brave_client=None):
        """
        Args:
            llm_client: Object with .api_key attribute (Anthropic key) and
                        optionally .finnhub_key for Finnhub API access.
            data_manager: Optional data manager that may expose a news feed.
            brave_client: Optional BraveSearchClient for live web news search.
        """
        self._llm = llm_client
        self._data = data_manager
        self._brave: Optional[object] = brave_client

    async def analyze(self, symbol: str) -> "NewsReport":
        """Full news analysis pipeline for a symbol"""

        # 1. Fetch headlines
        headlines = await self._fetch_headlines(symbol)

        if not headlines:
            logger.warning(f"No news found for {symbol}")
            return self._neutral_report(symbol, headline_count=0)

        # 2. LLM synthesis
        report = await self._llm_synthesize(symbol, headlines)
        return report

    async def _fetch_headlines(self, symbol: str) -> list[dict]:
        """
        Fetch recent news from Finnhub and merge with data manager feed if available.
        Returns a list of dicts with at least {"headline": str, "datetime": int/str}.
        """
        headlines = []

        # --- Finnhub company news ---
        finnhub_key = getattr(self._llm, "finnhub_key", None) or os.getenv("FINNHUB_API_KEY", "")
        if finnhub_key:
            try:
                from datetime import timedelta

                today = datetime.utcnow()
                from_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
                to_date = today.strftime("%Y-%m-%d")

                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{self.FINNHUB_BASE}/company-news",
                        params={
                            "symbol": symbol,
                            "from": from_date,
                            "to": to_date,
                            "token": finnhub_key,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        # Finnhub returns a list sorted newest-first
                        for item in data[:20]:
                            headlines.append(
                                {
                                    "headline": item.get("headline", ""),
                                    "source": item.get("source", ""),
                                    "datetime": item.get("datetime", 0),
                                    "summary": item.get("summary", "")[:200],
                                }
                            )
                    else:
                        logger.warning(f"Finnhub news returned {resp.status_code} for {symbol}")
            except Exception as e:
                logger.warning(f"Finnhub news fetch failed for {symbol}: {e}")

        # --- Brave Search live web news ---
        if self._brave is not None:
            try:
                brave_results = await self._brave.get_market_news(symbol)
                for item in brave_results:
                    headlines.append(
                        {
                            "headline": item.get("title", ""),
                            "source": item.get("published") or item.get("source", "brave"),
                            "datetime": item.get("age", ""),
                            "summary": item.get("description", "")[:200],
                        }
                    )
                logger.info(f"Brave Search added {len(brave_results)} headlines for {symbol}")
            except Exception as e:
                logger.warning(f"Brave Search news fetch failed for {symbol}: {e}")
        else:
            logger.debug(f"Brave Search not available for {symbol} — skipping live web search")

        # --- Optional data manager news feed ---
        if self._data and hasattr(self._data, "get_news"):
            try:
                dm_news = await self._data.get_news(symbol, limit=10)
                if dm_news:
                    for item in dm_news:
                        headlines.append(
                            {
                                "headline": item.get("headline", item.get("title", "")),
                                "source": item.get("source", "data_manager"),
                                "datetime": item.get("datetime", item.get("published_at", "")),
                                "summary": item.get("summary", item.get("description", ""))[:200],
                            }
                        )
            except Exception as e:
                logger.warning(f"Data manager news fetch failed for {symbol}: {e}")

        # Deduplicate by headline text, keep newest first, cap at 20
        seen = set()
        unique = []
        for h in headlines:
            key = h["headline"][:80]
            if key not in seen and key.strip():
                seen.add(key)
                unique.append(h)
        return unique[:20]

    async def _llm_synthesize(self, symbol: str, headlines: list[dict]) -> "NewsReport":
        """Use LLM to synthesize news headlines into a structured signal"""

        # Format headlines for the prompt
        headlines_text = ""
        for i, h in enumerate(headlines, 1):
            ts = h.get("datetime", "")
            if isinstance(ts, int) and ts > 0:
                ts = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            source = h.get("source", "")
            source_tag = f" ({source}, {ts})".rstrip(", ").rstrip("(").rstrip() if source or ts else ""
            headlines_text += f"{i}. {h['headline']}{source_tag}\n"
            if h.get("summary"):
                headlines_text += f"   {h['summary']}\n"

        prompt = f"""Analyze these {len(headlines)} recent news items for {symbol}:

{headlines_text}

Respond with JSON in exactly this format:
{{
  "signal": <float -1.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "event_type": "<earnings|fda|m&a|legal|macro|none|mixed>",
  "catalysts_bull": ["<catalyst 1>", "<catalyst 2>"],
  "catalysts_bear": ["<catalyst 1>", "<catalyst 2>"],
  "summary": "<one sentence overall news assessment>",
  "reasoning": "<2-3 sentence analysis explaining the signal and key drivers>"
}}"""

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
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 800,
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
                    model="claude-sonnet-4-6",
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    latency_ms=_latency_ms,
                    agent_name="news_analyst",
                )

            response_text = payload["content"][0]["text"].strip()

            # Strip markdown code blocks if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            result = json.loads(response_text)

            return NewsReport(
                symbol=symbol,
                timestamp=datetime.now(),
                signal=float(result.get("signal", 0.0)),
                confidence=float(result.get("confidence", 0.5)),
                event_type=result.get("event_type", "none"),
                catalysts_bull=result.get("catalysts_bull", []),
                catalysts_bear=result.get("catalysts_bear", []),
                headline_count=len(headlines),
                summary=result.get("summary", ""),
                reasoning=result.get("reasoning", ""),
            )

        except Exception as e:
            logger.error(f"LLM news synthesis failed for {symbol}: {e}")
            return self._neutral_report(symbol, headline_count=len(headlines))

    def _neutral_report(self, symbol: str, headline_count: int = 0) -> "NewsReport":
        return NewsReport(
            symbol=symbol,
            timestamp=datetime.now(),
            signal=0.0,
            confidence=0.1,
            event_type="none",
            catalysts_bull=[],
            catalysts_bear=[],
            headline_count=headline_count,
            summary="No news data available",
            reasoning="Could not retrieve or analyze news — returning neutral signal",
        )
