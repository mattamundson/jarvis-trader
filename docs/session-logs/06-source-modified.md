# Modified Engine Files — Full Source

These files existed before the session and were modified.
Full source included so diffs can be inferred by comparing to git history.


### `engine/config.py`
```python
"""
JARVIS TRADER — Configuration
All settings via environment variables (.env file).
Never hardcode secrets.
"""

import os
import sys
from typing import Optional, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _validate_required_env_vars():
    """
    Startup validation: ensure all required environment variables are set and non-empty.
    Called after TradingConfig initialization to catch missing critical secrets early.
    Fails fast with clear error messages pointing to missing variables.

    NOTE: pydantic-settings loads .env into model fields but does NOT write back to
    os.environ. We load dotenv explicitly here so os.environ.get() sees the .env values.
    """
    # Load .env into os.environ so the checks below see file-based values
    try:
        from dotenv import load_dotenv as _load_dotenv

        _load_dotenv(dotenv_path=".env", override=False)
    except ImportError:
        pass  # python-dotenv not installed — fall back to os.environ only

    required_vars = {
        # API Security — must be set to something other than the default stub
        "API_KEY": "FastAPI X-API-Key header authentication (use strong random value)",
    }

    optional_vars = {
        # Databases — engine uses SQLite for paper trading; Postgres/Redis are
        # legacy requirements that are not needed for paper trading mode.
        "POSTGRES_URL": "PostgreSQL connection (only needed for multi-instance deployments)",
        "REDIS_URL": "Redis connection (only needed for caching/rate-limiting at scale)",
        # Market Data
        "POLYGON_API_KEY": "Polygon.io API key for market data (falls back to yfinance)",
        # LLM pipeline — engine runs signal generation without Anthropic key;
        # LLM agents are skipped if this is absent.
        "ANTHROPIC_API_KEY": "Anthropic API key (sk-ant-api03-...) — enables LLM agent pipeline",
        # Other market data sources
        "FINNHUB_API_KEY": "Alternative market data source",
        "ALPACA_API_KEY": "Alpaca Markets integration",
        "SCHWAB_APP_KEY": "Charles Schwab OAuth (for live trading)",
        "TWILIO_ACCOUNT_SID": "Twilio WhatsApp alerts",
        "TWILIO_AUTH_TOKEN": "Twilio authentication",
        "TWILIO_WHATSAPP_FROM": "Twilio sender number",
        "WHATSAPP_TO": "WhatsApp alert recipient",
    }

    missing_critical = []
    missing_warnings = []

    # Check critical variables
    for var_name, description in required_vars.items():
        value = os.environ.get(var_name, "").strip()
        if not value:
            missing_critical.append((var_name, description))

    # Check optional variables (warn but don't fail)
    for var_name, description in optional_vars.items():
        value = os.environ.get(var_name, "").strip()
        if not value:
            missing_warnings.append((var_name, description))

    # If critical variables missing, fail with detailed error
    if missing_critical:
        error_message = "\n" + "=" * 80 + "\n"
        error_message += "STARTUP ERROR: Missing Required Environment Variables\n"
        error_message += "=" * 80 + "\n\n"

        for var_name, description in missing_critical:
            error_message += f"  {var_name}\n"
            error_message += f"    └─ {description}\n\n"

        error_message += "How to fix:\n"
        error_message += "  1. Copy .env.example to .env:\n"
        error_message += "     cp .env.example .env\n\n"
        error_message += "  2. Edit .env and populate all required variables with real values:\n"
        error_message += "     nano .env\n\n"
        error_message += "  3. NEVER commit .env — it's in .gitignore for your protection\n\n"
        error_message += "  4. Verify .env is loaded:\n"
        error_message += (
            "     source .env && python -c \"import os; print(os.getenv('API_KEY'))\"\n\n"
        )
        error_message += "=" * 80 + "\n"

        print(error_message, file=sys.stderr)
        sys.exit(1)

    # Warn about optional variables
    if missing_warnings:
        print("\n" + "=" * 80, file=sys.stderr)
        print(
            "WARNING: Some optional features will not work without these variables:",
            file=sys.stderr,
        )
        print("=" * 80 + "\n", file=sys.stderr)

        for var_name, description in missing_warnings:
            print(f"  {var_name}", file=sys.stderr)
            print(f"    └─ {description}\n", file=sys.stderr)

        print(
            "These features are optional. If you don't need them, you can ignore this warning.\n",
            file=sys.stderr,
        )
        print("=" * 80 + "\n", file=sys.stderr)


class TradingConfig(BaseSettings):
    """Risk parameters — all configurable, never LLM-modifiable"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Risk Controls (Safety Layer) ─────────────────────────────────────
    MAX_POSITION_SIZE_PCT: float = Field(0.05, description="Max 5% of portfolio per position")
    MAX_DAILY_LOSS_PCT: float = Field(0.02, description="Halt trading at -2% daily P&L")
    MAX_DRAWDOWN_PCT: float = Field(0.10, description="Emergency halt at -10% from equity peak")
    MAX_ORDERS_PER_MINUTE: int = Field(10, description="Rate throttle")
    MAX_CORRELATED_EXPOSURE_PCT: float = Field(0.20, description="Max 20% in correlated positions")
    PRICE_COLLAR_PCT: float = Field(0.05, description="Reject orders >5% from NBBO")
    MAX_SINGLE_ORDER_VALUE: float = Field(5000.0, description="No single order > $5,000")
    MAX_MARGIN_UTILIZATION: float = Field(0.40, description="Never exceed 40% of available margin")

    # ── Futures-Specific ─────────────────────────────────────────────────
    MAX_CONTRACTS_PER_INSTRUMENT: int = Field(2, description="Max micro contracts per instrument")
    MAX_OVERNIGHT_CONTRACTS: int = Field(1, description="Max contracts to hold overnight")

    # ── Consecutive Loss Tracking & Position Sizing ──────────────────────
    CONSECUTIVE_LOSS_HALF_SIZE: int = Field(
        3, description="Losses threshold for 0.5x position size"
    )
    CONSECUTIVE_LOSS_QUARTER_SIZE: int = Field(
        5, description="Losses threshold for 0.25x position size"
    )
    CONSECUTIVE_LOSS_HALT: int = Field(7, description="Losses threshold for trading halt")
    CONSECUTIVE_LOSS_HALT_HOURS: int = Field(24, description="Duration (hours) of trading halt")

    # ── Autonomy Tier ─────────────────────────────────────────────────────
    LIVE_TRADING_ENABLED: bool = Field(False, description="Set True to enable live trading")
    REQUIRE_HUMAN_APPROVAL: bool = Field(
        True, description="All live trades require Matt's approval"
    )

    ALLOW_PAPER_SIMULATED_ORDERS: bool = Field(
        False,
        description="When True, paper trading mode allows simulated orders via check_order route",
    )

    # ── Capital ────────────────────────────────────────────────────────────
    INITIAL_CAPITAL: float = Field(
        10000.0,
        description="Starting paper account balance in USD. Used by PnLMonitor when no broker equity is available.",
    )

    # ── Paper Trading Mode ─────────────────────────────────────────────────
    PAPER_TRADING: bool = Field(
        True,
        description="Set False only after 30-day forward test passes. Orders logged but NOT sent to broker when True.",
    )
    PAPER_TRADING_BROKER: str = Field(
        "IB_GATEWAY",
        description="Broker used for paper trading (IB_GATEWAY for Interactive Brokers Gateway)",
    )

    # ── Broker: Interactive Brokers ───────────────────────────────────────
    IBKR_HOST: str = Field("127.0.0.1", description="IB Gateway host")
    IBKR_PORT: int = Field(4002, description="4001=live, 4002=paper")
    IBKR_CLIENT_ID: int = Field(1, description="Client ID for IB Gateway connection")
    IBKR_PAPER_MODE: bool = Field(True, description="Always start in paper mode")

    # ── Broker: Charles Schwab ────────────────────────────────────────────
    SCHWAB_APP_KEY: Optional[str] = Field(default=None, description="Charles Schwab app key")
    SCHWAB_APP_SECRET: Optional[str] = Field(default=None, description="Charles Schwab app secret")
    SCHWAB_CALLBACK_URL: str = Field(
        "https://127.0.0.1", description="Charles Schwab OAuth callback URL"
    )

    # ── Market Data ───────────────────────────────────────────────────────
    POLYGON_API_KEY: Optional[str] = Field(default=None, description="Polygon.io API key")
    FRED_API_KEY: Optional[str] = Field(default=None, description="Federal Reserve FRED API key")
    FINNHUB_API_KEY: Optional[str] = Field(default=None, description="Finnhub API key")
    ALPACA_API_KEY: Optional[str] = Field(default=None, description="Alpaca Markets API key")
    ALPACA_SECRET_KEY: Optional[str] = Field(default=None, description="Alpaca Markets secret key")
    ALPACA_PAPER: bool = Field(default=True, description="Use Alpaca paper trading")

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = Field(
        "INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL"
    )

    # ── API Security ──────────────────────────────────────────────────────────
    API_KEY: Optional[str] = Field(
        default=None,
        description="FastAPI X-API-Key header authentication (must be set explicitly in .env)",
    )

    # ── LLM (Vercel AI Gateway via OIDC) ─────────────────────────────────
    # These are auto-provisioned by `vercel env pull` — no manual API keys needed
    ANTHROPIC_API_KEY: Optional[str] = Field(
        default=None, description="Anthropic API key for LLM agent pipeline"
    )
    LLM_PROVIDER: str = Field("anthropic", description="LLM provider")

    # ── Agent Models ──────────────────────────────────────────────────────
    ANALYST_MODEL: str = Field("claude-sonnet-4-6", description="Model for analyst agents")
    TRADER_MODEL: str = Field("claude-opus-4-6", description="Model for trader/risk/fund manager")
    FAST_MODEL: str = Field("claude-haiku-4-5-20251001", description="Model for fast/cheap ops")

    # ── Databases ─────────────────────────────────────────────────────────
    POSTGRES_URL: str = Field("postgresql://jarvis:jarvis@localhost:5432/jarvis_trader")
    REDIS_URL: str = Field("redis://localhost:6379")
    QUESTDB_HOST: str = Field("localhost")
    QUESTDB_PORT: int = Field(9000)

    # ── Notifications (WhatsApp via Twilio) ───────────────────────────────
    TWILIO_ACCOUNT_SID: Optional[str] = Field(default=None, description="Twilio account SID")
    TWILIO_AUTH_TOKEN: Optional[str] = Field(default=None, description="Twilio auth token")
    TWILIO_WHATSAPP_FROM: Optional[str] = Field(default=None, description="Twilio WhatsApp sender")
    WHATSAPP_TO: Optional[str] = Field(default=None, description="WhatsApp recipient number")

    # ── Instruments to Trade ─────────────────────────────────────────────
    FUTURES_WATCHLIST: Union[str, list[str]] = Field(
        default="MES,MNQ,MCL",
        description="Micro futures contracts to trade (comma-separated or list)",
    )
    OPTIONS_WATCHLIST: Union[str, list[str]] = Field(
        default=["SPY", "QQQ", "AAPL", "TSLA"], description="Underlying symbols for options trading"
    )

    @field_validator("FUTURES_WATCHLIST", "OPTIONS_WATCHLIST", mode="before")
    @classmethod
    def parse_watchlist(cls, v):
        """
        Parse list fields from comma-separated string or JSON array.
        Supports both formats:
        - Comma-separated: "MCL,MNQ"
        - JSON array: ["MCL", "MNQ"]
        Returns: list[str]
        """
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                try:
                    return json.loads(v)
                except (json.JSONDecodeError, ValueError):
                    pass
            return [item.strip().strip("\"'") for item in v.split(",") if item.strip()]
        return v

    @field_validator("API_KEY", mode="after")
    @classmethod
    def validate_api_key_not_default(cls, v):
        """
        Fail fast if API_KEY is not explicitly set.
        Raises an error if API_KEY is None or a known placeholder value.
        """
        if v is None or (isinstance(v, str) and v.strip() == ""):
            raise ValueError(
                "API_KEY must be explicitly set to a real value. "
                "Edit .env and set API_KEY to a strong random string. "
                "Example: API_KEY=your-secret-api-key-here"
            )
        if v == "CHANGE_ME_BEFORE_DEPLOY":
            raise ValueError(
                "API_KEY must be explicitly set to a real value. "
                "Found placeholder: 'CHANGE_ME_BEFORE_DEPLOY'. "
                "Edit .env and set API_KEY to a strong random string."
            )
        return v


# ── Module-level singleton ────────────────────────────────────────────────
# Used by all engine modules via `from config import settings`
settings = TradingConfig()

```

### `engine/agents/pipeline.py`
```python
"""
JARVIS TRADER — Trading Pipeline
===================================
Orchestrates the complete multi-agent analysis and decision pipeline for a symbol.

Pipeline order:
  1. Analyst stage (parallel):  technical, news, social, fundamental
  2. Debate stage:               bull agent + bear agent → debate orchestrator
  3. Trader:                     synthesizes everything → TradeDecision
  4. Risk Manager:               validates TradeDecision → RiskDecision
  5. Fund Manager:               portfolio-level final approval → FundDecision

All intermediate results are preserved in the returned pipeline_result dict
for audit logging, dashboards, and post-trade review.

The pipeline is non-blocking at each stage — if an analyst fails it returns
a neutral/empty report and the pipeline continues. Failures are logged and
captured in pipeline_result["errors"].
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from database import repository

try:
    from cache import (
        cache_signal,
        get_cached_signal,
        should_use_cache,
    )

    _CACHE_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _CACHE_AVAILABLE = False

try:
    _WA_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _WA_AVAILABLE = False

logger = logging.getLogger(__name__)

__all__ = ["TradingPipeline"]


class TradingPipeline:
    """
    Runs the complete multi-agent analysis pipeline for a single symbol.

    Required agents dict keys:
        technical     — TechnicalAnalystAgent
        news          — NewsAnalystAgent
        social        — (any agent with .analyze(symbol) → report with .to_dict())
        fundamental   — (any agent with .analyze(symbol) → report with .to_dict())
        bull          — (any agent with .argue(symbol, analyst_reports) → dict)
        bear          — (any agent with .argue(symbol, analyst_reports) → dict)
        debate        — DebateOrchestrator with .run_debate(bull_arg, bear_arg) → dict
        trader        — TraderAgent
        risk_manager  — RiskManagerAgent
        fund_manager  — FundManagerAgent

    All agents are optional — the pipeline degrades gracefully when absent.
    """

    def __init__(self, agents: dict, safety_layer, db_manager=None, context_manager=None):
        """
        Args:
            agents:          Dict of named agent instances (see class docstring)
            safety_layer:    SafetyLayer instance — provides get_status() and kill switch
            db_manager:      Optional DatabaseManager — if set, pipeline runs are persisted
            context_manager: Optional context manager instance for pipeline execution context
        """
        self._agents = agents
        self._safety = safety_layer
        self.db_manager = db_manager
        self.context_manager = context_manager

    async def analyze_and_decide(
        self,
        symbol: str,
        is_futures: bool = True,
        timeframe: str = "1h",
    ) -> dict:
        """
        Run the full pipeline for a symbol.

        Returns a pipeline_result dict containing:
            symbol              str
            is_futures          bool
            started_at          ISO timestamp
            completed_at        ISO timestamp
            analyst_reports     dict (technical, news, social, fundamental)
            debate_result       dict
            trade_decision      dict  (TradeDecision.to_dict())
            risk_decision       dict  (RiskDecision.to_dict())
            fund_decision       dict  (FundDecision.to_dict()) — present if risk approved
            final_action        str   "buy" | "sell" | "hold" | "pending_human_approval"
            final_quantity      int
            requires_human      bool
            errors              list[str]  — any non-fatal errors encountered
        """
        started_at = datetime.now()
        errors: list[str] = []
        pipeline_result: dict[str, Any] = {
            "symbol": symbol,
            "is_futures": is_futures,
            "started_at": started_at.isoformat(),
            "errors": errors,
        }

        logger.info(f"[Pipeline] Starting analysis for {symbol} (futures={is_futures})")

        # ── Cache Check: Return early if valid cached signal exists ────────────────
        if _CACHE_AVAILABLE:
            # Check if cached signal should be used (regime hasn't changed)
            if await should_use_cache(symbol):
                cached = await get_cached_signal(symbol)
                if cached:
                    logger.info(
                        f"[Pipeline] {symbol} cache hit — skipping full pipeline (saves LLM calls)"
                    )
                    cached["cache_hit"] = True
                    # Update completed_at timestamp for response
                    cached["completed_at"] = datetime.now().isoformat()
                    return cached

        # ── Stage 1: Analysts in parallel ─────────────────────────────────

        analyst_reports = await self._run_analysts(symbol, is_futures, errors, timeframe=timeframe)
        pipeline_result["analyst_reports"] = analyst_reports

        # ── Stage 2: Bull/Bear Debate ──────────────────────────────────────

        debate_result = await self._run_debate(symbol, analyst_reports, errors)
        pipeline_result["debate_result"] = debate_result

        # ── Stage 3: Trader Decision ───────────────────────────────────────

        safety_status = self._safety.get_status()
        trade_decision = await self._run_trader(
            symbol, debate_result, analyst_reports, safety_status, errors
        )
        pipeline_result["trade_decision"] = trade_decision

        # ── Stage 4: Risk Manager Review ──────────────────────────────────

        # We always pass an empty portfolio if none is available — callers should
        # inject a real portfolio dict via a wrapper or subclass
        portfolio = await self._get_portfolio()
        risk_decision = await self._run_risk_manager(
            trade_decision, safety_status, portfolio, errors
        )
        pipeline_result["risk_decision"] = risk_decision

        # ── Stage 5: Fund Manager (only if Risk Manager approved) ──────────

        fund_decision: Optional[dict] = None
        if risk_decision.get("approved", False):
            open_positions = portfolio.get("positions", [])
            fund_decision = await self._run_fund_manager(
                trade_decision, risk_decision, portfolio, open_positions, errors
            )
        else:
            logger.info(f"[Pipeline] Risk Manager vetoed {symbol} — skipping Fund Manager")

        pipeline_result["fund_decision"] = fund_decision

        # ── Resolve final action ───────────────────────────────────────────

        final_action, final_quantity, requires_human = self._resolve_final_action(
            trade_decision, risk_decision, fund_decision
        )
        pipeline_result["final_action"] = final_action
        pipeline_result["final_quantity"] = final_quantity
        pipeline_result["requires_human"] = requires_human

        completed_at = datetime.now()
        pipeline_result["completed_at"] = completed_at.isoformat()
        elapsed = (completed_at - started_at).total_seconds()

        # ── Human-readable summary line ────────────────────────────────────────
        regime = analyst_reports.get("technical", {}).get("regime", "UNKNOWN")
        trend = analyst_reports.get("technical", {}).get("trend", "UNKNOWN")
        confidence = fund_decision.get("final_conviction", 0.0) if fund_decision else 0.0
        pipeline_result["summary"] = (
            f"{symbol} | regime={regime} trend={trend} | "
            f"action={final_action.upper()} qty={final_quantity} | "
            f"conviction={confidence:.0%} human={requires_human}"
        )

        logger.info(
            f"[Pipeline] {symbol} complete in {elapsed:.1f}s — "
            f"final_action={final_action} qty={final_quantity} "
            f"requires_human={requires_human} errors={len(errors)}"
        )

        # ── Log decisions to PostgreSQL (audit trail) ──────────────────────────
        await self._log_pipeline_to_postgres(symbol, pipeline_result, trade_decision, errors)

        # ── Cache the pipeline result (signal caching for next 30 minutes) ───────────
        if _CACHE_AVAILABLE:
            try:
                await cache_signal(symbol, pipeline_result)
                logger.debug(f"[Pipeline] Cached signal for {symbol} (TTL=30min)")
            except Exception as e:
                logger.debug(f"[Pipeline] Failed to cache signal: {e}")

        # Emit WebSocket event for pipeline completion
        try:
            from websocket.events import emit_pipeline_complete

            timing = {
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "elapsed_seconds": elapsed,
            }
            asyncio.create_task(emit_pipeline_complete(symbol, final_action, timing))
        except ImportError:
            # WebSocket module may not be available in all contexts (e.g., backtesting)
            pass
        except Exception as e:
            logger.debug(f"Failed to emit pipeline_complete event: {e}")

        # Add cache_hit flag for logging
        pipeline_result["cache_hit"] = False
        return pipeline_result

    # ── Stage Runners ──────────────────────────────────────────────────────

    async def _run_analysts(
        self,
        symbol: str,
        is_futures: bool,
        errors: list,
        timeframe: str = "1h",
    ) -> dict:
        """Run all four analysts concurrently via asyncio.gather."""

        async def safe_analyze(name: str, coro) -> dict:
            try:
                report = await coro
                # Support both dataclasses with to_dict() and plain dicts
                if hasattr(report, "to_dict"):
                    return report.to_dict()
                elif isinstance(report, dict):
                    return report
                else:
                    return {
                        "signal": 0.0,
                        "confidence": 0.0,
                        "summary": f"{name} returned unexpected type",
                    }
            except Exception as e:
                err = f"{name} analyst failed: {e}"
                logger.warning(f"[Pipeline] {err}")
                errors.append(err)
                return {"signal": 0.0, "confidence": 0.0, "summary": f"{name} unavailable"}

        # Build coroutines — skip missing agents gracefully
        technical_coro = self._call_agent_analyze(
            "technical", symbol, is_futures=is_futures, timeframe=timeframe
        )
        news_coro = self._call_agent_analyze("news", symbol)
        social_coro = self._call_agent_analyze("social", symbol)
        fundamental_coro = self._call_agent_analyze("fundamental", symbol)

        results = await asyncio.gather(
            safe_analyze("technical", technical_coro),
            safe_analyze("news", news_coro),
            safe_analyze("social", social_coro),
            safe_analyze("fundamental", fundamental_coro),
        )

        return {
            "technical": results[0],
            "news": results[1],
            "social": results[2],
            "fundamental": results[3],
        }

    async def _call_agent_analyze(self, agent_name: str, symbol: str, **kwargs):
        """Delegates to the named agent's analyze() method, or returns neutral if absent."""
        agent = self._agents.get(agent_name)
        if agent is None:
            return {"signal": 0.0, "confidence": 0.0, "summary": f"{agent_name} unavailable"}
        return await agent.analyze(symbol, **kwargs)

    async def _run_debate(
        self,
        symbol: str,
        analyst_reports: dict,
        errors: list,
    ) -> dict:
        """Run the bull/bear debate. Returns neutral dict on failure."""
        try:
            bull_agent = self._agents.get("bull")
            bear_agent = self._agents.get("bear")
            debate_agent = self._agents.get("debate")

            if not all([bull_agent, bear_agent, debate_agent]):
                logger.debug("[Pipeline] Bull/bear/debate agents not configured — skipping debate")
                return {
                    "verdict": "neutral",
                    "bull_score": 0.5,
                    "bear_score": 0.5,
                    "summary": "Debate agents not configured",
                    "bull_arguments": [],
                    "bear_arguments": [],
                }

            # Debate orchestrator runs bull + bear internally
            debate_result = await debate_agent.run_debate(
                symbol=symbol,
                analyst_reports=analyst_reports,
                bull=bull_agent,
                bear=bear_agent,
            )

            # Normalise to dict
            if hasattr(debate_result, "to_dict"):
                return debate_result.to_dict()
            elif isinstance(debate_result, dict):
                return debate_result
            else:
                return {"verdict": "neutral", "summary": str(debate_result)}

        except Exception as e:
            err = f"Debate stage failed: {e}"
            logger.warning(f"[Pipeline] {err}")
            errors.append(err)
            return {
                "verdict": "neutral",
                "bull_score": 0.5,
                "bear_score": 0.5,
                "summary": "Debate failed — defaulting to neutral",
                "bull_arguments": [],
                "bear_arguments": [],
            }

    async def _run_trader(
        self,
        symbol: str,
        debate_result: dict,
        analyst_reports: dict,
        safety_status: dict,
        errors: list,
    ) -> dict:
        """Run the Trader agent. Returns HOLD on failure."""
        try:
            trader = self._agents.get("trader")
            if trader is None:
                logger.warning("[Pipeline] Trader agent not configured")
                return {
                    "symbol": symbol,
                    "action": "hold",
                    "quantity": 0,
                    "order_type": "market",
                    "limit_price": None,
                    "stop_price": None,
                    "time_in_force": "day",
                    "signal_score": 0.0,
                    "confidence": 0.0,
                    "reasoning": "Trader agent not configured",
                    "risk_notes": "Pipeline misconfiguration",
                    "timestamp": datetime.now().isoformat(),
                }

            decision = await trader.decide(symbol, debate_result, analyst_reports, safety_status)
            return decision.to_dict() if hasattr(decision, "to_dict") else decision

        except Exception as e:
            err = f"Trader stage failed: {e}"
            logger.error(f"[Pipeline] {err}")
            errors.append(err)
            return {
                "symbol": symbol,
                "action": "hold",
                "quantity": 0,
                "order_type": "market",
                "limit_price": None,
                "stop_price": None,
                "time_in_force": "day",
                "signal_score": 0.0,
                "confidence": 0.0,
                "reasoning": f"Trader agent exception: {e}",
                "risk_notes": "LLM failure — defaulting to HOLD",
                "timestamp": datetime.now().isoformat(),
            }

    async def _run_risk_manager(
        self,
        trade_decision: dict,
        safety_status: dict,
        portfolio: dict,
        errors: list,
    ) -> dict:
        """Run the Risk Manager. Approves trivially on failure to avoid blocking holds."""
        try:
            risk_manager = self._agents.get("risk_manager")
            if risk_manager is None:
                logger.warning("[Pipeline] Risk Manager not configured — auto-approving")
                return {
                    "approved": True,
                    "veto_reason": None,
                    "modified_quantity": None,
                    "modified_limit_price": None,
                    "risk_score": 0.5,
                    "reasoning": "Risk Manager not configured — passed without review",
                    "timestamp": datetime.now().isoformat(),
                }

            risk = await risk_manager.review(trade_decision, safety_status, portfolio)
            return risk.to_dict() if hasattr(risk, "to_dict") else risk

        except Exception as e:
            err = f"Risk Manager stage failed: {e}"
            logger.error(f"[Pipeline] {err}")
            errors.append(err)
            return {
                "approved": False,
                "veto_reason": f"Risk Manager exception: {e}",
                "modified_quantity": None,
                "modified_limit_price": None,
                "risk_score": 1.0,
                "reasoning": f"Risk Manager failed with exception: {e}. Defaulting to VETO for safety.",
                "timestamp": datetime.now().isoformat(),
            }

    async def _run_fund_manager(
        self,
        trade_decision: dict,
        risk_decision: dict,
        portfolio: dict,
        open_positions: list,
        errors: list,
    ) -> dict:
        """Run the Fund Manager. Approves conservatively on failure."""
        try:
            fund_manager = self._agents.get("fund_manager")
            if fund_manager is None:
                logger.warning("[Pipeline] Fund Manager not configured — auto-approving")
                qty = risk_decision.get("modified_quantity") or trade_decision.get("quantity", 0)
                return {
                    "approved": True,
                    "final_quantity": int(qty),
                    "priority": "immediate",
                    "portfolio_impact": "Fund Manager not configured — passed without portfolio review",
                    "reasoning": "Fund Manager not configured.",
                    "requires_human_approval": True,
                    "timestamp": datetime.now().isoformat(),
                }

            fund = await fund_manager.approve(
                trade_decision, risk_decision, portfolio, open_positions
            )
            return fund.to_dict() if hasattr(fund, "to_dict") else fund

        except Exception as e:
            err = f"Fund Manager stage failed: {e}"
            logger.error(f"[Pipeline] {err}")
            errors.append(err)
            qty = risk_decision.get("modified_quantity") or trade_decision.get("quantity", 1)
            return {
                "approved": True,
                "final_quantity": min(int(qty), 1),
                "priority": "immediate",
                "portfolio_impact": "Fund Manager failed — conservative fallback approval",
                "reasoning": f"Fund Manager exception: {e}. Approved at min size with human approval required.",
                "requires_human_approval": True,
                "timestamp": datetime.now().isoformat(),
            }

    def _resolve_final_action(
        self, trade_decision: dict, risk_decision: dict, fund_decision: dict
    ) -> tuple:
        """
        Resolve final action from multi-stage decisions.

        Logic:
        1. If risk manager rejected → HOLD
        2. If fund manager not run (risk rejected) → HOLD
        3. If fund manager rejected → HOLD
        4. Otherwise use fund_decision action/quantity

        Returns: (final_action, final_quantity, requires_human)
        """
        # Risk manager veto
        if risk_decision and not risk_decision.get("approved", False):
            logger.info("[Resolution] Risk manager veto → HOLD")
            return "hold", 0, False

        # Fund manager decision (only runs if risk approved)
        if fund_decision:
            if not fund_decision.get("execute", False):
                logger.info("[Resolution] Fund manager rejected → HOLD")
                return "hold", 0, False

            action = fund_decision.get("action", "HOLD").lower()
            quantity = fund_decision.get("contracts", fund_decision.get("quantity", 0))
            requires_human = fund_decision.get("human_approval_required", False)
            logger.info(
                f"[Resolution] Fund approved → {action} qty={quantity} human={requires_human}"
            )
            return action, quantity, requires_human

        # Fallback: use trade decision if we got here (risk approved but no fund decision)
        if trade_decision:
            action = trade_decision.get("action", "HOLD").lower()
            quantity = trade_decision.get("quantity", 0)
            requires_human = False
            logger.info(f"[Resolution] No fund decision, using trade → {action} qty={quantity}")
            return action, quantity, requires_human

        # Default to HOLD if nothing else available
        logger.warning("[Resolution] No decision available → HOLD")
        return "hold", 0, False

    # ── Portfolio Data ─────────────────────────────────────────────────────

    async def _get_portfolio(self) -> dict:
        """
        Retrieve current portfolio state.

        Override this method in a subclass (or inject a portfolio_provider into
        the agents dict as "portfolio") to supply real broker data.
        Falls back to a safe empty portfolio so the pipeline never crashes.
        """
        portfolio_provider = self._agents.get("portfolio")
        if portfolio_provider is not None:
            try:
                if asyncio.iscoroutinefunction(getattr(portfolio_provider, "get_portfolio", None)):
                    return await portfolio_provider.get_portfolio()
                elif callable(getattr(portfolio_provider, "get_portfolio", None)):
                    return portfolio_provider.get_portfolio()
            except Exception as e:
                logger.warning(f"[Pipeline] Portfolio fetch failed: {e}")

        # Safe default — Risk Manager and Fund Manager handle missing data gracefully
        equity = (
            self._safety._current_equity if hasattr(self._safety, "_current_equity") else 10_000.0
        )
        return {
            "total_value": equity,
            "available_cash": equity * 0.5,
            "margin_used_pct": 0.0,
            "daily_pnl": getattr(self._safety, "_daily_realized_pnl", 0.0),
            "open_position_count": 0,
            "positions": [],
        }

    # ── PostgreSQL Audit Logging ──────────────────────────────────────────────

    async def _log_pipeline_to_postgres(
        self,
        symbol: str,
        pipeline_result: dict,
        trade_decision: dict,
        errors: list,
    ) -> None:
        """
        Log pipeline execution to PostgreSQL for audit trail and analysis.

        Logs each agent's decision independently, plus the final trade decision.
        Gracefully handles database unavailability — never blocks the pipeline.

        Args:
            symbol: Trading symbol
            pipeline_result: Complete pipeline result dict
            trade_decision: Final trade decision dict
            errors: Any errors encountered
        """
        try:
            analyst_reports = pipeline_result.get("analyst_reports", {})
            fund_decision = pipeline_result.get("fund_decision")

            # Log each analyst's decision
            for agent_name in ["technical", "news", "social", "fundamental"]:
                report = analyst_reports.get(agent_name, {})
                if report and isinstance(report, dict):
                    await repository.insert_decision(
                        agent_name=agent_name,
                        symbol=symbol,
                        signal=report.get("signal", 0.0),
                        confidence=report.get("confidence", 0.0),
                        reasoning=report.get("summary", ""),
                        indicators=report.get("indicators"),
                        model_used=report.get("model_used"),
                        tokens_used=report.get("tokens_used"),
                        latency_ms=report.get("latency_ms"),
                        timeframe=report.get("timeframe"),
                    )

            # Log debate result (if present)
            debate_result = pipeline_result.get("debate_result", {})
            if debate_result and isinstance(debate_result, dict):
                await repository.insert_decision(
                    agent_name="debate",
                    symbol=symbol,
                    signal=debate_result.get("bull_score", 0.5)
                    - debate_result.get("bear_score", 0.5),
                    confidence=0.5,  # Debate doesn't have a direct confidence
                    reasoning=debate_result.get("summary", ""),
                )

            # Log trader decision (main decision point)
            if trade_decision and isinstance(trade_decision, dict):
                final_conviction = (
                    fund_decision.get("final_conviction", 0.0) if fund_decision else 0.0
                )
                await repository.insert_decision(
                    agent_name="trader",
                    symbol=symbol,
                    signal=trade_decision.get("signal_score", 0.0),
                    confidence=trade_decision.get("confidence", final_conviction),
                    reasoning=trade_decision.get("reasoning", ""),
                    model_used=trade_decision.get("model_used"),
                    tokens_used=trade_decision.get("tokens_used"),
                    latency_ms=trade_decision.get("latency_ms"),
                )

            # Log risk manager decision (if available)
            risk_decision = pipeline_result.get("risk_decision", {})
            if risk_decision and isinstance(risk_decision, dict):
                await repository.insert_decision(
                    agent_name="risk_manager",
                    symbol=symbol,
                    signal=1.0 if risk_decision.get("approved") else -1.0,
                    confidence=risk_decision.get("risk_score", 0.5),
                    reasoning=risk_decision.get("reasoning", ""),
                )

            # Log fund manager decision (if available)
            if fund_decision and isinstance(fund_decision, dict):
                await repository.insert_decision(
                    agent_name="fund_manager",
                    symbol=symbol,
                    signal=1.0 if fund_decision.get("approved") else -1.0,
                    confidence=fund_decision.get("final_conviction", 0.0),
                    reasoning=fund_decision.get("reasoning", ""),
                )

            logger.debug(f"[DB] Pipeline decisions logged for {symbol}")

        except Exception as e:
            # Never block pipeline execution due to database errors
            logger.warning(f"[DB] Failed to log pipeline to PostgreSQL: {e}")

    # ── Webhook Entry Point ────────────────────────────────────────────────

    async def run_on_signal(self, signal: dict) -> dict:
        """
        Entry point for TradingView webhook signals.
        Called by webhook_router when a LONG/SHORT/CLOSE alert arrives.

        Args:
            signal: Normalized webhook event dict with keys:
                symbol (str), action (str), price (float), timeframe (str),
                atr (float), regime (str), os_value (float), ob_value (float),
                received_at (str), source (str)

        Returns:
            dict with pipeline result or skip reason
        """
        symbol = signal.get("symbol", "MES")
        action = signal.get("action", "HOLD")
        source = signal.get("source", "tradingview")
        req_id = str(uuid.uuid4())[:8]

        logger.info(f"[Webhook:{req_id}] Signal received: {symbol} {action} from {source}")

        # Only run pipeline for actionable signals
        if action not in ("LONG", "SHORT", "CLOSE"):
            logger.debug(f"[Webhook:{req_id}] Skipping non-actionable action: {action}")
            return {
                "status": "skipped",
                "symbol": symbol,
                "action": action,
                "reason": f"Action '{action}' is not actionable — pipeline not triggered",
                "req_id": req_id,
            }

        # Determine is_futures from symbol name (micro futures naming convention)
        is_futures = not symbol.upper().startswith(("SPY", "QQQ", "IWM"))

        try:
            result = await self.analyze_and_decide(symbol, is_futures=is_futures)
            result["req_id"] = req_id
            result["webhook_action"] = action
            result["webhook_source"] = source
            logger.info(
                f"[Webhook:{req_id}] Pipeline complete: {symbol} "
                f"final_action={result.get('final_action', 'unknown')}"
            )
            return result
        except Exception as exc:
            logger.error(f"[Webhook:{req_id}] Pipeline raised for {symbol}: {exc}", exc_info=True)
            return {
                "status": "error",
                "symbol": symbol,
                "action": action,
                "req_id": req_id,
                "error": str(exc),
            }

```

### `engine/risk/safety_layer.py`
```python
"""
JARVIS TRADER — Safety Layer
================================
CRITICAL: This module is HARDCODED in Python. NO LLM reasoning in the safety path.
All risk controls are enforced here before any order reaches a broker.

Design principle from TradeTrap paper:
  - Portfolio state of record comes from broker API, NEVER from agent memory
  - Hard limits cannot be overridden by agent reasoning
  - Kill switch can only be re-enabled by human (Matt)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

try:
    from engine.execution.ib_gateway import IBGatewayManager

    _IB_GATEWAY_AVAILABLE = True
except ImportError:
    IBGatewayManager = None  # type: ignore[assignment,misc]
    _IB_GATEWAY_AVAILABLE = False

try:
    from risk.pnl_monitor import PnLMonitor
except ImportError:
    try:
        from engine.risk.pnl_monitor import PnLMonitor
    except ImportError:
        PnLMonitor = None  # type: ignore[assignment,misc]

try:
    from risk.loss_tracker import ConsecutiveLossTracker
except ImportError:
    try:
        from engine.risk.loss_tracker import ConsecutiveLossTracker
    except ImportError:
        ConsecutiveLossTracker = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


class KillSwitchReason(Enum):
    MANUAL = "manual"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MAX_DRAWDOWN = "max_drawdown"
    MARKET_CIRCUIT_BREAKER = "market_circuit_breaker"
    DATA_FEED_LOSS = "data_feed_loss"
    BROKER_DISCONNECT = "broker_disconnect"
    ANOMALOUS_ORDER_RATE = "anomalous_order_rate"


@dataclass
class OrderRequest:
    symbol: str
    quantity: int  # Positive = buy, negative = sell
    order_type: str  # "market", "limit", "stop", "stop_limit"
    limit_price: float | None = None
    stop_price: float | None = None
    is_futures: bool = False
    is_options: bool = False
    estimated_value: float = 0.0


@dataclass
class RiskCheckResult:
    approved: bool
    rejection_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    adjusted_order: Optional[OrderRequest] = None  # Order with position size adjusted for losses


class SafetyLayer:
    """
    Non-LLM risk management. Every order MUST pass through here.
    Instantiated once at startup and shared across all agents.
    """

    def __init__(self, config, ib_gateway=None, pnl_monitor=None, loss_tracker=None):
        """
        Parameters
        ----------
        config:
            JARVIS settings object (LIVE_TRADING_ENABLED, MAX_DAILY_LOSS_PCT, …).
        ib_gateway : IBGatewayManager | None
            Optional IB Gateway handle used by submit_paper_order().
            Passing None keeps the SafetyLayer fully backward-compatible — all
            existing callers that construct ``SafetyLayer(config)`` continue to
            work without changes.  The gateway is NEVER used by check_order()
            or any other existing method.
        pnl_monitor : PnLMonitor | None
            Optional PnLMonitor instance.  When provided, circuit-breaker checks
            in check_order() and sync_from_broker() read live P&L from the best
            available source (IB Gateway → SQLite → in-memory tracker) rather
            than relying solely on the values last set by sync_from_broker().
            Passing None preserves full backward-compatibility.
        loss_tracker : ConsecutiveLossTracker | None
            Optional ConsecutiveLossTracker instance. When provided, tracks
            consecutive losing trades and modulates position size accordingly.
            Passing None preserves full backward-compatibility.
        """
        self._config = config
        self._ib_gateway = ib_gateway  # used only by submit_paper_order()
        self._pnl_monitor: Optional[object] = pnl_monitor  # PnLMonitor | None
        self._loss_tracker: Optional[object] = loss_tracker  # ConsecutiveLossTracker | None
        self._kill_switch_active = False
        self._kill_switch_reason: KillSwitchReason | None = None

        # Daily tracking (reset at market open)
        self._daily_realized_pnl: float = 0.0
        self._daily_order_count: int = 0
        self._daily_date: date = date.today()

        # Peak equity for drawdown calculation (from broker API, not agent)
        self._equity_peak: float = 0.0
        self._current_equity: float = 0.0

        # Orders per minute tracking
        self._recent_order_timestamps: list[float] = []

        # Tilt detector (optional — injected after construction)
        self.tilt_detector = None

    def attach_ib_gateway(self, gateway) -> None:
        """Wire in an IB gateway after construction (called after paper connector connects)."""
        self._ib_gateway = gateway

    # ── Kill Switch ───────────────────────────────────────────────────────

    def activate_kill_switch(self, reason: KillSwitchReason | str, message: str = "") -> None:
        """Halt all trading. Requires human re-authorization to resume."""
        self._kill_switch_active = True
        # Convert string to enum if needed (for backward compatibility with tests)
        if isinstance(reason, str):
            try:
                reason = KillSwitchReason[reason]
            except KeyError:
                logger.warning(f"Unknown kill switch reason: {reason}")
                reason = KillSwitchReason.MANUAL
        self._kill_switch_reason = reason
        logger.critical(f"🔴 KILL SWITCH ACTIVATED: {reason.value}. {message}")
        # Log to PostgreSQL asynchronously (never block)
        try:
            asyncio.create_task(
                self._log_safety_event(
                    "kill_switch_activate",
                    reason.value,
                    {"reason": reason.value, "message": message},
                )
            )
        except RuntimeError:
            # No running event loop (e.g., in tests or sync context)
            logger.debug("No running event loop for async logging")

    def deactivate_kill_switch(self, authorized_by: str = "human") -> None:
        """Resume trading. Only callable by human action (not by agents)."""
        self._kill_switch_active = False
        self._kill_switch_reason = None
        logger.info(f"✅ Kill switch deactivated by: {authorized_by}")
        # Log to PostgreSQL asynchronously
        try:
            asyncio.create_task(
                self._log_safety_event(
                    "kill_switch_deactivate",
                    f"Deactivated by {authorized_by}",
                    {"authorized_by": authorized_by, "resolved": True},
                )
            )
        except RuntimeError:
            # No running event loop (e.g., in tests or sync context)
            logger.debug("No running event loop for async logging")

    @property
    def is_killed(self) -> bool:
        return self._kill_switch_active

    def get_status(self) -> dict:
        """Return safety layer status for agents."""
        return {
            "is_killed": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason.value
            if self._kill_switch_reason
            else None,
            "daily_realized_pnl": self._daily_realized_pnl,
            "equity_peak": self._equity_peak,
            "current_equity": self._current_equity,
            "recent_order_count": len(self._recent_order_timestamps),
        }

    # ── Pre-Trade Checks ─────────────────────────────────────────────────

    def _check_drawdown(self, portfolio_equity: float, warnings: list) -> RiskCheckResult:
        """Check max drawdown limits. Returns RiskCheckResult(approved=True) if passed."""
        if self._pnl_monitor is not None:
            drawdown = -self._pnl_monitor.get_drawdown_pct()
            if drawdown > self._config.MAX_DRAWDOWN_PCT:
                self.activate_kill_switch(
                    KillSwitchReason.MAX_DRAWDOWN,
                    f"Drawdown {drawdown:.1%} exceeded max {self._config.MAX_DRAWDOWN_PCT:.1%} (source: pnl_monitor)",
                )
                return RiskCheckResult(
                    approved=False, rejection_reason="Max drawdown breached — kill switch activated"
                )
            elif drawdown >= self._config.MAX_DRAWDOWN_PCT * 0.8:
                warnings.append(
                    f"Drawdown at {drawdown:.1%} — approaching {self._config.MAX_DRAWDOWN_PCT:.1%} limit"
                )
        elif self._equity_peak > 0:
            drawdown = (self._equity_peak - portfolio_equity) / self._equity_peak
            if drawdown > self._config.MAX_DRAWDOWN_PCT:
                self.activate_kill_switch(
                    KillSwitchReason.MAX_DRAWDOWN,
                    f"Drawdown {drawdown:.1%} exceeded max {self._config.MAX_DRAWDOWN_PCT:.1%}",
                )
                return RiskCheckResult(
                    approved=False, rejection_reason="Max drawdown breached — kill switch activated"
                )
            elif drawdown >= self._config.MAX_DRAWDOWN_PCT * 0.8:
                warnings.append(
                    f"Drawdown at {drawdown:.1%} — approaching {self._config.MAX_DRAWDOWN_PCT:.1%} limit"
                )
        return RiskCheckResult(approved=True, warnings=warnings)

    def _apply_loss_tracker_adjustment(
        self, order: OrderRequest, warnings: list
    ) -> RiskCheckResult | tuple[OrderRequest, list]:
        """Apply loss tracker adjustments. Returns error result or (adjusted_order, warnings)."""
        if self._loss_tracker is None:
            return order, warnings

        if self._loss_tracker.is_halted():
            return RiskCheckResult(
                approved=False, rejection_reason=self._loss_tracker.get_halt_reason()
            )

        multiplier = self._loss_tracker.get_position_size_multiplier()
        if multiplier < 1.0:
            reduced_quantity = max(1, int(abs(order.quantity) * multiplier))
            adjusted_order = OrderRequest(
                symbol=order.symbol,
                quantity=reduced_quantity if order.quantity > 0 else -reduced_quantity,
                order_type=order.order_type,
                limit_price=order.limit_price,
                stop_price=order.stop_price,
                is_futures=order.is_futures,
                is_options=order.is_options,
                estimated_value=order.estimated_value * multiplier,
            )
            consecutive_losses = self._loss_tracker.get_consecutive_losses()
            warnings.append(
                f"Consecutive losses: {consecutive_losses} — "
                f"position size reduced by {(1.0 - multiplier):.0%} "
                f"(qty: {order.quantity} → {adjusted_order.quantity})"
            )
            logger.warning(
                f"Position size reduction applied: {order.symbol} qty {order.quantity} → "
                f"{adjusted_order.quantity} (multiplier={multiplier:.2f})"
            )
            return adjusted_order, warnings
        return order, warnings

    def _check_kill_switch(self) -> RiskCheckResult:
        """Check kill switch status."""
        if self._kill_switch_active:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Kill switch active: {self._kill_switch_reason.value if self._kill_switch_reason else 'unknown'}",
            )
        return RiskCheckResult(approved=True)

    def _check_gating_conditions(self) -> RiskCheckResult:
        """Check live trading enabled and human approval conditions."""
        if not self._config.LIVE_TRADING_ENABLED:
            if getattr(self._config, "ALLOW_PAPER_SIMULATED_ORDERS", False):
                # Explicit opt-in: route through simulated paper path, skip all gating
                return RiskCheckResult(approved=True)
            return RiskCheckResult(
                approved=False,
                rejection_reason="Live trading is disabled (LIVE_TRADING_ENABLED=False)",
            )
        if self._config.REQUIRE_HUMAN_APPROVAL:
            return RiskCheckResult(
                approved=False,
                rejection_reason="Human approval required (REQUIRE_HUMAN_APPROVAL=True) — this is normal in initial deployment",
            )
        return RiskCheckResult(approved=True)

    def _check_daily_loss_limit(self, portfolio_equity: float) -> RiskCheckResult:
        """Check daily loss limit."""
        daily_pnl = (
            self._pnl_monitor.get_daily_pnl() if self._pnl_monitor else self._daily_realized_pnl
        )
        if daily_pnl < -(portfolio_equity * self._config.MAX_DAILY_LOSS_PCT):
            self.activate_kill_switch(
                KillSwitchReason.DAILY_LOSS_LIMIT,
                f"Daily loss {daily_pnl:.2f} exceeded limit",
            )
            return RiskCheckResult(
                approved=False, rejection_reason="Daily loss limit breached — kill switch activated"
            )
        return RiskCheckResult(approved=True)

    def _check_order_value_limits(
        self, order: OrderRequest, portfolio_equity: float
    ) -> RiskCheckResult:
        """Check order size and position size limits."""
        if order.estimated_value > self._config.MAX_SINGLE_ORDER_VALUE:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Order value ${order.estimated_value:,.0f} exceeds max ${self._config.MAX_SINGLE_ORDER_VALUE:,.0f}",
            )
        position_pct = order.estimated_value / portfolio_equity if portfolio_equity > 0 else 1.0
        if position_pct > self._config.MAX_POSITION_SIZE_PCT:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Position size {position_pct:.1%} exceeds max {self._config.MAX_POSITION_SIZE_PCT:.1%}",
            )
        return RiskCheckResult(approved=True)

    def _check_order_rate(self) -> tuple[RiskCheckResult, float]:
        """Check order rate throttle. Returns (RiskCheckResult, timestamp)."""
        import time

        now = time.time()
        self._recent_order_timestamps = [t for t in self._recent_order_timestamps if now - t < 60]
        if len(self._recent_order_timestamps) >= self._config.MAX_ORDERS_PER_MINUTE:
            self.activate_kill_switch(
                KillSwitchReason.ANOMALOUS_ORDER_RATE,
                f"Order rate exceeded {self._config.MAX_ORDERS_PER_MINUTE}/min",
            )
            return (
                RiskCheckResult(
                    approved=False, rejection_reason="Anomalous order rate — kill switch activated"
                ),
                now,
            )
        return RiskCheckResult(approved=True), now

    def _check_contract_limits(self, order: OrderRequest) -> RiskCheckResult:
        """Check futures contract limits."""
        if order.is_futures and abs(order.quantity) > self._config.MAX_CONTRACTS_PER_INSTRUMENT:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Requested {abs(order.quantity)} contracts exceeds max {self._config.MAX_CONTRACTS_PER_INSTRUMENT}",
            )
        return RiskCheckResult(approved=True)

    def check_order(self, order: OrderRequest, portfolio_equity: float) -> RiskCheckResult:
        """
        Run all pre-trade safety checks.
        Returns approved=False if ANY check fails.
        Hard limits are non-negotiable.
        """
        warnings = []

        # Run sequential checks, return early on failure
        for check_fn in [
            lambda: self._check_kill_switch(),
            lambda: self._check_gating_conditions(),
            lambda: self._check_daily_loss_limit(portfolio_equity),
            lambda: self._check_drawdown(portfolio_equity, warnings),
            lambda: self._check_order_value_limits(order, portfolio_equity),
            lambda: self._check_contract_limits(order),
        ]:
            result = check_fn()
            if isinstance(result, tuple):
                result, _ = result
            if not result.approved:
                return result

        # Order rate check returns timestamp
        rate_result, now = self._check_order_rate()
        if not rate_result.approved:
            return rate_result

        # Tilt detector check
        if self.tilt_detector is not None:
            tilt_state = self.tilt_detector.check()
            if tilt_state.position_size_multiplier == 0.0:
                return RiskCheckResult(
                    approved=False,
                    rejection_reason="Trading halted due to tilt detection (emotional/behavioral risk)",
                )
            elif tilt_state.severity in ("caution", "warning", "critical"):
                warnings.append(f"Tilt {tilt_state.severity}: behavioral risk indicators elevated")

        # Loss tracker adjustment
        loss_result = self._apply_loss_tracker_adjustment(order, warnings)
        if isinstance(loss_result, RiskCheckResult):
            return loss_result
        adjusted_order, warnings = loss_result

        # All checks passed
        self._recent_order_timestamps.append(now)
        logger.info(
            f"✅ Order approved: {adjusted_order.symbol} qty={adjusted_order.quantity} est_value=${adjusted_order.estimated_value:,.0f}"
        )
        return RiskCheckResult(
            approved=True,
            warnings=warnings,
            adjusted_order=adjusted_order if adjusted_order != order else None,
        )

    # ── Paper Order Submission (Safety → IB Gateway) ──────────────────────

    async def submit_paper_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "MKT",
        limit_price: float | None = None,
    ) -> dict:
        """
        Run all safety checks then, if they pass, route the order to IB
        Gateway in paper-trading mode (port 4002).

        This is the ONLY approved path from the SafetyLayer to the broker.
        No LLM reasoning happens here — pure deterministic gate.

        Parameters
        ----------
        symbol      : Ticker / futures root (e.g. "MES", "AAPL").
        action      : "BUY" or "SELL" (case-insensitive).
        quantity    : Positive integer — always pass the absolute lot size.
                      Direction is expressed via *action*.
        price       : Estimated execution price (used for value checks).
        order_type  : "MKT" (default) or "LMT".
        limit_price : Required when order_type == "LMT".

        Returns
        -------
        dict with keys:
            approved    (bool)   — True only when every safety check passed.
            reason      (str)    — Human-readable outcome (approval or rejection message).
            order_id    (str|None) — IB order ID string if the order was placed, else None.
            routed_to_ib (bool)  — True only when the order reached IB Gateway.
        """
        # ── 0. Kill switch — checked first, before anything else ──────────
        if self._kill_switch_active:
            reason = (
                f"Kill switch active: {self._kill_switch_reason.value}"
                if self._kill_switch_reason
                else "Kill switch active"
            )
            logger.warning(
                "submit_paper_order BLOCKED by kill switch — symbol=%s action=%s qty=%d: %s",
                symbol,
                action,
                quantity,
                reason,
            )
            return {"approved": False, "reason": reason, "order_id": None, "routed_to_ib": False}

        # ── 1. Build an OrderRequest so we can re-use check_order() fully ─
        action_upper = action.upper()
        signed_qty = quantity if action_upper == "BUY" else -quantity
        estimated_value = abs(quantity) * price

        # Detect futures by common micro/mini root symbols (heuristic; callers
        # can override by subclassing or by building the OrderRequest directly
        # and calling check_order() + submit_paper_order separately).
        _FUTURES_ROOTS = {
            "MES",
            "MNQ",
            "M2K",
            "MCL",
            "MGC",
            "MHG",
            "MSI",
            "ES",
            "NQ",
            "RTY",
            "CL",
            "GC",
            "HG",
        }
        is_futures = symbol.upper() in _FUTURES_ROOTS

        ib_order_type = order_type.lower()
        # Normalise "MKT"→"market", "LMT"→"limit" for OrderRequest
        if ib_order_type in ("mkt", "market"):
            normalised_order_type = "market"
        elif ib_order_type in ("lmt", "limit"):
            normalised_order_type = "limit"
        else:
            normalised_order_type = ib_order_type

        order = OrderRequest(
            symbol=symbol,
            quantity=signed_qty,
            order_type=normalised_order_type,
            limit_price=limit_price,
            is_futures=is_futures,
            estimated_value=estimated_value,
        )

        # ── 2. Full pre-trade safety gate ─────────────────────────────────
        # check_order() re-checks the kill switch internally (check #0 above
        # is an early-exit optimisation to avoid building OrderRequest at all
        # when we already know the kill switch is on).
        portfolio_equity = self._current_equity if self._current_equity > 0 else estimated_value
        risk_result = self.check_order(order, portfolio_equity)

        if not risk_result.approved:
            logger.warning(
                "submit_paper_order REJECTED by SafetyLayer — symbol=%s action=%s qty=%d: %s",
                symbol,
                action,
                quantity,
                risk_result.rejection_reason,
            )
            return {
                "approved": False,
                "reason": risk_result.rejection_reason or "Safety check failed",
                "order_id": None,
                "routed_to_ib": False,
            }

        if risk_result.warnings:
            for w in risk_result.warnings:
                logger.warning("submit_paper_order safety warning (order allowed): %s", w)

        # ── 3. Route to IB Gateway if available ───────────────────────────
        if self._ib_gateway is None:
            logger.info(
                "submit_paper_order: safety checks PASSED — no IB gateway attached "
                "(dry-run mode). symbol=%s action=%s qty=%d",
                symbol,
                action,
                quantity,
            )
            return {
                "approved": True,
                "reason": "Safety checks passed — IB gateway not attached (dry-run)",
                "order_id": None,
                "routed_to_ib": False,
            }

        if not self._ib_gateway.is_connected():
            logger.error(
                "submit_paper_order: safety checks PASSED but IB gateway is NOT connected. "
                "symbol=%s action=%s qty=%d",
                symbol,
                action,
                quantity,
            )
            return {
                "approved": True,
                "reason": "Safety checks passed — IB gateway not connected",
                "order_id": None,
                "routed_to_ib": False,
            }

        try:
            order_id = await self._ib_gateway.place_paper_order(
                symbol=symbol,
                action=action_upper,
                quantity=quantity,
                order_type=order_type.upper(),
                limit_price=limit_price,
            )
            logger.info(
                "submit_paper_order ROUTED to IB Gateway (paper) — symbol=%s action=%s "
                "qty=%d order_type=%s order_id=%s",
                symbol,
                action_upper,
                quantity,
                order_type.upper(),
                order_id,
            )
            return {
                "approved": True,
                "reason": "Order submitted to IB Gateway (paper trading)",
                "order_id": str(order_id) if order_id is not None else None,
                "routed_to_ib": True,
            }
        except Exception as exc:
            logger.error(
                "submit_paper_order: IB Gateway place_paper_order raised — symbol=%s: %s",
                symbol,
                exc,
                exc_info=True,
            )
            return {
                "approved": True,
                "reason": f"Safety checks passed but IB Gateway raised: {exc}",
                "order_id": None,
                "routed_to_ib": False,
            }

    # ── Portfolio State Sync (from broker, NOT from agents) ───────────────

    def sync_from_broker(self, equity: float, daily_pnl: float) -> None:
        """
        Called every 60 seconds with ground truth from broker API.
        This is the ONLY way portfolio state is updated — never via agent memory.
        """
        self._current_equity = equity
        self._daily_realized_pnl = daily_pnl

        if equity > self._equity_peak:
            self._equity_peak = equity

        # Auto-trigger daily loss check
        if daily_pnl < -(equity * self._config.MAX_DAILY_LOSS_PCT):
            self.activate_kill_switch(
                KillSwitchReason.DAILY_LOSS_LIMIT, f"Intraday sync: daily PnL {daily_pnl:.2f}"
            )

    def check_circuit_breakers(self) -> dict:
        """
        Return the current status of all circuit breakers as a single dict.

        This method is safe to call at any time — it does NOT activate the kill
        switch.  Use it for dashboard polling and the /safety/circuit-breakers
        API endpoint.

        Returns
        -------
        dict with keys:
            daily_pnl            (float)  — today's realized + unrealized P&L in $
            daily_limit          (float)  — maximum allowed daily loss in $ (negative)
            daily_pnl_pct        (float)  — daily P&L as fraction of starting balance
            daily_limit_pct      (float)  — configured daily loss limit (negative fraction)
            daily_limit_breached (bool)  — if daily loss limit has been breached
            drawdown_pct         (float)  — current drawdown from peak (negative)
            drawdown_limit_pct   (float)  — configured max drawdown (negative)
            drawdown_breached    (bool)  — if drawdown limit has been breached
            kill_switch_active   (bool)  — if emergency halt is engaged
            kill_switch_reason   (str)   — reason for kill switch if active
        """
        # Use PnLMonitor when available; fall back to in-memory values
        if self._pnl_monitor is not None:
            daily_pnl_for_check = self._pnl_monitor.get_daily_pnl()
        else:
            daily_pnl_for_check = self._daily_realized_pnl

        # Daily loss circuit breaker
        daily_limit = (
            -(self._current_equity * self._config.MAX_DAILY_LOSS_PCT)
            if self._current_equity > 0
            else 0
        )
        daily_pnl_pct = (
            (daily_pnl_for_check / self._current_equity) if self._current_equity > 0 else 0
        )
        daily_limit_pct = -self._config.MAX_DAILY_LOSS_PCT
        daily_limit_breached = daily_pnl_for_check < daily_limit

        # Drawdown circuit breaker
        drawdown_pct = 0.0
        if self._pnl_monitor is not None:
            drawdown_pct = -self._pnl_monitor.get_drawdown_pct()
        elif self._equity_peak > 0:
            drawdown_pct = (self._equity_peak - self._current_equity) / self._equity_peak
        drawdown_limit_pct = -self._config.MAX_DRAWDOWN_PCT
        drawdown_breached = drawdown_pct > self._config.MAX_DRAWDOWN_PCT

        return {
            "daily_pnl": daily_pnl_for_check,
            "daily_limit": daily_limit,
            "daily_pnl_pct": daily_pnl_pct,
            "daily_limit_pct": daily_limit_pct,
            "daily_limit_breached": daily_limit_breached,
            "drawdown_pct": drawdown_pct,
            "drawdown_limit_pct": drawdown_limit_pct,
            "drawdown_breached": drawdown_breached,
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason.value
            if self._kill_switch_reason
            else None,
        }

    # ── Loss Tracking API ──────────────────────────────────────────────────

    def record_trade_result(self, symbol: str, pnl: float) -> None:
        """
        Record a trade result to the loss tracker.

        Called by the trader agent or risk manager after a trade closes.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g., "MES", "AAPL")
        pnl : float
            Profit/loss in dollars
        """
        if self._loss_tracker is not None:
            is_win = self._loss_tracker.record_trade(symbol, pnl)
            logger.info(f"Trade recorded: {symbol} PnL=${pnl:.2f} ({'WIN' if is_win else 'LOSS'})")
        else:
            logger.debug(f"Loss tracker not available; trade not recorded: {symbol} PnL=${pnl:.2f}")

    def get_loss_tracker_status(self) -> dict:
        """
        Return current loss tracker status.

        Returns
        -------
        dict with comprehensive loss tracking state
        """
        if self._loss_tracker is None:
            return {"enabled": False, "message": "Loss tracker not available"}
        return {"enabled": True, **self._loss_tracker.get_status()}

    def reset_daily_pnl(self) -> dict[str, float | str]:
        """
        Reset in-memory daily realized PnL counters (human / ops / testing).

        Does not modify PnLMonitor or broker snapshots — only SafetyLayer counters.
        """
        self._daily_realized_pnl = 0.0
        self._daily_order_count = 0
        logger.warning("Daily PnL counters reset via API")
        return {"status": "ok", "daily_realized_pnl": 0.0}

    def orders_in_last_minute(self) -> int:
        """Count of order timestamps in the rolling 60s window (for circuit-breaker UI)."""
        now = time.time()
        self._recent_order_timestamps = [t for t in self._recent_order_timestamps if now - t < 60]
        return len(self._recent_order_timestamps)

    def reset_loss_tracker(self, symbol: Optional[str] = None) -> dict:
        """
        Manually reset loss tracker (human intervention).

        Parameters
        ----------
        symbol : str | None
            If None, reset global counter. Otherwise reset for this symbol.

        Returns
        -------
        dict with updated status
        """
        if self._loss_tracker is None:
            return {"status": "Loss tracker not available"}

        self._loss_tracker.reset(symbol=symbol)
        return {"status": "Reset successful", **self._loss_tracker.get_status()}

    async def _log_safety_event(
        self,
        event_type: str,
        reason: str,
        details: dict = None,
    ) -> None:
        """
        Log a safety event to PostgreSQL.

        Gracefully handles database unavailability — never blocks execution.

        Args:
            event_type: Type of event (kill_switch_activate, kill_switch_deactivate, etc.)
            reason: Human-readable reason
            details: Event details dict
        """
        try:
            from database import repository

            await repository.insert_safety_event(
                event_type=event_type,
                reason=reason,
                details=details,
                resolved=details.get("resolved", False) if details else False,
            )
            logger.debug(f"[DB] Safety event logged: {event_type}")
        except Exception as e:
            # Never block safety operations due to logging errors
            logger.warning(f"[DB] Failed to log safety event: {e}")

```

### `engine/main.py` (first 200 lines — full file is 4400 lines)
```python
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
from fastapi import APIRouter, FastAPI, HTTPException, Request
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
    CircuitBreakerStatus,
    DailyPnLResponse,
    DecisionHistoryResponse,
    DrawdownResponse,
    FullHealthResponse,
    HealthResponse,
    KillSwitchToggleResponse,
    NewsSentimentResponse,
    PaperPerformanceResponse,
    PaperPositionsResponse,
    PaperTradeResponse,
    PendingSignalsResponse,
    PortfolioResponse,
    RedditSentimentResponse,
    SafetyConfigResponse,
    SafetyStatusResponse,
    StatsSummaryResponse,
    TechnicalAnalysisResponse,
    TradeHistoryResponse,
)
from config import settings
from data.market_data import MarketDataManager
from database.schema import DatabaseManager, init_db
from execution.ib_gateway_connector import IBGatewayConnector
from execution.ib_order_manager import IBOrderManager
from llm.client import JarvisLLMClient
from llm.cost_tracker import CostTracker
from middleware.api_key_middleware import APIKeyMiddleware
from middleware.exception_handler import GlobalExceptionHandler
from middleware.rate_limit import get_limiter, rate_limit_exception_handler
from portfolio.tracker import PortfolioTracker
from risk.loss_tracker import ConsecutiveLossTracker
from risk.pnl_monitor import PnLMonitor
from risk.safety_layer import SafetyLayer
from routers.discord_router import router as discord_router
from routers.flags_router import router as flags_router
from routers.flags_router import set_flags as set_flags_router
from routers.journal_router import router as journal_router
from routers.journal_router import set_db_manager as set_journal_db
from routers.kairos_router import router as kairos_router
from routers.learning_router import router as learning_router
from routers.market_router import router as market_router
from routers.portfolio_router import inject_dependencies as inject_portfolio_deps
from routers.portfolio_router import router as portfolio_router
from routers.safety_router import inject_dependencies as inject_safety_router_deps
from routers.safety_router import router as safety_router
from routers.strategies_router import router as strategies_router
from routers.validation_router import router as validation_router
from routers.webhook_router import get_recent_webhooks
from routers.webhook_router import router as webhook_router
from schedulers.eod_scheduler import EODScheduler
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
ws_manager: WebSocketManager | None = None
cost_tracker: "CostTracker | None" = None
loss_tracker: "ConsecutiveLossTracker | None" = None

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
        ws_manager, \
        cost_tracker, \
        loss_tracker

    # Setup structured logging with file rotation FIRST, before any other initialization
    setup_logging(log_level=settings.LOG_LEVEL)
```

**Key additions to main.py** (search for these in the full file):

```python
# New imports added:
# line 77: from routers.flags_router import router as flags_router
# line 78: from routers.flags_router import set_flags as set_flags_router
# line 81: from routers.kairos_router import router as kairos_router
# line 218:     from flags import FeatureFlags, set_flags_instance
# line 220:     feature_flags = FeatureFlags(config=settings, db=db_manager)
# line 221:     set_flags_instance(feature_flags)
# line 222:     set_flags_router(feature_flags)
# line 571:             from risk.tilt_detector import TiltDetector
# line 573:             tilt_detector = TiltDetector(config=settings, loss_tracker=loss_tracker)
# line 575:             logger.info("✅ TiltDetector initialized")
# line 577:         logger.error(f"TiltDetector init failed (non-fatal): {_tilt_err}")
# line 604:             from kairos import KairosDaemon, set_kairos_instance
# line 616:             kairos_daemon = KairosDaemon(
# line 644:             from speculation import SpeculationEngine, set_speculation_engine
# line 646:             speculation_engine = SpeculationEngine(
# line 652:             logger.info("SpeculationEngine: initialized")
# line 659:                     f"SpeculationEngine: cycle {result['speculation_count']} — "
# line 680:                 "SpeculationEngine: pre-fetch job registered — fires at :15/:45 past each hour (9-4 CT weekdays)"
# line 683:             logger.error(f"SpeculationEngine init failed (non-fatal): {_spec_err}")
# line 685:         logger.info("SpeculationEngine: disabled (set ENABLE_SPECULATION=True to enable)")
# line 752: app.include_router(flags_router, prefix="/flags", tags=["feature-flags"])
# line 761: app.include_router(kairos_router)
```
