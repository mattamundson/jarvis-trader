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
    from profiling.pipeline_profiler import PipelineProfiler

    _PROFILER_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _PROFILER_AVAILABLE = False

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

__all__ = ["TradingPipeline", "pre_filter_signal"]


async def pre_filter_signal(
    symbol: str,
    timeframe: str,
    is_futures: bool,
    agents: dict,
) -> dict | None:
    """
    Pre-filter: skip pipeline when STC is mid-range (between OS+10 and OB-10).

    Args:
        symbol: Trading symbol
        timeframe: Timeframe (1h, 1d, etc.)
        is_futures: True if futures contract
        agents: Dict of agents (must include "technical" agent with _data)

    Returns:
        dict with pre-filter result if filter applied (HOLD action), or None to proceed
    """
    try:
        from backtest.signals import INSTRUMENT_PARAMS, generate_instrument_signals
        from config import settings as _cfg
        from routers.pipeline_router import record_signal_debug

        _tech_agent = agents.get("technical")
        _data_mgr = getattr(_tech_agent, "_data", None)
        if _data_mgr is None:
            return None

        _df = await _data_mgr.get_bars(
            symbol, lookback_days=5, timeframe=timeframe, is_futures=is_futures
        )
        if _df is None or _df.empty or len(_df) < 20:
            return None

        _sig_df = generate_instrument_signals(_df.copy(), symbol)
        if "stc_val" not in _sig_df.columns:
            return None

        _stc_val = float(_sig_df["stc_val"].iloc[-1])
        _params = INSTRUMENT_PARAMS.get(symbol, (15, 83, 0.70, 1.00, 1.618, 2.618, True))
        _stc_os, _stc_ob = int(_params[0]), int(_params[1])
        _mid_lo = float(_cfg.STC_MIDRANGE_SKIP_LOW)
        _mid_hi = float(_cfg.STC_MIDRANGE_SKIP_HIGH)

        if not _cfg.STC_MIDRANGE_SKIP_ENABLED or not (_mid_lo < _stc_val < _mid_hi):
            logger.debug(
                "[pre_filter_signal] symbol=%s stc_val=%.1f range=(%.0f–%.0f) action=PASS",
                symbol,
                _stc_val,
                _mid_lo,
                _mid_hi,
            )
            record_signal_debug(
                {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol,
                    "stc_val": round(_stc_val, 2),
                    "stage_blocked": "approved",
                    "reason": f"STC {_stc_val:.1f} outside skip range",
                }
            )
            return None

        logger.info(
            "[pre_filter_signal] symbol=%s stc_val=%.1f range=(%.0f–%.0f) action=SKIP",
            symbol,
            _stc_val,
            _mid_lo,
            _mid_hi,
        )
        record_signal_debug(
            {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "stc_val": round(_stc_val, 2),
                "stage_blocked": "pre_filter",
                "reason": f"STC {_stc_val:.1f} in skip range",
            }
        )

        return {
            "symbol": symbol,
            "is_futures": is_futures,
            "started_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat(),
            "final_action": "hold",
            "final_quantity": 0,
            "requires_human": False,
            "pre_filtered": True,
            "pre_filter_reason": "STC mid-range pre-filter",
            "pre_filter_stc": round(_stc_val, 2),
            "pre_filter_stc_os": _stc_os,
            "pre_filter_stc_ob": _stc_ob,
            "errors": [],
            "cache_hit": False,
        }

    except Exception as e:
        logger.debug("[pre_filter_signal] %s skipped: %s", symbol, e)
        return None


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
        self.profiler = PipelineProfiler() if _PROFILER_AVAILABLE else None

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
            "timeframe": timeframe,
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

        # ── STC Mid-Range Pre-Filter ───────────────────────────────────────────
        pre_filter_result = await pre_filter_signal(symbol, timeframe, is_futures, self._agents)
        if pre_filter_result is not None:
            return pre_filter_result

        # ── Stage 1: Analysts in parallel ─────────────────────────────────

        if self.profiler:
            await self.profiler.start_stage("analysts")
        analyst_reports = await self._run_analysts(symbol, is_futures, errors, timeframe=timeframe)
        if self.profiler:
            await self.profiler.end_stage("analysts")
        pipeline_result["analyst_reports"] = analyst_reports

        # ── Stage 2: Bull/Bear Debate ──────────────────────────────────────

        if self.profiler:
            await self.profiler.start_stage("debate")
        debate_result = await self._run_debate(symbol, analyst_reports, errors)
        if self.profiler:
            await self.profiler.end_stage("debate")
        pipeline_result["debate_result"] = debate_result

        # ── Stage 3: Trader Decision ───────────────────────────────────────

        if self.profiler:
            await self.profiler.start_stage("trader")
        safety_status = self._safety.get_status()
        trade_decision = await self._run_trader(
            symbol, debate_result, analyst_reports, safety_status, errors
        )
        if self.profiler:
            await self.profiler.end_stage("trader")
        pipeline_result["trade_decision"] = trade_decision

        # ── Stage 4: Risk Manager Review ──────────────────────────────────

        if self.profiler:
            await self.profiler.start_stage("risk_manager")
        # We always pass an empty portfolio if none is available — callers should
        # inject a real portfolio dict via a wrapper or subclass
        portfolio = await self._get_portfolio()
        risk_decision = await self._run_risk_manager(
            trade_decision, safety_status, portfolio, errors
        )
        if self.profiler:
            await self.profiler.end_stage("risk_manager")
        pipeline_result["risk_decision"] = risk_decision

        # ── Stage 5: Fund Manager (only if Risk Manager approved) ──────────

        fund_decision: Optional[dict] = None
        if risk_decision.get("approved", False):
            if self.profiler:
                await self.profiler.start_stage("fund_manager")
            open_positions = portfolio.get("positions", [])
            fund_decision = await self._run_fund_manager(
                trade_decision, risk_decision, portfolio, open_positions, errors
            )
            if self.profiler:
                await self.profiler.end_stage("fund_manager")
        else:
            logger.info(f"[Pipeline] Risk Manager vetoed {symbol} — skipping Fund Manager")

        pipeline_result["fund_decision"] = fund_decision

        # ── Resolve final action ───────────────────────────────────────────

        final_action, final_quantity, requires_human = self._resolve_final_action(
            trade_decision, risk_decision, fund_decision
        )

        # ── Futures confidence boost + minimum confidence gate ─────────────
        # Apply futures-specific tuning before committing the final action.
        # Futures (MCL, MNQ, MES) have cleaner technical signals but fewer
        # available analyst inputs (no fundamentals/social), so:
        #   1. Apply a small additive confidence boost to compensate
        #   2. Gate directional signals on instrument-specific min-confidence
        # This prevents low-data HOLDs from leaking through as weak directional
        # signals while also catching genuinely low-confidence reads.
        if final_action not in ("hold", "HOLD"):
            try:
                from config import settings as _cfg
                raw_confidence = float(trade_decision.get("confidence", 0.0))
                if is_futures:
                    boosted = raw_confidence + float(_cfg.FUTURES_CONFIDENCE_BOOST)
                    min_thresh = float(_cfg.FUTURES_MIN_CONFIDENCE_TO_TRADE)
                else:
                    boosted = raw_confidence  # no boost for equities
                    min_thresh = float(_cfg.EQUITY_MIN_CONFIDENCE_TO_TRADE)

                # Also skip zero-weight technical reports (no_price_data abstentions)
                tech_weight = (
                    analyst_reports.get("technical", {})
                    .get("indicators", {})
                    .get("weight", 1.0)  # default 1.0 = normal weight
                )
                if tech_weight == 0.0:
                    logger.warning(
                        "[Pipeline] %s: technical analyst abstained (no_price_data) — "
                        "confidence computed without technical input",
                        symbol,
                    )
                    # Without technical signal, drop below threshold to force HOLD
                    boosted = 0.0

                pipeline_result["raw_confidence"] = round(raw_confidence, 4)
                pipeline_result["boosted_confidence"] = round(boosted, 4)
                pipeline_result["confidence_threshold"] = round(min_thresh, 4)

                if boosted < min_thresh:
                    logger.info(
                        "[Pipeline] %s: confidence %.2f (boosted from %.2f) below threshold %.2f "
                        "— downgrading %s → HOLD",
                        symbol, boosted, raw_confidence, min_thresh, final_action.upper(),
                    )
                    final_action = "hold"
                    final_quantity = 0
                    pipeline_result["confidence_gate_triggered"] = True
                    pipeline_result["confidence_gate_reason"] = (
                        f"boosted_confidence={boosted:.3f} < threshold={min_thresh:.3f}"
                    )
                else:
                    pipeline_result["confidence_gate_triggered"] = False
                    logger.debug(
                        "[Pipeline] %s: confidence %.2f (boosted %.2f) ≥ threshold %.2f — "
                        "%s passes gate",
                        symbol, raw_confidence, boosted, min_thresh, final_action.upper(),
                    )
            except Exception as _cg_err:
                logger.warning("[Pipeline] Confidence gate error (non-fatal): %s", _cg_err)

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

        # Finish profiler run (stores report in history)
        if self.profiler:
            await self.profiler.finish_run()

        # Publish pipeline result event
        try:
            from events.bus import publish as publish_event
            _ev_action = pipeline_result.get('final_action', 'HOLD').upper()
            _ev_conviction = pipeline_result.get('boosted_confidence', 0.0)
            publish_event(
                'pipeline_run',
                f'{symbol} → {_ev_action} confidence={_ev_conviction:.0%}',
                symbol=symbol,
                severity='info'
            )
        except Exception as e:
            logger.warning(f"Failed to publish pipeline event: {e}")
        
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
                    result = report.to_dict()
                elif isinstance(report, dict):
                    result = report
                else:
                    result = {
                        "signal": 0.0,
                        "confidence": 0.0,
                        "summary": f"{name} returned unexpected type",
                    }
                # Detect and log zero-weight abstentions
                # (e.g. technical analyst returning no_price_data)
                indicators = result.get("indicators", {})
                if isinstance(indicators, dict) and indicators.get("weight") == 0.0:
                    reason = indicators.get("reason", "unknown")
                    logger.warning(
                        "[Pipeline] %s analyst abstained (weight=0.0, reason=%s) — "
                        "excluded from confidence computation",
                        name, reason,
                    )
                return result
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

    # Symbols that bypass Fund Manager review when Risk Manager has approved.
    # Matt Morrison (system owner) has explicitly authorized these bypasses.
    FUND_MANAGER_BYPASS_SYMBOLS = {"MES"}

    def _resolve_final_action(
        self, trade_decision: dict, risk_decision: dict, fund_decision: dict
    ) -> tuple:
        """
        Resolve final action from multi-stage decisions.

        Logic:
        1. If risk manager rejected → HOLD
        2. If symbol is in FUND_MANAGER_BYPASS_SYMBOLS and risk approved → execute directly
        3. If fund manager rejected → HOLD
        4. Otherwise use fund_decision action/quantity

        Returns: (final_action, final_quantity, requires_human)
        """
        # Risk manager veto
        if risk_decision and not risk_decision.get("approved", False):
            logger.info("[Resolution] Risk manager veto → HOLD")
            return "hold", 0, False

        # Owner-authorized bypass: skip Fund Manager for specified symbols
        symbol = (trade_decision or {}).get("symbol", "")
        if symbol in self.FUND_MANAGER_BYPASS_SYMBOLS:
            action = (trade_decision or {}).get("action", "hold").lower()
            quantity = risk_decision.get("modified_quantity") or (trade_decision or {}).get(
                "quantity", 1
            )
            logger.info(
                f"[Resolution] {symbol} bypass — Fund Manager skipped → {action} qty={quantity}"
            )
            return action, int(quantity), False

        # Fund manager decision — fix schema: FundDecision.to_dict() uses "approved"/"final_quantity"
        if fund_decision:
            approved = fund_decision.get("approved", fund_decision.get("execute", False))
            if not approved:
                logger.info("[Resolution] Fund manager rejected → HOLD")
                return "hold", 0, False

            priority = fund_decision.get("priority", "skip")
            if priority == "skip":
                logger.info("[Resolution] Fund manager priority=skip → HOLD")
                return "hold", 0, False

            action = (trade_decision or {}).get("action", "hold").lower()
            quantity = fund_decision.get(
                "final_quantity", fund_decision.get("contracts", fund_decision.get("quantity", 0))
            )
            requires_human = fund_decision.get(
                "requires_human_approval", fund_decision.get("human_approval_required", False)
            )
            logger.info(
                f"[Resolution] Fund approved → {action} qty={quantity} human={requires_human}"
            )
            return action, int(quantity), requires_human

        # Fallback: use trade decision if we got here (risk approved but no fund decision)
        if trade_decision:
            action = trade_decision.get("action", "hold").lower()
            quantity = trade_decision.get("quantity", 0)
            logger.info(f"[Resolution] No fund decision, using trade → {action} qty={quantity}")
            return action, int(quantity), False

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
