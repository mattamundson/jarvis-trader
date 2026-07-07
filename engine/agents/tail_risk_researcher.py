"""
JARVIS TRADER — Tail-Risk Researcher Agent (Novel #1)
======================================================
Adversarial agent that scores the proposed trade through a Taleb-style
tail-risk lens. It does not care about the bull or bear case — it cares
about *what happens if you are wrong*.

It produces:
  * tail_risk_score    — 0.0 (symmetric/safe) → 1.0 (asymmetric/dangerous)
  * size_multiplier    — 0.0–1.0 sizing recommendation (1.0 = no change)
  * veto               — True when the tail is unacceptable regardless of edge
  * worst_case_drawdown — implied $ loss if stop is gapped (estimate)
  * key_risks          — 3–5 specific tail scenarios for this symbol/setup
  * recommendation     — short prose: PROCEED / SIZE_DOWN / VETO

Design intent (sourced from `docs/digest/strategy-synthesis.md` Novel #1,
which sources `virattt/ai-hedge-fund` Taleb persona):

  > Add a Nassim-Taleb-style "tail risk / asymmetric-payoff" researcher
  > agent that explicitly scores kurtosis, worst-case slippage, and
  > gap-risk on the proposed trade. Rejects trades where max-adverse-
  > excursion implied by the stop is asymmetric against us (e.g. MCL
  > news gaps through stop).

Wiring (deferred to a separate gated change):
  * Called in parallel with bull/bear inside `engine/agents/debate.py`
    `_run_researchers` block.
  * `size_multiplier` consumed as a DOWNGRADE factor in
    `engine/agents/trader.py` sizing logic (multiplied into the existing
    0.5x–1.5x bounds — never UPGRADES sizing).
  * `veto` short-circuits trader.py to HOLD without affecting the
    bull/bear debate verdict.

Model: Claude Sonnet 4.6 (same as bull/bear)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from utils.llm_json import LLMJsonError, parse_llm_json

logger = logging.getLogger(__name__)

__all__ = ["TailRiskReport", "TailRiskResearcherAgent"]


@dataclass
class TailRiskReport:
    """Structured tail-risk verdict produced by the agent."""

    symbol: str
    timestamp: datetime

    tail_risk_score: float = 0.0
    size_multiplier: float = 1.0
    veto: bool = False
    worst_case_drawdown_usd: Optional[float] = None
    key_risks: list[str] = field(default_factory=list)
    recommendation: str = ""
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "tail_risk_score": self.tail_risk_score,
            "size_multiplier": self.size_multiplier,
            "veto": self.veto,
            "worst_case_drawdown_usd": self.worst_case_drawdown_usd,
            "key_risks": self.key_risks,
            "recommendation": self.recommendation,
            "reasoning": self.reasoning,
        }


class TailRiskResearcherAgent:
    """
    Scores a proposed trade through a tail-risk lens. Pairs with bull/bear
    researchers in DebateOrchestrator but operates orthogonally — its veto
    can override a bull/bear consensus when the implied left-tail is
    unacceptable.

    The agent assumes the system has already decided IT WANTS to take the
    trade. Its job is to ask: *what if you are wrong?*
    """

    SYSTEM_PROMPT = (
        "You are the Tail-Risk Researcher, modelled on Nassim Taleb. Your job "
        "is NOT to evaluate whether the trade will work — bull and bear "
        "researchers handle that. Your job is to score what happens when the "
        "trade fails in the worst plausible way: gap-throughs, news bombs, "
        "regime breaks, illiquidity events, exchange halts.\n\n"
        "Score the trade's PAYOFF ASYMMETRY:\n"
        "  - Symmetric (loss ≈ gain at the stop): tail_risk_score 0.0–0.3\n"
        "  - Mildly asymmetric (moderate gap risk, news-event windows): 0.3–0.6\n"
        "  - Sharply asymmetric (illiquid stop, headline window, OPEX week): 0.6–0.9\n"
        "  - Catastrophic asymmetry (stop is decorative; no realistic exit): 0.9–1.0\n\n"
        "size_multiplier: 1.0 = no change; 0.5–0.9 = downsize; 0.0 = veto\n"
        "veto: ONLY true when score ≥ 0.9 OR an unhedgeable event window is in "
        "the next 24h (FOMC, payrolls, EIA, earnings).\n\n"
        "Be specific. Cite the actual stop level, ATR, and one named risk per "
        "key_risks entry. Reject vague statements like 'market could move'.\n\n"
        "Your output must be valid JSON only — no prose outside the JSON."
    )

    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 1000
    ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION = "2023-06-01"

    # Caps applied AFTER LLM output to keep the agent honest.
    MIN_SIZE_MULTIPLIER = 0.0
    MAX_SIZE_MULTIPLIER = 1.0
    MIN_TAIL_SCORE = 0.0
    MAX_TAIL_SCORE = 1.0

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    async def analyze(
        self,
        symbol: str,
        analyst_reports: dict,
        proposed_trade: Optional[dict] = None,
    ) -> TailRiskReport:
        """
        Score *symbol*'s proposed trade for tail-risk asymmetry.

        Parameters
        ----------
        symbol:
            Ticker being analysed.
        analyst_reports:
            Same dict structure as bull/bear researchers.
        proposed_trade:
            Optional dict with keys {entry, stop, target, contracts, side}.
            If supplied, the agent computes worst-case drawdown explicitly.
            If absent, it estimates from analyst_reports and the symbol's
            typical ATR/contract size.
        """
        prompt = self._build_prompt(symbol, analyst_reports, proposed_trade)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.ANTHROPIC_API_URL,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": self.ANTHROPIC_VERSION,
                        "content-type": "application/json",
                    },
                    json={
                        "model": self.MODEL,
                        "max_tokens": self.MAX_TOKENS,
                        "system": self.SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                response.raise_for_status()
                data = response.json()

            response_text = data["content"][0]["text"].strip()
            result = self._parse_json(response_text)

            return self._build_report(symbol, result)

        except Exception as exc:
            logger.error(f"TailRiskResearcherAgent failed for {symbol}: {exc}")
            return self._safe_report(symbol)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_report(self, symbol: str, result: dict) -> TailRiskReport:
        score = self._clamp(
            self._safe_float(result.get("tail_risk_score"), 0.0),
            self.MIN_TAIL_SCORE,
            self.MAX_TAIL_SCORE,
        )
        size_mult = self._clamp(
            self._safe_float(result.get("size_multiplier"), 1.0),
            self.MIN_SIZE_MULTIPLIER,
            self.MAX_SIZE_MULTIPLIER,
        )
        veto = bool(result.get("veto", False))

        # Honesty enforcement: if veto=True, force size_multiplier=0
        # If score >= 0.9, force veto=True (model can't claim "danger but proceed")
        if score >= 0.9 and not veto:
            logger.info(
                "TailRisk %s: forcing veto=True because score=%.2f≥0.9",
                symbol, score,
            )
            veto = True
        if veto and size_mult > 0:
            size_mult = 0.0

        return TailRiskReport(
            symbol=symbol,
            timestamp=datetime.now(),
            tail_risk_score=score,
            size_multiplier=size_mult,
            veto=veto,
            worst_case_drawdown_usd=self._safe_float_or_none(
                result.get("worst_case_drawdown_usd")
            ),
            key_risks=list(result.get("key_risks") or []),
            recommendation=str(result.get("recommendation") or "").strip(),
            reasoning=str(result.get("reasoning") or "").strip(),
        )

    def _build_prompt(
        self,
        symbol: str,
        analyst_reports: dict,
        proposed_trade: Optional[dict],
    ) -> str:
        serialised: dict = {}
        for key, report in analyst_reports.items():
            if hasattr(report, "to_dict"):
                serialised[key] = report.to_dict()
            elif hasattr(report, "__dict__"):
                serialised[key] = report.__dict__
            else:
                serialised[key] = report
        reports_json = json.dumps(serialised, indent=2, default=str)

        trade_json = json.dumps(proposed_trade or {}, indent=2, default=str)

        return f"""Score the TAIL RISK of the proposed trade on {symbol}.

ANALYST REPORTS:
{reports_json}

PROPOSED TRADE (may be empty if not yet sized):
{trade_json}

Your job is to assume the bull/bear debate already concluded. Tell us what
happens when the trade fails in the worst plausible way. Cite specific
event windows, liquidity holes, or volatility regime that could cause a
gap-through.

Respond with valid JSON in exactly this format (no text outside the JSON):
{{
  "tail_risk_score": <float 0.0 to 1.0>,
  "size_multiplier": <float 0.0 to 1.0 — 1.0 = no change, lower = downsize>,
  "veto": <true | false>,
  "worst_case_drawdown_usd": <float dollars or null if cannot estimate>,
  "key_risks": [
    "<specific tail risk 1 with cited level, indicator, or event>",
    "<specific tail risk 2>",
    "<specific tail risk 3>"
  ],
  "recommendation": "<one of: PROCEED | SIZE_DOWN | VETO>",
  "reasoning": "<2-3 sentences justifying the score and recommendation>"
}}"""

    @staticmethod
    def _parse_json(text: str) -> dict:
        try:
            return parse_llm_json(text)
        except LLMJsonError as exc:
            logger.warning(
                f"TailRiskResearcher JSON parse error: {exc} — raw: {text[:200]}"
            )
            return {}

    @staticmethod
    def _safe_float(value, default: float) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float_or_none(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def _safe_report(self, symbol: str) -> TailRiskReport:
        """Conservative default when the LLM call fails: assume normal risk,
        no veto, no sizing change. Caller can rely on bull/bear verdict."""
        return TailRiskReport(
            symbol=symbol,
            timestamp=datetime.now(),
            tail_risk_score=0.0,
            size_multiplier=1.0,
            veto=False,
            recommendation="PROCEED",
            reasoning="TailRisk analysis unavailable — upstream error; deferring to bull/bear verdict.",
        )
