"""
Sentiment data endpoints
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["sentiment"])

# Global references (injected from main.py)
data_manager = None


def inject_dependencies(dm=None):
    """Inject dependencies from main.py"""
    global data_manager
    if dm is not None:
        data_manager = dm


@router.get("/sentiment/recent")
async def get_sentiment_recent():
    """Return latest sentiment scores across sources"""
    if not data_manager:
        return []
    results = []
    try:
        reddit_data = await data_manager.reddit.get_trending_tickers("all-stocks")
        for item in reddit_data[:3]:
            results.append(
                {
                    "symbol": item.get("ticker", ""),
                    "score": (item.get("sentiment", 0.5) - 0.5) * 2,  # Normalize to -1..1
                    "post_count": item.get("mentions", 0),
                    "source": "reddit",
                    "timestamp": datetime.now().isoformat(),
                }
            )
    except Exception:
        pass
    return results


@router.get("/sentiment/news/{symbol}")
async def get_news_sentiment(symbol: str):
    """Get news sentiment for a symbol via Finnhub"""
    if not data_manager or not data_manager.finnhub:
        raise HTTPException(503, "Finnhub not connected (add FINNHUB_API_KEY to .env)")
    sentiment = data_manager.finnhub.get_news_sentiment(symbol)
    return {"symbol": symbol, "sentiment": sentiment}
