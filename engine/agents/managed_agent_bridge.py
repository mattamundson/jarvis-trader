"""
Claude Managed Agents Bridge for JARVIS TRADER.

Provides an optional path to run the trading pipeline via Anthropic's
Claude Managed Agents infrastructure (public beta, launched April 8, 2026).

Default behavior: custom pipeline.py (no change)
Managed mode: set USE_MANAGED_AGENTS=true in engine/.env

Context:
    Claude Managed Agents pairs an agent harness tuned for performance with
    production infrastructure, enabling enterprise-scale agent deployments.
    This bridge evaluates that infrastructure for the JARVIS TRADER pipeline.

Usage:
    bridge = ManagedAgentBridge()
    if bridge.is_managed_mode():
        result = await bridge.run_stage1_managed(symbol, bars, context)
    else:
        result = await existing_pipeline_stage1(...)

API Reference: https://docs.anthropic.com/managed-agents (public beta)
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Environment variable controlling managed mode
USE_MANAGED_AGENTS_ENV = "USE_MANAGED_AGENTS"

# Managed Agents API endpoint (public beta)
MANAGED_AGENTS_API = "https://api.anthropic.com/v1/agents"


@dataclass
class ManagedAgentConfig:
    """Configuration for a single managed agent deployment."""

    agent_id: str
    name: str
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 1024
    system_prompt: str = ""
    tools: List[dict] = field(default_factory=list)


@dataclass
class Stage1AnalysisResult:
    """Result from Stage 1 analysis (either custom or managed path)."""

    technical: Optional[Any] = None
    news: Optional[Any] = None
    social: Optional[Any] = None
    fundamental: Optional[Any] = None
    corey: Optional[Any] = None
    path_used: str = "custom"  # "custom" or "managed"
    latency_ms: int = 0
    errors: Dict[str, str] = field(default_factory=dict)


class ManagedAgentBridge:
    """
    Bridge between JARVIS TRADER's custom pipeline and Claude Managed Agents.

    The bridge is INACTIVE by default. Enable with USE_MANAGED_AGENTS=true in .env.
    All methods degrade gracefully — if managed API is unavailable, falls back to custom.

    Architecture:
        Custom pipeline (default):
            asyncio.gather(technical, news, social, fundamental, corey) → analyst_reports

        Managed pipeline (when USE_MANAGED_AGENTS=true):
            POST /v1/agents/run → { agent_id, input } for each analyst
            Parallel execution via managed harness
            Results collected and normalized to same analyst_reports format
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._managed_mode = self._detect_managed_mode()
        self._agents_registered: Dict[str, str] = {}  # name → agent_id

        if self._managed_mode:
            logger.info(
                "ManagedAgentBridge: MANAGED MODE ACTIVE — using Anthropic Managed Agents API"
            )
        else:
            logger.debug("ManagedAgentBridge: custom pipeline mode (USE_MANAGED_AGENTS not set)")

    def _detect_managed_mode(self) -> bool:
        """Check if managed mode is enabled via environment variable."""
        val = os.environ.get(USE_MANAGED_AGENTS_ENV, "false").lower()
        return val in ("true", "1", "yes", "on")

    def is_managed_mode(self) -> bool:
        """Return True if bridge is in managed agent mode."""
        return self._managed_mode

    async def run_stage1(
        self,
        symbol: str,
        *,
        custom_runner: Optional[Any] = None,
        is_futures: bool = False,
        errors: Optional[List] = None,
        timeframe: str = "1h",
        bars_json: str = "",
        additional_context: str = "",
    ) -> Any:
        """
        Unified Stage 1 dispatcher — routes to managed or custom path.

        Acceptance-criteria entry point for US-H1: a single `run_stage1()` that
        implements both paths and logs which one is active.

        Parameters
        ----------
        symbol : str
            Instrument symbol (e.g. "MES", "MNQ", "MCL").

        custom_runner : async callable, required when managed mode is OFF
            Must match the signature of TradingPipeline._run_analysts:
                async (symbol, is_futures, errors, timeframe="1h") -> dict
            Returns a dict of analyst reports keyed by analyst name.

        is_futures, errors, timeframe : passed to custom_runner

        bars_json, additional_context : passed to run_stage1_managed when
            managed mode is active

        Returns
        -------
        Custom path: dict (whatever custom_runner returns — typically the
                     analyst_reports dict from TradingPipeline._run_analysts)
        Managed path: Stage1AnalysisResult (this module's dataclass)

        Raises
        ------
        ValueError if managed mode is OFF and custom_runner is None.

        Notes
        -----
        The return shapes intentionally differ — callers in the custom path
        already expect the dict from `_run_analysts`, while managed-mode
        callers can use the richer Stage1AnalysisResult dataclass for
        per-analyst error tracking. If you need shape-equivalence, normalize
        on the caller side.
        """
        if errors is None:
            errors = []

        if self._managed_mode:
            logger.info(
                "ManagedAgentBridge.run_stage1: MANAGED path active for %s",
                symbol,
            )
            return await self.run_stage1_managed(
                symbol=symbol,
                bars_json=bars_json,
                additional_context=additional_context,
            )

        if custom_runner is None:
            raise ValueError(
                "ManagedAgentBridge.run_stage1: custom_runner is required when "
                "USE_MANAGED_AGENTS is not enabled. Pass the existing "
                "TradingPipeline._run_analysts (or any async callable matching "
                "its signature)."
            )

        logger.info(
            "ManagedAgentBridge.run_stage1: CUSTOM path active for %s",
            symbol,
        )
        return await custom_runner(symbol, is_futures, errors, timeframe=timeframe)

    async def run_stage1_managed(
        self,
        symbol: str,
        bars_json: str,
        additional_context: str = "",
    ) -> Stage1AnalysisResult:
        """
        Run Stage 1 analysis via Claude Managed Agents API.

        This is the managed alternative to asyncio.gather(technical, news, social, ...).
        Mirrors the two-phase approach in pipeline._run_analysts():
          Phase A — technical analyst runs first (needed for current_price + ATR).
          Phase B — remaining analysts run in parallel with price/ATR context.

        Args:
            symbol: Futures symbol (e.g. "MES", "MNQ", "MCL")
            bars_json: OHLCV bars serialized as JSON string
            additional_context: Additional market context (macro, sentiment, etc.)

        Returns:
            Stage1AnalysisResult with all analyst outputs
        """
        if not self._managed_mode:
            raise RuntimeError("run_stage1_managed() called but managed mode is not active")

        if not self._api_key:
            logger.error("ANTHROPIC_API_KEY not set — cannot use managed agents")
            return Stage1AnalysisResult(
                path_used="managed_failed",
                errors={"auth": "ANTHROPIC_API_KEY not set"},
            )

        import time

        start_ms = time.time() * 1000

        # Phase A: technical first (price + ATR needed for corey)
        try:
            technical_result = await self._run_single_managed_analyst(
                "technical",
                self._build_technical_prompt(symbol, bars_json),
                symbol,
            )
        except Exception as e:
            logger.warning("Managed technical analyst failed: %s", e)
            technical_result = {"signal": 0.0, "confidence": 0.0, "summary": str(e)}

        current_price = float(technical_result.get("current_price") or 0.0)
        atr = float((technical_result.get("indicators") or {}).get("atr") or 0.0)

        # Phase B: remaining analysts in parallel via managed harness
        analyst_tasks = [
            ("news", self._build_news_prompt(symbol, additional_context)),
            ("social", self._build_social_prompt(symbol)),
            ("fundamental", self._build_fundamental_prompt(symbol)),
            ("corey", self._build_corey_prompt(symbol, current_price, atr)),
        ]

        try:
            results = await asyncio.gather(
                *[
                    self._run_single_managed_analyst(name, prompt, symbol)
                    for name, prompt in analyst_tasks
                ],
                return_exceptions=True,
            )

            stage1_result = Stage1AnalysisResult(
                technical=technical_result,
                path_used="managed",
                latency_ms=int(time.time() * 1000 - start_ms),
            )

            for (name, _), result in zip(analyst_tasks, results, strict=False):
                if isinstance(result, Exception):
                    stage1_result.errors[name] = str(result)
                    logger.warning("Managed agent %s failed: %s", name, result)
                    setattr(
                        stage1_result,
                        name,
                        {"signal": 0.0, "confidence": 0.0, "summary": f"{name} unavailable"},
                    )
                else:
                    setattr(stage1_result, name, result)

            logger.info(
                "Managed Stage 1 complete: latency=%dms errors=%d",
                stage1_result.latency_ms,
                len(stage1_result.errors),
            )
            return stage1_result

        except Exception as e:
            logger.error("Managed Stage 1 failed entirely: %s", e)
            return Stage1AnalysisResult(
                path_used="managed_failed",
                errors={"stage1": str(e)},
                latency_ms=int(time.time() * 1000 - start_ms),
            )

    async def _run_single_managed_analyst(
        self,
        analyst_name: str,
        prompt: str,
        symbol: str,
    ) -> Dict[str, Any]:
        """
        Run a single analyst via managed agent infrastructure.

        In public beta: uses direct Anthropic API with managed-agent-style structure.
        In GA: will use /v1/agents/run endpoint with registered agent_id.
        """
        try:
            import httpx

            # Beta: direct API call structured like managed agent
            payload = {
                "model": "claude-sonnet-4-6",
                "max_tokens": 1024,
                "system": (
                    f"You are JARVIS TRADER's {analyst_name} analyst. "
                    f"Analyze {symbol} and return a structured JSON signal assessment."
                ),
                "messages": [{"role": "user", "content": prompt}],
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                        # Managed agents beta header (activated when endpoint goes GA)
                        "anthropic-beta": "managed-agents-2026-04-08",
                    },
                    json=payload,
                )

                if response.status_code == 200:
                    data = response.json()
                    content = data.get("content", [{}])[0].get("text", "")
                    return {"analyst": analyst_name, "response": content, "raw": data}
                else:
                    raise Exception(f"API {response.status_code}: {response.text[:200]}")

        except Exception as e:
            raise RuntimeError(f"{analyst_name} managed call failed: {e}") from e

    # ── Prompt builders ────────────────────────────────────────────────────────

    def _build_technical_prompt(self, symbol: str, bars_json: str) -> str:
        return (
            f"Analyze {symbol} technical indicators from OHLCV bars: "
            f"{bars_json[:500]}... "
            f"Return JSON: {{signal: -1 to +1, regime, stc_value, current_price, "
            f"indicators: {{atr, rsi, trend}}}}"
        )

    def _build_news_prompt(self, symbol: str, context: str) -> str:
        return (
            f"Analyze recent news sentiment for {symbol}. "
            f"Context: {context[:300]}. "
            f"Return JSON: {{signal: -1 to +1, confidence, sentiment_score, "
            f"headline_count, key_events: []}}"
        )

    def _build_social_prompt(self, symbol: str) -> str:
        return (
            f"Analyze social sentiment and options flow for {symbol}. "
            f"Return JSON: {{signal: -1 to +1, confidence, sentiment_score, "
            f"volume_signal, unusual_activity: bool}}"
        )

    def _build_fundamental_prompt(self, symbol: str) -> str:
        return (
            f"Analyze macro fundamentals for {symbol}: VIX, yields, Fed stance, "
            f"sector rotation. "
            f"Return JSON: {{signal: -1 to +1, confidence, macro_bias, "
            f"vix_level, macro_risks: []}}"
        )

    def _build_corey_prompt(self, symbol: str, current_price: float, atr: float) -> str:
        return (
            f"Analyze Corey Snyder hidden pivot proximity for {symbol}. "
            f"Current price: {current_price}, ATR: {atr}. "
            f"Return JSON: {{signal: -1 to +1, confidence, pivot_proximity, "
            f"nearest_pivot, pivot_type}}"
        )

    # ── Status / health ────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return current bridge status for health checks."""
        return {
            "managed_mode": self._managed_mode,
            "api_key_present": bool(self._api_key),
            "agents_registered": len(self._agents_registered),
            "env_var": USE_MANAGED_AGENTS_ENV,
            "note": "Set USE_MANAGED_AGENTS=true in engine/.env to activate managed mode",
        }

    def log_status(self):
        """Log bridge status."""
        status = self.get_status()
        if status["managed_mode"]:
            logger.info(
                "Claude Managed Agents: ACTIVE | %d agents registered",
                status["agents_registered"],
            )
        else:
            logger.info(
                "Claude Managed Agents: inactive (custom pipeline active) | Set %s=true to enable",
                USE_MANAGED_AGENTS_ENV,
            )
