"""
JARVIS TRADER — Bear Researcher Agent
======================================
Constructs the strongest possible bearish case for a trade given a dict of
analyst reports (technical, news, social, fundamental signals).

Mirror of BullResearcherAgent — same interface, opposite mandate.
Both agents feed into DebateOrchestrator for structured adversarial analysis.

Model: Claude Sonnet 4.6
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

__all__ = ["BearReport", "BearResearcherAgent"]


@dataclass
class BearReport:
    """Structured bearish position produced by the Bear Researcher agent."""

    symbol: str
    timestamp: datetime

    # Core thesis
    bear_thesis: str = ""  # 2-3 sentence core bearish argument

    # Supporting risks / evidence
    key_risks: list[str] = field(default_factory=list)  # 3-5 specific risks / data points

    # Downside target (None if not determinable from the available data)
    downside_target: Optional[float] = None

    # Time horizon for the trade
    time_horizon: str = "swing"  # "intraday" | "swing" | "position"

    # 0-1: how strong is the bear case given the data
    conviction: float = 0.0

    # How the bear would rebut the main bull argument
    counterargument_response: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "bear_thesis": self.bear_thesis,
            "key_risks": self.key_risks,
            "downside_target": self.downside_target,
            "time_horizon": self.time_horizon,
            "conviction": self.conviction,
            "counterargument_response": self.counterargument_response,
        }


class BearResearcherAgent:
    """
    Given a dict of analyst reports for a symbol, constructs the strongest
    possible bearish case using Claude Sonnet.

    The agent is intentionally biased — its mandate is advocacy for the
    short/pass position, not balance. Pairing it with BullResearcherAgent
    inside DebateOrchestrator produces a balanced picture through structured
    adversarial reasoning.
    """

    SYSTEM_PROMPT = (
        "You are the Bear Researcher. Your job is to find and articulate the "
        "strongest bearish case for the trade. Do not be balanced — be an advocate "
        "for the short/pass position. Scrutinise the data for every indicator, "
        "signal, or narrative that warns of downside risk. Minimise bullish data "
        "points; reframe them as false breakouts, overextension, or temporary noise "
        "where possible. Your output must be valid JSON only — no prose outside the "
        "JSON object.\n\n"
        "SCORING RUBRIC:\n"
        "When rating the opposing argument, provide your assessment in this EXACT "
        "format on a new line:\n"
        "ASSESSMENT: SCORE: X/10 | EVIDENCE_COUNT: N | EVIDENCE_QUALITY: low/medium/high\n\n"
        "Definitions:\n"
        "- SCORE (1-10): Your conviction that the opposing argument will lead to a "
        "profitable trade\n"
        "- EVIDENCE_COUNT: Number of distinct data points cited (price levels, "
        "indicators, news events, macro data). Count: 0-10+\n"
        "- EVIDENCE_QUALITY:\n"
        "  - low = vague statements, no specific data (\"market seems uncertain\")\n"
        "  - medium = specific indicators or events cited (\"STC at 45, above midline\")\n"
        "  - high = quantified data with context (\"STC crossed above OS=15 with 1.8x "
        "ATR expansion, VIX=17.2 confirming low-vol regime\")"
    )

    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 1200
    ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    async def analyze(self, symbol: str, analyst_reports: dict) -> BearReport:
        """
        Construct the strongest bearish case for *symbol* given *analyst_reports*.

        Parameters
        ----------
        symbol:
            Ticker symbol being analysed (e.g. "AAPL", "ES", "BTC-USD").
        analyst_reports:
            Dict containing any combination of upstream report objects or dicts.
            Typical keys: "technical", "news", "social", "fundamental".
            Unknown keys are forwarded to the LLM as-is so the agent is
            forward-compatible with new signal sources.

        Returns
        -------
        BearReport
            Populated on success; default (zero-conviction) report on failure.
        """
        prompt = self._build_prompt(symbol, analyst_reports)

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

            return BearReport(
                symbol=symbol,
                timestamp=datetime.now(),
                bear_thesis=result.get("bear_thesis", ""),
                key_risks=result.get("key_risks", []),
                downside_target=self._safe_float(result.get("downside_target")),
                time_horizon=result.get("time_horizon", "swing"),
                conviction=float(result.get("conviction", 0.0)),
                counterargument_response=result.get("counterargument_response", ""),
            )

        except Exception as e:
            logger.error(f"BearResearcherAgent failed for {symbol}: {e}")
            return self._empty_report(symbol)

    async def call_llm(self, prompt: str) -> str:
        """Direct LLM call for debate scoring — returns raw text response.

        If the response contains a structured ASSESSMENT block, appends a
        WEIGHTED_SCORE line computed via _compute_weighted_score so that
        callers (e.g. DebateOrchestrator) can use evidence-adjusted scores.
        Falls back to raw text when no ASSESSMENT block is present.
        """
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
                    "max_tokens": 256,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
        raw_text = data["content"][0]["text"].strip()

        # Evidence-weighted score enhancement (backward-compatible)
        assessment = self._parse_assessment(raw_text)
        if assessment["score"] is not None:
            weighted = self._compute_weighted_score(
                raw_score=assessment["score"],
                evidence_count=assessment["evidence_count"] or 3,
                evidence_quality=assessment["evidence_quality"] or "medium",
            )
            raw_text = (
                f"{raw_text}\n"
                f"WEIGHTED_SCORE: {weighted:.2f}/10"
            )
        return raw_text

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_assessment(response_text: str) -> dict:
        """Parse structured assessment from LLM response."""
        result = {"score": None, "evidence_count": None, "evidence_quality": None}

        # Try structured format first
        pattern = (
            r'ASSESSMENT:\s*SCORE:\s*(\d+(?:\.\d+)?)/10\s*\|\s*'
            r'EVIDENCE_COUNT:\s*(\d+)\s*\|\s*'
            r'EVIDENCE_QUALITY:\s*(low|medium|high)'
        )
        match = re.search(pattern, response_text, re.IGNORECASE)
        if match:
            result["score"] = float(match.group(1))
            result["evidence_count"] = int(match.group(2))
            result["evidence_quality"] = match.group(3).lower()

        # Fallback: try existing score extraction pattern
        # (keep whatever score extraction already exists as primary, this as enhancement)
        return result

    @staticmethod
    def _compute_weighted_score(raw_score: float, evidence_count: int = 3,
                                evidence_quality: str = "medium") -> float:
        """Apply evidence weighting to raw score."""
        count_boost = 1 + 0.1 * min(evidence_count, 5)  # max 1.5x boost at 5 pieces
        quality_mult = {"low": 0.9, "medium": 1.0, "high": 1.1}.get(evidence_quality, 1.0)
        return min(10.0, raw_score * count_boost * quality_mult)

    def _build_prompt(self, symbol: str, analyst_reports: dict) -> str:
        """Serialise analyst reports into a structured prompt."""
        # Convert any dataclass/object reports to dicts if they expose to_dict()
        serialised = {}
        for key, report in analyst_reports.items():
            if hasattr(report, "to_dict"):
                serialised[key] = report.to_dict()
            elif hasattr(report, "__dict__"):
                serialised[key] = report.__dict__
            else:
                serialised[key] = report

        reports_json = json.dumps(serialised, indent=2, default=str)

        return f"""You are building the BEAR CASE for {symbol}.

Below are all available analyst reports for this symbol:

{reports_json}

Your task: find every piece of evidence that warns against a LONG trade on {symbol}
— reasons to short or stay flat.

Respond with valid JSON in exactly this format (no text outside the JSON):
{{
  "bear_thesis": "<2-3 sentence core bearish argument>",
  "key_risks": [
    "<specific risk or data point 1 supporting the bear case>",
    "<specific risk or data point 2>",
    "<specific risk or data point 3>",
    "<optional risk or data point 4>",
    "<optional risk or data point 5>"
  ],
  "downside_target": <float downside price target or null if not determinable>,
  "time_horizon": "<intraday|swing|position>",
  "conviction": <float 0.0 to 1.0 — how strong is the bear case given the data>,
  "counterargument_response": "<how would bears respond to the single biggest bull argument>"
}}"""

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Strip markdown fences if present, then parse JSON."""
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"BearResearcher JSON parse error: {e} — raw: {text[:200]}")
            return {}

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Return float or None without raising."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def _call_llm(self, prompt: str) -> str:
        """Generic LLM call used by DebateOrchestrator for adversarial scoring/rebuttals."""
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
                        "max_tokens": 512,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["content"][0]["text"].strip()
        except Exception as exc:
            logger.warning(f"BearResearcherAgent._call_llm failed: {exc}")
            return ""

    def _empty_report(self, symbol: str) -> BearReport:
        return BearReport(
            symbol=symbol,
            timestamp=datetime.now(),
            bear_thesis="Analysis unavailable — upstream error.",
            conviction=0.0,
        )
