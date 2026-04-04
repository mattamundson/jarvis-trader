"""
JARVIS TRADER — Risk Manager Agent
=====================================
Validates the Trader's decision through two sequential layers:

Layer 1 — Hard rules (Python, non-LLM):
  Fast, deterministic checks against the safety parameters from config.
  If any hard rule fails the trade is vetoed immediately. No LLM call is made.

Layer 2 — Soft rules (LLM reasoning, Claude Opus 4.6):
  If hard rules pass, Claude reviews the trade for:
  - Correlation risk (sector concentration)
  - Timing risk (chasing a move?)
  - Size appropriateness
  The LLM can approve, modify quantity/price, or veto with reasoning.

This two-layer design keeps critical safety checks deterministic while still
giving the pipeline sophisticated contextual risk reasoning.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

__all__ = ["RiskManagerAgent", "RiskDecision"]


@dataclass
class RiskDecision:
    """Result from the Risk Manager's review of a trade decision."""

    approved: bool
    reasoning: str

    # Populated when trade is rejected
    veto_reason: Optional[str] = None

    # Populated when the LLM recommends reducing size or adjusting price
    modified_quantity: Optional[int] = None
    modified_limit_price: Optional[float] = None

    # 0.0 = minimal risk, 1.0 = extreme risk
    risk_score: float = 0.0

    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "veto_reason": self.veto_reason,
            "modified_quantity": self.modified_quantity,
            "modified_limit_price": self.modified_limit_price,
            "risk_score": self.risk_score,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp.isoformat(),
        }


class RiskManagerAgent:
    """
    Two-layer risk validation for every trade decision.

    Hard layer: Python checks against config thresholds — fast, non-LLM, non-negotiable.
    Soft layer: Claude Opus reviews the trade in portfolio context for qualitative risk.
    """

    MODEL = "claude-opus-4-6"
    MAX_TOKENS = 1600

    # Hard-coded ceiling regardless of config — last line of defence
    ABSOLUTE_MAX_ORDER_VALUE = 5_000.0

    SYSTEM_PROMPT = (
        "You are the Risk Manager for JARVIS TRADER, an autonomous trading system. "
        "A trade has already passed hard Python safety checks. Your job is to evaluate "
        "the qualitative risk: correlation with existing positions, whether the trade is "
        "chasing a move (bad timing), and whether the size is appropriate given recent volatility. "
        "You may approve the trade, approve with a reduced quantity or adjusted limit price, "
        "or veto if the risk is unacceptable. Be conservative — missed gains are recoverable, "
        "large losses are not. "
        "Respond with valid JSON only. Do not add any explanation outside the JSON."
    )

    def __init__(self, llm_client):
        """
        Args:
            llm_client: Object with .api_key attribute (Anthropic key).
        """
        self._llm = llm_client

    async def review(
        self,
        trade_decision: dict,
        safety_status: dict,
        portfolio: dict,
    ) -> RiskDecision:
        """
        Review a TradeDecision dict from the Trader.

        Args:
            trade_decision: Output of TradeDecision.to_dict()
            safety_status:  Output of SafetyLayer.get_status()
            portfolio:      Dict describing current portfolio state.
                            Expected keys: "positions" (list), "total_value" (float),
                            "available_cash" (float), "margin_used_pct" (float)

        Returns:
            RiskDecision — approved or vetoed with reasoning
        """
        # ── Layer 1: Hard Rules (Python, no LLM) ──────────────────────────

        veto = self._hard_rules_check(trade_decision, safety_status, portfolio)
        if veto is not None:
            logger.warning(f"[RiskManager] Hard veto for {trade_decision.get('symbol')}: {veto}")
            return RiskDecision(
                approved=False,
                veto_reason=veto,
                reasoning=f"Hard rule violation: {veto}",
                risk_score=1.0,
                timestamp=datetime.now(),
            )

        action = trade_decision.get("action", "hold")
        # HOLD decisions pass trivially — no LLM needed
        if action == "hold":
            return RiskDecision(
                approved=True,
                reasoning="Hold action — no position change, no risk review required.",
                risk_score=0.0,
                timestamp=datetime.now(),
            )

        # ── Layer 2: Soft Rules (LLM reasoning) ───────────────────────────

        return await self._llm_review(trade_decision, safety_status, portfolio)

    # ── Hard Rules ────────────────────────────────────────────────────────

    def _hard_rules_check(
        self,
        trade: dict,
        safety: dict,
        portfolio: dict,
    ) -> Optional[str]:
        """
        Returns a veto reason string if any hard rule is violated, else None.
        Order matters — fail fast on the most critical checks first.
        """
        # 1. Kill switch
        if safety.get("kill_switch_active", False):
            reason = safety.get("kill_switch_reason", "unknown")
            return f"Kill switch is active: {reason}"

        action = trade.get("action", "hold")
        if action == "hold":
            return None  # Hold always passes hard rules

        # 2. Daily loss limit — compare daily_pnl against max_daily_loss config
        daily_pnl = safety.get("daily_pnl", 0.0)
        current_equity = safety.get("current_equity", 0.0)
        max_daily_loss = (
            -(current_equity * settings.MAX_DAILY_LOSS_PCT)
            if current_equity > 0
            else -(settings.MAX_DAILY_LOSS_PCT * 10_000)
        )
        if daily_pnl < max_daily_loss:
            return (
                f"Daily P&L ${daily_pnl:,.2f} breaches max daily loss "
                f"${max_daily_loss:,.2f} ({settings.MAX_DAILY_LOSS_PCT:.1%} of equity)"
            )

        # 3. Drawdown limit — use 0.09 as the pre-config-limit warning threshold
        current_drawdown = safety.get("drawdown_pct", 0.0)
        if current_drawdown > 0.09:
            return (
                f"Current drawdown {current_drawdown:.1%} exceeds 9% threshold "
                f"(hard limit: {settings.MAX_DRAWDOWN_PCT:.1%})"
            )

        # 4. Single order value limit
        quantity = abs(int(trade.get("quantity", 0)))
        limit_price = trade.get("limit_price")
        # Estimate order value: use limit_price if available, else fall back to
        # technical current_price if it was threaded through, else use equity heuristic
        if limit_price is not None and limit_price > 0:
            estimated_price = float(limit_price)
        else:
            # No price available — use a conservative upper bound check
            estimated_price = self.ABSOLUTE_MAX_ORDER_VALUE / max(quantity, 1) + 1

        estimated_value = quantity * estimated_price
        max_order_value = min(settings.MAX_SINGLE_ORDER_VALUE, self.ABSOLUTE_MAX_ORDER_VALUE)
        if estimated_value > max_order_value:
            return (
                f"Estimated order value ${estimated_value:,.2f} exceeds "
                f"max single order value ${max_order_value:,.2f}"
            )

        return None  # All hard rules passed

    # ── LLM Soft Review ───────────────────────────────────────────────────

    async def _llm_review(
        self,
        trade: dict,
        safety: dict,
        portfolio: dict,
    ) -> RiskDecision:
        prompt = self._build_prompt(trade, safety, portfolio)

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
                        "system": self.SYSTEM_PROMPT,
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
                    agent_name="risk_manager",
                )

            response_text = payload["content"][0]["text"].strip()

            # Strip markdown code fences if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            result = json.loads(response_text)
            return self._parse_risk_decision(result)

        except Exception as e:
            logger.error(f"[RiskManager] LLM review failed: {e}")
            # On LLM failure, approve conservatively to avoid blocking all trades,
            # but flag with a high risk score so Fund Manager can step in
            return RiskDecision(
                approved=True,
                reasoning=f"LLM risk review failed ({e}). Hard rules passed. Fund Manager should apply extra scrutiny.",
                risk_score=0.8,
                timestamp=datetime.now(),
            )

    def _build_prompt(self, trade: dict, safety: dict, portfolio: dict) -> str:
        positions = portfolio.get("positions", [])
        total_value = portfolio.get("total_value", 0.0)
        available_cash = portfolio.get("available_cash", 0.0)
        margin_used_pct = portfolio.get("margin_used_pct", 0.0)

        positions_text = ""
        if positions:
            for pos in positions[:10]:  # Cap at 10 to keep prompt size reasonable
                positions_text += (
                    f"  - {pos.get('symbol', '?')}: "
                    f"qty={pos.get('quantity', 0)}, "
                    f"sector={pos.get('sector', 'unknown')}, "
                    f"unrealized_pnl=${pos.get('unrealized_pnl', 0):,.2f}\n"
                )
        else:
            positions_text = "  (no open positions)\n"

        return f"""Review this trade for risk:

=== PROPOSED TRADE ===
Symbol: {trade.get("symbol")}
Action: {trade.get("action")}
Quantity: {trade.get("quantity")}
Order type: {trade.get("order_type")}
Limit price: {trade.get("limit_price")}
Stop price: {trade.get("stop_price")}
Signal score: {trade.get("signal_score")}
Confidence: {trade.get("confidence")}
Trader reasoning: {trade.get("reasoning", "N/A")}
Trader risk notes: {trade.get("risk_notes", "N/A")}

=== PORTFOLIO STATE ===
Total portfolio value: ${total_value:,.2f}
Available cash: ${available_cash:,.2f}
Margin used: {margin_used_pct:.1%}
Open positions:
{positions_text}

=== SAFETY STATUS ===
Daily P&L: ${safety.get("daily_pnl", 0):,.2f}
Current drawdown: {safety.get("drawdown_pct", 0):.1%}
Live trading enabled: {safety.get("live_trading_enabled", False)}

Evaluate these risk dimensions:
1. Correlation risk — are we already heavily exposed to this sector/instrument?
2. Timing risk — does this trade look like it is chasing a recent move?
3. Size risk — is the quantity appropriate given volatility and portfolio size?

Respond with JSON in exactly this format:
{{
  "approved": <true|false>,
  "veto_reason": <"string reason" or null if approved>,
  "modified_quantity": <int or null if no change>,
  "modified_limit_price": <float or null if no change>,
  "risk_score": <float 0.0 to 1.0>,
  "reasoning": "<2-4 sentence risk assessment covering all three dimensions>"
}}"""

    def _parse_risk_decision(self, result: dict) -> RiskDecision:
        approved = bool(result.get("approved", False))
        veto_reason = result.get("veto_reason") if not approved else None

        raw_qty = result.get("modified_quantity")
        modified_quantity = int(raw_qty) if raw_qty is not None else None

        raw_price = result.get("modified_limit_price")
        modified_limit_price = float(raw_price) if raw_price is not None else None

        return RiskDecision(
            approved=approved,
            veto_reason=veto_reason,
            modified_quantity=modified_quantity,
            modified_limit_price=modified_limit_price,
            risk_score=float(result.get("risk_score", 0.5)),
            reasoning=result.get("reasoning", ""),
            timestamp=datetime.now(),
        )
