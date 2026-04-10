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
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, FastAPI, HTTPException, Request, WebSocket
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
from agents.technical_analyst import TechnicalAnalystAgent
from agents.thinkscript_generator import ThinkScriptGeneratorAgent
from agents.trader import TraderAgent
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
from routers.discord_router import router as discord_router
from routers.flags_router import router as flags_router
from routers.flags_router import set_flags as set_flags_router
from routers.health_router import inject_dependencies as inject_health_router_deps
from routers.health_router import router as health_router
from routers.journal_router import router as journal_router
from routers.journal_router import set_db_manager as set_journal_db
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
from routers.scanner_router import router as scanner_router
from routers.scanner_router import inject_dependencies as inject_scanner_deps
from routers.scheduler_router import router as scheduler_router
from routers.scheduler_router import inject_scheduler as inject_scheduler_router_scheduler
from routers.trades_router import router as trades_router
from routers.wfe_router import router as wfe_router
from schedulers.eod_scheduler import EODScheduler
from notifications.validation_alerts import ValidationAlertManager
from notifications.morning_brief import inject_morning_brief_deps
from websocket.events import set_ws_manager
from websocket.manager import WebSocketManager

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

# Rate limit: track last alert time per symbol to avoid flooding (2-hour cooldown)
_last_alert_time: Dict[str, datetime] = {}
ALERT_COOLDOWN_HOURS = 2

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
        validation_alert_manager

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

    # Safety layer — always first; PnLMonitor feeds circuit breakers with live data
    safety_layer = SafetyLayer(settings, pnl_monitor=pnl_monitor)

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
                "technical": technical_analyst,
                "news": news_agent,
                "social": social_agent,
                "fundamental": fundamental_agent,
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

        symbols_to_scan = (
            [
                (sym, True)
                for sym in settings.FUTURES_WATCHLIST[:2]  # Top 2 futures
            ]
            + [
                (sym, False)
                for sym in settings.OPTIONS_WATCHLIST[:3]  # Top 3 equities
            ]
        )

        logger.info(f"Scheduled scan: {[s[0] for s in symbols_to_scan]}")
        from notifications.whatsapp import get_notifier

        notifier = get_notifier()

        async def _analyze_and_alert(symbol: str, is_futures: bool) -> None:
            import time as _time_mod

            try:
                _t0 = _time_mod.monotonic()
                result = await trading_pipeline.analyze_and_decide(symbol, is_futures)
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

                    # Rate limit: skip alert if we sent one for this symbol within cooldown window
                    now = datetime.now()
                    last_sent = _last_alert_time.get(symbol)
                    cooldown_expired = last_sent is None or (now - last_sent) >= timedelta(
                        hours=ALERT_COOLDOWN_HOURS
                    )

                    if notifier.enabled and cooldown_expired:
                        price_str = f" @ {price_info:.2f}" if price_info else ""
                        pct = int(confidence * 100)
                        short_reason = (
                            (reasoning[:100] + "...") if len(reasoning) > 100 else reasoning
                        )
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

        await asyncio.gather(*[_analyze_and_alert(sym, fut) for sym, fut in symbols_to_scan])

    # Run every 30 minutes on weekdays, 9:30am-4:00pm Chicago time
    if settings.ANTHROPIC_API_KEY:
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
        scheduler.start()
        logger.info("⏰ Scheduler started — watchlist scan every 30min (9:30am-4pm CT weekdays)")

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

    # Wire router dependencies now that all singletons are ready
    inject_portfolio_deps(paper_tracker, db_manager, data_manager)
    inject_safety_router_deps(safety_layer, loss_tracker)
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
    inject_brokers_deps(ibkr=ib_paper_connector, schwab=schwab_connector, tracker=paper_tracker)
    inject_approval_deps(safety_layer, paper_tracker, db_manager)
    inject_scheduler_router_scheduler(scheduler)
    inject_pipeline_deps(scheduler, trading_pipeline, safety_layer, db_manager, paper_tracker)
    # Morning brief deps
    inject_morning_brief_deps(data_manager, paper_tracker, safety_layer)

    # Initialize Signal Scanner
    try:
        from scanner.signal_scanner import SignalScanner

        signal_scanner = SignalScanner(
            trading_pipeline=trading_pipeline,
            db_manager=db_manager,
        )
        inject_scanner_deps(signal_scanner)
        await signal_scanner.start()
        logger.info("Signal scanner started (MCL + MNQ, 60-min interval)")
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
            symbols=["MCL", "MNQ"],
        )
        _orchestrator.register(_futures_module)
        set_orchestrator(_orchestrator)
        await _orchestrator.start()
        logger.info("MultiMarketOrchestrator started with 1 module (futures: MCL, MNQ)")
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

                brief_text = await assemble_morning_brief()
                logger.info("[MorningBrief] Assembled: %s chars", len(brief_text))
                await send_raw(brief_text)
            except Exception as exc:
                logger.error("[MorningBrief] run_morning_brief failed: %s", exc)

        if scheduler is not None:
            scheduler.add_job(
                run_morning_brief,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=8,
                    minute=45,
                    timezone="America/Chicago",
                ),
                id="morning_brief",
                name="Morning Intelligence Brief",
                max_instances=1,
                replace_existing=True,
            )
            logger.info("✅ Morning brief job registered — fires Mon–Fri at 08:45 CT")
    except Exception as _brief_err:
        logger.warning(f"Morning brief init failed (non-fatal): {_brief_err}")

    logger.info("JARVIS TRADER ready. Dashboard: http://localhost:3010")
    logger.info("   API docs: http://localhost:8010/docs")

    yield  # Server runs here

    # Teardown
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

app.include_router(health_router)
app.include_router(phase3_readiness_router)
app.include_router(journal_router, prefix="/journal", tags=["journal"])
app.include_router(trades_router)
app.include_router(flags_router, prefix="/flags", tags=["feature-flags"])
app.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
app.include_router(market_router)
app.include_router(analytics_router)
app.include_router(safety_router)
app.include_router(strategies_router)
app.include_router(validation_router)
app.include_router(paper_validation_router)
app.include_router(webhook_router)
app.include_router(discord_router)
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
app.include_router(scanner_router)
app.include_router(scheduler_router)
app.include_router(wfe_router)
app.include_router(v1_router)


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


@app.get("/position-sizing/calculate")
async def calculate_position_size_alias():
    """Top-level alias for position sizing calculation."""
    from utils.position_sizing import calculate_position_size

    result = calculate_position_size(
        symbol="MES",
        account_value=settings.INITIAL_CAPITAL,
        atr=15.0,
        risk_pct=0.01,
        atr_stop_multiplier=0.70,
        max_contracts=2,
    )
    return {
        "symbol": result.symbol,
        "contracts": result.contracts,
        "risk_per_trade": result.risk_per_trade,
        "stop_distance": result.stop_distance,
        "dollar_risk_per_contract": result.dollar_risk_per_contract,
        "account_value": result.account_value,
        "reasoning": result.reasoning,
    }


@app.get("/safety/loss-tracker")
async def get_loss_tracker_status():
    """
    Return consecutive loss tracking state.

    Returns:
        global_consecutive_losses: Total consecutive losses (all symbols)
        symbol_losses: Dict[symbol] -> consecutive loss count
        position_size_multiplier: 1.0 / 0.5 / 0.25 / 0.0 based on loss streak
        is_halted: True if trading is paused due to loss limit
        halt_until: ISO timestamp when trading resumes (if halted)
        last_trade_symbol: Which symbol was last traded
        last_trade_timestamp: When the last trade executed
        config: Loss threshold configuration
    """
    if not loss_tracker:
        raise HTTPException(500, "Loss tracker not initialized")
    try:
        return loss_tracker.get_status()
    except Exception as e:
        logger.error(f"[LOSS-TRACKER] Status query failed: {e}")
        raise HTTPException(500, f"Failed to get loss tracker status: {e}") from e


# ── Risk Limits Settings ───────────────────────────────────────────────────


@app.get("/settings/risk")
async def get_risk_settings():
    """Get current risk/circuit breaker settings."""
    try:
        # Get live circuit breaker state
        cb_status = {}
        if safety_layer:
            cb_status = safety_layer.check_circuit_breakers()

        # Get config defaults from env / TradingConfig
        config = {
            "daily_loss_limit": float(
                os.getenv("DAILY_LOSS_LIMIT", str(settings.MAX_DAILY_LOSS_PCT * 10000))
            ),
            "max_drawdown_pct": settings.MAX_DRAWDOWN_PCT,
            "max_contracts": settings.MAX_CONTRACTS_PER_INSTRUMENT,
            "risk_per_trade_pct": float(os.getenv("RISK_PER_TRADE_PCT", "0.01")),
            "atr_stop_multiplier": float(os.getenv("ATR_STOP_MULTIPLIER", "0.70")),
            "atr_target_multiplier": float(os.getenv("ATR_TARGET_MULTIPLIER", "1.50")),
        }

        # Override with DB settings if available (DB values take precedence over env)
        if db_manager:
            for key in config:
                val = db_manager.get_setting(key)
                if val is not None:
                    try:
                        config[key] = type(config[key])(val)
                    except (ValueError, TypeError):
                        pass

        return {
            "config": config,
            "circuit_breakers": cb_status,
            "editable_keys": list(config.keys()),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/settings/risk")
async def update_risk_settings(payload: dict):
    """Update risk settings (persists to DB settings table)."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    ALLOWED_KEYS = {
        "daily_loss_limit",
        "max_drawdown_pct",
        "max_contracts",
        "risk_per_trade_pct",
        "atr_stop_multiplier",
        "atr_target_multiplier",
    }

    VALIDATORS = {
        "daily_loss_limit": lambda v: float(v) > 0,
        "max_drawdown_pct": lambda v: 0 < float(v) <= 1.0,
        "max_contracts": lambda v: 1 <= int(v) <= 10,
        "risk_per_trade_pct": lambda v: 0 < float(v) <= 0.05,
        "atr_stop_multiplier": lambda v: 0.1 <= float(v) <= 3.0,
        "atr_target_multiplier": lambda v: 0.1 <= float(v) <= 5.0,
    }

    updated = {}
    errors = {}

    for key, value in payload.items():
        if key not in ALLOWED_KEYS:
            errors[key] = "Unknown setting"
            continue

        validator = VALIDATORS.get(key)
        try:
            if validator and not validator(value):
                errors[key] = f"Value {value} out of allowed range"
                continue
            db_manager.set_setting(key, str(value))
            updated[key] = value
        except Exception as e:
            errors[key] = str(e)[:80]

    return {
        "updated": updated,
        "errors": errors,
        "count": len(updated),
    }


# ── Strategy Parameters ────────────────────────────────────────────────────────


class StrategyParams(BaseModel):
    """Strategy parameter configuration."""

    ema_short: int = 8
    ema_long: int = 21
    ema_smoother: int = 34
    atr_length: int = 14
    atr_mult_stop: float = 1.5
    atr_mult_target: float = 3.0
    min_volume_sma: int = 20
    rsi_length: int = 14
    rsi_oversold: int = 30
    rsi_overbought: int = 70
    adaptive_regime: bool = True
    volume_filter: bool = False
    mtf_filter: bool = False


# In-memory strategy params (would be persisted in production)
_strategy_params = StrategyParams()


@app.get("/strategy/params")
async def get_strategy_params():
    """
    Get current strategy parameter configuration.

    Returns:
        ema_short: Short-term EMA period (default 8)
        ema_long: Medium-term EMA period (default 21)
        ema_smoother: Long-term EMA period (default 34)
        atr_length: ATR indicator period (default 14)
        atr_mult_stop: Stop loss as multiple of ATR (default 1.5x)
        atr_mult_target: Profit target as multiple of ATR (default 3.0x)
        min_volume_sma: Minimum volume SMA period (default 20)
        rsi_length: RSI indicator period (default 14)
        rsi_oversold: RSI oversold threshold (default 30)
        rsi_overbought: RSI overbought threshold (default 70)
        adaptive_regime: Apply regime-based filters (default True)
        volume_filter: Apply volume filters (default False)
        mtf_filter: Apply multi-timeframe filters (default False)
    """
    global _strategy_params
    return _strategy_params.model_dump()


@app.put("/strategy/params")
async def update_strategy_params(params: StrategyParams):
    """
    Update strategy parameter configuration.

    Changes take effect immediately for future backtests and live trading.
    Existing positions are unaffected.

    Request:
        ema_short, ema_long, ema_smoother: EMA periods
        atr_length, atr_mult_stop, atr_mult_target: ATR configuration
        min_volume_sma, rsi_length, rsi_oversold, rsi_overbought: Indicator settings
        adaptive_regime, volume_filter, mtf_filter: Feature flags
    """
    global _strategy_params
    try:
        # Validate parameters
        if not (1 < params.ema_short < params.ema_long < params.ema_smoother < 200):
            raise ValueError("EMA periods must satisfy: 1 < short < long < smoother < 200")
        if not (1 <= params.atr_length <= 50):
            raise ValueError("ATR length must be 1-50")
        if not (0.5 <= params.atr_mult_stop <= 10.0):
            raise ValueError("ATR stop multiplier must be 0.5-10.0")
        if not (0.5 <= params.atr_mult_target <= 10.0):
            raise ValueError("ATR target multiplier must be 0.5-10.0")
        if not (1 <= params.rsi_length <= 50):
            raise ValueError("RSI length must be 1-50")
        if not (0 < params.rsi_oversold < 50):
            raise ValueError("RSI oversold must be 0-50")
        if not (50 < params.rsi_overbought < 100):
            raise ValueError("RSI overbought must be 50-100")

        old_params = _strategy_params.model_dump()
        _strategy_params = params
        logger.info(f"[STRATEGY] Parameters updated: {params.model_dump()}")

        return {
            "status": "updated",
            "old_params": old_params,
            "new_params": params.model_dump(),
        }
    except ValueError as e:
        raise HTTPException(400, f"Invalid parameter: {e}") from e
    except Exception as e:
        logger.error(f"[STRATEGY] Update failed: {e}")
        raise HTTPException(500, f"Failed to update strategy parameters: {e}") from e


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

    df = await data_manager.get_bars(
        symbol, lookback_days=days, timeframe=timeframe, is_futures=futures
    )
    if df.empty:
        raise HTTPException(404, f"No data available for {symbol}")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": df.tail(200).to_dict(orient="records"),
        "count": len(df),
    }


@app.get("/llm/stats")
async def get_llm_stats(days_back: int = 0):
    """
    Get LLM API usage and cost statistics for a given day.

    Query Parameters:
        days_back: 0 for today, 1 for yesterday, etc. (default: 0)

    Returns:
        date: ISO date string
        total_calls: Total LLM API calls made
        total_cost_usd: Total cost in USD
        success_rate: Percentage of successful calls (0-1)
        avg_latency_ms: Average API latency in milliseconds
        per_model: Dict[model_name] -> {calls, input_tokens, output_tokens, cost_usd}
        per_agent: Dict[agent_name] -> {calls, cost_usd}
    """
    if not cost_tracker:
        raise HTTPException(500, "Cost tracker not initialized")
    try:
        return await cost_tracker.get_daily_summary(days_back=days_back)
    except Exception as e:
        logger.error(f"[LLM-STATS] Daily summary failed: {e}")
        raise HTTPException(500, f"Failed to get LLM stats: {e}") from e


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
    action: str  # "buy" | "sell" | "sell_short" | "buy_to_cover"
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
        except KeyError as e:
            raise HTTPException(404, f"No open trade with id={req.close_trade_id!r}") from e

        # Send WhatsApp notification for closed trade
        try:
            from notifications.whatsapp import format_trade_closed_alert, send_whatsapp_message

            duration_min = None
            if trade.entry_time:
                try:
                    from dateutil import parser as dtparser

                    entry_dt = dtparser.parse(trade.entry_time)
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                    duration_min = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 60
                except Exception:
                    pass

            msg = format_trade_closed_alert(
                symbol=trade.symbol,
                side=trade.action,
                quantity=int(trade.quantity),
                entry_price=float(trade.entry_price),
                exit_price=float(trade.exit_price),
                pnl=float(trade.pnl),
                duration_minutes=duration_min,
            )
            asyncio.create_task(send_whatsapp_message(msg))
        except Exception:
            pass  # Never let notification failure break the trade close

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


# ── Streak Stats ──────────────────────────────────────────────────────────


@app.get("/portfolio/stats/streaks")
async def get_trading_streaks():
    """Calculate current and maximum win/loss streaks from closed trades."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        import sqlite3

        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                rows = conn.execute(
                    """SELECT pnl FROM paper_trades
                       WHERE status = 'closed' AND pnl IS NOT NULL
                       ORDER BY exit_time ASC"""
                ).fetchall()
            finally:
                conn.close()

        if not rows:
            return {
                "current_streak": 0,
                "current_type": "none",
                "max_win_streak": 0,
                "max_loss_streak": 0,
                "total_trades": 0,
                "recent_results": [],
            }

        pnls = [r[0] for r in rows]
        results = ["W" if p > 0 else "L" for p in pnls]

        # Current streak
        current_type = results[-1]
        current = 0
        for r in reversed(results):
            if r == current_type:
                current += 1
            else:
                break

        # Max streaks
        max_win = max_loss = win_run = loss_run = 0
        for r in results:
            if r == "W":
                win_run += 1
                loss_run = 0
            else:
                loss_run += 1
                win_run = 0
            max_win = max(max_win, win_run)
            max_loss = max(max_loss, loss_run)

        return {
            "current_streak": current,
            "current_type": "win" if current_type == "W" else "loss",
            "max_win_streak": max_win,
            "max_loss_streak": max_loss,
            "total_trades": len(results),
            "recent_results": results[-10:],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


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
# GET /analytics/performance — canonical metrics: routers/analytics_router.py
# GET /analytics/validation-report — PASS/FAIL report: routers/analytics_router.py


@app.get("/analytics/performance/rolling")
async def get_rolling_performance(days: int = 30):
    """Get rolling performance metrics for the last N days (7, 14, or 30)."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")
    days = max(1, min(days, 90))  # clamp to 1-90 days
    try:
        from analytics.performance import PerformanceCalculator

        calc = PerformanceCalculator(db_manager)
        return calc.calculate_rolling(days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


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
        raise HTTPException(500, f"Analytics error: {exc}") from exc


@app.get("/analytics/mtf")
async def get_mtf_analysis(symbol: str = "MES"):
    """
    Multi-timeframe STC analysis for a single symbol.
    Returns 1h, 4h, and 1d STC signals with alignment and recommendation.
    """
    try:
        from analytics.mtf_analyzer import analyze_mtf

        sym = symbol.strip().upper()
        result = await analyze_mtf(sym, data_manager)
        return {
            "symbol": result.symbol,
            "recommendation": result.recommendation,
            "alignment": result.alignment,
            "confidence": result.confidence,
            "aligned_timeframes": result.aligned_timeframes,
            "total_timeframes": result.total_timeframes,
            "source": result.source,
            "timeframes": {
                s.timeframe: {
                    "stc_value": s.stc_value,
                    "stc_signal": s.stc_signal,
                    "price": s.price,
                    "source": s.source,
                }
                for s in result.signals
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/watchlist/scan")
async def watchlist_scan(symbols: str = "MES,MNQ,MCL"):
    """
    Run MTF analysis on all watchlist symbols and return a consolidated signal summary.
    symbols: comma-separated list (default: MES,MNQ,MCL)
    """
    try:
        from analytics.mtf_analyzer import analyze_mtf

        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            raise HTTPException(status_code=400, detail="No symbols provided")

        results = []
        for sym in symbol_list[:5]:  # cap at 5 to avoid abuse
            try:
                mtf_result = await analyze_mtf(sym, data_manager)
                results.append(
                    {
                        "symbol": sym,
                        "recommendation": mtf_result.recommendation,
                        "alignment": mtf_result.alignment,
                        "timeframes": {
                            s.timeframe: {
                                "stc_value": s.stc_value,
                                "stc_signal": s.stc_signal,
                            }
                            for s in mtf_result.signals
                        },
                        "error": None,
                    }
                )
            except Exception as sym_err:
                results.append(
                    {
                        "symbol": sym,
                        "recommendation": "WAIT",
                        "alignment": "NEUTRAL",
                        "timeframes": {},
                        "error": str(sym_err),
                    }
                )

        # Determine overall market bias
        buy_count = sum(1 for r in results if r["recommendation"] == "BUY")
        sell_count = sum(1 for r in results if r["recommendation"] == "SELL")
        if buy_count > sell_count:
            market_bias = "BULLISH"
        elif sell_count > buy_count:
            market_bias = "BEARISH"
        else:
            market_bias = "NEUTRAL"

        return {
            "symbols": results,
            "market_bias": market_bias,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "wait_count": len(results) - buy_count - sell_count,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── Recent decisions (for dashboard feed) ─────────────────────────────────

_decision_log: list[dict] = []  # In-memory ring buffer, 100 entries


def _log_decision(
    symbol: str,
    action: str,
    confidence: float = 0.0,
    source: str = "unknown",
    summary: str = "",
    reasoning: str = "",
    regime: str | None = None,
    signal_data: dict | None = None,
) -> None:
    """Append a decision to the in-memory ring buffer AND persist to SQLite."""
    entry: dict = {
        "id": len(_decision_log) + 1,
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "source": source,
        "summary": summary,
    }
    _decision_log.append(entry)
    if len(_decision_log) > 100:
        _decision_log.pop(0)

    # Persist to SQLite (non-blocking best-effort — never crash the caller)
    if db_manager:
        try:
            db_manager.insert_decision(
                symbol=symbol,
                action=action,
                confidence=confidence,
                regime=regime,
                signal_data=signal_data or {"source": source, "summary": summary},
                reasoning=reasoning or summary,
            )
        except Exception as _db_err:
            logger.warning(f"[DB] Failed to persist decision for {symbol}: {_db_err}")


@app.get("/decisions/recent")
async def get_recent_decisions(limit: int = 20):
    """Return most recent agent decisions — queries SQLite first, falls back to in-memory."""
    if db_manager:
        try:
            rows = db_manager.get_decisions(limit=limit)
            if rows:
                # Normalise to the same shape the dashboard expects
                return [
                    {
                        "id": r.get("id"),
                        "timestamp": r.get("timestamp"),
                        "symbol": r.get("symbol"),
                        "action": r.get("action"),
                        "confidence": r.get("confidence"),
                        "source": (r.get("signal_data_json") or {}).get("source", "db"),
                        "summary": r.get("reasoning") or "",
                    }
                    for r in rows
                ]
        except Exception as _db_err:
            logger.warning(f"[DB] get_decisions failed, falling back to in-memory: {_db_err}")
    return _decision_log[-limit:]


@app.post("/decisions/log")
async def log_decision(decision: dict):
    """Internal: agents call this to log decisions"""
    _log_decision(
        symbol=decision.get("symbol", "UNKNOWN"),
        action=decision.get("action", "hold"),
        confidence=float(decision.get("confidence", 0.0)),
        source=decision.get("source", "api"),
        summary=decision.get("summary", ""),
        reasoning=decision.get("reasoning", ""),
        regime=decision.get("regime"),
        signal_data=decision,
    )
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


# ── Watchlist ─────────────────────────────────────────────────────────────


@app.get("/watchlist")
async def get_watchlist():
    """Return configured watchlists as ticker items with live prices"""
    all_symbols = list(settings.FUTURES_WATCHLIST) + list(settings.OPTIONS_WATCHLIST)
    prices: dict = {}
    if data_manager and all_symbols:
        try:
            batch = await data_manager.get_batch_prices(all_symbols)
            for sym, price_dict in batch.items():
                prices[sym] = {
                    "last_price": price_dict.get("last_price"),
                    "change_pct": price_dict.get("change_pct"),
                }
        except Exception:
            pass

    items = []
    names = {
        "MES": "Micro E-mini S&P 500",
        "MNQ": "Micro E-mini Nasdaq",
        "MCL": "Micro Crude Oil",
        "MGC": "Micro Gold",
        "MHG": "Micro Copper",
        "MYM": "Micro Dow",
        "M2K": "Micro Russell 2000",
    }
    for sym in settings.FUTURES_WATCHLIST:
        p = prices.get(sym, {})
        items.append(
            {
                "symbol": sym,
                "name": names.get(sym, sym),
                "type": "futures",
                "last_price": p.get("last_price"),
                "change_pct": p.get("change_pct"),
            }
        )
    for sym in settings.OPTIONS_WATCHLIST:
        p = prices.get(sym, {})
        items.append(
            {
                "symbol": sym,
                "name": sym,
                "type": "options",
                "last_price": p.get("last_price"),
                "change_pct": p.get("change_pct"),
            }
        )
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
    Futures micro contracts (MES, MNQ, MCL etc) are mapped via data_manager.
    """
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {}

    try:
        batch = await data_manager.get_batch_prices(symbol_list)
        result = {}
        for sym in symbol_list:
            price_dict = batch.get(sym, {})
            result[sym] = {
                "symbol": sym,
                "last_price": price_dict.get("last_price"),
                "prev_close": price_dict.get("prev_close"),
                "change_pct": price_dict.get("change_pct"),
                "source": price_dict.get("source"),
            }
        return result
    except Exception as e:
        raise HTTPException(500, f"Price fetch failed: {e}") from e


# ── Earnings calendar awareness ──────────────────────────────────────────────────


@app.get("/market/earnings")
async def get_upcoming_earnings(days: int = 7):
    """Check for upcoming earnings near our watched symbols."""
    WATCHED = {
        "SPY": "S&P 500 ETF",
        "QQQ": "Nasdaq ETF",
        "AAPL": "Apple (QQQ weight)",
        "MSFT": "Microsoft (QQQ weight)",
        "NVDA": "Nvidia (QQQ weight)",
        "AMZN": "Amazon",
        "META": "Meta",
        "GOOGL": "Alphabet",
    }

    # Earnings calendar data requires a dedicated earnings data source (e.g. Polygon earnings
    # endpoint). No equivalent is available on data_manager at this time.
    return {
        "upcoming_earnings": [],
        "count": 0,
        "days_lookahead": days,
        "note": "Earnings calendar unavailable — no earnings data source configured",
        "source": "unavailable",
        "watched_symbols": list(WATCHED.keys()),
    }


# ── Pipeline ──────────────────────────────────────────────────────────────


class PipelineRequest(BaseModel):
    symbol: str
    is_futures: bool = False
    interval: str = "1h"


@app.post("/pipeline/run")
async def run_pipeline(req: PipelineRequest):
    """Run the full 5-stage AI trading pipeline for a symbol"""
    if not trading_pipeline:
        raise HTTPException(503, "Pipeline not available (no ANTHROPIC_API_KEY)")

    result = await trading_pipeline.analyze_and_decide(
        req.symbol, req.is_futures, timeframe=req.interval
    )

    final_action = result.get("final_action", "hold")

    # Log to decision feed (in-memory + SQLite)
    _log_decision(
        symbol=req.symbol,
        action=final_action,
        confidence=float(result.get("confidence", 0)),
        source="pipeline",
        summary=result.get("summary", ""),
        reasoning=(result.get("trade_decision") or {}).get("reasoning", ""),
    )

    # Auto-log to paper tracker when not in live mode and the pipeline decided to trade
    # Guard: only log approved instruments (FUTURES_WATCHLIST) — never DO NOT TRADE symbols
    _approved_for_paper = {s.upper() for s in (settings.FUTURES_WATCHLIST or [])}
    if (
        not settings.LIVE_TRADING_ENABLED
        and final_action != "hold"
        and req.symbol.upper() in _approved_for_paper
    ):
        try:
            trade_dec = result.get("trade_decision") or {}
            # Prefer limit_price, fall back to stop_price, then last known price from indicators
            entry_price = (
                trade_dec.get("limit_price")
                or trade_dec.get("stop_price")
                or (result.get("technical", {}) or {}).get("current_price")
            )
            final_qty = result.get("final_quantity", 1) or 1

            # Human-gate: when requires_human=True, insert a pending approval row
            # and skip immediately opening the paper trade
            if result.get("requires_human") and db_manager:
                approval_id = db_manager.insert_pending_approval(
                    symbol=req.symbol,
                    action=final_action,
                    quantity=float(final_qty),
                    entry_price=float(entry_price) if entry_price else None,
                    pipeline_snapshot=result,
                    timeframe=result.get("timeframe", "1h"),
                )
                result["pending_approval_id"] = approval_id
                logger.info(
                    f"[PAPER] Human gate — inserted pending approval {approval_id[:8]} "
                    f"for {req.symbol} {final_action.upper()}"
                )
                # Fire-and-forget: WebSocket + WhatsApp + Telegram fan-out
                try:
                    from notifications.pending_approval_notify import (
                        notify_pending_approval_queued as _notify_approval,
                    )

                    asyncio.create_task(
                        _notify_approval(
                            approval_id=approval_id,
                            symbol=req.symbol,
                            action=final_action,
                            quantity=float(final_qty),
                            entry_price=float(entry_price) if entry_price else None,
                        )
                    )
                except Exception as _notify_exc:
                    logger.warning("[PAPER] Approval notify task failed: %s", _notify_exc)
                # OpenClaw WhatsApp alert (direct WSL path, non-blocking)
                try:
                    from notifications.openclaw_notifier import (
                        notify_approval_required as _oc_approval,
                    )

                    asyncio.create_task(
                        _oc_approval(
                            symbol=req.symbol,
                            action=final_action,
                            quantity=float(final_qty),
                            entry_price=float(entry_price) if entry_price else 0.0,
                        )
                    )
                except Exception as _oc_exc:
                    logger.warning("[PAPER] OpenClaw approval notify failed: %s", _oc_exc)
            elif paper_tracker and entry_price:
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
            elif not entry_price:
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


@app.get("/signals/stats")
async def signals_stats():
    """Return webhook signal statistics including deduplication cache size."""
    from routers.webhook_router import _dedup_cache as _webhook_dedup

    recent = get_recent_webhooks(limit=50)
    return {
        "total_received": len(recent),
        "recent_webhooks": recent[:10],
        "dedup_cache_size": len(_webhook_dedup),
    }


@app.get("/scheduler/status")
async def scheduler_status():
    """Scheduled job status"""
    if not scheduler:
        return {"running": False, "jobs": []}
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run": next_run.isoformat() if next_run else None,
            }
        )
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

    symbols_to_scan = [(sym, True) for sym in settings.FUTURES_WATCHLIST[:2]] + [
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

            # Log to decision feed (in-memory + SQLite)
            _log_decision(
                symbol=symbol,
                action=action,
                confidence=float(confidence),
                source="manual_scan",
                summary=result.get("summary", ""),
                reasoning=reasoning,
            )

            alert_sent = False
            alert_suppressed_reason = None

            if action not in ("hold",):
                now = datetime.now()
                last_sent = _last_alert_time.get(symbol)
                cooldown_expired = last_sent is None or (now - last_sent) >= timedelta(
                    hours=ALERT_COOLDOWN_HOURS
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

            scan_results.append(
                {
                    "symbol": symbol,
                    "action": action,
                    "confidence": round(confidence, 4),
                    "final_quantity": qty,
                    "summary": result.get("summary", ""),
                    "errors": result.get("errors", []),
                    "alert_sent": alert_sent,
                    "alert_suppressed_reason": alert_suppressed_reason,
                }
            )

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
    ts = datetime.now(timezone.utc).isoformat()
    if not notifier.enabled:
        return {
            "status": "not_configured",
            "sent": False,
            "timestamp": ts,
            "message": "Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, WHATSAPP_TO to .env",
        }
    ok = await notifier.test()
    return {"status": "sent" if ok else "failed", "sent": bool(ok), "timestamp": ts}


# ── VIX threshold WhatsApp alert ──────────────────────────────────────────────────


@app.post("/notifications/vix-alert-check")
async def check_vix_alert():
    """Check VIX and send WhatsApp alert if above key thresholds."""
    try:
        from analytics.vix_overlay import VIXOverlay
        from notifications.whatsapp import send_whatsapp_message

        vix = VIXOverlay(data_manager=data_manager)
        state = await vix.get_state_async()

        thresholds = [
            (40, "EXTREME VIX", "Consider halting all trading"),
            (30, "ELEVATED VIX", "Reduce position size, widen stops"),
            (20, "CAUTION VIX", "Monitor closely, use regime filter"),
        ]

        alert_level = None
        guidance = None
        for level, label, advice in thresholds:
            if state.vix_value >= level:
                alert_level = label
                guidance = advice
                break

        if alert_level is None:
            return {
                "sent": False,
                "vix": state.vix_value,
                "regime": state.regime,
                "reason": "VIX normal — no alert needed",
            }

        msg = (
            "JARVIS TRADER - VIX Alert\n\n"
            f"VIX: {state.vix_value:.1f} - {alert_level}\n"
            f"Classification: {state.classification}\n\n"
            f"{guidance}\n\n"
            f"Source: {state.source}"
        )

        success = await send_whatsapp_message(msg)
        return {
            "sent": success,
            "vix": state.vix_value,
            "regime": state.regime,
            "alert_level": alert_level,
            "guidance": guidance,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── ThinkScript Generation ─────────────────────────────────────────────────

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
        raise HTTPException(500, f"FRED data unavailable: {e}") from e

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
        from backtest import BacktestDataLoader, Backtester, generate_signals

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


class WalkForwardRequest(BaseModel):
    """Request for walk-forward validation."""

    symbol: str
    start: str  # ISO date
    end: str  # ISO date
    interval: str = "1h"
    capital: float = 100_000.0
    adaptive_regime: bool = True
    volume_filter: bool = False
    mtf_filter: bool = False


@app.post("/backtest/walk-forward")
async def run_walk_forward(request: WalkForwardRequest):
    """
    Execute walk-forward validation on a symbol over a date range.

    Walk-Forward Analysis:
    1. Split data into overlapping train/test windows (6m train, 3m test, 3m step)
    2. For each window: optimize parameters on train data
    3. Validate optimized parameters on out-of-sample test data
    4. Compute Walk-Forward Efficiency (WFE = avg_oos_return / avg_is_return)

    WFE Interpretation:
        > 0.50: Strategy generalizes well
        0.30-0.50: Acceptable, some degradation
        < 0.30: Likely overfit

    Request:
        symbol: Instrument (e.g., "MES", "NQ", "SPY")
        start: Start date (ISO format, e.g., "2024-06-01")
        end: End date (ISO format, e.g., "2026-03-27")
        interval: Timeframe ("1h", "1d", "5m", etc.) — default "1h"
        capital: Initial capital (default 100000)
        adaptive_regime: Include regime filters (default True)
        volume_filter: Apply volume filters (default False)
        mtf_filter: Apply multi-timeframe filters (default False)

    Returns:
        windows: List of walk-forward windows with IS/OOS results
        summary: Aggregate metrics (avg_wfe, total_is_pnl, total_oos_pnl, etc.)
        verdict: PASS/CAUTION/FAIL based on WFE threshold
    """
    try:
        from concurrent.futures import ThreadPoolExecutor

        from backtest.data_loader import BacktestDataLoader
        from backtest.signals import generate_signals
        from backtest.walk_forward import WalkForwardValidator

        def _run_walk_forward():
            loader = BacktestDataLoader()

            # Load 1h data
            df_1h = loader.load(request.symbol, request.start, request.end, request.interval)
            if df_1h is None or df_1h.empty:
                raise ValueError(f"No data for {request.symbol}")

            df_1h = generate_signals(
                df_1h, symbol=request.symbol, adaptive_regime=request.adaptive_regime
            )

            # Load daily data if MTF filter requested
            df_daily = None
            if request.mtf_filter:
                df_daily = loader.load(request.symbol, request.start, request.end, "1d")
                if df_daily is not None:
                    df_daily = generate_signals(
                        df_daily, symbol=request.symbol, adaptive_regime=request.adaptive_regime
                    )

            multiplier = loader.get_multiplier(request.symbol)

            # Run walk-forward
            validator = WalkForwardValidator(train_months=6, test_months=3, step_months=3)
            result = validator.run(
                df_1h,
                symbol=request.symbol,
                multiplier=multiplier,
                capital=request.capital,
                top_n_params=1,
                fast=True,
                adaptive_regime=request.adaptive_regime,
                volume_filter=request.volume_filter,
                mtf_filter=request.mtf_filter,
                df_daily=df_daily,
            )
            return result

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, _run_walk_forward)

        return result

    except ValueError as e:
        logger.error(f"[WALK-FORWARD] Data error: {e}")
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        logger.error(f"[WALK-FORWARD] Validation failed: {e}")
        raise HTTPException(500, f"Walk-forward validation failed: {e}") from e


class RegimeAnalysisRequest(BaseModel):
    """Request for regime analysis on backtest results."""

    results_file: str  # Path to JSON results file (relative to backtest/results/)
    symbol: str = None  # Auto-detected if None


@app.post("/backtest/regime-analysis")
async def analyze_regime(request: RegimeAnalysisRequest):
    """
    Analyze backtest results broken down by market regime.

    Classifies each trade into a regime category and computes performance
    metrics per regime. Identifies which regimes are profitable and which
    should be avoided.

    Regime Categories:
        TRENDING_UP: EMA ribbon bullish + positive phase
        TRENDING_DOWN: EMA ribbon bearish + negative phase
        RANGE_BOUND: Compressed EMAs + low volatility
        HIGH_VOLATILITY: ATR consumed > 80% or extreme phase
        TRANSITION: Regime changed within last 5 bars

    Request:
        results_file: Path to backtest JSON (e.g., "MES_1h_results.json")
        symbol: Instrument symbol for regime classification (auto if None)

    Returns:
        regime_metrics: Dict[regime] -> {trade_count, win_rate, profit_factor, total_pnl, sharpe_ratio, etc.}
        overall_verdict: EXCELLENT/GOOD/ACCEPTABLE/POOR based on regime consistency
        best_regime: Most profitable regime
        worst_regime: Least profitable regime
    """
    try:
        from pathlib import Path

        from backtest.monte_carlo import _load_result_from_json
        from backtest.regime_analysis import RegimeAnalyzer

        # Resolve file path
        results_path = Path(request.results_file)
        if not results_path.is_absolute():
            alt_path = Path(__file__).parent / "backtest" / "results" / results_path.name
            if alt_path.exists():
                results_path = alt_path
            elif not results_path.exists():
                results_path = Path(__file__).parent / "backtest" / "results" / request.results_file

        if not results_path.exists():
            raise FileNotFoundError(f"Results file not found: {results_path}")

        # Load backtest result
        logger.info(f"[REGIME-ANALYSIS] Loading {results_path.name}")
        bt_result = _load_result_from_json(str(results_path))

        # Auto-detect symbol from filename if not provided
        symbol = request.symbol
        if not symbol:
            stem = results_path.stem
            for part in stem.split("_"):
                if part.isupper() and len(part) <= 4:
                    symbol = part
                    break
        if not symbol:
            symbol = "MES"

        # Run regime analysis
        logger.info(f"[REGIME-ANALYSIS] Analyzing {len(bt_result.trades)} trades for {symbol}")
        RegimeAnalyzer()
        regime_stats = {}

        # Classify each trade by regime and accumulate stats
        for trade in bt_result.trades:
            regime = trade.get("regime", "UNKNOWN")
            if regime not in regime_stats:
                regime_stats[regime] = {
                    "trade_count": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "total_pnl": 0.0,
                    "trades": [],
                }

            pnl = trade.get("pnl", 0.0)
            is_win = pnl >= 0

            regime_stats[regime]["trade_count"] += 1
            if is_win:
                regime_stats[regime]["winning_trades"] += 1
            else:
                regime_stats[regime]["losing_trades"] += 1
            regime_stats[regime]["total_pnl"] += pnl
            regime_stats[regime]["trades"].append(trade)

        # Compute derived metrics
        for _, stats in regime_stats.items():
            count = stats["trade_count"]
            stats["win_rate"] = stats["winning_trades"] / count if count > 0 else 0.0
            pnls = [t.get("pnl", 0.0) for t in stats["trades"]]
            gross_profit = sum(p for p in pnls if p > 0)
            gross_loss = abs(sum(p for p in pnls if p < 0))
            stats["profit_factor"] = gross_profit / gross_loss if gross_loss > 0 else 0.0
            stats["avg_win"] = (
                stats["total_pnl"] / stats["winning_trades"] if stats["winning_trades"] > 0 else 0.0
            )
            stats["avg_loss"] = (
                stats["total_pnl"] / stats["losing_trades"] if stats["losing_trades"] > 0 else 0.0
            )
            # Clean up trades from output
            del stats["trades"]

        # Determine verdict
        if not regime_stats:
            verdict = "NO_DATA"
        else:
            avg_wrate = sum(s.get("win_rate", 0) for s in regime_stats.values()) / len(regime_stats)
            if avg_wrate >= 0.60:
                verdict = "EXCELLENT"
            elif avg_wrate >= 0.55:
                verdict = "GOOD"
            elif avg_wrate >= 0.50:
                verdict = "ACCEPTABLE"
            else:
                verdict = "POOR"

        best_regime = (
            max(regime_stats.items(), key=lambda x: x[1].get("total_pnl", 0))[0]
            if regime_stats
            else None
        )
        worst_regime = (
            min(regime_stats.items(), key=lambda x: x[1].get("total_pnl", 0))[0]
            if regime_stats
            else None
        )

        return {
            "regime_metrics": regime_stats,
            "overall_verdict": verdict,
            "best_regime": best_regime,
            "worst_regime": worst_regime,
            "regime_count": len(regime_stats),
        }

    except FileNotFoundError as e:
        logger.error(f"[REGIME-ANALYSIS] File error: {e}")
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        logger.error(f"[REGIME-ANALYSIS] Analysis failed: {e}")
        raise HTTPException(500, f"Regime analysis failed: {e}") from e


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

        results = {}

        # --- MNQ 1h ---
        try:
            if not data_manager:
                raise ValueError("data_manager not initialized")
            nq = await data_manager.get_bars("MNQ", lookback_days=10, timeframe="1h")
            if nq is not None and len(nq) >= 20:
                rc = RegimeClassifier()
                nq_classified = rc.classify(nq)
                last_regime = (
                    nq_classified["regime_type"].iloc[-1] if len(nq_classified) > 0 else "UNKNOWN"
                )
                # 30-day breakdown (use available bars)
                regime_counts = nq_classified["regime_type"].value_counts(normalize=True) * 100
                results["MNQ_1h"] = {
                    "current_regime": str(last_regime),
                    "regime_breakdown_30d": {str(k): round(v, 1) for k, v in regime_counts.items()},
                }
            else:
                raise ValueError("Insufficient MNQ data")
        except Exception:
            results["MNQ_1h"] = {
                "current_regime": "RANGING",
                "regime_breakdown_30d": {"TRENDING": 15.3, "RANGING": 80.5, "VOLATILE": 4.2},
            }

        # --- MGC 1d ---
        try:
            if not data_manager:
                raise ValueError("data_manager not initialized")
            gc = await data_manager.get_bars("MGC", lookback_days=60, timeframe="1d")
            if gc is not None and len(gc) >= 20:
                rc = RegimeClassifier()
                gc_classified = rc.classify(gc)
                last_regime = (
                    gc_classified["regime_type"].iloc[-1] if len(gc_classified) > 0 else "UNKNOWN"
                )
                last_row = gc_classified.iloc[-1]
                results["MGC_1d"] = {
                    "current_regime": str(last_regime),
                    "adaptive_stc_os": int(last_row.get("adaptive_stc_os", 15)),
                    "adaptive_stc_ob": int(last_row.get("adaptive_stc_ob", 92)),
                }
            else:
                raise ValueError("Insufficient MGC data")
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

    Fetches 200 daily bars via data_manager, runs the full indicator +
    regime + signal pipeline, and returns the last bar's signal with entry/exit
    levels.
    """
    from concurrent.futures import ThreadPoolExecutor

    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    # Fetch data asynchronously before entering the sync thread worker
    gc_df = await data_manager.get_bars("MGC", lookback_days=200, timeframe="1d")
    if gc_df is None or len(gc_df) < 50:
        raise HTTPException(503, "Insufficient MGC data from data_manager")

    def _generate_signal(gc):
        from backtest.paper_config import MGC_PAPER_CONFIG
        from backtest.signals import generate_signals

        # Run full signal pipeline with adaptive regime
        df = generate_signals(
            gc,
            symbol="MGC",
            adaptive_regime=True,
            regime_filter=True,
        )

        if df.empty:
            return {"error": "Signal generation returned empty DataFrame"}

        # Extract last bar
        last = df.iloc[-1]
        config = MGC_PAPER_CONFIG

        # Determine direction from bias
        bias = str(last.get("bias", "NEUTRAL"))
        if bias in ("STRONG_BULL", "LEAN_BULL"):
            direction = "LONG"
        elif bias in ("STRONG_BEAR", "LEAN_BEAR"):
            direction = "SHORT"
        else:
            direction = None

        entry_signal = str(last.get("entry_signal", "NO_TRADE"))
        regime_type = str(last.get("regime_type", "UNKNOWN"))

        # Map signal to simplified output
        if entry_signal == "ENTRY_NOW":
            signal = "ENTRY_NOW"
        elif entry_signal == "WAIT_FOR_PULLBACK":
            signal = "WAIT_FOR_PULLBACK"
        elif entry_signal == "FADE_EXTREME":
            signal = "FADE_EXTREME"
        else:
            signal = "NO_ENTRY"

        # Get date from index
        signal_date = (
            str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1])[:10]
        )

        return {
            "date": signal_date,
            "symbol": "MGC",
            "signal": signal,
            "direction": direction,
            "regime": regime_type,
            "adaptive_stc_os": int(last.get("adaptive_stc_os", 15)),
            "adaptive_stc_ob": int(last.get("adaptive_stc_ob", 92)),
            "entry_price": round(float(last["close"]), 2),
            "stop_level": round(float(last.get("stop_level", 0)), 2),
            "target_1": round(float(last.get("target_1", 0)), 2),
            "target_2": round(float(last.get("target_2", 0)), 2),
            "atr": round(float(last.get("atr", 0)), 2),
            "bias": bias,
            "stc_val": round(float(last.get("stc_val", 50)), 2),
            "stc_signal": str(last.get("stc_signal", "neutral")),
            "ema_trend": str(last.get("ema_trend", "neutral")),
            "config": f"adaptive_regime=ON, risk={config['risk_per_trade'] * 100:.2f}%",
        }

    try:
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, _generate_signal, gc_df)
        if "error" in result:
            raise HTTPException(503, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PAPER-MGC] Signal generation failed: {e}")
        raise HTTPException(500, f"MGC signal generation failed: {e}") from e


@app.post("/paper/mgc-log-trade")
async def log_mgc_paper_trade(req: MGCTradeLogRequest):
    """
    Log a completed MGC paper trade and return updated performance metrics.

    The trade is recorded via PaperTradeTracker (JSON persistence in
    backtest/results/paper_trades_MGC.json) with automatic P&L calculation
    including commission and slippage.
    """
    try:
        from backtest.paper_config import MGC_PAPER_CONFIG
        from backtest.paper_tracker import PaperTradeTracker

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
                trade_dict.get("pnl", 0)
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
        raise HTTPException(500, f"Failed to log MGC paper trade: {e}") from e


@app.get("/paper/mgc-performance")
async def get_mgc_paper_performance():
    """
    Return current MGC paper trading performance metrics.

    Reads from the PaperTradeTracker JSON store and returns:
    total trades, P&L, win rate, profit factor, max drawdown,
    regime breakdown, exit reason breakdown, and kill condition status.
    """
    try:
        from backtest.paper_config import MGC_PAPER_CONFIG
        from backtest.paper_tracker import PaperTradeTracker

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
        raise HTTPException(500, f"Failed to get MGC performance: {e}") from e


# ── Monte Carlo Backtest Analysis ────────────────────────────────────────────


class MonteCarloRequest(BaseModel):
    """Request for Monte Carlo simulation on backtest results."""

    results_file: str  # Path to JSON results file (relative to backtest/results/)
    simulations: int = 1_000  # Number of simulations (default: 1000)
    max_slippage_ticks: float = 0.0  # Max random slippage per trade in ticks (default: 0)
    symbol: str = None  # Instrument symbol (auto-detected if None)
    initial_capital: float = 100_000.0  # Starting capital for simulation


@app.post("/backtest/monte-carlo")
async def run_monte_carlo_analysis(req: MonteCarloRequest) -> dict:
    """
    Run Monte Carlo simulation on backtest results to validate strategy robustness.

    Shuffles trade order N times with optional slippage modeling to generate a
    distribution of possible outcomes. Returns percentile statistics across all
    simulations plus confidence metrics (probability of ruin, 2x return target, etc).

    Request:
        results_file: Path to backtest JSON (e.g., "MES_1h_2024-06-01_2026-03-27.json")
        simulations: Number of Monte Carlo runs (default: 1000)
        max_slippage_ticks: Uniform random slippage 0-N ticks per trade (default: 0)
        symbol: Instrument symbol for tick value lookup (auto if None)
        initial_capital: Starting capital (default: 100000)

    Returns:
        percentile_statistics: p5, p25, median, p75, p95 for final capital, max drawdown, Sharpe
        confidence_metrics: prob_profitable, prob_ruin, prob_2x, VaR 5%, CVaR
        verdict: EXCELLENT/GOOD/MARGINAL/POOR based on distribution quality
    """
    try:
        from pathlib import Path

        from backtest.monte_carlo import _load_result_from_json, run_monte_carlo

        # Resolve file path
        results_path = Path(req.results_file)
        if not results_path.is_absolute():
            # Try relative to backtest/results/
            alt_path = Path(__file__).parent / "backtest" / "results" / results_path.name
            if alt_path.exists():
                results_path = alt_path
            elif not results_path.exists():
                results_path = Path(__file__).parent / "backtest" / "results" / req.results_file

        if not results_path.exists():
            raise FileNotFoundError(f"Results file not found: {results_path}")

        # Load backtest result
        logger.info(f"[MONTE-CARLO] Loading {results_path.name}")
        bt_result = _load_result_from_json(str(results_path))

        # Auto-detect symbol from filename if not provided
        symbol = req.symbol
        if not symbol:
            stem = results_path.stem
            for part in stem.split("_"):
                if part.isupper() and len(part) <= 4:
                    symbol = part
                    break
        if not symbol:
            symbol = "MES"

        # Run simulation
        logger.info(f"[MONTE-CARLO] Running {req.simulations:,} simulations for {symbol}")
        mc_results = run_monte_carlo(
            bt_result,
            n_simulations=req.simulations,
            initial_capital=req.initial_capital,
            max_slippage_ticks=req.max_slippage_ticks,
            symbol=symbol,
            seed=42,
        )

        return mc_results

    except FileNotFoundError as e:
        logger.error(f"[MONTE-CARLO] File error: {e}")
        raise HTTPException(404, f"Results file not found: {e}") from e
    except Exception as e:
        logger.error(f"[MONTE-CARLO] Simulation failed: {e}")
        raise HTTPException(500, f"Monte Carlo simulation failed: {e}") from e


@app.post("/backtest/monte-carlo/chart")
async def generate_monte_carlo_chart(req: MonteCarloRequest) -> dict:
    """
    Generate an interactive HTML equity curve fan chart from Monte Carlo results.

    Creates a visualization showing median equity curve plus 25th-75th and 5th-95th
    percentile bands. Useful for assessing visual robustness and trade sequencing risk.

    Returns:
        chart_path: Full file path to generated HTML
        url: Relative URL if served via static files
    """
    try:
        from pathlib import Path

        from backtest.monte_carlo_viz import save_fan_chart

        # Resolve file path (same as monte-carlo endpoint)
        results_path = Path(req.results_file)
        if not results_path.is_absolute():
            alt_path = Path(__file__).parent / "backtest" / "results" / results_path.name
            if alt_path.exists():
                results_path = alt_path
            elif not results_path.exists():
                results_path = Path(__file__).parent / "backtest" / "results" / req.results_file

        if not results_path.exists():
            raise FileNotFoundError(f"Results file not found: {results_path}")

        # But we need the JSON results from run_monte_carlo first!
        # Check if _monte_carlo.json exists
        stem = results_path.stem
        mc_json_path = results_path.parent / f"{stem}_monte_carlo.json"
        if not mc_json_path.exists():
            raise FileNotFoundError(
                f"Monte Carlo JSON not found. Run /backtest/monte-carlo first to generate {mc_json_path.name}"
            )

        logger.info(f"[MONTE-CARLO-VIZ] Generating chart from {mc_json_path.name}")
        html_path = save_fan_chart(str(mc_json_path))

        return {
            "chart_path": str(html_path),
            "status": "success",
            "message": f"Chart generated: {Path(html_path).name}",
        }

    except FileNotFoundError as e:
        logger.error(f"[MONTE-CARLO-VIZ] File error: {e}")
        raise HTTPException(404, f"Error: {e}") from e
    except Exception as e:
        logger.error(f"[MONTE-CARLO-VIZ] Chart generation failed: {e}")
        raise HTTPException(500, f"Chart generation failed: {e}") from e


# ── WebSocket Real-Time Events ────────────────────────────────────────────


@app.websocket("/ws/events")
async def websocket_endpoint(websocket):
    """
    WebSocket endpoint for real-time trading events.

    Accepts connections at /ws/events.
    Sends JSON events for:
      - order_fill: Order execution
      - kill_switch: Kill switch state changes
      - circuit_breaker: Circuit breaker triggers
      - pipeline_complete: Pipeline analysis completion
      - safety_event: Safety/risk events
      - price_update: Price updates
      - ping: Keep-alive ping

    Connection is kept alive with ping frames every 30 seconds.
    Client is automatically removed on disconnect or send failure.
    """
    if not ws_manager:
        await websocket.close(code=1011, reason="WebSocket manager not initialized")
        return

    await ws_manager.connect(websocket)

    try:
        # Keep the connection alive and listen for client frames
        ping_interval = 30  # seconds
        last_ping = datetime.now()

        while True:
            try:
                # Receive with timeout to allow periodic ping
                data = await asyncio.wait_for(websocket.receive_json(), timeout=ping_interval)
                logger.debug(f"WebSocket received: {data.get('type', 'unknown')}")

            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                now = datetime.now()
                if (now - last_ping).total_seconds() >= ping_interval:
                    try:
                        await websocket.send_json({"type": "ping", "timestamp": now.isoformat()})
                        last_ping = now
                    except Exception as e:
                        logger.debug(f"Ping failed: {e}")
                        break

            except Exception as e:
                logger.debug(f"WebSocket receive error: {e}")
                break

    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        await ws_manager.disconnect(websocket)
        logger.info("WebSocket connection closed")


# ── WebSocket Status Endpoint ─────────────────────────────────────────────


@app.get("/ws/status")
async def websocket_status():
    """Get WebSocket manager status — connected client count."""
    if not ws_manager:
        return {"status": "not_initialized", "connections": 0}
    return {"status": "ok", "connections": ws_manager.get_connection_count()}


# ── Performance Report Endpoint ───────────────────────────────────────────────


@app.get("/reports/performance")
async def generate_performance_report(format: str = "html"):
    """Generate a self-contained HTML performance report."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        from datetime import datetime, timezone

        from analytics.performance import PerformanceCalculator

        calc = PerformanceCalculator(db_manager)
        summary = calc.calculate_summary()
        compare = calc.compare_to_backtest()

        # Get trade history
        trades = db_manager.get_trade_history(limit=200)
        daily_pnl = db_manager.get_daily_pnl(days=90)

        now = datetime.now(timezone.utc)

        # Build HTML report
        html = _build_performance_report_html(
            summary=summary,
            compare=compare,
            trades=trades,
            daily_pnl=daily_pnl,
            generated_at=now.isoformat(),
        )

        from fastapi.responses import HTMLResponse, Response

        if format == "html":
            return HTMLResponse(content=html)
        else:
            # Return as downloadable file
            return Response(
                content=html,
                media_type="text/html",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="jarvis-performance-{now.strftime("%Y%m%d")}.html"'
                    )
                },
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _build_performance_report_html(
    summary: dict,
    compare: dict,
    trades: list,
    daily_pnl: list,
    generated_at: str,
) -> str:
    """Build a self-contained HTML performance report."""

    def fmt_pct(v, decimals=1):
        if v is None:
            return "N/A"
        return f"{v * 100:.{decimals}f}%"

    def fmt_num(v, decimals=2):
        if v is None:
            return "N/A"
        return f"{v:.{decimals}f}"

    def fmt_usd(v):
        if v is None:
            return "N/A"
        return f"${v:,.2f}"

    # Summary metrics
    pf = summary.get("profit_factor")
    sharpe = summary.get("sharpe_ratio")
    win_rate = summary.get("win_rate")
    max_dd = summary.get("max_drawdown", 0)
    total_trades = summary.get("total_trades", 0)
    gross_pnl = summary.get("gross_pnl", 0)

    # Validation status
    pf_pass = pf and pf >= 2.0
    sharpe_pass = sharpe and sharpe >= 1.5

    pf_class = "pass" if pf_pass else ("fail" if pf else "neutral")
    pf_status_class = "pass" if pf_pass else "fail"
    pf_status_txt = "Pass (>= 2.0)" if pf_pass else ("Fail (>= 2.0)" if pf else "No data")

    sharpe_class = "pass" if sharpe_pass else ("fail" if sharpe else "neutral")
    sharpe_status_class = "pass" if sharpe_pass else "fail"
    sharpe_status_txt = (
        "Pass (>= 1.5)" if sharpe_pass else ("Fail (>= 1.5)" if sharpe else "No data")
    )

    gross_pnl_safe = gross_pnl or 0
    pnl_class = "pass" if gross_pnl_safe >= 0 else "fail"

    # Trade rows
    trade_rows = ""
    for t in trades[:100]:
        pnl = t.get("pnl", 0) or 0
        color = "#22c55e" if pnl >= 0 else "#ef4444"
        entry_price = t.get("entry_price", 0) or 0
        exit_price = t.get("exit_price", 0) or 0
        trade_rows += (
            "<tr>"
            f"<td>{t.get('symbol', '?')}</td>"
            f"<td>{t.get('side', '?').upper()}</td>"
            f"<td>{t.get('quantity', '?')}</td>"
            f"<td>${entry_price:.2f}</td>"
            f"<td>${exit_price:.2f}</td>"
            f'<td style="color:{color}">{fmt_usd(pnl)}</td>'
            f"<td>{str(t.get('entry_time', ''))[:10]}</td>"
            "</tr>"
        )

    # Daily P&L data for chart
    pnl_data = [r.get("realized_pnl", 0) for r in daily_pnl[-30:]]
    pnl_json = str(pnl_data).replace("None", "0")
    dates_json = str([str(r.get("date", ""))[:10] for r in daily_pnl[-30:]])

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "<title>JARVIS TRADER - Performance Report</title>\n"
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>\n'
        "<style>\n"
        "  * { box-sizing: border-box; margin: 0; padding: 0; }\n"
        "  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;\n"
        "          background: #0a0a0a; color: #e5e5e5; padding: 24px; }\n"
        "  h1 { font-size: 1.5rem; margin-bottom: 4px; }\n"
        "  .subtitle { color: #6b6b6b; font-size: 0.875rem; margin-bottom: 24px; }\n"
        "  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));"
        " gap: 12px; margin-bottom: 24px; }\n"
        "  .card { background: #161616; border: 1px solid #262626; border-radius: 8px; padding: 16px; }\n"
        "  .card-label { font-size: 0.75rem; color: #6b6b6b; text-transform: uppercase; letter-spacing: 0.05em; }\n"
        "  .card-value { font-size: 1.5rem; font-weight: 600; margin-top: 4px; }\n"
        "  .card-status { font-size: 0.75rem; margin-top: 4px; }\n"
        "  .pass { color: #22c55e; }\n"
        "  .fail { color: #ef4444; }\n"
        "  .neutral { color: #6b6b6b; }\n"
        "  .section { background: #161616; border: 1px solid #262626; border-radius: 8px;"
        " padding: 20px; margin-bottom: 16px; }\n"
        "  .section h2 { font-size: 1rem; margin-bottom: 16px; color: #a3a3a3; }\n"
        "  table { width: 100%; border-collapse: collapse; font-size: 0.8125rem; }\n"
        "  th { text-align: left; padding: 8px 12px; border-bottom: 1px solid #262626;"
        " color: #6b6b6b; font-weight: 500; }\n"
        "  td { padding: 8px 12px; border-bottom: 1px solid #1a1a1a; }\n"
        "  tr:hover td { background: #1a1a1a; }\n"
        "  canvas { max-height: 200px; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<h1>JARVIS TRADER - Performance Report</h1>\n"
        f'<p class="subtitle">Generated {generated_at[:10]} | Paper Trading Phase</p>\n'
        "\n"
        '<div class="grid">\n'
        '  <div class="card">\n'
        '    <div class="card-label">Profit Factor</div>\n'
        f'    <div class="card-value {pf_class}">{fmt_num(pf)}</div>\n'
        f'    <div class="card-status {pf_status_class}">{pf_status_txt}</div>\n'
        "  </div>\n"
        '  <div class="card">\n'
        '    <div class="card-label">Sharpe Ratio</div>\n'
        f'    <div class="card-value {sharpe_class}">{fmt_num(sharpe)}</div>\n'
        f'    <div class="card-status {sharpe_status_class}">{sharpe_status_txt}</div>\n'
        "  </div>\n"
        '  <div class="card">\n'
        '    <div class="card-label">Win Rate</div>\n'
        f'    <div class="card-value neutral">{fmt_pct(win_rate)}</div>\n'
        '    <div class="card-status neutral">Target &gt;= 50%</div>\n'
        "  </div>\n"
        '  <div class="card">\n'
        '    <div class="card-label">Max Drawdown</div>\n'
        f'    <div class="card-value fail">{fmt_pct(max_dd)}</div>\n'
        '    <div class="card-status neutral">Limit &lt;= -15%</div>\n'
        "  </div>\n"
        '  <div class="card">\n'
        '    <div class="card-label">Total Trades</div>\n'
        f'    <div class="card-value neutral">{total_trades}</div>\n'
        '    <div class="card-status neutral">Target &gt;= 30</div>\n'
        "  </div>\n"
        '  <div class="card">\n'
        '    <div class="card-label">Gross P&amp;L</div>\n'
        f'    <div class="card-value {pnl_class}">{fmt_usd(gross_pnl)}</div>\n'
        '    <div class="card-status neutral">Paper account</div>\n'
        "  </div>\n"
        "</div>\n"
        "\n"
        '<div class="section">\n'
        "  <h2>Daily P&amp;L - Last 30 Days</h2>\n"
        '  <canvas id="pnlChart"></canvas>\n'
        "</div>\n"
        "\n"
        '<div class="section">\n'
        "  <h2>Trade History (latest 100)</h2>\n"
        "  <table>\n"
        "    <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th>"
        "<th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Date</th></tr></thead>\n"
        f"    <tbody>{trade_rows}</tbody>\n"
        "  </table>\n"
        "</div>\n"
        "\n"
        "<script>\n"
        "const ctx = document.getElementById('pnlChart').getContext('2d');\n"
        f"const pnlData = {pnl_json};\n"
        f"const labels = {dates_json};\n"
        "new Chart(ctx, {\n"
        "  type: 'bar',\n"
        "  data: {\n"
        "    labels: labels,\n"
        "    datasets: [{\n"
        "      label: 'Daily P&L',\n"
        "      data: pnlData,\n"
        "      backgroundColor: pnlData.map(v => v >= 0 ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)'),\n"
        "      borderColor: pnlData.map(v => v >= 0 ? '#22c55e' : '#ef4444'),\n"
        "      borderWidth: 1,\n"
        "    }],\n"
        "  },\n"
        "  options: {\n"
        "    responsive: true,\n"
        "    plugins: { legend: { display: false } },\n"
        "    scales: {\n"
        "      x: { ticks: { color: '#6b6b6b', maxTicksLimit: 10 } },\n"
        "      y: { ticks: { color: '#6b6b6b' }, grid: { color: '#1a1a1a' } },\n"
        "    },\n"
        "  },\n"
        "});\n"
        "</script>\n"
        "</body>\n"
        "</html>"
    )


@app.get("/portfolio/stats/session-today")
async def get_todays_session():
    """Get today's trading session stats (current calendar day in CT)."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        import sqlite3
        from datetime import datetime, timezone

        import pytz

        ct = pytz.timezone("America/Chicago")
        now_ct = datetime.now(ct)
        today_ct = now_ct.strftime("%Y-%m-%d")

        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                cursor = conn.execute(
                    """SELECT pnl, side, symbol, quantity, entry_price, exit_price, entry_time, exit_time
                       FROM paper_trades
                       WHERE status = 'closed'
                         AND date(exit_time) = ?
                       ORDER BY exit_time ASC""",
                    (today_ct,),
                )
                cols = [d[0] for d in cursor.description]
                trades = [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]

                # Open positions opened today
                cursor2 = conn.execute(
                    """SELECT symbol, side, quantity, entry_price, entry_time
                       FROM paper_trades
                       WHERE status = 'open'
                         AND date(entry_time) = ?""",
                    (today_ct,),
                )
                cols2 = [d[0] for d in cursor2.description]
                open_today = [dict(zip(cols2, row, strict=False)) for row in cursor2.fetchall()]
            finally:
                conn.close()

        pnls = [float(t.get("pnl", 0) or 0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        gross_pnl = sum(pnls)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / len(pnls) if pnls else None

        return {
            "date": today_ct,
            "session": "RTH" if 8 <= now_ct.hour < 15 else "EXTENDED",
            "closed_trades": len(trades),
            "open_trades": len(open_today),
            "gross_pnl": round(gross_pnl, 2),
            "wins": win_count,
            "losses": loss_count,
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "best_trade": round(max(pnls), 2) if pnls else None,
            "worst_trade": round(min(pnls), 2) if pnls else None,
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else None,
            "symbols_traded": list({t.get("symbol") for t in trades}),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/portfolio/stats/commissions")
async def get_commission_stats():
    """
    Estimate total commissions paid during paper trading phase.
    MES: $1.57/contract/side (CME exchange + NFA + brokerage estimate)
    MNQ: $1.57/contract/side
    MCL: $2.05/contract/side
    """
    if db_manager is None:
        raise HTTPException(status_code=503, detail="DB not initialized")
    try:
        RATES = {"MES": 1.57, "MNQ": 1.57, "MCL": 2.05, "DEFAULT": 1.57}
        trades = db_manager.get_trade_history(limit=10000)
        total_commissions = 0.0
        by_symbol: dict[str, float] = {}
        for t in trades:
            sym = (t.get("symbol") or "").upper()
            qty = int(t.get("quantity") or 1)
            rate = RATES.get(sym, RATES["DEFAULT"])
            commission = rate * qty * 2  # entry + exit
            total_commissions += commission
            by_symbol[sym] = by_symbol.get(sym, 0.0) + commission

        # Net PnL after commissions
        gross_pnl = sum(float(t.get("pnl") or 0) for t in trades if t.get("status") == "closed")
        net_pnl = gross_pnl - total_commissions

        return {
            "total_commissions": round(total_commissions, 2),
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "by_symbol": {k: round(v, 2) for k, v in by_symbol.items()},
            "trade_count": len(trades),
            "avg_commission_per_trade": round(total_commissions / max(len(trades), 1), 2),
            "rates": RATES,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/analytics/trades/by-day")
async def get_trades_by_day():
    """Day-of-week breakdown of paper trade performance.
    Returns win rate, avg pnl, count for each day (Mon-Fri).
    """
    try:
        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                rows = conn.execute(
                    """SELECT
                         strftime('%w', exit_time) AS dow,
                         COUNT(*) AS cnt,
                         SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                         SUM(pnl) AS total_pnl,
                         AVG(pnl) AS avg_pnl
                       FROM paper_trades
                       WHERE status = 'closed' AND exit_time IS NOT NULL
                       GROUP BY dow
                       ORDER BY dow"""
                ).fetchall()
            finally:
                conn.close()

        DAY_NAMES = {
            "0": "Sun",
            "1": "Mon",
            "2": "Tue",
            "3": "Wed",
            "4": "Thu",
            "5": "Fri",
            "6": "Sat",
        }
        result = []
        for row in rows:
            dow, cnt, wins, total_pnl, avg_pnl = row
            result.append(
                {
                    "day": DAY_NAMES.get(str(dow), str(dow)),
                    "count": cnt,
                    "wins": wins,
                    "losses": cnt - wins,
                    "win_rate": round(wins / cnt, 3) if cnt > 0 else 0.0,
                    "total_pnl": round(total_pnl or 0, 2),
                    "avg_pnl": round(avg_pnl or 0, 2),
                }
            )
        return {"days": result, "total_days_analyzed": len(result)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/analytics/trades/by-symbol")
async def get_trades_by_symbol():
    """Per-symbol breakdown of paper trade performance."""
    try:
        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                rows = conn.execute(
                    """SELECT
                         symbol,
                         COUNT(*) AS cnt,
                         SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                         SUM(pnl) AS total_pnl,
                         AVG(pnl) AS avg_pnl,
                         MAX(pnl) AS best_trade,
                         MIN(pnl) AS worst_trade
                       FROM paper_trades
                       WHERE status = 'closed'
                       GROUP BY symbol
                       ORDER BY total_pnl DESC"""
                ).fetchall()
            finally:
                conn.close()

        result = []
        for row in rows:
            symbol, cnt, wins, total_pnl, avg_pnl, best, worst = row
            result.append(
                {
                    "symbol": symbol,
                    "count": cnt,
                    "wins": wins,
                    "losses": cnt - wins,
                    "win_rate": round(wins / cnt, 3) if cnt > 0 else 0.0,
                    "total_pnl": round(total_pnl or 0, 2),
                    "avg_pnl": round(avg_pnl or 0, 2),
                    "best_trade": round(best or 0, 2),
                    "worst_trade": round(worst or 0, 2),
                }
            )
        return {"symbols": result, "total_symbols": len(result)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/alerts/history")
async def get_alert_history(limit: int = 100, alert_type: str | None = None):
    """Return recent alert log entries."""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="DB not initialized")
    try:
        rows = db_manager.get_alert_history(limit=min(limit, 500), alert_type=alert_type)
        return {"alerts": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/alerts/stats")
async def get_alert_stats():
    """Return alert counts grouped by type and status."""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="DB not initialized")
    try:
        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                cursor = conn.execute("""
                    SELECT alert_type, status, COUNT(*) as count
                    FROM alert_log
                    GROUP BY alert_type, status
                    ORDER BY count DESC
                """)
                rows = [
                    {"alert_type": r[0], "status": r[1], "count": r[2]} for r in cursor.fetchall()
                ]
                total_cursor = conn.execute("SELECT COUNT(*) FROM alert_log")
                total = total_cursor.fetchone()[0]
            finally:
                conn.close()
        return {"stats": rows, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/portfolio/import/trades")
async def import_paper_trades(request: Request):
    """Bulk import paper trades from JSON array.

    Body: {"trades": [{"symbol": "MES", "action": "LONG", "entry_price": 5000.0,
                       "exit_price": 5010.0, "quantity": 1, "pnl": 50.0,
                       "entry_time": "2026-03-01T09:30:00Z",
                       "exit_time": "2026-03-01T10:00:00Z"}, ...]}
    Returns: {"imported": N, "skipped": 0, "errors": []}
    """
    try:
        body = await request.json()
        trades = body.get("trades", [])
        if not isinstance(trades, list):
            raise HTTPException(status_code=400, detail="'trades' must be a list")
        if len(trades) > 1000:
            raise HTTPException(status_code=400, detail="Max 1000 trades per import")

        imported = 0
        errors = []

        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                for i, t in enumerate(trades):
                    try:
                        import uuid as _uuid

                        trade_id = t.get("trade_id") or str(_uuid.uuid4())
                        conn.execute(
                            """INSERT OR IGNORE INTO paper_trades
                               (trade_id, symbol, side, entry_price, exit_price, quantity,
                                pnl, status, entry_time, exit_time, strategy_params, notes)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                trade_id,
                                str(t.get("symbol", "UNKNOWN")),
                                str(t.get("action", t.get("side", "LONG"))),
                                float(t.get("entry_price", 0)),
                                float(t.get("exit_price", 0)),
                                int(t.get("quantity", 1)),
                                float(t.get("pnl", 0)),
                                "CLOSED",
                                str(t.get("entry_time", datetime.now(timezone.utc).isoformat())),
                                str(t.get("exit_time", datetime.now(timezone.utc).isoformat())),
                                str(t.get("strategy", t.get("strategy_params", "imported"))),
                                str(t.get("notes", "")),
                            ),
                        )
                        imported += 1
                    except Exception as e:
                        errors.append({"index": i, "error": str(e)})
                conn.commit()
            finally:
                conn.close()

        return {"imported": imported, "skipped": len(errors), "errors": errors[:10]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/analytics/trades/by-hour")
async def get_trades_by_hour():
    """Hour-of-day trade performance breakdown."""
    try:
        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    CAST(strftime('%H', exit_time) AS INTEGER) as hour,
                    COUNT(*) as count,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                    ROUND(SUM(pnl), 2) as total_pnl,
       