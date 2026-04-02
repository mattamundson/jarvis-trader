"""
JARVIS TRADER — Fund Manager Agent
=====================================
The final portfolio-level approval authority in the pipeline.

The Fund Manager thinks at the portfolio level, not the individual trade level.
A trade can be technically sound and pass the Risk Manager's review but still
be wrong for the portfolio right now — wrong concentration, wrong timing
relative to existing risk, or simply too much capital deployed at once.

Model: Claude Opus 4.6 — portfolio-level judgment requires the most capable
reasoning to weigh cross-instrument interactions and holistic portfolio health.

Human approval gate:
  If REQUIRE_HUMAN_APPROVAL is True in config, OR the trade's estimated value
  exceeds $2,000, requires_human_approval is set True. The FundDecision is
  logged and surfaced to Matt but NOT forwarded to execution automatically.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from config import settings

logger = logging.getLogger(__name__)

__all__ = ["FundManagerAgent", "FundDecision"]

# Trades above this dollar threshold always require human confirmation
HUMAN_APPROVAL_VALUE_THRESHOLD = 2_000.0


@dataclass
class FundDecision:
    """Final approval decision from the Fund Manager."""

    approved: bool
    final_quantity: int  # May be reduced from risk_manager's approved quantity
    priority: str  # "immediate" | "wait_for_pullback" | "skip"
    portfolio_impact: str  # Brief description of effect on overall portfolio
    reasoning: str  # Full Fund Manager reasoning

    # True when the trade needs Matt's sign-off before execution
    requires_human_approval: bool = False

    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "final_quantity": self.final_quantity,
            "priority": self.priority,
            "portfolio_impact": self.portfolio_impact,
            "reasoning": self.reasoning,
            "requires_human_approval": self.requires_human_approval,
            "timestamp": self.timestamp.isoformat(),
        }


class FundManagerAgent:
    """
    Portfolio-level final approval.

    Receives the Trader's original decision, the Risk Manager's review,
    the current portfolio state, and all open positions.

    Considers:
      - Portfolio concentration (too much in one sector or instrument?)
      - Available capital and current margin utilization
      - Overall portfolio health (is now a good time to add risk?)
      - Whether the trade fits the current strategy and market regime

    If the trade is approved, the Fund Manager may still reduce the quantity
    or change priority from "immediate" to "wait_for_pullback".

    If requires_human_approval is True, the decision is logged and surfaced
    to Matt but the pipeline does NOT forward it to execution.
    """

    MODEL = "claude-opus-4-6"
    MAX_TOKENS = 800

    SYSTEM_PROMPT = (
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

    def __init__(self, llm_client):
        """
        Args:
            llm_client: Object with .api_key attribute (Anthropic key).
        """
        self._llm = llm_client

    async def approve(
        self,
        trade_decision: dict,
        risk_decision: dict,
        portfolio: dict,
        open_positions: list,
    ) -> FundDecision:
        """
        Give final portfolio-level approval (or rejection) for a trade.

        Args:
            trade_decision:  Output of TradeDecision.to_dict()
            risk_decision:   Output of RiskDecision.to_dict()
            portfolio:       Current portfolio state dict.
                             Expected keys: "total_value" (float),
                             "available_cash" (float), "margin_used_pct" (float),
                             "daily_pnl" (float), "open_position_count" (int)
            open_positions:  List of position dicts with at least:
                             symbol, quantity, sector, unrealized_pnl, market_value

        Returns:
            FundDecision — final portfolio-level ruling
        """
        # If the Risk Manager already vetoed, the Fund Manager should not override
        if not risk_decision.get("approved", False):
            veto_reason = risk_decision.get("veto_reason", "Risk Manager vetoed")
            logger.info(f"[FundManager] Passing through Risk Manager veto: {veto_reason}")
            return FundDecision(
                approved=False,
                final_quantity=0,
                priority="skip",
                portfolio_impact="Trade was already rejected by the Risk Manager.",
                reasoning=f"Risk Manager veto passed through: {veto_reason}",
                requires_human_approval=False,
                timestamp=datetime.now(),
            )

        action = trade_decision.get("action", "hold")
        # HOLD decisions pass trivially
        if action == "hold":
            return FundDecision(
                approved=True,
                final_quantity=0,
                priority="skip",
                portfolio_impact="No position change. Portfolio unchanged.",
                reasoning="Hold decision — no Fund Manager review required.",
                requires_human_approval=False,
                timestamp=datetime.now(),
            )

        # Determine if human approval is required
        requires_human = self._requires_human_approval(trade_decision, risk_decision)

        # Call LLM for portfolio-level judgment
        fund_decision = await self._llm_approve(
            trade_decision, risk_decision, portfolio, open_positions
        )
        fund_decision.requires_human_approval = requires_human

        if requires_human:
            logger.info(
                f"[FundManager] Trade {trade_decision.get('symbol')} requires human approval — "
                "logged but NOT sent to execution."
            )

        return fund_decision

    # ── Human Approval Gate ────────────────────────────────────────────────

    def _requires_human_approval(self, trade: dict, risk: dict) -> bool:
        """
        Returns True if human approval is required before execution.
        Conditions (either is sufficient):
          - REQUIRE_HUMAN_APPROVAL config setting is True
          - Estimated trade value exceeds $2,000
        """
        if settings.REQUIRE_HUMAN_APPROVAL:
            return True

        quantity = abs(int(trade.get("quantity", 0)))
        limit_price = trade.get("limit_price")
        # Use modified quantity from risk manager if available
        risk_qty = risk.get("modified_quantity")
        if risk_qty is not None:
            quantity = abs(int(risk_qty))

        if limit_price is not None and float(limit_price) > 0:
            estimated_value = quantity * float(limit_price)
            if estimated_value > HUMAN_APPROVAL_VALUE_THRESHOLD:
                return True

        return False

    # ── LLM Portfolio Review ───────────────────────────────────────────────

    async def _llm_approve(
        self,
        trade: dict,
        risk: dict,
        portfolio: dict,
        open_positions: list,
    ) -> FundDecision:
        prompt = self._build_prompt(trade, risk, portfolio, open_positions)

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
                    agent_name="fund_manager",
                )

            response_text = payload["content"][0]["text"].strip()

            # Strip markdown code fences if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            result = json.loads(response_text)
            return self._parse_fund_decision(result, trade, risk)

        except Exception as e:
            logger.error(f"[FundManager] LLM approval failed: {e}")
            # On failure, approve conservatively with reduced quantity (1 contract max)
            original_qty = int(trade.get("quantity", 1))
            safe_qty = min(original_qty, 1)
            return FundDecision(
                approved=True,
                final_quantity=safe_qty,
                priority="immediate",
                portfolio_impact=f"LLM failure — conservative approval at qty={safe_qty}.",
                reasoning=f"Fund Manager LLM call failed ({e}). Approved conservatively at minimum size.",
                requires_human_approval=True,  # Force human review on LLM failure
                timestamp=datetime.now(),
            )

    def _build_prompt(
        self,
        trade: dict,
        risk: dict,
        portfolio: dict,
        open_positions: list,
    ) -> str:
        total_value = portfolio.get("total_value", 0.0)
        available_cash = portfolio.get("available_cash", 0.0)
        margin_used_pct = portfolio.get("margin_used_pct", 0.0)
        daily_pnl = portfolio.get("daily_pnl", 0.0)
        open_position_count = portfolio.get("open_position_count", len(open_positions))

        # Summarize open positions — sector concentration is the key concern
        sector_map: dict[str, float] = {}
        positions_text = ""
        for pos in open_positions[:15]:
            sector = pos.get("sector", "unknown")
            mkt_val = float(pos.get("market_value", 0))
            sector_map[sector] = sector_map.get(sector, 0.0) + mkt_val
            positions_text += (
                f"  {pos.get('symbol', '?')}: qty={pos.get('quantity', 0)}, "
                f"sector={sector}, market_value=${mkt_val:,.2f}, "
                f"unrealized_pnl=${pos.get('unrealized_pnl', 0):,.2f}\n"
            )
        if not positions_text:
            positions_text = "  (no open positions)\n"

        # Sector concentration summary
        sector_summary = ""
        if sector_map and total_value > 0:
            for sec, val in sorted(sector_map.items(), key=lambda x: -x[1]):
                pct = val / total_value * 100
                sector_summary += f"  {sec}: ${val:,.2f} ({pct:.1f}%)\n"
        else:
            sector_summary = "  (no concentration data)\n"

        # Use risk-manager-adjusted quantity if available
        effective_qty = risk.get("modified_quantity") or trade.get("quantity", 0)
        effective_limit = risk.get("modified_limit_price") or trade.get("limit_price")

        return f"""Make the final portfolio-level decision on this trade.

=== PROPOSED TRADE (after Risk Manager review) ===
Symbol: {trade.get("symbol")}
Action: {trade.get("action")}
Effective quantity: {effective_qty}
Order type: {trade.get("order_type")}
Effective limit price: {effective_limit}
Signal score: {trade.get("signal_score")}
Confidence: {trade.get("confidence")}
Trader reasoning: {trade.get("reasoning", "N/A")}

=== RISK MANAGER VERDICT ===
Approved: {risk.get("approved")}
Risk score: {risk.get("risk_score", "N/A")}
Modified quantity: {risk.get("modified_quantity", "none")}
Risk reasoning: {risk.get("reasoning", "N/A")}

=== PORTFOLIO HEALTH ===
Total value: ${total_value:,.2f}
Available cash: ${available_cash:,.2f}
Margin used: {margin_used_pct:.1%}
Daily P&L: ${daily_pnl:,.2f}
Open positions: {open_position_count}

=== OPEN POSITIONS ===
{positions_text}
=== SECTOR CONCENTRATION ===
{sector_summary}
=== LIMITS ===
Max correlated exposure: {settings.MAX_CORRELATED_EXPOSURE_PCT:.1%} of portfolio
Max margin utilization: {settings.MAX_MARGIN_UTILIZATION:.1%}
Max single order value: ${settings.MAX_SINGLE_ORDER_VALUE:,.0f}

Consider:
1. Portfolio concentration — will this add dangerous sector or instrument concentration?
2. Capital availability — do we have enough cash/margin headroom?
3. Overall portfolio health — is now the right time to add risk?
4. Strategic fit — does this trade complement or conflict with existing positions?

Respond with JSON in exactly this format:
{{
  "approved": <true|false>,
  "final_quantity": <int: 0 if not approved, otherwise your approved quantity>,
  "priority": "<immediate|wait_for_pullback|skip>",
  "portfolio_impact": "<one sentence describing how this changes the overall portfolio>",
  "reasoning": "<2-4 sentence portfolio-level analysis>"
}}"""

    def _parse_fund_decision(
        self,
        result: dict,
        trade: dict,
        risk: dict,
    ) -> FundDecision:
        approved = bool(result.get("approved", False))

        priority = result.get("priority", "skip").lower()
        if priority not in ("immediate", "wait_for_pullback", "skip"):
            priority = "skip"

        final_quantity = int(result.get("final_quantity", 0))
        if not approved:
            final_quantity = 0

        return FundDecision(
            approved=approved,
            final_quantity=final_quantity,
            priority=priority,
            portfolio_impact=result.get("portfolio_impact", ""),
            reasoning=result.get("reasoning", ""),
            requires_human_approval=False,  # Caller sets this after
            timestamp=datetime.now(),
        )
