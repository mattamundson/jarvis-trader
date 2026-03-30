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

    def __init__(self, agents: dict, safety_layer, db_manager=None):
        """
        Args:
            agents:       Dict of named agent instances (see class docstring)
            safety_layer: SafetyLayer instance — provides get_status() and kill switch
            db_manager:   Optional DatabaseManager — if set, pipeline runs are persisted
        """
        self._agents = agents
        self._safety = safety_layer
        self.db_manager = db_manager

    async def analyze_and_decide(
        self,
        symbol: str,
        is_futures: bool = True,
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

        analyst_reports = await self._run_analysts(symbol, is_futures, errors)
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
        technical_coro = self._call_agent_analyze("technical", symbol, is_futures=is_futures)
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
        signal.get("symbol", "MES")
        action = signal.get("action", "HOLD")
        signal.get("source", "tradingview")

        str(uuid.uuid4())[:8]

        # Only run pipeline for actionable signals
        if action not in ("LONG", "SHORT", "CLOSE"):
            pass
