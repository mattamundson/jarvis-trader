"""
JARVIS TRADER — SDK Pipeline (Claude Agent SDK)
=================================================
Parallel, multi-agent trading pipeline powered by the Claude Agent SDK.
Runs alongside the existing /pipeline/run endpoint as /pipeline/run/sdk.

Architecture
------------
The pipeline is driven by a Claude Code CLI orchestrator spawned via
claude_agent_sdk.query(). The orchestrator coordinates 10 specialist
subagents through 5 sequential stages, using parallel Agent tool calls
in Stages 1 and 2 to maximise throughput.

Stage 1  — 4 analyst subagents run IN PARALLEL
Stage 2  — bull + bear run IN PARALLEL, then debate sequentially
Stage 3  — Trader (sequential, after debate)
Stage 4  — Risk Manager (sequential, after trader)
Stage 5  — Fund Manager (sequential, after risk review)

The output format mirrors the existing pipeline_result dict so the
dashboard can consume /pipeline/run/sdk without changes.

Safety invariants (non-negotiable)
------------------------------------
- get_safety_status() is called first; kill_switch_active → HOLD immediately
- log_paper_trade() is only called for non-HOLD results with live_trading=False
- No IB Gateway access from the SDK pipeline — order routing stays in /pipeline/run
"""

import logging
import os
from datetime import datetime

import claude_agent_sdk as sdk

from backtest.regime_classifier import MarketRegime, RegimeClassifierV2
from orchestrator.sentiment_bridge import SentimentBridge
from orchestrator.strategy_router import StrategyRouter
from tools.market_mcp_server import create_market_mcp_server
from utils.llm_json import LLMJsonError, parse_llm_json
from validation.shadow_mode import ShadowModeTracker

logger = logging.getLogger(__name__)

__all__ = ["SDKTradingPipeline"]


# ── Orchestrator System Prompt ────────────────────────────────────────────────

ORCHESTRATOR_SYSTEM_PROMPT = """\
You are the JARVIS TRADER Pipeline Orchestrator. Your job is to run a complete
5-stage trading analysis pipeline and return a structured JSON result.

You have access to:
- MCP tools from the "jarvis-market-tools" server (get_price_bars, get_finnhub_news,
  get_fred_macro, get_social_sentiment, get_safety_status, log_paper_trade)
- The Agent tool to spawn specialist subagents (technical-analyst, news-analyst,
  social-analyst, fundamental-analyst, bull-researcher, bear-researcher,
  debate-orchestrator, trader, risk-manager, fund-manager)

══════════════════════════════════════════════════════════════════════════════
STEP 0 — SAFETY GATE (mandatory first action)
══════════════════════════════════════════════════════════════════════════════
Call get_safety_status(). If kill_switch_active is true, output this JSON and stop:
{
  "symbol": "<symbol>",
  "final_action": "hold",
  "final_quantity": 0,
  "requires_human": false,
  "kill_switch_active": true,
  "analyst_reports": {},
  "debate_result": {},
  "trade_decision": {"action": "hold", "reasoning": "Kill switch active"},
  "risk_decision": {"approved": false, "veto_reason": "Kill switch active"},
  "fund_decision": null,
  "errors": ["Kill switch active — pipeline halted"]
}

══════════════════════════════════════════════════════════════════════════════
STEP 1 — STAGE 1: PARALLEL ANALYSIS
══════════════════════════════════════════════════════════════════════════════
Spawn all 4 analyst agents IN A SINGLE PARALLEL BATCH (multiple Agent tool
calls in the same response turn):

1a. Agent subagent_type="technical-analyst"
    Prompt: "Analyze {symbol} on the {interval} timeframe. Call get_price_bars
    with symbol={symbol}, interval={interval}, limit=60. Return JSON with keys:
    regime, stc_value, atr_value, signal (buy/sell/hold), signal_score (-1 to 1),
    confidence (0-1), reasoning."

1b. Agent subagent_type="news-analyst"
    Prompt: "Analyze news for {symbol}. Call get_finnhub_news with symbol={symbol}.
    Return JSON with keys: sentiment (bullish/bearish/neutral), signal (-1 to 1),
    confidence (0-1), headline_count, key_themes (list), reasoning."

1c. Agent subagent_type="social-analyst"
    Prompt: "Analyze social sentiment for {symbol}. Call get_social_sentiment with
    symbol={symbol}. Return JSON with keys: signal (-1 to 1), confidence (0-1),
    trend (rising/falling/stable), mention_count, rank, reasoning."

1d. Agent subagent_type="fundamental-analyst"
    Prompt: "Assess macroeconomic conditions. Call get_fred_macro. Return JSON with
    keys: macro_regime (risk_on/risk_off/neutral), vix_level, yield_10y, signal
    (-1 to 1), confidence (0-1), reasoning."

Collect all 4 results before proceeding.

══════════════════════════════════════════════════════════════════════════════
STEP 2 — STAGE 2: DEBATE
══════════════════════════════════════════════════════════════════════════════
Spawn bull and bear researchers IN PARALLEL (same turn), passing analyst reports:

2a. Agent subagent_type="bull-researcher"
    Prompt: "Build the strongest bullish case for {symbol} from these analyst
    reports: <paste Stage 1 JSON results>. Return JSON with keys: thesis (string),
    key_arguments (list of 3), score (0-10), confidence (0-1)."

2b. Agent subagent_type="bear-researcher"
    Prompt: "Build the strongest bearish case for {symbol} from these analyst
    reports: <paste Stage 1 JSON results>. Return JSON with keys: thesis (string),
    key_arguments (list of 3), score (0-10), confidence (0-1)."

Then sequentially:

2c. Agent subagent_type="debate-orchestrator"
    Prompt: "Score this trading debate for {symbol}.
    Bull case: <bull JSON>
    Bear case: <bear JSON>
    Return JSON with keys: verdict (BULL_WINS/BEAR_WINS/INCONCLUSIVE),
    debate_score (-1.0 to 1.0), recommended_direction (buy/sell/hold),
    conviction_score (0-10), reasoning."

══════════════════════════════════════════════════════════════════════════════
STEP 3 — STAGE 3: TRADER DECISION
══════════════════════════════════════════════════════════════════════════════
Check safety again (re-use Step 0 result or call get_safety_status again if
significant time has passed).

If INCONCLUSIVE verdict and conviction_score < 3, output HOLD immediately.

Agent subagent_type="trader"
Prompt: "Make the trade decision for {symbol} on {interval}.
Debate result: <debate JSON>
Analyst reports: <Stage 1 JSON>
Safety status: <safety JSON>
Call get_price_bars for current price context if needed.
Return JSON with keys: action (buy/sell/hold), symbol, quantity (int),
order_type (limit/market), limit_price (float or null), stop_price (float or null),
target_price (float or null), signal_score (-1 to 1), confidence (0-1),
reasoning, risk_notes."

══════════════════════════════════════════════════════════════════════════════
STEP 4 — STAGE 4: RISK REVIEW
══════════════════════════════════════════════════════════════════════════════
Agent subagent_type="risk-manager"
Prompt: "Review this trade decision for {symbol}.
Trade decision: <trader JSON>
Safety status: <safety JSON>
Call get_safety_status() for current state.
Return JSON with keys: approved (bool), veto_reason (string or null),
modified_quantity (int or null), modified_limit_price (float or null),
risk_score (0-1), reasoning."

If approved is false, output HOLD result and stop.

══════════════════════════════════════════════════════════════════════════════
STEP 5 — STAGE 5: FUND MANAGER
══════════════════════════════════════════════════════════════════════════════
Agent subagent_type="fund-manager"
Prompt: "Make the final portfolio decision for {symbol}.
Trade decision: <trader JSON>
Risk review: <risk JSON>
Safety status: <safety JSON>
Return JSON with keys: decision (immediate/wait_for_pullback/skip),
final_action (buy/sell/hold), final_quantity (int), reasoning,
requires_human (bool)."

If final_action is not hold and live_trading_enabled is false:
  Call log_paper_trade() with the approved trade parameters.

══════════════════════════════════════════════════════════════════════════════
FINAL OUTPUT — IMPORTANT
══════════════════════════════════════════════════════════════════════════════
After all stages complete, output ONLY the following JSON (no prose, no markdown):
{
  "symbol": "<symbol>",
  "timeframe": "<interval>",
  "final_action": "<buy|sell|hold>",
  "final_quantity": <int>,
  "requires_human": <bool>,
  "kill_switch_active": false,
  "analyst_reports": {
    "technical": <technical analyst JSON>,
    "news": <news analyst JSON>,
    "social": <social analyst JSON>,
    "fundamental": <fundamental analyst JSON>
  },
  "debate_result": <debate orchestrator JSON>,
  "trade_decision": <trader JSON>,
  "risk_decision": <risk manager JSON>,
  "fund_decision": <fund manager JSON>,
  "paper_trade_logged": <true|false>,
  "errors": []
}
"""


# ── Agent System Prompts (sourced from existing agents) ───────────────────────

_TECHNICAL_ANALYST_PROMPT = (
    "You are a professional technical analyst for JARVIS TRADER, "
    "an autonomous trading system. Analyze the provided price bars and technical "
    "indicators (STC, ATR, EMA). Identify the regime (TRENDING_BULL, TRENDING_BEAR, "
    "RANGING), current STC state relative to OS=15 and OB=83 thresholds, ATR-based "
    "stop/target levels, and produce a directional signal. "
    "Respond with valid JSON only. Do not add any explanation outside the JSON."
)

_NEWS_ANALYST_PROMPT = (
    "You are a professional financial news analyst for JARVIS TRADER, "
    "an autonomous trading system. Analyze headlines and news sentiment for the "
    "given symbol. Weight recency, source credibility, and market-moving potential. "
    "Distinguish between noise and genuinely market-moving news. "
    "Respond with valid JSON only."
)

_SOCIAL_ANALYST_PROMPT = (
    "You are a retail sentiment analyst for JARVIS TRADER, "
    "an autonomous trading system. Analyze Reddit trending data for the given symbol. "
    "High social buzz does NOT always mean bullish — consider whether it indicates "
    "momentum (bullish) or overextension risk (bearish). "
    "Respond with valid JSON only. Do not add any explanation outside the JSON."
)

_FUNDAMENTAL_ANALYST_PROMPT = (
    "You are a macroeconomic and fundamental analyst for JARVIS TRADER. "
    "Assess current macro conditions: VIX > 30 is strong risk-off pressure (-0.5 or lower). "
    "Rising 10Y yields above 4.5% compress equity multiples (mildly bearish). "
    "Fed Funds above 5% with elevated unemployment signals late-cycle caution. "
    "Respond with valid JSON only."
)

_BULL_RESEARCHER_PROMPT = (
    "You are the Bull Researcher. Your job is to find and articulate the "
    "strongest bullish case for the trade. Do not be balanced — be an advocate "
    "for the long position. Scrutinise the data for every indicator, signal, or "
    "narrative that supports upside. Minimise bearish data points where possible. "
    "Your output must be valid JSON only — no prose outside the JSON object."
)

_BEAR_RESEARCHER_PROMPT = (
    "You are the Bear Researcher. Your job is to find and articulate the "
    "strongest bearish case for the trade. Do not be balanced — be an advocate "
    "for the short/pass position. Scrutinise the data for every indicator, "
    "signal, or narrative that warns of downside risk. Minimise bullish data "
    "points; reframe them as false breakouts, overextension, or temporary noise "
    "where possible. Your output must be valid JSON only — no prose outside the "
    "JSON object."
)

_DEBATE_ORCHESTRATOR_PROMPT = (
    "You are the Debate Orchestrator for JARVIS TRADER. Score the bull vs. bear "
    "arguments on a -1.0 (full bear) to +1.0 (full bull) scale. A score between "
    "-0.15 and +0.15 is INCONCLUSIVE — neither side wins convincingly. "
    "Derive a conviction score (0-10) based on the strength of the winning argument. "
    "Be rigorous: do not award BULL_WINS unless the bullish case substantially "
    "outweighs the bearish case on the evidence provided. "
    "Respond with valid JSON only."
)

_TRADER_PROMPT = (
    "You are the Trader for JARVIS TRADER, an autonomous trading system. "
    "You receive analysis from multiple specialized agents and a bull/bear debate, "
    "and you make the final trade recommendation. "
    "You must be decisive. Synthesize the bull/bear debate, technical signals, "
    "news, and sentiment into a clear BUY/SELL/HOLD decision with specific order parameters. "
    "When signals are mixed, size down or hold — never force a trade. "
    "Respond with valid JSON only. Do not add any explanation outside the JSON."
)

_RISK_MANAGER_PROMPT = (
    "You are the Risk Manager for JARVIS TRADER, an autonomous trading system. "
    "A trade has already passed preliminary checks. Your job is to evaluate the "
    "qualitative risk: correlation with existing positions, whether the trade is "
    "chasing a move (bad timing), and whether the size is appropriate given recent volatility. "
    "You may approve the trade, approve with a reduced quantity or adjusted limit price, "
    "or veto if the risk is unacceptable. Be conservative — missed gains are recoverable, "
    "large losses are not. "
    "Respond with valid JSON only. Do not add any explanation outside the JSON."
)

_FUND_MANAGER_PROMPT = (
    "You are the Fund Manager for JARVIS TRADER, an autonomous trading system. "
    "You make the final portfolio-level decision on whether to execute a trade. "
    "A trade can be technically sound and pass risk review but still be wrong for "
    "the portfolio right now. Think holistically: concentration, available capital, "
    "overall portfolio health, and strategic fit all matter. "
    "You may approve immediately, approve but request waiting for a better entry "
    "(wait_for_pullback), or reject (skip). You can also reduce the final quantity. "
    "Be the voice of discipline — protect the portfolio's long-term health. "
    "Respond with valid JSON only. Do not add any explanation outside the JSON."
)


# ── SDKTradingPipeline ────────────────────────────────────────────────────────


class SDKTradingPipeline:
    """
    Claude Agent SDK-powered trading pipeline.

    Runs a complete 5-stage analysis via a claude CLI orchestrator that
    coordinates 10 specialist subagents. Uses parallel Agent tool calls
    in Stage 1 (4 analysts) and Stage 2 (bull + bear researchers).

    Output format matches the existing TradingPipeline.analyze_and_decide()
    pipeline_result dict for dashboard compatibility.
    """

    ORCHESTRATOR_MODEL = "claude-sonnet-4-6"

    def __init__(
        self,
        data_manager,
        api_key: str = "",
    ):
        """
        Args:
            data_manager: JARVIS DataManager instance for price bars.
            api_key:      JARVIS engine API key (for localhost:8010 endpoints).
        """
        self._data_manager = data_manager
        self._api_key = api_key or os.getenv("JARVIS_API_KEY", "")

        # Phase 2 Components
        self._classifier = RegimeClassifierV2()
        self._router = StrategyRouter()
        self._shadow_tracker = ShadowModeTracker(
            data_manager._db if hasattr(data_manager, "_db") else None
        )

        # Super-Engine Orchestration (Phase 6)
        # Note: news_analyst is wired in from the orchestrator map if needed
        self._sentiment_bridge = SentimentBridge(news_analyst=None)

        # Build the in-process MCP server
        self._mcp_server = create_market_mcp_server(
            data_manager=data_manager,
            api_key=self._api_key,
        )

        # Define all 10 specialist subagents
        self._agent_definitions = self._build_agent_definitions()

    def _build_agent_definitions(self) -> dict[str, sdk.AgentDefinition]:
        """Build the 10 AgentDefinition objects for the pipeline stages."""
        from llm.model_router import route_task

        # Check if local inference mode is active
        use_local = os.getenv("OLLAMA_ENABLED", "False").lower() == "true"

        return {
            # Stage 1 — Parallel analysts
            "technical-analyst": sdk.AgentDefinition(
                description="Technical analysis agent: price bars, STC signals, regime detection",
                prompt=_TECHNICAL_ANALYST_PROMPT,
                model=route_task("technical_analyst", use_local=use_local),
                mcpServers=["market"],
                effort="medium",
            ),
            "news-analyst": sdk.AgentDefinition(
                description="News analyst: headline sentiment and event risk assessment",
                prompt=_NEWS_ANALYST_PROMPT,
                model=route_task("news_analyst", use_local=use_local),
                mcpServers=["market"],
                effort="medium",
            ),
            "social-analyst": sdk.AgentDefinition(
                description="Social sentiment analyst: Reddit trending and retail sentiment",
                prompt=_SOCIAL_ANALYST_PROMPT,
                model=route_task("social_analyst", use_local=use_local),
                mcpServers=["market"],
                effort="low",
            ),
            "fundamental-analyst": sdk.AgentDefinition(
                description="Macroeconomic analyst: VIX, yields, Fed Funds, unemployment",
                prompt=_FUNDAMENTAL_ANALYST_PROMPT,
                model=route_task("fundamental_analyst", use_local=use_local),
                mcpServers=["market"],
                effort="medium",
            ),
            # Stage 2 — Debate
            "bull-researcher": sdk.AgentDefinition(
                description="Bull researcher: strongest bullish case for the trade",
                prompt=_BULL_RESEARCHER_PROMPT,
                model=route_task("bull_researcher", use_local=use_local),
                effort="medium",
            ),
            "bear-researcher": sdk.AgentDefinition(
                description="Bear researcher: strongest bearish case against the trade",
                prompt=_BEAR_RESEARCHER_PROMPT,
                model=route_task("bear_researcher", use_local=use_local),
                effort="medium",
            ),
            "debate-orchestrator": sdk.AgentDefinition(
                description="Debate orchestrator: scores bull vs. bear, returns verdict and conviction",
                prompt=_DEBATE_ORCHESTRATOR_PROMPT,
                model=route_task("debate_orchestrator", use_local=use_local),
                effort="medium",
            ),
            # Stage 3-5 — Decision chain
            "trader": sdk.AgentDefinition(
                description="Trader: synthesises debate into BUY/SELL/HOLD with order parameters",
                prompt=_TRADER_PROMPT,
                model=route_task("trader", use_local=use_local),
                mcpServers=["market"],
                effort="high",
            ),
            "risk-manager": sdk.AgentDefinition(
                description="Risk manager: validates trade against portfolio risk limits",
                prompt=_RISK_MANAGER_PROMPT,
                model=route_task("risk_manager", use_local=use_local),
                mcpServers=["market"],
                effort="high",
            ),
            "fund-manager": sdk.AgentDefinition(
                description="Fund manager: final portfolio-level approval and sizing",
                prompt=_FUND_MANAGER_PROMPT,
                model=route_task("fund_manager", use_local=use_local),
                mcpServers=["market"],
                effort="high",
            ),
        }

    async def analyze_and_decide(
        self,
        symbol: str,
        interval: str = "1h",
        is_futures: bool = True,
    ) -> dict:
        """
        Run the full 5-stage SDK pipeline for the given symbol.

        Args:
            symbol:     Futures symbol (e.g. "MCL", "MNQ").
            interval:   Bar timeframe (e.g. "1h", "4h", "1d").
            is_futures: Currently always True — SDK pipeline targets futures.

        Returns:
            pipeline_result dict with the same shape as TradingPipeline output.
        """
        started_at = datetime.now()
        logger.info("[SDKPipeline] Starting %s %s", symbol, interval)

        # 1. Regime Detection (Phase 2)
        bars = await self._data_manager.get_bars(
            symbol, lookback_days=10, timeframe=interval, is_futures=is_futures
        )
        df_regime = self._classifier.classify(bars)
        current_regime = MarketRegime(df_regime["regime_v2"].iloc[-1])
        logger.info("[SDKPipeline] Detected Regime: %s", current_regime)

        orchestrator_prompt = (
            f"Run the JARVIS 5-stage trading pipeline for symbol={symbol} interval={interval}. "
            f"Follow the system prompt protocol exactly. "
            f"The current market REGIME is {current_regime}. Factor this into your analysis. "
            f"Output ONLY the final JSON object — no prose, no markdown code blocks."
        )

        options = sdk.ClaudeAgentOptions(
            model=self.ORCHESTRATOR_MODEL,
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            agents=self._agent_definitions,
            mcp_servers={"market": self._mcp_server},
            permission_mode="bypassPermissions",
            max_turns=60,
            effort="high",
        )

        result_text: str | None = None
        errors: list[str] = []

        try:
            async for message in sdk.query(prompt=orchestrator_prompt, options=options):
                if isinstance(message, sdk.ResultMessage):
                    result_text = message.result
                    break  # We only need the final result
        except Exception as exc:
            logger.error("[SDKPipeline] query() failed for %s: %s", symbol, exc)
            errors.append(str(exc))

        # Parse the JSON result from the orchestrator
        pipeline_result = self._parse_result(
            result_text=result_text,
            symbol=symbol,
            interval=interval,
            is_futures=is_futures,
            started_at=started_at,
            errors=errors,
        )

        # 2. Extract active positions for the router
        active_symbols = []
        if hasattr(self._data_manager, "_db"):
            active_symbols = [p["symbol"] for p in self._data_manager._db.get_open_trades()]

        # 3. Multi-Strategy Routing (Phase 2)
        pipeline_result = self._router.route_decision(
            symbol=symbol,
            regime=current_regime,
            raw_decision=pipeline_result,
            active_positions=active_symbols,
        )

        # 4. Shadow Logging (Phase 2)
        if pipeline_result.get("is_shadow") and pipeline_result.get("final_action") in [
            "buy",
            "sell",
        ]:
            self._shadow_tracker.log_shadow_entry(
                symbol=symbol,
                side=pipeline_result["final_action"],
                quantity=pipeline_result["final_quantity"],
                price=pipeline_result["trade_decision"].get("limit_price")
                or bars["close"].iloc[-1],
                strategy_name="SDK_Shadow",
                reasoning=pipeline_result.get("reasoning", ""),
            )

        logger.info(
            "[SDKPipeline] %s complete — action=%s quantity=%d regime=%s (%.1fs)",
            symbol,
            pipeline_result.get("final_action", "unknown"),
            pipeline_result.get("final_quantity", 0),
            current_regime,
            (datetime.now() - started_at).total_seconds(),
        )
        return pipeline_result

    def _parse_result(
        self,
        result_text: str | None,
        symbol: str,
        interval: str,
        is_futures: bool,
        started_at: datetime,
        errors: list[str],
    ) -> dict:
        """
        Parse the orchestrator's text output into a pipeline_result dict.
        Falls back to a HOLD result on any parse failure.
        """
        base = {
            "symbol": symbol,
            "timeframe": interval,
            "is_futures": is_futures,
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now().isoformat(),
            "sdk_pipeline": True,
            "errors": errors,
        }

        if not result_text:
            logger.warning("[SDKPipeline] No result text from orchestrator for %s", symbol)
            return {
                **base,
                **self._hold_result(reason="SDK orchestrator returned no result"),
            }

        # Tolerant extraction (fences, surrounding prose, trailing commas) via
        # utils.llm_json — supersedes the prior fence-strip + manual brace fallback.
        try:
            parsed = parse_llm_json(result_text)
        except LLMJsonError as exc:
            logger.warning("[SDKPipeline] JSON parse failed for %s: %s", symbol, exc)
            errors.append(f"JSON parse error: {exc}")
            return {
                **base,
                **self._hold_result(reason=f"Could not parse orchestrator output: {exc}"),
            }

        # Merge parsed result into base (parsed keys take precedence)
        result = {**base, **parsed}

        # Ensure required keys are present
        result.setdefault("final_action", "hold")
        result.setdefault("final_quantity", 0)
        result.setdefault("requires_human", False)
        result.setdefault("analyst_reports", {})
        result.setdefault("debate_result", {})
        result.setdefault("trade_decision", {})
        result.setdefault("risk_decision", {})
        result.setdefault("fund_decision", None)
        result.setdefault("errors", errors)

        # Normalise final_action to lowercase
        result["final_action"] = str(result["final_action"]).lower()
        if result["final_action"] not in ("buy", "sell", "hold", "pending_human_approval"):
            result["final_action"] = "hold"

        return result

    @staticmethod
    def _hold_result(reason: str) -> dict:
        return {
            "final_action": "hold",
            "final_quantity": 0,
            "requires_human": False,
            "kill_switch_active": False,
            "analyst_reports": {},
            "debate_result": {},
            "trade_decision": {"action": "hold", "reasoning": reason},
            "risk_decision": {"approved": False, "veto_reason": reason},
            "fund_decision": None,
            "paper_trade_logged": False,
        }
