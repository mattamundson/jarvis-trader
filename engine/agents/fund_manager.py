"""
JARVIS TRADER — Fund Manager Agent
=====================================
The final portfolio-level approval authority in the pipeline.

The Fund Manager thinks at the portfolio level, not the individual trade level.
A trade can be technically sound and pass the Risk Manager's review but still
be wrong for the portfolio right now — wrong concentration, wrong timing
relative to existing risk, or simply too much capital deployed at once.

Model: claude-sonnet-4-6 — portfolio-level judgment.

Human approval gate:
  If REQUIRE_HUMAN_APPROVAL is True in config, OR the trade's estimated value
  exceeds $2,000, requires_human_approval is set True. The FundDecision is
  logged and surfaced to Matt but NOT forwarded to execution automatically.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from config import settings
<<<<<<< HEAD
=======
from llm.client import resolve_agent_model
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
from utils.llm_json import parse_llm_json

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

<<<<<<< HEAD
    MODEL = "claude-sonnet-4-6"
=======
    MODEL = "claude-sonnet-4-6"  # fallback; live model resolved via resolve_agent_model (T1)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    MAX_TOKENS = 1600

    SYSTEM_PROMPT_LIVE = (
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

    SYSTEM_PROMPT_PAPER = (
        "You are the Fund Manager for JARVIS TRADER in PAPER TRADING mode. "
        "This is a validation phase — the goal is to gather real trade data to assess "
        "strategy performance. Your job is to be appropriately permissive: approve any "
        "trade that passed the Risk Manager review, has positive R:R (reward:risk > 1.0), "
        "and a confidence score above 0.35. Do NOT apply live-trading-level conservatism. "
        "Reject only if there is a clear portfolio-level problem: margin would be exhausted, "
        "the same instrument already has an open position in the same direction, or the "
        "daily P&L halt is close to being triggered. "
        "Think of each approved trade as a data point — we need volume to validate the strategy. "
        "You may reduce quantity to 1 contract if capital is tight, but default to approving. "
        "Respond with valid JSON only. Do not add any explanation outside the JSON."
    )

    # Use the live prompt as the default; _build_prompt injects paper context dynamically
    SYSTEM_PROMPT = SYSTEM_PROMPT_LIVE

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

        Owner directive (2026-06-15): human approval is governed SOLELY by the
        REQUIRE_HUMAN_APPROVAL config flag. When it is False, no trade requires
        human sign-off regardless of size — trades auto-execute (paper unless
        LIVE_TRADING_ENABLED is also True). When True, every trade requires
        approval. The legacy $2,000 value threshold is intentionally no longer an
        independent gate, so that disabling approval applies to ALL trades.
        """
        return bool(settings.REQUIRE_HUMAN_APPROVAL)

    # ── LLM Portfolio Review ───────────────────────────────────────────────

    async def _llm_approve(
        self,
        trade: dict,
        risk: dict,
        portfolio: dict,
        open_positions: list,
    ) -> FundDecision:
        is_paper = not getattr(settings, "LIVE_TRADING_ENABLED", False)
        system_prompt = self.SYSTEM_PROMPT_PAPER if is_paper else self.SYSTEM_PROMPT_LIVE
        prompt = self._build_prompt(trade, risk, portfolio, open_positions, is_paper=is_paper)

        try:
            # Route through JarvisLLMClient so the Vertex->Gemini->OpenAI
            # fallback chain applies (B2, 2026-06-10: a raw httpx POST straight
            # at the Anthropic REST endpoint failed 400 on credit exhaustion).
            result_llm = await self._llm.call(
<<<<<<< HEAD
                model=self.MODEL,
=======
                model=resolve_agent_model(self._llm, self.MODEL),
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.MAX_TOKENS,
                agent_name="fund_manager",
            )
            if not getattr(result_llm, "success", False):
                raise RuntimeError(
                    f"fund_manager LLM call failed: {getattr(result_llm, 'error', 'unknown')}"
                )

            response_text = (result_llm.content or "").strip()

            # Tolerant extraction (fences, prose, trailing commas) — see
            # utils.llm_json (2026-06-04 synthesis-failure wave).
            result = parse_llm_json(response_text)
            return self._parse_fund_decision(result, trade, risk)

        except Exception as e:
            # FAIL CLOSED (PRB-11, mirrors GT-49): an LLM/parse failure during
            # Fund Manager review is an UNKNOWN portfolio-level verdict, not
            # evidence the trade is safe. Silently approving at qty=1 here
            # converted an approval failure into fail-open behavior — the same
            # defect class as the 2026-06-15 inert-kill-switch incident and
            # the GT-49 per-account kill-state fix (safety_layer.py). "Unknown
            # state" must never resolve to "safe to trade": reject/hold the
            # trade until a real Fund Manager verdict succeeds.
            logger.error(
                "[FundManager] LLM approval failed — failing CLOSED (rejected) "
                "rather than auto-approving: %s",
                e,
            )
            return FundDecision(
                approved=False,
                final_quantity=0,
                priority="skip",
                portfolio_impact=f"Fund Manager LLM call failed ({e}) — rejected, fail-closed on unknown portfolio-level verdict.",
                reasoning=f"Fund Manager LLM call failed ({e}). Failing CLOSED (rejected) rather than auto-approving.",
                requires_human_approval=True,  # Surface to Matt regardless of REQUIRE_HUMAN_APPROVAL
                timestamp=datetime.now(),
            )

    def _build_prompt(
        self,
        trade: dict,
        risk: dict,
        portfolio: dict,
        open_positions: list,
        is_paper: bool = False,
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

        paper_banner = (
            "\n*** PAPER TRADING MODE — Validation Phase ***\n"
            "Approve any trade with R:R > 1.0 and confidence > 0.35 that passed risk review.\n"
            "Goal: accumulate data. Reject only on genuine portfolio-level blockers.\n"
            if is_paper else ""
        )

        return f"""Make the final portfolio-level decision on this trade.{paper_banner}

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

CRITICAL: Your response MUST be valid JSON containing ALL fields listed below. Missing any field will cause the trade to be silently rejected.
- Set priority='immediate' when approving a trade to execute now. Use 'skip' ONLY to reject.
- If approved=true, set final_quantity to the number from the risk manager (or the quantity in the trade decision).

Respond with JSON in exactly this format:
{{
  "approved": true,
  "final_quantity": 1,
  "priority": "immediate",
  "portfolio_impact": "...",
  "reasoning": "..."
}}"""

    def _parse_fund_decision(
        self,
        result: dict,
        trade: dict,
        risk: dict,
    ) -> FundDecision:
        approved = bool(result.get("approved", False))

        priority_raw = result.get("priority")
        if priority_raw is None:
            # LLM omitted priority — infer from approval status
            priority = "immediate" if approved else "skip"
        else:
            priority = str(priority_raw).lower()
            if priority not in ("immediate", "wait_for_pullback", "skip"):
                priority = "immediate" if approved else "skip"
            elif approved and priority == "skip":
                # LLM returned contradictory approved=True + priority=skip;
                # approval wins — treat as immediate
                priority = "immediate"

        final_quantity = int(result.get("final_quantity", 0))
        if not approved:
            final_quantity = 0
        elif final_quantity == 0:
            # LLM approved but omitted final_quantity — use risk manager's quantity
            final_quantity = int(risk.get("modified_quantity") or trade.get("quantity", 1) or 1)

        return FundDecision(
            approved=approved,
            final_quantity=final_quantity,
            priority=priority,
            portfolio_impact=result.get("portfolio_impact", ""),
            reasoning=result.get("reasoning", ""),
            requires_human_approval=False,  # Caller sets this after
            timestamp=datetime.now(),
        )
