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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from utils.position_sizing import PositionSizeResult, calculate_position_size

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

    # Signal metadata
    signal_score: float  # -1.0 (strong sell) to +1.0 (strong buy)
    confidence: float  # 0.0 to 1.0

    # Qualitative output
    reasoning: str  # Full explanation of the decision
    risk_notes: str  # What could go wrong

    # Audit trail
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "time_in_force": self.time_in_force,
            "signal_score": self.signal_score,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "risk_notes": self.risk_notes,
            "timestamp": self.timestamp.isoformat(),
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

    MODEL = "claude-opus-4-6"
    MAX_TOKENS = 1000

    SYSTEM_PROMPT = (
        "You are the Trader for JARVIS TRADER, an autonomous trading system. "
        "You receive analysis from multiple specialized agents (technical, news, social, fundamental) "
        "and a bull/bear debate, and you make the final trade recommendation. "
        "You must be decisive. Your job is to synthesize the bull/bear debate, technical signals, "
        "news, and sentiment into a clear BUY/SELL/HOLD decision with specific order parameters. "
        "When signals are mixed, size down or hold — never force a trade. "
        "Respond with valid JSON only. Do not add any explanation outside the JSON."
    )

    def __init__(self, llm_client):
        """
        Args:
            llm_client: Object with .api_key attribute (Anthropic key).
        """
        self._llm = llm_client

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

        from ..config import settings  # local import to avoid circular deps at module level

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

        # Build the analysis prompt from all upstream reports
        prompt = self._build_prompt(
            symbol, debate_result, analyst_reports, safety_status, position_size
        )

        try:
            api_key = getattr(self._llm, "api_key", None) or os.getenv("ANTHROPIC_API_KEY", "")

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
                        "system": self.SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                payload = resp.json()

            response_text = payload["content"][0]["text"].strip()

            # Strip markdown code fences if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            result = json.loads(response_text)
            return self._parse_decision(symbol, result, position_size)

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
        technical = analyst_reports.get("technical", {})
        news = analyst_reports.get("news", {})
        social = analyst_reports.get("social", {})
        fundamental = analyst_reports.get("fundamental", {})

        # Safety context
        daily_pnl = safety_status.get("daily_pnl", 0.0)
        drawdown = safety_status.get("drawdown_pct", 0.0)
        live_enabled = safety_status.get("live_trading_enabled", False)
        current_equity = safety_status.get("current_equity", 0.0)

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
Max single order value: $5,000
Max contracts per instrument: {position_size.contracts}

=== FIXED-FRACTIONAL POSITION SIZING (pre-calculated) ===
Sized contracts: {position_size.contracts}
Risk budget (1% of account): ${position_size.risk_per_trade:,.2f}
ATR stop distance: {position_size.stop_distance:.4f} pts
Dollar risk per contract: ${position_size.dollar_risk_per_contract:,.2f}
Sizing detail: {position_size.reasoning}

IMPORTANT: Use quantity={position_size.contracts} for buy/sell orders.
Only set quantity=0 if action=hold. Do NOT increase quantity above {position_size.contracts}.

Respond with JSON in exactly this format:
{{
  "action": "<buy|sell|hold>",
  "quantity": <int: 0 if hold, otherwise use the pre-calculated sized contracts above>,
  "order_type": "<market|limit|stop_limit>",
  "limit_price": <float or null>,
  "stop_price": <float or null>,
  "time_in_force": "<day|gtc|ioc>",
  "signal_score": <float -1.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "reasoning": "<thorough explanation of why this action was chosen>",
  "risk_notes": "<what could go wrong, key risks to monitor>"
}}"""

    # ── Result Parsing ─────────────────────────────────────────────────────

    def _parse_decision(
        self,
        symbol: str,
        result: dict,
        position_size: Optional[PositionSizeResult] = None,
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

        # Append sizing detail to reasoning for auditability
        reasoning = result.get("reasoning", "")
        if position_size is not None and action != "hold":
            reasoning = f"{reasoning}\n\n[Position Sizing] {position_size.reasoning}"

        return TradeDecision(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            signal_score=float(result.get("signal_score", 0.0)),
            confidence=float(result.get("confidence", 0.5)),
            reasoning=reasoning,
            risk_notes=result.get("risk_notes", ""),
            timestamp=datetime.now(),
        )

    def _hold_decision(self, symbol: str, reasoning: str, risk_notes: str) -> TradeDecision:
        return TradeDecision(
            symbol=symbol,
            action="hold",
            quantity=0,
            order_type="market",
            limit_price=None,
            stop_price=None,
            time_in_force="day",
            signal_score=0.0,
            confidence=0.0,
            reasoning=reasoning,
            risk_notes=risk_notes,
            timestamp=datetime.now(),
        )
