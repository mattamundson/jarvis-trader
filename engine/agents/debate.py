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
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .bear_researcher import BearReport, BearResearcherAgent
from .bull_researcher import BullReport, BullResearcherAgent

logger = logging.getLogger(__name__)

__all__ = ["DebateResult", "DebateOrchestrator"]

# Scoring verdict thresholds
_VERDICT_THRESHOLD = 0.10


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

        Returns
        -------
        DebateResult
            Full 3-round result including debate_score and verdict.
        """
        logger.info(f"[Debate] {symbol} — Round 1: parallel opening statements")
        bull_report, bear_report = await asyncio.gather(
            bull.analyze(symbol, analyst_reports),
            bear.analyze(symbol, analyst_reports),
        )

        result = self._build_initial_result(symbol, bull_report, bear_report)

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

            # ── Score ─────────────────────────────────────────────────────────
            # bear_score_of_bull: how harshly bear rated bull (low = weak bull)
            # bull_score_of_bear: how harshly bull rated bear (low = weak bear)
            # A high bear_score_of_bull with low bull_score_of_bear → bull wins
            debate_score = round((bear_score - bull_score) / 10, 4)
            result.debate_score = debate_score

            if debate_score >= _VERDICT_THRESHOLD:
                verdict = "BULL_WINS"
            elif debate_score <= -_VERDICT_THRESHOLD:
                verdict = "BEAR_WINS"
            else:
                # Tie-break: score is in dead zone — check conviction asymmetry
                _CONVICTION_TIE_BREAK = 0.35  # require 35% asymmetry to break tie
                bear_conv = result.bear_conviction
                bull_conv = result.bull_conviction
                conviction_diff = bear_conv - bull_conv  # positive = bear dominant
                if conviction_diff >= _CONVICTION_TIE_BREAK:
                    verdict = "BEAR_WINS"
                    result.scoring_failed = True
                    # Nudge debate_score just past the bear threshold so downstream
                    # consumers see a directional signal rather than a neutral 0.0.
                    result.debate_score = -0.10
                    logger.info(
                        f"[Debate] {symbol} tie broken by conviction: "
                        f"bear {bear_conv:.2f} vs bull {bull_conv:.2f} → BEAR_WINS "
                        f"(debate_score overridden to -0.10)"
                    )
                elif -conviction_diff >= _CONVICTION_TIE_BREAK:
                    verdict = "BULL_WINS"
                    result.scoring_failed = True
                    # Nudge debate_score just past the bull threshold so downstream
                    # consumers see a directional signal rather than a neutral 0.0.
                    result.debate_score = 0.10
                    logger.info(
                        f"[Debate] {symbol} tie broken by conviction: "
                        f"bull {bull_conv:.2f} vs bear {bear_conv:.2f} → BULL_WINS "
                        f"(debate_score overridden to +0.10)"
                    )
                else:
                    verdict = "INCONCLUSIVE"

            result.verdict = verdict

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
        snippet = {
            k: v
            for k, v in d.items()
            if isinstance(v, str) and len(v) > 10
        }
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


async def _score_argument(
    agent: object,
    opponent_role: str,
    opponent_case: str,
) -> tuple[int, str]:
    """
    Ask *agent* to score the opponent's argument and name its weakest point.

    Returns (score: int 1-10, weakest_point: str).

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
        f'Respond in JSON only: {{"score": <int 1-10>, "weakest_point": "<one sentence>"}}'
    )
    try:
        raw: str = await _call_agent_llm(agent, prompt)
        data = _parse_json_response(raw)
        score = int(data.get("score", 5))
        score = max(1, min(10, score))
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
            logger.error(
                f"[Debate] _rebuttal ({side}) — "
                "Anthropic credit balance exhausted."
            )
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


def _parse_json_response(raw: str) -> dict:
    """Extract the first JSON object from *raw*, tolerating markdown fences."""
    raw = raw.strip()
    # Strip ```json ... ``` fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()
    # Find the first '{' ... '}' block
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in response: {raw[:200]!r}")
    return json.loads(raw[start:end])
