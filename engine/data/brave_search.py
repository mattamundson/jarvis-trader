"""
Brave Search API client for JARVIS Trader news and market research.
Docs: https://api.search.brave.com/app/documentation/web-search
Rate limits: Free tier 1 req/sec, 2000/month. Paid: higher.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

BRAVE_API_BASE = "https://api.search.brave.com/res/v1"


class BraveSearchClient:
    """Async Brave Search client with rate limiting and structured results."""

    def __init__(self, api_key: str, requests_per_second: float = 1.0):
        self._api_key = api_key
        self._rps = requests_per_second
        self._last_request_at: float = 0.0
        self._session: Optional[httpx.AsyncClient] = None

    async def _get_session(self) -> httpx.AsyncClient:
        if self._session is None or self._session.is_closed:
            self._session = httpx.AsyncClient(
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self._api_key,
                },
                timeout=10.0,
            )
        return self._session

    async def _throttle(self):
        """Enforce rate limit."""
        import time
        elapsed = time.monotonic() - self._last_request_at
        min_interval = 1.0 / self._rps
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_request_at = time.monotonic()

    async def web_search(
        self,
        query: str,
        count: int = 10,
        freshness: Optional[str] = "pw",  # pw=past week, pd=past day, pm=past month
        country: str = "us",
    ) -> list[dict]:
        """
        Search the web. Returns list of {title, url, description, age}.
        freshness: pd=past day, pw=past week, pm=past month, None=any
        """
        await self._throttle()
        session = await self._get_session()
        params = {
            "q": query,
            "count": min(count, 20),
            "country": country,
            "search_lang": "en",
            "text_decorations": False,
            "spellcheck": False,
        }
        if freshness:
            params["freshness"] = freshness

        try:
            resp = await session.get(f"{BRAVE_API_BASE}/web/search", params=params)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "age": item.get("age", ""),
                    "source": "brave",
                })
            logger.info(f"BraveSearch: '{query}' → {len(results)} results")
            return results
        except httpx.HTTPStatusError as e:
            logger.error(f"BraveSearch HTTP {e.response.status_code} for '{query}': {e}")
            return []
        except Exception as e:
            logger.error(f"BraveSearch failed for '{query}': {e}")
            return []

    async def news_search(self, query: str, count: int = 10) -> list[dict]:
        """Search Brave News index specifically."""
        await self._throttle()
        session = await self._get_session()
        params = {
            "q": query,
            "count": min(count, 20),
            "country": "us",
            "search_lang": "en",
            "spellcheck": False,
        }
        try:
            resp = await session.get(f"{BRAVE_API_BASE}/news/search", params=params)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "age": item.get("age", ""),
                    "source": "brave_news",
                    "published": item.get("meta_url", {}).get("hostname", ""),
                })
            logger.info(f"BraveNews: '{query}' → {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"BraveNews failed for '{query}': {e}")
            return []

    async def get_market_news(self, symbol: str, company_name: str = "") -> list[dict]:
        """
        Get recent market news for a trading symbol.
        Runs sequential searches: symbol news + macro context.
        """
        queries = [f"{symbol} futures trading news today"]
        if company_name:
            queries.append(f"{company_name} earnings news")
        queries.append(
            "crude oil market news"
            if "CL" in symbol or "MCL" in symbol
            else f"{symbol} market outlook"
        )

        all_results = []
        for q in queries:
            results = await self.news_search(q, count=5)
            all_results.extend(results)

        # Deduplicate by URL
        seen = set()
        deduped = []
        for r in all_results:
            if r["url"] not in seen:
                seen.add(r["url"])
                deduped.append(r)

        return deduped[:15]

    async def close(self):
        if self._session and not self._session.is_closed:
            await self._session.aclose()
