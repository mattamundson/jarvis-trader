"""
JARVIS TRADER — Pattern Vision Analyst (scaffold)
=================================================
Visual-pattern recognition agent. Renders the recent price chart to an image,
sends it to a vision-capable LLM, and returns a structured classification
(head-and-shoulders, triangle breakout, channel break, etc.) that the debate
stack can consume as a 6th analyst signal.

Adapted from Y-Research-SBU/QuantAgent (arxiv 2509.09995) Pattern Agent.
Reference analysis: ``docs/digest/ml-ai-synthesis.md`` — Novel #2.

SCAFFOLD ONLY — not live-wired into ``engine/agents/pipeline.py``. The
live-wiring step must (a) swap real ``ChartCapture`` / ``VisionClassifier``
implementations for the Protocol-based fakes used in tests, (b) gate the
invocation on ``ic_ensemble`` weight for the technical analyst, and (c) route
through ``TokenProxy`` so 300s cache hits are honored for identical chart
windows. See module-bottom NEXT STEPS.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from utils.llm_json import parse_llm_json

logger = logging.getLogger(__name__)

# Known pattern types the classifier is allowed to emit. Kept as a frozenset
# so the dataclass post-init can reject unknown labels before they poison the
# debate stack. Extend here if a new visual pattern is added.
KNOWN_PATTERNS: frozenset[str] = frozenset(
    {
        "head_and_shoulders",
        "inverse_head_and_shoulders",
        "double_top",
        "double_bottom",
        "ascending_triangle",
        "descending_triangle",
        "symmetrical_triangle",
        "bull_flag",
        "bear_flag",
        "channel_breakout_up",
        "channel_breakout_down",
        "range_consolidation",
        "no_clear_pattern",
    }
)


@dataclass
class PatternVisionReport:
    """Structured output of the Pattern Vision Analyst.

    Signal semantics match the rest of the analyst stack: ``signal`` in
    ``[-1.0, +1.0]``, ``confidence`` in ``[0.0, 1.0]``. An abstention carries
    ``confidence=0.0`` AND ``indicators["weight"] == 0.0`` so
    ``pipeline._run_analysts.safe_analyze`` excludes it from confidence math
    (same convention as ``TechnicalReport._no_price_report``).
    """

    symbol: str
    timestamp: datetime
    timeframe: str
    signal: float = 0.0
    confidence: float = 0.0
    pattern_type: str = "no_clear_pattern"
    reasoning: str = ""
    summary: str = ""
    indicators: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "timeframe": self.timeframe,
            "signal": self.signal,
            "confidence": self.confidence,
            "pattern_type": self.pattern_type,
            "reasoning": self.reasoning,
            "summary": self.summary,
            "indicators": self.indicators,
        }


class ChartCapture(Protocol):
    """Renders a chart for ``symbol`` at ``timeframe`` and returns PNG bytes.

    Real implementation will drive the ``chrome-devtools`` MCP server
    (registered in ``.mcp.json`` commit d99fad4, 2026-04-16) against
    TradingView and base64-decode the screenshot tool's output. The Protocol
    exists so tests can swap in a fake that returns a fixture PNG without
    spinning up Chrome.
    """

    async def capture(self, symbol: str, timeframe: str) -> bytes:
        ...


@dataclass
class VisionClassification:
    """What the vision LLM returns. ``raw`` is preserved for debugging."""

    pattern_type: str
    signal: float
    confidence: float
    reasoning: str
    raw: str = ""


class VisionClassifier(Protocol):
    """Sends ``png_bytes`` + a context prompt to a vision model and parses
    the response into a :class:`VisionClassification`.

    Real implementation will call ``LLMClient.call`` with a message whose
    ``content`` is a two-block list: ``[{"type": "image", "source": {...}},
    {"type": "text", "text": context}]`` on ``claude-sonnet-4-6`` (vision
    capable). The Protocol lets tests inject canned classifications without
    burning image-input tokens.
    """

    async def classify(self, png_bytes: bytes, context: str) -> VisionClassification:
        ...


class PatternVisionAnalyst:
    """6th analyst for the debate pipeline — visual pattern recognition.

    Orchestration:
        1. Capture the chart window (Chrome CDP MCP → PNG bytes)
        2. Classify the image against known visual patterns
        3. Translate into a signal-compatible report

    Graceful degradation: any failure at step 1 or 2 returns an abstention
    (``weight=0.0``, reason tagged) instead of raising. This matches
    ``technical_analyst._no_price_report`` so the debate stack never
    mis-interprets an infra failure as a bearish vote.
    """

    def __init__(
        self,
        chart_capture: ChartCapture,
        classifier: VisionClassifier,
    ) -> None:
        self._capture = chart_capture
        self._classifier = classifier

    async def analyze(
        self,
        symbol: str,
        timeframe: str = "1h",
        context_hint: str = "",
    ) -> PatternVisionReport:
        """Full pattern-recognition pipeline for one symbol/timeframe.

        ``context_hint`` is optional extra text (e.g. from Hidden Pivots or
        the technical analyst's STC state) the classifier uses to tie-break
        ambiguous shapes. Never raises — failures return abstention reports.
        """
        png_bytes = await self._safe_capture(symbol, timeframe)
        if png_bytes is None:
            return self._abstention(symbol, timeframe, reason="chart_capture_failed")

        classification = await self._safe_classify(png_bytes, symbol, timeframe, context_hint)
        if classification is None:
            return self._abstention(symbol, timeframe, reason="vision_classify_failed")

        if classification.pattern_type not in KNOWN_PATTERNS:
            logger.warning(
                "[PatternVisionAnalyst] %s: classifier returned unknown pattern %r — "
                "abstaining to avoid poisoning debate with unvalidated label",
                symbol,
                classification.pattern_type,
            )
            return self._abstention(symbol, timeframe, reason="unknown_pattern_type")

        signal = _clamp(classification.signal, -1.0, 1.0)
        confidence = _clamp(classification.confidence, 0.0, 1.0)

        return PatternVisionReport(
            symbol=symbol,
            timestamp=datetime.now(),
            timeframe=timeframe,
            signal=signal,
            confidence=confidence,
            pattern_type=classification.pattern_type,
            reasoning=classification.reasoning,
            summary=f"{classification.pattern_type} (signal={signal:+.2f} conf={confidence:.2f})",
            indicators={"raw_response_len": len(classification.raw)},
        )

    async def _safe_capture(self, symbol: str, timeframe: str) -> bytes | None:
        try:
            return await self._capture.capture(symbol, timeframe)
        except Exception as exc:
            logger.warning(
                "[PatternVisionAnalyst] chart capture failed for %s %s: %s",
                symbol, timeframe, exc,
            )
            return None

    async def _safe_classify(
        self,
        png_bytes: bytes,
        symbol: str,
        timeframe: str,
        context_hint: str,
    ) -> VisionClassification | None:
        context = _build_context_prompt(symbol, timeframe, context_hint)
        try:
            return await self._classifier.classify(png_bytes, context)
        except Exception as exc:
            logger.warning(
                "[PatternVisionAnalyst] vision classify failed for %s %s: %s",
                symbol, timeframe, exc,
            )
            return None

    @staticmethod
    def _abstention(symbol: str, timeframe: str, *, reason: str) -> PatternVisionReport:
        return PatternVisionReport(
            symbol=symbol,
            timestamp=datetime.now(),
            timeframe=timeframe,
            signal=0.0,
            confidence=0.0,
            pattern_type="no_clear_pattern",
            reasoning=(
                f"Pattern vision analyst abstained ({reason}). "
                "This is NOT a bearish signal — debate stack should exclude "
                "this report from confidence computation."
            ),
            summary="pattern-vision abstention",
            indicators={"weight": 0.0, "reason": reason},
        )


def _clamp(value: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return max(lo, min(hi, v))


def _build_context_prompt(symbol: str, timeframe: str, context_hint: str) -> str:
    lines = [
        f"Symbol: {symbol}",
        f"Timeframe: {timeframe}",
        "",
        "You are a visual-pattern-recognition analyst. Identify the dominant chart "
        "pattern in the image above. Respond with JSON matching this schema:",
        "{",
        '  "pattern_type": "<one of: head_and_shoulders, inverse_head_and_shoulders, '
        "double_top, double_bottom, ascending_triangle, descending_triangle, "
        "symmetrical_triangle, bull_flag, bear_flag, channel_breakout_up, "
        'channel_breakout_down, range_consolidation, no_clear_pattern>",',
        '  "signal": <float in [-1.0, +1.0]>,',
        '  "confidence": <float in [0.0, 1.0]>,',
        '  "reasoning": "<1-3 sentences on which features drove the classification>"',
        "}",
        "Emit no_clear_pattern rather than guessing when the shape is ambiguous.",
    ]
    if context_hint:
        lines.extend(["", f"Context hint: {context_hint}"])
    return "\n".join(lines)


def parse_vision_json(raw: str) -> VisionClassification:
    """Parse a vision-model response string into a :class:`VisionClassification`.

    Tolerates markdown code fences around JSON. On any parse failure returns
    a ``no_clear_pattern`` abstention rather than raising — the analyst's
    ``_safe_classify`` wrapper then routes that into the standard abstention
    path so partial failures never surface as false signals.
    """
    # Tolerant extraction (fences, prose, trailing commas) via utils.llm_json.
    # LLMJsonError subclasses json.JSONDecodeError, so the abstention path below
    # still catches a genuinely unparseable response.
    try:
        data: Any = parse_llm_json(raw)
    except json.JSONDecodeError:
        return VisionClassification(
            pattern_type="no_clear_pattern",
            signal=0.0,
            confidence=0.0,
            reasoning="vision response was not valid JSON",
            raw=raw,
        )
    if not isinstance(data, dict):
        return VisionClassification(
            pattern_type="no_clear_pattern",
            signal=0.0,
            confidence=0.0,
            reasoning="vision response did not decode to a JSON object",
            raw=raw,
        )
    return VisionClassification(
        pattern_type=str(data.get("pattern_type", "no_clear_pattern")),
        signal=_clamp(data.get("signal", 0.0), -1.0, 1.0),
        confidence=_clamp(data.get("confidence", 0.0), 0.0, 1.0),
        reasoning=str(data.get("reasoning", "")),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# NEXT STEPS (live-wiring follow-up, not in scope for this scaffold)
# ---------------------------------------------------------------------------
# 1. Implement ``ChromeDevToolsChartCapture(ChartCapture)`` that:
#    - Opens chart URL via ``chrome-devtools`` MCP tool ``navigate``
#    - Waits for chart render (``wait_for_selector`` on TV canvas)
#    - Calls MCP ``screenshot`` and base64-decodes to ``bytes``
# 2. Implement ``ClaudeVisionClassifier(VisionClassifier)`` that:
#    - Encodes ``png_bytes`` to base64
#    - Calls ``llm_client.call`` with
#      ``messages=[{"role": "user", "content": [
#          {"type": "image", "source": {"type": "base64",
#              "media_type": "image/png", "data": b64}},
#          {"type": "text", "text": context},
#      ]}]``
#    - Routes result through ``parse_vision_json``
# 3. Wire into ``pipeline._run_analysts`` as a 6th analyst, gated by:
#    - ``ic_ensemble.get_weight("technical") >= VISION_IC_THRESHOLD``
#    - ``TokenProxy`` cache-check (300s TTL is appropriate for 1h charts)
# 4. Add eval script that replays 30 historical MCL 1h Hidden-Pivots setups
#    and compares HP+Vision vs HP-alone on realized 2h forward pnl.
