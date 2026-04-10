"""
JARVIS TRADER — Trader Agent
==============================
The final decision maker before the risk/fund review pipeline.
Receives all upstream analyst reports and the bull/bear debate result,
then produces a concrete, order-ready TradeDecision.

Model: Claude Opus 4.6 — most capable model, used here because this is the
critical decision point where all analysis converges into an actionable order.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from utils.position_sizing import (
    PositionSizeResult,
    calculate_position_size,
    calculate_half_kelly_size,
    compute_rolling_edge,
)

try:
    from backtest.position_sizer import PositionSizer as _PositionSizer

    _POSITION_SIZER_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _POSITION_SIZER_AVAILABLE = False

logger = logging.getLogger(__name__)

__all__ = ["TraderAgent", "TradeDecision"]


@dataclass
class TradeDecision:
    """
    Fully specified trade decision produced by the Trader agent.
    Consumed by RiskManagerAgent and FundManagerAgent before execution.
    """

    symbol: str
    action: str  # "buy" | "sell" | "hold"
    quantity: int  # Number of contracts/shares (0 if hold)
    order_type: str  # "market" | "limit" | "stop_limit"
    time_in_force: str  # "day" | "gtc" | "ioc"

    # Price parameters (None when not applicable)
    limit_price: Optional[float]
    stop_price: Optional[float]

    # ATR-based trade geometry (None if hold or ATR unavailable)
    entry_price: Optional[float]   # Intended entry price
    target_1: Optional[float]      # T1 exit level (1st scale-out ~1/3 position)
    target_2: Optional[float]      # T2 exit level (stretch target)
    atr_used: Optional[float]      # ATR value used for stop/target calculation
    rr_ratio: Optional[float]      # R:R = (target_1 - entry) / abs(entry - stop)

    # Signal metadata
    signal_score: float  # -1.0 (strong sell) to +1.0 (strong buy)
    confidence: float  # 0.0 to 1.0

    # Qualitative output
    reasoning: str  # Full explanation of the decision
    risk_notes: str  # What could go wrong

    # Audit trail
    timestamp: datetime = field(default_factory=datetime.now)

    # Position sizing method used ('half_kelly', 'fixed_fractional', etc.)
    sizing_method: str = "fixed_fractional"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "entry_price": self.entry_price,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "atr_used": self.atr_used,
            "rr_ratio": self.rr_ratio,
            "time_in_force": self.time_in_force,
            "signal_score": self.signal_score,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "risk_notes": self.risk_notes,
            "timestamp": self.timestamp.isoformat(),
            "sizing_method": self.sizing_method,
        }


class TraderAgent:
    """
    Synthesizes the full multi-agent analysis stack (technical, news, social,
    fundamental + bull/bear debate) into a single, order-ready TradeDecision.

    The Trader is decisive. It does not waffle. When the evidence is mixed it
    defaults to HOLD, but when signals align it issues a specific order with
    exact price parameters.

    If the SafetyLayer kill switch is active, the Trader returns HOLD immediately
    without consulting the LLM — no reasoning needed when trading is halted.
    """

    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 1200

    SYSTEM_PROMPT_LIVE = (
        "You are the Trader for JARVIS TRADER, an autonomous trading system. "
        "You receive analysis from multiple specialized agents (technical, news, social, fundamental) "
        "and a bull/bear debate, and you make the final trade recommendation. "
        "You must be decisive. Your job is to synthesize the bull/bear debate, technical signals, "
        "news, and sentiment into a clear BUY/SELL/HOLD decision with specific order parameters. "
        "When signals are mixed, size down or hold — never force a trade. "
        "When the action is buy or sell, you MUST calculate ATR-based stop and target prices "
        "using the multipliers provided in the prompt. "
        "Respond with valid JSON only. Do not add any explanation outside the JSON."
    )

    SYSTEM_PROMPT_PAPER = (
        "You are the Trader for JARVIS TRADER in PAPER TRADING mode. "
        "This is a strategy validation phase — every executed trade is a data point. "
        "Your job is to act decisively: if the debate verdict is non-INCONCLUSIVE (BULL_WINS or "
        "BEAR_WINS), align your action with the verdict. BULL_WINS → buy. BEAR_WINS → sell. "
        "Use the pre-calculated ATR stop and target levels from the prompt. "
        "Only return HOLD if: (1) debate verdict is INCONCLUSIVE, OR (2) ATR data is missing so "
        "you cannot calculate a valid stop/target, OR (3) R:R < 1.0 based on the pre-calculated "
        "levels. Do NOT return HOLD due to mixed analyst signals or geopolitical uncertainty — "
        "uncertainty is what we are testing. The max order value limit in the prompt is for "
        "live trading; paper trades have no capital at risk, so do not let it block execution. "
        "Respond with valid JSON only. Do not add any explanation outside the JSON."
    )

    # Default to live; _build_prompt selects paper dynamically
    SYSTEM_PROMPT = SYSTEM_PROMPT_LIVE

    # Per-symbol stop/target ATR multipliers — mirrors INSTRUMENT_PARAMS in backtest/signals.py
    # Format: (stop_atr, t1_atr, t2_atr)
    _SYMBOL_ATR_PARAMS: dict = {
        "MNQ": (0.70, 1.00, 1.80),
        "MCL": (0.50, 1.00, 2.618),
        "MES": (1.00, 2.50, 4.00),   # Composite path params (COMP_STOP_ATR / COMP_T1_ATR / COMP_T2_ATR)
        "MGC": (0.70, 2.00, 3.236),
    }
    _DEFAULT_ATR_PARAMS = (0.70, 1.50, 2.50)  # Generic fallback

    # Dollar value per point per instrument
    _POINT_VALUES: dict = {
        "MES": 5.0,
        "MNQ": 2.0,
        "MCL": 100.0,
        "MGC": 10.0,
    }

    def __init__(self, llm_client, db_manager=None):
        """
        Args:
            llm_client: Object with .api_key attribute (Anthropic key).
            db_manager: Optional DatabaseManager instance. When provided,
                        Half-Kelly sizing is attempted using recent closed
                        paper trades (falls back to fixed-fractional when
                        fewer than 10 trades exist or on any error).
        """
        self._llm = llm_client
        self._db = db_manager

    async def decide(
        self,
        symbol: str,
        debate_result: dict,
        analyst_reports: dict,
        safety_status: dict,
    ) -> TradeDecision:
        """
        Produce a TradeDecision for the given symbol.

        Args:
            symbol:           Ticker / futures symbol (e.g. "MES", "AAPL")
            debate_result:    Output from DebateOrchestrator.run_debate() as dict
            analyst_reports:  Dict keyed by agent name → report dict
                              Expected keys: "technical", "news", "social", "fundamental"
            safety_status:    Output from SafetyLayer.get_status()

        Returns:
            TradeDecision dataclass (action="hold" quantity=0 if kill switch active)
        """
        # Hard gate: kill switch overrides everything — no LLM call needed
        if safety_status.get("kill_switch_active", False):
            reason = safety_status.get("kill_switch_reason", "unknown")
            logger.warning(f"[Trader] Kill switch active ({reason}) — returning HOLD for {symbol}")
            return self._hold_decision(
                symbol=symbol,
                reasoning=f"Kill switch is active: {reason}. All trading halted.",
                risk_notes="System safety halt. No trades until kill switch is manually cleared.",
            )

        # ── Fixed-fractional position sizing ──────────────────────────────
        # account_value: use current_equity from SafetyLayer (broker-sourced);
        #   fall back to 10,000 if not yet synced from broker.
        account_value: float = safety_status.get("current_equity") or 10_000.0

        # ATR is stored in analyst_reports["technical"]["indicators"]["atr"]
        # by TechnicalAnalystAgent._compute_indicators()
        technical_report = analyst_reports.get("technical", {})
        indicators = technical_report.get("indicators", {})
        atr: Optional[float] = indicators.get("atr") if isinstance(indicators, dict) else None

        from config import settings  # local import to avoid circular deps at module level

        max_contracts: int = settings.MAX_CONTRACTS_PER_INSTRUMENT

        position_size: PositionSizeResult = calculate_position_size(
            symbol=symbol,
            account_value=account_value,
            atr=atr,
            risk_pct=0.01,
            atr_stop_multiplier=0.70,
            max_contracts=max_contracts,
        )

        logger.info(
            f"[Trader] Position sizing for {symbol}: "
            f"account=${account_value:,.2f} atr={atr} => {position_size.contracts} contract(s) | "
            f"{position_size.reasoning}"
        )

        # ── PositionSizer: signal-strength scaling ─────────────────────────
        # Apply backtest.PositionSizer to optionally scale contracts based on
        # debate conviction score. Falls back silently to the fixed-fractional
        # result if PositionSizer is unavailable or raises.
        if _POSITION_SIZER_AVAILABLE and atr and atr > 0:
            try:
                from utils.position_sizing import INSTRUMENT_MULTIPLIERS, _DEFAULT_MULTIPLIER

                point_value = INSTRUMENT_MULTIPLIERS.get(symbol, _DEFAULT_MULTIPLIER)
                sizer = _PositionSizer(
                    capital=account_value,
                    risk_pct=0.01,
                    max_contracts=max_contracts,
                )
                atr_sized_contracts = sizer.compute_initial_size(
                    atr=atr,
                    stop_mult=0.70,
                    multiplier=point_value,
                )
                # Use NET conviction (|bear - bull| / 10) as signal strength.
                # Raw bull_score alone is wrong for short trades and inflates size
                # on tie signals (both = 6 → conviction=0.6 → 3× base).
                bull_s = float(debate_result.get("bull_score", 5.0))
                bear_s = float(debate_result.get("bear_score", 5.0))
                conviction = abs(bull_s - bear_s) / 10.0  # 0=no edge, 1=max conviction
                scaled_contracts = sizer.signal_strength_scaling(atr_sized_contracts, conviction)
                # Override only if the scaled value differs from fixed-fractional
                if scaled_contracts != position_size.contracts:
                    logger.info(
                        "[Trader] PositionSizer scaled contracts: "
                        "%d → %d (conviction=%.2f, atr=%.4f)",
                        position_size.contracts,
                        scaled_contracts,
                        conviction,
                        atr,
                    )
                    # Mutate the contracts field on the existing result dataclass
                    position_size.contracts = scaled_contracts
            except Exception as _ps_err:
                logger.warning(
                    "[Trader] PositionSizer scaling failed (non-fatal), "
                    "using fixed-fractional result: %s",
                    _ps_err,
                )

        # ── Half-Kelly sizing (optional enhancement) ───────────────────────
        # Attempts to replace fixed-fractional with Half-Kelly if we have
        # enough closed paper trade history (≥ 10 trades).  Never blocks a
        # trade — any failure silently falls back to the fixed-fractional result.
        sizing_method = 'fixed_fractional'
        sizing_info: dict = {}

        if self._db is not None:
            try:
                recent_trades_raw = (
                    self._db.get_closed_trades(symbol=symbol, limit=20)
                    if hasattr(self._db, 'get_closed_trades') else []
                )
                # Normalise: each item needs a 'pnl' key
                recent_trades = [
                    {'pnl': t.get('pnl', t.get('realized_pnl', 0))}
                    for t in (recent_trades_raw or [])
                ]
                edge = compute_rolling_edge(recent_trades)

                if edge.get('sufficient_data'):
                    # Dollar value of one tick per instrument
                    tick_value_map = {'MES': 12.50, 'MNQ': 5.00, 'MCL': 10.00, 'MGC': 10.00}
                    tick_value = tick_value_map.get(symbol, 12.50)

                    # ATR in ticks (atr in points / tick_size in points)
                    tick_size_map = {'MES': 0.25, 'MNQ': 0.25, 'MCL': 0.01, 'MGC': 0.10}
                    tick_size = tick_size_map.get(symbol, 0.25)
                    atr_ticks = atr / tick_size if atr and atr > 0 else 60.0

                    sizing_info = calculate_half_kelly_size(
                        capital=account_value,
                        win_rate=edge['win_rate'],
                        avg_win_loss_ratio=edge['avg_win_loss_ratio'],
                        tick_value=tick_value,
                        atr_ticks=atr_ticks,
                        max_contracts=max_contracts,
                    )
                    sizing_method = sizing_info.get('method', 'half_kelly')

                    # Override contracts if Half-Kelly produced a valid result
                    hk_contracts = sizing_info.get('contracts')
                    if hk_contracts and sizing_method == 'half_kelly':
                        logger.info(
                            "[Trader] Half-Kelly sizing for %s: "
                            "kelly=%.4f half_kelly=%.4f risk_pct=%.2f%% => %d contract(s) "
                            "(was %d fixed-fractional)",
                            symbol,
                            sizing_info.get('kelly_fraction', 0),
                            sizing_info.get('half_kelly', 0),
                            sizing_info.get('risk_pct', 0) * 100,
                            hk_contracts,
                            position_size.contracts,
                        )
                        position_size.contracts = hk_contracts
                    else:
                        logger.info(
                            "[Trader] Half-Kelly for %s returned method=%s "
                            "(edge not sufficient for override); using fixed-fractional.",
                            symbol,
                            sizing_method,
                        )
                else:
                    logger.debug(
                        "[Trader] Half-Kelly skipped for %s: only %d closed trades "
                        "(need ≥ 10).",
                        symbol,
                        edge.get('n_trades', 0),
                    )
            except Exception as _hk_err:
                # Half-Kelly is optional — never block a trade on sizing errors
                sizing_method = 'fixed_fractional_fallback'
                sizing_info = {}
                logger.warning(
                    "[Trader] Half-Kelly sizing failed for %s (non-fatal): %s",
                    symbol,
                    _hk_err,
                )

        # Build the analysis prompt from all upstream reports
        is_paper = not getattr(settings, "LIVE_TRADING_ENABLED", False)
        system_prompt = self.SYSTEM_PROMPT_PAPER if is_paper else self.SYSTEM_PROMPT_LIVE
        prompt = self._build_prompt(
            symbol, debate_result, analyst_reports, safety_status, position_size
        )

        try:
            api_key = getattr(self._llm, "api_key", None) or os.getenv("ANTHROPIC_API_KEY", "")
            _t0 = time.time()

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self.MODEL,
                        "max_tokens": self.MAX_TOKENS,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                payload = resp.json()

            _latency_ms = int((time.time() - _t0) * 1000)

            # Track cost via JarvisLLMClient if available
            usage = payload.get("usage", {})
            if hasattr(self._llm, "track_raw_call"):
                await self._llm.track_raw_call(
                    model=self.MODEL,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    latency_ms=_latency_ms,
                    agent_name="trader",
                )

            response_text = payload["content"][0]["text"].strip()

            # Strip markdown code fences if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            result = json.loads(response_text)
            decision = self._parse_decision(symbol, result, position_size, sizing_method)
            logger.info(
                "[Trader] %s decision: action=%s confidence=%.2f signal_score=%.2f",
                symbol, decision.action, decision.confidence, decision.signal_score,
            )
            return decision

        except Exception as e:
            logger.error(f"[Trader] LLM decision failed for {symbol}: {e}")
            return self._hold_decision(
                symbol=symbol,
                reasoning=f"Trader LLM call failed: {e}. Defaulting to HOLD.",
                risk_notes="LLM failure — no trade decision made. Investigate before retrying.",
            )

    # ── Prompt Construction ────────────────────────────────────────────────

    def _build_prompt(
        self,
        symbol: str,
        debate_result: dict,
        analyst_reports: dict,
        safety_status: dict,
        position_size: PositionSizeResult,
    ) -> str:
        from config import settings  # local import to avoid circular deps

        technical = analyst_reports.get("technical", {})
        news = analyst_reports.get("news", {})
        social = analyst_reports.get("social", {})
        fundamental = analyst_reports.get("fundamental", {})

        # Safety context
        daily_pnl = safety_status.get("daily_pnl", 0.0)
        drawdown = safety_status.get("drawdown_pct", 0.0)
        live_enabled = safety_status.get("live_trading_enabled", False)
        current_equity = safety_status.get("current_equity", 0.0)

        # ATR and per-symbol multipliers
        indicators = technical.get("indicators", {})
        atr_val: Optional[float] = indicators.get("atr") if isinstance(indicators, dict) else None
        current_price: Optional[float] = technical.get("current_price")

        stop_mult, t1_mult, t2_mult = self._SYMBOL_ATR_PARAMS.get(
            symbol.upper(), self._DEFAULT_ATR_PARAMS
        )
        point_value = self._POINT_VALUES.get(symbol.upper(), 1.0)

        # Pre-calculate concrete price levels when ATR and price are available
        if atr_val and atr_val > 0 and current_price and current_price > 0:
            stop_dist = round(stop_mult * atr_val, 4)
            t1_dist = round(t1_mult * atr_val, 4)
            t2_dist = round(t2_mult * atr_val, 4)
            long_stop = round(current_price - stop_dist, 4)
            long_t1 = round(current_price + t1_dist, 4)
            long_t2 = round(current_price + t2_dist, 4)
            short_stop = round(current_price + stop_dist, 4)
            short_t1 = round(current_price - t1_dist, 4)
            short_t2 = round(current_price - t2_dist, 4)
            rr_long = round(t1_dist / stop_dist, 2) if stop_dist > 0 else 0.0
            rr_short = rr_long  # symmetric

            dollar_risk = round(stop_dist * point_value * position_size.contracts, 2)
            dollar_t1 = round(t1_dist * point_value * position_size.contracts, 2)

            atr_section = f"""
=== ATR-BASED TRADE GEOMETRY (pre-calculated, use these values) ===
Symbol: {symbol} | Point value: ${point_value}/pt | Contracts: {position_size.contracts}
Current price: {current_price}
ATR (14-bar Wilder): {atr_val:.4f} pts

--- LONG scenario ---
  Entry:    {current_price}
  Stop:     {long_stop}  ({stop_mult}× ATR below entry)
  Target 1: {long_t1}  ({t1_mult}× ATR above entry)  → R:R = {rr_long:.2f}
  Target 2: {long_t2}  ({t2_mult}× ATR above entry)
  Dollar risk (stop): ${dollar_risk:,.2f} | Dollar at T1: ${dollar_t1:,.2f}

--- SHORT scenario ---
  Entry:    {current_price}
  Stop:     {short_stop}  ({stop_mult}× ATR above entry)
  Target 1: {short_t1}  ({t1_mult}× ATR below entry)  → R:R = {rr_short:.2f}
  Target 2: {short_t2}  ({t2_mult}× ATR below entry)
  Dollar risk (stop): ${dollar_risk:,.2f} | Dollar at T1: ${dollar_t1:,.2f}

INSTRUCTION: If action=buy, use long_stop as stop_price, long_t1 as target_1, long_t2 as target_2.
             If action=sell, use short_stop as stop_price, short_t1 as target_1, short_t2 as target_2.
             Only trade if R:R >= 1.0. Return null for all price fields if action=hold."""
        else:
            atr_section = f"""
=== ATR-BASED TRADE GEOMETRY ===
ATR not available for {symbol} — cannot pre-calculate stop/target levels.
Stop multiplier: {stop_mult}× ATR | T1 multiplier: {t1_mult}× ATR | T2 multiplier: {t2_mult}× ATR
If ATR becomes available, calculate: stop = entry ± ({stop_mult} × ATR), T1 = entry ± ({t1_mult} × ATR).
Return null for entry_price, stop_price, target_1, target_2, atr_used, rr_ratio when ATR is unknown."""

        return f"""Make a trade decision for {symbol}.

=== BULL/BEAR DEBATE RESULT ===
Verdict: {debate_result.get("verdict", "N/A")}
Bull score: {debate_result.get("bull_score", "N/A")}
Bear score: {debate_result.get("bear_score", "N/A")}
Debate summary: {debate_result.get("summary", "N/A")}
Key bull arguments: {debate_result.get("bull_arguments", [])}
Key bear arguments: {debate_result.get("bear_arguments", [])}

=== TECHNICAL ANALYSIS ===
Signal: {technical.get("signal", "N/A")} | Confidence: {technical.get("confidence", "N/A")}
Trend: {technical.get("trend", "N/A")} | Regime: {technical.get("regime", "N/A")}
Current price: {technical.get("current_price", "N/A")}
Support levels: {technical.get("support_levels", [])}
Resistance levels: {technical.get("resistance_levels", [])}
Summary: {technical.get("summary", "N/A")}

=== NEWS ANALYSIS ===
Signal: {news.get("signal", "N/A")} | Confidence: {news.get("confidence", "N/A")}
Event type: {news.get("event_type", "none")}
Bullish catalysts: {news.get("catalysts_bull", [])}
Bearish catalysts: {news.get("catalysts_bear", [])}
Summary: {news.get("summary", "N/A")}

=== SOCIAL SENTIMENT ===
Signal: {social.get("signal", "N/A")} | Confidence: {social.get("confidence", "N/A")}
Summary: {social.get("summary", "N/A")}

=== FUNDAMENTAL ANALYSIS ===
Signal: {fundamental.get("signal", "N/A")} | Confidence: {fundamental.get("confidence", "N/A")}
Summary: {fundamental.get("summary", "N/A")}

=== PORTFOLIO / RISK CONTEXT ===
Live trading enabled: {live_enabled}
Current equity: ${current_equity:,.2f}
Daily P&L: ${daily_pnl:,.2f}
Current drawdown: {drawdown:.1%}
Max single order value: ${settings.MAX_SINGLE_ORDER_VALUE:,.0f}
Max contracts per instrument: {position_size.contracts}

=== FIXED-FRACTIONAL POSITION SIZING (pre-calculated) ===
Sized contracts: {position_size.contracts}
Risk budget (1% of account): ${position_size.risk_per_trade:,.2f}
ATR stop distance: {position_size.stop_distance:.4f} pts
Dollar risk per contract: ${position_size.dollar_risk_per_contract:,.2f}
Sizing detail: {position_size.reasoning}
{atr_section}

IMPORTANT: Use quantity={position_size.contracts} for buy/sell orders.
Only set quantity=0 if action=hold. Do NOT increase quantity above {position_size.contracts}.

Respond with JSON in exactly this format:
{{
  "action": "<buy|sell|hold>",
  "quantity": <int: 0 if hold, otherwise use the pre-calculated sized contracts above>,
  "order_type": "<market|limit|stop_limit>",
  "limit_price": <float or null>,
  "stop_price": <float or null: ATR-based stop from the geometry section above>,
  "entry_price": <float or null: current price for market orders, null for hold>,
  "target_1": <float or null: T1 from geometry section above>,
  "target_2": <float or null: T2 from geometry section above>,
  "atr_used": <float or null: the ATR value used for calculations>,
  "rr_ratio": <float or null: (T1 - entry) / abs(entry - stop), null for hold>,
  "time_in_force": "<day|gtc|ioc>",
  "signal_score": <float -1.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "reasoning": "<thorough explanation of why this action was chosen, including R:R assessment>",
  "risk_notes": "<what could go wrong, key risks to monitor>"
}}"""

    # ── Result Parsing ─────────────────────────────────────────────────────

    def _parse_decision(
        self,
        symbol: str,
        result: dict,
        position_size: Optional[PositionSizeResult] = None,
        sizing_method: str = "fixed_fractional",
    ) -> TradeDecision:
        action = result.get("action", "hold").lower()
        if action not in ("buy", "sell", "hold"):
            action = "hold"

        quantity = int(result.get("quantity", 0))
        if action == "hold":
            quantity = 0
        elif position_size is not None:
            # Enforce the fixed-fractional sizing: if the LLM suggested more
            # contracts than the formula allows, cap it.  If it suggested fewer
            # (e.g. 1 when sizing says 2) we respect the LLM's conservatism.
            quantity = min(quantity, position_size.contracts)
            # Ensure at least 1 for an active signal
            if quantity < 1:
                quantity = position_size.contracts

        order_type = result.get("order_type", "market").lower()
        if order_type not in ("market", "limit", "stop_limit"):
            order_type = "market"

        time_in_force = result.get("time_in_force", "day").lower()
        if time_in_force not in ("day", "gtc", "ioc"):
            time_in_force = "day"

        raw_limit = result.get("limit_price")
        limit_price = float(raw_limit) if raw_limit is not None else None

        raw_stop = result.get("stop_price")
        stop_price = float(raw_stop) if raw_stop is not None else None

        # ATR geometry fields
        raw_entry = result.get("entry_price")
        entry_price = float(raw_entry) if raw_entry is not None else None

        raw_t1 = result.get("target_1")
        target_1 = float(raw_t1) if raw_t1 is not None else None

        raw_t2 = result.get("target_2")
        target_2 = float(raw_t2) if raw_t2 is not None else None

        raw_atr = result.get("atr_used")
        atr_used = float(raw_atr) if raw_atr is not None else None

        raw_rr = result.get("rr_ratio")
        rr_ratio = float(raw_rr) if raw_rr is not None else None

        # Validate stop is on the correct side of entry — LLMs occasionally return
        # the wrong-direction stop (e.g. short_stop for a buy).  Correct server-side.
        if action in ("buy", "sell") and stop_price is not None and entry_price is not None:
            stop_correct = (action == "buy" and stop_price < entry_price) or (
                action == "sell" and stop_price > entry_price
            )
            if not stop_correct:
                if atr_used is not None and atr_used > 0:
                    stop_mult, _, _ = self._SYMBOL_ATR_PARAMS.get(
                        symbol.upper(), self._DEFAULT_ATR_PARAMS
                    )
                    stop_dist = round(stop_mult * atr_used, 4)
                    corrected = (
                        round(entry_price - stop_dist, 4)
                        if action == "buy"
                        else round(entry_price + stop_dist, 4)
                    )
                    logger.warning(
                        "[TraderAgent] corrected inverted stop for %s %s: %.4f → %.4f",
                        action,
                        symbol,
                        stop_price,
                        corrected,
                    )
                    stop_price = corrected
                else:
                    logger.warning(
                        "[TraderAgent] stop %.4f is on wrong side of entry %.4f for %s %s"
                        " — nulled (ATR unavailable for correction)",
                        stop_price,
                        entry_price,
                        action,
                        symbol,
                    )
                    stop_price = None

        # Recompute R:R server-side for auditability when all price fields are present
        if action in ("buy", "sell") and entry_price and stop_price and target_1:
            risk = abs(entry_price - stop_price)
            reward = abs(target_1 - entry_price)
            if risk > 0:
                rr_ratio = round(reward / risk, 2)

        # Append sizing detail to reasoning for auditability
        reasoning = result.get("reasoning", "")
        if position_size is not None and action != "hold":
            rr_str = f" | R:R={rr_ratio:.2f}" if rr_ratio else ""
            reasoning = f"{reasoning}\n\n[Position Sizing] {position_size.reasoning}{rr_str}"

        return TradeDecision(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            entry_price=entry_price,
            target_1=target_1,
            target_2=target_2,
            atr_used=atr_used,
            rr_ratio=rr_ratio,
            time_in_force=time_in_force,
            signal_score=float(result.get("signal_score", 0.0)),
            confidence=float(result.get("confidence", 0.5)),
            reasoning=reasoning,
            risk_notes=result.get("risk_notes", ""),
            timestamp=datetime.now(),
            sizing_method=sizing_method,
        )

    def _hold_decision(self, symbol: str, reasoning: str, risk_notes: str) -> TradeDecision:
        return TradeDecision(
            symbol=symbol,
            action="hold",
            quantity=0,
            order_type="market",
            limit_price=None,
            stop_price=None,
            entry_price=None,
            target_1=None,
            target_2=None,
            atr_used=None,
            rr_ratio=None,
            time_in_force="day",
            signal_score=0.0,
            confidence=0.0,
            reasoning=reasoning,
            risk_notes=risk_notes,
            timestamp=datetime.now(),
        )
