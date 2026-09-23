"""
JARVIS TRADER — Social Analyst Agent
======================================
Fetches retail sentiment data from ApeWisdom (Reddit trending tickers) and
optional StockTwits data, then uses an LLM to produce a structured social
sentiment signal.

POLICY — futures sentiment source (verbatim owner directive, 2026-04-19):
  "Futures-specific Reddit sentiment is not a signal I trust — the only
   futures information I trust should be from the Corey Sures auction-theory
   tools Discord in the channel #market-updates."

Implementation: `_fetch_reddit_praw` returns None for any symbol in
FUTURES_SUBREDDIT_MAP. PRAW is only ever queried for equity tickers that
happen to use DEFAULT_SUBREDDITS. Corey's #market-updates → corey_session_bias
pipeline (engine/discord/commentary_processor.py → corey_auction_analyst.py)
remains the SOLE authoritative futures sentiment source.

Refresh interval: every 30 minutes.
Model: Claude Haiku (claude-haiku-4-5-20251001) — lightweight task
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

<<<<<<< HEAD
=======
from llm.client import resolve_agent_model
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
from utils.llm_json import parse_llm_json

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

        # PRAW (raw Reddit) credentials — read once at construction. Unset → PRAW
        # source is skipped and analyze() falls back to ApeWisdom-only (equities).
        # Acquire at https://www.reddit.com/prefs/apps (create a "script" app).
        self._reddit_client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self._reddit_client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self._reddit_user_agent = os.getenv(
            "REDDIT_USER_AGENT",
            "jarvis-trader/1.0 (social_analyst; read-only)",
        )
        self._praw_instance = None  # lazy-init on first fetch

        # NOTE: PRAW creds are optional BY POLICY — retail Reddit chatter is
        # explicitly not trusted as a futures sentiment signal. Corey Sures'
        # auction-theory Discord (channel #market-updates) is the sole
        # authoritative futures sentiment source; see the module docstring
        # and the FUTURES_SUBREDDIT_MAP guard in _fetch_reddit_praw().

    async def analyze(self, symbol: str, current_price: float = None) -> "SocialReport":
        """Full social sentiment analysis pipeline for a symbol"""

        # Determine futures-specific subreddits for context annotation
        subreddits = FUTURES_SUBREDDIT_MAP.get(symbol.upper(), DEFAULT_SUBREDDITS)
        is_futures = symbol.upper() in FUTURES_SUBREDDIT_MAP

        # 1. Run 6-step institutional options flow analysis early so it feeds the LLM prompt
        flow_data = self._scan_institutional_flow(symbol, current_price)
        if flow_data.get("flow_bias") != 0.0:
            options_context = (
                f"\nInstitutional Flow (6-step analysis): {flow_data.get('description', '')}"
                f"\nFlow bias: {flow_data['flow_bias']:+.2f} | IV rank: {flow_data.get('iv_rank', 'N/A')}"
            )
        else:
            options_context = (
                f"\nInstitutional Flow: {flow_data.get('reason', 'no significant flow detected')}"
            )

        # 2. Fetch trending data from ApeWisdom
        trending_data = await self._fetch_apewisdom()

        # 3. Find symbol in trending list
        symbol_data = self._find_symbol(symbol, trending_data)

        # 4. Optionally enrich with StockTwits
        stocktwits_data = await self._fetch_stocktwits(symbol) if self._stocktwits_token else None

        # 5. Enrich with JARVIS engine reddit sentiment (processed/cached)
        engine_reddit_data = await self._fetch_engine_reddit_sentiment()

        # 6. Fetch news sentiment for this symbol
        news_sentiment = await self._fetch_engine_news_sentiment(symbol)

        # 7. Raw PRAW fetch from futures-specific subreddits (additive — ApeWisdom
        # aggregates equity-heavy boards but misses r/energy, r/oilandgas, etc.
        # where MCL/MGC conversation actually lives). Silently skipped if
        # REDDIT_CLIENT_ID/SECRET not configured or praw unavailable.
        praw_data = await self._fetch_reddit_praw(symbol, subreddits)

        # 8. If no data found at all, return neutral
        if (
            symbol_data is None
            and stocktwits_data is None
            and not engine_reddit_data
            and not news_sentiment
            and not praw_data
        ):
            logger.info(f"{symbol} not found in social trending data — returning neutral")
            return self._neutral_report(symbol)

        # 9. LLM synthesis (pass institutional flow context)
        report = await self._llm_synthesize(
            symbol, symbol_data, stocktwits_data, trending_data,
            engine_reddit_data=engine_reddit_data,
            news_sentiment=news_sentiment,
            praw_data=praw_data,
            subreddits=subreddits,
            is_futures=is_futures,
            options_context=options_context,
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

    async def _fetch_reddit_praw(
        self,
        symbol: str,
        subreddits: list[str],
        hot_limit: int = 15,
    ) -> Optional[dict]:
        """
        Optional PRAW fetch for EQUITIES ONLY. Futures symbols are gated off
        by policy — retail Reddit chatter is untrusted for futures. Corey
        Sures' Discord #market-updates is the sole futures sentiment source
        (see engine/discord/commentary_processor.py + corey_auction_analyst).

        Returns a dict with hot post titles / scores / mention count for
        equity symbols when credentials are present, or None if the symbol
        is futures, credentials are missing, PRAW isn't installed, or the
        fetch fails.
        """
        # Futures policy gate — never query Reddit for futures tickers.
        if symbol.upper() in FUTURES_SUBREDDIT_MAP:
            logger.debug(
                "[policy] PRAW skipped for %s — futures sentiment sourced from "
                "Corey Discord #market-updates only",
                symbol,
            )
            return None

        if not self._reddit_client_id or not self._reddit_client_secret:
            # No credentials configured — silently skip this source
            return None

        try:
            # Lazy import — praw is an optional dep; avoid import-time hard requirement
            import praw  # type: ignore
        except ImportError:
            logger.debug("PRAW not installed — skipping raw Reddit fetch")
            return None

        try:
            if self._praw_instance is None:
                self._praw_instance = praw.Reddit(
                    client_id=self._reddit_client_id,
                    client_secret=self._reddit_client_secret,
                    user_agent=self._reddit_user_agent,
                    check_for_async=False,  # we're calling sync PRAW from async via loop offload
                )

            reddit = self._praw_instance
            symbol_upper = symbol.upper()

            import asyncio

            def _sync_fetch() -> dict:
                hot_posts: list[dict] = []
                symbol_mentions = 0
                total_seen = 0
                for sub_name in subreddits:
                    try:
                        subreddit = reddit.subreddit(sub_name)
                        for post in subreddit.hot(limit=hot_limit):
                            total_seen += 1
                            title = getattr(post, "title", "") or ""
                            selftext = (getattr(post, "selftext", "") or "")[:200]
                            score = int(getattr(post, "score", 0) or 0)
                            num_comments = int(getattr(post, "num_comments", 0) or 0)

                            if symbol_upper in title.upper() or symbol_upper in selftext.upper():
                                symbol_mentions += 1

                            hot_posts.append(
                                {
                                    "subreddit": sub_name,
                                    "title": title[:140],
                                    "score": score,
                                    "num_comments": num_comments,
                                }
                            )
                    except Exception as sub_err:
                        logger.debug(
                            f"PRAW fetch failed for r/{sub_name}: {sub_err}"
                        )
                        continue

                # Keep top 10 by score for the LLM prompt (keeps token count bounded)
                hot_posts.sort(key=lambda p: p["score"], reverse=True)
                return {
                    "subreddits_queried": subreddits,
                    "posts_scanned": total_seen,
                    "symbol_mentions": symbol_mentions,
                    "top_posts": hot_posts[:10],
                }

            # PRAW is sync — run in a thread pool to stay async-friendly
            result = await asyncio.to_thread(_sync_fetch)
            if result.get("posts_scanned", 0) == 0:
                return None
            return result

        except Exception as e:
            logger.debug(f"PRAW Reddit fetch failed for {symbol}: {e}")
            return None

    async def _llm_synthesize(
        self,
        symbol: str,
        symbol_data: Optional[dict],
        stocktwits_data: Optional[dict],
        all_trending: list[dict],
        engine_reddit_data: Optional[dict] = None,
        news_sentiment: Optional[dict] = None,
        praw_data: Optional[dict] = None,
        subreddits: Optional[list[str]] = None,
        is_futures: bool = False,
        options_context: Optional[str] = None,
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

        # Raw PRAW data (futures-specific subreddits)
        if praw_data:
            top_posts = praw_data.get("top_posts", [])
            social_context += (
                f"\nRaw Reddit (PRAW, futures-specific subreddits):\n"
                f"- Subreddits queried: {', '.join('r/' + s for s in praw_data.get('subreddits_queried', []))}\n"
                f"- Posts scanned: {praw_data.get('posts_scanned', 0)}\n"
                f"- {symbol} direct mentions: {praw_data.get('symbol_mentions', 0)}\n"
            )
            if top_posts:
                social_context += "- Top hot posts (by score):\n"
                for p in top_posts[:5]:
                    social_context += (
                        f"  · r/{p['subreddit']} ({p['score']}↑ / {p['num_comments']}💬): "
                        f"{p['title']}\n"
                    )
        else:
            social_context += "\nRaw Reddit (PRAW): unavailable (credentials not set or source skipped)\n"

        # Institutional options flow (6-step analysis)
        if options_context:
            social_context += options_context + "\n"

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
<<<<<<< HEAD
            if hasattr(self._llm, "call"):
                # Primary: use JarvisLLMClient (retry, fallback, cost tracking built-in)
                llm_result = await self._llm.call(
                    model="claude-haiku-4-5-20251001",
=======
            model = resolve_agent_model(self._llm, "claude-haiku-4-5-20251001", fast=True)
            if hasattr(self._llm, "call"):
                # Primary: use JarvisLLMClient (retry, fallback, cost tracking built-in)
                llm_result = await self._llm.call(
                    model=model,
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
                    system=self.SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                    agent_name="social_analyst",
                )
                if not llm_result.success:
                    raise RuntimeError(llm_result.error or "LLM call failed")
                response_text = llm_result.content.strip()
            else:
                # Fallback: raw httpx when LLM client is not JarvisLLMClient
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
<<<<<<< HEAD
                            "model": "claude-haiku-4-5-20251001",
=======
                            "model": model,
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
                            "max_tokens": 500,
                            "system": self.SYSTEM_PROMPT,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                _latency_ms = int((time.time() - _t0) * 1000)
                if hasattr(self._llm, "track_raw_call"):
                    await self._llm.track_raw_call(
<<<<<<< HEAD
                        model="claude-haiku-4-5-20251001",
=======
                        model=model,
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
                        input_tokens=payload.get("usage", {}).get("input_tokens", 0),
                        output_tokens=payload.get("usage", {}).get("output_tokens", 0),
                        latency_ms=_latency_ms,
                        agent_name="social_analyst",
                    )
                response_text = payload["content"][0]["text"].strip()

            # Tolerant extraction: markdown fences, leading/trailing prose, and
            # trailing commas now recover instead of failing to a zero-signal
            # report (see utils.llm_json — 2026-06-04 synthesis-failure wave).
            result = parse_llm_json(response_text)

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

    # ------------------------------------------------------------------
    # Institutional Options Flow Pipeline (6-step — @xynth_m workflow)
    # ------------------------------------------------------------------

    def _scan_institutional_flow(self, symbol: str, current_price: float = None) -> dict:
        """
        6-step institutional options flow analysis.
        Based on @xynth_m's institutional trading desk workflow.
        Returns flow_bias (-1 to +1), iv_rank, trade_count, and description.
        """
        try:
            # Step 1: Get large options trades (premium > $50K)
            # Try IB Gateway options data first, fall back to whatever is available
            large_trades = self._get_large_options_trades(symbol, min_premium=50000)
            if not large_trades:
                return {"flow_bias": 0.0, "reason": "no_large_trades_found", "iv_rank": None}

            # Step 2: Filter by price trend alignment
            # Align with current price momentum (calls above-price or puts below-price)
            trend_aligned = [t for t in large_trades if self._trade_aligns_with_trend(t, current_price)]

            # Step 3: IV rank check — reject high-IV entries (chasing premium)
            iv_rank = self._get_iv_rank(symbol)
            if iv_rank is not None and iv_rank > 70:
                return {
                    "flow_bias": 0.0,
                    "reason": "iv_rank_too_high",
                    "iv_rank": iv_rank,
                    "description": f"IV rank {iv_rank:.0f} > 70 — elevated premium risk",
                }

            if not trend_aligned:
                return {"flow_bias": 0.0, "reason": "no_trend_aligned_trades", "iv_rank": iv_rank}

            # Step 4: Count bullish vs bearish flow
            bullish_premium = sum(t.get("premium", 0) for t in trend_aligned if t.get("type") == "call")
            bearish_premium = sum(t.get("premium", 0) for t in trend_aligned if t.get("type") == "put")
            total_premium = bullish_premium + bearish_premium

            if total_premium == 0:
                return {"flow_bias": 0.0, "reason": "zero_premium", "iv_rank": iv_rank}

            # Step 5: Compute directional bias (-1 to +1)
            flow_bias = (bullish_premium - bearish_premium) / total_premium

            # Step 6: Scale confidence by trade concentration (whale risk adjustment)
            trade_count = len(trend_aligned)
            concentration_penalty = 1.0 if trade_count >= 5 else 0.7  # Fewer trades = less confidence
            flow_bias *= concentration_penalty

            iv_display = f"{iv_rank:.0f}" if iv_rank is not None else "N/A"
            return {
                "flow_bias": round(flow_bias, 3),
                "iv_rank": iv_rank,
                "trade_count": trade_count,
                "bullish_premium": bullish_premium,
                "bearish_premium": bearish_premium,
                "description": (
                    f"Flow: {trade_count} aligned trades | "
                    f"Bull ${bullish_premium:,.0f} vs Bear ${bearish_premium:,.0f} | "
                    f"IV rank {iv_display}"
                ),
            }

        except Exception as e:
            logger.debug(f"Institutional flow scan error for {symbol}: {e}")
            return {"flow_bias": 0.0, "reason": f"error: {e}"}

    def _get_large_options_trades(self, symbol: str, min_premium: float = 50000) -> list:
        """Fetch options trades above minimum premium threshold."""
        try:
            # Try IB Gateway options data if available via market data manager
            mdm = getattr(self, "market_data", None) or getattr(self, "mdm", None)
            if mdm and hasattr(mdm, "get_options_flow"):
                return mdm.get_options_flow(symbol, min_premium=min_premium) or []
            # No options data source available — graceful degradation
            return []
        except Exception:
            return []

    def _trade_aligns_with_trend(self, trade: dict, current_price: float) -> bool:
        """Check if an options trade direction aligns with price trend."""
        trade_type = trade.get("type", "").lower()
        strike = trade.get("strike", 0)
        if not strike or not current_price:
            return True  # Can't determine — include by default
        # Calls near/above price = bullish bets; puts near/below price = bearish bets
        if trade_type == "call" and strike >= current_price * 0.98:  # Near-ATM or OTM calls
            return True
        if trade_type == "put" and strike <= current_price * 1.02:  # Near-ATM or OTM puts
            return True
        return False  # Deep ITM — likely hedges, exclude

    def _get_iv_rank(self, symbol: str) -> Optional[float]:
        """Get IV rank (0-100) from available data source."""
        try:
            mdm = getattr(self, "market_data", None) or getattr(self, "mdm", None)
            if mdm and hasattr(mdm, "get_iv_rank"):
                return mdm.get_iv_rank(symbol)
            return None  # Not available — skip IV rank filter
        except Exception:
            return None

    # ------------------------------------------------------------------

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
