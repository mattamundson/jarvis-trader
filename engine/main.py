"""
JARVIS TRADER — Main Server
============================
FastAPI backend for the trading engine.
Runs on port 8010 (separate from GMS JARVIS on 8009).

Start with: uvicorn main:app --reload --port 8010
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
from data.market_data import MarketDataManager
from risk.safety_layer import SafetyLayer, OrderRequest
from agents.technical_analyst import TechnicalAnalystAgent

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("jarvis_trader")

# ── Global State ─────────────────────────────────────────────────────────
data_manager: MarketDataManager | None = None
safety_layer: SafetyLayer | None = None
technical_analyst: TechnicalAnalystAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and teardown on startup/shutdown"""
    global data_manager, safety_layer, technical_analyst

    logger.info("🤖 JARVIS TRADER starting up...")
    logger.info(f"   Live trading: {'ENABLED ⚠️' if settings.LIVE_TRADING_ENABLED else 'DISABLED (paper mode)'}")
    logger.info(f"   IBKR port:   {settings.IBKR_PORT} ({'live' if settings.IBKR_PORT == 4001 else 'paper'})")

    # Safety layer — always first
    safety_layer = SafetyLayer(settings)

    # Market data connections
    data_manager = MarketDataManager(settings)
    await data_manager.initialize()

    # Agents (need LLM client)
    class SimpleLLMClient:
        api_key = settings.ANTHROPIC_API_KEY

    if settings.ANTHROPIC_API_KEY:
        llm_client = SimpleLLMClient()
        technical_analyst = TechnicalAnalystAgent(llm_client, data_manager)
        logger.info("✅ Technical Analyst agent initialized")
    else:
        logger.warning("⚠️  No ANTHROPIC_API_KEY — LLM agents disabled. Add to .env to enable.")

    logger.info("✅ JARVIS TRADER ready. Dashboard: http://localhost:3010")
    logger.info("   API docs: http://localhost:8010/docs")

    yield  # Server runs here

    # Teardown
    if data_manager and data_manager.ibkr:
        await data_manager.ibkr.disconnect()
    logger.info("👋 JARVIS TRADER shutdown complete")


app = FastAPI(
    title="JARVIS TRADER",
    description="AI-powered autonomous trading system for futures and options",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3010", "http://localhost:3000", "http://localhost:3004"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────

_start_time = datetime.now()

@app.get("/health")
async def health():
    safety = safety_layer.get_status() if safety_layer else {}
    return {
        "status": "online",
        "version": "0.1.0",
        "timestamp": datetime.now().isoformat(),
        "live_trading": settings.LIVE_TRADING_ENABLED,
        "kill_switch_active": safety.get("kill_switch_active", False),
        "paper_mode": not settings.LIVE_TRADING_ENABLED,
        "ibkr_connected": data_manager.ibkr.is_connected if data_manager and data_manager.ibkr else False,
        "schwab_connected": False,  # Schwab connector TODO
        "uptime_seconds": (datetime.now() - _start_time).total_seconds(),
    }


# ── Safety / Kill Switch ──────────────────────────────────────────────────

@app.post("/safety/kill-switch/activate")
async def activate_kill_switch(reason: str = "manual"):
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    from risk.safety_layer import KillSwitchReason
    safety_layer.activate_kill_switch(KillSwitchReason.MANUAL, f"Manual activation: {reason}")
    return {"status": "kill_switch_activated", "reason": reason}


@app.post("/safety/kill-switch/deactivate")
async def deactivate_kill_switch():
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    safety_layer.deactivate_kill_switch(authorized_by="matt_dashboard")
    return {"status": "kill_switch_deactivated"}


@app.get("/safety/status")
async def safety_status():
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    return safety_layer.get_status()


# ── Analysis ──────────────────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    symbol: str
    timeframe: str = "15m"
    is_futures: bool = False


@app.post("/analyze/technical")
async def run_technical_analysis(req: AnalysisRequest):
    """Run the Technical Analyst agent on a symbol"""
    if not technical_analyst:
        raise HTTPException(503, "Technical analyst not available (no API key)")

    report = await technical_analyst.analyze(req.symbol, req.timeframe, req.is_futures)

    return {
        "symbol": report.symbol,
        "timestamp": report.timestamp.isoformat(),
        "timeframe": report.timeframe,
        "signal": report.signal,
        "confidence": report.confidence,
        "trend": report.trend,
        "regime": report.regime,
        "is_overbought": report.is_overbought,
        "is_oversold": report.is_oversold,
        "summary": report.summary,
        "reasoning": report.reasoning,
        "scores": {
            "trend": report.trend_score,
            "momentum": report.momentum_score,
            "volatility": report.volatility_score,
            "volume": report.volume_score,
        },
        "levels": {
            "current_price": report.current_price,
            "support": report.support_levels,
            "resistance": report.resistance_levels,
        },
        "raw_indicators": report.indicators,
    }


@app.get("/analyze/bars/{symbol}")
async def get_bars(symbol: str, timeframe: str = "5m", days: int = 7, futures: bool = False):
    """Get OHLCV bars for a symbol"""
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    df = await data_manager.get_bars(symbol, lookback_days=days, timeframe=timeframe, is_futures=futures)
    if df.empty:
        raise HTTPException(404, f"No data available for {symbol}")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": df.tail(200).to_dict(orient="records"),
        "count": len(df),
    }


@app.get("/sentiment/reddit")
async def get_reddit_sentiment(filter: str = "all-stocks"):
    """Get trending tickers from Reddit"""
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    tickers = await data_manager.reddit.get_trending_tickers(filter)
    return {"filter": filter, "tickers": tickers[:20]}


@app.get("/sentiment/news/{symbol}")
async def get_news_sentiment(symbol: str):
    """Get news sentiment for a symbol via Finnhub"""
    if not data_manager or not data_manager.finnhub:
        raise HTTPException(503, "Finnhub not connected (add FINNHUB_API_KEY to .env)")

    sentiment = data_manager.finnhub.get_news_sentiment(symbol)
    return {"symbol": symbol, "sentiment": sentiment}


# ── Portfolio ─────────────────────────────────────────────────────────────

@app.get("/portfolio")
async def get_portfolio():
    """Current portfolio state — sourced from broker API, never from agent memory"""
    if not safety_layer:
        raise HTTPException(503, "Safety layer not initialized")
    status = safety_layer.get_status()
    return {
        "total_equity": status.get("portfolio_equity", 0.0),
        "cash_balance": status.get("portfolio_equity", 0.0),  # Approximation until broker sync
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "daily_pnl": status.get("daily_pnl", 0.0),
        "margin_used": 0.0,
        "margin_available": status.get("portfolio_equity", 0.0),
        "positions": [],  # Populated after IBKR connector is wired
    }


# ── Recent decisions (for dashboard feed) ─────────────────────────────────

_decision_log: list[dict] = []  # In-memory ring buffer, 100 entries

@app.get("/decisions/recent")
async def get_recent_decisions(limit: int = 20):
    """Return most recent agent decisions"""
    return _decision_log[-limit:]


@app.post("/decisions/log")
async def log_decision(decision: dict):
    """Internal: agents call this to log decisions"""
    _decision_log.append({**decision, "id": len(_decision_log) + 1})
    if len(_decision_log) > 100:
        _decision_log.pop(0)
    return {"ok": True}


# ── Sentiment feed ────────────────────────────────────────────────────────

@app.get("/sentiment/recent")
async def get_sentiment_recent():
    """Return latest sentiment scores across sources"""
    if not data_manager:
        return []
    results = []
    try:
        reddit_data = await data_manager.reddit.get_trending_tickers("all-stocks")
        for item in reddit_data[:3]:
            results.append({
                "symbol": item.get("ticker", ""),
                "score": (item.get("sentiment", 0.5) - 0.5) * 2,  # Normalize to -1..1
                "post_count": item.get("mentions", 0),
                "source": "reddit",
                "timestamp": datetime.now().isoformat(),
            })
    except Exception:
        pass
    return results


# ── Watchlist ─────────────────────────────────────────────────────────────

@app.get("/watchlist")
async def get_watchlist():
    """Return configured watchlists as ticker items"""
    items = []
    for sym in settings.FUTURES_WATCHLIST:
        items.append({
            "symbol": sym,
            "name": {"MES": "Micro E-mini S&P 500", "MNQ": "Micro E-mini Nasdaq", "MCL": "Micro Crude Oil"}.get(sym, sym),
            "type": "futures",
            "last_price": None,
            "change_pct": None,
        })
    for sym in settings.OPTIONS_WATCHLIST:
        items.append({
            "symbol": sym,
            "name": sym,
            "type": "options",
            "last_price": None,
            "change_pct": None,
        })
    return items


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
