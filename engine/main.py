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
from datetime import datetime, timedelta, timezone
from typing import Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.models import (
    HealthResponse,
    FullHealthResponse,
    IBConnectionTestResponse,
    IBConnectResponse,
    SafetyStatusResponse,
    CircuitBreakerStatus,
    SafetyConfigResponse,
    KillSwitchToggleResponse,
    TechnicalAnalysisResponse,
    BarsResponse,
    RedditSentimentResponse,
    NewsSentimentResponse,
    PortfolioResponse,
    PaperPositionsResponse,
    PaperTradeResponse,
    PaperPerformanceResponse,
    PendingSignalsResponse,
    PaperKillSwitchStatus,
    PaperKillSwitchToggleResponse,
    ResetSignalsResponse,
    TradeHistoryResponse,
    DailyPnLResponse,
    DecisionHistoryResponse,
    StatsSummaryResponse,
    DrawdownResponse,
    TradingDaysResponse,
    PaperPhaseSummaryResponse,
    WebSocketStatusResponse,
)

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
from routers.webhook_router import router as webhook_router, set_pipeline_callback, get_recent_webhooks
from websocket.manager import WebSocketManager
from websocket.events import set_ws_manager

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
ws_manager: WebSocketManager | None = None

# Rate limit: track last alert time per symbol to avoid flooding (2-hour cooldown)
_last_alert_time: Dict[str, datetime] = {}
ALERT_COOLDOWN_HOURS = 2

# 5-minute macro snapshot cache (keyed by "snapshot", stores flattened dict + "_ts")
_macro_cache: Dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and teardown on startup/shutdown"""
    global data_manager, safety_layer, technical_analyst, trading_pipeline, scheduler, paper_tracker, db_manager, pnl_monitor, eod_scheduler, order_manager, ws_manager

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

    # WebSocket manager for real-time event streaming
    ws_manager = WebSocketManager()
    set_ws_manager(ws_manager)
    logger.info("✅ WebSocket manager initialized for real-time events")

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


# ── API Versioning ────────────────────────────────────────────────────────────
# Create v1 router with /v1 prefix for future versioning support
v1_router = APIRouter(prefix="/v1", tags=["v1"])

# Register all endpoints with the v1 router below.
# For now, we serve the same endpoints under both / (legacy) and /v1 (new).
# This allows clients to transition gradually.


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3010", "http://localhost:3000", "http://localhost:3004"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(journal_router, prefix="/journal", tags=["journal"])
app.include_router(v1_router)


# ── Health ────────────────────────────────────────────────────────────────

_start_time = datetime.now(timezone.utc)

@app.get("/health", response_model=HealthResponse)
async def health():
    safety = safety_layer.get_status() if safety_layer else {}

    # Quick database connectivity check
    db_ok = False
    try:
        if db_manager:
            db_manager.health_check()
            db_ok = True
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    status = "ok" if db_ok else "degraded"

    return {
        "status": status,
        "version": "1.1.0",
        "timestamp": now.isoformat(),
        "live_trading": settings.LIVE_TRADING_ENABLED,
        "kill_switch_active": safety.get("kill_switch_active", False),
        "paper_mode": not settings.LIVE_TRADING_ENABLED,
        "database": "connected" if db_ok else "error",
        "ibkr_connected": data_manager.ibkr.is_connected() if data_manager and data_manager.ibkr else False,
        "schwab_connected": False,  # Schwab connector TODO
        "uptime_seconds": (now - _start_time).total_seconds(),
    }


@app.get("/health/full", response_model=FullHealthResponse)
async def full_health_check():
    """Comprehensive health check of all JARVIS TRADER subsystems."""
    status: dict = {}
    overall = "healthy"

    # 1. Database health
    try:
        if db_manager:
            db_health = db_manager.health_check()
            status["database"] = {"status": "ok", "details": db_health}
        else:
            status["database"] = {"status": "not_initialized"}
            overall = "degraded"
    except Exception as e:
        status["database"] = {"status": "error", "error": str(e)}
        overall = "degraded"

    # 2. Safety layer
    try:
        if safety_layer:
            kill_switch = safety_layer._kill_switch_active
            kill_reason = safety_layer._kill_switch_reason
            status["safety_layer"] = {
                "status": "ok",
                "kill_switch_active": kill_switch,
                "kill_switch_reason": kill_reason.value if kill_reason else None,
            }
            if kill_switch:
                overall = "kill_switch_active"
        else:
            status["safety_layer"] = {"status": "not_initialized"}
            overall = "degraded"
    except Exception as e:
        status["safety_layer"] = {"status": "error", "error": str(e)}
        overall = "degraded"

    # 3. IB Gateway (optional — may not be connected)
    try:
        ib_gw = data_manager.ibkr if data_manager else None
        if ib_gw:
            ib_health = await ib_gw.health_check()
            status["ib_gateway"] = ib_health
        else:
            status["ib_gateway"] = {"status": "not_configured", "mode": "paper_only"}
    except Exception as e:
        status["ib_gateway"] = {"status": "error", "error": str(e)}

    # 4. Circuit breakers
    try:
        if safety_layer and hasattr(safety_layer, "check_circuit_breakers"):
            breakers = safety_layer.check_circuit_breakers()
            status["circuit_breakers"] = breakers
            if not breakers.get("all_clear", True):
                # Only escalate if kill switch hasn't already set a stronger state
                if overall == "healthy":
                    overall = "circuit_breaker_tripped"
        else:
            status["circuit_breakers"] = {"status": "not_available"}
    except Exception as e:
        status["circuit_breakers"] = {"status": "error", "error": str(e)}

    # 5. Portfolio tracker
    try:
        if paper_tracker:
            positions = paper_tracker.get_open_positions()
            status["portfolio"] = {
                "status": "ok",
                "open_positions": len(positions),
            }
        else:
            status["portfolio"] = {"status": "not_initialized"}
    except Exception as e:
        status["portfolio"] = {"status": "error", "error": str(e)}

    # 6. PnL monitor
    try:
        if pnl_monitor:
            pnl_state = pnl_monitor.get_current_pnl_state()
            status["pnl_monitor"] = {
                "status": "ok",
                "source": pnl_state.source,
                "daily_pnl": round(pnl_monitor.get_daily_pnl(), 4),
                "drawdown_pct": round(pnl_monitor.get_drawdown_pct(), 6),
                "current_balance": round(pnl_state.current_balance, 2),
                "starting_balance": round(pnl_state.starting_balance, 2),
            }
        else:
            status["pnl_monitor"] = {"status": "not_initialized"}
    except Exception as e:
        status["pnl_monitor"] = {"status": "error", "error": str(e)}

    return {
        "overall": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": (datetime.now(timezone.utc) - _start_time).total_seconds(),
        "subsystems": status,
        "version": "1.1.0",
        "phase": "paper_trading",
    }


# ── Safety / Kill Switch ──────────────────────────────────────────────────

@app.post("/safety/kill-switch/activate", response_model=KillSwitchToggleResponse)
async def activate_kill_switch(reason: str = "manual"):
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    from risk.safety_layer import KillSwitchReason
    safety_layer.activate_kill_switch(KillSwitchReason.MANUAL, f"Manual activation: {reason}")
    from notifications.whatsapp import get_notifier
    from websocket.events import emit_kill_switch_change
    asyncio.create_task(get_notifier().alert_kill_switch(reason))
    asyncio.create_task(emit_kill_switch_change(active=True, reason=reason))
    return {"status": "kill_switch_activated", "reason": reason}


@app.post("/safety/kill-switch/deactivate", response_model=KillSwitchToggleResponse)
async def deactivate_kill_switch():
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    from websocket.events import emit_kill_switch_change
    safety_layer.deactivate_kill_switch(authorized_by="matt_dashboard")
    asyncio.create_task(emit_kill_switch_change(active=False, reason="Manual deactivation"))
    return {"status": "kill_switch_deactivated"}


@app.get("/safety/status", response_model=SafetyStatusResponse)
async def safety_status():
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    return safety_layer.get_status()


@app.get("/safety/circuit-breakers", response_model=CircuitBreakerStatus)
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


@app.get("/safety/config", response_model=SafetyConfigResponse)
async def get_safety_config():
    """
    Return current risk parameter configuration (read-only).
    Sourced from settings singleton — reflects .env values at startup.
    """
    return {
        "max_daily_loss_pct": settings.MAX_DAILY_LOSS_PCT,
        "max_drawdown_pct": settings.MAX_DRAWDOWN_PCT,
        "max_position_size_pct": settings.MAX_POSITION_SIZE_PCT,
        "max_contracts_per_instrument": settings.MAX_CONTRACTS_PER_INSTRUMENT,
        "max_overnight_contracts": settings.MAX_OVERNIGHT_CONTRACTS,
        "max_orders_per_minute": settings.MAX_ORDERS_PER_MINUTE,
        "max_single_order_value": settings.MAX_SINGLE_ORDER_VALUE,
        "max_margin_utilization": settings.MAX_MARGIN_UTILIZATION,
        "live_trading_enabled": settings.LIVE_TRADING_ENABLED,
        "require_human_approval": settings.REQUIRE_HUMAN_APPROVAL,
        "ibkr_host": settings.IBKR_HOST,
        "ibkr_port": settings.IBKR_PORT,
        "ibkr_client_id": settings.IBKR_CLIENT_ID,
        "ibkr_paper_mode": settings.IBKR_PAPER_MODE,
    }


@app.post("/safety/reset-daily-pnl", response_model=dict)
async def reset_daily_pnl():
    """Reset the in-memory daily P&L counter (useful for testing)."""
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    safety_layer._daily_realized_pnl = 0.0
    safety_layer._daily_order_count = 0
    return {"status": "daily_pnl_reset", "message": "Daily P&L counter cleared"}


# ── Analysis ──────────────────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    symbol: str
    timeframe: str = "15m"
    is_futures: bool = False


@app.post("/analyze/technical", response_model=TechnicalAnalysisResponse)
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


@app.get("/analyze/bars/{symbol}", response_model=BarsResponse)
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


@app.get("/sentiment/reddit", response_model=RedditSentimentResponse)
async def get_reddit_sentiment(filter: str = "all-stocks"):
    """Get trending tickers from Reddit"""
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    tickers = await data_manager.reddit.get_trending_tickers(filter)
    return {"filter": filter, "tickers": tickers[:20]}


@app.get("/sentiment/news/{symbol}", response_model=NewsSentimentResponse)
async def get_news_sentiment(symbol: str):
    """Get news sentiment for a symbol via Finnhub"""
    if not data_manager or not data_manager.finnhub:
        raise HTTPException(503, "Finnhub not connected (add FINNHUB_API_KEY to .env)")

    sentiment = data_manager.finnhub.get_news_sentiment(symbol)
    return {"symbol": symbol, "sentiment": sentiment}


# ── Portfolio ─────────────────────────────────────────────────────────────

@app.get("/portfolio", response_model=PortfolioResponse)
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


@app.get("/portfolio/paper/positions", response_model=PaperPositionsResponse)
async def get_paper_positions():
    """Return all currently open paper-trade positions."""
    if not paper_tracker:
        raise HTTPException(503, "Paper tracker not initialized")
    return {
        "positions": paper_tracker.get_open_positions(),
        "count": len(paper_tracker.get_open_positions()),
    }


@app.post("/portfolio/paper/trade", response_model=PaperTradeResponse)
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


@app.get("/portfolio/paper/performance", response_model=PaperPerformanceResponse)
async def get_paper_performance():
    """Return performance metrics for all closed paper trades."""
    if not paper_tracker:
        raise HTTPException(503, "Paper tracker not initialized")
    return paper_tracker.get_performance()


# ── Pending Signals (MGC daily scanner output) ────────────────────────────

@app.get("/paper/pending-signals", response_model=PendingSignalsResponse)
async def get_pending_signals():
    """
    Return pending entry signals generated by the daily MGC scanner.

    Reads from backtest/results/pending_signals.json. Each entry includes
    date, symbol, direction, estimated entry price, stop, target, regime,
    and a status field (pending / filled / expired).
    """
    import json as _json
    from pathlib import Path

    pending_file = Path(__file__).parent / "backtest" / "results" / "pending_signals.json"
    if not pending_file.exists():
        return {"signals": [], "count": 0}

    try:
        signals = _json.loads(pending_file.read_text(encoding="utf-8"))
    except Exception:
        signals = []

    return {"signals": signals, "count": len(signals)}


# ── Historical Query Endpoints (SQLite) ───────────────────────────────────

@app.get("/portfolio/history/trades", response_model=TradeHistoryResponse)
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


@app.get("/portfolio/history/daily-pnl", response_model=DailyPnLResponse)
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


@app.get("/portfolio/history/decisions", response_model=DecisionHistoryResponse)
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


@app.get("/portfolio/stats/summary", response_model=StatsSummaryResponse)
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


@app.get("/portfolio/stats/drawdown", response_model=DrawdownResponse)
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


REQUIRED_TRADING_DAYS = 30


@app.get("/portfolio/stats/trading-days", response_model=TradingDaysResponse)
async def get_trading_days():
    """
    Return the number of unique calendar days that had at least one closed trade.

    Merges dates from both ``daily_pnl`` (rows with trade_count > 0) and
    ``paper_trades`` (distinct date(entry_time) for closed trades) so the
    count is accurate even when the EOD snapshot has not run yet today.
    """
    if not db_manager:
        return TradingDaysResponse(
            active_trading_days=0,
            first_trade_date=None,
            last_trade_date=None,
            required_days_for_live=REQUIRED_TRADING_DAYS,
            days_remaining=REQUIRED_TRADING_DAYS,
            ready_for_live=False,
            session_duration_calendar_days=0,
        )
    try:
        sql_daily = (
            "SELECT DISTINCT date FROM daily_pnl WHERE trade_count > 0 ORDER BY date ASC"
        )
        sql_paper = (
            "SELECT DISTINCT date(entry_time) AS date FROM paper_trades "
            "WHERE status = 'closed'"
        )
        with db_manager._lock:
            conn = db_manager._connect()
            try:
                rows_daily = conn.execute(sql_daily).fetchall()
                rows_paper = conn.execute(sql_paper).fetchall()
            finally:
                conn.close()

        dates = set()
        for row in rows_daily:
            if row["date"]:
                dates.add(str(row["date"])[:10])
        for row in rows_paper:
            if row["date"]:
                dates.add(str(row["date"])[:10])

        sorted_dates = sorted(dates)
        active_days = len(sorted_dates)
        first_date = sorted_dates[0] if sorted_dates else None
        last_date = sorted_dates[-1] if sorted_dates else None

        if first_date and last_date and first_date != last_date:
            from datetime import date as _date
            d0 = _date.fromisoformat(first_date)
            d1 = _date.fromisoformat(last_date)
            calendar_days = (d1 - d0).days
        else:
            calendar_days = 0

        days_remaining = max(0, REQUIRED_TRADING_DAYS - active_days)
        return TradingDaysResponse(
            active_trading_days=active_days,
            first_trade_date=first_date,
            last_trade_date=last_date,
            required_days_for_live=REQUIRED_TRADING_DAYS,
            days_remaining=days_remaining,
            ready_for_live=(active_days >= REQUIRED_TRADING_DAYS),
            session_duration_calendar_days=calendar_days,
        )
    except Exception as exc:
        logger.error(f"[DB] get_trading_days failed: {exc}")
        return TradingDaysResponse(
            active_trading_days=0,
            first_trade_date=None,
            last_trade_date=None,
            required_days_for_live=REQUIRED_TRADING_DAYS,
            days_remaining=REQUIRED_TRADING_DAYS,
            ready_for_live=False,
            session_duration_calendar_days=0,
        )


@app.get("/portfolio/stats/paper-phase-summary", response_model=PaperPhaseSummaryResponse)
async def get_paper_phase_summary():
    """
    Comprehensive paper-trading phase summary for the scorecard page.

    Combines trade counts, balance, return percentage, active trading days,
    and live-readiness into a single response so the scorecard only needs
    one API call.
    """
    if not db_manager:
        return PaperPhaseSummaryResponse(
            phase="paper",
            started_at=None,
            trading_days=0,
            required_trading_days=REQUIRED_TRADING_DAYS,
            total_trades=0,
            current_balance=10000.0,
            initial_balance=10000.0,
            total_return_pct=0.0,
            validation_ready=False,
        )
    try:
        initial_balance = float(
            db_manager.get_setting("INITIAL_ACCOUNT_VALUE", default=10000.0) or 10000.0
        )

        sql_trades = (
            "SELECT COUNT(*) AS total_trades, COALESCE(SUM(pnl), 0.0) AS total_pnl, "
            "MIN(entry_time) AS first_entry "
            "FROM paper_trades WHERE status = 'closed'"
        )
        sql_daily_dates = (
            "SELECT DISTINCT date FROM daily_pnl WHERE trade_count > 0"
        )
        sql_paper_dates = (
            "SELECT DISTINCT date(entry_time) AS date FROM paper_trades "
            "WHERE status = 'closed'"
        )

        with db_manager._lock:
            conn = db_manager._connect()
            try:
                tr = conn.execute(sql_trades).fetchone()
                rows_daily = conn.execute(sql_daily_dates).fetchall()
                rows_paper = conn.execute(sql_paper_dates).fetchall()
            finally:
                conn.close()

        total_trades = int(tr["total_trades"]) if tr else 0
        total_pnl = float(tr["total_pnl"]) if tr else 0.0
        first_entry = str(tr["first_entry"]) if tr and tr["first_entry"] else None

        dates: set = set()
        for row in rows_daily:
            if row["date"]:
                dates.add(str(row["date"])[:10])
        for row in rows_paper:
            if row["date"]:
                dates.add(str(row["date"])[:10])

        trading_days = len(dates)
        current_balance = initial_balance + total_pnl
        total_return_pct = (
            round((total_pnl / initial_balance) * 100, 4) if initial_balance else 0.0
        )

        return PaperPhaseSummaryResponse(
            phase="paper",
            started_at=first_entry,
            trading_days=trading_days,
            required_trading_days=REQUIRED_TRADING_DAYS,
            total_trades=total_trades,
            current_balance=round(current_balance, 2),
            initial_balance=round(initial_balance, 2),
            total_return_pct=total_return_pct,
            validation_ready=(trading_days >= REQUIRED_TRADING_DAYS),
        )
    except Exception as exc:
        logger.error(f"[DB] get_paper_phase_summary failed: {exc}")
        return PaperPhaseSummaryResponse(
            phase="paper",
            started_at=None,
            trading_days=0,
            required_trading_days=REQUIRED_TRADING_DAYS,
            total_trades=0,
            current_balance=10000.0,
            initial_balance=10000.0,
            total_return_pct=0.0,
            validation_ready=False,
        )


# ── Pipeline Run History ───────────────────────────────────────────────────

@app.get("/pipeline/history")
async def get_pipeline_history(limit: int = 50, symbol: str = ""):
    """
    Return historical pipeline run records from SQLite.

    Each record corresponds to one TradingPipeline execution triggered by
    a TradingView webhook or manual call.

    Query params:
        limit  : max rows to return (default 50, capped at 200)
        symbol : filter by ticker symbol (optional, case-insensitive)
    """
    if not db_manager:
        return {"runs": [], "count": 0, "note": "db_manager not initialized"}
    try:
        limit = min(max(1, limit), 200)
        runs = db_manager.get_pipeline_history(
            limit=limit,
            symbol=symbol.upper() if symbol else None,
        )
        return {"runs": runs, "count": len(runs)}
    except Exception as exc:
        logger.error(f"[DB] get_pipeline_history failed: {exc}")
        return {"runs": [], "count": 0, "error": str(exc)}


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
    Compare current live/paper metrics against confirmed backtest targets.

    Backtest baseline (MES 1h, 2023-2024):
      PF=5.27, Sharpe=4.16, WinRate=68%, MaxDD=-8.2%, TotalReturn=+47.2%

    Live/paper values are read from SQLite via PerformanceCalculator.
    Returns:
      backtest              — confirmed backtest values + metadata
      live_paper            — current forward-test metrics (zeros when no data)
      validation_thresholds — per-metric pass/fail vs required minimums
      ready_for_live        — True only when all thresholds are met
      degradation_factor    — live/backtest ratio per metric (null = no live data)
    """
    from analytics.performance import (
        BACKTEST_PROFIT_FACTOR,
        BACKTEST_SHARPE,
        BACKTEST_WIN_RATE,
        BACKTEST_MAX_DRAWDOWN,
        BACKTEST_TOTAL_RETURN,
        BACKTEST_SYMBOL,
        BACKTEST_TIMEFRAME,
        BACKTEST_PERIOD,
        PROFIT_FACTOR_TARGET,
        SHARPE_TARGET,
        MIN_TRADING_DAYS_REQUIRED,
    )

    # Canonical no-data response (db not ready or no trades yet)
    _empty_response = {
        "backtest": {
            "profit_factor": BACKTEST_PROFIT_FACTOR,
            "sharpe_ratio": BACKTEST_SHARPE,
            "win_rate": BACKTEST_WIN_RATE,
            "max_drawdown": BACKTEST_MAX_DRAWDOWN,
            "total_return_pct": BACKTEST_TOTAL_RETURN,
            "symbol": BACKTEST_SYMBOL,
            "timeframe": BACKTEST_TIMEFRAME,
            "period": BACKTEST_PERIOD,
        },
        "live_paper": {
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "total_return_pct": 0.0,
            "trade_count": 0,
            "trading_days": 0,
        },
        "validation_thresholds": {
            "profit_factor": {"required": PROFIT_FACTOR_TARGET, "met": False},
            "sharpe_ratio": {"required": SHARPE_TARGET, "met": False},
            "min_trading_days": {
                "required": MIN_TRADING_DAYS_REQUIRED,
                "current": 0,
                "met": False,
            },
        },
        "ready_for_live": False,
        "degradation_factor": {
            "profit_factor": None,
            "sharpe_ratio": None,
            "note": "No live data yet",
        },
    }

    if not db_manager:
        return {**_empty_response, "note": "Database not initialized."}

    try:
        from analytics.performance import PerformanceCalculator
        calc = PerformanceCalculator(db_manager)
        return calc.compare_to_backtest()
    except Exception as exc:
        logger.error(f"[Analytics] compare_to_backtest failed: {exc}")
        raise HTTPException(500, f"Analytics error: {exc}")


@app.get("/validation/readiness-check")
async def get_readiness_check():
    """Comprehensive pre-live trading readiness check."""
    checks = []

    def add_check(name: str, passed: bool, value: str, requirement: str, critical: bool = True):
        checks.append({
            "name": name,
            "passed": passed,
            "value": value,
            "requirement": requirement,
            "critical": critical,
        })

    # --- Performance checks ---
    try:
        if db_manager:
            from analytics.performance import PerformanceCalculator
            calc = PerformanceCalculator(db_manager)
            summary = calc.calculate_summary()

            pf = summary.get("profit_factor")
            sharpe = summary.get("sharpe_ratio")
            win_rate = summary.get("win_rate", 0)
            drawdown = summary.get("max_drawdown", 0)
            total_trades = summary.get("total_trades", 0)

            add_check("Profit Factor", bool(pf and pf >= 2.0),
                      f"{pf:.2f}" if pf else "N/A", ">= 2.0")
            add_check("Sharpe Ratio", bool(sharpe and sharpe >= 1.5),
                      f"{sharpe:.2f}" if sharpe else "N/A", ">= 1.5")
            add_check("Win Rate", bool(win_rate and win_rate >= 0.50),
                      f"{win_rate*100:.1f}%" if win_rate else "N/A", ">= 50%", critical=False)
            add_check("Max Drawdown", bool(abs(drawdown) <= 0.15),
                      f"{drawdown*100:.1f}%", "<= -15%", critical=False)
            add_check("Minimum Trades", total_trades >= 30,
                      str(total_trades), ">= 30 trades")
        else:
            for name in ["Profit Factor", "Sharpe Ratio", "Minimum Trades"]:
                add_check(name, False, "N/A", "Database required")
    except Exception as e:
        add_check("Performance Data", False, f"Error: {str(e)[:50]}", "Available")

    # --- Trading days check ---
    try:
        if db_manager:
            import sqlite3
            conn = sqlite3.connect(db_manager.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT date) FROM daily_pnl WHERE trade_count > 0")
            days = cursor.fetchone()[0] or 0
            conn.close()
            add_check("Trading Days", days >= 30, str(days), ">= 30 days")
        else:
            add_check("Trading Days", False, "N/A", "Database required")
    except Exception:
        add_check("Trading Days", False, "Error", ">= 30 days")

    # --- System checks ---
    # Kill switch
    try:
        if safety_layer:
            cb = safety_layer.get_circuit_breaker_status()
            kill_active = cb.get("kill_switch_active", False)
            add_check("Kill Switch Clear", not kill_active,
                      "ACTIVE" if kill_active else "CLEAR", "Not active", critical=True)
        else:
            add_check("Kill Switch Clear", False, "N/A", "Safety layer required")
    except Exception:
        add_check("Kill Switch Clear", False, "Error", "Safety layer required")

    # Database health
    try:
        if db_manager:
            health = db_manager.health_check()
            db_ok = health.get("status") == "healthy"
            add_check("Database", db_ok, "Healthy" if db_ok else "Unhealthy", "Healthy", critical=False)
        else:
            add_check("Database", False, "Not initialized", "Initialized", critical=False)
    except Exception:
        add_check("Database", False, "Error", "Healthy", critical=False)

    critical_checks = [c for c in checks if c["critical"]]
    all_critical_pass = all(c["passed"] for c in critical_checks)
    all_pass = all(c["passed"] for c in checks)
    passed_count = sum(1 for c in checks if c["passed"])

    return {
        "ready_for_live": all_critical_pass,
        "all_checks_pass": all_pass,
        "checks": checks,
        "passed": passed_count,
        "total": len(checks),
        "summary": "READY" if all_critical_pass else "NOT READY",
    }


# ── Market session status ──────────────────────────────────────────────────

@app.get("/market/session")
async def get_market_session():
    """Return current market session status."""
    from datetime import datetime, time, timezone
    import pytz

    ct = pytz.timezone("America/Chicago")
    now_ct = datetime.now(ct)
    weekday = now_ct.weekday()  # 0=Mon, 6=Sun
    current_time = now_ct.time()

    # Market hours in CT
    pre_market_start = time(7, 0)   # 7:00 AM CT
    rth_start = time(8, 30)         # 8:30 AM CT (RTH open = 9:30 ET)
    rth_end = time(15, 0)           # 3:00 PM CT (RTH close = 4:00 ET)
    after_hours_end = time(17, 0)   # 5:00 PM CT (futures reset)

    # Futures sessions (CME Globex) in CT
    futures_open = time(17, 0)      # 5:00 PM CT day before (Sunday evening)
    futures_close = time(16, 0)     # 4:00 PM CT

    is_weekend = weekday >= 5

    if is_weekend and weekday == 6 and current_time >= time(17, 0):
        session = "FUTURES_OPEN"
        label = "Futures Open (Sunday Evening)"
        color = "green"
    elif is_weekend:
        session = "WEEKEND"
        label = "Weekend — Markets Closed"
        color = "gray"
    elif current_time < pre_market_start:
        session = "OVERNIGHT"
        label = "Overnight Session"
        color = "blue"
    elif current_time < rth_start:
        session = "PRE_MARKET"
        label = "Pre-Market"
        color = "yellow"
    elif current_time < rth_end:
        session = "RTH"
        label = "Regular Trading Hours"
        color = "green"
    elif current_time < after_hours_end:
        session = "AFTER_HOURS"
        label = "After Hours"
        color = "yellow"
    else:
        session = "FUTURES_OPEN"
        label = "Futures Open"
        color = "green"

    # Next session transition
    # Calculate minutes until next transition
    def minutes_until(target_time):
        target_dt = now_ct.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
        if target_dt <= now_ct:
            # Add a day
            from datetime import timedelta
            target_dt += timedelta(days=1)
        return int((target_dt - now_ct).total_seconds() / 60)

    next_transitions = {
        "OVERNIGHT": ("Pre-Market", minutes_until(pre_market_start)),
        "PRE_MARKET": ("RTH Open", minutes_until(rth_start)),
        "RTH": ("RTH Close", minutes_until(rth_end)),
        "AFTER_HOURS": ("Futures Open", minutes_until(after_hours_end)),
        "FUTURES_OPEN": ("RTH Open", minutes_until(rth_start)),
        "WEEKEND": ("Futures Open Sunday", None),
    }

    next_session, mins_until = next_transitions.get(session, ("Unknown", None))

    return {
        "session": session,
        "label": label,
        "color": color,
        "is_trading_hours": session == "RTH",
        "is_futures_active": session in ("RTH", "FUTURES_OPEN", "PRE_MARKET", "AFTER_HOURS", "OVERNIGHT"),
        "timestamp_ct": now_ct.isoformat(),
        "next_session": next_session,
        "minutes_until_next": mins_until,
        "day_of_week": now_ct.strftime("%A"),
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


@app.post("/notifications/morning-briefing")
async def send_morning_briefing():
    """Manually trigger the WhatsApp morning briefing."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        from notifications.whatsapp import format_morning_briefing, send_whatsapp_message

        # Gather open positions
        positions = paper_tracker.get_open_positions() if paper_tracker else []

        # Get yesterday's P&L
        from datetime import datetime, timedelta, timezone
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        daily_pnl_rows = db_manager.get_daily_pnl(days=2)
        yesterday_pnl = next(
            (r for r in daily_pnl_rows if r.get("date", "").startswith(yesterday[:10])),
            None,
        )

        # Circuit breakers
        cb_status = safety_layer.check_circuit_breakers() if safety_layer else {}

        # Session info
        import pytz
        ct = pytz.timezone("America/Chicago")
        now_ct = datetime.now(ct)
        session_info = {"day_of_week": now_ct.strftime("%A")}

        msg = format_morning_briefing(
            session_info=session_info,
            positions=positions,
            daily_pnl=yesterday_pnl,
            circuit_breakers=cb_status,
        )

        success = await send_whatsapp_message(msg)
        return {"sent": success, "message_preview": msg[:200]}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


@app.get("/backtest/walk-forward-results")
async def get_walk_forward_results():
    """Return all walk-forward JSON result files from backtest/results/."""
    import json
    from pathlib import Path

    results_dir = Path(__file__).parent / "backtest" / "results"
    if not results_dir.exists():
        return {"results": []}

    wf_files = sorted(results_dir.glob("WF_*.json"))
    results = []
    for f in wf_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            summary = data.get("summary", {})
            results.append({
                "filename": f.name,
                "symbol": data.get("symbol", "?"),
                "interval": data.get("interval", "?"),
                "generated": data.get("generated", ""),
                "wfe": summary.get("wfe", 0),
                "avg_oos_return": summary.get("avg_oos_return", 0),
                "avg_oos_sharpe": summary.get("avg_oos_sharpe", 0),
                "avg_oos_pf": summary.get("avg_oos_profit_factor", 0),
                "windows_profitable": summary.get("windows_profitable", 0),
                "total_windows": summary.get("total_windows", 0),
                "mode": "adaptive" if "adaptive" in f.name.lower() else "static",
            })
        except Exception as e:
            logger.warning(f"Failed to parse WF file {f.name}: {e}")

    return {"results": results}


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


@app.post("/backtest/regime-analysis")
async def run_regime_analysis(request: BacktestRequest):
    """
    Analyze backtest results broken down by market regime.

    Takes a symbol, date range, and interval; runs the backtest and then
    performs regime-specific performance analysis across TRENDING_UP/DOWN,
    RANGE_BOUND, HIGH_VOLATILITY, etc.

    Returns:
      - regime_metrics: Dict mapping regime -> {trade_count, win_rate, pf, sharpe, etc}
      - edge_sources: Which regimes are profitable, distribution of trades
    """
    from concurrent.futures import ThreadPoolExecutor
    import json

    def _run():
        from backtest import Backtester, BacktestDataLoader, generate_signals
        from backtest.regime_analysis import RegimeAnalyzer
        from pathlib import Path

        # Run the backtest first
        loader = BacktestDataLoader()
        df = loader.load(request.symbol, request.start, request.end, request.interval)
        if df is None or df.empty:
            raise ValueError(f"No data for {request.symbol}")

        df = generate_signals(df, symbol=request.symbol)
        multiplier = loader.get_multiplier(request.symbol)
        backtester = Backtester(
            initial_capital=request.capital,
            risk_per_trade=request.risk_per_trade,
        )
        result = backtester.run(df, request.symbol, multiplier)

        # Get trades with regime data
        trades = [t.to_dict() for t in result.trades]

        # Perform regime analysis
        analyzer = RegimeAnalyzer(df=None)
        analyzer.analyze_trades(trades, regime_column='regime')

        # Save regime analysis results
        results_dir = Path(__file__).parent / "backtest" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)

        regime_filename = f"{request.symbol}_{request.interval}_regime_analysis.json"
        regime_path = results_dir / regime_filename

        analysis_data = {
            'symbol': request.symbol,
            'interval': request.interval,
            'start': request.start,
            'end': request.end,
            'analysis_date': datetime.now(timezone.utc).isoformat(),
            'regime_metrics': analyzer.to_dict(),
            'edge_sources': analyzer.identify_edge_sources(),
            'backtest_summary': {
                'total_trades': result.total_trades,
                'win_rate': result.win_rate,
                'profit_factor': result.profit_factor,
                'total_return_pct': result.total_return_pct,
                'sharpe_ratio': result.sharpe_ratio,
            }
        }

        with open(regime_path, 'w') as f:
            json.dump(analysis_data, f, indent=2)

        return {
            'regime_metrics': analyzer.to_dict(),
            'edge_sources': analyzer.identify_edge_sources(),
            'backtest_summary': analysis_data['backtest_summary'],
            'results_file': regime_filename,
        }

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, _run)
    return result


# ── Walk-Forward Validation ─────────────────────────────────────────────

class WalkForwardRequest(BaseModel):
    symbol: str = "SPY"
    interval: str = "1h"
    start: str = "2024-06-01"
    end: str = "2026-03-27"
    train_months: int = 6
    test_months: int = 3
    step_months: int = 3
    capital: float = 100_000.0
    full_grid: bool = False
    adaptive_regime: bool = False
    volume_filter: bool = False
    mtf_filter: bool = False


@app.post("/backtest/walk-forward")
async def run_walk_forward(request: WalkForwardRequest):
    """
    Execute walk-forward validation to detect parameter overfitting.

    Rolls through historical data, optimizing on training windows and validating
    on out-of-sample test windows. Returns Walk-Forward Efficiency (WFE) and
    detailed per-window metrics.

    Args:
        symbol: Trading symbol (e.g., "SPY", "MES", "MCL")
        interval: Timeframe ("1d", "1h", "15m", etc.)
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
        train_months: Training window size (default: 6)
        test_months: Test window size (default: 3)
        step_months: Step size between windows (default: 3)
        capital: Initial capital for backtests (default: 100,000)
        full_grid: Use full param grid (slower) vs fast grid
        adaptive_regime: Use regime-adaptive STC thresholds
        volume_filter: Block entries on below-average volume
        mtf_filter: Apply 4h MTF confirmation filter

    Returns:
        Detailed walk-forward results with:
        - WFE (Walk-Forward Efficiency): OOS Sharpe / IS Sharpe
          * > 0.70 = Excellent (minimal overfitting)
          * 0.50-0.70 = Good (acceptable degradation)
          * 0.30-0.50 = Marginal (significant overfitting)
          * < 0.30 = Poor (likely unusable)
        - Per-window IS and OOS metrics
        - Parameter stability across windows
        - Results file path
    """
    def _run():
        try:
            from backtest.walk_forward import WalkForwardValidator, save_results
            from backtest.data_loader import BacktestDataLoader
            import json

            # Load data
            loader = BacktestDataLoader()
            logger.info(f"[WF] Loading {request.symbol} ({request.interval}) from {request.start} to {request.end}...")
            df = loader.load(request.symbol, request.start, request.end, request.interval)

            if df is None or df.empty:
                return {
                    "error": f"No data returned for {request.symbol}",
                    "symbol": request.symbol,
                    "interval": request.interval,
                }

            logger.info(f"[WF] Loaded {len(df)} bars. Running walk-forward validation...")

            # Run walk-forward validation
            validator = WalkForwardValidator(
                train_months=request.train_months,
                test_months=request.test_months,
                step_months=request.step_months,
            )

            multiplier = loader.get_multiplier(request.symbol)
            result = validator.run(
                df,
                request.symbol,
                multiplier=multiplier,
                capital=request.capital,
                fast=not request.full_grid,
                adaptive_regime=request.adaptive_regime,
                volume_filter=request.volume_filter,
                mtf_filter=request.mtf_filter,
            )

            # Save results to JSON
            results_path = save_results(
                result,
                request.symbol,
                request.interval,
                adaptive_regime=request.adaptive_regime,
                volume_filter=request.volume_filter,
                mtf_filter=request.mtf_filter,
            )

            logger.info(f"[WF] Walk-forward validation complete. Results saved to {results_path}")

            # Return summary + file path
            return {
                "success": True,
                "symbol": request.symbol,
                "interval": request.interval,
                "windows_count": result["summary"]["total_windows"],
                "summary": result["summary"],
                "results_file": str(results_path),
                "windows": [
                    {
                        "window": w["window"],
                        "train_period": w["train_period"],
                        "test_period": w["test_period"],
                        "best_params": w["best_params"],
                        "is_metrics": {
                            "trades": w["is_result"].total_trades,
                            "win_rate": round(w["is_result"].win_rate, 4),
                            "profit_factor": round(min(w["is_result"].profit_factor, 999.0), 3),
                            "sharpe": round(w["is_result"].sharpe_ratio, 3),
                            "return_pct": round(w["is_result"].total_return_pct * 100, 2),
                        },
                        "oos_metrics": {
                            "trades": w["oos_result"].total_trades,
                            "win_rate": round(w["oos_result"].win_rate, 4),
                            "profit_factor": round(min(w["oos_result"].profit_factor, 999.0), 3),
                            "sharpe": round(w["oos_result"].sharpe_ratio, 3),
                            "return_pct": round(w["oos_result"].total_return_pct * 100, 2),
                        },
                    }
                    for w in result["windows"]
                ],
            }

        except Exception as exc:
            logger.error(f"[WF] Walk-forward validation failed: {exc}", exc_info=True)
            return {
                "error": str(exc),
                "symbol": request.symbol,
                "interval": request.interval,
            }

    from concurrent.futures import ThreadPoolExecutor
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
                # Alert would be sent here with trade details
                logger.info(f"[WHATSAPP] Would send alert for trade: {trade}")
        except Exception as exc:
            logger.warning(f"[WHATSAPP] Alert failed: {exc}")

        return metrics

    except Exception as exc:
        logger.error(f"[PAPER-MGC-LOG] Failed to log trade: {exc}", exc_info=True)
        raise HTTPException(500, f"Failed to log trade: {exc}")


# ── Market Regime Status ──────────────────────────────────────────────────

@app.get("/analytics/regime")
async def get_analytics_regime():
    """
    Current 5-layer market regime assessment.

    Returns the composite regime (BULLISH / BEARISH / NEUTRAL / UNKNOWN),
    a confidence score, and per-layer detail for:
      vix       -- VIX overlay (stub until Phase 3 data feed)
      mtf       -- Multi-timeframe alignment (stub)
      stc       -- Schaff Trend Cycle signal (from last pipeline run if available)
      ema_trend -- EMA trend direction (from last pipeline run if available)
      volume    -- Volume vs average (stub)

    When the pipeline has been run at least once, signal values from the
    most recent decision log entry are surfaced. Otherwise all layers
    report stub status.
    """
    now = datetime.now(timezone.utc)

    # VIX layer -- read from VIXOverlay stub
    vix_value: float | None = None
    vix_classification = "UNKNOWN"
    try:
        from analytics.vix_overlay import VIXOverlay
        overlay = VIXOverlay()
        vix_state = overlay.get_current_state()
        vix_value = vix_state.vix_value
        vix_classification = vix_state.regime  # CALM / NORMAL / CAUTION / ELEVATED / EXTREME
    except Exception:
        pass

    # STC / EMA trend -- pull from most recent decision log entries
    stc_signal = "UNKNOWN"
    ema_direction = "UNKNOWN"
    try:
        for entry in reversed(_decision_log):
            if "stc_signal" in entry:
                stc_signal = str(entry["stc_signal"]).upper()
                break
        for entry in reversed(_decision_log):
            if "ema_trend" in entry:
                ema_direction = str(entry["ema_trend"]).upper()
                break
    except Exception:
        pass

    # Derive composite regime from available signals
    bullish_signals = 0
    bearish_signals = 0
    total_active = 0

    if vix_classification in ("CALM", "NORMAL"):
        bullish_signals += 1
        total_active += 1
    elif vix_classification in ("ELEVATED", "EXTREME"):
        bearish_signals += 1
        total_active += 1
    elif vix_classification == "CAUTION":
        total_active += 1  # neutral vote

    if stc_signal in ("BULLISH", "BUY", "LONG", "POSITIVE", "ABOVE_SIGNAL"):
        bullish_signals += 1
        total_active += 1
    elif stc_signal in ("BEARISH", "SELL", "SHORT", "NEGATIVE", "BELOW_SIGNAL"):
        bearish_signals += 1
        total_active += 1

    if ema_direction in ("UPTREND", "UP", "BULLISH", "LONG"):
        bullish_signals += 1
        total_active += 1
    elif ema_direction in ("DOWNTREND", "DOWN", "BEARISH", "SHORT"):
        bearish_signals += 1
        total_active += 1

    if total_active == 0:
        composite_regime = "UNKNOWN"
        confidence = 0.0
        trade_filter = "unknown"
    elif bullish_signals > bearish_signals:
        composite_regime = "BULLISH"
        confidence = round(bullish_signals / total_active, 2)
        trade_filter = "pass"
    elif bearish_signals > bullish_signals:
        composite_regime = "BEARISH"
        confidence = round(bearish_signals / total_active, 2)
        trade_filter = "block"
    else:
        composite_regime = "NEUTRAL"
        confidence = 0.5
        trade_filter = "unknown"

    # VIX EXTREME always blocks regardless of other signals
    if vix_classification == "EXTREME":
        composite_regime = "BEARISH"
        confidence = 1.0
        trade_filter = "block"

    return {
        "timestamp": now.isoformat(),
        "regime": composite_regime,
        "confidence": confidence,
        "layers": {
            "vix": {
                "status": "stub",
                "value": vix_value,
                "classification": vix_classification,
            },
            "mtf": {
                "status": "stub",
                "timeframes_aligned": None,
            },
            "stc": {
                "status": "stub",
                "value": None,
                "signal": stc_signal,
            },
            "ema_trend": {
                "status": "stub",
                "direction": ema_direction,
            },
            "volume": {
                "status": "stub",
                "above_average": None,
            },
        },
        "note": "Regime filter stubs active -- live data feeds needed for full activation",
        "trade_filter": trade_filter,
    }