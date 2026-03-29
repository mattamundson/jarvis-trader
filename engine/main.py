"""
JARVIS TRADER — Main Server
============================
FastAPI backend for the trading engine.
Runs on port 8010 (separate from GMS JARVIS on 8009).

Start with: uvicorn main:app --reload --port 8010
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
from data.market_data import MarketDataManager
from risk.safety_layer import SafetyLayer, OrderRequest
from risk.pnl_monitor import PnLMonitor
from agents.technical_analyst import TechnicalAnalystAgent
from agents.news_analyst import NewsAnalystAgent
from agents.social_analyst import SocialAnalystAgent
from agents.fundamental_analyst import FundamentalistAgent
from agents.bull_researcher import BullResearcherAgent
from agents.bear_researcher import BearResearcherAgent
from agents.debate import DebateOrchestrator
from agents.trader import TraderAgent
from agents.risk_manager import RiskManagerAgent
from agents.fund_manager import FundManagerAgent
from agents.pipeline import TradingPipeline
from portfolio.tracker import get_tracker, PortfolioTracker
from database.schema import init_db, DatabaseManager
from schedulers.eod_scheduler import EODScheduler
from routers.journal_router import router as journal_router, set_db_manager as set_journal_db
from execution.ib_order_manager import IBOrderManager

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
trading_pipeline: TradingPipeline | None = None
scheduler: AsyncIOScheduler | None = None
paper_tracker: PortfolioTracker | None = None
db_manager: DatabaseManager | None = None
pnl_monitor: PnLMonitor | None = None
eod_scheduler: EODScheduler | None = None
order_manager: IBOrderManager | None = None

# Rate limit: track last alert time per symbol to avoid flooding (2-hour cooldown)
_last_alert_time: Dict[str, datetime] = {}
ALERT_COOLDOWN_HOURS = 2

# 5-minute macro snapshot cache (keyed by "snapshot", stores flattened dict + "_ts")
_macro_cache: Dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and teardown on startup/shutdown"""
    global data_manager, safety_layer, technical_analyst, trading_pipeline, scheduler, paper_tracker, db_manager, pnl_monitor, eod_scheduler, order_manager

    logger.info("🤖 JARVIS TRADER starting up...")
    logger.info(f"   Live trading: {'ENABLED ⚠️' if settings.LIVE_TRADING_ENABLED else 'DISABLED (paper mode)'}")
    logger.info(f"   IBKR port:   {settings.IBKR_PORT} ({'live' if settings.IBKR_PORT == 4001 else 'paper'})")

    # Initialize SQLite database
    os.makedirs("data", exist_ok=True)
    db_manager = init_db(db_path="data/jarvis_trader.db")
    db_manager.initialize()
    set_journal_db(db_manager)
    logger.info("✅ SQLite database initialized at data/jarvis_trader.db")

    # Paper trading tracker — initialise before safety layer so it is always available
    paper_tracker = PortfolioTracker(db_manager=db_manager)
    logger.info("✅ Paper portfolio tracker ready")

    # P&L Monitor — wires SQLite + IB Gateway data to circuit breakers
    # IB gateway is not available yet at this point; it is injected after data_manager is ready
    pnl_monitor = PnLMonitor(
        db_manager=db_manager,
        ib_gateway=None,          # updated below once data_manager is initialised
        paper_tracker=paper_tracker,
    )
    logger.info("✅ PnL Monitor initialised (SQLite + paper tracker sources active)")

    # Safety layer — always first; PnLMonitor feeds circuit breakers with live data
    safety_layer = SafetyLayer(settings, pnl_monitor=pnl_monitor)

    # IB Order Manager — bridges SafetyLayer + IBGateway for paper-order submission
    # ib_gateway is None until data_manager connects; injected below after data_manager init
    order_manager = IBOrderManager(
        safety_layer=safety_layer,
        ib_gateway=None,
        portfolio_tracker=paper_tracker,
    )
    logger.info("✅ IBOrderManager initialized (ib_gateway=None until IBKR connects)")

    # Market data connections
    data_manager = MarketDataManager(settings)
    await data_manager.initialize()

    # Now that data_manager is ready, inject the IB gateway into PnLMonitor
    # so the circuit breakers can read live account data from IBKR when connected.
    if pnl_monitor is not None and data_manager.ibkr is not None:
        pnl_monitor._ib = data_manager.ibkr
        logger.info("✅ PnL Monitor: IB Gateway wired (live account data source active)")

    # Agents (need LLM client)
    class SimpleLLMClient:
        api_key = settings.ANTHROPIC_API_KEY

    if settings.ANTHROPIC_API_KEY:
        llm_client = SimpleLLMClient()

        # Stage 1: Analysts
        technical_analyst = TechnicalAnalystAgent(llm_client, data_manager)
        news_agent = NewsAnalystAgent(llm_client, data_manager)
        social_agent = SocialAnalystAgent(llm_client)
        fundamental_agent = FundamentalistAgent(llm_client, data_manager)

        # Stage 2: Debate
        bull_agent = BullResearcherAgent(api_key=settings.ANTHROPIC_API_KEY)
        bear_agent = BearResearcherAgent(api_key=settings.ANTHROPIC_API_KEY)
        debate_agent = DebateOrchestrator()

        # Stages 3-5: Trader → Risk → Fund
        trader_agent = TraderAgent(llm_client)
        risk_agent = RiskManagerAgent(llm_client)
        fund_agent = FundManagerAgent(llm_client)

        logger.info("✅ All 10 trading agents initialized")

        # Trading Pipeline — all agents wired
        trading_pipeline = TradingPipeline(
            agents={
                "technical":    technical_analyst,
                "news":         news_agent,
                "social":       social_agent,
                "fundamental":  fundamental_agent,
                "bull":         bull_agent,
                "bear":         bear_agent,
                "debate":       debate_agent,
                "trader":       trader_agent,
                "risk_manager": risk_agent,
                "fund_manager": fund_agent,
            },
            safety_layer=safety_layer,
        )
        logger.info("✅ Trading Pipeline initialized — all 5 stages wired")
    else:
        logger.warning("⚠️  No ANTHROPIC_API_KEY — LLM agents disabled. Add to .env to enable.")

    # Scheduled analysis (runs during market hours)
    scheduler = AsyncIOScheduler(timezone="America/Chicago")

    async def run_watchlist_analysis():
        """Run full pipeline on all watchlist symbols — called by scheduler or manual trigger."""
        if not trading_pipeline or not safety_layer:
            return
        safety = safety_layer.get_status()
        if safety.get("kill_switch_active"):
            logger.info("Scheduler: skipping — kill switch active")
            return

        symbols_to_scan = [
            (sym, True) for sym in settings.FUTURES_WATCHLIST[:2]  # Top 2 futures
        ] + [
            (sym, False) for sym in settings.OPTIONS_WATCHLIST[:3]  # Top 3 equities
        ]

        logger.info(f"Scheduled scan: {[s[0] for s in symbols_to_scan]}")
        from notifications.whatsapp import get_notifier
        notifier = get_notifier()

        for symbol, is_futures in symbols_to_scan:
            try:
                result = await trading_pipeline.analyze_and_decide(symbol, is_futures)
                action = result.get("final_action", "hold")

                # Extract key fields for logging and alerting
                fund_dec = result.get("fund_decision") or {}
                trade_dec = result.get("trade_decision") or {}
                confidence = fund_dec.get("final_conviction", trade_dec.get("confidence", 0.0))
                qty = result.get("final_quantity", 0)
                price_info = trade_dec.get("limit_price") or trade_dec.get("stop_price")
                reasoning = trade_dec.get("reasoning", "")

                # Always log to decision feed
                _decision_log.append({
                    "id": len(_decision_log) + 1,
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol,
                    "action": action,
                    "confidence": confidence,
                    "source": "scheduler",
                    "summary": result.get("summary", ""),
                })
                if len(_decision_log) > 100:
                    _decision_log.pop(0)

                if action not in ("hold",):
                    logger.info(f"{symbol}: {action.upper()} qty={qty} confidence={confidence:.0%}")

                    # Rate limit: skip alert if we sent one for this symbol within cooldown window
                    now = datetime.now()
                    last_sent = _last_alert_time.get(symbol)
                    cooldown_expired = (
                        last_sent is None
                        or (now - last_sent) >= timedelta(hours=ALERT_COOLDOWN_HOURS)
                    )

                    if notifier.enabled and cooldown_expired:
                        price_str = f" @ {price_info:.2f}" if price_info else ""
                        pct = int(confidence * 100)
                        short_reason = (reasoning[:100] + "...") if len(reasoning) > 100 else reasoning
                        msg = (
                            f"JARVIS: {symbol} -> {action.upper()} {qty}{price_str}\n"
                            f"Confidence: {pct}%\n"
                            f"Reason: {short_reason}"
                        )
                        sent = await notifier.send(msg)
                        if sent:
                            _last_alert_time[symbol] = now
                            logger.info(f"WhatsApp alert sent for {symbol} ({action.upper()})")
                        else:
                            logger.warning(f"WhatsApp alert failed for {symbol}")
                    elif not cooldown_expired:
                        logger.info(
                            f"WhatsApp alert for {symbol} suppressed — cooldown active "
                            f"(last sent {last_sent.strftime('%H:%M')})"
                        )
                else:
                    logger.debug(f"{symbol}: hold — no alert sent")

            except Exception as e:
                logger.error(f"Scheduler analysis failed for {symbol}: {e}")

    # Run every 30 minutes on weekdays, 9:30am-4:00pm Chicago time
    if settings.ANTHROPIC_API_KEY:
        scheduler.add_job(
            run_watchlist_analysis,
            CronTrigger(
                day_of_week="mon-fri",
                hour="9-15",
                minute="0,30",
                timezone="America/Chicago"
            ),
            id="watchlist_scan",
            name="Watchlist Auto-Scan",
            max_instances=1,
            misfire_grace_time=300,
        )
        scheduler.start()
        logger.info("⏰ Scheduler started — watchlist scan every 30min (9:30am-4pm CT weekdays)")

    # ── Daily MGC signal scanner (runs 18:00 ET / 23:00 UTC) ────────────
    async def run_daily_mgc_signal():
        """Fetch today's MGC daily bar, run adaptive-regime signals, log pending entries."""
        import json as _json
        from pathlib import Path
        try:
            import yfinance as yf
            from backtest.signals import generate_signals as _gen_signals

            logger.info("[MGC-daily] Fetching GC=F daily bar...")
            gc_df = yf.download("GC=F", period="90d", interval="1d", progress=False)
            if gc_df is None or gc_df.empty or len(gc_df) < 20:
                logger.warning("[MGC-daily] Insufficient data from yfinance — skipping")
                return

            # Flatten MultiIndex columns if present (yfinance sometimes returns them)
            if hasattr(gc_df.columns, 'levels') and gc_df.columns.nlevels > 1:
                gc_df.columns = [c[0] if isinstance(c, tuple) else c for c in gc_df.columns]

            # Normalise column names to lowercase
            gc_df.columns = [c.lower() for c in gc_df.columns]

            sig_df = _gen_signals(gc_df, symbol="MGC", adaptive_regime=True)

            last_row = sig_df.iloc[-1]
            signal_val = str(last_row.get("entry_signal", "")).upper()
            logger.info(f"[MGC-daily] Last bar signal: {signal_val}")

            if signal_val == "ENTRY_NOW":
                direction = str(last_row.get("bias", "LONG")).upper()
                entry_est = float(last_row.get("close", 0))
                stop_lvl = float(last_row.get("stop_level", 0))
                t1 = float(last_row.get("target_1", 0))
                regime = str(last_row.get("regime_type", "UNKNOWN"))

                pending_file = Path(__file__).parent / "backtest" / "results" / "pending_signals.json"
                existing = []
                if pending_file.exists():
                    try:
                        existing = _json.loads(pending_file.read_text(encoding="utf-8"))
                    except Exception:
                        existing = []

                new_signal = {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "symbol": "MGC",
                    "signal": "ENTRY_NOW",
                    "direction": direction,
                    "entry_price_estimate": round(entry_est, 2),
                    "stop_level": round(stop_lvl, 2),
                    "target_1": round(t1, 2),
                    "regime_type": regime,
                    "status": "pending",
                }
                existing.append(new_signal)
                pending_file.write_text(_json.dumps(existing, indent=2), encoding="utf-8")
                logger.info(f"[MGC-daily] ENTRY_NOW logged -> {pending_file.name}: {direction} @ ~{entry_est:.2f}")

                # Send WhatsApp alert for MGC entry signal
                from notifications.whatsapp import get_notifier as _mgc_notifier
                notifier = _mgc_notifier()
                if notifier.enabled:
                    msg = (
                        f"JARVIS MGC DAILY SIGNAL\n"
                        f"Direction: {direction}\n"
                        f"Entry est: {entry_est:.2f}\n"
                        f"Stop: {stop_lvl:.2f}\n"
                        f"Target 1: {t1:.2f}\n"
                        f"Regime: {regime}"
                    )
                    await notifier.send(msg)
            else:
                logger.info("[MGC-daily] No ENTRY_NOW — no pending signal logged")

        except Exception as exc:
            logger.error(f"[MGC-daily] Failed: {exc}", exc_info=True)

    scheduler.add_job(
        run_daily_mgc_signal,
        CronTrigger(
            day_of_week="mon-fri",
            hour=23,
            minute=0,
            timezone="UTC",   # 23:00 UTC = 18:00 ET
        ),
        id="mgc_daily_signal",
        name="MGC Daily Signal Scanner",
        max_instances=1,
        misfire_grace_time=600,
    )
    if not scheduler.running:
        scheduler.start()
    logger.info("⏰ MGC daily signal job registered — 18:00 ET (23:00 UTC) weekdays")

    # EOD P&L snapshot scheduler — registers its own jobs on the existing scheduler
    from notifications.whatsapp import get_notifier as _get_notifier
    eod_scheduler = EODScheduler(
        db_manager=db_manager,
        portfolio_tracker=paper_tracker,
        whatsapp_notifier=_get_notifier(),
    )
    if scheduler is not None:
        eod_scheduler.register_with_scheduler(scheduler)

    logger.info("✅ JARVIS TRADER ready. Dashboard: http://localhost:3010")
    logger.info("   API docs: http://localhost:8010/docs")

    yield  # Server runs here

    # Teardown
    if data_manager and data_manager.ibkr:
        await data_manager.ibkr.disconnect()
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
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

app.include_router(journal_router, prefix="/journal", tags=["journal"])


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
    from notifications.whatsapp import get_notifier
    asyncio.create_task(get_notifier().alert_kill_switch(reason))
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


@app.get("/safety/circuit-breakers")
async def get_circuit_breakers():
    """
    Current circuit breaker state for all safety limits.

    Returns a snapshot of every circuit breaker without triggering any
    state changes.  Safe to poll frequently (e.g. every 5 seconds from
    the dashboard).

    Response fields:
        daily_pnl            — today's P&L in dollars (realized + unrealized)
        daily_limit          — max allowed daily loss in dollars (negative)
        daily_pnl_pct        — daily P&L as fraction of starting balance
        daily_limit_pct      — configured daily loss limit (e.g. -0.02)
        daily_limit_breached — True when daily loss limit has been exceeded
        drawdown_pct         — current drawdown from peak (negative fraction)
        drawdown_limit_pct   — configured max drawdown limit (e.g. -0.10)
        drawdown_breached    — True when max drawdown has been exceeded
        kill_switch_active   — whether the kill switch is currently on
        kill_switch_reason   — reason string or null
        pnl_source           — data origin: "ib" | "sqlite" | "memory"
        current_balance      — current account balance in dollars
        starting_balance     — balance at start of today in dollars
        orders_last_minute   — number of orders placed in the last 60 seconds
        all_clear            — True when no circuit breaker has tripped
    """
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    return safety_layer.check_circuit_breakers()


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


# ── Paper Trading Portfolio ───────────────────────────────────────────────

class PaperTradeRequest(BaseModel):
    symbol: str
    action: str                     # "buy" | "sell" | "sell_short" | "buy_to_cover"
    quantity: float
    price: float
    notes: str = ""
    close_trade_id: str | None = None  # If set, this call closes an existing trade


@app.get("/portfolio/paper/positions")
async def get_paper_positions():
    """Return all currently open paper-trade positions."""
    if not paper_tracker:
        raise HTTPException(503, "Paper tracker not initialized")
    return {
        "positions": paper_tracker.get_open_positions(),
        "count": len(paper_tracker.get_open_positions()),
    }


@app.post("/portfolio/paper/trade")
async def submit_paper_trade(req: PaperTradeRequest):
    """
    Open or close a paper trade.

    - If close_trade_id is omitted (or null):  opens a new position.
    - If close_trade_id is provided:           closes that position at req.price.

    Body fields:
        symbol        : ticker (e.g. "SPY", "MES")
        action        : "buy" | "sell" | "sell_short" | "buy_to_cover"
        quantity      : number of shares/contracts
        price         : fill price
        notes         : optional free-text (pipeline summary, reasoning, etc.)
        close_trade_id: trade_id to close (optional)
    """
    if not paper_tracker:
        raise HTTPException(503, "Paper tracker not initialized")

    if req.close_trade_id:
        try:
            trade = paper_tracker.close_trade(req.close_trade_id, req.price)
        except KeyError:
            raise HTTPException(404, f"No open trade with id={req.close_trade_id!r}")
        return {
            "status": "closed",
            "trade": trade.to_dict(),
        }
    else:
        trade_id = paper_tracker.open_trade(
            symbol=req.symbol,
            action=req.action,
            quantity=req.quantity,
            price=req.price,
            notes=req.notes,
        )
        return {
            "status": "opened",
            "trade_id": trade_id,
            "symbol": req.symbol.upper(),
            "action": req.action,
            "quantity": req.quantity,
            "entry_price": req.price,
        }


@app.get("/portfolio/paper/performance")
async def get_paper_performance():
    """Return performance metrics for all closed paper trades."""
    if not paper_tracker:
        raise HTTPException(503, "Paper tracker not initialized")
    return paper_tracker.get_performance()


# ── Historical Query Endpoints (SQLite) ───────────────────────────────────

@app.get("/portfolio/history/trades")
async def get_trade_history(limit: int = 100, symbol: str = "", status: str = ""):
    """
    Return historical trades from SQLite.

    Query params:
        limit  : max rows to return (default 100)
        symbol : filter by ticker symbol (optional)
        status : filter by status — "open" | "closed" (optional)
    """
    if not db_manager:
        return {"trades": [], "count": 0, "note": "db_manager not initialized"}
    try:
        trades = db_manager.get_trades(
            limit=limit,
            symbol=symbol.upper() if symbol else None,
            status=status.lower() if status else None,
        )
        return {"trades": trades, "count": len(trades)}
    except Exception as exc:
        logger.error(f"[DB] get_trades failed: {exc}")
        return {"trades": [], "count": 0, "error": str(exc)}


@app.get("/portfolio/history/daily-pnl")
async def get_daily_pnl(days: int = 30):
    """
    Return daily P&L snapshots for the last N days.

    Query params:
        days : lookback window in calendar days (default 30)
    """
    if not db_manager:
        return {"daily_pnl": [], "days": days, "note": "db_manager not initialized"}
    try:
        records = db_manager.get_daily_pnl(days=days)
        return {"daily_pnl": records, "days": days, "count": len(records)}
    except Exception as exc:
        logger.error(f"[DB] get_daily_pnl failed: {exc}")
        return {"daily_pnl": [], "days": days, "error": str(exc)}


@app.get("/portfolio/history/decisions")
async def get_decision_history(limit: int = 50, symbol: str = ""):
    """
    Return historical agent decisions from SQLite.

    Query params:
        limit  : max rows to return (default 50)
        symbol : filter by ticker symbol (optional)
    """
    if not db_manager:
        return {"decisions": [], "count": 0, "note": "db_manager not initialized"}
    try:
        decisions = db_manager.get_decisions(
            limit=limit,
            symbol=symbol.upper() if symbol else None,
        )
        return {"decisions": decisions, "count": len(decisions)}
    except Exception as exc:
        logger.error(f"[DB] get_decisions failed: {exc}")
        return {"decisions": [], "count": 0, "error": str(exc)}


@app.get("/portfolio/stats/summary")
async def get_stats_summary():
    """
    Aggregate performance summary from SQLite — win rate, total P&L, trade counts,
    best/worst trade, profit factor.
    """
    if not db_manager:
        return {"note": "db_manager not initialized"}
    try:
        summary = db_manager.get_stats_summary()
        return summary
    except Exception as exc:
        logger.error(f"[DB] get_stats_summary failed: {exc}")
        return {"error": str(exc)}


@app.get("/portfolio/stats/drawdown")
async def get_drawdown():
    """
    Return max drawdown and the equity curve used to compute it (from SQLite trades).
    """
    if not db_manager:
        return {"max_drawdown": 0.0, "equity_curve": [], "note": "db_manager not initialized"}
    try:
        drawdown = db_manager.get_drawdown()
        return drawdown
    except Exception as exc:
        logger.error(f"[DB] get_drawdown failed: {exc}")
        return {"max_drawdown": 0.0, "equity_curve": [], "error": str(exc)}


# ── Analytics / Performance Validation ────────────────────────────────────

@app.get("/analytics/performance")
async def get_analytics_performance():
    """
    Forward-test validation report.

    Computes Profit Factor, Sharpe ratio, win rate, average win/loss,
    max drawdown, and total P&L from all closed paper trades and daily P&L
    records stored in SQLite.

    Returns a structured report with status PASS / FAIL / INSUFFICIENT_DATA
    and a plain-English recommendation.
    """
    if not db_manager:
        return {
            "status": "INSUFFICIENT_DATA",
            "metrics": {},
            "thresholds": {
                "profit_factor": 2.0,
                "sharpe_ratio": 1.5,
                "min_trades_required": 10,
            },
            "recommendation": "Database not initialized.",
        }
    try:
        from analytics.performance import PerformanceCalculator
        calc = PerformanceCalculator(db_manager)
        return calc.get_validation_report()
    except Exception as exc:
        logger.error(f"[Analytics] get_validation_report failed: {exc}")
        raise HTTPException(500, f"Analytics error: {exc}")


@app.get("/analytics/performance/compare")
async def get_analytics_performance_compare():
    """
    Compare current forward-test metrics against backtest targets.

    Forward metrics (from live paper trading in SQLite) are compared to the
    reference backtest results: PF=5.27, Sharpe=4.16.

    Returns per-metric diffs, retention percentages, and a ``degradation_ok``
    flag that is True when forward results still exceed the paper thresholds
    (PF > 2.0 and Sharpe > 1.5).
    """
    if not db_manager:
        return {
            "forward": {},
            "backtest": {"profit_factor": 5.27, "sharpe_ratio": 4.16},
            "comparison": {},
            "degradation_ok": False,
            "note": "Database not initialized.",
        }
    try:
        from analytics.performance import PerformanceCalculator
        calc = PerformanceCalculator(db_manager)
        return calc.compare_to_backtest()
    except Exception as exc:
        logger.error(f"[Analytics] compare_to_backtest failed: {exc}")
        raise HTTPException(500, f"Analytics error: {exc}")


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
    """Return configured watchlists as ticker items with live prices"""
    import yfinance as yf

    futures_map = {
        "MES": "ES=F", "MNQ": "NQ=F", "MCL": "CL=F",
        "MGC": "GC=F", "MHG": "HG=F", "MYM": "YM=F", "M2K": "RTY=F",
    }
    all_symbols = list(settings.FUTURES_WATCHLIST) + list(settings.OPTIONS_WATCHLIST)
    prices: dict = {}
    try:
        yf_tickers_map = {s: futures_map.get(s, s) for s in all_symbols}
        tickers_obj = yf.Tickers(" ".join(set(yf_tickers_map.values())))
        for sym, yf_sym in yf_tickers_map.items():
            try:
                info = tickers_obj.tickers[yf_sym].fast_info
                current = float(info.last_price) if hasattr(info, "last_price") and info.last_price else None
                prev = float(info.previous_close) if hasattr(info, "previous_close") and info.previous_close else None
                chg = ((current - prev) / prev) if current and prev and prev > 0 else None
                prices[sym] = {"last_price": current, "change_pct": chg}
            except Exception:
                prices[sym] = {"last_price": None, "change_pct": None}
    except Exception:
        pass

    items = []
    names = {"MES": "Micro E-mini S&P 500", "MNQ": "Micro E-mini Nasdaq", "MCL": "Micro Crude Oil",
             "MGC": "Micro Gold", "MHG": "Micro Copper", "MYM": "Micro Dow", "M2K": "Micro Russell 2000"}
    for sym in settings.FUTURES_WATCHLIST:
        p = prices.get(sym, {})
        items.append({"symbol": sym, "name": names.get(sym, sym), "type": "futures",
                      "last_price": p.get("last_price"), "change_pct": p.get("change_pct")})
    for sym in settings.OPTIONS_WATCHLIST:
        p = prices.get(sym, {})
        items.append({"symbol": sym, "name": sym, "type": "options",
                      "last_price": p.get("last_price"), "change_pct": p.get("change_pct")})
    return items


class WatchlistAddRequest(BaseModel):
    symbol: str


@app.post("/watchlist")
async def add_to_watchlist(req: WatchlistAddRequest):
    """Add a symbol to the appropriate watchlist (futures or equities)."""
    symbol = req.symbol.strip().upper()
    if not symbol:
        raise HTTPException(400, "symbol must not be empty")

    futures_symbols = {"MES", "MNQ", "MCL", "MGC", "MHG", "MYM", "M2K", "ES", "NQ", "CL", "GC"}
    is_futures = symbol in futures_symbols

    if is_futures:
        if symbol not in settings.FUTURES_WATCHLIST:
            settings.FUTURES_WATCHLIST = list(settings.FUTURES_WATCHLIST) + [symbol]
    else:
        if symbol not in settings.OPTIONS_WATCHLIST:
            settings.OPTIONS_WATCHLIST = list(settings.OPTIONS_WATCHLIST) + [symbol]

    return {"status": "added", "symbol": symbol, "type": "futures" if is_futures else "options"}


@app.delete("/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str):
    """Remove a symbol from the watchlist (futures or equities)."""
    symbol = symbol.strip().upper()
    removed = False

    if symbol in settings.FUTURES_WATCHLIST:
        settings.FUTURES_WATCHLIST = [s for s in settings.FUTURES_WATCHLIST if s != symbol]
        removed = True
    elif symbol in settings.OPTIONS_WATCHLIST:
        settings.OPTIONS_WATCHLIST = [s for s in settings.OPTIONS_WATCHLIST if s != symbol]
        removed = True

    if not removed:
        raise HTTPException(404, f"Symbol {symbol} not found in watchlist")

    return {"status": "removed", "symbol": symbol}


# ── Live Prices ────────────────────────────────────────────────────────────

@app.get("/prices/snapshot")
async def get_price_snapshot(symbols: str = "SPY,QQQ,MES,MNQ"):
    """
    Get current prices and daily change % for comma-separated symbols.
    Futures micro contracts (MES, MNQ, MCL etc) are mapped to continuous contracts.
    """
    import yfinance as yf

    futures_map = {"MES": "ES=F", "MNQ": "NQ=F", "MCL": "CL=F",
                   "MGC": "GC=F", "MHG": "HG=F", "MYM": "YM=F", "M2K": "RTY=F"}
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {}

    yf_tickers = [futures_map.get(s, s) for s in symbol_list]
    try:
        tickers = yf.Tickers(" ".join(yf_tickers))
        result = {}
        for original, yf_ticker in zip(symbol_list, yf_tickers):
            try:
                info = tickers.tickers[yf_ticker].fast_info
                current = float(info.last_price) if hasattr(info, "last_price") and info.last_price else None
                prev = float(info.previous_close) if hasattr(info, "previous_close") and info.previous_close else None
                chg = ((current - prev) / prev) if current and prev and prev > 0 else None
                result[original] = {"symbol": original, "last_price": current, "prev_close": prev,
                                    "change_pct": chg, "yf_ticker": yf_ticker}
            except Exception as e:
                result[original] = {"symbol": original, "last_price": None, "prev_close": None,
                                    "change_pct": None, "error": str(e)}
        return result
    except Exception as e:
        raise HTTPException(500, f"Price fetch failed: {e}")


# ── Pipeline ──────────────────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    symbol: str
    is_futures: bool = False


@app.post("/pipeline/run")
async def run_pipeline(req: PipelineRequest):
    """Run the full 5-stage AI trading pipeline for a symbol"""
    if not trading_pipeline:
        raise HTTPException(503, "Pipeline not available (no ANTHROPIC_API_KEY)")

    result = await trading_pipeline.analyze_and_decide(req.symbol, req.is_futures)

    final_action = result.get("final_action", "hold")

    # Log to decision feed
    _decision_log.append({
        "id": len(_decision_log) + 1,
        "timestamp": datetime.now().isoformat(),
        "symbol": req.symbol,
        "action": final_action,
        "confidence": result.get("confidence", 0),
        "source": "pipeline",
        "summary": result.get("summary", ""),
    })
    if len(_decision_log) > 100:
        _decision_log.pop(0)

    # Auto-log to paper tracker when not in live mode and the pipeline decided to trade
    if not settings.LIVE_TRADING_ENABLED and final_action != "hold" and paper_tracker:
        try:
            trade_dec = result.get("trade_decision") or {}
            # Prefer limit_price, fall back to stop_price, then last known price from indicators
            entry_price = (
                trade_dec.get("limit_price")
                or trade_dec.get("stop_price")
                or (result.get("technical", {}) or {}).get("current_price")
            )
            final_qty = result.get("final_quantity", 1) or 1

            if entry_price:
                trade_id = paper_tracker.open_trade(
                    symbol=req.symbol,
                    action=final_action,
                    quantity=float(final_qty),
                    price=float(entry_price),
                    notes=result.get("summary", ""),
                )
                result["paper_trade_id"] = trade_id
                logger.info(
                    f"[PAPER] Auto-logged {req.symbol} {final_action.upper()} "
                    f"qty={final_qty} @ {entry_price:.4f}  id={trade_id[:8]}"
                )
            else:
                logger.warning(
                    f"[PAPER] Skipped auto-log for {req.symbol} {final_action.upper()} "
                    f"— could not determine entry price from pipeline result"
                )
        except Exception as exc:
            logger.error(f"[PAPER] Auto-log failed for {req.symbol}: {exc}")

    # Send WhatsApp alert for non-HOLD signals
    from notifications.whatsapp import get_notifier
    notifier = get_notifier()
    asyncio.create_task(notifier.alert_pipeline_result(req.symbol, result))

    return result


@app.get("/pipeline/status")
async def pipeline_status():
    """Pipeline availability and last run info"""
    return {
        "available": trading_pipeline is not None,
        "last_run": _decision_log[-1] if _decision_log else None,
        "decision_count": len(_decision_log),
    }


@app.get("/scheduler/status")
async def scheduler_status():
    """Scheduled job status"""
    if not scheduler:
        return {"running": False, "jobs": []}
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": next_run.isoformat() if next_run else None,
        })
    return {
        "running": scheduler.running,
        "jobs": jobs,
        "total_decisions_logged": len(_decision_log),
    }


@app.post("/scheduler/scan-now")
async def trigger_scan_now():
    """
    Manually trigger a full watchlist scan immediately.
    Runs the same pipeline as the scheduled job — useful for testing outside market hours.
    Respects kill switch. Does NOT bypass the 2-hour WhatsApp rate limit.
    """
    if not trading_pipeline:
        raise HTTPException(503, "Pipeline not available (no ANTHROPIC_API_KEY)")
    if not safety_layer:
        raise HTTPException(503, "Safety layer not initialized")

    safety = safety_layer.get_status()
    if safety.get("kill_switch_active"):
        return {"status": "skipped", "reason": "kill_switch_active"}

    symbols_to_scan = [
        (sym, True) for sym in settings.FUTURES_WATCHLIST[:2]
    ] + [
        (sym, False) for sym in settings.OPTIONS_WATCHLIST[:3]
    ]

    logger.info(f"Manual scan triggered: {[s[0] for s in symbols_to_scan]}")

    from notifications.whatsapp import get_notifier
    notifier = get_notifier()

    scan_results = []
    for symbol, is_futures in symbols_to_scan:
        try:
            result = await trading_pipeline.analyze_and_decide(symbol, is_futures)
            action = result.get("final_action", "hold")

            fund_dec = result.get("fund_decision") or {}
            trade_dec = result.get("trade_decision") or {}
            confidence = fund_dec.get("final_conviction", trade_dec.get("confidence", 0.0))
            qty = result.get("final_quantity", 0)
            price_info = trade_dec.get("limit_price") or trade_dec.get("stop_price")
            reasoning = trade_dec.get("reasoning", "")

            _decision_log.append({
                "id": len(_decision_log) + 1,
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "action": action,
                "confidence": confidence,
                "source": "manual_scan",
                "summary": result.get("summary", ""),
            })
            if len(_decision_log) > 100:
                _decision_log.pop(0)

            alert_sent = False
            alert_suppressed_reason = None

            if action not in ("hold",):
                now = datetime.now()
                last_sent = _last_alert_time.get(symbol)
                cooldown_expired = (
                    last_sent is None
                    or (now - last_sent) >= timedelta(hours=ALERT_COOLDOWN_HOURS)
                )
                if notifier.enabled and cooldown_expired:
                    price_str = f" @ {price_info:.2f}" if price_info else ""
                    pct = int(confidence * 100)
                    short_reason = (reasoning[:100] + "...") if len(reasoning) > 100 else reasoning
                    msg = (
                        f"JARVIS: {symbol} -> {action.upper()} {qty}{price_str}\n"
                        f"Confidence: {pct}%\n"
                        f"Reason: {short_reason}"
                    )
                    alert_sent = await notifier.send(msg)
                    if alert_sent:
                        _last_alert_time[symbol] = now
                elif not cooldown_expired:
                    alert_suppressed_reason = f"cooldown_active_since_{last_sent.strftime('%H:%M')}"
                elif not notifier.enabled:
                    alert_suppressed_reason = "whatsapp_not_configured"

            scan_results.append({
                "symbol": symbol,
                "action": action,
                "confidence": round(confidence, 4),
                "final_quantity": qty,
                "summary": result.get("summary", ""),
                "errors": result.get("errors", []),
                "alert_sent": alert_sent,
                "alert_suppressed_reason": alert_suppressed_reason,
            })

        except Exception as e:
            logger.error(f"Manual scan failed for {symbol}: {e}")
            scan_results.append({"symbol": symbol, "error": str(e)})

    return {
        "status": "complete",
        "scanned_at": datetime.now().isoformat(),
        "symbols_scanned": len(scan_results),
        "results": scan_results,
    }


@app.post("/notifications/whatsapp/test")
async def test_whatsapp():
    """Test WhatsApp notification config"""
    from notifications.whatsapp import get_notifier
    notifier = get_notifier()
    if not notifier.enabled:
        return {
            "status": "not_configured",
            "message": "Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, WHATSAPP_TO to .env",
        }
    ok = await notifier.test()
    return {"status": "sent" if ok else "failed"}


# ── ThinkScript Generation ─────────────────────────────────────────────────

from agents.thinkscript_generator import ThinkScriptGeneratorAgent

thinkscript_generator: ThinkScriptGeneratorAgent | None = None

class ThinkScriptRequest(BaseModel):
    symbol: str
    timeframe: str = "15m"
    is_futures: bool = False

@app.post("/thinkscript/generate")
async def generate_thinkscript(req: ThinkScriptRequest):
    """Generate ThinkScript code for ThinkorSwim from JARVIS analysis"""
    gen = ThinkScriptGeneratorAgent(
        llm_client=technical_analyst.llm_client if technical_analyst else None
    )

    # Get technical analysis first
    tech_report = None
    if technical_analyst:
        try:
            tech_report = await technical_analyst.analyze(req.symbol, req.timeframe, req.is_futures)
        except Exception:
            pass

    result = await gen.generate(
        symbol=req.symbol,
        timeframe=req.timeframe,
        technical_report=tech_report,
        script_type="study",
    )

    return {
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "title": result.title,
        "code": result.code,
        "description": result.description,
        "usage_instructions": result.usage_instructions,
        "signals_included": result.signals_included,
        "timestamp": result.timestamp.isoformat(),
    }


# ── Macro Data (FRED) ──────────────────────────────────────────────────────

@app.get("/macro/snapshot")
async def get_macro_snapshot():
    """
    Current macro environment from FRED — flat snapshot for dashboard polling.

    Returns:
        {"vix": float, "fed_funds_rate": float, "ten_year_yield": float, "unemployment": float}

    Uses a 5-minute in-memory cache so 60s dashboard polling doesn't hammer FRED.
    The underlying FREDDataService already caches at 1h per series; this adds a
    dedicated short-TTL cache for the flattened response shape.
    """
    from data.fred_data import get_fred_service

    # 5-minute in-memory cache for the flattened snapshot
    now = datetime.now()
    cached = _macro_cache.get("snapshot")
    if cached and (now - cached["_ts"]).total_seconds() < 300:
        return {k: v for k, v in cached.items() if k != "_ts"}

    service = get_fred_service()
    try:
        raw = service.get_macro_snapshot()
    except Exception as e:
        raise HTTPException(500, f"FRED data unavailable: {e}")

    # The FREDDataService returns nested dicts: {"vix": {"value": 27.4, ...}, ...}
    # Flatten to the shape the dashboard WatchlistBar expects.
    def _val(key: str):
        entry = raw.get(key)
        if entry is None:
            return None
        if isinstance(entry, dict):
            return entry.get("value")
        try:
            return float(entry)
        except (TypeError, ValueError):
            return None

    flat = {
        "vix": _val("vix"),
        "fed_funds_rate": _val("fed_funds_rate"),
        "ten_year_yield": _val("ten_year_yield"),
        "unemployment": _val("unemployment"),
        "timestamp": raw.get("timestamp", now.isoformat()),
    }

    # Store in cache with sentinel timestamp
    _macro_cache["snapshot"] = {**flat, "_ts": now}

    return flat


@app.get("/macro/series/{series_id}")
async def get_macro_series(series_id: str, periods: int = 24):
    """Get historical data for a FRED series (e.g. FEDFUNDS, GS10, VIXCLS)"""
    from data.fred_data import get_fred_service
    service = get_fred_service()
    history = service.get_series_history(series_id.upper(), periods)
    if not history:
        raise HTTPException(404, f"FRED series {series_id} not found or unavailable")
    return {"series_id": series_id.upper(), "data": history, "count": len(history)}



# ── Backtest endpoint ──────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    symbol: str = "SPY"
    start: str = "2024-01-01"
    end: str = "2025-12-31"
    interval: str = "1d"
    capital: float = 100000.0
    risk_per_trade: float = 0.01


@app.get("/backtest/results")
async def get_backtest_results():
    """Return all saved backtest result JSON files from backtest/results/."""
    import json
    from pathlib import Path

    results_dir = Path(__file__).parent / "backtest" / "results"
    if not results_dir.exists():
        return []

    results = []
    for json_file in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            data["_filename"] = json_file.name
            results.append(data)
        except Exception as e:
            logger.warning(f"Failed to parse {json_file.name}: {e}")

    return results


@app.post("/backtest/run")
async def run_backtest(request: BacktestRequest):
    """Run a backtest for a symbol over the specified date range."""
    from concurrent.futures import ThreadPoolExecutor

    def _run():
        from backtest import Backtester, BacktestDataLoader, generate_signals

        loader = BacktestDataLoader()
        df = loader.load(request.symbol, request.start, request.end, request.interval)
        if df is None or df.empty:
            raise ValueError(f"No data for {request.symbol}")
        df = generate_signals(df)
        multiplier = loader.get_multiplier(request.symbol)
        backtester = Backtester(
            initial_capital=request.capital,
            risk_per_trade=request.risk_per_trade,
        )
        result = backtester.run(df, request.symbol, multiplier)
        return result.to_dict()

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, _run)
    return result


# ── Regime & Paper-Trading Status ─────────────────────────────────────────

@app.get("/backtest/regime-status")
async def get_regime_status():
    """
    Current regime classification for tracked symbols.

    Runs RegimeClassifier on recent bars and returns the current regime,
    30-day breakdown, and key regime indicators for each symbol.
    Falls back to static data if market data is unavailable.
    """
    try:
        from backtest.regime import RegimeClassifier
        import yfinance as yf
        import pandas as pd

        results = {}

        # --- MNQ 1h (via NQ=F) ---
        try:
            nq = yf.download("NQ=F", period="10d", interval="1h", progress=False)
            if nq is not None and len(nq) >= 20:
                rc = RegimeClassifier()
                nq_classified = rc.classify(nq)
                last_regime = nq_classified['regime_type'].iloc[-1] if len(nq_classified) > 0 else "UNKNOWN"
                # 30-day breakdown (use available bars)
                regime_counts = nq_classified['regime_type'].value_counts(normalize=True) * 100
                results["MNQ_1h"] = {
                    "current_regime": str(last_regime),
                    "regime_breakdown_30d": {str(k): round(v, 1) for k, v in regime_counts.items()},
                }
            else:
                raise ValueError("Insufficient NQ data")
        except Exception:
            results["MNQ_1h"] = {
                "current_regime": "RANGING",
                "regime_breakdown_30d": {"TRENDING": 15.3, "RANGING": 80.5, "VOLATILE": 4.2},
            }

        # --- MGC 1d (via GC=F) ---
        try:
            gc = yf.download("GC=F", period="60d", interval="1d", progress=False)
            if gc is not None and len(gc) >= 20:
                rc = RegimeClassifier()
                gc_classified = rc.classify(gc)
                last_regime = gc_classified['regime_type'].iloc[-1] if len(gc_classified) > 0 else "UNKNOWN"
                last_row = gc_classified.iloc[-1]
                results["MGC_1d"] = {
                    "current_regime": str(last_regime),
                    "adaptive_stc_os": int(last_row.get('adaptive_stc_os', 15)),
                    "adaptive_stc_ob": int(last_row.get('adaptive_stc_ob', 92)),
                }
            else:
                raise ValueError("Insufficient GC data")
        except Exception:
            results["MGC_1d"] = {
                "current_regime": "TRENDING",
                "adaptive_stc_os": 15,
                "adaptive_stc_ob": 92,
            }

        return results

    except ImportError:
        # RegimeClassifier not available — return static fallback
        return {
            "MNQ_1h": {
                "current_regime": "RANGING",
                "regime_breakdown_30d": {"TRENDING": 15.3, "RANGING": 80.5, "VOLATILE": 4.2},
            },
            "MGC_1d": {
                "current_regime": "TRENDING",
                "adaptive_stc_os": 15,
                "adaptive_stc_ob": 92,
            },
        }


@app.get("/backtest/paper-status")
async def get_paper_status():
    """
    Walk-Forward Efficiency (WFE) and paper-trading readiness for each symbol.

    Returns the current status (ACTIVE / RESEARCH / NO-TRADE), WFE score,
    and configuration details for symbols being tracked.
    """
    return {
        "MGC_1d": {
            "status": "ACTIVE",
            "wfe": 0.88,
            "wfe_label": "EXCELLENT",
            "cleared_date": "2026-03-29",
            "risk_per_trade": "0.25%",
            "config": "adaptive_regime=ON",
        },
        "MNQ_1h": {
            "status": "RESEARCH",
            "wfe": 0.34,
            "wfe_label": "ACCEPTABLE",
            "target_wfe": 0.40,
        },
        "MCL_1h": {
            "status": "NO-TRADE",
            "wfe": -0.31,
            "wfe_label": "FAILED",
            "target_wfe": 0.40,
        },
    }


# ── MGC Paper Trading — Live Signal Generation ──────────────────────────────

class MGCTradeLogRequest(BaseModel):
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    contracts: int = 1
    direction: str = "LONG"
    exit_reason: str = "unknown"
    regime_type: str = "unknown"


@app.get("/paper/mgc-signal")
async def get_mgc_signal():
    """
    Generate today's MGC (Gold Micro) signal using the walk-forward validated
    adaptive regime strategy (WFE=0.88).

    Fetches 200 daily bars of GC=F via yfinance, runs the full indicator +
    regime + signal pipeline, and returns the last bar's signal with entry/exit
    levels.
    """
    from concurrent.futures import ThreadPoolExecutor

    def _generate_signal():
        import yfinance as yf
        from backtest.signals import compute_all_indicators, generate_signals
        from backtest.regime import RegimeClassifier
        from backtest.paper_config import MGC_PAPER_CONFIG

        # Fetch data
        gc = yf.download("GC=F", period="200d", interval="1d", progress=False)
        if gc is None or len(gc) < 50:
            return {"error": "Insufficient GC=F data from yfinance", "bars_received": len(gc) if gc is not None else 0}

        # Flatten MultiIndex columns if present (yfinance sometimes returns them)
        if hasattr(gc.columns, 'nlevels') and gc.columns.nlevels > 1:
            gc.columns = gc.columns.get_level_values(0)

        # Normalize column names to lowercase
        gc.columns = [c.lower() for c in gc.columns]

        # Run full signal pipeline with adaptive regime
        df = generate_signals(
            gc,
            symbol='MGC',
            adaptive_regime=True,
            regime_filter=True,
        )

        if df.empty:
            return {"error": "Signal generation returned empty DataFrame"}

        # Extract last bar
        last = df.iloc[-1]
        config = MGC_PAPER_CONFIG

        # Determine direction from bias
        bias = str(last.get('bias', 'NEUTRAL'))
        if bias in ('STRONG_BULL', 'LEAN_BULL'):
            direction = "LONG"
        elif bias in ('STRONG_BEAR', 'LEAN_BEAR'):
            direction = "SHORT"
        else:
            direction = None

        entry_signal = str(last.get('entry_signal', 'NO_TRADE'))
        regime_type = str(last.get('regime_type', 'UNKNOWN'))

        # Map signal to simplified output
        if entry_signal == 'ENTRY_NOW':
            signal = "ENTRY_NOW"
        elif entry_signal == 'WAIT_FOR_PULLBACK':
            signal = "WAIT_FOR_PULLBACK"
        elif entry_signal == 'FADE_EXTREME':
            signal = "FADE_EXTREME"
        else:
            signal = "NO_ENTRY"

        # Get date from index
        signal_date = str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else str(df.index[-1])[:10]

        return {
            "date": signal_date,
            "symbol": "MGC",
            "signal": signal,
            "direction": direction,
            "regime": regime_type,
            "adaptive_stc_os": int(last.get('adaptive_stc_os', 15)),
            "adaptive_stc_ob": int(last.get('adaptive_stc_ob', 92)),
            "entry_price": round(float(last['close']), 2),
            "stop_level": round(float(last.get('stop_level', 0)), 2),
            "target_1": round(float(last.get('target_1', 0)), 2),
            "target_2": round(float(last.get('target_2', 0)), 2),
            "atr": round(float(last.get('atr', 0)), 2),
            "bias": bias,
            "stc_val": round(float(last.get('stc_val', 50)), 2),
            "stc_signal": str(last.get('stc_signal', 'neutral')),
            "ema_trend": str(last.get('ema_trend', 'neutral')),
            "config": f"adaptive_regime=ON, risk={config['risk_per_trade']*100:.2f}%",
        }

    try:
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, _generate_signal)
        if "error" in result:
            raise HTTPException(503, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PAPER-MGC] Signal generation failed: {e}")
        raise HTTPException(500, f"MGC signal generation failed: {e}")


@app.post("/paper/mgc-log-trade")
async def log_mgc_paper_trade(req: MGCTradeLogRequest):
    """
    Log a completed MGC paper trade and return updated performance metrics.

    The trade is recorded via PaperTradeTracker (JSON persistence in
    backtest/results/paper_trades_MGC.json) with automatic P&L calculation
    including commission and slippage.
    """
    try:
        from backtest.paper_tracker import PaperTradeTracker
        from backtest.paper_config import MGC_PAPER_CONFIG

        tracker = PaperTradeTracker(MGC_PAPER_CONFIG)

        trade_dict = {
            "entry_date": req.entry_date,
            "exit_date": req.exit_date,
            "entry_price": req.entry_price,
            "exit_price": req.exit_price,
            "contracts": req.contracts,
            "side": req.direction.lower(),
            "exit_reason": req.exit_reason,
            "regime_type": req.regime_type.lower(),
        }

        tracker.add_trade(trade_dict)

        # Check kill conditions
        should_kill, kill_reason = tracker.check_kill_conditions()

        metrics = tracker.get_metrics()
        metrics["trade_logged"] = True
        metrics["kill_threshold_breached"] = should_kill
        metrics["kill_reason"] = kill_reason if should_kill else None

        # Send WhatsApp alert for new trade
        try:
            from notifications.whatsapp import get_notifier
            notifier = get_notifier()
            if notifier.enabled:
                pnl = trade_dict.get("pnl", 0)
                msg = (
                    f"JARVIS PAPER-MGC: {req.direction} trade closed\n"
                    f"Entry: {req.entry_price:.2f} -> Exit: {req.exit_price:.2f}\n"
                    f"Reason: {req.exit_reason}\n"
                    f"Total trades: {metrics['total_trades']}, "
                    f"Win rate: {metrics['win_rate']:.0%}"
                )
                if should_kill:
                    msg += f"\n*** KILL THRESHOLD BREACHED: {kill_reason} ***"
                asyncio.create_task(notifier.send(msg))
        except Exception:
            pass  # notification failure should not block the trade log

        return metrics

    except Exception as e:
        logger.error(f"[PAPER-MGC] Trade log failed: {e}")
        raise HTTPException(500, f"Failed to log MGC paper trade: {e}")


@app.get("/paper/mgc-performance")
async def get_mgc_paper_performance():
    """
    Return current MGC paper trading performance metrics.

    Reads from the PaperTradeTracker JSON store and returns:
    total trades, P&L, win rate, profit factor, max drawdown,
    regime breakdown, exit reason breakdown, and kill condition status.
    """
    try:
        from backtest.paper_tracker import PaperTradeTracker
        from backtest.paper_config import MGC_PAPER_CONFIG

        tracker = PaperTradeTracker(MGC_PAPER_CONFIG)
        metrics = tracker.get_metrics()

        # Add kill condition check
        should_kill, kill_reason = tracker.check_kill_conditions()
        metrics["kill_threshold_breached"] = should_kill
        metrics["kill_reason"] = kill_reason if should_kill else None
        metrics["monthly_summary"] = tracker.monthly_summary()
        metrics["config"] = {
            "symbol": MGC_PAPER_CONFIG["symbol"],
            "interval": MGC_PAPER_CONFIG["interval"],
            "adaptive_regime": MGC_PAPER_CONFIG["adaptive_regime"],
            "risk_per_trade": MGC_PAPER_CONFIG["risk_per_trade"],
            "initial_capital": MGC_PAPER_CONFIG["initial_capital"],
            "wfe": 0.88,
        }

        return metrics

    except Exception as e:
        logger.error(f"[PAPER-MGC] Performance query failed: {e}")
        raise HTTPException(500, f"Failed to get MGC performance: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
