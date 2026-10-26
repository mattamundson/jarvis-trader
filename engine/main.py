"""
JARVIS TRADER — Main Server
============================
FastAPI backend for the trading engine.
Runs on port 8010 (separate from GMS JARVIS on 8009).

Start with: ~/scripts/restart-jarvis-engine.sh   (PYTHONPATH-guarded canonical restart)
(No --reload — IB Gateway / duplicate client-id issues; use restart_engine.ps1 after code changes.
Manual dev start: cd engine && PYTHONPATH= .venv\\Scripts\\python -m uvicorn main:app --port 8010)
"""

import asyncio
import json
import logging
import logging.handlers
import os
import signal
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from agents.bear_researcher import BearResearcherAgent
from agents.breakout_agent import BreakoutAgent
from agents.harmonic_agent import HarmonicAgent
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
from agents.trader import TraderAgent
from config import settings
from data.market_data import MarketDataManager
from database.schema import DatabaseManager, init_db
from learning.model_drawer import ModelDrawer
from strategies.arbitrage.polymarket_arb import ArbScout
from execution.ib_gateway_connector import IBGatewayConnector
from execution.ib_order_manager import IBOrderManager
from execution.order_router import OrderRouter
from execution.schwab_connector import SchwabConnector
from llm.client import JarvisLLMClient
from llm.cost_tracker import CostTracker
from utils.inference_router import get_inference_router
from middleware.api_key_middleware import APIKeyMiddleware
from middleware.exception_handler import GlobalExceptionHandler
from middleware.rate_limit import get_limiter, rate_limit_exception_handler
from portfolio.tracker import PortfolioTracker
from risk.loss_tracker import ConsecutiveLossTracker
from risk.pnl_monitor import PnLMonitor
from risk.safety_layer import SafetyLayer
from risk.margin_monitor import MarginMonitorAgent
from risk.regime_guard import RegimeGuard
from validation.shadow_mode import ShadowModeTracker
from routers.analytics_router import router as analytics_router
from routers.analytics_router import set_db_manager as set_analytics_db
from routers.analytics_router import set_data_manager as set_analytics_data_manager
from routers.backtest_router import router as backtest_router
from routers.backtest_router import inject_dependencies as inject_backtest_deps
from routers.options_backtest_router import router as options_backtest_router
from routers.discord_router import inject_data_manager as inject_discord_data_manager
from routers.discord_router import router as discord_router
from routers.experiments_router import router as experiments_router
from routers.flags_router import router as flags_router
from routers.flags_router import set_flags as set_flags_router
from routers.health_router import inject_dependencies as inject_health_router_deps
from routers.health_router import router as health_router
from routers.journal_router import router as journal_router
from routers.journal_router import set_db_manager as set_journal_db
from routers.journal_review_router import router as journal_review_router
from routers.journal_review_router import inject_dependencies as inject_journal_review_deps
from routers.jarvis_router import router as jarvis_router
from routers.kairos_router import router as kairos_router
from routers.learning_router import router as learning_router
from routers.events_router import router as events_router
from routers.market_router import router as market_router
from routers.institutional_router import router as institutional_router
from routers.institutional_router import inject_data_manager as inject_institutional_data_manager
from routers.phase3_readiness_router import inject_dependencies as inject_phase3_readiness_deps
from routers.phase3_readiness_router import router as phase3_readiness_router
from routers.portfolio_router import inject_dependencies as inject_portfolio_deps
from routers.portfolio_router import router as portfolio_router
from routers.profiling_router import router as profiling_router
from routers.profiling_router import set_profiler_instance
from routers.reports_router import router as reports_router
from routers.strategy_lab_router import router as strategy_lab_router
from routers.safety_router import inject_dependencies as inject_safety_router_deps
from routers.safety_router import router as safety_router
from routers.schwab_router import router as schwab_router
from routers.schwab_router import set_schwab_connector
from routers.strategies_router import router as strategies_router
from routers.trading_status_router import router as trading_status_router
from routers.validation_router import router as validation_router
from routers.validation_router import set_validation_alert_manager
from routers.paper_validation_router import router as paper_validation_router
from routers.proactive_validation_router import router as proactive_validation_router
from routers.execution_status_router import router as execution_status_router
from routers.webhook_router import router as webhook_router
from routers.whatsapp_router import router as whatsapp_router
from routers.whatsapp_router import inject_dependencies as inject_whatsapp_deps
from routers.instruments_router import router as instruments_router
from routers.brokers_router import router as brokers_router
from routers.brokers_router import inject_dependencies as inject_brokers_deps
from routers.options_router import router as options_router
from routers.options_router import set_data_manager as set_options_data_manager
from routers.approval_router import router as approval_router
from routers.approval_router import inject_dependencies as inject_approval_deps
from routers.actionable_router import router as actionable_router
from routers.actionable_router import inject_dependencies as inject_actionable_deps
from routers.signal_outcomes_router import router as signal_outcomes_router
from routers.signal_outcomes_router import (
    inject_dependencies as inject_signal_outcomes_deps,
)
from routers.approval_queue_router import router as approval_queue_router
from routers.approval_queue_router import inject_approval_queue_deps
from routers.pipeline_router import router as pipeline_router
from routers.pipeline_router import inject_dependencies as inject_pipeline_deps
from routers.session_brief_router import router as session_brief_router
from routers.session_brief_router import inject_dependencies as inject_session_brief_deps
from routers.framing_brief_router import router as framing_brief_router
from routers.options_signals_router import router as options_signals_router
from routers.pipeline_ws_router import router as pipeline_ws_router
from routers.messaging_router import router as messaging_router
from routers.messaging_router import inject_dependencies as inject_messaging_deps
from routers.observability_router import router as observability_router
from routers.strategy_c_router import router as strategy_c_router
from routers.scanner_router import router as scanner_router
from routers.scanner_router import inject_dependencies as inject_scanner_deps
from routers.super_engine_router import router as super_engine_router, inject_super_engine
from routers.tradingview_router import router as tradingview_router
from routers.scheduler_router import router as scheduler_router
from routers.scheduler_router import inject_scheduler as inject_scheduler_router_scheduler
from routers.trades_router import router as trades_router
from routers.trades_router import inject_dependencies as inject_trades_deps
from routers.strategy_ledger_router import router as strategy_ledger_router
from routers.forward_test_router import router as forward_test_router
from routers.validation_analytics_router import router as validation_analytics_router
from routers.wfe_router import router as wfe_router
from routers.discovery_router import router as discovery_router
from routers.orders_router import router as orders_router
from routers.orders_router import inject_dependencies as inject_orders_deps
from routers.hidden_pivots_router import router as hidden_pivots_router
from routers.hidden_pivots_router import inject_dependencies as inject_hp_deps
from routers.decisions_router import router as decisions_router
from routers.decisions_router import set_db_manager as set_decisions_db
from routers.decisions_router import set_data_manager as set_decisions_data_manager
from routers.admin_router import router as admin_router
from routers.cache_router import router as cache_router
from routers.readiness_router import router as readiness_router
from routers.polymarket_router import router as polymarket_router
from api.operations_dashboard import router as operations_dashboard_router
from routers.attribution_router import router as attribution_router
from routers.vault_router import router as vault_router
from routers.pnl_truth_router import router as pnl_truth_router
from routers.durability_router import router as durability_router
from routers.ib_scanner_router import router as ib_scanner_router
from routers.macro_router import router as macro_router, inject_dependencies as inject_macro_deps
from routers.analysis_router import (
    router as analysis_router,
    inject_dependencies as inject_analysis_deps,
)
from routers.regime_router import (
    router as regime_router,
    inject_dependencies as inject_regime_deps,
)
from routers.watchlist_router import (
    router as watchlist_router,
    inject_dependencies as inject_watchlist_deps,
)
from routers.sentiment_router import (
    router as sentiment_router,
    inject_dependencies as inject_sentiment_deps,
)
from routers.settings_router import (
    router as settings_router,
    inject_dependencies as inject_settings_deps,
)
from routers.prices_router import (
    router as prices_router,
    inject_dependencies as inject_prices_deps,
)
from routers.tos_router import (
    router as tos_router,
    inject_dependencies as inject_tos_deps,
)
from routers.pnl_attribution_router import router as pnl_attribution_router
from routers.auction_bias_router import (
    router as auction_bias_router,
    inject_dependencies as inject_auction_bias_deps,
)
from routers.websocket_router import (
    router as websocket_router,
    inject_dependencies as inject_websocket_deps,
)
from routers.thinkscript_router import (
    router as thinkscript_router,
    inject_dependencies as inject_thinkscript_deps,
)
from routers.alerts_router import (
    router as alerts_router,
    inject_dependencies as inject_alerts_deps,
)
from routers.notifications_router import router as notifications_router
from routers.pipeline_board_router import router as pipeline_board_router
from routers.config_router import router as config_router
from routers.crypto_router import router as crypto_router
from routers.openclaw_router import router as openclaw_router
from routers.openclaw_router import inject_dependencies as inject_openclaw_deps
from data.price_cache import PriceCache
from data.auction_bias_provider import LiveAuctionDataProvider
from schedulers.eod_scheduler import EODScheduler
from notifications.validation_alerts import ValidationAlertManager
from notifications.morning_brief import inject_morning_brief_deps
from websocket.events import set_ws_manager
from websocket.manager import WebSocketManager

try:
    from execution.polymarket_connector import PolymarketConnector
except ImportError as _pm_err:
    PolymarketConnector = None  # Polymarket optional; py-clob-client↔py-order-utils version skew
try:
    from data.openbb_adapter import OpenBBAdapter
except ImportError as _obb_err:
    OpenBBAdapter = None  # openbb optional; install only if macro data needed
from risk.protections import RiskProtections
from orchestrator.sentiment_bridge import SentimentBridge

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

    # Quiet pure-infrastructure loggers that flood stderr (→ the PM2 error log,
    # 220MB on 2026-07-06) with zero diagnostic value: apscheduler emits a
    # start+finish INFO line per interval job (Messaging Health Monitor, Auto-expire,
    # SafetyLayer Equity Sync, ...), and httpx/httpcore log every request (the ollama
    # /api/tags poll, every Anthropic call). Real signals (CSV-cache fallbacks,
    # ib_async delayed-data, our own WARN/ERROR) are deliberately left untouched.
    # This is the source-side complement to scripts/rotate_pm2_logs.ps1.
    for _noisy in ("apscheduler", "httpx", "httpcore"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)


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
margin_monitor: "MarginMonitorAgent | None" = None
breakout_analyst: "BreakoutAgent | None" = None
harmonic_analyst: "HarmonicAgent | None" = None
polymarket: "PolymarketConnector | None" = None
openbb: "OpenBBAdapter | None" = None
risk_protections: RiskProtections | None = None
sentiment_bridge: SentimentBridge | None = None
model_drawer: ModelDrawer | None = None
arb_scout: ArbScout | None = None
shadow_tracker: ShadowModeTracker | None = None
oms_manager: "OMSManager | None" = None  # noqa: F821
tv_streamer: "TVStreamer | None" = None  # noqa: F821
memory_bridge: "MemoryBridge | None" = None  # noqa: F821
redis_trigger: "RedisSignalTrigger | None" = None  # noqa: F821
trailing_stop_manager: "TrailingStopManager | None" = None  # noqa: F821
portfolio_allocator: "PortfolioAllocator | None" = None  # noqa: F821
canary_manager: "CanaryManager | None" = None  # noqa: F821
ib_data_watchdog: "IBDataWatchdog | None" = None  # noqa: F821
ib_freshness_heartbeat: "IBFreshnessHeartbeat | None" = None  # noqa: F821
paper_stop_monitor: "PaperStopMonitor | None" = None  # noqa: F821


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
    _log_pipeline_whatsapp_to_alert_log(symbol, msg, "suppressed", error="whatsapp_not_configured")
    return False, "whatsapp_not_configured"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and teardown on startup/shutdown"""
    global data_manager, safety_layer, technical_analyst, trading_pipeline, scheduler, paper_tracker, db_manager, pnl_monitor, eod_scheduler, order_manager, ib_paper_connector, schwab_connector, order_router, ws_manager, cost_tracker, loss_tracker, validation_alert_manager, sdk_pipeline, margin_monitor, breakout_analyst, harmonic_analyst, polymarket, openbb, risk_protections, model_drawer, arb_scout, sentiment_bridge, shadow_tracker, oms_manager, tv_streamer, memory_bridge, redis_trigger, trailing_stop_manager, portfolio_allocator, canary_manager

    # Setup structured logging with file rotation FIRST, before any other initialization
    setup_logging(log_level=settings.LOG_LEVEL)

    logger.info("🤖 JARVIS TRADER starting up...")

    # ── Heavy Init Background Task (Phase 1.8) ───────────────────────────
    async def _complete_background_init():
        """Heavy lifting moved here to enable <10s server binding."""
        global data_manager, ib_paper_connector, schwab_connector, portfolio_allocator
        global tv_streamer, redis_trigger, trailing_stop_manager, canary_manager
        global paper_stop_monitor, ib_data_watchdog, ib_freshness_heartbeat

        logger.info("⏳ Starting heavy background initialization...")

        # 1. Market Data + IBKR Connection
        try:
            await data_manager.initialize()
            logger.info("✅ MarketDataManager background initialization complete")

            # Paper IB connection
            if settings.PAPER_TRADING and ib_paper_connector:
                _paper_ib_ok = False
                for _attempt in range(3):
                    _paper_ib_ok = await ib_paper_connector.connect()
                    if _paper_ib_ok:
                        break
                    if _attempt < 2:
                        logger.warning(
                            f"IB connector attempt {_attempt+1}/3 failed; retrying in 30s"
                        )
                        await asyncio.sleep(30)

                if _paper_ib_ok:
                    safety_layer.attach_ib_gateway(ib_paper_connector)
                    order_router.attach_ibkr(ib_paper_connector)
                    logger.info(
                        "✅ %s (paper) connected + attached to order path",
                        type(ib_paper_connector).__name__,
                    )
                else:
                    if getattr(settings, "IB_PAPER_BROKER_ENABLED", False):
                        # Real gateway requested but unreachable: leave the order path
                        # UNATTACHED (fail-closed, no orders route) and shout about it.
                        logger.critical(
                            "IB_PAPER_BROKER_ENABLED=1 but the REAL IB gateway failed to connect "
                            "after 3 attempts — order path is UNATTACHED (fail-closed: no orders "
                            "will route). Check IB Gateway on port %s.",
                            settings.IBKR_PORT,
                        )
                    else:
                        logger.warning(
                            "⚠️ IBGatewayConnector background connect failed after 3 attempts"
                        )
        except Exception as e:
            logger.error(f"❌ Background data/IBKR init failed: {e}")

        # 2. Schwab Connection
        if settings.SCHWAB_APP_KEY and settings.SCHWAB_APP_SECRET:
            try:
                if await schwab_connector.initialize():
                    order_router.attach_schwab(schwab_connector)
                    logger.info("✅ SchwabConnector background initialization complete")
            except Exception as e:
                logger.warning(f"⚠️ Schwab background init failed: {e}")

        # 3. Portfolio Allocator
        try:
            await portfolio_allocator.calculate_allocations()
            logger.info("✅ Portfolio Allocator background calculation complete")
        except Exception as e:
            logger.warning(f"⚠️ Portfolio Allocator background failed: {e}")

        # 4. Real-Time Data Fabric
        try:
            from data.tradingview_stream import get_tv_streamer

            greeks_watch = os.getenv("OPTIONS_GREEKS_WATCH", "").split(",")
            greeks_watch = [s.strip() for s in greeks_watch if s.strip()]

            tv_streamer = get_tv_streamer(greeks_symbols=greeks_watch)
            await tv_streamer.start(data_manager=data_manager)
            logger.info("🚀 Real-time data fabric background activated")

            from events.redis_listener import RedisSignalTrigger
            from services.trailing_stop_manager import TrailingStopManager

            redis_trigger = RedisSignalTrigger(
                pipeline_callback=lambda sym: asyncio.create_task(
                    trading_pipeline.analyze_and_decide(sym, is_futures=True)
                ),
                symbols=[
                    "MES",
                    "MNQ",
                    "MCL",
                    "BTCUSD",
                ],  # MGC eliminated 2026-06-26 re-gate (all 5 variants honest FAIL)
            )
            await redis_trigger.start()

            trailing_stop_manager = TrailingStopManager(oms_manager, data_manager)
            await trailing_stop_manager.start()
            logger.info("🚀 Event-driven signal trigger + Trail Stop active")
        except Exception as e:
            logger.warning(f"⚠️ Real-time fabric background failed: {e}")

        # 5. A/B Canary Framework (Phase 7.3)
        try:
            from services.canary_manager import CanaryManager

            canary_manager = CanaryManager(db_manager, data_manager)
            await canary_manager.start()
            logger.info("🚀 A/B Canary Framework activated (Shadow Testing loop)")
        except Exception as e:
            logger.warning(f"⚠️ CanaryManager background failed: {e}")

        # 5.5. IB data-leg auto-reconnect watchdog (mid-session self-healing).
        # The execution leg already self-heals via its heartbeat; this gives the
        # market-data leg the same, plus stale-data detection + silent-degrade alerts.
        try:
            from services.ib_data_watchdog import IBDataWatchdog

            ib_data_watchdog = IBDataWatchdog(data_manager)
            await ib_data_watchdog.start()
        except Exception as e:
            logger.warning(f"⚠️ IBDataWatchdog failed to start: {e}")

        # 5.6. IB market-data freshness heartbeat. Keeps datasource:ib_gateway
        # fresh in Redis on a fixed cadence regardless of open positions, so
        # /system/data-integrity and the feeds_live readiness gate reflect the
        # live IB feed instead of the dead TV scraper's stale keys.
        try:
            from services.ib_freshness_heartbeat import IBFreshnessHeartbeat

            ib_freshness_heartbeat = IBFreshnessHeartbeat(data_manager)
            await ib_freshness_heartbeat.start()
        except Exception as e:
            logger.warning(f"⚠️ IBFreshnessHeartbeat failed to start: {e}")

        # 6. Paper Stop-Loss Monitor (Initiative 1, Track A2)
        # Feed-independent backstop: enforces open paper stops via the tick-price
        # path even when the historical-bar pipeline (and thus the paper_runner
        # bar-loop) is dark. Closes the gap that caused trade #178's −$1,284 loss.
        try:
            from services.paper_stop_monitor import PaperStopMonitor

            # oms_manager_getter is a lazy zero-arg lookup, not a direct
            # reference: this background-init task races the outer lifespan()
            # flow that constructs OMSManager (line ~751), so capturing
            # `oms_manager` by value here could freeze in a stale None if this
            # branch runs first. The getter re-reads the module global fresh
            # on every sweep instead.
            paper_stop_monitor = PaperStopMonitor(
                db_manager, data_manager, oms_manager_getter=lambda: oms_manager
            )
            await paper_stop_monitor.start()
            logger.info("🛡️ Paper stop-loss monitor activated (feed-independent backstop)")
        except Exception as e:
            logger.warning(f"⚠️ PaperStopMonitor background failed: {e}")

        logger.info("✨ Heavy background initialization FINISHED")

        # I3: post-init invariant self-check -- one structured block per boot.
        # Re-asserts live state (flags table, RL gate, fidelity collector,
        # DO_NOT_TRADE, mode, LLM chain) so silent degradation is loud.
        try:
            from startup_checks import log_post_init_selfcheck

            log_post_init_selfcheck(settings)
        except Exception as _selfcheck_err:
            logger.warning("Post-init self-check failed (non-fatal): %s", _selfcheck_err)

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
    inject_journal_review_deps(db_path=settings.SQLITE_DB_PATH, llm=None)
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

    # Margin Monitor — Phase 3
    # Initialized here, connector will be wired after data_manager
    margin_monitor = MarginMonitorAgent(connector=None)
    logger.info("✅ Margin Monitor Agent initialised")

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

    # JARVIS Super-Engine: Polymarket, OpenBB, Risk Protections
    if PolymarketConnector is not None:
        polymarket = PolymarketConnector()
        await polymarket.connect()
    else:
        polymarket = None  # py-clob-client dep skew; wiki + OpenBB still functional
    openbb = OpenBBAdapter() if OpenBBAdapter is not None else None
    risk_protections = RiskProtections(db_manager=db_manager)
    model_drawer = ModelDrawer(model_dir=str(db_manager._db_path.parent / "models"))
    arb_scout = None  # Initialized after data_manager

    # Needs analyst for the bridge, assuming news_analyst is initialized later or available
    # For now, initialize stub if news_analyst is not yet ready
    sentiment_bridge = SentimentBridge(news_analyst=None)

    # Inject into API registry
    inject_super_engine(
        {"polymarket": polymarket, "openbb": openbb, "sentiment_bridge": sentiment_bridge}
    )

    logger.info(
        "✅ Super-Engine components initialized (Polymarket, OpenBB, Protections, SentimentBridge)"
    )

    # Paper IB connector — Instance creation (connection moved to background)
    ib_paper_connector = None
    if settings.PAPER_TRADING:
        from execution.order_gateway_factory import build_order_gateway

        # P0-2: simulator by default; the real IBGatewayManager (port 4002 paper)
        # only when IB_PAPER_BROKER_ENABLED is set. Same variable + duck-typed
        # interface, so the connect/attach wiring below is unchanged either way.
        ib_paper_connector = build_order_gateway(settings, safety_layer, paper_tracker)

    order_manager = IBOrderManager(
        safety_layer=safety_layer,
        ib_gateway=ib_paper_connector,
        portfolio_tracker=paper_tracker,
    )
    logger.info("✅ IBOrderManager initialized")

    # Wire IBKR into the order router now that it is available
    if ib_paper_connector is not None:
        order_router.attach_ibkr(ib_paper_connector)

    # HB-4: Position Reconciliation on Restart
    if ib_paper_connector is not None:
        from execution.position_reconciler import PositionReconciler

        # Load existing state into OMS first
        if oms_manager:
            await oms_manager.reload_from_db(db_manager)

        reconciler = PositionReconciler(ib_paper_connector, oms_manager=oms_manager)
        asyncio.create_task(reconciler.reconcile())
        logger.info(
            "✅ PositionReconciler initialized and scheduled to check for orphaned positions"
        )

    # Schwab connector — Instance creation (initialization moved to background)
    schwab_connector = None
    if settings.SCHWAB_APP_KEY and settings.SCHWAB_APP_SECRET:
        schwab_connector = SchwabConnector(settings, safety_layer)

    set_schwab_connector(schwab_connector)
    # Inject the fully-wired order_router and safety_layer into the orders_router API bridge.
    # safety_layer is required so futures orders route through SafetyLayer.submit_paper_order()
    # rather than bypassing risk checks via OrderRouter.route_order() directly.
    inject_orders_deps(order_router, safety_layer=safety_layer)
    logger.info(
        "✅ OrderRouter ready — IBKR: %s | Schwab: %s",
        "connected" if order_router.ibkr else "not wired",
        "connected" if (schwab_connector and schwab_connector.is_connected) else "not connected",
    )

    # Market data connections — Instance creation (initialization moved to background)
    data_manager = MarketDataManager(settings)
    set_analytics_data_manager(data_manager)
    set_options_data_manager(data_manager)
    # Wire the data manager into SafetyLayer so submit_paper_order() can run the
    # entry-price-sanity check on client-supplied limit prices (2026-08-03 incident —
    # see the price-sanity block in SafetyLayer.submit_paper_order()).
    safety_layer.attach_data_manager(data_manager)
    set_decisions_data_manager(data_manager)
    # Wire the real-price source into the paper connector so simulated fills use
    # the live get_tick_price waterfall instead of static mock quotes. Without
    # this, unlisted symbols (e.g. MGC) filled at the 100.5 sentinel and poisoned
    # paper_trades. (2026-06-22 paper-fill integrity fix.)
    from execution.order_gateway_factory import wire_paper_price_source

    if wire_paper_price_source(ib_paper_connector, data_manager):
        logger.info("✅ Paper connector: real-price source wired (get_tick_price)")
    # Re-inject with data_manager now available so /orders/status can fall back to
    # data_manager.ibkr for IBKR connected-state when safety_layer has no gateway attached.
    inject_orders_deps(order_router, safety_layer=safety_layer, data_manager=data_manager)

    # ── OMS v2 (Phase 2.3) ──────────────────────────────────────────────────
    from execution.oms_v2 import OMSManager

    oms_manager = OMSManager(order_router, ib_order_manager=order_manager)
    logger.info("✅ OMS v2 initialized (Bracket & OCO management active)")

    # Start PolygonStreamer background task if available
    if data_manager.polygon_streamer:
        asyncio.create_task(data_manager.polygon_streamer.connect())
        logger.info("✅ Polygon Streamer background task started")

    # Now that data_manager is ready, inject the IB gateway into PnLMonitor
    # so the circuit breakers can read live account data from IBKR when connected.
    if pnl_monitor is not None and data_manager.ibkr is not None:
        pnl_monitor._ib = data_manager.ibkr
        logger.info("✅ PnL Monitor: IB Gateway wired (live account data source active)")

    _margin_connector = ib_paper_connector or data_manager.ibkr
    if margin_monitor is not None and _margin_connector is not None:
        margin_monitor._connector = _margin_connector
        asyncio.create_task(margin_monitor.run_loop())
        logger.info("✅ Margin Monitor: broker connector wired and background loop started")

    # Wire Schwab into MarketDataManager as Tier 2 price source (equities/options quotes)
    if schwab_connector is not None and schwab_connector.is_connected:
        data_manager.inject_schwab(schwab_connector)
        logger.info("✅ Schwab wired into MarketDataManager as Tier 2 price source")

    # Wire thinkorswim RTD into MarketDataManager as Tier 0 (broker-direct quotes
    # for MES/SPY/QQQ/VIX via thinkorswim's own RTD COM server, which proxies to
    # its TCP listener on 127.0.0.1:12001). Read-only source — no order path.
    # Injection is cheap; the session itself is brought up in the background so
    # startup never blocks on COM. Absent TOS / pywin32 it degrades to Tier 0
    # inactive with the waterfall unchanged.
    #
    # The bring-up MUST stay on the event-loop thread: RTDService.dll registers
    # no ThreadingModel, so COM treats it as Apartment-threaded and the object
    # must be created in the process's first apartment. Moving this to a worker
    # thread makes ServerStart hang forever with no exception (see the THREADING
    # section of data/tos_rtd_adapter.py). The wait_for is a bound on the await,
    # not a fix for that.
    tos_rtd_connector = None
    try:
        from data.tos_rtd_adapter import TOSRTDConnector

        tos_rtd_connector = TOSRTDConnector()
        data_manager.inject_tos_rtd(tos_rtd_connector)
        # Expose the derived-indicator engine over /tos/indicators (ATR, Keltner,
        # multi-TF S/R, day-range gauge). Injected here so the router sees the
        # same connector instance the waterfall uses.
        inject_tos_deps(tos_rtd_connector)
        logger.info("✅ thinkorswim RTD wired into MarketDataManager as Tier 0 price source")

        async def _bring_up_tos_rtd(connector):
            try:
                if await asyncio.wait_for(connector.connect(), timeout=30):
                    logger.info("✅ thinkorswim RTD session live (Tier 0 active)")
                else:
                    logger.info(
                        "thinkorswim RTD session not started — Tier 0 inactive, "
                        "waterfall unchanged"
                    )
            except Exception as _rtd_bringup_err:  # noqa: BLE001 — never fatal
                logger.warning("thinkorswim RTD bring-up failed (non-fatal): %s", _rtd_bringup_err)

        asyncio.create_task(_bring_up_tos_rtd(tos_rtd_connector))
    except Exception as _tos_err:
        logger.warning("thinkorswim RTD connector unavailable (non-fatal): %s", _tos_err)
        tos_rtd_connector = None

    # JARVIS Super-Engine: Initialize ArbScout and RegimeGuard once data_manager is ready
    arb_scout = ArbScout(polymarket_connector=polymarket, data_manager=data_manager)
    regime_guard = RegimeGuard(data_manager=data_manager)

    # Add initial pairs for cross-market monitoring
    arb_scout.add_pair("0x...", "MES")

    # Update super-engine injection with all components now ready
    inject_super_engine(
        {
            "polymarket": polymarket,
            "openbb": openbb,
            "sentiment_bridge": sentiment_bridge,
            "model_drawer": model_drawer,
            "arb_scout": arb_scout,
            "regime_guard": regime_guard,
        }
    )

    inject_institutional_data_manager(data_manager)

    # Agents (need LLM client)
    llm_provider = os.getenv("JARVIS_LLM_PROVIDER", "ollama").strip().lower()
    llm_enabled = llm_provider == "ollama" or bool(settings.ANTHROPIC_API_KEY)
    if llm_enabled:
        from llm.memory_bridge import MemoryBridge

        llm_client = JarvisLLMClient(
            api_key=settings.ANTHROPIC_API_KEY or "ollama-local",
            db_manager=db_manager,
        )
        memory_bridge = MemoryBridge(db_manager)
        direct_anthropic_key = settings.ANTHROPIC_API_KEY
        if getattr(llm_client, "provider", "").lower() == "ollama":
            os.environ["ANTHROPIC_API_KEY"] = ""
            direct_anthropic_key = ""
            logger.info("✅ Ollama mode active — direct Anthropic call sites disabled at runtime")

        # Startup assertion — fail loud if the client is missing required interface
        _required_methods = ["call"]
        _missing = [m for m in _required_methods if not callable(getattr(llm_client, m, None))]
        if _missing:
            raise RuntimeError(
                f"LLM client {type(llm_client).__name__} is missing required methods: {_missing}. "
                "Check llm/client.py — agents will silently HOLD without this."
            )
        logger.info(f"✅ LLM client validated: {type(llm_client).__name__} has {_required_methods}")

        # Initialize inference router (Ollama primary, Anthropic fallback)
        get_inference_router()
        # Note: test_connection() moved to background to save ~500ms

        # ── Portfolio Capital Allocator (Phase 8.1) ──────────────────────────
        from execution.portfolio_allocator import PortfolioAllocator

        portfolio_allocator = PortfolioAllocator(db_manager)
        # Note: calculate_allocations() moved to background to save ~2-5s

        # Stage 1: Analysts
        technical_analyst = TechnicalAnalystAgent(llm_client, data_manager)

        # Wire Brave Search into news analyst if key is configured
        _brave_client = None
        _brave_api_key: str | None = getattr(settings, "BRAVE_API_KEY", None)
        if _brave_api_key:
            from data.brave_search import BraveSearchClient

            _brave_client = BraveSearchClient(api_key=_brave_api_key)
            logger.info("✅ Brave Search wired into news analyst")
        else:
            logger.warning("BRAVE_API_KEY not set — news analyst running without live web search")

        news_agent = NewsAnalystAgent(llm_client, data_manager, brave_client=_brave_client)
        # Wire live analyst into sentiment bridge
        if sentiment_bridge:
            sentiment_bridge.analyst = news_agent
            logger.info("✅ Sentiment Bridge wired into News Analyst")
        social_agent = SocialAnalystAgent(llm_client)
        fundamental_agent = FundamentalistAgent(llm_client, data_manager)
        corey_agent = CoreyAuctionAnalystAgent(llm_client=llm_client)

        # Stage 2: Debate
        bull_agent = BullResearcherAgent(api_key=direct_anthropic_key, memory_bridge=memory_bridge)
        bear_agent = BearResearcherAgent(api_key=direct_anthropic_key, memory_bridge=memory_bridge)
        debate_agent = DebateOrchestrator()

        # Stage 3/4: Risk & Fund Management
        risk_agent = RiskManagerAgent(llm_client)
        fund_agent = FundManagerAgent(llm_client)

        # Stage 5: Trader (Phase 8.1)
        trader_agent = TraderAgent(
            llm_client,
            db_manager=db_manager,
            memory_bridge=memory_bridge,
            portfolio_allocator=portfolio_allocator,
        )

        # Stage 1 Enrichment
        breakout_analyst = BreakoutAgent(data_manager)
        harmonic_analyst = HarmonicAgent(data_manager)

        logger.info("✅ All 13 trading agents initialized (incl. Corey, Breakout, Harmonics)")

        # Shadow Mode Tracker — logs 'would-be' trades for blocklisted instruments
        shadow_tracker = ShadowModeTracker(db_manager)

        # Trading Pipeline — all agents wired
        trading_pipeline = TradingPipeline(
            agents={
                "technical": technical_analyst,
                "news": news_agent,
                "social": social_agent,
                "fundamental": fundamental_agent,
                "corey": corey_agent,
                "breakout": breakout_analyst,
                "harmonic": harmonic_analyst,
                "bull": bull_agent,
                "bear": bear_agent,
                "debate": debate_agent,
                "trader": trader_agent,
                "risk_manager": risk_agent,
                "fund_manager": fund_agent,
            },
            safety_layer=safety_layer,
            db_manager=db_manager,
            shadow_tracker=shadow_tracker,
            memory_bridge=memory_bridge,
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

        # Trade Review Service — post-trade LLM analysis
        try:
            from analytics.trade_review import init_review_service

            init_review_service(llm_client, db_manager)
            inject_trades_deps(db_manager, llm_client)
            inject_journal_review_deps(db_path=settings.SQLITE_DB_PATH, llm=llm_client)
            logger.info("✅ Trade Review Service initialised — post-trade LLM grading active")
        except Exception as _rv_init_exc:
            logger.warning("⚠️  Trade Review Service init failed (non-fatal): %s", _rv_init_exc)
    else:
        logger.warning(
            "⚠️  No local/provider LLM configured — LLM agents disabled. Set JARVIS_LLM_PROVIDER=ollama or configure a hosted key."
        )

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
        symbols_to_scan = [(sym, True) for sym in settings.FUTURES_WATCHLIST] + [  # MES, MNQ, MCL
            (sym, False) for sym in settings.OPTIONS_WATCHLIST[:3]  # SPY, QQQ, AAPL
        ]

        logger.info(f"Scheduled scan: {[s[0] for s in symbols_to_scan]}")

        async def _analyze_and_alert(symbol: str, is_futures: bool) -> None:
            import time as _time_mod

            # ── Scanner guards (added 2026-04-10) ────────────────────────
            # Guard 1: Already-open position check. Prevents duplicate trades
            # like the 2026-04-10 incident where MES shorts #108/#109/#110 were
            # created on consecutive hourly scans against identical bogus prices.
            try:
                import sqlite3 as _sqlite3

                def _check_open_position():
                    with _sqlite3.connect(settings.SQLITE_DB_PATH) as _conn:
                        return _conn.execute(
                            "SELECT id, side FROM paper_trades WHERE symbol=? AND status='open' LIMIT 1",
                            (symbol,),
                        ).fetchone()

                _existing = await asyncio.to_thread(_check_open_position)
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
                    "MCL": (40.0, 130.0),  # WTI crude: ~$60-100 typical
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
                # Real/intended fill price for the OMS bracket call below. MUST
                # NOT fall back to stop_price: stop_price is not a price proxy,
                # and using it here silently defeats SafetyLayer's per-trade
                # dollar-risk gate (points_at_risk = |entry - stop| collapses to
                # ~0 when entry == stop). trade_dec["entry_price"] is the
                # Trader agent's actual intended entry (see TradeDecision.
                # entry_price docstring in agents/trader.py); limit_price wins
                # only when this is a genuine LMT order, since that IS the
                # price that will be submitted.
                # Root-cause of trade #287 (MGC, 2026-07-xx): this used to be
                # `trade_dec.get("limit_price") or trade_dec.get("stop_price")`,
                # so a MKT order (no limit_price) always priced its bracket
                # entry at the stop, approving trades already ~$191.83 over the
                # $50/ticket MAX_TRADE_LOSS_USD cap before any market movement.
                price_info = trade_dec.get("limit_price") or trade_dec.get("entry_price")
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

                    # ── OMS v2 Execution (Phase 2.3) ──
                    if oms_manager and action.lower() in ("buy", "sell"):
                        try:
                            if trade_dec.get("is_spread"):
                                await oms_manager.execute_options_spread(
                                    symbol=symbol,
                                    spread_type=trade_dec.get("type")
                                    or trade_dec.get("spread_type")
                                    or "BULL_PUT_SPREAD",
                                    short_opt=trade_dec.get("short_option_symbol"),
                                    long_opt=trade_dec.get("long_option_symbol"),
                                    quantity=qty,
                                    net_credit=trade_dec.get("net_credit", 0.0),
                                )
                            else:
                                await oms_manager.execute_bracket(
                                    symbol=symbol,
                                    action=action,
                                    quantity=qty,
                                    entry_price=float(price_info or 0.0),
                                    stop_loss=trade_dec.get("stop_price"),
                                    take_profit=trade_dec.get("target_price"),
                                    entry_type="MKT" if not trade_dec.get("limit_price") else "LMT",
                                )
                        except Exception as oms_exc:
                            logger.error(
                                "[Scheduler] OMS execution failed for %s: %s", symbol, oms_exc
                            )

                    # Multi-channel fan-out (Telegram/Discord/WhatsApp/toast).
                    # Shared cooldown dedupes vs the in-pipeline broadcast.
                    from notifications.signal_broadcast import broadcast_signal

                    await broadcast_signal(symbol, result, source="scheduler")
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
    if llm_enabled:
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

            # HB-3: Decouple initial scan from lifespan (<10s boot constraint)
            async def delayed_watchlist_scan():
                await asyncio.sleep(10)
                # Only run during scheduled market hours (Mon-Fri 9:00-15:59 CT).
                # Without this gate the watchdog-restart cycle fires a full
                # 9-analyst LLM pipeline run at 3 AM, which saturates the event loop
                # and trips the watchdog again within 5-10 minutes.
                try:
                    from zoneinfo import ZoneInfo

                    _ct = ZoneInfo("America/Chicago")
                    _now = datetime.now(_ct)
                    if _now.weekday() >= 5 or not (9 <= _now.hour < 16):
                        logger.info(
                            "⏰ Skipping delayed initial scan — outside market hours (%s CT)",
                            _now.strftime("%H:%M %a"),
                        )
                        return
                except Exception:
                    pass  # ZoneInfo unavailable — fall through and run anyway
                logger.info("⏰ Running delayed initial watchlist scan (10s post-boot)")
                try:
                    await run_watchlist_analysis()
                except Exception as e:
                    logger.error(f"Initial watchlist scan failed: {e}")

            asyncio.create_task(delayed_watchlist_scan())
        else:
            logger.warning(
                "⛔ WATCHLIST_SCAN_ENABLED=false — hourly watchlist auto-scan is DISABLED. "
                "Re-enable in .env after data layer + scanner guards are verified."
            )

        # ── Approval Expiry Background Job (Phase 1 Protection) ──────────
        async def run_approval_expiry():
            """Auto-cancel pending trades older than 5 minutes."""
            from approval.service import cancel_expired_approvals

            try:
                cancelled = cancel_expired_approvals(db_manager)
                if cancelled > 0:
                    logger.info(f"⏰ Auto-expired {cancelled} stale approval(s)")
            except Exception as e:
                logger.error(f"Approval expiry job failed: {e}")

        scheduler.add_job(
            run_approval_expiry,
            "interval",
            minutes=1,
            id="approval_expiry",
            name="Auto-expire stale approvals",
            max_instances=1,
        )
        logger.info("⏰ Approval expiry job registered (every 1m)")

        # Delayed run for approval expiry (don't wait 1m for first check)
        async def delayed_approval_expiry():
            await asyncio.sleep(5)
            await run_approval_expiry()

        asyncio.create_task(delayed_approval_expiry())

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

    # MGC was eliminated in the 2026-06-26 honest re-gate (all 5 variants FAIL, paper
    # disabled). This daily scanner writes pending ENTRY_NOW signals to pending_signals.json
    # and fires WhatsApp alerts -- actionable noise/risk for an untradeable symbol. Gate it
    # OFF by default; set MGC_DAILY_SCANNER_ENABLED=1 to restore the daily watch.
    _mgc_daily_enabled = os.environ.get("MGC_DAILY_SCANNER_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if _mgc_daily_enabled:
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

        # Defense-in-depth (2026-05-07): cross-check PAPER_CONFIGS enabled flag
        # AND DO_NOT_TRADE_SYMBOLS before dispatching. This catches future drift
        # where a config gets re-enabled for a symbol that's still blocked
        # at the verdict layer (root cause of the MNQ 55-trade wiring leak,
        # commit 0772e20 — paper_config had enabled=True, dispatcher didn't
        # cross-check the DO_NOT_TRADE blocklist).
        from backtest.paper_config import PAPER_CONFIGS
        from backtest.signals import DO_NOT_TRADE_SYMBOLS as _DO_NOT_TRADE

        _active_1h = []
        for _sym, _cfg in PAPER_CONFIGS.items():
            if not _cfg.get("enabled", False):
                continue
            if _sym in _DO_NOT_TRADE:
                logger.warning(
                    "[MARKET_OPEN] BLOCKED: %s has enabled=True in PAPER_CONFIGS "
                    "but is in DO_NOT_TRADE_SYMBOLS — skipping signal dispatch. "
                    "Fix: set enabled=False in paper_config.py for this symbol.",
                    _sym,
                )
                continue
            _active_1h.append((_sym, True))

        instruments_1h = _active_1h
        instruments_15m = [("MCL", "15m"), ("MNQ", "15m")]
        if instruments_1h:
            logger.info(
                "[MARKET_OPEN] Starting parallel 1h+15m scans for: %s",
                ", ".join(s for s, _ in instruments_1h),
            )
        else:
            logger.info("[MARKET_OPEN] No enabled+ungated 1h instruments — skipping 1h scan")

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
                # Defense-in-depth: also block DO_NOT_TRADE symbols even if
                # config.enabled is True (prevents wiring-leak class of bug).
                from backtest.signals import DO_NOT_TRADE_SYMBOLS as _DO_NOT_TRADE_15M

                if symbol in _DO_NOT_TRADE_15M:
                    logger.warning(
                        "[MARKET_OPEN] BLOCKED 15m: %s enabled=True but in "
                        "DO_NOT_TRADE_SYMBOLS — skipping. Fix paper_config.py.",
                        symbol,
                    )
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

            if safety_layer and safety_layer.get_status().get("is_killed"):
                logger.info("[INTRADAY_15M] Skipping — kill switch active")
                return

            from backtest.signals import DO_NOT_TRADE_SYMBOLS as _DO_NOT_TRADE_INTRA

            loader = BacktestDataLoader()
            for symbol in ["MCL", "MNQ"]:
                try:
                    config = FIFTEEN_MIN_CONFIGS.get(symbol)
                    if not config or not config.get("enabled"):
                        continue
                    # Defense-in-depth: block DO_NOT_TRADE symbols even if
                    # config.enabled slips back to True (wiring-leak prevention).
                    if symbol in _DO_NOT_TRADE_INTRA:
                        logger.warning(
                            "[INTRADAY_15M] BLOCKED: %s enabled=True but in "
                            "DO_NOT_TRADE_SYMBOLS — skipping. Fix paper_config.py.",
                            symbol,
                        )
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
        market_price_fn=data_manager.get_current_price if data_manager is not None else None,
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
        logger.info("✅ AlertManager started — P&L push alerts active via OpenClaw WhatsApp")
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
    inject_macro_deps(data_manager=data_manager)
    from routers.market_router import inject_dependencies as inject_market_deps

    inject_market_deps(data_manager=data_manager)
    inject_brokers_deps(
        ibkr=ib_paper_connector,
        schwab=schwab_connector,
        tracker=paper_tracker,
        data_manager=data_manager,
        db_path=str(db_manager._db_path),
    )
    inject_approval_deps(safety_layer, paper_tracker, db_manager)
    inject_actionable_deps(db_manager)
    inject_signal_outcomes_deps(db_manager, data_manager)
    inject_analysis_deps(technical_analyst, data_manager, cost_tracker)
    inject_regime_deps(data_manager)
    inject_watchlist_deps(db_manager, data_manager=data_manager)
    inject_sentiment_deps(data_manager)
    inject_settings_deps(settings, db_manager, safety_layer)
    inject_prices_deps(PriceCache(), data_manager=data_manager)
    inject_auction_bias_deps(LiveAuctionDataProvider(data_manager))
    inject_websocket_deps(ws_manager)
    inject_thinkscript_deps(technical_analyst)
    inject_alerts_deps(db_manager=db_manager)

    # ── Autonomous Pipeline Approval Queue ────────────────────────────────────
    # Default-OFF: only activated when ENABLE_AUTONOMOUS_PIPELINE=1 in .env.
    # The router is always registered (serves /approvals/* to review the queue).
    # The background loop is only started when the flag is explicitly set.
    inject_approval_queue_deps(
        safety_layer,
        db_path=str(db_manager._db_path),
        paper_tracker=paper_tracker,
    )
    logger.info("✅ Approval queue router wired (prefix=/approvals)")
    inject_openclaw_deps(db_manager, paper_tracker, safety_layer)
    logger.info("✅ OpenClaw webhook router wired (prefix=/openclaw)")

    _autonomous_enabled_at_boot = os.environ.get("ENABLE_AUTONOMOUS_PIPELINE", "0").strip() == "1"
    if _autonomous_enabled_at_boot:
        from scheduler.pipeline_autonomous import inject_autonomous_deps, run_autonomous_loop

        inject_autonomous_deps(
            trading_pipeline=trading_pipeline,
            safety_layer=safety_layer,
            db_path=str(db_manager._db_path),
            data_manager=data_manager,
        )
        _tick_interval = int(os.environ.get("AUTONOMOUS_TICK_SECONDS", "300"))
        asyncio.create_task(run_autonomous_loop())
        logger.info(
            "⏰ Autonomous pipeline loop started — tick=%ds "
            "(ENABLE_AUTONOMOUS_PIPELINE=1 detected at boot)",
            _tick_interval,
        )
    else:
        logger.info(
            "Autonomous pipeline scheduler: DISABLED "
            "(ENABLE_AUTONOMOUS_PIPELINE not set or =0 — default-off)"
        )

    # ── Discord Reaction Watcher — approval/reject/extend via emoji ───────────
    # Default-OFF: no-ops gracefully if DISCORD_PERSONAL_BOT_TOKEN or
    # DISCORD_PERSONAL_USER_ID are absent from .env.
    _reaction_watcher_task = None
    try:
        from discord.reaction_watcher import (
            is_reaction_watcher_enabled,
            watch_approval_reactions,
        )

        if is_reaction_watcher_enabled():
            _reaction_watcher_task = asyncio.create_task(watch_approval_reactions())
            logger.info(
                "Discord reaction watcher started — emoji reactions on bot-posted "
                "approval messages will call /approvals/{id}/approve|reject|extend"
            )
        else:
            logger.info(
                "Discord reaction watcher: DISABLED "
                "(DISCORD_PERSONAL_BOT_TOKEN or DISCORD_PERSONAL_USER_ID not set)"
            )
    except Exception as _rw_err:
        logger.warning("Discord reaction watcher init failed (non-fatal): %s", _rw_err)

    inject_scheduler_router_scheduler(scheduler)
    inject_pipeline_deps(
        scheduler,
        trading_pipeline,
        safety_layer,
        db_manager,
        paper_tracker,
        sdk_pipeline,
        data_manager=data_manager,
    )
    inject_messaging_deps(db_manager, paper_tracker=paper_tracker, safety_layer=safety_layer)
    inject_session_brief_deps(db_manager)
    # Morning brief deps
    inject_morning_brief_deps(data_manager, paper_tracker, safety_layer)
    inject_hp_deps(data_manager, settings)

    # Initialize Signal Scanner
    try:
        from scanner.signal_scanner import SignalScanner

        # Use FUTURES_WATCHLIST from settings so MES, MGC are included, and add
        # OPTIONS_WATCHLIST equities (QQQ, AAPL, SPY, TSLA) so equity signals
        # become real paper trades too. The scanner prices/analyzes each symbol
        # with the correct asset class via set_futures_symbols() below.
        _futures_syms = (
            list(settings.FUTURES_WATCHLIST) if settings.FUTURES_WATCHLIST else ["MCL", "MNQ"]
        )
        _equity_syms = list(getattr(settings, "OPTIONS_WATCHLIST", []) or [])
        _scan_symbols = _futures_syms + _equity_syms
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
        # Inject safety layer (kill-switch gate) + data manager (entry-price
        # sanity / phantom-price guard) so the autonomous live opener enforces
        # both before booking a paper trade. Without these the scanner loop had
        # no kill-switch check and no price-sanity gate.
        if safety_layer is not None:
            signal_scanner.set_safety_layer(safety_layer)
            logger.info("Signal scanner: safety_layer injected (kill-switch gate)")
        if data_manager is not None:
            signal_scanner.set_data_manager(data_manager)
            logger.info("Signal scanner: data_manager injected (entry-price sanity)")
        # Declare which scanned symbols are futures; the rest are priced as equities.
        signal_scanner.set_futures_symbols(_futures_syms)
        if _equity_syms:
            logger.info("Signal scanner: equity execution enabled for %s", _equity_syms)
        inject_scanner_deps(signal_scanner)
        if settings.WATCHLIST_SCAN_ENABLED:
            asyncio.create_task(signal_scanner.start())
            logger.info(
                "Signal scanner queued as background task (symbols=%s, 60-min interval)",
                _scan_symbols,
            )
        else:
            logger.warning(
                "⛔ Signal scanner initialized but NOT started because "
                "WATCHLIST_SCAN_ENABLED=false"
            )
    except Exception as e:
        logger.warning("Signal scanner failed to queue: %s (non-fatal)", e)

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

    # Initialize Weekly Adaptive Calibration (Saturday 00:00)
    try:
        from backtest.auto_calibrate import run_weekly_calibration

        scheduler.add_job(
            run_weekly_calibration,
            CronTrigger(day_of_week="sat", hour=0, minute=0, timezone="America/Chicago"),
            id="weekly_adaptive_calibration",
            name="Weekly Adaptive Walk-Forward Calibration",
            max_instances=1,
            misfire_grace_time=3600,
        )
        logger.info("⏰ Weekly Adaptive Calibration registered — runs Saturdays at 00:00 CT")
    except Exception as _calib_err:
        logger.warning(f"Failed to register weekly calibration (non-fatal): {_calib_err}")

    # Initialize Database Backup (nightly at 23:30 UTC)
    try:
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
                        _decision = await _sup.review(
                            SupervisorEvent(
                                event_type="morning_brief",
                                payload={"length": len(brief_text), "preview": brief_text[:500]},
                            )
                        )
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
                result = await clusterer.cluster_recent(lookback_days=7, force_refresh=True)
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
            logger.info("✅ Bookmark clusterer registered — fires Sun at 18:00 CT")
    except Exception as _bm_err:
        logger.warning(f"Bookmark clusterer init failed (non-fatal): {_bm_err}")

    # Daily bookmark vault render — writes any missing Discord bookmarks to
    # second-brain/wiki/discord-bookmarks/ so agents and the human both have
    # an Obsidian-linkable page for every URL dropped in #general. Catch-up
    # mode: existing files are skipped (preserves 2026-04-17 manual triage).
    try:
        from scripts.render_bookmarks_to_vault import render_vault as _render_vault
        from vault.paths import vault_root as _vault_root

        _BOOKMARK_DB_PATH = os.environ.get("JARVIS_TRADER_DB_PATH", "engine/data/jarvis_trader.db")
        # Default under the canonical vault root (honours JARVIS_VAULT_ROOT) instead
        # of a hardcoded absolute path, so bookmarks land beside the other vault
        # writers. Explicit BOOKMARK_VAULT_DIR still overrides.
        _BOOKMARK_VAULT_DIR = os.environ.get(
            "BOOKMARK_VAULT_DIR",
            str(_vault_root() / "discord-bookmarks"),
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
                logger.error("[BookmarkVaultRender] daily render failed: %s", exc, exc_info=True)

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
            logger.info("✅ Bookmark vault renderer registered — fires daily 03:00 CT")
    except Exception as _bvr_err:
        logger.warning(f"Bookmark vault renderer init failed (non-fatal): {_bvr_err}")

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
                from datetime import datetime
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
                    logger.debug("[CoreyStale] OK — last msg %.1f days ago", days_stale)
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
            """Push JARVIS paper-trade P&L to SafetyLayer circuit breakers.

            Reads daily PnL directly from paper_trades (trades closed today),
            not from pnl_monitor.  pnl_monitor reads IBKR DUP662235 demo
            account data (pre-seeded NAV $3.97M) whose daily swing contaminates
            the daily_pnl SQLite table and causes false kill-switch fires.
            2026-06-01 incident: -$678k IBKR demo delta fired kill switch on a
            real -$1,284 scanner paper trade.

            T0-02 fix (2026-07-09 dashboard-integrity audit): the 2026-06-01
            patch above passed sync_from_broker() a static
            ``INITIAL_CAPITAL`` as "equity" every 60s, with no cumulative P&L
            added back in.  Since equity never varied call-to-call,
            ``_current_equity``/``_equity_peak`` — and every
            Sharpe/Sortino/Calmar/max-DD figure derived from them via
            pnl_snapshots.portfolio_equity — were frozen at exactly $10,000.00
            from 2026-06-02 onward, even though daily_pnl (and real trading)
            moved normally.  Equity must be initial capital PLUS all-time
            realized P&L, mirroring the same cash-basis (realized-only)
            accounting ``daily_pnl.ending_balance`` already uses.
            """
            try:
                if safety_layer is None:
                    return
                today_str = date.today().isoformat()
                paper_daily_pnl = 0.0
                total_realized_pnl = 0.0
                if db_manager is not None:
                    try:
                        closed_today = [
                            t
                            for t in db_manager.get_closed_trades(limit=200)
                            if (t.get("exit_time") or "").startswith(today_str)
                        ]
                        paper_daily_pnl = sum(float(t.get("pnl") or 0.0) for t in closed_today)
                    except Exception as _db_exc:
                        logger.warning(
                            "[sync_safety_equity] paper_trades query failed: %s", _db_exc
                        )
                    try:
                        stats = db_manager.get_stats_summary()
                        total_realized_pnl = float(stats.get("total_pnl") or 0.0)
                    except Exception as _stats_exc:
                        logger.warning(
                            "[sync_safety_equity] get_stats_summary failed (equity will "
                            "fall back to initial capital only): %s",
                            _stats_exc,
                        )
                config_equity = float(getattr(settings, "INITIAL_CAPITAL", 10_000.0))
                current_equity = config_equity + total_realized_pnl
                safety_layer.sync_from_broker(current_equity, paper_daily_pnl)
                logger.debug(
                    "[sync_safety_equity] equity=%.2f (initial=%.2f + "
                    "realized=%.2f) daily_pnl=%.2f source=paper_trades today=%s",
                    current_equity,
                    config_equity,
                    total_realized_pnl,
                    paper_daily_pnl,
                    today_str,
                )
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

    # Open position stop monitor — closes scanner-opened paper_trades when
    # stop_loss is breached.  Runs every 5 minutes.
    # Fixes the 2026-06-01 incident where MGC trade #178 rode -128 pts
    # (stop was 6.4 pts) because scanner-opened trades had no stop poller.
    try:

        async def _monitor_open_stops() -> None:
            """Close open paper_trades whose stop_loss price has been breached."""
            try:
                if db_manager is None or data_manager is None:
                    return
                open_trades = db_manager.get_open_trades()
                if not open_trades:
                    return
                from portfolio.tracker import (
                    _resolve_multiplier as _resolve_mult_fn,
                    UnknownInstrumentMultiplierError as _UnknownMultErr,
                    _commission_per_contract as _commission_per_contract_fn,
                )  # noqa: E501

                for _trade in open_trades:
                    _stop = _trade.get("stop_loss")
                    _sym = (_trade.get("symbol") or "").upper()
                    if _stop is None:
                        # OMS v2 bracket-executed trades never persist
                        # stop_loss onto the paper_trades row
                        # (PortfolioTracker.open_trade() has no stop_loss
                        # parameter -- a separate, documented data-hygiene
                        # gap, out of scope here). Fall back to the OMS's own
                        # in-memory bracket record, which DOES hold the real
                        # stop_loss_price from execute_bracket() time.
                        if oms_manager is not None and _sym:
                            try:
                                _stop = oms_manager.resolve_stop_for_symbol(_sym)
                            except Exception as _oms_fb_exc:
                                logger.debug(
                                    "[stop_monitor] OMS stop fallback failed for %s: %s",
                                    _sym,
                                    _oms_fb_exc,
                                )
                        if _stop is None:
                            continue
                    _stop_f = float(_stop)
                    if not _sym:
                        continue
                    _side = (_trade.get("side") or "buy").lower()
                    _entry = float(_trade.get("entry_price") or 0.0)
                    _tid = _trade.get("trade_id", "")
                    _is_fut_sm = _sym in {
                        str(x).upper() for x in (settings.FUTURES_WATCHLIST or [])
                    }
                    try:
                        _pd = await data_manager.get_current_price(_sym, is_futures=_is_fut_sm)
                        _cur = float(
                            _pd.get("last_price")
                            or _pd.get("price")
                            or _pd.get("last")
                            or _pd.get("close")
                            or 0.0
                        )
                        if not _cur:
                            continue
                    except Exception as _pe:
                        logger.debug("[stop_monitor] price fetch %s: %s", _sym, _pe)
                        continue
                    _is_long = "buy" in _side
                    _hit = (_is_long and _cur <= _stop_f) or (not _is_long and _cur >= _stop_f)
                    if not _hit:
                        continue
                    try:
                        _mult = _resolve_mult_fn(_sym)
                    except _UnknownMultErr:
                        logger.error(
                            "[stop_monitor] no contract multiplier for %s -- "
                            "skipping stop close to avoid mis-stated P&L",
                            _sym,
                        )
                        continue
                    _qty = float(_trade.get("quantity") or 1.0)
                    _gross_pnl = (
                        (_stop_f - _entry) * _qty * _mult
                        if _is_long
                        else (_entry - _stop_f) * _qty * _mult
                    )
                    # T0-06: reuse PortfolioTracker's exact commission constant/logic
                    # (portfolio.tracker._commission_per_contract) instead of passing a
                    # zero-commission pnl straight through — close_paper_trade() treats
                    # an explicit `pnl` as broker-confirmed (already net of fees) and
                    # will NOT re-deduct it, so an un-costed figure here previously
                    # closed every stop-driven trade commission-free.
                    _pnl = _gross_pnl - (_commission_per_contract_fn() * abs(_qty))
                    logger.warning(
                        "[stop_monitor] STOP HIT %s %s id=%s entry=%.2f "
                        "stop=%.2f current=%.2f pnl=%.2f (net of commission)",
                        _sym,
                        _side,
                        _tid[:8] if _tid else "?",
                        _entry,
                        _stop_f,
                        _cur,
                        _pnl,
                    )
                    _closed = False
                    if paper_tracker is not None:
                        try:
                            paper_tracker.close_paper_trade(
                                trade_id=_tid,
                                exit_price=_stop_f,
                                pnl=_pnl,
                            )
                            _closed = True
                        except KeyError:
                            pass
                    if not _closed:
                        db_manager.close_trade(
                            trade_id=_tid,
                            exit_price=_stop_f,
                            pnl=_pnl,
                            notes="stop_monitor: stop_loss breached",
                        )
            except Exception as exc:
                logger.warning("[stop_monitor] error: %s", exc, exc_info=True)

        if scheduler is not None:
            scheduler.add_job(
                _monitor_open_stops,
                "interval",
                minutes=5,
                id="monitor_open_stops",
                name="Open Position Stop Monitor",
                max_instances=1,
                replace_existing=True,
            )
            logger.info("✅ Stop monitor job registered — fires every 5 minutes")
    except Exception as _stop_mon_err:
        logger.warning(f"Stop monitor init failed (non-fatal): {_stop_mon_err}")

    # ── RL executor — MES paper validation (experimental, non-blocking) ───────
    try:
        from pathlib import Path as _RLPath
        from strategies.rl_executor import RLExecutor

        _rl_model_dir = _RLPath(__file__).parent / "data" / "rl_models"
        _mes_models = sorted(_rl_model_dir.glob("MES_*.zip"))
        # Gate on the existing ENABLE_RL_TRADING feature flag (default False).
        # Previously this block autostarted whenever a MES_*.zip existed,
        # bypassing the flag entirely -- so the experimental RL executor ran
        # uncoordinated alongside the LLM pipeline on the same MES paper account,
        # tracking its own in-memory _paper_position and contaminating
        # execution-fidelity data. is_enabled honors a runtime override, so RL
        # can be toggled on for isolated eval without a code change.
        from flags import get_flags as _get_flags

        _rl_enabled = _get_flags().is_enabled("ENABLE_RL_TRADING")
        if _mes_models and _rl_enabled:
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
        elif not _rl_enabled:
            logger.info(
                "[RL Executor] Disabled (ENABLE_RL_TRADING=False) -- experimental "
                "MES RL executor not started; enable via the feature-flags API "
                "for isolated evaluation"
            )
        else:
            logger.warning("[RL Executor] No MES model found in data/rl_models/ — skipping")
    except Exception as _rl_err:
        logger.warning("[RL Executor] Could not start: %s — continuing without RL", _rl_err)

    # ── Weekly strategy discovery ──────────────────────────────────────────────
    try:

        async def _run_nightly_discovery() -> None:
            """Nightly: generate + evaluate one LLM strategy per active instrument."""
            try:
                from pathlib import Path as _Path
                from strategies.discovery_loop import generate_strategy, evaluate_strategy_file

                for _sym, _ivl in [("MES", "1h"), ("MGC", "1h"), ("MCL", "1h"), ("MNQ", "1h")]:
                    logger.info(f"[NightlyDiscovery] Running cycle for {_sym}/{_ivl}")
                    _path = await generate_strategy(symbol=_sym, interval=_ivl)
                    if _path is None:
                        logger.warning(f"[NightlyDiscovery] No strategy generated for {_sym}")
                        continue
                    _result = evaluate_strategy_file(
                        filename=_Path(_path).name, symbol=_sym, interval=_ivl
                    )
                    logger.info(
                        f"[NightlyDiscovery] {_sym} verdict={_result.get('verdict')} "
                        f"sharpe={_result.get('sharpe', 0):.2f}"
                    )
            except Exception as _disc_err:
                logger.error(f"[NightlyDiscovery] Failed: {_disc_err}", exc_info=True)

        if scheduler is not None:
            scheduler.add_job(
                _run_nightly_discovery,
                CronTrigger(hour=1, minute=0, timezone="America/Chicago"),
                id="nightly_discovery",
                name="Nightly Strategy Discovery Loop",
                max_instances=1,
                replace_existing=True,
            )
            logger.info("✅ Nightly strategy discovery loop registered (01:00 CT)")
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
            ("MES", "trend", 7, "scripts/mes_trend_search_results.json"),
            ("MCL", "meanrev", 1, "scripts/mcl_meanrev_search_results.json"),
            ("MNQ", "trend", 1, "scripts/mnq_trend_search_results.json"),
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
                            _results_file,
                            _sym,
                            _fam,
                            _rank,
                        )
                        continue
                    try:
                        _snap = orchestrate_gate_v2(
                            results_file=_results_file,
                            symbol=_sym,
                            family=_fam,
                            rank=_rank,
                            reports_dir=reports_dir,
                            output_dir=output_dir,
                        )
                        logger.info(
                            "[GateV2Weekly] %s/%s rank=%d verdict=%s via=%s "
                            "(core %d/4, alt %d/5)",
                            _sym,
                            _fam,
                            _rank,
                            _snap.verdict,
                            _snap.passed_via or "-",
                            _snap.n_core_passed,
                            _snap.n_alt_passed,
                        )
                    except Exception as _inner_err:
                        logger.error(
                            "[GateV2Weekly] %s/%s rank=%d failed: %s",
                            _sym,
                            _fam,
                            _rank,
                            _inner_err,
                            exc_info=True,
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

        # ── Phase 7.6: Weekly Self-Audit & Drift Detection ──────────────────────
        async def _run_weekly_self_audit() -> None:
            """Sunday 18:00 CT: Meta-analysis of performance, drift, and optimization."""
            try:
                from agents.self_audit import WeeklySelfAuditAgent
                from analytics.drift_detector import DriftDetector
                from backtest.paper_config import ACTIVE_INSTRUMENTS

                # 1. Performance Audit (P7.6)
                auditor = WeeklySelfAuditAgent(db_manager)
                audit_result = await auditor.run_audit()
                if "report_md" in audit_result:
                    logger.info(
                        "✅ Weekly self-audit complete — report written to docs/weekly_audit.md"
                    )

                # 2. Strategy Drift Detection (P7.2)
                drifter = DriftDetector(db_manager)
                for _sym in ACTIVE_INSTRUMENTS:
                    _drift = await drifter.check_drift(_sym)
                    if _drift.get("trigger_alert"):
                        logger.warning(
                            f"⚠️ [Pipeline] {_sym} drift detected — demoted to shadow-mode recommended."
                        )

                # 3. Monthly Re-Bayes (P7.4)
                # Only runs on the first Sunday of the month
                now = datetime.now()
                if now.day <= 7:
                    logger.info(
                        "[Main] First Sunday of month detected — triggering Bayesian re-optimization"
                    )
                    from optimization.scheduled_rebayes import ScheduledRebayes

                    optimizer = ScheduledRebayes(db_manager)
                    await optimizer.run_monthly_rebayes()

            except Exception as _audit_err:
                logger.error(f"[SelfAudit] Failed: {_audit_err}", exc_info=True)

        if scheduler is not None:
            scheduler.add_job(
                _run_weekly_self_audit,
                CronTrigger(day_of_week="sun", hour=18, minute=0, timezone="America/Chicago"),
                id="weekly_self_audit",
                name="Weekly Meta-Learning Self-Audit",
                max_instances=1,
                replace_existing=True,
            )
            logger.info("✅ Weekly self-audit & drift detection registered (Sunday 18:00 CT)")

        # ── Batch processing (Anthropic Message Batches API) ───────────────
        # Generic poll sweep: harvests any ended batch job (any agent) into
        # batch_results as soon as it ends, decoupled from each consumer's
        # own collection cadence. See engine/llm/batch_client.py.
        async def _run_batch_poll_sweep() -> None:
            try:
                from llm.batch_client import JarvisBatchClient

                summary = await JarvisBatchClient().sweep_pending()
                if summary["newly_ended"] or summary["newly_stale"]:
                    logger.info("[BatchPollSweep] %s", summary)
            except Exception as _sweep_err:
                logger.warning(f"[BatchPollSweep] failed (non-fatal): {_sweep_err}")

        if scheduler is not None:
            scheduler.add_job(
                _run_batch_poll_sweep,
                CronTrigger(minute="*/15"),
                id="batch_poll_sweep",
                name="Batch Job Poll Sweep",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=600,
            )
            logger.info("✅ Batch poll sweep registered (every 15 minutes)")

        # Research agent weekend pass — batch-API pilot (replaces the
        # standalone Windows Scheduled Task; same default symbols/cadence).
        async def _run_research_agent_weekend_submit() -> None:
            try:
                from scheduler.research_agent_weekend import run_weekend_research_pass_submit

                symbols_env = os.environ.get("RESEARCH_AGENT_SYMBOLS", "")
                symbols = [s.strip().upper() for s in symbols_env.split(",") if s.strip()] or [
                    "MES",
                    "MNQ",
                    "MCL",
                    "MGC",
                ]
                n_hyp_env = os.environ.get("RESEARCH_AGENT_N_HYPOTHESES", "3")
                try:
                    n_hypotheses = int(n_hyp_env)
                except ValueError:
                    n_hypotheses = 3

                result = await run_weekend_research_pass_submit(
                    symbols=symbols, n_hypotheses_per_symbol=n_hypotheses
                )
                logger.info("[ResearchAgentWeekendSubmit] %s", result)
            except Exception as _submit_err:
                logger.warning(f"[ResearchAgentWeekendSubmit] failed (non-fatal): {_submit_err}")

        async def _run_research_agent_weekend_collect() -> None:
            try:
                from scheduler.research_agent_weekend import run_weekend_research_pass_collect

                result = await run_weekend_research_pass_collect()
                logger.info("[ResearchAgentWeekendCollect] %s", result)
            except Exception as _collect_err:
                logger.warning(f"[ResearchAgentWeekendCollect] failed (non-fatal): {_collect_err}")

        if scheduler is not None:
            scheduler.add_job(
                _run_research_agent_weekend_submit,
                CronTrigger(day_of_week="sat", hour=10, minute=0, timezone="America/Chicago"),
                id="research_agent_weekend_submit",
                name="Research Agent Weekend Batch Submit",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=3600,
            )
            scheduler.add_job(
                _run_research_agent_weekend_collect,
                CronTrigger(day_of_week="sat", hour=16, minute=0, timezone="America/Chicago"),
                id="research_agent_weekend_collect_sat",
                name="Research Agent Weekend Batch Collect (Saturday)",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=3600,
            )
            scheduler.add_job(
                _run_research_agent_weekend_collect,
                CronTrigger(day_of_week="sun", hour=8, minute=0, timezone="America/Chicago"),
                id="research_agent_weekend_collect_sun",
                name="Research Agent Weekend Batch Collect (Sunday)",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info(
                "✅ Research agent weekend batch pass registered "
                "(submit Sat 10:00 CT, collect Sat 16:00 CT + Sun 08:00 CT)"
            )

    except Exception as _gv2_init_err:
        logger.warning(f"Weekly gate v2 job init failed (non-fatal): {_gv2_init_err}")

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

    # ── Predictive Maintenance Monitor (default OFF) ──────────────────────────
    # Monitors memory growth, IB reconnects, LLM latency, and pm2 restart delta.
    # Only starts when ENABLE_PREDICTIVE_MAINTENANCE=1 in .env.
    # Auto-restart requires BOTH flags set to 1 (see docs/runbooks/PREDICTIVE_MAINTENANCE_RUNBOOK.md).
    try:
        from monitoring.predictive_maintenance import HealthMonitor as _HealthMonitor
        from monitoring.predictive_maintenance import (
            is_predictive_maintenance_enabled as _pm_enabled,
        )

        if _pm_enabled():
            _health_monitor = _HealthMonitor()
            asyncio.create_task(_health_monitor.monitor_loop())
            logger.info(
                "Predictive maintenance monitor started "
                "(ENABLE_PREDICTIVE_MAINTENANCE=1, alert-only=%s)",
                not bool(
                    __import__("os")
                    .environ.get("PREDICTIVE_MAINTENANCE_ALLOW_RESTART", "0")
                    .strip()
                    == "1"
                ),
            )
        else:
            logger.info(
                "Predictive maintenance monitor: DISABLED "
                "(set ENABLE_PREDICTIVE_MAINTENANCE=1 to enable — default off)"
            )
    except Exception as _pm_err:
        logger.warning("Predictive maintenance monitor init failed (non-fatal): %s", _pm_err)

    # ── Final yield to bind FastAPI server ───────────────────────────────
    # HB-3: schedule heavy init BEFORE the yield. Post-yield code in a
    # lifespan context manager runs at SHUTDOWN, so a post-yield create_task
    # never runs at startup — that broke the IBKR data feed (2026-05-24).
    # create_task does not await, so the <10s server-bind constraint holds.
    asyncio.create_task(_complete_background_init())

    yield  # Server runs here!

    # Teardown
    # Stop Trailing stop manager
    if trailing_stop_manager:
        await trailing_stop_manager.stop()

    # Stop Canary manager
    if canary_manager:
        await canary_manager.stop()

    # Stop IB data-leg watchdog
    if ib_data_watchdog:
        await ib_data_watchdog.stop()

    # Stop IB market-data freshness heartbeat
    if ib_freshness_heartbeat:
        await ib_freshness_heartbeat.stop()

    # Stop thinkorswim RTD session (Tier 0 market-data source — calls
    # ServerTerminate on the RTD server and cancels its keep-warm task)
    if tos_rtd_connector is not None:
        try:
            await tos_rtd_connector.close()
            logger.info("🛑 thinkorswim RTD session closed")
        except Exception:
            pass

    # Stop Paper stop-loss monitor
    if paper_stop_monitor:
        await paper_stop_monitor.stop()

    # Stop Redis trigger
    if redis_trigger:
        await redis_trigger.stop()

    # Stop TV streamer
    if tv_streamer:
        try:
            await tv_streamer.stop()
            logger.info("🛑 Real-time data fabric stopped")
        except Exception:
            pass

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
    # Cancel Discord reaction watcher gracefully
    if _reaction_watcher_task is not None and not _reaction_watcher_task.done():
        _reaction_watcher_task.cancel()
        try:
            await _reaction_watcher_task
        except (asyncio.CancelledError, Exception):
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3010", "http://localhost:3000", "http://localhost:3004"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(APIKeyMiddleware)
app.state.limiter = get_limiter()
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

# Prometheus exposition at /metrics (auth-exempt; see monitoring.metrics +
# middleware.auth.EXEMPT_PATHS). P1.0 of the observability roadmap — the jarvis_*
# families were defined but never mounted/scraped before this.
from monitoring.metrics import mount_metrics  # noqa: E402

mount_metrics(app)

app.include_router(health_router)
app.include_router(phase3_readiness_router)
app.include_router(readiness_router)
app.include_router(journal_router, prefix="/journal", tags=["journal"])
app.include_router(journal_review_router, prefix="/journal", tags=["journal-review"])
app.include_router(jarvis_router)
app.include_router(trades_router)
app.include_router(strategy_ledger_router)
app.include_router(trading_status_router)
app.include_router(forward_test_router)
app.include_router(validation_analytics_router)
app.include_router(flags_router, prefix="/flags", tags=["feature-flags"])
app.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
app.include_router(market_router)
app.include_router(analytics_router)
app.include_router(attribution_router)
app.include_router(vault_router)
app.include_router(pnl_truth_router)
app.include_router(durability_router)
app.include_router(safety_router)
app.include_router(strategies_router)
app.include_router(validation_router)
app.include_router(paper_validation_router)
app.include_router(proactive_validation_router)
app.include_router(execution_status_router)
app.include_router(webhook_router)
app.include_router(whatsapp_router)
inject_whatsapp_deps(db_manager, paper_tracker, safety_layer, data_manager)
app.include_router(discord_router)
app.include_router(experiments_router)
app.include_router(backtest_router)
app.include_router(options_backtest_router)
app.include_router(learning_router)
app.include_router(events_router)
app.include_router(kairos_router)
app.include_router(admin_router)
app.include_router(profiling_router)
app.include_router(reports_router)
app.include_router(schwab_router)
app.include_router(instruments_router)
app.include_router(brokers_router)
app.include_router(options_router, prefix="/options", tags=["options"])
app.include_router(approval_router)
app.include_router(actionable_router)
app.include_router(signal_outcomes_router)
app.include_router(approval_queue_router)
app.include_router(pipeline_router)
app.include_router(session_brief_router)
app.include_router(framing_brief_router)
app.include_router(options_signals_router)
app.include_router(pipeline_ws_router)
app.include_router(messaging_router)
app.include_router(scanner_router)
app.include_router(tradingview_router)
app.include_router(scheduler_router)
app.include_router(wfe_router)
app.include_router(discovery_router)
app.include_router(hidden_pivots_router)
app.include_router(decisions_router)
app.include_router(cache_router)
app.include_router(polymarket_router)
app.include_router(super_engine_router)
app.include_router(operations_dashboard_router)
app.include_router(institutional_router)
app.include_router(orders_router)
app.include_router(v1_router)
app.include_router(observability_router)
app.include_router(strategy_c_router)
app.include_router(ib_scanner_router)
app.include_router(macro_router)
app.include_router(analysis_router)
app.include_router(regime_router)
app.include_router(watchlist_router)
app.include_router(sentiment_router)
app.include_router(settings_router)
app.include_router(prices_router)
app.include_router(tos_router)
app.include_router(pnl_attribution_router)
app.include_router(auction_bias_router)
app.include_router(websocket_router)
app.include_router(thinkscript_router)
app.include_router(alerts_router)
app.include_router(notifications_router)
app.include_router(strategy_lab_router)

app.include_router(pipeline_board_router)
app.include_router(config_router)
app.include_router(crypto_router)
app.include_router(openclaw_router)

# ── WebSocket Price Feed ────────────────────────────────────────────────────────
from websocket.price_feed import price_feed_endpoint

app.websocket("/ws/prices")(price_feed_endpoint)


# ── WebSocket Events (Trading Events) ────────────────────────────────────────────
from websocket.events_endpoint import events_endpoint


async def events_handler(websocket: WebSocket):
    """Route WebSocket /ws/events to events_endpoint with ws_manager."""
    await events_endpoint(websocket, ws_manager)


app.websocket("/ws/events")(events_handler)

# ── Safety / Kill Switch (shared routes live in routers/safety_router.py) ───


# -- /position-sizing/calculate -- served by routers/settings_router.py (wired 2026-05-22) --


# ── /safety/circuit-breakers — served by routers/safety_router.py ──

# -- /safety/config -- served by routers/safety_router.py (wired 2026-05-22) --
# ── /safety/reset-daily-pnl — served by routers/safety_router.py ──

# -- /safety/loss-tracker -- served by routers/safety_router.py (wired 2026-05-22) --
# ── Risk Limits Settings ───────────────────────────────────────────────────


# -- /settings/risk (GET+POST) + /strategy/params (GET+PUT) -- served by routers/settings_router.py (wired 2026-05-22) --

# ── Analysis / LLM stats / Reddit sentiment — served by routers/analysis_router.py (wired 2026-05-22) ──


# ── Sentiment (news/{symbol} + recent) — served by routers/sentiment_router.py (wired 2026-05-22) ──


# ── Portfolio ─────────────────────────────────────────────────────────────


# -- /portfolio -- served by routers/portfolio_router.py (wired 2026-05-22) --


# ── Paper Trading Portfolio ───────────────────────────────────────────────


# ── /portfolio/paper/positions — served by routers/portfolio_router.py (wired 2026-05-22) ──


# -- /portfolio/paper/trade/manual -- served by routers/portfolio_router.py (wired 2026-05-22) --


# -- /portfolio/paper/performance -- served by routers/portfolio_router.py (wired 2026-05-22) --

# ── Pending Signals (MGC daily scanner output) ────────────────────────────


# -- /paper/pending-signals -- served by routers/backtest_router.py (wired 2026-05-22) --
# -- /paper/reset-pending-signals (POST) -- served by routers/backtest_router.py (wired 2026-07-28, GT-40) --


# ── Historical Query Endpoints (SQLite) ───────────────────────────────────


# -- /portfolio/history/trades -- served by routers/portfolio_router.py (wired 2026-05-22) --


# -- /portfolio/history/daily-pnl -- served by routers/portfolio_router.py (wired 2026-05-22) --


# -- /portfolio/history/decisions -- served by routers/portfolio_router.py (wired 2026-05-22) --


# -- /portfolio/stats/summary -- served by routers/portfolio_router.py (wired 2026-05-22) --


# -- /portfolio/stats/drawdown -- served by routers/portfolio_router.py (wired 2026-05-22) --


# ── Streak Stats ──────────────────────────────────────────────────────────


# -- /portfolio/stats/streaks -- served by routers/portfolio_router.py (wired 2026-05-22) --


# ── Pipeline Run History ───────────────────────────────────────────────────


# -- /pipeline/history -- served by routers/pipeline_router.py (wired 2026-05-22) --


# ── Analytics / Performance Validation ────────────────────────────────────
# GET /analytics/performance — canonical metrics: routers/analytics_router.py
# GET /analytics/validation-report — PASS/FAIL report: routers/analytics_router.py


# ── /analytics/performance/rolling + /analytics/performance/compare — served by routers/analytics_router.py ──


# ── /analytics/mtf — served by routers/analytics_router.py (wired 2026-05-22) ──

# ── watchlist/scan — served by routers/watchlist_router.py (wired 2026-05-22) ──


# ── Recent decisions (for dashboard feed) ─────────────────────────────────

_decision_log: list[dict] = []  # In-memory ring buffer, 100 entries


def _build_data_provenance(dm, symbol: str) -> dict | None:
    """Snapshot *what data* a decision was based on, for honest persistence.

    Answers post-hoc audits like "was this fill made on live IBKR data or a
    stale CSV-cache fallback?" (the 2026-06-29 frozen-MES-5300 class). Sourced
    entirely from the data manager's *existing* observability so it adds no new
    probe and no new state:

    - ``last_bar_source`` — the most-recent data tier that served bars
      (``ibkr`` | ``sqlite_cache`` | ``polygon`` | ``csv_cache`` | ``none``).
      This is GLOBAL on the manager, not per-symbol, so it is *approximate*
      when several symbols are served concurrently; named honestly so a reader
      never over-trusts it.
    - ``serve_age_s`` — seconds since bars were last served *for this symbol*
      (per-symbol via ``symbol_freshness()``, accurate). ``None`` if this symbol
      has not been served yet this run.

    Fully defensive: returns ``None`` when the data manager is unavailable and
    never raises into the decision path (a provenance failure must never block
    or corrupt a decision). Deliberately reads the manager's existing surface
    rather than adding a public accessor, to avoid colliding with in-flight
    market_data.py work.
    """
    if dm is None:
        return None
    prov: dict = {}
    try:
        prov["last_bar_source"] = getattr(dm, "_last_bar_source", None)
    except Exception:
        prov["last_bar_source"] = None
    try:
        fresh = dm.symbol_freshness()
        prov["serve_age_s"] = fresh.get(symbol.upper()) if isinstance(fresh, dict) else None
    except Exception:
        prov["serve_age_s"] = None
    return prov


def _log_decision(
    symbol: str,
    action: str,
    confidence: float = 0.0,
    source: str = "unknown",
    summary: str = "",
    reasoning: str = "",
    regime: str | None = None,
    signal_data: dict | None = None,
    full_pipeline_data: dict | None = None,
) -> None:
    """Append a decision to the in-memory ring buffer AND persist to SQLite."""
    # Data-truth: stamp *what data* this decision was based on (tier + per-symbol
    # serve-age) so a post-hoc audit can tell a live-IBKR decision from one made
    # on a stale CSV-cache fallback (the 2026-06-29 frozen-MES-5300 class). The
    # engine already has read-time freshness gates (entry_price_sanity); this
    # records the provenance the gate saw, it does NOT change any trade decision.
    provenance = _build_data_provenance(data_manager, symbol)

    entry: dict = {
        "id": len(_decision_log) + 1,
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "source": source,
        "summary": summary,
        "data_provenance": provenance,
    }
    _decision_log.append(entry)
    if len(_decision_log) > 100:
        _decision_log.pop(0)

    # Persist to SQLite (non-blocking best-effort — never crash the caller).
    # Provenance rides inside signal_data_json (no schema migration): merge into
    # a *copy* so we never mutate the caller's dict.
    if db_manager:
        try:
            sig = signal_data if signal_data is not None else {"source": source, "summary": summary}
            if provenance is not None and isinstance(sig, dict):
                sig = {**sig, "data_provenance": provenance}
            db_manager.insert_decision(
                symbol=symbol,
                action=action,
                confidence=confidence,
                regime=regime,
                signal_data=sig,
                reasoning=reasoning or summary,
                full_pipeline_data=full_pipeline_data,
            )
        except Exception as _db_err:
            logger.warning(f"[DB] Failed to persist decision for {symbol}: {_db_err}")


# ── /decisions/recent + /decisions/log — served by routers/decisions_router.py ──


# ── Sentiment (recent + news) — served by routers/sentiment_router.py (wired 2026-05-22) ──


# ── Watchlist (GET/POST/DELETE + /scan) — served by routers/watchlist_router.py (wired 2026-05-22) ──


# ── Live Prices ────────────────────────────────────────────────────────────


# ── /prices/snapshot — served by routers/prices_router.py (wired 2026-05-22) ──

# ── Earnings calendar awareness ──────────────────────────────────────────────────


# ── /market/earnings — served by routers/market_router.py ──
# ── /pipeline/run/sdk — served by routers/pipeline_router.py ──


# -- /notifications/whatsapp/test -- served by routers/notifications_router.py (wired 2026-05-22) --


# ── VIX threshold WhatsApp alert ──────────────────────────────────────────────────


# -- /notifications/vix-alert-check -- served by routers/notifications_router.py (wired 2026-05-22) --


# -- /safety/regime-alert + /safety/retirement-status -- served by routers/safety_router.py (wired 2026-05-22) --

# -- /thinkscript/* -- served by routers/thinkscript_router.py (wired 2026-05-22) --

# ── Macro Data (FRED) — served by routers/macro_router.py (wired 2026-05-22) ──


# ── Backtest routes (run, walk-forward, regime-analysis, regime-status, paper-status,
# mgc-signal, mgc-log-trade, monte-carlo) — served by routers/backtest_router.py ──


# /backtest/walk-forward, /backtest/regime-analysis, /backtest/regime-status,
# /backtest/paper-status, /paper/mgc-signal, /paper/mgc-log-trade
# -- all served by routers/backtest_router.py (wired 2026-05-22)


# -- /paper/mgc-performance -- served by routers/backtest_router.py (wired 2026-05-22) --


# ── Monte Carlo — served by routers/backtest_router.py (wired 2026-05-22) ──


# ── WebSocket Real-Time Events ────────────────────────────────────────────


# -- /ws/events -- served by routers/websocket_router.py (wired 2026-05-22) --


# ── WebSocket Status Endpoint ─────────────────────────────────────────────


# ── /ws/status — served by routers/websocket_router.py (wired 2026-05-22) ──


# -- /portfolio/stats/session-today -- served by routers/portfolio_router.py (wired 2026-05-22) --


# -- /portfolio/stats/weekly -- served by routers/portfolio_router.py (wired 2026-05-22) --


# -- /portfolio/stats/commissions -- served by routers/portfolio_router.py (wired 2026-05-22) --


# -- /analytics/trades/by-day + /analytics/trades/by-symbol -- served by routers/analytics_router.py --


# -- /alerts/history -- served by routers/alerts_router.py (wired 2026-05-22) --


# -- /alerts/stats -- served by routers/alerts_router.py (wired 2026-05-22) --


# -- /portfolio/import/trades -- served by routers/portfolio_router.py (wired 2026-05-22,
#    RETIRED 2026-07-26 / D3-02: now always returns 410 -- silently discarded every row) --
