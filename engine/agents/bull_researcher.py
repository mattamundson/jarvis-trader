"""
JARVIS TRADER — Bull Researcher Agent
======================================
Constructs the strongest possible bullish case for a trade given a dict of
analyst reports (technical, news, social, fundamental signals).

This agent is deliberately one-sided — it is an advocate, not a balanced analyst.
It feeds into the DebateOrchestrator alongside the BearResearcherAgent so that
the combined system surfaces the best argument on each side before a final
trading decision is made.

Model: Claude Sonnet 4.6
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

__all__ = ["BullReport", "BullResearcherAgent"]


@dataclass
class BullReport:
    """Structured bullish position produced by the Bull Researcher agent."""

    symbol: str
    timestamp: datetime

    # Core thesis
    bull_thesis: str = ""  # 2-3 sentence core bullish argument

    # Supporting evidence
    key_evidence: list[str] = field(default_factory=list)  # 3-5 specific data points

    # Price target (None if not determinable from the available data)
    price_target: Optional[float] = None

    # Time horizon for the trade
    time_horizon: str = "swing"  # "intraday" | "swing" | "position"

    # 0-1: how strong is the bull case given the data (not how likely the trade wins)
    conviction: float = 0.0

    # How the bull would rebut the main bear risk
    counterargument_response: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "bull_thesis": self.bull_thesis,
            "key_evidence": self.key_evidence,
            "price_target": self.price_target,
            "time_horizon": self.time_horizon,
            "conviction": self.conviction,
            "counterargument_response": self.counterargument_response,
        }


class BullResearcherAgent:
    """
    Given a dict of analyst reports for a symbol, constructs the strongest
    possible bullish case using Claude Sonnet.

    The agent is intentionally biased — its mandate is advocacy, not balance.
    Pairing it with BearResearcherAgent inside DebateOrchestrator produces a
    balanced picture through structured adversarial reasoning.
    """

    SYSTEM_PROMPT = (
        "You are the Bull Researcher. Your job is to find and articulate the "
        "strongest bullish case for the trade. Do not be balanced — be an advocate "
        "for the long position. Scrutinize the data for every indicator, signal, or "
        "narrative that supports a move higher. Minimise bearish data points; "
        "reframe them as temporary or priced-in where possible. Your output must be "
        "valid JSON only — no prose outside the JSON object."
    )

    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 1200
    ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    async def analyze(self, symbol: str, analyst_reports: dict) -> BullReport:
        """
        Construct the strongest bullish case for *symbol* given *analyst_reports*.

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
        BullReport
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

            return BullReport(
                symbol=symbol,
                timestamp=datetime.now(),
                bull_thesis=result.get("bull_thesis", ""),
                key_evidence=result.get("key_evidence", []),
                price_target=self._safe_float(result.get("price_target")),
                time_horizon=result.get("time_horizon", "swing"),
                conviction=float(result.get("conviction", 0.0)),
                counterargument_response=result.get("counterargument_response", ""),
            )

        except Exception as e:
            logger.error(f"BullResearcherAgent failed for {symbol}: {e}")
            return self._empty_report(symbol)

    # ── Internal helpers ──────────────────────────────────────────────────────

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

        return f"""You are building the BULL CASE for {symbol}.

Below are all available analyst reports for this symbol:

{reports_json}

Your task: find every piece of evidence that supports a LONG trade on {symbol}.

Respond with valid JSON in exactly this format (no text outside the JSON):
{{
  "bull_thesis": "<2-3 sentence core bullish argument>",
  "key_evidence": [
    "<specific data point 1 supporting the bull case>",
    "<specific data point 2>",
    "<specific data point 3>",
    "<optional data point 4>",
    "<optional data point 5>"
  ],
  "price_target": <float price target or null if not determinable>,
  "time_horizon": "<intraday|swing|position>",
  "conviction": <float 0.0 to 1.0 — how strong is the bull case given the data>,
  "counterargument_response": "<how would bulls respond to the single biggest bear risk>"
}}"""

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Strip markdown fences if present, then parse JSON."""
        if text.startswith("```"):
            parts = text.split("```")
            # parts[1] is the fenced block; strip optional language tag
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"BullResearcher JSON parse error: {e} — raw: {text[:200]}")
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

    def _empty_report(self, symbol: str) -> BullReport:
        return BullReport(
            symbol=symbol,
            timestamp=datetime.now(),
            bull_thesis="Analysis unavailable — upstream error.",
            conviction=0.0,
        )
