"""
JARVIS TRADER — Claude Advisor Strategy Client
================================================
Implements Anthropic's Advisor Strategy pattern (released Apr 9, 2026, beta).

Pattern overview
----------------
Fast executor agents (Sonnet/Haiku) call Opus as a consulting advisor when they
hit a hard decision mid-run. The main agent remains on the cheap model; only the
narrow "hard case" gets escalated. This gives +2.7pp SWE-bench accuracy with an
11.9% cost reduction versus running Opus throughout.

Source: https://x.com/claudeai/status/2042308622181339453
API:    Messages API beta (Apr 9, 2026) — "advisor tool"

JARVIS integration points
-------------------------
1. DebateOrchestrator — when abs(debate_score) is within ±0.05 of the regime
   threshold, the debate is INCONCLUSIVE by a razor-thin margin. Consult Opus
   for a tiebreak verdict instead of forcing HOLD.
2. TraderAgent — when pre-execution confidence < 0.5, the trade is marginal.
   Consult Opus for entry/stop/target refinement before committing.
3. Pipeline — when 2+ Stage 1 agents returned errors, consult Opus for a
   degraded-mode best-available decision.

<<<<<<< HEAD
The client is optional — pipelines gracefully no-op when JarvisLLMClient or
ANTHROPIC_API_KEY is unavailable. It never raises on failure; the original
decision is returned unchanged so the pipeline stays deterministic.
=======
The client is optional — pipelines gracefully no-op when JarvisLLMClient is
unavailable. It never raises on failure; the original decision is returned
unchanged so the pipeline stays deterministic.
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
"""

from __future__ import annotations

import logging
<<<<<<< HEAD
import os
=======
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = ["AdvisorClient", "AdvisorVerdict", "AdvisorRefinement"]


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------


@dataclass
class AdvisorVerdict:
    """Opus advisor's tiebreak verdict on an inconclusive debate."""

    verdict: str  # "LONG" | "SHORT" | "HOLD"
    confidence: float  # 0.0 – 1.0
    reasoning: str
    source: str = "opus_advisor"  # "opus_advisor" | "fallback"
    consulted: bool = False  # True if we actually called the LLM


@dataclass
class AdvisorRefinement:
    """Opus advisor's refinement of a low-confidence trade setup."""

    entry: float
    stop: float
    target: float
    confidence: float
    notes: str
    source: str = "opus_advisor"
    consulted: bool = False


# ---------------------------------------------------------------------------
# AdvisorClient
# ---------------------------------------------------------------------------


class AdvisorClient:
    """
    Opus-as-advisor client for high-stakes mid-pipeline escalation.

    Usage:
        advisor = AdvisorClient()  # lazy-loads JarvisLLMClient if available

        # Debate tiebreak
        if advisor.should_consult_debate(debate_score, regime_threshold):
            result = await advisor.consult_debate_tiebreak(
                bull_case=bull_text, bear_case=bear_text,
                debate_score=0.19, regime="TRENDING_BULL",
                analyst_reports=reports,
            )
            if result.consulted and result.verdict != "HOLD":
                final_verdict = result.verdict

        # Trader refinement
        if advisor.should_consult_trader(confidence=0.42):
            refined = await advisor.consult_trader_refinement(...)
    """

    # Escalate when debate score is within this tolerance of the verdict threshold.
    TIEBREAK_TOLERANCE = 0.05
    # Escalate when trader confidence is below this value.
    LOW_CONFIDENCE_THRESHOLD = 0.5
<<<<<<< HEAD
    # Advisor always uses the most capable model.
=======
    # Default premium fallback when no real provider-aware client is available.
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    ADVISOR_MODEL = "claude-opus-4-7"
    # Cap advisor response to contain cost; verdicts/refinements are short.
    ADVISOR_MAX_TOKENS = 600
    # Deterministic-ish — advisor should not free-associate.
    ADVISOR_TEMPERATURE = 0.2

    def __init__(self, llm_client: Optional[Any] = None):
        """
        Initialize the advisor client.

        Args:
            llm_client: Optional JarvisLLMClient instance. If None, the client
<<<<<<< HEAD
                tries to lazy-load one using ANTHROPIC_API_KEY from the env.
                If no client can be constructed, the advisor no-ops gracefully.
=======
                tries to lazy-load one from the active provider config. If no
                client can be constructed, the advisor no-ops gracefully.
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
        """
        self.llm = llm_client
        if self.llm is None:
            self.llm = self._try_lazy_load_llm()

    @staticmethod
    def _try_lazy_load_llm() -> Optional[Any]:
<<<<<<< HEAD
        """Attempt to construct a JarvisLLMClient. Never raises."""
=======
        """Attempt to construct a JarvisLLMClient from the active provider config. Never raises."""
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
        try:
            # Import shape matches engine/llm/client.py
            from llm.client import JarvisLLMClient  # type: ignore
        except Exception:
            try:
                from engine.llm.client import JarvisLLMClient  # type: ignore
            except Exception as e:
                logger.info(
                    "AdvisorClient: JarvisLLMClient not importable (%s); "
                    "advisor will no-op.",
                    e,
                )
                return None

<<<<<<< HEAD
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.info(
                "AdvisorClient: ANTHROPIC_API_KEY not set; advisor will no-op."
            )
            return None

        try:
            return JarvisLLMClient(api_key=api_key)
=======
        try:
            return JarvisLLMClient()
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
        except Exception as e:
            logger.warning(
                "AdvisorClient: failed to construct JarvisLLMClient (%s); "
                "advisor will no-op.",
                e,
            )
            return None

    # ------------------------------------------------------------------
    # Escalation gates — cheap boolean checks pipelines use before awaiting
    # ------------------------------------------------------------------

    def should_consult_debate(
        self,
        debate_score: float,
        threshold: float,
        tolerance: Optional[float] = None,
    ) -> bool:
        """
        Return True if the debate score is within tiebreak tolerance of the
        verdict threshold in either direction.

        Example:
            threshold=0.20, tolerance=0.05 → consult if |score| in [0.15, 0.25].
        """
        tol = self.TIEBREAK_TOLERANCE if tolerance is None else tolerance
        return abs(abs(debate_score) - threshold) <= tol

    def should_consult_trader(
        self,
        confidence: float,
        floor: Optional[float] = None,
    ) -> bool:
        """Return True if trader confidence is below the low-confidence floor."""
        f = self.LOW_CONFIDENCE_THRESHOLD if floor is None else floor
        return confidence < f

    def is_available(self) -> bool:
        """Whether the advisor can actually make LLM calls right now."""
        return self.llm is not None

<<<<<<< HEAD
=======
    @staticmethod
    def _resolve_model(llm_client: Any) -> str:
        """Prefer the active client's provider-aware default model when available."""
        try:
            from llm.client import resolve_agent_model  # type: ignore
        except Exception:
            try:
                from engine.llm.client import resolve_agent_model  # type: ignore
            except Exception:
                return AdvisorClient.ADVISOR_MODEL
        return resolve_agent_model(llm_client, AdvisorClient.ADVISOR_MODEL)

>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    # ------------------------------------------------------------------
    # Consultations — async, graceful fallback on any error
    # ------------------------------------------------------------------

    async def consult_debate_tiebreak(
        self,
        bull_case: str,
        bear_case: str,
        debate_score: float,
        regime: str,
        analyst_reports: Dict[str, Any],
    ) -> AdvisorVerdict:
        """
        Ask Opus for a tiebreak verdict on an inconclusive debate.

        Returns an AdvisorVerdict. On any failure (no client, API error, parse
        failure), returns a HOLD verdict with consulted=False so callers can
        fall back to their own logic without special-casing exceptions.
        """
        if self.llm is None:
            return AdvisorVerdict(
                verdict="HOLD",
                confidence=0.0,
                reasoning="advisor unavailable",
                source="fallback",
                consulted=False,
            )

        system = (
            "You are a senior trading advisor with 20+ years of futures experience. "
            "You are being consulted on an inconclusive bull/bear debate. "
            "Your job is to break the tie with decisive, evidence-based judgment. "
            "You MUST output exactly one line in this format:\n"
            "VERDICT: LONG|SHORT|HOLD | CONFIDENCE: 0.0-1.0 | REASONING: <one sentence>\n"
            "Do not output anything else."
        )

        user_prompt = self._format_debate_prompt(
            bull_case=bull_case,
            bear_case=bear_case,
            debate_score=debate_score,
            regime=regime,
            analyst_reports=analyst_reports,
        )

        try:
            result = await self.llm.call(
<<<<<<< HEAD
                model=self.ADVISOR_MODEL,
=======
                model=self._resolve_model(self.llm),
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=self.ADVISOR_MAX_TOKENS,
                temperature=self.ADVISOR_TEMPERATURE,
                agent_name="advisor_debate",
            )
        except Exception as e:
            logger.warning("AdvisorClient debate consult raised: %s", e)
            return AdvisorVerdict(
                verdict="HOLD",
                confidence=0.0,
                reasoning=f"advisor error: {e}",
                source="fallback",
                consulted=False,
            )

        if not getattr(result, "success", False):
            return AdvisorVerdict(
                verdict="HOLD",
                confidence=0.0,
                reasoning=f"advisor call failed: {getattr(result, 'error', 'unknown')}",
                source="fallback",
                consulted=False,
            )

        parsed = self._parse_verdict(result.content)
        parsed.consulted = True
        return parsed

    async def consult_trader_refinement(
        self,
        direction: str,
        entry: float,
        stop: float,
        target: float,
        confidence: float,
        regime: str,
        notes: str = "",
    ) -> AdvisorRefinement:
        """
        Ask Opus to refine the entry/stop/target on a low-confidence setup.

        Returns an AdvisorRefinement. On any failure, the original values are
        echoed back with consulted=False.
        """
        if self.llm is None:
            return AdvisorRefinement(
                entry=entry,
                stop=stop,
                target=target,
                confidence=confidence,
                notes="advisor unavailable",
                source="fallback",
                consulted=False,
            )

        system = (
            "You are a senior trading advisor. A pipeline produced a low-confidence "
            "setup and is asking you to refine the entry/stop/target. "
            "Keep the direction. Output EXACTLY one line in this format:\n"
            "ENTRY: <float> | STOP: <float> | TARGET: <float> | "
            "CONFIDENCE: 0.0-1.0 | NOTES: <one short sentence>\n"
            "Do not output anything else."
        )

        user_prompt = (
            f"DIRECTION: {direction}\n"
            f"CURRENT ENTRY: {entry}\n"
            f"CURRENT STOP: {stop}\n"
            f"CURRENT TARGET: {target}\n"
            f"CURRENT CONFIDENCE: {confidence:.2f}\n"
            f"REGIME: {regime}\n"
            f"NOTES: {notes or 'none'}\n"
        )

        try:
            result = await self.llm.call(
<<<<<<< HEAD
                model=self.ADVISOR_MODEL,
=======
                model=self._resolve_model(self.llm),
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=self.ADVISOR_MAX_TOKENS,
                temperature=self.ADVISOR_TEMPERATURE,
                agent_name="advisor_trader",
            )
        except Exception as e:
            logger.warning("AdvisorClient trader consult raised: %s", e)
            return AdvisorRefinement(
                entry=entry,
                stop=stop,
                target=target,
                confidence=confidence,
                notes=f"advisor error: {e}",
                source="fallback",
                consulted=False,
            )

        if not getattr(result, "success", False):
            return AdvisorRefinement(
                entry=entry,
                stop=stop,
                target=target,
                confidence=confidence,
                notes=f"advisor call failed: {getattr(result, 'error', 'unknown')}",
                source="fallback",
                consulted=False,
            )

        refined = self._parse_refinement(
            result.content,
            fallback_entry=entry,
            fallback_stop=stop,
            fallback_target=target,
            fallback_confidence=confidence,
        )
        refined.consulted = True
        return refined

    # ------------------------------------------------------------------
    # Prompt formatting helpers
    # ------------------------------------------------------------------

    def _format_debate_prompt(
        self,
        bull_case: str,
        bear_case: str,
        debate_score: float,
        regime: str,
        analyst_reports: Dict[str, Any],
    ) -> str:
        """Compact prompt formatter — keeps advisor tokens cheap."""
        signals = []
        for agent, report in (analyst_reports or {}).items():
            if isinstance(report, dict):
                sig = report.get("signal")
                if sig is not None:
                    signals.append(f"- {agent}: signal={sig}")
                else:
                    bias = report.get("bias") or report.get("verdict") or ""
                    if bias:
                        signals.append(f"- {agent}: {bias}")
            else:
                snippet = str(report)[:120]
                signals.append(f"- {agent}: {snippet}")

        signals_str = "\n".join(signals) if signals else "(none)"
        # Truncate cases to keep advisor calls cheap.
        bull_trim = (bull_case or "")[:1500]
        bear_trim = (bear_case or "")[:1500]

        return (
            f"REGIME: {regime}\n"
            f"DEBATE SCORE: {debate_score:.3f} (within tiebreak tolerance)\n\n"
            f"ANALYST SIGNALS:\n{signals_str}\n\n"
            f"BULL CASE:\n{bull_trim}\n\n"
            f"BEAR CASE:\n{bear_trim}\n\n"
            f"Decide."
        )

    # ------------------------------------------------------------------
    # Response parsers — forgiving, always return a valid object
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_verdict(response: str) -> AdvisorVerdict:
        """
        Parse a VERDICT/CONFIDENCE/REASONING line from the advisor response.

        Accepts minor formatting drift — scans each line, extracts fields by
        prefix, and falls back to HOLD on parse failure.
        """
        verdict = "HOLD"
        confidence = 0.0
        reasoning = ""

        try:
            for line in (response or "").splitlines():
                if "VERDICT:" not in line.upper():
                    continue
                parts = [p.strip() for p in line.split("|")]
                for p in parts:
                    up = p.upper()
                    if up.startswith("VERDICT:"):
                        raw = p.split(":", 1)[1].strip().upper()
                        if raw in {"LONG", "SHORT", "HOLD"}:
                            verdict = raw
                    elif up.startswith("CONFIDENCE:"):
                        try:
                            confidence = float(p.split(":", 1)[1].strip())
                            confidence = max(0.0, min(1.0, confidence))
                        except ValueError:
                            pass
                    elif up.startswith("REASONING:"):
                        reasoning = p.split(":", 1)[1].strip()
                break
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("verdict parse failed: %s", e)

        return AdvisorVerdict(
            verdict=verdict,
            confidence=confidence,
            reasoning=reasoning,
        )

    @staticmethod
    def _parse_refinement(
        response: str,
        fallback_entry: float,
        fallback_stop: float,
        fallback_target: float,
        fallback_confidence: float,
    ) -> AdvisorRefinement:
        """Parse ENTRY/STOP/TARGET/CONFIDENCE/NOTES from the advisor response."""
        entry = fallback_entry
        stop = fallback_stop
        target = fallback_target
        confidence = fallback_confidence
        notes = ""

        def _grab_float(part: str) -> Optional[float]:
            m = re.search(r"-?\d+(?:\.\d+)?", part)
            if not m:
                return None
            try:
                return float(m.group(0))
            except ValueError:
                return None

        try:
            for line in (response or "").splitlines():
                up = line.upper()
                if "ENTRY:" not in up or "STOP:" not in up:
                    continue
                parts = [p.strip() for p in line.split("|")]
                for p in parts:
                    upper = p.upper()
                    if upper.startswith("ENTRY:"):
                        v = _grab_float(p)
                        if v is not None:
                            entry = v
                    elif upper.startswith("STOP:"):
                        v = _grab_float(p)
                        if v is not None:
                            stop = v
                    elif upper.startswith("TARGET:"):
                        v = _grab_float(p)
                        if v is not None:
                            target = v
                    elif upper.startswith("CONFIDENCE:"):
                        v = _grab_float(p)
                        if v is not None:
                            confidence = max(0.0, min(1.0, v))
                    elif upper.startswith("NOTES:"):
                        notes = p.split(":", 1)[1].strip()
                break
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("refinement parse failed: %s", e)

        return AdvisorRefinement(
            entry=entry,
            stop=stop,
            target=target,
            confidence=confidence,
            notes=notes,
        )
