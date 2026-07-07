"""
JARVIS TRADER — Risk Manager Agent
=====================================
Validates the Trader's decision through two sequential layers:

Layer 1 — Hard rules (Python, non-LLM):
  Fast, deterministic checks against the safety parameters from config.
  If any hard rule fails the trade is vetoed immediately. No LLM call is made.

Layer 2 — Soft rules (LLM reasoning, Claude Opus 4.7):
  If hard rules pass, Claude reviews the trade for:
  - Correlation risk (sector concentration)
  - Timing risk (chasing a move?)
  - Size appropriateness
  The LLM can approve, modify quantity/price, or veto with reasoning.

This two-layer design keeps critical safety checks deterministic while still
giving the pipeline sophisticated contextual risk reasoning.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from config import settings
from utils.llm_json import parse_llm_json

try:
    from orchestrator.correlation_monitor import CorrelationMonitor

    _CORRELATION_MONITOR_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _CORRELATION_MONITOR_AVAILABLE = False

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

    # Hard-check audit trail — visible in pipeline detail endpoint
    hard_checks_passed: bool = True
    hard_checks_detail: list = field(default_factory=list)

    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "veto_reason": self.veto_reason,
            "modified_quantity": self.modified_quantity,
            "modified_limit_price": self.modified_limit_price,
            "risk_score": self.risk_score,
            "reasoning": self.reasoning,
            "hard_checks_passed": self.hard_checks_passed,
            "hard_checks_detail": self.hard_checks_detail,
            "timestamp": self.timestamp.isoformat(),
        }


class RiskManagerAgent:
    """
    Two-layer risk validation for every trade decision.

    Hard layer: Python checks against config thresholds — fast, non-LLM, non-negotiable.
    Soft layer: Claude Opus reviews the trade in portfolio context for qualitative risk.
    """

    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 1600

    # Hard-coded ceiling regardless of config — last line of defence
    # Set high enough to accommodate futures notional (MNQ ~$38K, MCL ~$10K)
    ABSOLUTE_MAX_ORDER_VALUE = 100_000.0

    SYSTEM_PROMPT_PAPER = (
        "You are the Risk Manager for JARVIS TRADER, an autonomous trading system. "
        "THIS IS PAPER TRADING MODE. The purpose is to validate signal quality across real "
        "market conditions — not to protect real capital. "
        "A trade has already passed all hard Python safety checks (kill switch, daily loss limit, "
        "drawdown limit, order value cap). Your soft review evaluates qualitative risk only: "
        "correlation with existing positions, timing (chasing a move?), and size appropriateness. "
        "APPROVAL BIAS: Approve trades that have good risk/reward (R:R > 1.5:1) and moderate "
        "confidence (>= 0.35). We need signal data — blocking valid signals defeats the purpose. "
        "Do NOT veto based on confidence being below 0.50 — the paper mode floor is 0.35. "
        "Reserve veto strictly for: no stop loss set, correlated positions exceeding limits, "
        "or clear timing errors (entering after a 3x ATR gap). "
        "Do not veto solely for 'could be better' reasoning in paper mode. "
        "Respond with valid JSON only. Do not add any explanation outside the JSON."
    )

    SYSTEM_PROMPT_LIVE = (
        "You are the Risk Manager for JARVIS TRADER, an autonomous trading system. "
        "A trade has already passed hard Python safety checks. Your job is to evaluate "
        "the qualitative risk: correlation with existing positions, whether the trade is "
        "chasing a move (bad timing), and whether the size is appropriate given recent volatility. "
        "You may approve the trade, approve with a reduced quantity or adjusted limit price, "
        "or veto if the risk is unacceptable. Be conservative — missed gains are recoverable, "
        "large losses are not. "
        "Respond with valid JSON only. Do not add any explanation outside the JSON."
    )

    # Resolved at runtime based on LIVE_TRADING_ENABLED
    SYSTEM_PROMPT = SYSTEM_PROMPT_PAPER  # default; overridden in __init__

    def __init__(self, llm_client, db_manager=None):
        """
        Args:
            llm_client: Object with .api_key attribute (Anthropic key).
            db_manager: Optional DatabaseManager.
        """
        self._llm = llm_client
        self._db = db_manager
        self.is_paper_mode = not settings.LIVE_TRADING_ENABLED
        self.SYSTEM_PROMPT = (
            self.SYSTEM_PROMPT_PAPER if self.is_paper_mode else self.SYSTEM_PROMPT_LIVE
        )

        # Phase 8.3: Cross-Asset Hedger
        from risk.hedger import PortfolioHedger

        self._hedger = PortfolioHedger(db_manager)

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

        veto, hard_checks_detail, modified_quantity = self._hard_rules_check(
            trade_decision, safety_status, portfolio
        )
        if veto is not None:
            logger.warning(f"[RiskManager] Hard veto for {trade_decision.get('symbol')}: {veto}")
            return RiskDecision(
                approved=False,
                veto_reason=veto,
                reasoning=f"Hard rule violation: {veto}",
                risk_score=1.0,
                hard_checks_passed=False,
                hard_checks_detail=hard_checks_detail,
                timestamp=datetime.now(),
            )

        action = trade_decision.get("action", "hold")
        # HOLD decisions pass trivially — no LLM needed
        if action == "hold":
            return RiskDecision(
                approved=True,
                reasoning="Hold action — no position change, no risk review required.",
                risk_score=0.0,
                hard_checks_passed=True,
                hard_checks_detail=hard_checks_detail,
                timestamp=datetime.now(),
            )

        # ── Layer 1b: VIX Hard Check (async, non-blocking) ────────────────

        vix_veto, vix_reason = await self._check_vix_risk_limit(trade_decision)
        if vix_veto:
            logger.warning(
                "[RiskManager] VIX hard veto for %s: %s",
                trade_decision.get("symbol"),
                vix_reason,
            )
            vix_detail = hard_checks_detail + [
                {"check": "vix_limit", "passed": False, "detail": vix_reason}
            ]
            return RiskDecision(
                approved=False,
                veto_reason=vix_reason,
                reasoning=f"VIX extreme fear — force HOLD: {vix_reason}",
                risk_score=1.0,
                hard_checks_passed=False,
                hard_checks_detail=vix_detail,
                timestamp=datetime.now(),
            )

        # VIX passed — record it in the audit trail
        hard_checks_detail.append(
            {"check": "vix_limit", "passed": True, "detail": "VIX within normal range"}
        )

        # ── Layer 2: Soft Rules (LLM reasoning) ───────────────────────────

        # Phase 8.3: Apply scaled quantity from correlation check
        if modified_quantity < trade_decision.get("quantity", 0):
            logger.info(
                "[RiskManager] Applying scaled quantity: %d -> %d",
                trade_decision.get("quantity"),
                modified_quantity,
            )
            trade_decision["quantity"] = modified_quantity
            trade_decision["modified_by_risk"] = True

        return await self._llm_review(
            trade_decision, safety_status, portfolio, hard_checks_detail
        )

    # ── VIX Risk Check ────────────────────────────────────────────────────

    async def _check_vix_risk_limit(self, trade_decision: dict) -> tuple[bool, str]:
        """
        Return (veto, reason).

        - VIX > 40: force HOLD (veto=True)
        - VIX 30–40: log warning, allow trade (veto=False)
        - VIX < 30 or check fails: no action (fail open)
        """
        try:
            _api_key = os.environ.get("API_KEY", "")
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(
                    "http://localhost:8010/macro/snapshot",
                    headers={"x-api-key": _api_key},
                )
            if resp.status_code == 200:
                vix = float(resp.json().get("vix", 0) or 0)
                if vix > 40:
                    return True, f"VIX {vix:.1f} > 40 — fear extreme, force HOLD"
                if vix > 30:
                    logger.warning(
                        "[RiskManager] VIX %.1f > 30 — elevated fear, trade allowed but size caution advised",
                        vix,
                    )
        except Exception as exc:
            logger.debug("[RiskManager] VIX check skipped (fail open): %s", exc)
        return False, ""

    # ── Hard Rules ────────────────────────────────────────────────────────

    def _hard_rules_check(
        self,
        trade: dict,
        safety: dict,
        portfolio: dict,
    ) -> tuple[Optional[str], list, int]:
        """
        Returns (veto_reason, checks_detail, modified_quantity).

        veto_reason: non-None string if any hard rule is violated, else None.
        checks_detail: list of dicts — {check, passed, detail} for each check run.
        Order matters — fail fast on the most critical checks first.
        """
        checks: list[dict] = []

        def _pass(check: str, detail: str = "") -> None:
            checks.append({"check": check, "passed": True, "detail": detail})

        def _fail(check: str, detail: str) -> tuple[str, list, int]:
            checks.append({"check": check, "passed": False, "detail": detail})
            return detail, checks, 0

        # 1. Kill switch
        if safety.get("kill_switch_active", False):
            reason = safety.get("kill_switch_reason", "unknown")
            return _fail("kill_switch", f"Kill switch is active: {reason}")
        _pass("kill_switch", "Inactive")

        action = trade.get("action", "hold")
        if action == "hold":
            return None, checks, 0  # Hold always passes hard rules

        # 2. Daily loss limit — compare daily_pnl against max_daily_loss config
        daily_pnl = safety.get("daily_pnl", 0.0)
        current_equity = safety.get("current_equity", 0.0)
        max_daily_loss = (
            -(current_equity * settings.MAX_DAILY_LOSS_PCT)
            if current_equity > 0
            else -(settings.MAX_DAILY_LOSS_PCT * 10_000)
        )
        if daily_pnl < max_daily_loss:
            return _fail(
                "daily_loss_limit",
                f"Daily P&L ${daily_pnl:,.2f} breaches max daily loss "
                f"${max_daily_loss:,.2f} ({settings.MAX_DAILY_LOSS_PCT:.1%} of equity)",
            )
        _pass("daily_loss_limit", f"Daily P&L ${daily_pnl:,.2f} within limit ${max_daily_loss:,.2f}")

        # 3. Drawdown limit — use 0.09 as the pre-config-limit warning threshold
        current_drawdown = safety.get("drawdown_pct", 0.0)
        if current_drawdown > 0.09:
            return _fail(
                "drawdown_limit",
                f"Current drawdown {current_drawdown:.1%} exceeds 9% threshold "
                f"(hard limit: {settings.MAX_DRAWDOWN_PCT:.1%})",
            )
        _pass("drawdown_limit", f"Drawdown {current_drawdown:.1%} within 9% threshold")

        # 4. Single order value limit
        quantity = abs(int(trade.get("quantity", 0)))
        limit_price = trade.get("limit_price")
        entry_price_raw = trade.get("entry_price")
        # Estimate order value: limit_price > entry_price > equity heuristic
        # For market orders, TraderAgent sets entry_price but limit_price=None.
        # The equity heuristic (5000/qty+1) always produces ~$5,001 and would
        # incorrectly block every single-contract market order.
        if limit_price is not None and limit_price > 0:
            estimated_price = float(limit_price)
        elif entry_price_raw is not None and entry_price_raw > 0:
            estimated_price = float(entry_price_raw)
        else:
            # No price available — skip the value check rather than blocking
            # with a fabricated estimate (old heuristic always produced ~$5,001)
            _pass("order_value_limit", "No price available — order value check skipped")
            estimated_price = None  # type: ignore[assignment]

        if estimated_price is not None:
            estimated_value = quantity * estimated_price
            max_order_value = min(settings.MAX_SINGLE_ORDER_VALUE, self.ABSOLUTE_MAX_ORDER_VALUE)
            if estimated_value > max_order_value:
                return _fail(
                    "order_value_limit",
                    f"Estimated order value ${estimated_value:,.2f} exceeds "
                    f"max single order value ${max_order_value:,.2f}",
                )
            _pass(
                "order_value_limit", f"Estimated value ${estimated_value:,.2f} within ${max_order_value:,.2f}"
            )

        # 4b. Dynamic Beta Correlation Scaling (Phase 8.3)
        scaled_qty = quantity
        try:
            corr_factor = self._hedger.get_correlation_scaling_factor(trade.get("symbol"), portfolio)
            if corr_factor < 1.0:
                scaled_qty = max(1, int(quantity * corr_factor))
                _pass(
                    "correlation_scaling",
                    f"Beta-correlation high; scaled quantity {quantity} -> {scaled_qty} (factor: {corr_factor:.1f})",
                )
            else:
                _pass("correlation_scaling", "No correlation scaling required")
        except Exception as _corr_err:
            logger.debug(f"[RiskManager] Correlation scaling failed: {_corr_err}")

        # 5. Correlation / directional-exposure check
        if _CORRELATION_MONITOR_AVAILABLE:
            try:
                total_capital = portfolio.get("total_value", 0.0) or 10_000.0
                positions = portfolio.get("positions", [])
                monitor = CorrelationMonitor(total_capital=total_capital)
                for pos in positions:
                    sym = pos.get("symbol", "unknown")
                    qty = pos.get("quantity", 0)
                    # Estimate exposure: use unrealized_pnl as a proxy for directional USD risk.
                    # Sign: positive qty = long = positive exposure.
                    exposure = pos.get("unrealized_pnl", 0.0)
                    if qty < 0:
                        exposure = -abs(exposure)
                    monitor.update(sym, exposure)
                if monitor.is_overexposed():
                    return _fail(
                        "correlation_exposure",
                        "Portfolio is overexposed — correlated directional risk too high "
                        f"({monitor.total_net_exposure_pct():.1%} of capital, "
                        f"limit {monitor.max_directional_pct:.0%})",
                    )
                _pass(
                    "correlation_exposure", f"Net exposure within limit ({monitor.max_directional_pct:.0%})"
                )
            except Exception as _cm_err:
                logger.warning("[RiskManager] CorrelationMonitor check failed (non-fatal): %s", _cm_err)
                _pass("correlation_exposure", f"Check skipped (non-fatal): {_cm_err}")
        else:
            _pass("correlation_exposure", "CorrelationMonitor not available — skipped")

        return None, checks, scaled_qty  # All hard rules passed

    # ── LLM Soft Review ───────────────────────────────────────────────────

    async def _llm_review(
        self,
        trade: dict,
        safety: dict,
        portfolio: dict,
        hard_checks_detail: Optional[list] = None,
    ) -> RiskDecision:
        prompt = self._build_prompt(trade, safety, portfolio)

        try:
            # Route through JarvisLLMClient so the Vertex->Gemini->OpenAI
            # fallback chain applies (B2, 2026-06-10: a raw httpx POST straight
            # at the Anthropic REST endpoint failed 400 on credit exhaustion).
            result_llm = await self._llm.call(
                model=self.MODEL,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.MAX_TOKENS,
                agent_name="risk_manager",
            )
            if not getattr(result_llm, "success", False):
                raise RuntimeError(
                    f"risk_manager LLM call failed: {getattr(result_llm, 'error', 'unknown')}"
                )

            response_text = (result_llm.content or "").strip()

            # Tolerant extraction (fences, prose, trailing commas) — see
            # utils.llm_json (2026-06-04 synthesis-failure wave).
            result = parse_llm_json(response_text)
            decision = self._parse_risk_decision(result)
            decision.hard_checks_passed = True
            decision.hard_checks_detail = hard_checks_detail or []
            return decision

        except Exception as e:
            logger.error(f"[RiskManager] LLM review failed: {e}")
            # On LLM failure, approve conservatively to avoid blocking all trades,
            # but flag with a high risk score so Fund Manager can step in
            return RiskDecision(
                approved=True,
                reasoning=f"LLM risk review failed ({e}). Hard rules passed. Fund Manager should apply extra scrutiny.",
                risk_score=0.8,
                hard_checks_passed=True,
                hard_checks_detail=hard_checks_detail or [],
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

        # Build correlation warning section
        correlation_warning = ""
        proposed_symbol = (trade.get("symbol") or "").upper()
        if proposed_symbol in ("MNQ", "MES"):
            open_symbols = {p.get("symbol", "").upper() for p in positions}
            if proposed_symbol == "MNQ" and "MES" in open_symbols:
                correlation_warning = "\nWARNING: MNQ position proposed but MES already open. High correlation (0.95).\n  → If both open, max contracts reduced to 1 each.\n"
            elif proposed_symbol == "MES" and "MNQ" in open_symbols:
                correlation_warning = "\nWARNING: MES position proposed but MNQ already open. High correlation (0.95).\n  → If both open, max contracts reduced to 1 each.\n"

        # Compute R:R ratio for the prompt if stop and limit are present
        stop_price = trade.get("stop_price")
        limit_price = trade.get("limit_price")
        rr_text = "N/A"
        if stop_price and limit_price and stop_price > 0 and limit_price > 0:
            risk_pts = abs(float(limit_price) - float(stop_price))
            # Use a 1:1 minimum target as proxy if no explicit target; show ratio from entry to stop
            if risk_pts > 0:
                rr_text = f"Risk: {risk_pts:.2f} pts from entry to stop"

        trading_mode = "PAPER TRADING (signal validation)" if self.is_paper_mode else "LIVE TRADING"
        paper_guidance = (
            "\nPAPER MODE GUIDANCE: Approve trades with R:R > 1.5:1 and confidence >= 0.35. "
            "The confidence floor in paper mode is 0.35 — do NOT block for confidence < 0.50. "
            "Veto only for: missing stop, correlated exposure breach, or extreme timing error.\n"
            if self.is_paper_mode
            else ""
        )

        return f"""Review this trade for risk:

=== TRADING MODE ===
{trading_mode}
{paper_guidance}
=== PROPOSED TRADE ===
Symbol: {trade.get("symbol")}
Action: {trade.get("action")}
Quantity: {trade.get("quantity")}
Order type: {trade.get("order_type")}
Limit price: {trade.get("limit_price")}
Stop price: {trade.get("stop_price")}
Risk/Reward: {rr_text}
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
{correlation_warning}

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
