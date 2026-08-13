"""
JARVIS TRADER — Debate Orchestrator
=====================================
Runs a structured 3-round adversarial bull/bear debate and scores the outcome.

Round structure
---------------
Round 1  — Initial positions (parallel): both agents independently analyse the
           same analyst_reports and produce their opening arguments.
Round 2  — Adversarial scoring (parallel): each side scores the opponent's
           argument 1-10 and identifies its single weakest point.
Round 3  — Rebuttals (parallel): each side rebuts the weakness identified by
           the opponent in Round 2.

Scoring
-------
debate_score = (bear_score_of_bull - bull_score_of_bear) / 10
  Range: -1.0 to +1.0
  > 0.2  → BULL_WINS  → long bias
  < -0.2 → BEAR_WINS  → short bias
  else   → INCONCLUSIVE → force HOLD downstream regardless of TraderAgent

The final DebateResult contains the raw reports, per-round outputs, the
debate_score, and a verdict string.
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .bear_researcher import BearReport, BearResearcherAgent
from .bull_researcher import BullReport, BullResearcherAgent
from .tail_risk_researcher import TailRiskReport, TailRiskResearcherAgent

logger = logging.getLogger(__name__)

__all__ = ["DebateResult", "DebateOrchestrator"]

# ── Lazy-init Advisor + IC Ensemble (Tracks F + H, wired 2026-04-10) ──────
# Module-level singletons so we don't pay construction cost per debate run.
# Both gracefully degrade when their dependencies are missing — see the
# AdvisorClient + ICWeightedEnsemble docstrings for failure semantics.
_advisor_instance = None
_ic_ensemble_instance = None
_tail_risk_instance = None
_brier_tracker_instance = None


def _is_tail_risk_enabled() -> bool:
    """Tail-risk researcher (Novel #1) is opt-in via env. Defaults False so the
    pipeline ships dark; flip to "true"/"1" to enable parallel scoring."""
    flag = os.environ.get("TAIL_RISK_RESEARCHER_ENABLED", "false").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _is_brier_enabled() -> bool:
    """Brier calibration blend (Novel #2) is opt-in via env. Defaults False so the
    pipeline ships dark; flip to "true"/"1" after trade_outcomes has N>=5 per agent."""
    flag = os.environ.get("BRIER_CALIBRATION_ENABLED", "false").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _is_sepa_enabled() -> bool:
    """SEPA (Minervini Stage 2) regime-confirmation nudge is opt-in via env.
    Defaults False so the pipeline ships dark; flip to "true"/"1" once pipeline.py
    is wired to populate `sepa_context` with daily OHLC series."""
    flag = os.environ.get("REGIME_USE_SEPA", "false").strip().lower()
    return flag in ("1", "true", "yes", "on")


# SEPA nudge parameters. Intentionally small — this is a regime confirmation,
# not a directional override. Magnitude is less than half of the tightest
# regime threshold (COMPRESSION at 0.15), so SEPA alone cannot flip a verdict;
# it only strengthens an already-near-threshold score.
_SEPA_BULL_THRESHOLD: float = 0.75
_SEPA_BEAR_THRESHOLD: float = 0.25
_SEPA_NUDGE_MAGNITUDE: float = 0.03
_SEPA_MIN_EVALUATED: int = 5


# Symbol-scoped Corey weight floor for futures (Phase 4 D4).
# Per owner directive 2026-04-19 (feedback_futures_sentiment_source.md), Corey's
# #market-updates channel is the authoritative futures sentiment source; equities
# use the normal accuracy-weighted path unchanged. The floor (1.20) is near the
# MAX_WEIGHT cap (1.30) from AgentFeedbackTracker so it meaningfully amplifies
# Corey's signal during cold-start when few organic trade_outcomes rows exist.
COREY_FUTURES_SYMBOLS: frozenset[str] = frozenset({"MCL", "MNQ", "MES", "MGC"})
COREY_FUTURES_WEIGHT_FLOOR: float = 1.20


def _apply_corey_futures_elevation(agent_weights: dict, symbol: str) -> dict:
    """Return a copy of *agent_weights* with Corey's weight floored for futures.

    No-op for non-futures symbols. Takes max(historical_weight, floor) so a
    historically-accurate Corey above the floor is not regressed downward.
    """
    if not isinstance(symbol, str):
        return agent_weights
    if symbol.upper() not in COREY_FUTURES_SYMBOLS:
        return agent_weights
    elevated = dict(agent_weights)
    current = elevated.get("corey", 1.0)
    elevated["corey"] = max(current, COREY_FUTURES_WEIGHT_FLOOR)
    return elevated


def _corey_tiebreak(analyst_reports: Optional[dict]) -> Optional[str]:
    """Return a verdict based on Corey's session bias, or None.

    Used as a last-resort tie-break when debate_score is in the dead zone AND
    the existing conviction-asymmetry tie-break failed to break the tie.
    Corey is the authoritative futures sentiment source per owner directive
    (2026-04-19); if he's committed enough to the session direction
    (conviction >= 0.5) and bias is not neutral, follow him.

    Threshold matches the researcher-evidence boost threshold (0.5) from
    BullResearcherAgent._apply_discord_evidence for consistency.

    Returns "BULL_WINS" | "BEAR_WINS" | None.
    """
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
    if conv < 0.5:
        return None
    if bias == "bullish":
        return "BULL_WINS"
    if bias == "bearish":
        return "BEAR_WINS"
    return None


def _apply_sepa_nudge(debate_score: float, raw_nudge: float) -> tuple[float, float]:
    """Apply a SEPA nudge only when it agrees with the debate direction.

    Returns ``(new_debate_score, applied_nudge)``. The applied_nudge is 0.0
    when the raw nudge would contradict the debate — SEPA is a confirmation
    signal, not a reversal signal. Callers store the applied_nudge for audit.
    """
    if raw_nudge == 0.0:
        return (debate_score, 0.0)
    if debate_score > 0 and raw_nudge > 0:
        return (round(debate_score + raw_nudge, 4), raw_nudge)
    if debate_score < 0 and raw_nudge < 0:
        return (round(debate_score + raw_nudge, 4), raw_nudge)
    # Directionally contradicts (or debate_score is exactly 0) — don't apply
    return (debate_score, 0.0)


def _compute_sepa_nudge(
    sepa_context: Optional[dict],
) -> tuple[Optional[float], float]:
    """Compute a bounded debate-score nudge from a SEPA evaluation.

    Pure function — does no I/O and no config reads. The env gate
    (:func:`_is_sepa_enabled`) is checked at the call site; this helper is
    safe to call directly in tests.

    Parameters
    ----------
    sepa_context:
        Optional dict with either:
          * ``{"close": pd.Series, "high": pd.Series, "low": pd.Series,
             "benchmark_close": Optional[pd.Series]}`` — we'll evaluate SEPA
             from the supplied bars, or
          * ``{"result": SEPAResult}`` — a pre-computed result (lets the caller
             cache the evaluation across the pipeline).

    Returns
    -------
    (score, nudge) tuple:
        ``score`` is the SEPA score in [0, 1] or None if the context was
        missing/thin. ``nudge`` is a float in {-_SEPA_NUDGE_MAGNITUDE, 0,
        +_SEPA_NUDGE_MAGNITUDE} to be added to ``debate_score``.
    """
    if not sepa_context:
        return (None, 0.0)

    try:
        if "result" in sepa_context:
            sepa_result = sepa_context["result"]
        else:
            try:
                from engine.analytics.sepa_trend_template import evaluate_sepa
            except ImportError:
                from analytics.sepa_trend_template import evaluate_sepa
            sepa_result = evaluate_sepa(
                close=sepa_context.get("close"),
                high=sepa_context.get("high"),
                low=sepa_context.get("low"),
                benchmark_close=sepa_context.get("benchmark_close"),
            )
    except Exception as _err:  # pragma: no cover — defensive
        logger.info("SEPA evaluation failed in debate: %s", _err)
        return (None, 0.0)

    if sepa_result is None:
        return (None, 0.0)

    evaluated = getattr(sepa_result, "evaluated_count", 0)
    if evaluated < _SEPA_MIN_EVALUATED:
        return (None, 0.0)

    score = float(getattr(sepa_result, "score", 0.0))
    if score >= _SEPA_BULL_THRESHOLD:
        return (score, _SEPA_NUDGE_MAGNITUDE)
    if score <= _SEPA_BEAR_THRESHOLD:
        return (score, -_SEPA_NUDGE_MAGNITUDE)
    return (score, 0.0)


def _get_tail_risk_agent() -> Optional[TailRiskResearcherAgent]:
    """Lazy-construct TailRiskResearcherAgent. Returns None if disabled or init fails."""
    global _tail_risk_instance
    if not _is_tail_risk_enabled():
        return None
    if _tail_risk_instance is None:
        try:
            _tail_risk_instance = TailRiskResearcherAgent()
        except Exception as _err:  # pragma: no cover — defensive
            logger.info("TailRiskResearcherAgent unavailable: %s", _err)
            _tail_risk_instance = False
    return _tail_risk_instance if _tail_risk_instance is not False else None


def _get_advisor():
    """Lazy-construct AdvisorClient. Returns None on import/init failure."""
    global _advisor_instance
    if _advisor_instance is None:
        try:
            from engine.agents.advisor_client import AdvisorClient

            _advisor_instance = AdvisorClient()
        except Exception as _err:  # pragma: no cover — defensive
            logger.info("AdvisorClient unavailable in debate: %s", _err)
            _advisor_instance = False  # sentinel: tried and failed
    return _advisor_instance if _advisor_instance is not False else None


def _get_ic_ensemble(agents):
    """Lazy-construct ICWeightedEnsemble. Returns None on import/init failure."""
    global _ic_ensemble_instance
    if _ic_ensemble_instance is None:
        try:
            try:
                from engine.analytics.ic_ensemble import ICWeightedEnsemble
            except ImportError:
                from analytics.ic_ensemble import ICWeightedEnsemble
            _ic_ensemble_instance = ICWeightedEnsemble(agents=list(agents))
        except Exception as _err:  # pragma: no cover — defensive
            logger.info("ICWeightedEnsemble unavailable in debate: %s", _err)
            _ic_ensemble_instance = False  # sentinel
    return _ic_ensemble_instance if _ic_ensemble_instance is not False else None


def _get_brier_tracker(agents):
    """Lazy-construct BrierCalibrationTracker. Returns None when env-gate is off or init fails.

    Singleton so we don't re-open the agent_feedback.db connection per debate run.
    Failures cache to a False sentinel so retries don't stampede.
    """
    global _brier_tracker_instance
    if not _is_brier_enabled():
        return None
    if _brier_tracker_instance is None:
        try:
            try:
                from engine.analytics.ic_ensemble import BrierCalibrationTracker
            except ImportError:
                from analytics.ic_ensemble import BrierCalibrationTracker
            _brier_tracker_instance = BrierCalibrationTracker(agents=list(agents))
        except Exception as _err:  # pragma: no cover — defensive
            logger.info("BrierCalibrationTracker unavailable in debate: %s", _err)
            _brier_tracker_instance = False  # sentinel
    return _brier_tracker_instance if _brier_tracker_instance is not False else None


# Regime-adaptive debate verdict thresholds.
# Tighter thresholds for high-conviction regimes (less noise needed to call a winner);
# looser thresholds for choppy/uncertain regimes (require stronger signal).
REGIME_DEBATE_THRESHOLDS: dict[str, float] = {
    "COMPRESSION": 0.15,
    "TRENDING_BULL": 0.18,
    "TRENDING_BEAR": 0.18,
    "RANGE_BOUND": 0.22,
    "EXHAUSTED": 0.25,
    "RANGING": 0.22,  # alias for RANGE_BOUND
    "CAUTION": 0.20,  # default for unknown regimes
}
DEFAULT_DEBATE_THRESHOLD = 0.20

# Legacy fixed threshold (kept so existing callers that reference _VERDICT_THRESHOLD still compile)
_VERDICT_THRESHOLD = DEFAULT_DEBATE_THRESHOLD

# Brier calibration blend weight (Novel #2).
#   final_mult = alpha * (1 + IC) + (1 - alpha) * brier_mult_centered
# alpha=1.0 preserves pure IC behavior (the dark-ship baseline), alpha=0.0
# is pure Brier. 0.5 is a symmetric starting point; tune per regime in a follow-up.
BRIER_BLEND_ALPHA: float = 0.5


@dataclass
class DebateResult:
    """Structured outcome of the 3-round bull/bear debate for a single symbol."""

    symbol: str
    timestamp: datetime

    # Round 1 — raw agent outputs
    bull_report: Optional[BullReport] = None
    bear_report: Optional[BearReport] = None

    # Round 2 — adversarial scores (each side rates the opponent 1-10)
    bull_score: int = 5  # bear's rating of the bull argument
    bear_score: int = 5  # bull's rating of the bear argument
    bull_weakest_point: str = ""
    bear_weakest_point: str = ""

    # Round 3 — rebuttals
    bull_rebuttal: str = ""
    bear_rebuttal: str = ""

    # Scoring output
    debate_score: float = 0.0  # -1.0 to +1.0
    verdict: str = "INCONCLUSIVE"  # BULL_WINS | BEAR_WINS | INCONCLUSIVE

    # Legacy fields kept for backwards compat with pipeline logging
    bull_conviction: float = 0.0
    bear_conviction: float = 0.0
    debate_summary: str = "Inconclusive"
    recommended_direction: str = "flat"
    combined_signal: float = 0.0

    # Flags
    rounds_completed: int = 1
    scoring_failed: bool = False
    credits_exhausted: bool = False

    # IC-weighted alpha combination metadata (Track F1)
    ir_score: float = 0.0  # IR = IC_avg × √N (Fundamental Law of Active Management)
    ic_avg: float = 0.0  # mean Information Coefficient across active analysts
    ic_n_analysts: int = 0  # number of analysts with IC > 0

    # Tail-risk researcher output (Novel #1, opt-in via TAIL_RISK_RESEARCHER_ENABLED)
    tail_risk_report: Optional[TailRiskReport] = None

    # SEPA regime-confirmation nudge (opt-in via REGIME_USE_SEPA).
    # sepa_score is the Minervini Stage 2 score in [0, 1]; sepa_nudge is the
    # signed delta applied to debate_score (±_SEPA_NUDGE_MAGNITUDE or 0).
    sepa_score: Optional[float] = None
    sepa_nudge: float = 0.0

    # Phase 3.2 Structured Confluence Scoring
    confluence_scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            # Round 1
            "bull_report": self.bull_report.to_dict() if self.bull_report else None,
            "bear_report": self.bear_report.to_dict() if self.bear_report else None,
            # Round 2
            "bull_score": self.bull_score,
            "bear_score": self.bear_score,
            "bull_weakest_point": self.bull_weakest_point,
            "bear_weakest_point": self.bear_weakest_point,
            # Round 3
            "bull_rebuttal": self.bull_rebuttal,
            "bear_rebuttal": self.bear_rebuttal,
            # Scoring
            "debate_score": self.debate_score,
            "verdict": self.verdict,
            # Legacy
            "bull_conviction": self.bull_conviction,
            "bear_conviction": self.bear_conviction,
            "debate_summary": self.debate_summary,
            "recommended_direction": self.recommended_direction,
            "combined_signal": self.combined_signal,
            # Meta
            "rounds_completed": self.rounds_completed,
            "scoring_failed": self.scoring_failed,
            "credits_exhausted": self.credits_exhausted,
            # IC/IR metadata (Track F1)
            "ir_score": self.ir_score,
            "ic_avg": self.ic_avg,
            "ic_n_analysts": self.ic_n_analysts,
            # Tail-risk (Novel #1, opt-in)
            "tail_risk_report": self.tail_risk_report.to_dict() if self.tail_risk_report else None,
            # SEPA regime confirmation (opt-in)
            "sepa_score": self.sepa_score,
            "sepa_nudge": self.sepa_nudge,
            # Confluence (Phase 3.2)
            "confluence_scores": self.confluence_scores,
        }


class DebateOrchestrator:
    """
    Orchestrates a 3-round adversarial debate between BullResearcherAgent
    and BearResearcherAgent, scores the outcome, and returns a verdict.

    Usage
    -----
    ::

        from engine.agents.bull_researcher import BullResearcherAgent
        from engine.agents.bear_researcher import BearResearcherAgent
        from engine.agents.debate import DebateOrchestrator

        bull = BullResearcherAgent(api_key="sk-ant-...")
        bear = BearResearcherAgent(api_key="sk-ant-...")
        orchestrator = DebateOrchestrator()

        result = await orchestrator.run_debate(
            symbol="MCL",
            analyst_reports={"technical": tech_report, "news": news_report},
            bull=bull,
            bear=bear,
        )
        print(result.verdict)        # "BULL_WINS" | "BEAR_WINS" | "INCONCLUSIVE"
        print(result.debate_score)   # float -1.0 to +1.0
    """

    # Legacy conviction thresholds (still used for recommended_direction)
    CONVICTION_THRESHOLD = 0.15
    DIRECTION_THRESHOLD = 0.10

    # ── Public entry point ────────────────────────────────────────────────────

    async def run_debate(
        self,
        symbol: str,
        analyst_reports: dict,
        bull: BullResearcherAgent,
        bear: BearResearcherAgent,
        rounds: int = 3,  # kept for interface compat; 3 is the default
        regime: Optional[str] = None,
        sepa_context: Optional[dict] = None,
    ) -> DebateResult:
        """
        Run the 3-round adversarial debate and return a scored DebateResult.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        analyst_reports:
            Dict of upstream signal dicts/objects (technical, news, etc.).
        bull:
            Instantiated BullResearcherAgent.
        bear:
            Instantiated BearResearcherAgent.
        rounds:
            Ignored — always runs 3 rounds. Kept for backwards compat.
        regime:
            Optional market regime string from TechnicalAnalystAgent (e.g.
            "TRENDING_BULL", "COMPRESSION").  When provided, the verdict
            threshold is looked up from REGIME_DEBATE_THRESHOLDS; otherwise
            DEFAULT_DEBATE_THRESHOLD (0.20) is used.

        Returns
        -------
        DebateResult
            Full 3-round result including debate_score and verdict.
        """
        # Resolve the adaptive threshold for this regime
        _threshold = REGIME_DEBATE_THRESHOLDS.get((regime or "").upper(), DEFAULT_DEBATE_THRESHOLD)

        # Load agent accuracy weights (pre-computed; no DB hit in hot path)
        try:
            from engine.analytics.agent_feedback import AgentFeedbackTracker

            _tracker = AgentFeedbackTracker()
            if regime:
                agent_weights = _tracker.get_weights_by_regime(regime)
            else:
                agent_weights = _tracker.load_weights()
        except Exception:
            _tracker = None
            agent_weights = {}

        # Phase 4 D4: floor Corey's weight for futures symbols so his
        # authoritative sentiment signal is not down-weighted during the
        # cold-start period while trade_outcomes is still accumulating.
        agent_weights = _apply_corey_futures_elevation(agent_weights, symbol)

        # IC scores — Information Coefficients per analyst.
        # Track H upgrade (2026-04-10): prefer Spearman rank correlation from
        # ICWeightedEnsemble when its underlying trade_outcomes table has
        # enough rows; fall back to the existing accuracy-based formulation
        # (Track F1) when the new ensemble is empty or unavailable. The two
        # produce different magnitudes but the downstream `signal × (1 + IC)`
        # formula handles both — Spearman just yields stronger boosts for
        # genuinely-skilled analysts because it captures rank ordering, not
        # binary correctness.
        _ic_analyst_names = [
            "technical",
            "news",
            "social",
            "fundamental",
            "corey",
            "breakout",
            "harmonic",
        ]
        ic_scores: dict[str, float] = {}
        _ic_source = "none"

        _spearman_ensemble = _get_ic_ensemble(_ic_analyst_names)
        if _spearman_ensemble is not None:
            try:
                _spearman_ics = {
                    name: _spearman_ensemble.compute_ic(name) for name in _ic_analyst_names
                }
                if any(v > 0 for v in _spearman_ics.values()):
                    ic_scores = {name: max(0.0, v) for name, v in _spearman_ics.items()}
                    _ic_source = "spearman"
            except Exception as _ic_err:
                logger.debug("ICWeightedEnsemble.compute_ic failed: %s", _ic_err)

        if not ic_scores:
            try:
                if _tracker is not None:
                    ic_scores = {
                        name: max(0.0, _tracker.compute_accuracy(name) - 0.5)
                        for name in _ic_analyst_names
                    }
                    _ic_source = "accuracy"
                else:
                    ic_scores = {}
            except Exception:
                ic_scores = {}

        # Brier calibration weights (Novel #2). Gated by BRIER_CALIBRATION_ENABLED.
        # Returns normalized inverse-Brier weights summing to 1.0 (neutral=1/N per agent).
        # Cold-start is self-protecting: agents with < min_trades=5 rows get the
        # neutral sentinel which collapses the blend to pure IC.
        _brier_tracker = _get_brier_tracker(_ic_analyst_names)
        brier_weights: dict[str, float] = {}
        if _brier_tracker is not None:
            try:
                brier_weights = _brier_tracker.get_calibration_weights(_ic_analyst_names)
                logger.debug("[Debate] %s brier_weights=%s", symbol, brier_weights)
            except Exception as _b_err:
                logger.debug("BrierCalibrationTracker.get_calibration_weights failed: %s", _b_err)

        # Compute IR (Information Ratio) for this debate run and log it
        _ic_active = {k: v for k, v in ic_scores.items() if v > 0}
        _n_analysts = len(_ic_active)
        _avg_ic = sum(_ic_active.values()) / max(_n_analysts, 1) if _ic_active else 0.0
        _ir_score = _avg_ic * (_n_analysts**0.5) if _n_analysts > 0 else 0.0
        logger.info(
            "[Debate] %s alpha combination: IC_avg=%.3f N=%d IR_score=%.3f source=%s brier_on=%s",
            symbol,
            _avg_ic,
            _n_analysts,
            _ir_score,
            _ic_source,
            bool(brier_weights),
        )

        # Apply IC weights + accuracy weights to analyst_reports signals before
        # passing to researchers.  Each analyst's signal is boosted by its IC
        # quality (IC=0.2 → 1.2× multiplier) on top of the accuracy weight so
        # that historically-accurate, high-IC analysts exert more influence.
        weighted_reports = {}
        for agent_name, report in analyst_reports.items():
            weight = agent_weights.get(agent_name, 1.0)
            if isinstance(report, dict) and "signal" in report:
                report = dict(report)
                # Apply accuracy weight (Track E)
                if weight != 1.0:
                    report["signal"] = report["signal"] * weight
                    report["_weight_applied"] = round(weight, 3)
                # Apply IC multiplier on top (Track F1): signal × (1 + IC).
                # When Brier weights are available (Novel #2), blend them into the
                # multiplier via `_brier_blended_signal` instead.
                if brier_weights:
                    report["signal"] = _brier_blended_signal(
                        report["signal"],
                        agent_name,
                        ic_scores,
                        brier_weights,
                        BRIER_BLEND_ALPHA,
                    )
                    report["_brier_applied"] = round(brier_weights.get(agent_name, 0.0), 4)
                else:
                    report["signal"] = _ic_weighted_signal(report["signal"], agent_name, ic_scores)
                ic_val = ic_scores.get(agent_name, 0.0)
                if ic_val > 0:
                    report["_ic_applied"] = round(ic_val, 3)
            weighted_reports[agent_name] = report

        logger.info(f"[Debate] {symbol} — Round 1: parallel opening statements")
        _tail_risk_agent = _get_tail_risk_agent()
        if _tail_risk_agent is not None:
            bull_report, bear_report, tail_risk_report = await asyncio.gather(
                bull.analyze(symbol, weighted_reports),
                bear.analyze(symbol, weighted_reports),
                _tail_risk_agent.analyze(symbol, weighted_reports),
            )
        else:
            bull_report, bear_report = await asyncio.gather(
                bull.analyze(symbol, weighted_reports),
                bear.analyze(symbol, weighted_reports),
            )
            tail_risk_report = None

        result = self._build_initial_result(symbol, bull_report, bear_report)
        result.tail_risk_report = tail_risk_report
        if tail_risk_report is not None:
            logger.info(
                "[Debate] %s tail-risk: score=%.2f size_mult=%.2f veto=%s rec=%s",
                symbol,
                tail_risk_report.tail_risk_score,
                tail_risk_report.size_multiplier,
                tail_risk_report.veto,
                tail_risk_report.recommendation,
            )

        # Attach IC/IR metadata to result (Track F1)
        result.ir_score = round(_ir_score, 4)
        result.ic_avg = round(_avg_ic, 4)
        result.ic_n_analysts = _n_analysts

        # ── SEPA regime-confirmation computation (opt-in, REGIME_USE_SEPA) ───
        # The raw nudge is computed here; actual application is gated by
        # :func:`_apply_sepa_nudge` at each verdict site so SEPA only
        # reinforces the debate direction, never contradicts it.
        _sepa_raw_nudge = 0.0
        if _is_sepa_enabled():
            _sepa_score, _sepa_raw_nudge = _compute_sepa_nudge(sepa_context)
            result.sepa_score = _sepa_score
            if _sepa_raw_nudge != 0.0:
                logger.info(
                    "[Debate] %s SEPA: score=%.2f raw_nudge=%+.3f (applied only "
                    "if directionally aligned with verdict)",
                    symbol,
                    _sepa_score,
                    _sepa_raw_nudge,
                )

        # ── Short-circuit: skip Rounds 2+3 when Round 1 conviction is decisive ────
        # If one researcher is clearly more confident, scoring rounds won't flip the
        # verdict. Saves 2–4 Sonnet calls per high-conviction debate (~30% of runs).
        _r1_delta = result.bull_conviction - result.bear_conviction
        if abs(_r1_delta) >= 0.35:
            _nudged, _applied = _apply_sepa_nudge(_r1_delta, _sepa_raw_nudge)
            result.debate_score = round(_nudged, 4)
            result.sepa_nudge = _applied
            result.verdict = "BULL_WINS" if _r1_delta > 0 else "BEAR_WINS"
            result.scoring_failed = True
            logger.info(
                "[Debate] %s — conviction short-circuit: delta=%.2f ≥ 0.35 → %s "
                "(Rounds 2+3 skipped)",
                symbol,
                _r1_delta,
                result.verdict,
            )
            return result

        # ── Round 2 + 3: adversarial scoring + rebuttals (best-effort) ───────
        try:
            bull_case = _extract_case_text(bull_report, role="bull")
            bear_case = _extract_case_text(bear_report, role="bear")

            logger.info(f"[Debate] {symbol} — Round 2: adversarial scoring")
            (
                bull_score,
                bull_weakest,
                bear_score,
                bear_weakest,
            ) = await self._run_round_2(bull, bear, bull_case, bear_case)

            result.bull_score = bull_score
            result.bear_score = bear_score
            result.bull_weakest_point = bull_weakest
            result.bear_weakest_point = bear_weakest
            result.rounds_completed = 2

            logger.info(
                "[Debate] %s: bull=%.2f bear=%.2f spread=%.2f threshold=%.2f (regime=%s)",
                symbol,
                bull_score,
                bear_score,
                abs(bull_score - bear_score),
                _threshold,
                regime or "default",
            )

            # Detect credit exhaustion first: sentinel takes priority over
            # generic "Scoring unavailable".
            bull_credits_exhausted = bull_weakest == _CREDIT_EXHAUSTED_SENTINEL
            bear_credits_exhausted = bear_weakest == _CREDIT_EXHAUSTED_SENTINEL
            if bull_credits_exhausted or bear_credits_exhausted:
                logger.error(
                    f"[Debate] {symbol} — Anthropic credit balance exhausted. "
                    "Pipeline will use technical fallback."
                )
                result.credits_exhausted = True
                result.scoring_failed = True
                # Zero out scores so net_conviction is unambiguously 0
                result.bull_score = 0
                result.bear_score = 0

            # Detect when scoring calls returned the generic failure default.
            # Dual failure: 5/5 is an artifact — set scoring_failed so pipeline
            # passes control to TraderAgent rather than forcing HOLD.
            # Single failure: one side defaulted to 5, producing an unreliable
            # directional score — also flag as scoring_failed.
            bull_score_failed = bull_weakest == "Scoring unavailable"
            bear_score_failed = bear_weakest == "Scoring unavailable"
            if bull_score_failed or bear_score_failed:
                failure_side = (
                    "both sides"
                    if bull_score_failed and bear_score_failed
                    else ("bull scoring" if bull_score_failed else "bear scoring")
                )
                logger.warning(
                    f"[Debate] {symbol} — {failure_side} _score_argument failed; "
                    "treating as scoring failure (will not force HOLD)"
                )
                result.scoring_failed = True

            logger.info(f"[Debate] {symbol} — Round 3: rebuttals")
            bull_rebuttal, bear_rebuttal = await self._run_round_3(
                bull,
                bear,
                bull_case,
                bear_case,
                bull_weakest,
                bear_weakest,
            )

            result.bull_rebuttal = bull_rebuttal
            result.bear_rebuttal = bear_rebuttal
            result.rounds_completed = 3

            # ── Phase 3.2: Structured Confluence Scoring ──────────────────────
            logger.info(f"[Debate] {symbol} — Evaluating 6-dimension confluence")
            conf_dir, conf_scores = await self._score_confluence(
                bull, bull_case, bear_case, weighted_reports
            )
            result.confluence_scores = conf_scores

            # Count dimensions with strong agreement (>= 0.6)
            strong_agreements = sum(1 for score in conf_scores.values() if score >= 0.6)

            if conf_dir in ("BULL", "BEAR") and strong_agreements >= 4:
                verdict = "BULL_WINS" if conf_dir == "BULL" else "BEAR_WINS"
                # debate_score is used downstream; fake it to pass thresholds
                debate_score = 0.8 if conf_dir == "BULL" else -0.8
                logger.info(
                    f"[Debate] {symbol} confluence PASSED ({strong_agreements}/6 >= 0.6) → {verdict}"
                )
            else:
                verdict = "INCONCLUSIVE"
                debate_score = 0.0
                logger.info(
                    f"[Debate] {symbol} confluence FAILED ({strong_agreements}/6 >= 0.6) → INCONCLUSIVE"
                )

            result.debate_score = debate_score
            result.verdict = verdict
            conviction = abs(debate_score)
            logger.info("[Debate] %s: verdict=%s conviction=%.2f", symbol, verdict, conviction)

            logger.info(
                f"[Debate] {symbol} scored: bull_score={bull_score}/10 "
                f"bear_score={bear_score}/10 debate_score={debate_score:+.2f} "
                f"→ verdict={verdict}"
            )

        except Exception as exc:
            if _is_credit_error(exc):
                logger.error(
                    f"[Debate] {symbol} — Anthropic credit balance exhausted. "
                    "Pipeline will use technical fallback."
                )
                result.credits_exhausted = True
            else:
                logger.warning(
                    f"[Debate] {symbol} — Rounds 2+3 failed ({exc}); "
                    "falling back to 1-round conviction scoring"
                )
            result.scoring_failed = True
            # verdict stays INCONCLUSIVE (safe default for fallback)

        # ── Advisor consultation (Track F, wired 2026-04-10) ─────────────
        # Consult Claude Opus as a tiebreaker when:
        #   • the verdict is INCONCLUSIVE (regardless of scoring_failed), OR
        #   • |debate_score| is within tiebreak tolerance of the regime
        #     threshold (razor-thin BULL_WINS / BEAR_WINS calls).
        # The advisor never raises — graceful no-op when unavailable. On a
        # decisive verdict it overrides the result and nudges debate_score
        # past the threshold so downstream consumers see a directional signal.
        try:
            _advisor = _get_advisor()
            if _advisor is not None and _advisor.is_available():
                _should_consult = (
                    result.verdict == "INCONCLUSIVE"
                    or _advisor.should_consult_debate(result.debate_score, _threshold)
                )
                if _should_consult:
                    bull_case_text = (
                        _extract_case_text(bull_report, role="bull") if bull_report else ""
                    )
                    bear_case_text = (
                        _extract_case_text(bear_report, role="bear") if bear_report else ""
                    )
                    verdict_obj = await _advisor.consult_debate_tiebreak(
                        bull_case=bull_case_text,
                        bear_case=bear_case_text,
                        debate_score=result.debate_score,
                        regime=(regime or "UNKNOWN"),
                        analyst_reports=weighted_reports,
                    )
                    if verdict_obj.consulted and verdict_obj.verdict in {
                        "LONG",
                        "SHORT",
                    }:
                        translated = "BULL_WINS" if verdict_obj.verdict == "LONG" else "BEAR_WINS"
                        logger.info(
                            "[Debate] %s — advisor tiebreak: %s "
                            "(was %s, conf=%.2f) reasoning=%s",
                            symbol,
                            translated,
                            result.verdict,
                            verdict_obj.confidence,
                            (verdict_obj.reasoning or "")[:80],
                        )
                        result.verdict = translated
                        # The advisor produced a decisive call — clear the
                        # failure flag so pipeline.py:662 honors the new
                        # verdict instead of treating it as a fallback.
                        result.scoring_failed = False
                        # Nudge debate_score past the threshold so downstream
                        # consumers see a directional, post-advisor signal.
                        if translated == "BULL_WINS" and result.debate_score < _threshold:
                            result.debate_score = round(_threshold + 0.01, 4)
                        elif translated == "BEAR_WINS" and result.debate_score > -_threshold:
                            result.debate_score = round(-_threshold - 0.01, 4)
        except Exception as _adv_err:  # pragma: no cover — defensive
            logger.warning("[Debate] %s — advisor consult raised: %s", symbol, _adv_err)

        return result

    # ── Round 2: adversarial scoring ─────────────────────────────────────────

    async def _run_round_2(
        self,
        bull: BullResearcherAgent,
        bear: BearResearcherAgent,
        bull_case: str,
        bear_case: str,
    ) -> tuple[int, str, int, str]:
        """
        Each side scores the opponent's argument 1-10 and identifies its
        single weakest point.

        Returns
        -------
        (bull_score, bull_weakest_point, bear_score, bear_weakest_point)
          bull_score:        bear's rating of the bull argument (1-10)
          bull_weakest_point: bear's identified weakness in the bull case
          bear_score:        bull's rating of the bear argument (1-10)
          bear_weakest_point: bull's identified weakness in the bear case
        """
        bear_scores_bull_coro = _score_argument(
            agent=bear,
            opponent_role="BULL",
            opponent_case=bull_case,
        )
        bull_scores_bear_coro = _score_argument(
            agent=bull,
            opponent_role="BEAR",
            opponent_case=bear_case,
        )

        (bull_score, bull_weakest), (bear_score, bear_weakest) = await asyncio.gather(
            bear_scores_bull_coro,
            bull_scores_bear_coro,
        )
        return bull_score, bull_weakest, bear_score, bear_weakest

    # ── Round 3: rebuttals ───────────────────────────────────────────────────

    async def _run_round_3(
        self,
        bull: BullResearcherAgent,
        bear: BearResearcherAgent,
        bull_case: str,
        bear_case: str,
        bull_weakest_point: str,
        bear_weakest_point: str,
    ) -> tuple[str, str]:
        """
        Each side rebuts the weakness identified by the opponent in Round 2.

        Returns
        -------
        (bull_rebuttal, bear_rebuttal)
        """
        bull_rebuttal_coro = _rebuttal(
            agent=bull,
            side="BULL",
            original_case=bull_case,
            criticism=bull_weakest_point,
        )
        bear_rebuttal_coro = _rebuttal(
            agent=bear,
            side="BEAR",
            original_case=bear_case,
            criticism=bear_weakest_point,
        )
        bull_rebuttal, bear_rebuttal = await asyncio.gather(
            bull_rebuttal_coro,
            bear_rebuttal_coro,
        )
        return bull_rebuttal, bear_rebuttal

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_initial_result(
        self,
        symbol: str,
        bull_report: BullReport,
        bear_report: BearReport,
    ) -> DebateResult:
        """Build a DebateResult from Round 1 outputs (legacy conviction scoring)."""
        bull_conv = bull_report.conviction if bull_report else 0.0
        bear_conv = bear_report.conviction if bear_report else 0.0
        combined = bull_conv - bear_conv

        if combined >= self.CONVICTION_THRESHOLD:
            summary = "Bull thesis stronger"
        elif combined <= -self.CONVICTION_THRESHOLD:
            summary = "Bear thesis stronger"
        else:
            summary = "Inconclusive"

        if combined >= self.DIRECTION_THRESHOLD:
            direction = "long"
        elif combined <= -self.DIRECTION_THRESHOLD:
            direction = "short"
        else:
            direction = "flat"

        return DebateResult(
            symbol=symbol,
            timestamp=datetime.now(),
            bull_report=bull_report,
            bear_report=bear_report,
            bull_conviction=bull_conv,
            bear_conviction=bear_conv,
            debate_summary=summary,
            recommended_direction=direction,
            combined_signal=round(combined, 4),
            rounds_completed=1,
        )

    async def _score_confluence(
        self,
        agent: object,
        bull_case: str,
        bear_case: str,
        analyst_reports: dict,
    ) -> tuple[str, dict[str, float]]:
        """
        Evaluate structured confluence across 6 dimensions (Phase 3.2).
        Returns (direction, scores_dict).
        direction: "BULL", "BEAR", or "INCONCLUSIVE"
        scores_dict: {"trend": 0.8, "mean_rev": 0.2, ...} (0-1 scale)

        Routes through *agent*'s own LLM client (via _call_agent_llm, the same
        helper _score_argument/_rebuttal use) instead of a hardcoded direct
        Anthropic client. The direct-client version silently fell back to
        all-zero scores on every Anthropic credit exhaustion, forcing every
        debate to INCONCLUSIVE regardless of the real bull/bear scoring --
        even though the rest of the pipeline had already been migrated onto
        the multi-provider model_router and stayed healthy throughout.
        """
        prompt = (
            "You are a quantitative trading evaluator. Review the bull and bear arguments, "
            "as well as the analyst reports, and score the market context across 6 dimensions. "
            "For each dimension, provide a score from 0.0 to 1.0 representing how strongly it "
            "supports the dominant direction (BULL or BEAR).\n\n"
            f"Bull Case:\n{bull_case}\n\n"
            f"Bear Case:\n{bear_case}\n\n"
            "Respond ONLY with valid JSON in this exact format:\n"
            "{\n"
            '  "direction": "BULL" or "BEAR",\n'
            '  "scores": {\n'
            '    "trend": 0.8,\n'
            '    "mean_rev": 0.6,\n'
            '    "breakout": 0.9,\n'
            '    "volatility": 0.4,\n'
            '    "macro": 0.7,\n'
            '    "sentiment": 0.8\n'
            "  }\n"
            "}"
        )

        try:
            raw = await _call_agent_llm(agent, prompt)
            data = _parse_json_response(raw)

            direction = str(data.get("direction", "INCONCLUSIVE")).upper()
            scores = data.get("scores", {})

            # Ensure all 6 dimensions are present with float values
            clean_scores = {
                dim: float(scores.get(dim, 0.0))
                for dim in ["trend", "mean_rev", "breakout", "volatility", "macro", "sentiment"]
            }

            return direction, clean_scores
        except Exception as exc:
            logger.error("[Debate] _score_confluence failed: %s", exc)
            return "INCONCLUSIVE", dict.fromkeys(["trend", "mean_rev", "breakout", "volatility", "macro", "sentiment"], 0.0)


# ── Module-level LLM helpers (stateless, reuse agent's LLM client) ───────────


def _extract_case_text(report: object, role: str) -> str:
    """Pull a readable summary string out of a bull or bear report."""
    if report is None:
        return f"No {role} argument available."
    # Try the richest narrative fields first
    for attr in (
        "bull_thesis",
        "bear_thesis",
        "summary",
        "thesis",
        "reasoning",
    ):
        value = getattr(report, attr, None)
        if value and isinstance(value, str):
            return value
    # Fallback: serialise to dict and dump the most informative fields
    try:
        d = report.to_dict()
        snippet = {k: v for k, v in d.items() if isinstance(v, str) and len(v) > 10}
        return json.dumps(snippet, indent=2)[:800]
    except Exception:
        return str(report)[:800]


_CREDIT_EXHAUSTED_SENTINEL = "Credits exhausted"

_CREDIT_ERROR_PHRASES = (
    "credit balance too low",
    "insufficient credits",
    "your credit balance",
    "billing",
    "payment required",
    "402",
)


def _is_credit_error(exc: Exception) -> bool:
    """Return True when *exc* indicates Anthropic credit exhaustion (HTTP 400/402)."""
    msg = str(exc).lower()
    return any(phrase in msg for phrase in _CREDIT_ERROR_PHRASES)


def _parse_evidence_fields(text: str) -> tuple[Optional[int], Optional[str]]:
    """
    Extract EVIDENCE_COUNT and EVIDENCE_QUALITY from a scoring response.

    Looks for the pattern:
        SCORE: X/10 | EVIDENCE_COUNT: N | EVIDENCE_QUALITY: low/medium/high

    Returns (evidence_count, evidence_quality) — both None if not found.
    """
    count_match = re.search(r"EVIDENCE_COUNT:\s*(\d+)", text, re.IGNORECASE)
    quality_match = re.search(r"EVIDENCE_QUALITY:\s*(low|medium|high)", text, re.IGNORECASE)
    evidence_count = int(count_match.group(1)) if count_match else None
    evidence_quality = quality_match.group(1).lower() if quality_match else None
    return evidence_count, evidence_quality


def _apply_evidence_weight(
    raw_score: int, evidence_count: Optional[int], evidence_quality: Optional[str]
) -> float:
    """
    Apply evidence-count and quality multipliers to a raw 1-10 score.

    Formula:
        weighted = raw_score × (1 + 0.1 × min(evidence_count, 5)) × quality_mult
    Falls back to raw_score if fields are absent.
    """
    if evidence_count is None and evidence_quality is None:
        return float(raw_score)
    ec = min(evidence_count or 3, 5)
    quality_mult = {"low": 0.9, "medium": 1.0, "high": 1.1}.get(evidence_quality or "medium", 1.0)
    weighted = raw_score * (1 + 0.1 * ec) * quality_mult
    return round(weighted, 4)


async def _score_argument(
    agent: object,
    opponent_role: str,
    opponent_case: str,
) -> tuple[int, str]:
    """
    Ask *agent* to score the opponent's argument and name its weakest point.

    Returns (score: int 1-10, weakest_point: str).

    The prompt asks the LLM to optionally include an evidence metadata line:
        SCORE: X/10 | EVIDENCE_COUNT: N | EVIDENCE_QUALITY: low/medium/high
    When present, the raw score is adjusted by _apply_evidence_weight() before
    being cast to int.  When absent, the raw score is used as-is.

    On credit exhaustion returns (0, _CREDIT_EXHAUSTED_SENTINEL) so the caller
    can detect and propagate credits_exhausted without treating it as a normal
    scoring failure.

    Falls back to (5, "Scoring unavailable") on any other error.
    """
    prompt = (
        f"You are scoring a trading debate. Rate the {opponent_role} argument "
        f"on a scale of 1-10 for logical coherence and identify its single "
        f"weakest point.\n\n"
        f"{opponent_role} argument:\n{opponent_case}\n\n"
        f"When rating, optionally include an evidence metadata line in your response:\n"
        f"SCORE: X/10 | EVIDENCE_COUNT: N | EVIDENCE_QUALITY: low/medium/high\n"
        f"Evidence count = number of distinct data points cited (price levels, indicators, "
        f"macro data, news events). Evidence quality = low (vague statements), medium "
        f"(specific data cited), high (quantified data with source).\n\n"
        f'Respond in JSON only: {{"score": <int 1-10>, "weakest_point": "<one sentence>"}}'
    )
    try:
        raw: str = await _call_agent_llm(agent, prompt)
        # Parse evidence metadata from the raw response BEFORE JSON extraction
        evidence_count, evidence_quality = _parse_evidence_fields(raw)
        data = _parse_json_response(raw)
        raw_score = int(data.get("score", 5))
        raw_score = max(1, min(10, raw_score))
        # Apply evidence weighting (no-op when fields are absent)
        weighted = _apply_evidence_weight(raw_score, evidence_count, evidence_quality)
        # Clamp to [1, 10] and convert back to int for downstream compatibility
        score = max(1, min(10, int(round(weighted))))
        if evidence_count is not None or evidence_quality is not None:
            logger.debug(
                "[Debate] _score_argument (%s): raw=%d evidence_count=%s quality=%s weighted=%.2f→%d",
                opponent_role,
                raw_score,
                evidence_count,
                evidence_quality,
                weighted,
                score,
            )
        weakest = str(data.get("weakest_point", "Not identified"))
        return score, weakest
    except Exception as exc:
        if _is_credit_error(exc):
            logger.error(
                f"[Debate] _score_argument ({opponent_role}) — "
                "Anthropic credit balance exhausted. "
                "Returning credit-exhausted sentinel."
            )
            return 0, _CREDIT_EXHAUSTED_SENTINEL
        logger.warning(f"[Debate] _score_argument failed ({exc}); defaulting to 5")
        return 5, "Scoring unavailable"


async def _rebuttal(
    agent: object,
    side: str,
    original_case: str,
    criticism: str,
) -> str:
    """
    Ask *agent* to rebut the criticism of its position.

    Returns a 2-3 sentence rebuttal string.
    Falls back to an empty string on any error.
    """
    prompt = (
        f"You are the {side} side in a trading debate. "
        f"Rebut this criticism of your argument:\n"
        f"Criticism: {criticism}\n"
        f"Your original argument: {original_case}\n\n"
        f"Respond with 2-3 sentences defending your position."
    )
    try:
        return await _call_agent_llm(agent, prompt)
    except Exception as exc:
        if _is_credit_error(exc):
            logger.error(f"[Debate] _rebuttal ({side}) — " "Anthropic credit balance exhausted.")
            return _CREDIT_EXHAUSTED_SENTINEL
        logger.warning(f"[Debate] _rebuttal ({side}) failed ({exc})")
        return ""


async def _call_agent_llm(agent: object, prompt: str) -> str:
    """
    Call the agent's underlying LLM client with *prompt* and return raw text.

    Supports agents that expose:
    - agent._client (Anthropic async client)
    - agent.client
    - agent._call_llm(prompt) coroutine
    - agent.call_llm(prompt) coroutine
    """
    # Strategy 1: _call_llm / call_llm coroutine
    for method_name in ("_call_llm", "call_llm"):
        method = getattr(agent, method_name, None)
        if callable(method):
            result = method(prompt)
            if asyncio.iscoroutine(result):
                return await result
            return str(result)

    # Strategy 2: direct Anthropic client
    client = getattr(agent, "_client", None) or getattr(agent, "client", None)
    if client is not None:
        model = getattr(agent, "model", "claude-haiku-4-5")
        response = await client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""

    raise RuntimeError(
        f"Agent {type(agent).__name__} exposes no callable LLM interface "
        "(_call_llm, call_llm, _client, client)."
    )


def _ic_weighted_signal(signal: float, agent_name: str, ic_scores: dict) -> float:
    """
    Apply IC (Information Coefficient) weight to an analyst signal.

    Formula (Track F1 — Fundamental Law of Active Management):
        w(i) = IC(i) / 1.0   (simplified: η=1, σ assumed=1)
        adjusted_signal = signal × (1 + IC(i))

    IC(i) = historical_accuracy(i) - 0.5:
        IC = 0.0  → random (no boost)
        IC = 0.2  → 70% accurate analyst → 1.2× multiplier
        IC = 0.5  → perfect analyst → 1.5× multiplier

    When no IC data is available (IC ≤ 0) the raw signal is returned unchanged.
    """
    ic = ic_scores.get(agent_name, 0.0)
    if ic <= 0:
        return signal  # No IC data — use raw signal
    return signal * (1.0 + ic)  # Boost proportional to IC quality


def _brier_blended_signal(
    signal: float,
    agent_name: str,
    ic_scores: dict,
    brier_weights: dict,
    alpha: float,
) -> float:
    """
    Blend IC-based multiplier with Brier-calibration weight (Novel #2).

    Formula:
        ic_mult             = 1 + max(0, IC(agent))
        brier_mult_centered = brier_weights[agent] * N    # neutral (1/N) → 1.0
        final_mult          = alpha * ic_mult + (1 - alpha) * brier_mult_centered

    Rationale:
        * Normalized inverse-Brier weights sum to 1.0 across N agents, so the
          neutral per-agent weight is 1/N. Multiplying by N re-centers on 1.0
          so a well-calibrated agent gets >1.0 and a confidently-wrong agent
          gets <1.0 — matching the `ic_mult` scale.
        * alpha=1.0 exactly preserves the pure-IC path (regression-safe).
        * alpha=0.0 is pure Brier re-weighting.
        * Default alpha=0.5 starts symmetric.

    Cold-start: when an agent has < min_trades=5 outcomes, BrierCalibrationTracker
    returns the neutral sentinel (0.25), which normalizes to the uniform 1/N
    weight — so `brier_mult_centered == 1.0` and the blend collapses to
    `alpha * (1 + IC) + (1 - alpha)` ≈ IC behavior. No destabilization.
    """
    ic = max(0.0, ic_scores.get(agent_name, 0.0))
    ic_mult = 1.0 + ic

    n = max(1, len(brier_weights))
    neutral = 1.0 / n
    brier_w = brier_weights.get(agent_name, neutral)
    brier_mult_centered = brier_w * n

    return signal * (alpha * ic_mult + (1.0 - alpha) * brier_mult_centered)


def _parse_json_response(raw: str) -> dict:
    """Extract the first JSON object from *raw*, tolerating markdown fences."""
    raw = raw.strip()
    # Strip ```json ... ``` fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(line for line in lines if not line.startswith("```")).strip()
    # Find the first '{' ... '}' block
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in response: {raw[:200]!r}")
    return json.loads(raw[start:end])
