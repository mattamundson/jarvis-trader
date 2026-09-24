"""
JARVIS TRADER — Trader Agent
==============================
The final decision maker before the risk/fund review pipeline.
Receives all upstream analyst reports and the bull/bear debate result,
then produces a concrete, order-ready TradeDecision.

Model: Claude Opus 4.7 — most capable model, used here because this is the
critical decision point where all analysis converges into an actionable order.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from llm.client import resolve_agent_model
from utils.llm_json import parse_llm_json
from utils.position_sizing import (
    INSTRUMENT_MULTIPLIERS,
    PositionSizeResult,
    calculate_half_kelly_size,
    calculate_position_size,
    compute_rolling_edge,
)

try:
    from backtest.position_sizer import PositionSizer as _PositionSizer

    _POSITION_SIZER_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _POSITION_SIZER_AVAILABLE = False

logger = logging.getLogger(__name__)

__all__ = ["TraderAgent", "TradeDecision"]

# ---------------------------------------------------------------------------
# AdvisorClient lazy-load — optional, gracefully degraded on failure
# ---------------------------------------------------------------------------
_advisor_instance = None
_tool_inspection_manager = None


def _get_advisor():
    """
    Lazy-construct AdvisorClient. Returns None on import/init failure.
    Never raises — used to consult on low-confidence trades.
    """
    global _advisor_instance
    if _advisor_instance is None:
        try:
            from agents.advisor_client import AdvisorClient

            _advisor_instance = AdvisorClient()
        except Exception as _err:  # pragma: no cover — defensive
            logger.info("AdvisorClient unavailable in trader: %s", _err)
            _advisor_instance = False  # sentinel: tried and failed
    return _advisor_instance if _advisor_instance is not False else None


def _detect_corey_contradiction(action: str, analyst_reports: Optional[dict]) -> Optional[dict]:
    """Detect a high-conviction Corey session bias that contradicts the trader action.

    Returns {"bias": str, "conviction": float} when Corey's directional_bias is
    opposite to *action* and conviction > 0.7. Returns None otherwise (including
    agreement, neutral bias, low conviction, missing briefing).

    Threshold 0.7 (vs. 0.5 used by researcher evidence + debate tie-break): we're
    gating an expensive Opus consultation, so require stronger disagreement signal.
    """
    if action not in ("buy", "sell"):
        return None
    if not isinstance(analyst_reports, dict):
        return None
    briefing = analyst_reports.get("discord_briefing")
    if not isinstance(briefing, dict):
        return None
    corey = briefing.get("corey_bias") or {}
    bias = str(corey.get("directional_bias") or "").lower()
    try:
        conv = float(corey.get("conviction") or 0.0)
    except (TypeError, ValueError):
        return None
    if conv <= 0.7:
        return None
    if action == "buy" and bias == "bearish":
        return {"bias": bias, "conviction": conv}
    if action == "sell" and bias == "bullish":
        return {"bias": bias, "conviction": conv}
    return None


def _get_tool_inspection_manager():
    """Lazy-construct the tool inspection manager. Returns None on import/init failure."""
    global _tool_inspection_manager
    if _tool_inspection_manager is None:
        try:
            from config import settings as _settings
            from risk.tool_inspector import (
                KillSwitchInspector,
                LiquidityInspector,
                RiskInspector,
                ToolInspectionManager,
                VolatilityInspector,
            )

            max_contracts = getattr(_settings, "MAX_CONTRACTS_PER_INSTRUMENT", 2)
            _tool_inspection_manager = ToolInspectionManager(
                [
                    LiquidityInspector(min_recent_volume=1000.0),
                    VolatilityInspector(require_approval_vix=35.0, deny_vix=50.0),
                    RiskInspector(
                        min_size_mult=0.5,
                        max_size_mult=1.5,
                        max_contracts=max_contracts,
                    ),
                    KillSwitchInspector(),
                ]
            )
        except Exception as _err:  # pragma: no cover - defensive lazy import
            logger.info("ToolInspectionManager unavailable in trader: %s", _err)
            _tool_inspection_manager = False
    return _tool_inspection_manager if _tool_inspection_manager is not False else None


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
    entry_price: Optional[float]  # Intended entry price
    target_1: Optional[float]  # T1 exit level (1st scale-out ~1/3 position)
    target_2: Optional[float]  # T2 exit level (stretch target)
    atr_used: Optional[float]  # ATR value used for stop/target calculation

    # Phase 5.4: Options Spread Parameters
    is_spread: bool = False
    short_option_symbol: Optional[str] = None
    long_option_symbol: Optional[str] = None
    net_credit: Optional[float] = None
    rr_ratio: Optional[float] = None  # R:R = (target_1 - entry) / abs(entry - stop)

    # Signal metadata
    signal_score: float = 0.0  # -1.0 (strong sell) to +1.0 (strong buy)
    confidence: float = 0.0  # 0.0 to 1.0

    # Qualitative output
    reasoning: str = ""  # Full explanation of the decision
    risk_notes: str = ""  # What could go wrong

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

    MODEL = "claude-sonnet-4-6"  # fallback; live model resolved via resolve_agent_model (T1)
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
        "MES": (
            1.00,
            2.50,
            4.00,
        ),  # Composite path params (COMP_STOP_ATR / COMP_T1_ATR / COMP_T2_ATR)
        "MGC": (0.70, 2.00, 3.236),
    }
    _DEFAULT_ATR_PARAMS = (0.70, 1.50, 2.50)  # Generic fallback

    # Dollar value per point per instrument — sourced from the canonical
    # INSTRUMENT_MULTIPLIERS table in engine/utils/position_sizing.py
    _POINT_VALUES: dict = INSTRUMENT_MULTIPLIERS

    def __init__(
        self,
        llm_client,
        db_manager=None,
        memory_bridge=None,
        portfolio_allocator=None,
    ):
        """
        Args:
            llm_client: Object with .api_key attribute (Anthropic key).
            db_manager: Optional DatabaseManager instance. When provided,
                        Half-Kelly sizing is attempted using recent closed
                        paper trades (falls back to fixed-fractional when
                        fewer than 10 trades exist or on any error).
            memory_bridge: Optional MemoryBridge for persistent working memory.
            portfolio_allocator: Optional PortfolioAllocator for dynamic sizing.
        """
        self._llm = llm_client
        self._db = db_manager
        self._memory = memory_bridge
        self._allocator = portfolio_allocator

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

        # ── Regime Safety Gate (Phase 8.2) ──────────────────────────────
        # Analyst reports are passed via a wrapper in the real pipeline
        regime_override = analyst_reports.get("regime_override")
        if regime_override and regime_override.get("blocked"):
            reason = regime_override.get("reason", "Regime block active")
            logger.warning(f"[Trader] {symbol} — {reason}")
            return self._hold_decision(
                symbol=symbol,
                reasoning=reason,
                risk_notes="Systemic regime protection active (CRISIS/VOLATILE). No new entries allowed.",
            )

        # ── Working Memory Recall (Phase 3.5) ─────────────────────────────
        working_memory = ""
        if self._memory:
            working_memory = self._memory.recall(
                agent_name="trader",
                symbol=symbol,
                topic="general",
                limit=5
            )
            if working_memory:
                logger.info(f"[Trader] {symbol} — Recalled working memory")

        # ── Portfolio-Aware Sizing (Phase 8.1) ────────────────────────────
        # Fetch optimal risk percentage from allocator
        risk_pct = 0.01  # baseline 1%
        if self._allocator:
            # Extract strategy name from technical analyst report if possible
            tech = analyst_reports.get("technical", {})
            strategy = tech.get("indicators", {}).get("stark_signal", "unknown")
            risk_pct = self._allocator.get_risk_pct(strategy, symbol)
            logger.info(f"[Trader] {symbol} — Allocator risk_pct: {risk_pct:.2%}")

        # ── Options Setup Evaluation (Phase 5.4) ──────────────────────────
        options_setup = analyst_reports.get("options", {})
        if options_setup.get("signal", 0) != 0:
            logger.info(f"[Trader] {symbol} — Options setup detected: {options_setup.get('summary')}")
            # We can choose to prioritize options if regime is RANGE or MEANREV
            # For now, we'll let the LLM decide by including the setup in the prompt.

        # ── Fixed-fractional position sizing ──────────────────────────────
        # account_value: use current_equity from SafetyLayer (broker-sourced);
        #   fall back to 10,000 if not yet synced from broker.
        account_value: float = safety_status.get("current_equity") or 10_000.0

        # ATR is stored in analyst_reports["technical"]["indicators"]["atr"]
        # by TechnicalAnalystAgent._compute_indicators()
        technical_report = analyst_reports.get("technical", {})
        indicators = technical_report.get("indicators", {})
        atr: Optional[float] = indicators.get("atr") if isinstance(indicators, dict) else None

        if not atr or atr <= 0:
            logger.warning(
                "[Trader] %s: ATR is %s — cannot compute stop/target, defaulting to HOLD",
                symbol,
                atr,
            )

        from config import settings  # local import to avoid circular deps at module level

        max_contracts: int = settings.MAX_CONTRACTS_PER_INSTRUMENT

        position_size: PositionSizeResult = calculate_position_size(
            symbol=symbol,
            account_value=account_value,
            atr=atr,
            risk_pct=risk_pct,
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
                from utils.position_sizing import _DEFAULT_MULTIPLIER, INSTRUMENT_MULTIPLIERS

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
                # PositionSizer.signal_strength_scaling maps conviction [0,1] → scale (0.5 + conviction)
                # i.e. 0.5x at conviction=0, 1.0x at 0.5, 1.5x at 1.0 — then integer-clamped to
                # [1, max_contracts]. Effective range here is thus 0.5x–1.5x base, hard-capped at
                # max_contracts=2 for micro futures.
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
        sizing_method = "fixed_fractional"
        sizing_info: dict = {}

        if self._db is not None:
            try:
                recent_trades_raw = (
                    self._db.get_closed_trades(symbol=symbol, limit=20)
                    if hasattr(self._db, "get_closed_trades")
                    else []
                )
                # Normalise: each item needs a 'pnl' key
                recent_trades = [
                    {"pnl": t.get("pnl", t.get("realized_pnl", 0))}
                    for t in (recent_trades_raw or [])
                ]
                edge = compute_rolling_edge(recent_trades)

                if edge.get("sufficient_data"):
                    # Dollar value of one tick per instrument = $/point × tick_size
                    # MES: $5/pt × 0.25 = $1.25   MNQ: $2/pt × 0.25 = $0.50
                    # MCL: $100/pt × 0.01 = $1.00  MGC: $10/pt × 0.10 = $1.00
                    tick_value_map = {"MES": 1.25, "MNQ": 0.50, "MCL": 1.00, "MGC": 1.00}
                    tick_value = tick_value_map.get(symbol, 1.25)

                    # ATR in ticks (atr in points / tick_size in points)
                    tick_size_map = {"MES": 0.25, "MNQ": 0.25, "MCL": 0.01, "MGC": 0.10}
                    tick_size = tick_size_map.get(symbol, 0.25)
                    atr_ticks = atr / tick_size if atr and atr > 0 else 60.0

                    sizing_info = calculate_half_kelly_size(
                        capital=account_value,
                        win_rate=edge["win_rate"],
                        avg_win_loss_ratio=edge["avg_win_loss_ratio"],
                        tick_value=tick_value,
                        atr_ticks=atr_ticks,
                        max_contracts=max_contracts,
                    )
                    sizing_method = sizing_info.get("method", "half_kelly")

                    # Override contracts if Half-Kelly produced a valid result
                    hk_contracts = sizing_info.get("contracts")
                    if hk_contracts and sizing_method == "half_kelly":
                        logger.info(
                            "[Trader] Half-Kelly sizing for %s: "
                            "kelly=%.4f half_kelly=%.4f risk_pct=%.2f%% => %d contract(s) "
                            "(was %d fixed-fractional)",
                            symbol,
                            sizing_info.get("kelly_fraction", 0),
                            sizing_info.get("half_kelly", 0),
                            sizing_info.get("risk_pct", 0) * 100,
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
                        "[Trader] Half-Kelly skipped for %s: only %d closed trades " "(need ≥ 10).",
                        symbol,
                        edge.get("n_trades", 0),
                    )
            except Exception as _hk_err:
                # Half-Kelly is optional — never block a trade on sizing errors
                sizing_method = "fixed_fractional_fallback"
                sizing_info = {}
                logger.warning(
                    "[Trader] Half-Kelly sizing failed for %s (non-fatal): %s",
                    symbol,
                    _hk_err,
                )

        # ── A2: VIX regime position-size multiplier ───────────────────────
        # Extract VIX from fundamental report and apply regime-based scaling.
        # Falls back silently — never blocks a trade.
        try:
            from analytics.vix_overlay import classify_vix

            _fund_report = analyst_reports.get("fundamental", {})
            _fund_vix = _fund_report.get("key_metrics", {}).get("vix")
            if _fund_vix is not None and float(_fund_vix) > 0:
                _vix_val = float(_fund_vix)
                _vix_regime, _vix_size_pct, _vix_trading_allowed = classify_vix(_vix_val)
                if not _vix_trading_allowed:
                    # VIX EXTREME (≥ 40) — force HOLD immediately, no further sizing
                    logger.warning(
                        "[Trader] %s: VIX EXTREME (%.1f ≥ 40) — trading paused, returning HOLD",
                        symbol,
                        _vix_val,
                    )
                    return self._hold_decision(
                        symbol=symbol,
                        reasoning=f"VIX EXTREME regime (VIX={_vix_val:.1f} ≥ 40). Trading paused.",
                        risk_notes="Extreme fear regime — no directional exposure until VIX normalises.",
                    )
                _vix_adjusted = max(1, round(position_size.contracts * _vix_size_pct))
                logger.info(
                    "[Trader] VIX regime %s (%.1f): position sizing multiplier %.2fx "
                    "— contracts %d → %d",
                    _vix_regime,
                    _vix_val,
                    _vix_size_pct,
                    position_size.contracts,
                    _vix_adjusted,
                )
                position_size.contracts = _vix_adjusted
        except Exception as _vix_err:
            logger.debug("[Trader] VIX size overlay failed (non-fatal): %s", _vix_err)

        # ── Volatility-targeting position-size multiplier (DEFAULT OFF) ────
        # Final risk overlay: scale contracts toward a constant target vol so
        # quiet regimes size up and turbulent regimes size down. Gated behind
        # settings.VOL_TARGET_ENABLED (default False) => inert until enabled.
        # OOS-validated on MGC trend (backtest/vol_target_wfo.py: Sharpe +0.69,
        # MaxDD -59%). Realized vol comes from the existing rv_20_ann_pct
        # indicator. Falls back silently — never blocks or vetoes a trade.
        if settings.VOL_TARGET_ENABLED:
            try:
                from utils.position_sizing import apply_vol_target_scaling

                _rv = indicators.get("rv_20_ann_pct") if isinstance(indicators, dict) else None
                _vt_contracts, _vt_reason = apply_vol_target_scaling(
                    contracts=position_size.contracts,
                    symbol=symbol,
                    realized_vol_ann_pct=_rv,
                    target_vol_by_symbol=settings.VOL_TARGET_PER_SYMBOL,
                    max_leverage=settings.VOL_TARGET_MAX_LEVERAGE,
                    max_contracts=max_contracts,
                )
                if _vt_contracts != position_size.contracts:
                    logger.info(
                        "[Trader] Vol-target sizing for %s: contracts %d → %d (%s)",
                        symbol,
                        position_size.contracts,
                        _vt_contracts,
                        _vt_reason,
                    )
                    position_size.contracts = _vt_contracts
            except Exception as _vt_err:
                logger.debug("[Trader] Vol-target size overlay failed (non-fatal): %s", _vt_err)

        # ── Confluence-based position sizing override ─────────────────────
        # Count how many Stage 1 agents agree with the debate verdict direction.
        # Insufficient agreement (< 40%) forces a HOLD regardless of debate outcome.
        _debate_verdict = (
            debate_result.get("verdict", "INCONCLUSIVE")
            if isinstance(debate_result, dict)
            else getattr(debate_result, "verdict", "INCONCLUSIVE")
        )
        if _debate_verdict == "BULL_WINS":
            _confluence_direction = "LONG"
        elif _debate_verdict == "BEAR_WINS":
            _confluence_direction = "SHORT"
        else:
            _confluence_direction = None

        # Fix B (2026-04-10) — High-conviction bypass: when the debate produces
        # a decisively strong verdict (|debate_score| > 0.30, above the highest
        # regime threshold of 0.25), skip the Stage 1 confluence gate entirely.
        # The adversarial bull/bear debate design intentionally permits minority
        # theses to overrule the majority; a strong numerical verdict is the
        # debate earning that right. Any Round 1 conviction short-circuit
        # (|delta|≥0.35 in debate.py:283) automatically qualifies.
        _debate_score_raw = (
            debate_result.get("debate_score", 0.0)
            if isinstance(debate_result, dict)
            else getattr(debate_result, "debate_score", 0.0)
        )
        try:
            _debate_score = float(_debate_score_raw)
        except (TypeError, ValueError):
            _debate_score = 0.0

        _high_conviction_bypass = abs(_debate_score) > 0.30 and _confluence_direction is not None
        if _high_conviction_bypass:
            logger.info(
                "[Trader] %s: high-conviction bypass — |debate_score|=%.3f > 0.30, "
                "skipping confluence gate for %s verdict",
                symbol,
                abs(_debate_score),
                _debate_verdict,
            )

        _confluence_hold = False
        if _confluence_direction is not None and not _high_conviction_bypass:
            confluence_mult = self._compute_confluence_multiplier(
                analyst_reports, _confluence_direction
            )
            if confluence_mult == 0.0:
                logger.warning(
                    "[Trader] %s: insufficient confluence for %s verdict — overriding to HOLD",
                    symbol,
                    _debate_verdict,
                )
                _confluence_hold = True
            else:
                _base_contracts = position_size.contracts
                _new_contracts = max(1, round(_base_contracts * confluence_mult))
                _new_contracts = min(_new_contracts, max_contracts)
                if _new_contracts != _base_contracts:
                    logger.info(
                        "[Trader] %s: confluence_mult=%.2f → contracts %d → %d",
                        symbol,
                        confluence_mult,
                        _base_contracts,
                        _new_contracts,
                    )
                    position_size.contracts = _new_contracts

        if _confluence_hold:
            # Fix C (2026-04-10) — Advisor tiebreak on confluence-vetoed verdicts.
            # Before forcing HOLD on a decisive-but-contrarian debate verdict,
            # consult Claude Opus for a second opinion. The advisor sees the
            # full bull/bear cases plus the Stage 1 disagreement and decides
            # whether the debate's minority thesis is worth executing at
            # minimum size. This is the "razor-thin decision with expensive
            # consequences" case the Anthropic Advisor Strategy was designed for.
            _advisor_override = False
            _advisor_reasoning = ""
            try:
                _advisor = _get_advisor()
                if _advisor is not None and _advisor.is_available():

                    def _extract_thesis(report_obj, thesis_key):
                        if report_obj is None:
                            return ""
                        if isinstance(report_obj, dict):
                            return str(report_obj.get(thesis_key, "") or "")
                        return str(getattr(report_obj, thesis_key, "") or "")

                    _bull_report = (
                        debate_result.get("bull_report")
                        if isinstance(debate_result, dict)
                        else getattr(debate_result, "bull_report", None)
                    )
                    _bear_report = (
                        debate_result.get("bear_report")
                        if isinstance(debate_result, dict)
                        else getattr(debate_result, "bear_report", None)
                    )
                    _bull_case_text = _extract_thesis(_bull_report, "bull_thesis")
                    _bear_case_text = _extract_thesis(_bear_report, "bear_thesis")
                    _regime_str = (
                        debate_result.get("regime", "unknown")
                        if isinstance(debate_result, dict)
                        else getattr(debate_result, "regime", "unknown")
                    ) or "unknown"

                    _verdict_obj = await _advisor.consult_debate_tiebreak(
                        bull_case=_bull_case_text,
                        bear_case=_bear_case_text,
                        debate_score=_debate_score,
                        regime=_regime_str,
                        analyst_reports=analyst_reports,
                    )
                    if _verdict_obj.consulted and _verdict_obj.verdict in {"LONG", "SHORT"}:
                        _expected_side = "LONG" if _debate_verdict == "BULL_WINS" else "SHORT"
                        if _verdict_obj.verdict == _expected_side:
                            _advisor_override = True
                            _advisor_reasoning = _verdict_obj.reasoning or ""
                            # Risk-bounded probe: cap at 1 contract regardless of sizing
                            position_size.contracts = max(1, min(position_size.contracts, 1))
                            logger.info(
                                "[Trader] %s: advisor tiebreak OVERRIDES confluence hold "
                                "(verdict=%s, confidence=%.2f) — executing at probe size (1 contract)",
                                symbol,
                                _verdict_obj.verdict,
                                _verdict_obj.confidence,
                            )
                        else:
                            logger.info(
                                "[Trader] %s: advisor agrees with confluence hold "
                                "(advisor=%s, debate=%s) — honouring HOLD",
                                symbol,
                                _verdict_obj.verdict,
                                _debate_verdict,
                            )
            except Exception as _adv_err:
                logger.warning(
                    "[Trader] %s: confluence-advisor consult raised: %s",
                    symbol,
                    _adv_err,
                )

            if not _advisor_override:
                return self._hold_decision(
                    symbol=symbol,
                    reasoning=(
                        f"Confluence gate: debate verdict={_debate_verdict} but insufficient "
                        "Stage 1 agent agreement. Forcing HOLD to avoid low-confluence trade."
                        + (
                            f" Advisor consulted: {_advisor_reasoning[:120]}"
                            if _advisor_reasoning
                            else ""
                        )
                    ),
                    risk_notes="Less than 40% of analyst agents agreed with the debate direction.",
                )
            # Advisor overrode the hold — fall through to build the LLM trader
            # prompt at probe sizing. The downstream flow runs normally.

        # Build the analysis prompt from all upstream reports
        is_paper = not getattr(settings, "LIVE_TRADING_ENABLED", False)
        system_prompt = self.SYSTEM_PROMPT_PAPER if is_paper else self.SYSTEM_PROMPT_LIVE
        prompt = self._build_prompt(
            symbol, debate_result, analyst_reports, safety_status, position_size
        )

        try:
            # Route through JarvisLLMClient so the Vertex->Gemini->OpenAI
            # fallback chain applies to the decision stage. A raw httpx POST
            # straight at the Anthropic REST endpoint here meant every decision
            # failed 400 while Anthropic credits were exhausted, even though
            # client-routed analysts were falling back fine (2026-06-10).
            result = await self._llm.call(
                model=resolve_agent_model(self._llm, self.MODEL),
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.MAX_TOKENS,
                agent_name="trader",
            )
            if not getattr(result, "success", False):
                raise RuntimeError(
                    f"trader LLM call failed: {getattr(result, 'error', 'unknown')}"
                )

            response_text = (result.content or "").strip()

            # Tolerant extraction (fences, prose, trailing commas) — see
            # utils.llm_json (2026-06-04 synthesis-failure wave).
            result = parse_llm_json(response_text)
            decision = self._parse_decision(symbol, result, position_size, sizing_method)
            decision, inspection_used_advisor = await self._apply_tool_inspection(
                symbol=symbol,
                decision=decision,
                analyst_reports=analyst_reports,
                safety_status=safety_status,
                position_size=position_size,
            )

            # Advisor consultation on low-confidence trades
            advisor = _get_advisor()
            if not inspection_used_advisor and advisor is not None and decision.action != "hold":
                try:
                    # Extract regime from debate result for advisor context
                    regime = "unknown"
                    if isinstance(debate_result, dict):
                        regime = debate_result.get("regime", "unknown")
                    else:
                        regime = getattr(debate_result, "regime", "unknown")

                    if advisor.should_consult_trader(decision.confidence):
                        refined = await advisor.consult_trader_refinement(
                            direction=decision.action.upper(),
                            entry=decision.entry_price or 0.0,
                            stop=decision.stop_price or 0.0,
                            target=decision.target_1 or 0.0,
                            confidence=decision.confidence,
                            regime=regime,
                        )
                        if refined.consulted:
                            # Apply advisor refinements to the decision
                            decision.entry_price = refined.entry
                            decision.stop_price = refined.stop
                            decision.target_1 = refined.target
                            decision.confidence = refined.confidence
                            # Append advisor notes to reasoning for auditability
                            decision.reasoning += f"\n\n[Advisor Refinement] {refined.notes}"
                            logger.info(
                                "[Trader] %s: Advisor refined low-confidence trade. "
                                "confidence: %.2f → %.2f",
                                symbol,
                                float(result.get("confidence", 0.5)),
                                refined.confidence,
                            )
                except Exception as _adv_err:
                    logger.warning(
                        "[Trader] Advisor consultation raised for %s: %s", symbol, _adv_err
                    )
                    # graceful: continue with original decision

            # Corey-contradiction override (Phase 4 D3):
            # If Corey has a high-conviction session bias opposite to the trader's
            # proposed direction, escalate to Opus. Opus-HOLD or opposite verdict
            # overrides to HOLD; Opus-same-direction halves size (risk-adjusted
            # for the signal conflict, floor 1 contract).
            contradiction = _detect_corey_contradiction(decision.action, analyst_reports)
            if contradiction is not None and advisor is not None and decision.action != "hold":
                try:
                    regime = "unknown"
                    if isinstance(debate_result, dict):
                        regime = debate_result.get("regime", "unknown")
                    else:
                        regime = getattr(debate_result, "regime", "unknown")

                    trader_side = "LONG" if decision.action == "buy" else "SHORT"
                    opposite_side = "SHORT" if trader_side == "LONG" else "LONG"
                    consult = await advisor.consult_debate_tiebreak(
                        bull_case=(
                            f"Trader proposes {trader_side} on {symbol} at "
                            f"{decision.entry_price} with confidence={decision.confidence:.2f}."
                        ),
                        bear_case=(
                            f"Corey session bias is {contradiction['bias'].upper()} "
                            f"(conviction {contradiction['conviction']:.2f}) — "
                            f"contradicts the proposed {trader_side}."
                        ),
                        debate_score=0.0,
                        regime=regime,
                        analyst_reports=analyst_reports,
                    )
                    if consult.consulted:
                        opus_verdict = (consult.verdict or "").upper()
                        audit = (
                            f"\n\n[Corey-Contradiction Advisor] bias={contradiction['bias']} "
                            f"conv={contradiction['conviction']:.2f} | opus_verdict={opus_verdict} "
                            f"(conf={consult.confidence:.2f}): {consult.reasoning}"
                        )
                        if opus_verdict == "HOLD" or opus_verdict == opposite_side:
                            logger.info(
                                "[Trader] %s Corey contradiction → Opus override to HOLD "
                                "(opus=%s, trader=%s)",
                                symbol,
                                opus_verdict,
                                trader_side,
                            )
                            decision = self._hold_decision(
                                symbol=symbol,
                                reasoning=(
                                    f"Opus overrode {trader_side} to HOLD on Corey contradiction. "
                                    f"Corey bias={contradiction['bias']} "
                                    f"conv={contradiction['conviction']:.2f}. "
                                    f"Opus verdict={opus_verdict}: {consult.reasoning}"
                                ),
                                risk_notes=(
                                    "Corey session bias contradicted trader direction with "
                                    "high conviction; Opus confirmed HOLD."
                                ),
                            )
                        else:
                            # Opus agreed with trader — halve size as risk adjustment.
                            original_qty = decision.quantity
                            decision.quantity = max(1, decision.quantity // 2)
                            decision.reasoning += audit + (
                                f" | size adjusted {original_qty} → {decision.quantity} "
                                f"(50% conflict haircut)"
                            )
                            logger.info(
                                "[Trader] %s Corey contradiction → Opus proceed, "
                                "quantity %d → %d",
                                symbol,
                                original_qty,
                                decision.quantity,
                            )
                except Exception as _contra_err:
                    logger.warning(
                        "[Trader] Corey-contradiction advisor raised for %s: %s",
                        symbol,
                        _contra_err,
                    )
                    # graceful: continue with original decision

            logger.info(
                "[Trader] %s decision: action=%s confidence=%.2f signal_score=%.2f",
                symbol,
                decision.action,
                decision.confidence,
                decision.signal_score,
            )
            return decision

        except Exception as e:
            logger.error(f"[Trader] LLM decision failed for {symbol}: {e}")
            return self._hold_decision(
                symbol=symbol,
                reasoning=f"Trader LLM call failed: {e}. Defaulting to HOLD.",
                risk_notes="LLM failure — no trade decision made. Investigate before retrying.",
            )

    def _build_tool_inspection_context(
        self,
        analyst_reports: dict,
        safety_status: dict,
        position_size: Optional[PositionSizeResult],
    ) -> dict:
        """Build a context payload for the tool inspection manager from existing trader inputs."""
        technical_report = analyst_reports.get("technical", {})
        fundamental_report = analyst_reports.get("fundamental", {})
        indicators = (
            technical_report.get("indicators", {}) if isinstance(technical_report, dict) else {}
        )

        recent_volume = None
        if isinstance(technical_report, dict):
            for key in ("recent_volume", "current_volume", "volume"):
                if technical_report.get(key) is not None:
                    recent_volume = technical_report.get(key)
                    break
        if recent_volume is None and isinstance(indicators, dict):
            for key in ("recent_volume", "volume"):
                if indicators.get(key) is not None:
                    recent_volume = indicators.get(key)
                    break

        vix = None
        if isinstance(fundamental_report, dict):
            key_metrics = fundamental_report.get("key_metrics", {})
            if isinstance(key_metrics, dict):
                vix = key_metrics.get("vix")

        from config import settings  # local import to avoid circular deps

        return {
            "recent_volume": recent_volume,
            "vix": vix,
            "kill_switch_active": safety_status.get("kill_switch_active", False),
            "base_size": position_size.contracts if position_size is not None else 0,
            "max_contracts": getattr(settings, "MAX_CONTRACTS_PER_INSTRUMENT", 2),
        }

    async def _apply_tool_inspection(
        self,
        symbol: str,
        decision: TradeDecision,
        analyst_reports: dict,
        safety_status: dict,
        position_size: Optional[PositionSizeResult],
    ) -> tuple[TradeDecision, bool]:
        """Apply the tool inspection chain to the generated trade decision."""
        if decision.action == "hold":
            return decision, False

        manager = _get_tool_inspection_manager()
        if manager is None:
            return decision, False

        context = self._build_tool_inspection_context(
            analyst_reports=analyst_reports,
            safety_status=safety_status,
            position_size=position_size,
        )
        args = {
            "symbol": symbol,
            "action": decision.action,
            "quantity": decision.quantity,
        }
        inspection_result, messages = manager.inspect_all("ib_order", args, context)
        message_text = (
            "; ".join(message for message in messages if message) or "tool inspection triggered"
        )

        if inspection_result.value == "allow":
            return decision, False

        if inspection_result.value == "deny":
            logger.warning(
                "[Trader] %s: tool inspection denied execution — %s", symbol, message_text
            )
            return (
                self._hold_decision(
                    symbol=symbol,
                    reasoning=f"Tool inspection blocked trade: {message_text}",
                    risk_notes=message_text,
                ),
                False,
            )

        advisor = _get_advisor()
        if advisor is None or not advisor.is_available():
            logger.warning(
                "[Trader] %s: tool inspection requires approval but advisor unavailable — %s",
                symbol,
                message_text,
            )
            return (
                self._hold_decision(
                    symbol=symbol,
                    reasoning=f"Tool inspection requires approval: {message_text}",
                    risk_notes=f"Approval required before execution. {message_text}",
                ),
                False,
            )

        regime = "unknown"
        if isinstance(debate_result := analyst_reports.get("debate_result"), dict):
            regime = debate_result.get("regime", "unknown")

        try:
            refined = await advisor.consult_trader_refinement(
                direction=decision.action.upper(),
                entry=decision.entry_price or 0.0,
                stop=decision.stop_price or 0.0,
                target=decision.target_1 or 0.0,
                confidence=decision.confidence,
                regime=regime,
                notes=message_text,
            )
        except Exception as _inspect_err:
            logger.warning(
                "[Trader] %s: tool inspection advisor consult raised — %s",
                symbol,
                _inspect_err,
            )
            return (
                self._hold_decision(
                    symbol=symbol,
                    reasoning=f"Tool inspection approval failed: {message_text}",
                    risk_notes=f"Approval path raised error: {_inspect_err}",
                ),
                False,
            )

        if not getattr(refined, "consulted", False):
            logger.warning(
                "[Trader] %s: tool inspection approval unavailable — %s",
                symbol,
                message_text,
            )
            return (
                self._hold_decision(
                    symbol=symbol,
                    reasoning=f"Tool inspection requires approval: {message_text}",
                    risk_notes="Advisor approval was unavailable; execution blocked.",
                ),
                False,
            )

        decision.entry_price = refined.entry
        decision.stop_price = refined.stop
        decision.target_1 = refined.target
        decision.confidence = refined.confidence
        decision.reasoning += f"\n\n[Tool Inspection] {message_text}"
        if refined.notes:
            decision.reasoning += f"\n[Advisor Approval] {refined.notes}"
        logger.info(
            "[Trader] %s: tool inspection required approval and advisor allowed continuation",
            symbol,
        )
        return decision, True

    # ── Prompt Construction ────────────────────────────────────────────────

    def _build_prompt(
        self,
        symbol: str,
        debate_result: dict,
        analyst_reports: dict,
        safety_status: dict,
        position_size: PositionSizeResult,
        working_memory: str = "",
    ) -> str:
        from config import settings  # local import to avoid circular deps

        technical = analyst_reports.get("technical", {})
        news = analyst_reports.get("news", {})
        social = analyst_reports.get("social", {})
        forward_recorder = analyst_reports.get("forward_recorder_metric")
        regime_status = analyst_reports.get("regime_status")

        # Phase 3.5: Working Memory Integration
        memory_section = ""
        if working_memory:
            memory_section = f"""
=== TRADER WORKING MEMORY (PHASE 3.5) ===
The following observations and lessons were recalled from your prior sessions for {symbol}:
{working_memory}
Include these cross-session insights in your reasoning.
"""

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

        # Build the StarkTPO block only when a real signal is present.
        # When stark_signal is absent (StarkTPO skipped or not ready), omit the
        # entire HARD CONSTRAINT section so no spurious HOLD directive fires.
        tpo_section = ""
        if technical.get("stark_signal"):
            tpo_section = (
                "=== STARK-TPO ALGORITHMIC MATRIX (HARD CONSTRAINT) ===\n"
                f"TPO Algorithmic Signal: {technical.get('stark_signal')}\n"
                f"TPO Sub-Structure: {technical.get('stark_structure', 'UNKNOWN')}\n"
                "\n"
                "CRITICAL DIRECTIVE: The Stark-TPO algorithm has computed the raw math edge.\n"
                "If the TPO Algorithmic Signal is 'HOLD', you MUST output 'hold'.\n"
                "If the TPO Algorithmic Signal is 'LONG' or 'SHORT', weight it heavily but still apply risk judgment.\n"
                "\n"
            )

        return f"""Make a trade decision for {symbol}.

{memory_section}
{tpo_section}=== DETERMINISTIC REGIME-BASED ROUTER (PHASE 4) ===
Current Regime: {getattr(regime_status, 'regime', 'NEUTRAL').value.upper() if regime_status else 'NEUTRAL'}
Description: {getattr(regime_status, 'description', 'No deterministic regime status available.') if regime_status else 'None'}
ADX: {getattr(regime_status, 'adx', 0.0):.1f} | ATR Ratio: {getattr(regime_status, 'atr_ratio', 1.0):.2f}

ROUTING DIRECTIVES:
- If regime=TRENDING: Prioritize 'Breakout Specialist' and 'STARK-TPO Alignment'.
- If regime=RANGING: Prioritize 'Harmonic Vision' (reversal zones) and 'STC/Oscillator' confluence. Expect mean-reversion.
- If regime=VOLATILE: Be extremely conservative. Require higher confidence (>0.8) for any entry.

=== NEWS & SENTIMENT OVERLAY ===
News Event Type: {news.get("event_type", "none")}
Bullish Catalysts: {news.get("catalysts_bull", [])}
Bearish Catalysts: {news.get("catalysts_bear", [])}
Social Signal: {social.get("signal", "N/A")}

=== BREAKOUT SPECIALIST ENRICHMENT (PHASE 4) ===
Breakout Status: {analyst_reports.get("breakout", {}).get("status", "N/A")} ({analyst_reports.get("breakout", {}).get("side", "N/A")})
Value Area (VAH/VAL): {analyst_reports.get("breakout", {}).get("vah", "N/A")} / {analyst_reports.get("breakout", {}).get("val", "N/A")}
POC: {analyst_reports.get("breakout", {}).get("poc", "N/A")}
Signal: {analyst_reports.get("breakout", {}).get("signal", 0.0)} (weight: HIGH for breakouts)

=== HARMONIC VISION ENRICHMENT (PHASE 4) ===
Patterns: {analyst_reports.get("harmonic", {}).get("summary", "None detected")}
Active Patterns: {analyst_reports.get("harmonic", {}).get("patterns", [])}
Signal: {analyst_reports.get("harmonic", {}).get("signal", 0.0)} (weight: HIGH for reversal confluence)

=== OPTIONS YIELD OVERLAY (PHASE 5) ===
Options Signal: {analyst_reports.get("options", {}).get("signal", 0.0)}
Best Spread: {json.dumps(analyst_reports.get("options", {}).get("best_spread"), indent=2)}
Options Summary: {analyst_reports.get("options", {}).get("summary", "No options spreads available.")}

{self._forward_recorder_section(forward_recorder)}

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
  "reasoning": "<thorough explanation of why this action was chosen, integrating TPO structure with News sentiment>",
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

        # Phase 5.4: Options Spread Fields
        is_spread = bool(result.get("is_spread", False))
        short_opt = result.get("short_option_symbol")
        long_opt = result.get("long_option_symbol")
        net_credit = result.get("net_credit")

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
            is_spread=is_spread,
            short_option_symbol=short_opt,
            long_option_symbol=long_opt,
            net_credit=net_credit,
            rr_ratio=rr_ratio,
            time_in_force=time_in_force,
            signal_score=float(result.get("signal_score", 0.0)),
            confidence=float(result.get("confidence", 0.5)),
            reasoning=reasoning,
            risk_notes=result.get("risk_notes", ""),
            timestamp=datetime.now(),
            sizing_method=sizing_method,
        )
    @staticmethod
    def _forward_recorder_section(metric: Optional[dict]) -> str:
        """Render the MES forward-recorder feedback block when present.

        Returns empty string (including no header) when the metric is absent
        so non-MES symbols — and MES pipelines where pre-market recording
        failed — get the legacy prompt shape unchanged.

        `degraded=True` means samples < 5; the block tells the LLM the
        signal is weak so the trader can avoid over-weighting it.
        """
        if not isinstance(metric, dict):
            return ""
        hit_rate = metric.get("hit_rate")
        samples = metric.get("samples", 0)
        degraded = metric.get("degraded")
        last = metric.get("last_hypothesis") or {}

        hr_str = f"{hit_rate:.2f}" if isinstance(hit_rate, (int, float)) else "N/A"
        deg_str = " (degraded: sample size < 5)" if degraded else ""
        last_line = (
            f"Last hypothesis ({last.get('date', '?')}): "
            f"side={last.get('entry_hypothesis_side', '?')} "
            f"open={last.get('open_price', '?')} "
            f"reason={last.get('entry_hypothesis_reason', '?')}"
            if last
            else "No prior session hypothesis on record."
        )
        return (
            f"\n=== FORWARD-RECORDER FEEDBACK (MES observational) ===\n"
            f"Recent hit rate (last {samples} sessions): {hr_str}{deg_str}\n"
            f"{last_line}\n"
            f"Use this empirically-derived feedback as directional context — "
            f"a low hit rate warrants extra caution on high-conviction entries.\n"
        )

    def _compute_confluence_multiplier(
        self, analyst_reports: dict, verdict_direction: str
    ) -> float:
        """
        Count how many Stage 1 agents agree with the verdict direction.

        Each agent report is expected to carry a signal value accessible via
        a ``signal``, ``bias``, or ``sentiment_score`` attribute/key.
        Positive values are treated as bullish; negative as bearish.

        Parameters
        ----------
        analyst_reports:
            Dict of upstream agent reports (objects with attributes, or plain dicts).
        verdict_direction:
            "LONG" or "SHORT" (derived from the debate verdict).

        Returns
        -------
        float
            1.5  — 80%+ agreement  (4/5 or 5/5 agents aligned)
            1.0  — 60% agreement   (3/5 agents aligned)
            0.75 — 40% agreement   (2/5 agents aligned)
            0.0  — < 40% agreement — caller should force HOLD
        """
        agreements = 0
        total = 0
        for agent_name, report in analyst_reports.items():
            # hidden_pivots is supplemental — exclude from primary confluence vote
            if agent_name == "hidden_pivots":
                continue
            # Try attribute access first (dataclass), then dict key access
            signal = None
            for field_name in ("signal", "bias", "sentiment_score"):
                signal = getattr(report, field_name, None)
                if signal is None and isinstance(report, dict):
                    signal = report.get(field_name)
                if signal is not None:
                    break
            if signal is None:
                continue
            try:
                signal_val = float(signal)
            except (TypeError, ValueError):
                continue
            total += 1
            if verdict_direction == "LONG" and signal_val > 0:
                agreements += 1
            elif verdict_direction == "SHORT" and signal_val < 0:
                agreements += 1

        if total == 0:
            # No signal data available — neutral, do not penalise
            return 1.0

        ratio = agreements / total
        if ratio >= 0.8:
            return 1.5
        elif ratio >= 0.6:
            return 1.0
        elif ratio >= 0.4:
            return 0.75
        elif ratio >= 0.2:
            return 0.5  # Fix A (2026-04-10) — minority support still permits a half-size trade
        elif ratio > 0.0:
            return 0.25  # Fix A (2026-04-10) — lone-voice support permits a quarter-size probe
        else:
            return 0.0  # Zero agreement still forces HOLD (upstream Fix C may still override via advisor)

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
