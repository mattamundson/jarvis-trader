"""
JARVIS TRADER — Main Server
============================
FastAPI backend for the trading engine.
Runs on port 8010 (separate from GMS JARVIS on 8009).

Start with: .venv\\Scripts\\python -m uvicorn main:app --port 8010
(No --reload — IB Gateway / duplicate client-id issues; use restart_engine.ps1 after code changes.)
"""

import asyncio
import json
import logging
import logging.handlers
import os
import signal
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded

from agents.bear_researcher import BearResearcherAgent
from agents.bull_researcher import BullResearcherAgent
from agents.debate import DebateOrchestrator
from agents.fund_manager import FundManagerAgent
from agents.fundamental_analyst import FundamentalistAgent
from agents.news_analyst import NewsAnalystAgent
from agents.pipeline import TradingPipeline
from agents.risk_manager import RiskManagerAgent
from agents.social_analyst import SocialAnalystAgent
from agents.corey_auction_analyst import CoreyAuctionAnalystAgent
from agents.technical_analyst import TechnicalAnalystAgent
from agents.thinkscript_generator import ThinkScriptGeneratorAgent
from agents.trader import TraderAgent
from schemas.thinkscript_registry import ScriptRegistry, ScriptWithDocs
from utils.thinkscript_registry_loader import load_registry, read_doc
from api.models import (
    BarsResponse,
    DailyPnLResponse,
    DecisionHistoryResponse,
    DrawdownResponse,
    NewsSentimentResponse,
    PaperPerformanceResponse,
    PaperPositionsResponse,
    PaperTradeResponse,
    PendingSignalsResponse,
    PortfolioResponse,
    RedditSentimentResponse,
    SafetyConfigResponse,
    StatsSummaryResponse,
    TechnicalAnalysisResponse,
    TradeHistoryResponse,
)
from config import settings
from data.market_data import MarketDataManager
from database.schema import DatabaseManager, init_db
from execution.ib_gateway_connector import IBGatewayConnector
from execution.ib_order_manager import IBOrderManager
from execution.order_router import OrderRouter
from execution.schwab_connector import SchwabConnector
from llm.client import JarvisLLMClient
from llm.cost_tracker import CostTracker
from middleware.api_key_middleware import APIKeyMiddleware
from middleware.exception_handler import GlobalExceptionHandler
from middleware.rate_limit import get_limiter, rate_limit_exception_handler
from portfolio.tracker import PortfolioTracker
from risk.loss_tracker import ConsecutiveLossTracker
from risk.pnl_monitor import PnLMonitor
from risk.safety_layer import SafetyLayer
from routers.analytics_router import router as analytics_router
from routers.analytics_router import set_db_manager as set_analytics_db
from routers.analytics_router import set_data_manager as set_analytics_data_manager
from routers.backtest_router import router as backtest_router
from routers.backtest_router import inject_dependencies as inject_backtest_deps
from routers.discord_router import inject_data_manager as inject_discord_data_manager
from routers.discord_router import router as discord_router
from routers.experiments_router import router as experiments_router
from routers.flags_router import router as flags_router
from routers.flags_router import set_flags as set_flags_router
from routers.health_router import inject_dependencies as inject_health_router_deps
from routers.health_router import router as health_router
from routers.journal_router import router as journal_router
from routers.journal_router import set_db_manager as set_journal_db
from routers.jarvis_router import router as jarvis_router
from routers.kairos_router import router as kairos_router
from routers.learning_router import router as learning_router
from routers.events_router import router as events_router
from routers.market_router import router as market_router
from routers.phase3_readiness_router import inject_dependencies as inject_phase3_readiness_deps
from routers.phase3_readiness_router import router as phase3_readiness_router
from routers.portfolio_router import inject_dependencies as inject_portfolio_deps
from routers.portfolio_router import router as portfolio_router
from routers.profiling_router import router as profiling_router
from routers.profiling_router import set_profiler_instance
from routers.safety_router import inject_dependencies as inject_safety_router_deps
from routers.safety_router import router as safety_router
from routers.schwab_router import router as schwab_router
from routers.schwab_router import set_schwab_connector
from routers.strategies_router import router as strategies_router
from routers.validation_router import router as validation_router
from routers.validation_router import set_validation_alert_manager
from routers.paper_validation_router import router as paper_validation_router
from routers.proactive_validation_router import router as proactive_validation_router
from routers.webhook_router import get_recent_webhooks
from routers.webhook_router import router as webhook_router
from routers.instruments_router import router as instruments_router
from routers.brokers_router import router as brokers_router
from routers.brokers_router import inject_dependencies as inject_brokers_deps
from routers.options_router import router as options_router
from routers.approval_router import router as approval_router
from routers.approval_router import inject_dependencies as inject_approval_deps
from routers.pipeline_router import router as pipeline_router
from routers.pipeline_router import inject_dependencies as inject_pipeline_deps
from routers.messaging_router import router as messaging_router
from routers.messaging_router import inject_dependencies as inject_messaging_deps
from routers.observability_router import router as observability_router
from routers.strategy_c_router import router as strategy_c_router
from routers.system2_router import router as system2_router
from routers.eod_router import router as eod_router
from routers.research_journal_router import router as research_journal_router
from routers.scanner_router import router as scanner_router
from routers.scanner_router import inject_dependencies as inject_scanner_deps
from routers.tradingview_router import router as tradingview_router
from routers.scheduler_router import router as scheduler_router
from routers.scheduler_router import inject_scheduler as inject_scheduler_router_scheduler
from routers.trades_router import router as trades_router
from routers.wfe_router import router as wfe_router
from routers.discovery_router import router as discovery_router
from routers.hidden_pivots_router import router as hidden_pivots_router
from routers.hidden_pivots_router import inject_dependencies as inject_hp_deps
from routers.decisions_router import router as decisions_router
from routers.decisions_router import set_db_manager as set_decisions_db
from routers.cache_router import router as cache_router
from routers.analysis_router import router as analysis_router
from routers.analysis_router import inject_dependencies as inject_analysis_deps
from routers.sentiment_router import router as sentiment_router
from routers.sentiment_router import inject_dependencies as inject_sentiment_deps
from routers.watchlist_router import router as watchlist_router
from routers.watchlist_router import inject_dependencies as inject_watchlist_deps
from routers.macro_router import router as macro_router
from routers.macro_router import inject_dependencies as inject_macro_deps
from routers.settings_router import router as settings_router
from routers.settings_router import inject_dependencies as inject_settings_deps
from routers.reports_router import router as reports_router
from routers.reports_router import inject_dependencies as inject_reports_deps
from routers.prices_router import router as prices_router
from routers.prices_router import inject_dependencies as inject_prices_deps
from data.price_cache import PriceCache
from routers.thinkscript_router import router as thinkscript_router
from routers.strategy_lab_router import router as strategy_lab_router
from routers.notifications_router import router as notifications_router
from routers.alerts_router import router as alerts_router
from routers.websocket_router import router as websocket_router
from routers.thinkscript_router import inject_dependencies as inject_thinkscript_deps
from schedulers.eod_scheduler import EODScheduler
from notifications.validation_alerts import ValidationAlertManager
from notifications.morning_brief import inject_morning_brief_deps
from websocket.events import set_ws_manager
from websocket.manager import WebSocketManager

try:
    from agents.sdk_pipeline import SDKTradingPipeline
except ModuleNotFoundError as exc:
    if exc.name != "claude_agent_sdk":
        raise
    SDKTradingPipeline = None

# ── Logging (initialized in lifespan) ────────────────────────────────────
logger = logging.getLogger("jarvis_trader")


class JSONFormatter(logging.Formatter):
    """Custom JSON-structured log formatter"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "module": record.module,
            "funcName": record.funcName,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure structured logging with file rotation and console output.
    Called during lifespan startup BEFORE any other module initialization.
    """
    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    # Parse log level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear any existing handlers
    root_logger.handlers.clear()

    # JSON formatter for structured logs
    json_formatter = JSONFormatter()

    # Console handler (for Docker/stdout)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root_logger.addHandler(console_handler)

    # File handler with rotation (10MB files, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        filename="logs/jarvis.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(json_formatter)
    root_logger.addHandler(file_handler)


# ── Global State ─────────────────────────────────────────────────────────
data_manager: MarketDataManager | None = None
safety_layer: SafetyLayer | None = None
technical_analyst: TechnicalAnalystAgent | None = None
trading_pipeline: TradingPipeline | None = None
sdk_pipeline: "SDKTradingPipeline | None" = None
scheduler: AsyncIOScheduler | None = None
paper_tracker: PortfolioTracker | None = None
db_manager: DatabaseManager | None = None
pnl_monitor: PnLMonitor | None = None
eod_scheduler: EODScheduler | None = None
order_manager: IBOrderManager | None = None
ib_paper_connector: IBGatewayConnector | None = None
schwab_connector: SchwabConnector | None = None
order_router: OrderRouter = OrderRouter()
ws_manager: WebSocketManager | None = None
cost_tracker: "CostTracker | None" = None
loss_tracker: "ConsecutiveLossTracker | None" = None
validation_alert_manager: "ValidationAlertManager | None" = None


def _log_pipeline_whatsapp_to_alert_log(
    symbol: str,
    message: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Persist pipeline WhatsApp outcomes (sent, failed, suppressed) for audit."""
    if db_manager is None:
        return
    try:
        db_manager.insert_alert_log(
            alert_type="pipeline_signal",
            message=message,
            channel="whatsapp",
            symbol=symbol,
            status=status,
            error=error,
        )
    except Exception as exc:
        logger.warning("alert_log pipeline_signal insert failed (non-fatal): %s", exc)


async def _deliver_pipeline_whatsapp_if_eligible(
    symbol: str,
    action: str,
    qty: int,
    price_info,
    reasoning: str,
    confidence: float,
) -> Tuple[bool, Optional[str]]:
    """
    Send Twilio WhatsApp for a non-HOLD pipeline result when cooldown allows.

    Returns (delivered_to_twilio, suppressed_reason). ``suppressed_reason`` is None
    on successful send; ``send_failed`` when Twilio returns false; otherwise a
    short code for API responses (manual scan).
    """
    from notifications.pipeline_alert_cooldown import (
        get_last_pipeline_alert_sent,
        mark_pipeline_alert_sent,
        pipeline_alert_decision,
    )
    from notifications.whatsapp import get_notifier

    notifier = get_notifier()
    now = datetime.now()
    last_sent = get_last_pipeline_alert_sent(symbol)
    decision = pipeline_alert_decision(
        last_sent=last_sent,
        now=now,
        cooldown_minutes=settings.ALERT_COOLDOWN_MINUTES,
        notifier_enabled=notifier.enabled,
    )
    price_str = f" @ {price_info:.2f}" if price_info else ""
    pct = int(confidence * 100)
    short_reason = (reasoning[:100] + "...") if len(reasoning) > 100 else reasoning
    msg = (
        f"JARVIS: {symbol} -> {action.upper()} {qty}{price_str}\n"
        f"Confidence: {pct}%\n"
        f"Reason: {short_reason}"
    )

    if decision == "send":
        sent = await notifier.send(msg)
        if sent:
            mark_pipeline_alert_sent(symbol, now)
            _log_pipeline_whatsapp_to_alert_log(symbol, msg, "sent")
            logger.info("WhatsApp alert sent for %s (%s)", symbol, action.upper())
            return True, None
        _log_pipeline_whatsapp_to_alert_log(
            symbol, msg, "failed", error="twilio_send_returned_false"
        )
        logger.warning("WhatsApp alert failed for %s", symbol)
        return False, "send_failed"

    if decision == "suppressed_cooldown":
        tail = last_sent.strftime("%H:%M") if last_sent else "unknown"
        logger.info(
            "WhatsApp alert for %s suppressed — cooldown active (last sent %s)",
            symbol,
            tail,
        )
        _log_pipeline_whatsapp_to_alert_log(
            symbol,
            msg,
            "suppressed_cooldown",
            error=(f"last_sent={last_sent.isoformat()}" if last_sent else "last_sent=n/a"),
        )
        return False, f"cooldown_active_since_{tail}"

    logger.info("WhatsApp alert for %s suppressed — WhatsApp not configured", symbol)
    _log_pipeline_whatsapp_to_alert_log(
        symbol, msg, "suppressed", error="whatsapp_not_configured"
    )
    return False, "whatsapp_not_configured"


# 5-minute macro snapshot cache (keyed by "snapshot", stores flattened dict + "_ts")
_macro_cache: Dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and teardown on startup/shutdown"""
    global \
        data_manager, \
        safety_layer, \
        technical_analyst, \
        trading_pipeline, \
        scheduler, \
        paper_tracker, \
        db_manager, \
        pnl_monitor, \
        eod_scheduler, \
        order_manager, \
        ib_paper_connector, \
        schwab_connector, \
        order_router, \
        ws_manager, \
        cost_tracker, \
        loss_tracker, \
        validation_alert_manager, \
        sdk_pipeline

    # Setup structured logging with file rotation FIRST, before any other initialization
    setup_logging(log_level=settings.LOG_LEVEL)

    logger.info("🤖 JARVIS TRADER starting up...")
    logger.info(
        f"   Live trading: {'ENABLED ⚠️' if settings.LIVE_TRADING_ENABLED else 'DISABLED (paper mode)'}"
    )
    logger.info(
        f"   IBKR port:   {settings.IBKR_PORT} ({'live' if settings.IBKR_PORT == 4001 else 'paper'})"
    )

    # Run startup validation checks BEFORE scheduler setup
    from startup_checks import run_startup_checks

    check_results = run_startup_checks(settings)

    # Fail boot if any CRITICAL checks failed
    critical_failures = [r for r in check_results if r.status == "fail"]
    if critical_failures:
        logger.error(
            f"🛑 {len(critical_failures)} critical startup check(s) failed. Engine shutdown."
        )
        raise SystemExit(1)

    logger.info("✅ All startup checks passed")

    # Initialize SQLite database
    os.makedirs("data", exist_ok=True)
    db_manager = init_db(db_path="data/jarvis_trader.db")
    db_manager.initialize()
    set_journal_db(db_manager)
    set_analytics_db(db_manager)
    set_decisions_db(db_manager)
    logger.info("✅ SQLite database initialized at data/jarvis_trader.db")

    # Feature Flags — two-layer flag system (config defaults + runtime SQLite overrides)
    from flags import FeatureFlags, set_flags_instance

    feature_flags = FeatureFlags(config=settings, db=db_manager)
    set_flags_instance(feature_flags)
    set_flags_router(feature_flags)
    logger.info("✅ Feature Flags system initialised")

    # Hook system — register default logging/db hooks
    from hooks.registry import get_hook_registry
    from hooks.trading_hooks import register_default_hooks

    _hook_registry = get_hook_registry()
    register_default_hooks(_hook_registry)
    logger.info("✅ Trading hook registry initialised")

    # Paper trading tracker — initialise before safety layer so it is always available
    paper_tracker = PortfolioTracker(db_manager=db_manager)
    # US-2004 / Bug B9: rebuild in-memory open-position state from SQLite so that
    # any crash-induced JSONL/in-memory divergence is corrected before trading resumes.
    paper_tracker.reload_open_positions_from_db()
    # Also sync closed trades from SQLite to ensure P&L calculations match DB on restart
    paper_tracker.initialize_closed_trades_from_db()
    logger.info("✅ Paper portfolio tracker ready (open + closed trades rebuilt from SQLite)")

    # P&L Monitor — wires SQLite + IB Gateway data to circuit breakers
    # IB gateway is not available yet at this point; it is injected after data_manager is ready
    pnl_monitor = PnLMonitor(
        db_manager=db_manager,
        ib_gateway=None,  # updated below once data_manager is initialised
        paper_tracker=paper_tracker,
        starting_balance=settings.INITIAL_CAPITAL,
    )
    logger.info("✅ PnL Monitor initialised (SQLite + paper tracker sources active)")

    # Safety layer — always first; PnLMonitor feeds circuit breakers with live data.
    # Both db_path (for kill-switch state via raw sqlite3) and db_manager (for typed
    # upsert_pnl_snapshot calls) must be passed — they're separate code paths inside
    # SafetyLayer. Omitting db_manager silently disables pnl_snapshots writes.
    safety_layer = SafetyLayer(
        settings,
        pnl_monitor=pnl_monitor,
        db_path=str(db_manager._db_path),
        db_manager=db_manager,
    )

    # Paper IB connector — JSON audit + optional PortfolioTracker mirror; wired into SafetyLayer
    ib_paper_connector = None
    if settings.PAPER_TRADING:
        ib_paper_connector = IBGatewayConnector(
            settings,
            safety_layer,
            portfolio_tracker=paper_tracker,
        )
        _paper_ib_ok = await ib_paper_connector.connect()
        if _paper_ib_ok:
            safety_layer.attach_ib_gateway(ib_paper_connector)
            logger.info(
                "✅ IBGatewayConnector (paper) connected — SafetyLayer routes fills; "
                "tracker mirror active when configured"
            )
        else:
            logger.warning(
                "⚠️ IBGatewayConnector.connect() returned False — paper orders stay dry-run"
            )

    order_manager = IBOrderManager(
        safety_layer=safety_layer,
        ib_gateway=ib_paper_connector,
        portfolio_tracker=paper_tracker,
    )
    logger.info("✅ IBOrderManager initialized")

    # Wire IBKR into the order router now that it is available
    order_router.attach_ibkr(ib_paper_connector)

    # Schwab connector — initialized only when credentials are present.
    # SCHWAB_READY=False guard inside SchwabConnector prevents accidental activation.
    schwab_connector = None
    if settings.SCHWAB_APP_KEY and settings.SCHWAB_APP_SECRET:
        try:
            schwab_connector = SchwabConnector(settings, safety_layer)
            _schwab_ok = await schwab_connector.initialize()
            if _schwab_ok:
                order_router.attach_schwab(schwab_connector)
                logger.info("✅ SchwabConnector initialized and wired into OrderRouter")
            else:
                logger.warning(
                    "SchwabConnector.initialize() returned False — "
                    "equity/options orders via Schwab unavailable"
                )
        except Exception as _schwab_err:
            logger.warning(
                "SchwabConnector init failed (non-fatal, equities unavailable): %s",
                _schwab_err,
            )
            schwab_connector = None
    else:
        logger.info("Schwab credentials not set — SchwabConnector skipped (Phase 3 feature)")

    set_schwab_connector(schwab_connector)
    logger.info(
        "✅ OrderRouter ready — IBKR: %s | Schwab: %s",
        "connected" if order_router.ibkr else "not wired",
        "connected" if (schwab_connector and schwab_connector.is_connected) else "not connected",
    )

    # Market data connections
    data_manager = MarketDataManager(settings)
    await data_manager.initialize()
    set_analytics_data_manager(data_manager)

    # Now that data_manager is ready, inject the IB gateway into PnLMonitor
    # so the circuit breakers can read live account data from IBKR when connected.
    if pnl_monitor is not None and data_manager.ibkr is not None:
        pnl_monitor._ib = data_manager.ibkr
        logger.info("✅ PnL Monitor: IB Gateway wired (live account data source active)")

    # Wire Schwab into MarketDataManager as Tier 2 price source (equities/options quotes)
    if schwab_connector is not None and schwab_connector.is_connected:
        data_manager.inject_schwab(schwab_connector)
        logger.info("✅ Schwab wired into MarketDataManager as Tier 2 price source")

    # Now that data_manager is ready, inject the IB gateway into PnLMonitor
    # so the circuit breakers can read live account data from IBKR when connected.
    if pnl_monitor is not None and data_manager.ibkr is not None:
        pnl_monitor._ib = data_manager.ibkr
        logger.info("✅ PnL Monitor: IB Gateway wired (live account data source active)")

    # Agents (need LLM client)
    if settings.ANTHROPIC_API_KEY:
        llm_client = JarvisLLMClient(api_key=settings.ANTHROPIC_API_KEY)

        # Startup assertion — fail loud if the client is missing required interface
        _required_methods = ["call"]
        _missing = [m for m in _required_methods if not callable(getattr(llm_client, m, None))]
        if _missing:
            raise RuntimeError(
                f"LLM client {type(llm_client).__name__} is missing required methods: {_missing}. "
                "Check llm/client.py — agents will silently HOLD without this."
            )
        logger.info(f"✅ LLM client validated: {type(llm_client).__name__} has {_required_methods}")

        # Stage 1: Analysts
        technical_analyst = TechnicalAnalystAgent(llm_client, data_manager)

        # Wire Brave Search into news analyst if key is configured
        _brave_client = None
        if getattr(settings, "BRAVE_API_KEY", None):
            from data.brave_search import BraveSearchClient
            _brave_client = BraveSearchClient(api_key=settings.BRAVE_API_KEY)
            logger.info("✅ Brave Search wired into news analyst")
        else:
            logger.warning("BRAVE_API_KEY not set — news analyst running without live web search")

        news_agent = NewsAnalystAgent(llm_client, data_manager, brave_client=_brave_client)
        social_agent = SocialAnalystAgent(llm_client)
        fundamental_agent = FundamentalistAgent(llm_client, data_manager)
        corey_agent = CoreyAuctionAnalystAgent(llm_client=llm_client)

        # Stage 2: Debate
        bull_agent = BullResearcherAgent(api_key=settings.ANTHROPIC_API_KEY)
        bear_agent = BearResearcherAgent(api_key=settings.ANTHROPIC_API_KEY)
        debate_agent = DebateOrchestrator()

        # Stages 3-5: Trader → Risk → Fund
        trader_agent = TraderAgent(llm_client, db_manager=db_manager)
        risk_agent = RiskManagerAgent(llm_client)
        fund_agent = FundManagerAgent(llm_client)

        logger.info("✅ All 11 trading agents initialized (incl. CoreyAuctionAnalyst)")

        # Trading Pipeline — all agents wired
        trading_pipeline = TradingPipeline(
            agents={
                "technical": technical_analyst,
                "news": news_agent,
                "social": social_agent,
                "fundamental": fundamental_agent,
                "corey": corey_agent,
                "bull": bull_agent,
                "bear": bear_agent,
                "debate": debate_agent,
                "trader": trader_agent,
                "risk_manager": risk_agent,
                "fund_manager": fund_agent,
            },
            safety_layer=safety_layer,
        )

        # Wire profiler instance into profiling_router
        if trading_pipeline.profiler:
            set_profiler_instance(trading_pipeline.profiler)
            logger.info("✅ PipelineProfiler wired into /pipeline/profiling endpoint")

        logger.info("✅ Trading Pipeline initialized — all 5 stages wired")

        # SDK Pipeline — parallel Claude Agent SDK path (/pipeline/run/sdk)
        try:
            sdk_pipeline = SDKTradingPipeline(
                data_manager=data_manager,
                api_key=getattr(settings, "API_KEY", ""),
            )
            logger.info("✅ SDK Pipeline initialized — /pipeline/run/sdk available")
        except Exception as _sdk_exc:
            logger.warning("⚠️  SDK Pipeline init failed (non-fatal): %s", _sdk_exc)
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

        # Futures + equities — sequential to avoid OOM from parallel 10-agent LLM pipelines
        symbols_to_scan = (
            [
                (sym, True)
                for sym in settings.FUTURES_WATCHLIST  # MES, MNQ, MCL
            ]
            + [
                (sym, False)
                for sym in settings.OPTIONS_WATCHLIST[:3]  # SPY, QQQ, AAPL
            ]
        )

        logger.info(f"Scheduled scan: {[s[0] for s in symbols_to_scan]}")

        async def _analyze_and_alert(symbol: str, is_futures: bool) -> None:
            import time as _time_mod

            # ── Scanner guards (added 2026-04-10) ────────────────────────
            # Guard 1: Already-open position check. Prevents duplicate trades
            # like the 2026-04-10 incident where MES shorts #108/#109/#110 were
            # created on consecutive hourly scans against identical bogus prices.
            try:
                import sqlite3 as _sqlite3

                with _sqlite3.connect(settings.SQLITE_DB_PATH) as _conn:
                    _existing = _conn.execute(
                        "SELECT id, side FROM paper_trades WHERE symbol=? AND status='open' LIMIT 1",
                        (symbol,),
                    ).fetchone()
                if _existing is not None:
                    logger.info(
                        "[Scanner guard] %s already has open position id=%s side=%s — skipping scan",
                        symbol,
                        _existing[0],
                        _existing[1],
                    )
                    return
            except Exception as _guard_exc:
                logger.warning(
                    "[Scanner guard] already-open check failed for %s: %s (allowing scan)",
                    symbol,
                    _guard_exc,
                )

            try:
                _t0 = _time_mod.monotonic()
                result = await trading_pipeline.analyze_and_decide(symbol, is_futures)

                # Guard 2: Price sanity check. Reject the decision if the
                # pipeline operated on a price outside the hard-coded "plausible
                # range" for the instrument. This is a last-line defense against
                # stale-cache contamination like the 2026-04-10 incident where
                # MES shorts were entered at $70.57 (real MES ~$6000).
                # Ranges are deliberately wide — only catch obvious absurdities.
                _PLAUSIBLE_PRICE_RANGE = {
                    "MCL": (40.0, 130.0),   # WTI crude: ~$60-100 typical
                    "MES": (3000.0, 8000.0),  # S&P 500 mini: ~$4000-7000
                    "MNQ": (10000.0, 30000.0),  # Nasdaq mini
                    "MGC": (1500.0, 5000.0),  # Gold
                    "MYM": (25000.0, 50000.0),  # Dow mini
                }
                _trade_dec_for_guard = result.get("trade_decision") or {}
                _px_candidate = (
                    _trade_dec_for_guard.get("limit_price")
                    or _trade_dec_for_guard.get("stop_price")
                    or _trade_dec_for_guard.get("entry_price")
                )
                _range = _PLAUSIBLE_PRICE_RANGE.get(symbol.upper())
                if (
                    _range is not None
                    and _px_candidate is not None
                    and result.get("final_action", "hold") not in ("hold",)
                ):
                    try:
                        _px = float(_px_candidate)
                        if _px < _range[0] or _px > _range[1]:
                            logger.error(
                                "[Scanner guard] %s price sanity FAILED: px=%.2f outside plausible range %s — "
                                "forcing HOLD. Likely stale-cache contamination.",
                                symbol,
                                _px,
                                _range,
                            )
                            # Rewrite the result to HOLD and log to decision feed, then return
                            result["final_action"] = "hold"
                            result["sanity_override"] = {
                                "price_rejected": _px,
                                "plausible_range": list(_range),
                                "reason": "price outside hardcoded plausible range — refusing to trade",
                            }
                            _log_decision(
                                symbol=symbol,
                                action="hold",
                                confidence=0.0,
                                source="scanner_guard_sanity_failed",
                                summary=f"Price sanity guard rejected px={_px:.2f} outside {_range}",
                                reasoning="Scanner guard: price outside plausible range (stale cache?)",
                                full_pipeline_data=result,
                            )
                            return
                    except (TypeError, ValueError):
                        pass
                _duration_ms = (_time_mod.monotonic() - _t0) * 1000.0
                action = result.get("final_action", "hold")

                # Extract key fields for logging and alerting
                fund_dec = result.get("fund_decision") or {}
                trade_dec = result.get("trade_decision") or {}
                confidence = fund_dec.get("final_conviction", trade_dec.get("confidence", 0.0))
                qty = result.get("final_quantity", 0)
                price_info = trade_dec.get("limit_price") or trade_dec.get("stop_price")
                reasoning = trade_dec.get("reasoning", "")

                # Always log to decision feed (in-memory + SQLite)
                _log_decision(
                    symbol=symbol,
                    action=action,
                    confidence=float(confidence),
                    source="scheduler",
                    summary=result.get("summary", ""),
                    reasoning=reasoning,
                    full_pipeline_data=result,
                )

                # Persist pipeline run to pipeline_runs for audit trail.
                if db_manager:
                    try:
                        from approval.pipeline_history import pipeline_run_record_from_result

                        _run_record = pipeline_run_record_from_result(
                            symbol=symbol,
                            result=result,
                            duration_ms=_duration_ms,
                            source="watchlist",
                        )
                        db_manager.insert_pipeline_run(_run_record)
                    except Exception as _db_exc:
                        logger.warning(
                            "[Scheduler] Failed to log pipeline_run for %s: %s", symbol, _db_exc
                        )

                if action not in ("hold",):
                    logger.info(f"{symbol}: {action.upper()} qty={qty} confidence={confidence:.0%}")
                    await _deliver_pipeline_whatsapp_if_eligible(
                        symbol=symbol,
                        action=action,
                        qty=qty,
                        price_info=price_info,
                        reasoning=reasoning,
                        confidence=float(confidence),
                    )
                else:
                    logger.debug(f"{symbol}: hold — no alert sent")

            except Exception as e:
                logger.error(f"Scheduler analysis failed for {symbol}: {e}")

        # Sequential execution — avoids OOM from 6 simultaneous 10-agent LLM pipelines
        for sym, fut in symbols_to_scan:
            await _analyze_and_alert(sym, fut)

    # Run every 30 minutes on weekdays, 9:30am-4:00pm Chicago time
    # WATCHLIST_SCAN_ENABLED added 2026-04-10 as an emergency kill switch — when False,
    # the scheduler still starts (other jobs below depend on it) but the watchlist scan
    # job is not registered, preventing contaminated-data pipeline runs from landing trades.
    if settings.ANTHROPIC_API_KEY:
        if settings.WATCHLIST_SCAN_ENABLED:
            scheduler.add_job(
                run_watchlist_analysis,
                CronTrigger(
                    day_of_week="mon-fri", hour="9-15", minute="0,30", timezone="America/Chicago"
                ),
                id="watchlist_scan",
                name="Watchlist Auto-Scan",
                max_instances=1,
                misfire_grace_time=300,
            )
            logger.info("⏰ Watchlist auto-scan registered — every 30min (9:30am-4pm CT weekdays)")
        else:
            logger.warning(
                "⛔ WATCHLIST_SCAN_ENABLED=false — hourly watchlist auto-scan is DISABLED. "
                "Re-enable in .env after data layer + scanner guards are verified."
            )
        scheduler.start()
        logger.info("⏰ Scheduler started")

    # ── Daily MGC signal scanner (runs 18:00 ET / 23:00 UTC) ────────────
    async def run_daily_mgc_signal():
        """Fetch today's MGC daily bar, run adaptive-regime signals, log pending entries."""
        import json as _json
        from pathlib import Path

        try:
            from backtest.signals import generate_signals as _gen_signals

            logger.info("[MGC-daily] Fetching MGC daily bar via data_manager...")
            gc_df = await data_manager.get_bars("MGC", lookback_days=90, timeframe="1d")
            if gc_df is None or gc_df.empty or len(gc_df) < 20:
                logger.warning("[MGC-daily] Insufficient data from data_manager — skipping")
                return

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

                pending_file = (
                    Path(__file__).parent / "backtest" / "results" / "pending_signals.json"
                )
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
                logger.info(
                    f"[MGC-daily] ENTRY_NOW logged -> {pending_file.name}: {direction} @ ~{entry_est:.2f}"
                )

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
            timezone="UTC",  # 23:00 UTC = 18:00 ET
        ),
        id="mgc_daily_signal",
        name="MGC Daily Signal Scanner",
        max_instances=1,
        misfire_grace_time=600,
    )
    # Messaging health monitor — check Ollama every 60s
    try:
        from services.messaging_health import run_health_check
        scheduler.add_job(
            run_health_check,
            "interval",
            seconds=60,
            id="messaging_health_check",
            name="Messaging Health Monitor",
            max_instances=1,
            misfire_grace_time=30,
        )
        logger.info("✅ Messaging health monitor registered (60s interval)")
    except Exception as _mhc_err:
        logger.warning("Messaging health monitor init failed (non-fatal): %s", _mhc_err)

    if not scheduler.running:
        scheduler.start()
    logger.info("⏰ MGC daily signal job registered — 18:00 ET (23:00 UTC) weekdays")

    # ── Market open scan (09:31 ET) — parallel 1h + 15m scans for MCL, MNQ ──────
    async def market_open_scan_job():
        """Trigger parallel 1h and 15m pipeline scans at market open (MCL, MNQ)."""
        if not trading_pipeline or not safety_layer:
            logger.warning("[MARKET_OPEN] Pipeline or safety layer not available")
            return

        safety = safety_layer.get_status()
        if safety.get("kill_switch_active"):
            logger.info("[MARKET_OPEN] Skipping — kill switch active")
            return

        instruments_1h = [("MCL", True), ("MNQ", True)]
        instruments_15m = [("MCL", "15m"), ("MNQ", "15m")]
        logger.info("[MARKET_OPEN] Starting parallel 1h+15m scans for MCL, MNQ")

        async def _scan_1h(symbol: str) -> None:
            import time as _time_mod

            try:
                _t0 = _time_mod.monotonic()
                result = await trading_pipeline.analyze_and_decide(symbol, True, timeframe="1h")
                _duration_ms = (_time_mod.monotonic() - _t0) * 1000.0
                action = result.get("final_action", "hold")
                logger.info(f"[MARKET_OPEN] {symbol} 1h: {action.upper()}")

                if db_manager:
                    try:
                        from approval.pipeline_history import pipeline_run_record_from_result

                        _run_record = pipeline_run_record_from_result(
                            symbol=symbol,
                            result=result,
                            duration_ms=_duration_ms,
                            source="market_open_1h",
                        )
                        db_manager.insert_pipeline_run(_run_record)
                    except Exception as _db_exc:
                        logger.warning(
                            "[MARKET_OPEN] Failed to log pipeline_run 1h for %s: %s",
                            symbol,
                            _db_exc,
                        )
            except Exception as e:
                logger.error(f"[MARKET_OPEN] 1h pipeline failed for {symbol}: {e}")

        async def _scan_15m(symbol: str) -> None:
            import time as _time_mod

            try:
                from backtest.data_loader import BacktestDataLoader
                from backtest.paper_config import FIFTEEN_MIN_CONFIGS
                from backtest.signals import compute_all_indicators, generate_signals
                from routers.scanner_router import record_signal

                _t0 = _time_mod.monotonic()
                loader = BacktestDataLoader()
                config = FIFTEEN_MIN_CONFIGS.get(symbol)
                if not config or not config.get("enabled"):
                    logger.info(f"[MARKET_OPEN] {symbol} 15m not enabled, skipping")
                    return

                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                df = loader.load(symbol=symbol, start=start_date, end=end_date, interval="15m")
                if df is None or df.empty:
                    logger.warning(f"[MARKET_OPEN] No 15m data for {symbol}")
                    return

                df = df.tail(50).reset_index(drop=True)
                df = compute_all_indicators(df)
                stc = config.get("stc_params", {})
                df = generate_signals(
                    df,
                    regime_filter=config.get("regime_filter", True),
                    stc_oversold=stc.get("stc_os"),
                    stc_overbought=stc.get("stc_ob"),
                    symbol=symbol,
                    adaptive_regime=config.get("adaptive_regime", False),
                    volume_filter=config.get("volume_filter", False),
                )
                entry_rows = df[df["entry_signal"] == "ENTRY_NOW"]
                if not entry_rows.empty:
                    latest = entry_rows.iloc[-1]
                    record_signal(
                        symbol=symbol,
                        timeframe="15m",
                        entry_signal="ENTRY_NOW",
                        bias=latest.get("bias"),
                        regime=latest.get("regime"),
                        composite_score=None,
                        position_size_multiplier=0.5,
                    )
                    _duration_ms = (_time_mod.monotonic() - _t0) * 1000.0
                    logger.info(
                        f"[MARKET_OPEN] {symbol} 15m ENTRY_NOW — "
                        f"regime={latest.get('regime')}, bias={latest.get('bias')} "
                        f"({_duration_ms:.0f}ms)"
                    )
                else:
                    _duration_ms = (_time_mod.monotonic() - _t0) * 1000.0
                    logger.info(f"[MARKET_OPEN] {symbol} 15m: no signal ({_duration_ms:.0f}ms)")
            except Exception as e:
                logger.error(f"[MARKET_OPEN] 15m scan failed for {symbol}: {e}")

        tasks = [_scan_1h(sym) for sym, _ in instruments_1h] + [
            _scan_15m(sym) for sym, _ in instruments_15m
        ]
        await asyncio.gather(*tasks)

    scheduler.add_job(
        market_open_scan_job,
        CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=31,
            timezone="America/New_York",
        ),
        id="market_open_scan",
        name="Market Open Scan",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("⏰ Market open scan job registered — 09:31 ET weekdays")

    # ── EOD summary (16:05 ET) — logs daily P&L summary ────────────────────────
    async def eod_summary_job():
        """Log end-of-day summary with P&L metrics."""
        try:
            if paper_tracker is None:
                logger.info("[EOD_SUMMARY] No trades today")
                return

            today_trades = paper_tracker.get_trades_by_date(
                date_str=datetime.now().strftime("%Y-%m-%d")
            )
            total_trades = len(today_trades) if today_trades else 0

            if total_trades == 0:
                logger.info("[EOD_SUMMARY] No trades today")
                return

            realized_pnl = sum(t.get("realized_pnl", 0) for t in today_trades)
            winning = sum(1 for t in today_trades if t.get("realized_pnl", 0) > 0)
            losing = sum(1 for t in today_trades if t.get("realized_pnl", 0) < 0)

            logger.info(
                f"[EOD_SUMMARY] Trades: {total_trades} | "
                f"P&L: ${realized_pnl:.2f} | Wins: {winning} | Losses: {losing}"
            )

            # Run memory consolidation (non-fatal if it fails)
            try:
                from learning.consolidator import TradingMemoryConsolidator

                consolidator = TradingMemoryConsolidator(db_manager=db_manager)
                result = await consolidator.consolidate_daily()
                logger.info(
                    f"[EOD_CONSOLIDATION] {result.get('patterns_extracted', 0)} patterns extracted"
                )
            except Exception as consolidation_error:
                logger.warning(f"[EOD_CONSOLIDATION] Non-fatal error: {consolidation_error}")

        except Exception as e:
            logger.error(f"[EOD_SUMMARY] Failed: {e}")

    scheduler.add_job(
        eod_summary_job,
        CronTrigger(
            day_of_week="mon-fri",
            hour=16,
            minute=5,
            timezone="America/New_York",
        ),
        id="eod_summary",
        name="EOD Summary",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("⏰ EOD summary job registered — 16:05 ET weekdays")

    # ── Intraday 15-minute scanner (US-1402) ──────────────────────────────────
    async def intraday_scan_15m_job():
        """Scan MCL and MNQ on 15m timeframe to increase trade frequency."""
        try:
            from backtest.data_loader import BacktestDataLoader
            from backtest.paper_config import FIFTEEN_MIN_CONFIGS
            from backtest.signals import compute_all_indicators, generate_signals
            from routers.scanner_router import record_signal

            if safety_layer and safety_layer.get_status().get("kill_switch_active"):
                logger.info("[INTRADAY_15M] Skipping — kill switch active")
                return

            loader = BacktestDataLoader()
            for symbol in ["MCL", "MNQ"]:
                try:
                    config = FIFTEEN_MIN_CONFIGS.get(symbol)
                    if not config or not config.get("enabled"):
                        continue
                    end_date = datetime.now().strftime("%Y-%m-%d")
                    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                    df = loader.load(symbol=symbol, start=start_date, end=end_date, interval="15m")
                    if df is None or df.empty:
                        logger.warning(f"[INTRADAY_15M] No data for {symbol} 15m")
                        continue
                    df = df.tail(50).reset_index(drop=True)
                    df = compute_all_indicators(df)
                    stc = config.get("stc_params", {})
                    df = generate_signals(
                        df,
                        regime_filter=config.get("regime_filter", True),
                        stc_oversold=stc.get("stc_os"),
                        stc_overbought=stc.get("stc_ob"),
                        symbol=symbol,
                        adaptive_regime=config.get("adaptive_regime", False),
                        volume_filter=config.get("volume_filter", False),
                    )
                    entry_rows = df[df["entry_signal"] == "ENTRY_NOW"]
                    if not entry_rows.empty:
                        latest = entry_rows.iloc[-1]
                        record_signal(
                            symbol=symbol,
                            timeframe="15m",
                            entry_signal="ENTRY_NOW",
                            bias=latest.get("bias"),
                            regime=latest.get("regime"),
                            composite_score=None,
                        )
                        logger.info(
                            f"[INTRADAY_15M] {symbol} ENTRY_NOW — "
                            f"regime={latest.get('regime')}, bias={latest.get('bias')}"
                        )
                except Exception as sym_err:
                    logger.error(f"[INTRADAY_15M] {symbol} failed: {sym_err}")
        except Exception as e:
            logger.error(f"[INTRADAY_15M] job failed: {e}")

    scheduler.add_job(
        intraday_scan_15m_job,
        CronTrigger(minute="*/15", day_of_week="mon-fri", hour="9-15", timezone="America/New_York"),
        id="intraday_scan_15m",
        name="Intraday 15m Scanner",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    logger.info("⏰ Intraday 15m scanner registered — every 15 min 09:45-15:45 ET weekdays")

    # EOD P&L snapshot scheduler — registers its own jobs on the existing scheduler
    from notifications.whatsapp import get_notifier as _get_notifier
    from learning.consolidator import TradingMemoryConsolidator

    learning_consolidator = TradingMemoryConsolidator(db_manager=db_manager)

    eod_scheduler = EODScheduler(
        db_manager=db_manager,
        portfolio_tracker=paper_tracker,
        whatsapp_notifier=_get_notifier(),
        learning_consolidator=learning_consolidator,
    )
    if scheduler is not None:
        eod_scheduler.register_with_scheduler(scheduler)

    # Validation Alert Manager — monitors 30-day paper validation gates
    try:
        validation_alert_manager = ValidationAlertManager(alert_file="data/validation_alerts.json")
        eod_scheduler._alert_manager = validation_alert_manager
        set_validation_alert_manager(validation_alert_manager)
        logger.info("✅ ValidationAlertManager initialized and wired to EODScheduler")
    except Exception as _alert_err:
        logger.warning("ValidationAlertManager init failed (non-fatal): %s", _alert_err)

    # WebSocket manager for real-time event streaming
    ws_manager = WebSocketManager()
    set_ws_manager(ws_manager)
    logger.info("✅ WebSocket manager initialized for real-time events")

    # LLM Cost Tracker
    cost_tracker = CostTracker(db_path="data/llm_costs.db")
    logger.info("✅ LLM Cost Tracker initialized")

    # Consecutive Loss Tracker
    loss_tracker = ConsecutiveLossTracker(data_dir="data")
    logger.info("✅ Consecutive Loss Tracker initialized")

    # Wire loss tracker into SafetyLayer so 3/5/7-loss scaling logic is active
    safety_layer._loss_tracker = loss_tracker
    logger.info("✅ ConsecutiveLossTracker wired into SafetyLayer (3→0.5x, 5→0.25x, 7→halt)")

    # AlertManager — push WhatsApp alerts when P&L thresholds are crossed
    _pnl_alert_manager = None
    try:
        from risk.alert_manager import AlertManager as _AlertManager
        from notifications.openclaw_notifier import send_raw as _oc_send_raw

        _pnl_alert_manager = _AlertManager(notify_fn=_oc_send_raw)
        _pnl_alert_manager.start()
        safety_layer.inject_alert_manager(_pnl_alert_manager)
        logger.info(
            "✅ AlertManager started — P&L push alerts active via OpenClaw WhatsApp"
        )
    except Exception as _am_err:
        logger.warning("AlertManager init failed (non-fatal — no P&L push alerts): %s", _am_err)

    # Wire router dependencies now that all singletons are ready
    inject_portfolio_deps(paper_tracker, db_manager, data_manager, safety_layer)
    inject_safety_router_deps(safety_layer, loss_tracker)
    # Inject AlertManager into safety router for /safety/alerts/history
    try:
        from routers.safety_router import inject_alert_manager as _inject_am
        if _pnl_alert_manager is not None:
            _inject_am(_pnl_alert_manager)
    except Exception as _am_inject_err:
        logger.warning("Failed to inject AlertManager into safety_router: %s", _am_inject_err)
    inject_phase3_readiness_deps(safety_layer)
    inject_health_router_deps(
        _health_server_start,
        data_manager,
        safety_layer,
        db_manager,
        paper_tracker,
        pnl_monitor,
        trading_pipeline,
        schwab_connector,
    )
    inject_discord_data_manager(data_manager)
    inject_backtest_deps(data_manager)
    from routers.market_router import inject_dependencies as inject_market_deps
    inject_market_deps(data_manager=data_manager)
    inject_brokers_deps(ibkr=ib_paper_connector, schwab=schwab_connector, tracker=paper_tracker)
    inject_approval_deps(safety_layer, paper_tracker, db_manager)
    inject_scheduler_router_scheduler(scheduler)
    inject_pipeline_deps(scheduler, trading_pipeline, safety_layer, db_manager, paper_tracker, sdk_pipeline)
    inject_messaging_deps(str(db_manager._db_path))
    # Morning brief deps
    inject_morning_brief_deps(data_manager, paper_tracker, safety_layer)
    inject_hp_deps(data_manager, settings)
    # Routers migrated from inline main.py handlers (B4 route consolidation)
    inject_analysis_deps(technical_analyst, data_manager, cost_tracker)
    inject_sentiment_deps(data_manager)
    inject_watchlist_deps(db_manager, data_manager)
    inject_macro_deps(data_manager)
    inject_settings_deps(settings, db_manager, safety_layer)
    inject_reports_deps(db_manager)
    inject_prices_deps(PriceCache(), data_manager)
    inject_thinkscript_deps(technical_analyst)

    # Initialize Signal Scanner
    try:
        from scanner.signal_scanner import SignalScanner

        # Use FUTURES_WATCHLIST from settings so MCL, MNQ, MES are all included.
        # Fallback to ["MCL", "MNQ"] if setting is empty.
        _scan_symbols = list(settings.FUTURES_WATCHLIST) if settings.FUTURES_WATCHLIST else ["MCL", "MNQ"]
        _scanner_initial_delay = int(getattr(settings, "SCANNER_INITIAL_DELAY_SECONDS", 60))
        signal_scanner = SignalScanner(
            trading_pipeline=trading_pipeline,
            db_manager=db_manager,
            symbols=_scan_symbols,
            initial_delay_seconds=_scanner_initial_delay,
        )
        # Inject paper tracker so the scanner can auto-log paper trades
        # when it fires a BUY/SELL signal in paper mode.
        if paper_tracker is not None:
            signal_scanner.set_paper_tracker(paper_tracker)
            logger.info("Signal scanner: paper_tracker injected")
        inject_scanner_deps(signal_scanner)
        await signal_scanner.start()
        logger.info("Signal scanner started (symbols=%s, 60-min interval)", _scan_symbols)
    except Exception as e:
        logger.warning("Signal scanner failed to start: %s (non-fatal)", e)

    # Initialize Tilt Detection
    try:
        if getattr(settings, "ENABLE_TILT_DETECTION", True):
            from risk.tilt_detector import TiltDetector

            tilt_detector = TiltDetector(config=settings, loss_tracker=loss_tracker)
            safety_layer.tilt_detector = tilt_detector
            logger.info("✅ TiltDetector initialized")
    except Exception as _tilt_err:
        logger.error(f"TiltDetector init failed (non-fatal): {_tilt_err}")

    # Multi-Market Orchestrator
    try:
        from markets.futures.module import FuturesMarketModule
        from orchestrator.multi_market import MultiMarketOrchestrator, set_orchestrator

        _orchestrator = MultiMarketOrchestrator(
            daily_target=getattr(settings, "DAILY_TARGET", 500.0),
        )
        _futures_module = FuturesMarketModule(
            ib_gateway=ib_paper_connector,
            portfolio_tracker=paper_tracker,
            safety_layer=safety_layer,
            trading_pipeline=trading_pipeline,
            symbols=["MCL", "MNQ", "MES"],
        )
        _orchestrator.register(_futures_module)
        set_orchestrator(_orchestrator)
        await _orchestrator.start()
        logger.info("MultiMarketOrchestrator started with 1 module (futures: MCL, MNQ, MES)")
    except Exception as _orch_err:
        logger.warning("MultiMarketOrchestrator init failed (non-fatal): %s", _orch_err)

    # Initialize KAIROS if enabled
    if getattr(settings, "ENABLE_KAIROS", False):
        try:
            from kairos import KairosDaemon, set_kairos_instance
            from kairos.watchers import (
                CorrelationBreakWatcher,
                RegimeChangeWatcher,
                RiskLimitWatcher,
                SpreadWideningWatcher,
                STCCrossoverWatcher,
                VIXSpikeWatcher,
                VolumeAnomalyWatcher,
            )

            logger.info("KAIROS: initializing proactive monitoring daemon...")
            # Wire in WhatsApp notifier for alerts (Phase 2 — requires Twilio creds in .env)
            from notifications.whatsapp import get_notifier

            whatsapp_notifier = get_notifier()
            kairos_daemon = KairosDaemon(
                config=settings,
                data_manager=data_manager,
                safety_layer=safety_layer,
                ws_manager=ws_manager,
                notifier=whatsapp_notifier,
            )
            # Register all watchers
            kairos_daemon.register_watcher(RegimeChangeWatcher())
            kairos_daemon.register_watcher(STCCrossoverWatcher())
            kairos_daemon.register_watcher(RiskLimitWatcher())
            kairos_daemon.register_watcher(VIXSpikeWatcher())
            kairos_daemon.register_watcher(VolumeAnomalyWatcher())
            kairos_daemon.register_watcher(SpreadWideningWatcher())
            kairos_daemon.register_watcher(CorrelationBreakWatcher())
            set_kairos_instance(kairos_daemon)
            await kairos_daemon.start()
            logger.info("KAIROS: started")
        except Exception as _kairos_err:
            logger.error(
                "KAIROS: init failed (non-fatal, engine will start without KAIROS): %s", _kairos_err
            )
    else:
        logger.info("KAIROS: disabled (set ENABLE_KAIROS=True to enable)")

    # Initialize Speculation Engine (pre-fetches market data during idle periods)
    if getattr(settings, "ENABLE_SPECULATION", False):
        try:
            from speculation import SpeculationEngine, set_speculation_engine

            speculation_engine = SpeculationEngine(
                config=settings,
                data_manager=data_manager,
                prefetch_ttl=600,  # 10-minute cache TTL
            )
            set_speculation_engine(speculation_engine)
            logger.info("SpeculationEngine: initialized")

            # Register 15-min pre-fetch job offset from the 30-min pipeline scan
            # (fires at :15 and :45 past each hour so data is warm before :00/:30 scans)
            async def run_speculation_cycle():
                result = await speculation_engine.speculate()
                logger.debug(
                    f"SpeculationEngine: cycle {result['speculation_count']} — "
                    f"{result['symbols_processed']}/{result['symbols_requested']} symbols "
                    f"cached in {result['duration_ms']:.0f}ms"
                )

            scheduler.add_job(
                run_speculation_cycle,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour="9-15",
                    minute="15,45",
                    timezone="America/Chicago",
                ),
                id="speculation_prefetch",
                name="Speculation Pre-fetch",
                max_instances=1,
                misfire_grace_time=120,
            )
            if not scheduler.running:
                scheduler.start()
            logger.info(
                "SpeculationEngine: pre-fetch job registered — fires at :15/:45 past each hour (9-4 CT weekdays)"
            )
        except Exception as _spec_err:
            logger.error(f"SpeculationEngine init failed (non-fatal): {_spec_err}")
    else:
        logger.info("SpeculationEngine: disabled (set ENABLE_SPECULATION=True to enable)")

    # Initialize Database Backup (nightly at 23:30 UTC)
    try:
        import asyncio

        from backup.db_backup import get_backup_manager

        backup_manager = get_backup_manager()

        async def run_nightly_backup():
            """Run database backup and cleanup in thread executor."""
            loop = asyncio.get_event_loop()
            backup_result = await loop.run_in_executor(None, backup_manager.backup)
            cleanup_result = await loop.run_in_executor(None, backup_manager.cleanup_old)
            logger.info(f"Backup: {backup_result.get('message')}")
            logger.info(f"Cleanup: {cleanup_result.get('message')}")

        if scheduler is not None:
            scheduler.add_job(
                run_nightly_backup,
                CronTrigger(hour=23, minute=30, timezone="UTC"),
                id="nightly_db_backup",
                name="Nightly Database Backup",
                max_instances=1,
                misfire_grace_time=300,
            )
            if not scheduler.running:
                scheduler.start()
            logger.info("✅ Database backup job registered — fires nightly at 23:30 UTC")
    except Exception as _backup_err:
        logger.warning(f"Database backup init failed (non-fatal): {_backup_err}")

    # Initialize Nightly Learning Consolidation (04:00 ET = 09:00 UTC)
    try:

        async def run_nightly_consolidation() -> None:
            try:
                from learning.consolidator import TradingMemoryConsolidator

                consolidator = TradingMemoryConsolidator(db_manager=db_manager)
                result = await consolidator.consolidate_daily()
                logger.info("[LEARNING] Nightly consolidation complete: %s", result)
            except Exception as exc:
                logger.error("[LEARNING] Nightly consolidation failed: %s", exc)

        if scheduler is not None:
            scheduler.add_job(
                run_nightly_consolidation,
                CronTrigger(hour=9, minute=0, timezone="UTC"),  # 04:00 ET = 09:00 UTC
                id="nightly_learning_consolidation",
                name="Nightly Learning Consolidation",
                replace_existing=True,
            )
            logger.info(
                "✅ Learning consolidation job registered — fires nightly at 09:00 UTC (04:00 ET)"
            )
    except Exception as _consolidation_err:
        logger.warning(f"Learning consolidation init failed (non-fatal): {_consolidation_err}")

    # Initialize Morning Intelligence Brief (8:45 CT, Mon–Fri)
    try:

        async def run_morning_brief() -> None:
            """Fire-and-forget morning intelligence brief at 8:45 CT."""
            try:
                from notifications.morning_brief import assemble_morning_brief
                from notifications.openclaw_notifier import send_raw
                from notifications.discord_notifier import discord_morning_brief

                brief_text = await assemble_morning_brief()
                logger.info("[MorningBrief] Assembled: %s chars", len(brief_text))
                # Supervisor gate (Hermes pattern) — review brief before sending.
                _send_brief = True
                try:
                    from notifications.supervisor import get_supervisor, SupervisorEvent
                    _sup = get_supervisor()
                    if _sup.enabled:
                        _decision = await _sup.review(SupervisorEvent(
                            event_type="morning_brief",
                            payload={"length": len(brief_text), "preview": brief_text[:500]},
                        ))
                        _send_brief = _decision.pass_through
                        if not _send_brief:
                            logger.info("Supervisor ACK'd morning brief: %s", _decision.reason)
                except Exception as _sup_exc:
                    logger.warning("Supervisor morning_brief gate failed (fail-open): %s", _sup_exc)
                if _send_brief:
                    await send_raw(brief_text)
                    await discord_morning_brief(brief_text)
            except Exception as exc:
                logger.error("[MorningBrief] run_morning_brief failed: %s", exc)

        if scheduler is not None:
            scheduler.add_job(
                run_morning_brief,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=7,
                    minute=25,
                    timezone="America/Chicago",
                ),
                id="morning_brief",
                name="Morning Intelligence Brief",
                max_instances=1,
                replace_existing=True,
            )
            logger.info("✅ Morning brief job registered — fires Mon–Fri at 07:25 CT")
    except Exception as _brief_err:
        logger.warning(f"Morning brief init failed (non-fatal): {_brief_err}")

    # Initialize Nightly Discord Import (6:00 AM CT, Mon–Fri)
    try:

        async def run_nightly_discord() -> None:
            """Run Discord nightly import + sentiment ETL, emit completion event."""
            try:
                import scripts.nightly_discord as nd_module

                import_stats = nd_module.run_discord_import()
                sentiment_stats = nd_module.run_sentiment_etl()

                logger.info(f"Discord import complete: {import_stats}")
                logger.info(f"Discord sentiment ETL complete: {sentiment_stats}")

                from websocket.events import publish_event

                combined_stats = {"import": import_stats, "sentiment_etl": sentiment_stats}
                publish_event(
                    "system",
                    f"Discord nightly import complete: {combined_stats}",
                    severity="info",
                )

            except Exception as exc:
                logger.error("[Discord] Nightly import failed: %s", exc, exc_info=True)
                from websocket.events import publish_event

                publish_event("system", "Discord nightly import FAILED", severity="warn")

        if scheduler is not None:
            scheduler.add_job(
                run_nightly_discord,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=6,
                    minute=0,
                    timezone="America/Chicago",
                ),
                id="nightly_discord_import",
                name="Nightly Discord Import",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info("✅ Discord nightly import job registered — fires Mon–Fri at 06:00 CT")
    except Exception as _discord_err:
        logger.warning(f"Discord nightly import init failed (non-fatal): {_discord_err}")

    # Weekly bookmark thematic clustering — Sunday 18:00 CT pre-warms the
    # 6h cache so Monday-morning dashboard/API reads are instant (no LLM wait).
    try:

        async def run_bookmark_clusterer() -> None:
            try:
                from routers.discord_router import _get_bookmark_clusterer

                clusterer = _get_bookmark_clusterer()
                result = await clusterer.cluster_recent(
                    lookback_days=7, force_refresh=True
                )
                logger.info(
                    "[BookmarkClusterer] refreshed: %d themes, %d bookmarks, "
                    "actionable=%s, cost=$%.4f, error=%s",
                    len(result.themes),
                    result.bookmark_count,
                    result.actionable,
                    result.cost_usd,
                    result.error,
                )
            except Exception as exc:
                logger.error("[BookmarkClusterer] weekly refresh failed: %s", exc)

        if scheduler is not None:
            scheduler.add_job(
                run_bookmark_clusterer,
                CronTrigger(
                    day_of_week="sun",
                    hour=18,
                    minute=0,
                    timezone="America/Chicago",
                ),
                id="bookmark_weekly_cluster",
                name="Weekly Bookmark Thematic Clustering",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info(
                "✅ Bookmark clusterer registered — fires Sun at 18:00 CT"
            )
    except Exception as _bm_err:
        logger.warning(f"Bookmark clusterer init failed (non-fatal): {_bm_err}")

    # Daily bookmark vault render — writes any missing Discord bookmarks to
    # second-brain/wiki/discord-bookmarks/ so agents and the human both have
    # an Obsidian-linkable page for every URL dropped in #general. Catch-up
    # mode: existing files are skipped (preserves 2026-04-17 manual triage).
    try:
        from scripts.render_bookmarks_to_vault import render_vault as _render_vault

        _BOOKMARK_DB_PATH = os.environ.get(
            "JARVIS_TRADER_DB_PATH", "engine/data/jarvis_trader.db"
        )
        _BOOKMARK_VAULT_DIR = os.environ.get(
            "BOOKMARK_VAULT_DIR",
            r"C:\Users\mattm\second-brain\wiki\discord-bookmarks",
        )

        async def run_bookmark_vault_render() -> None:
            try:
                stats = _render_vault(_BOOKMARK_DB_PATH, _BOOKMARK_VAULT_DIR)
                logger.info(
                    "[BookmarkVaultRender] created=%d skipped=%d failed=%d by_kind=%s",
                    stats.get("created", 0),
                    stats.get("skipped_existing", 0),
                    stats.get("failed", 0),
                    stats.get("by_kind", {}),
                )
            except Exception as exc:
                logger.error(
                    "[BookmarkVaultRender] daily render failed: %s", exc, exc_info=True
                )

        if scheduler is not None:
            scheduler.add_job(
                run_bookmark_vault_render,
                CronTrigger(hour=3, minute=0, timezone="America/Chicago"),
                id="bookmark_vault_render",
                name="Daily Bookmark Vault Render",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info(
                "✅ Bookmark vault renderer registered — fires daily 03:00 CT"
            )
    except Exception as _bvr_err:
        logger.warning(
            f"Bookmark vault renderer init failed (non-fatal): {_bvr_err}"
        )

    # MES session forward-recorder — observational experiment that accumulates
    # (Corey bias + gamma levels + IB levels → hypothesis → session outcome)
    # rows for post-hoc evaluation once ~8-12 weeks of data exist. Does NOT
    # trade. See memory/project_mes_forward_recorder.md for experiment design.
    try:
        from experiments.mes_session_recorder import record_session as _mes_record
        from experiments.mes_session_outcome import fill_outcomes as _mes_fill_outcomes

        async def run_mes_session_recorder() -> None:
            try:
                result = await _mes_record(data_manager=data_manager)
                logger.info(
                    "[MESRecorder] inserted=%s side=%s reason=%s warnings=%s",
                    result.inserted,
                    result.hypothesis_side,
                    result.hypothesis_reason,
                    result.warnings,
                )
            except Exception as exc:
                logger.error("[MESRecorder] morning pass failed: %s", exc, exc_info=True)

        async def run_mes_session_outcome() -> None:
            try:
                result = await _mes_fill_outcomes(data_manager=data_manager)
                logger.info(
                    "[MESOutcome] filled=%d skipped_existing=%d skipped_no_data=%d errors=%s",
                    result.updated_rows,
                    result.skipped_existing,
                    result.skipped_no_data,
                    result.errors,
                )
            except Exception as exc:
                logger.error("[MESOutcome] afternoon pass failed: %s", exc, exc_info=True)

        if scheduler is not None:
            scheduler.add_job(
                run_mes_session_recorder,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=8,
                    minute=30,
                    timezone="America/Chicago",
                ),
                id="mes_session_recorder",
                name="MES Session Hypothesis Recorder (morning)",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=1800,
            )
            scheduler.add_job(
                run_mes_session_outcome,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=15,
                    minute=15,
                    timezone="America/Chicago",
                ),
                id="mes_session_outcome",
                name="MES Session Hypothesis Outcome (afternoon)",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info(
                "✅ MES session forward-recorder registered — "
                "morning 08:30 CT / outcome 15:15 CT, Mon-Fri"
            )
    except Exception as _mes_err:
        logger.warning(f"MES forward-recorder init failed (non-fatal): {_mes_err}")

    # Corey staleness watchdog (hourly, weekdays 9-17 CT) — alerts if
    # discord_corey_commentary stops refreshing. Agents consume corey_session_bias
    # derived from this table; silent staleness = silent signal drift.
    try:

        async def run_corey_staleness_check() -> None:
            """Alert on WhatsApp if Corey's commentary feed is >48h stale on a weekday."""
            try:
                import sqlite3
                from datetime import datetime, timedelta
                from zoneinfo import ZoneInfo
                from config import settings
                from notifications.openclaw_notifier import notify_corey_stale

                ct = ZoneInfo("America/Chicago")
                now_ct = datetime.now(ct)
                if now_ct.weekday() >= 5:  # Saturday/Sunday — no alert
                    return

                with sqlite3.connect(settings.SQLITE_DB_PATH) as conn:
                    row = conn.execute(
                        "SELECT MAX(timestamp) FROM discord_corey_commentary"
                    ).fetchone()

                if not row or not row[0]:
                    logger.warning("[CoreyStale] discord_corey_commentary empty — firing alert")
                    await notify_corey_stale(days_stale=999, last_message_date="never")
                    return

                last_raw = str(row[0])
                try:
                    last_dt = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=ZoneInfo("UTC"))
                except ValueError:
                    logger.error("[CoreyStale] Unparseable last-msg timestamp: %r", last_raw)
                    return

                age = now_ct - last_dt.astimezone(ct)
                days_stale = age.total_seconds() / 86400.0
                if days_stale >= 2.0:
                    logger.warning(
                        "[CoreyStale] discord_corey_commentary %.1f days stale — alerting",
                        days_stale,
                    )
                    await notify_corey_stale(
                        days_stale=int(days_stale),
                        last_message_date=last_dt.strftime("%Y-%m-%d %H:%M CT"),
                    )
                else:
                    logger.debug(
                        "[CoreyStale] OK — last msg %.1f days ago", days_stale
                    )
            except Exception as exc:
                logger.error("[CoreyStale] check failed (non-fatal): %s", exc, exc_info=True)

        if scheduler is not None:
            scheduler.add_job(
                run_corey_staleness_check,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour="9-17",
                    minute=0,
                    timezone="America/Chicago",
                ),
                id="corey_staleness_watchdog",
                name="Corey Commentary Staleness Watchdog",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=1800,
            )
            logger.info("✅ Corey staleness watchdog registered — hourly Mon-Fri 9-17 CT")
    except Exception as _corey_err:
        logger.warning(f"Corey staleness watchdog init failed (non-fatal): {_corey_err}")

    # Initialize IB Gateway Health Monitor (every 15 minutes, Mon-Fri 8:00am-4:45pm CT)
    try:

        async def run_ib_health_check() -> None:
            """Check IB Gateway health and alert on disconnect."""
            try:
                from health.ib_monitor import check_ib_health
                from brokers.ib_paper_connector import ib_paper_connector

                result = await check_ib_health(ib_paper_connector)
                if not result:
                    logger.warning("[IBHealth] IB Gateway health check failed (disconnected)")
            except Exception as exc:
                logger.debug(f"[IBHealth] Health check failed (non-fatal): {exc}")

        if scheduler is not None:
            scheduler.add_job(
                run_ib_health_check,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour="8-16",
                    minute="0,15,30,45",
                    timezone="America/Chicago",
                ),
                id="ib_health_monitor",
                name="IB Gateway Health Monitor",
                max_instances=1,
                misfire_grace_time=60,
                replace_existing=True,
            )
            logger.info(
                "✅ IB health monitor job registered — fires every 15 min Mon–Fri 8am–4:45pm CT"
            )
    except Exception as _health_err:
        logger.warning(f"IB health monitor init failed (non-fatal): {_health_err}")

    # Periodic SafetyLayer equity sync (every 60 seconds) — ground-truth from PnLMonitor
    try:

        async def _sync_safety_equity() -> None:
            """Pull current equity + daily P&L from PnLMonitor and push to SafetyLayer."""
            try:
                if safety_layer is None or pnl_monitor is None:
                    logger.warning(
                        "[sync_safety_equity] early-return: safety_layer=%s pnl_monitor=%s",
                        safety_layer is not None,
                        pnl_monitor is not None,
                    )
                    return
                state = pnl_monitor.get_current_pnl_state()
                equity = state.current_balance if state.current_balance > 0 else safety_layer._current_equity
                daily_pnl = pnl_monitor.get_daily_pnl()
                safety_layer.sync_from_broker(equity, daily_pnl)
            except Exception as exc:
                logger.warning("[sync_safety_equity] error: %s", exc, exc_info=True)

        if scheduler is not None:
            scheduler.add_job(
                _sync_safety_equity,
                "interval",
                seconds=60,
                id="sync_safety_equity",
                name="SafetyLayer Equity Sync",
                max_instances=1,
                replace_existing=True,
            )
            if not scheduler.running:
                scheduler.start()
            logger.info("✅ SafetyLayer equity sync job registered — fires every 60 seconds")
    except Exception as _sync_err:
        logger.warning(f"SafetyLayer equity sync job init failed (non-fatal): {_sync_err}")

    # ── RL executor — MES paper validation (experimental, non-blocking) ───────
    try:
        from pathlib import Path as _RLPath
        from strategies.rl_executor import RLExecutor

        _rl_model_dir = _RLPath(__file__).parent / "data" / "rl_models"
        _mes_models = sorted(_rl_model_dir.glob("MES_*.zip"))
        if _mes_models:
            _latest_mes_model = str(_mes_models[-1]).removesuffix(".zip")
            _rl_executor = RLExecutor(
                symbol="MES",
                model_path=_latest_mes_model,
                data_manager=data_manager,
                safety_layer=safety_layer,
            )
            _rl_executor.start()  # sync — starts BackgroundScheduler thread (non-blocking)
            logger.info(
                "RL executor started — MES paper validation running (model: %s)",
                _mes_models[-1].name,
            )
        else:
            logger.warning("[RL Executor] No MES model found in data/rl_models/ — skipping")
    except Exception as _rl_err:
        logger.warning("[RL Executor] Could not start: %s — continuing without RL", _rl_err)

    # ── Weekly strategy discovery ──────────────────────────────────────────────
    try:
        async def _run_weekly_discovery() -> None:
            """Saturday midnight: generate + evaluate one LLM strategy per active instrument."""
            try:
                from pathlib import Path as _Path
                from strategies.discovery_loop import generate_strategy, evaluate_strategy_file

                for _sym, _ivl in [("MCL", "1h"), ("MNQ", "1h")]:
                    logger.info(f"[WeeklyDiscovery] Running cycle for {_sym}/{_ivl}")
                    _path = await generate_strategy(symbol=_sym, interval=_ivl)
                    if _path is None:
                        logger.warning(f"[WeeklyDiscovery] No strategy generated for {_sym}")
                        continue
                    _result = evaluate_strategy_file(
                        filename=_Path(_path).name, symbol=_sym, interval=_ivl
                    )
                    logger.info(
                        f"[WeeklyDiscovery] {_sym} verdict={_result.get('verdict')} "
                        f"sharpe={_result.get('sharpe', 0):.2f}"
                    )
            except Exception as _disc_err:
                logger.error(f"[WeeklyDiscovery] Failed: {_disc_err}", exc_info=True)

        if scheduler is not None:
            scheduler.add_job(
                _run_weekly_discovery,
                CronTrigger(day_of_week="sat", hour=0, minute=0, timezone="America/Chicago"),
                id="weekly_discovery",
                name="Weekly Strategy Discovery",
                max_instances=1,
                replace_existing=True,
            )
            logger.info("Weekly strategy discovery job registered (Saturday 00:00 Chicago)")
    except Exception as _weekly_err:
        logger.warning(f"Weekly discovery job init failed (non-fatal): {_weekly_err}")

    # ── Weekly gate v2 orchestrator ────────────────────────────────────────────
    # Re-scores the revised dual-pathway gate for each tracked symbol and
    # persists a verdict snapshot under engine/data/gate_v2_verdicts/.
    # Advisory only — does NOT block routing. See:
    #   * scripts/gate_v2_orchestrator.py
    #   * backtest/gate_v2_policy.py
    #   * memory/project_gate_v2_proposal.md
    try:
        # (symbol, family, rank, results_file_relative_to_engine/)
        _GATE_V2_TRACKED: list[tuple[str, str, int, str]] = [
            ("MES", "trend",   7, "scripts/mes_trend_search_results.json"),
            ("MCL", "meanrev", 1, "scripts/mcl_meanrev_search_results.json"),
            ("MNQ", "trend",   1, "scripts/mnq_trend_search_results.json"),
        ]

        async def _run_weekly_gate_v2() -> None:
            """Saturday 01:00 CT: re-score gate v2 for each tracked symbol."""
            try:
                from pathlib import Path as _Path
                from scripts.gate_v2_orchestrator import orchestrate_gate_v2

                engine_dir = _Path(__file__).resolve().parent
                reports_dir = engine_dir / "scripts" / "validation_reports"
                output_dir = engine_dir / "data" / "gate_v2_verdicts"

                for _sym, _fam, _rank, _results_rel in _GATE_V2_TRACKED:
                    _results_file = engine_dir / _results_rel
                    if not _results_file.exists():
                        logger.warning(
                            "[GateV2Weekly] missing results file %s — skipping %s/%s rank=%d",
                            _results_file, _sym, _fam, _rank,
                        )
                        continue
                    try:
                        _snap = orchestrate_gate_v2(
                            results_file=_results_file,
                            symbol=_sym, family=_fam, rank=_rank,
                            reports_dir=reports_dir,
                            output_dir=output_dir,
                        )
                        logger.info(
                            "[GateV2Weekly] %s/%s rank=%d verdict=%s via=%s "
                            "(core %d/4, alt %d/5)",
                            _sym, _fam, _rank, _snap.verdict,
                            _snap.passed_via or "-",
                            _snap.n_core_passed, _snap.n_alt_passed,
                        )
                    except Exception as _inner_err:
                        logger.error(
                            "[GateV2Weekly] %s/%s rank=%d failed: %s",
                            _sym, _fam, _rank, _inner_err, exc_info=True,
                        )
            except Exception as _gv2_err:
                logger.error(f"[GateV2Weekly] cycle failed: {_gv2_err}", exc_info=True)

        if scheduler is not None:
            scheduler.add_job(
                _run_weekly_gate_v2,
                CronTrigger(day_of_week="sat", hour=1, minute=0, timezone="America/Chicago"),
                id="weekly_gate_v2",
                name="Weekly Gate v2 Orchestrator",
                max_instances=1,
                replace_existing=True,
            )
            logger.info("Weekly gate v2 orchestrator registered (Saturday 01:00 Chicago)")
    except Exception as _gv2_init_err:
        logger.warning(
            f"Weekly gate v2 job init failed (non-fatal): {_gv2_init_err}"
        )

    # ── Telegram long-polling service ──────────────────────────────────────────
    try:
        from routers.messaging_router import start_messaging_services
        await start_messaging_services()
        logger.info("✅ Messaging services started (Telegram poller)")
    except Exception as _msg_err:
        logger.warning("Messaging services init failed (non-fatal): %s", _msg_err)

    logger.info("JARVIS TRADER ready. Dashboard: http://localhost:3010")
    logger.info("   API docs: http://localhost:8010/docs")

    # ── Signal handlers for clean crash detection ──────────────────────────────
    # Log reason before exit so watchdog.log can distinguish crash vs intentional stop.
    def _make_signal_handler(sig_name: str):
        def _handler(signum, frame):
            logger.warning(
                "ENGINE SHUTTING DOWN — reason: %s (signal %d)",
                sig_name,
                signum,
            )
            # Re-raise as KeyboardInterrupt so uvicorn's normal shutdown path runs
            raise KeyboardInterrupt(f"Signal {sig_name} received")
        return _handler

    try:
        # SIGINT = Ctrl-C / manual stop; SIGTERM = Task Scheduler / OS shutdown
        signal.signal(signal.SIGINT, _make_signal_handler("SIGINT"))
        signal.signal(signal.SIGTERM, _make_signal_handler("SIGTERM"))
        logger.info("✅ Signal handlers registered (SIGINT, SIGTERM)")
    except (OSError, ValueError) as _sig_err:
        # On Windows, SIGTERM is not always supported; log and continue
        logger.warning("Signal handler registration incomplete: %s", _sig_err)

    yield  # Server runs here

    # Teardown
    # Stop AlertManager worker gracefully
    if _pnl_alert_manager is not None:
        try:
            await _pnl_alert_manager.stop()
        except Exception:
            pass
    try:
        from orchestrator.multi_market import get_orchestrator

        _orch = get_orchestrator()
        if _orch:
            await _orch.stop()
    except Exception:
        pass
    # Shutdown KAIROS
    try:
        from kairos import get_kairos

        kairos = get_kairos()
        if kairos:
            await kairos.stop()
    except Exception:
        pass
    if data_manager and data_manager.ibkr:
        await data_manager.ibkr.disconnect()
    try:
        if ib_paper_connector and ib_paper_connector.is_connected():
            await ib_paper_connector.disconnect()
    except Exception:
        pass
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
    # Close Brave Search client if it was initialised
    try:
        if _brave_client is not None:
            await _brave_client.close()
    except Exception:
        pass
    # Stop Telegram poller
    try:
        from routers.messaging_router import stop_messaging_services
        await stop_messaging_services()
    except Exception:
        pass
    logger.info("JARVIS TRADER shutdown complete")


_health_server_start = datetime.now(timezone.utc)

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


app.add_middleware(GlobalExceptionHandler)
# Build CORS origins from env so Railway/Vercel deployments work without code changes.
# CORS_ALLOWED_ORIGINS env var accepts comma-separated URLs (no trailing slashes).
# Falls back to localhost-only for local dev when env var is not set.
_cors_env = os.environ.get("CORS_ALLOWED_ORIGINS", "")
_cors_origins: list[str] = (
    [o.strip() for o in _cors_env.split(",") if o.strip()]
    if _cors_env
    else [
        "http://localhost:3010",
        "http://localhost:3000",
        "http://localhost:3004",
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(APIKeyMiddleware)
app.state.limiter = get_limiter()
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

app.include_router(health_router)
app.include_router(phase3_readiness_router)
app.include_router(journal_router, prefix="/journal", tags=["journal"])
app.include_router(jarvis_router)
app.include_router(trades_router)
app.include_router(flags_router, prefix="/flags", tags=["feature-flags"])
app.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
app.include_router(market_router)
app.include_router(analytics_router)
app.include_router(safety_router)
app.include_router(strategies_router)
app.include_router(validation_router)
app.include_router(paper_validation_router)
app.include_router(proactive_validation_router)
app.include_router(webhook_router)
app.include_router(discord_router)
app.include_router(experiments_router)
app.include_router(backtest_router)
app.include_router(learning_router)
app.include_router(events_router)
app.include_router(kairos_router)
app.include_router(profiling_router)
app.include_router(schwab_router)
app.include_router(instruments_router)
app.include_router(brokers_router)
app.include_router(options_router)
app.include_router(approval_router)
app.include_router(pipeline_router)
app.include_router(messaging_router)
app.include_router(scanner_router)
app.include_router(tradingview_router)
app.include_router(scheduler_router)
app.include_router(wfe_router)
app.include_router(discovery_router)
app.include_router(hidden_pivots_router)
app.include_router(decisions_router)
app.include_router(cache_router)
app.include_router(v1_router)
app.include_router(observability_router)
app.include_router(strategy_c_router)
app.include_router(system2_router)
app.include_router(analysis_router)
app.include_router(sentiment_router)
app.include_router(watchlist_router)
app.include_router(macro_router)
app.include_router(settings_router)
app.include_router(reports_router)
app.include_router(prices_router)
app.include_router(thinkscript_router)
app.include_router(eod_router)
app.include_router(research_journal_router)



