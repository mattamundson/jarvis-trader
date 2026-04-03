"""
JARVIS TRADER — Debate Orchestrator
=====================================
Runs a structured multi-round bull/bear debate between BullResearcherAgent and
BearResearcherAgent and synthesises the outcome into a single trading direction.

Round structure
---------------
Round 1  — Initial positions (parallel): both agents independently analyse the
           same analyst_reports and produce their opening arguments.
Round 2+ — Rebuttal rounds (sequential): each agent receives the opponent's
           previous output and is asked to respond. Currently the agents reuse
           their standard analyze() method with the opponent's report injected
           as an additional "opponent_position" key so that the existing LLM
           system prompts naturally respond to the challenge.

The final DebateResult contains the raw reports, a computed combined_signal
(-1 to +1), a debate_summary label, and a recommended direction.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .bear_researcher import BearReport, BearResearcherAgent
from .bull_researcher import BullReport, BullResearcherAgent

logger = logging.getLogger(__name__)

__all__ = ["DebateResult", "DebateOrchestrator"]


@dataclass
class DebateResult:
    """Structured outcome of the bull/bear debate for a single symbol."""

    symbol: str
    timestamp: datetime

    # Raw agent outputs
    bull_report: Optional[BullReport] = None
    bear_report: Optional[BearReport] = None

    # Conviction scores extracted for convenience
    bull_conviction: float = 0.0
    bear_conviction: float = 0.0

    # Narrative summary of which side "won" the debate
    debate_summary: str = (
        "Inconclusive"  # "Bull thesis stronger" | "Bear thesis stronger" | "Inconclusive"
    )

    # Final trading direction
    recommended_direction: str = "flat"  # "long" | "short" | "flat"

    # Signed signal: (bull_conviction - bear_conviction), range -1 to +1
    combined_signal: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "bull_report": self.bull_report.to_dict() if self.bull_report else None,
            "bear_report": self.bear_report.to_dict() if self.bear_report else None,
            "bull_conviction": self.bull_conviction,
            "bear_conviction": self.bear_conviction,
            "debate_summary": self.debate_summary,
            "recommended_direction": self.recommended_direction,
            "combined_signal": self.combined_signal,
        }


class DebateOrchestrator:
    """
    Orchestrates a multi-round adversarial debate between a BullResearcherAgent
    and a BearResearcherAgent and resolves the outcome.

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
            symbol="AAPL",
            analyst_reports={"technical": tech_report, "news": news_report},
            bull=bull,
            bear=bear,
            rounds=2,
        )
        print(result.recommended_direction)  # "long" | "short" | "flat"
    """

    # Minimum conviction gap to declare a winner rather than "Inconclusive"
    CONVICTION_THRESHOLD = 0.15

    # Minimum absolute combined_signal to recommend long/short vs flat
    DIRECTION_THRESHOLD = 0.10

    async def run_debate(
        self,
        symbol: str,
        analyst_reports: dict,
        bull: BullResearcherAgent,
        bear: BearResearcherAgent,
        rounds: int = 1,
    ) -> DebateResult:
        """
        Run *rounds* rounds of bull/bear debate for *symbol*.

        Round 1 is always parallel (both agents analyse the same reports).
        Subsequent rounds are sequential: each agent receives a copy of
        analyst_reports augmented with the opponent's previous position so
        the LLM can naturally construct a rebuttal.

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
            Number of debate rounds. 1 = opening statements only.
            2+ = opening + rebuttal rounds.

        Returns
        -------
        DebateResult
            Synthesised outcome with direction, signal, and raw reports.
        """
        rounds = max(1, rounds)

        # ── Round 1: parallel opening statements ─────────────────────────────
        logger.info(f"[Debate] {symbol} — Round 1 opening statements (parallel)")
        bull_report, bear_report = await asyncio.gather(
            bull.analyze(symbol, analyst_reports),
            bear.analyze(symbol, analyst_reports),
        )

        # ── Round 2+: sequential rebuttal rounds ─────────────────────────────
        for round_num in range(2, rounds + 1):
            logger.info(f"[Debate] {symbol} — Round {round_num} rebuttals")

            # Bull responds to the bear's previous argument
            bull_rebuttal_reports = dict(analyst_reports)
            bull_rebuttal_reports["opponent_position"] = {
                "role": "bear",
                "bear_thesis": bear_report.bear_thesis,
                "key_risks": bear_report.key_risks,
                "conviction": bear_report.conviction,
                "counterargument_response": bear_report.counterargument_response,
            }
            bull_report = await bull.analyze(symbol, bull_rebuttal_reports)

            # Bear responds to the bull's updated argument
            bear_rebuttal_reports = dict(analyst_reports)
            bear_rebuttal_reports["opponent_position"] = {
                "role": "bull",
                "bull_thesis": bull_report.bull_thesis,
                "key_evidence": bull_report.key_evidence,
                "conviction": bull_report.conviction,
                "counterargument_response": bull_report.counterargument_response,
            }
            bear_report = await bear.analyze(symbol, bear_rebuttal_reports)

        # ── Resolve outcome ───────────────────────────────────────────────────
        result = self._resolve(symbol, bull_report, bear_report)
        logger.info(
            f"[Debate] {symbol} resolved: {result.debate_summary} "
            f"(bull={result.bull_conviction:.2f}, bear={result.bear_conviction:.2f}, "
            f"signal={result.combined_signal:+.2f}) → {result.recommended_direction}"
        )
        return result

    # ── Internal resolution logic ─────────────────────────────────────────────

    def _resolve(
        self,
        symbol: str,
        bull_report: BullReport,
        bear_report: BearReport,
    ) -> DebateResult:
        """
        Compute the combined_signal, debate_summary, and recommended_direction
        from the final conviction scores of both agents.

        combined_signal = bull_conviction - bear_conviction  (range: -1 to +1)

        Summary labels:
          Bull conviction beats bear by >= CONVICTION_THRESHOLD  → "Bull thesis stronger"
          Bear conviction beats bull by >= CONVICTION_THRESHOLD  → "Bear thesis stronger"
          Otherwise                                              → "Inconclusive"

        Direction:
          combined_signal >= +DIRECTION_THRESHOLD  → "long"
          combined_signal <= -DIRECTION_THRESHOLD  → "short"
          Otherwise                                → "flat"
        """
        bull_conv = bull_report.conviction if bull_report else 0.0
        bear_conv = bear_report.conviction if bear_report else 0.0

        combined = bull_conv - bear_conv

        gap = combined  # positive = bulls ahead, negative = bears ahead

        if gap >= self.CONVICTION_THRESHOLD:
            summary = "Bull thesis stronger"
        elif gap <= -self.CONVICTION_THRESHOLD:
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
        )
