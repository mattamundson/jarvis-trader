"""
JARVIS TRADER — Kronos Financial Foundation Model Classifier (stub)
===================================================================
Wraps the (future) Kronos paper-based financial foundation model as the 7th
analyst in the debate pipeline. Produces a :class:`VisionClassification`-
compatible verdict so it can slot alongside ``PatternVisionAnalyst`` without
requiring pipeline.py changes.

STUB ONLY — no HF Inference API or real LLM call yet. The paper schema for
Kronos's output format has not been locked; wire in the real call once that
lands. See ``docs/digest/`` for the integration card.

Gated by ``ENABLE_KRONOS`` env var (default off — set to ``"1"`` to activate).
Do NOT add this flag to ``engine/.env.example`` automatically; Amo will do that.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

# Re-use the shared VisionClassification dataclass from pattern_vision_analyst
# so the debate stack receives identical output shape from both visual analysts.
from agents.pattern_vision_analyst import VisionClassification, _clamp  # noqa: PLC2701

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment-flag helper
# ---------------------------------------------------------------------------

_ENV_FLAG = "ENABLE_KRONOS"


def is_kronos_enabled() -> bool:
    """Return True only when the ``ENABLE_KRONOS`` env var is set to ``"1"``.

    Intentionally strict: any value other than the exact string ``"1"`` is
    treated as disabled so that accidentally-set env vars don't activate a
    stub that emits neutral verdicts and silently dilutes the debate stack.
    """
    return os.environ.get(_ENV_FLAG, "") == "1"


# ---------------------------------------------------------------------------
# Output dataclass (pipeline-compatible)
# ---------------------------------------------------------------------------


@dataclass
class KronosVerdict:
    """Structured output of the Kronos classifier, pipeline-compatible.

    Mirrors the signal semantics of :class:`PatternVisionReport`:
    ``signal`` in ``[-1.0, +1.0]``, ``confidence`` in ``[0.0, 1.0]``.
    An abstention carries ``confidence=0.0`` and ``indicators["weight"] == 0.0``
    so ``pipeline._run_analysts.safe_analyze`` excludes it from confidence math
    (same convention as ``TechnicalReport._no_price_report``).
    """

    signal: float = 0.0
    confidence: float = 0.0
    direction: str = "neutral"
    reasoning: str = ""
    indicators: dict = field(default_factory=dict)

    def to_vision_classification(self) -> VisionClassification:
        """Convert to the shared :class:`VisionClassification` shape.

        This lets the debate stack treat Kronos output identically to
        PatternVisionAnalyst output without requiring a new protocol branch.
        """
        return VisionClassification(
            pattern_type="no_clear_pattern",
            signal=_clamp(self.signal, -1.0, 1.0),
            confidence=_clamp(self.confidence, 0.0, 1.0),
            reasoning=self.reasoning,
            raw="",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "confidence": self.confidence,
            "direction": self.direction,
            "reasoning": self.reasoning,
            "indicators": self.indicators,
        }


# ---------------------------------------------------------------------------
# KronosClassifier
# ---------------------------------------------------------------------------


class KronosClassifier:
    """7th analyst stub for the debate pipeline — Kronos foundation model.

    Interface contract mirrors :class:`agents.pattern_vision_analyst.VisionClassifier`
    in spirit: an ``async classify`` method that accepts time-series bars and
    returns a structured verdict. The signature differs slightly because Kronos
    operates on raw OHLCV bars rather than rendered PNG bytes.

    Real implementation will:
    1. Serialize ``bars`` to the Kronos paper's input schema (to be locked).
    2. Call the HF Inference API endpoint (model id TBD).
    3. Parse the response into a :class:`KronosVerdict`.
    4. Return ``verdict.to_vision_classification()`` for debate-stack compat.

    Until those steps are ready, ``classify`` returns a hardcoded neutral
    verdict with ``confidence=0.0`` so it contributes zero weight to the
    debate outcome. Graceful-degradation contract: never raises.
    """

    def __init__(self) -> None:
        if not is_kronos_enabled():
            logger.debug(
                "[KronosClassifier] ENABLE_KRONOS is not set — classifier instantiated "
                "but will return neutral abstentions on every call."
            )

    async def classify(self, bars: list[dict]) -> VisionClassification:
        """Classify a list of OHLCV bar dicts.

        Args:
            bars: List of bar dicts (keys: ``open``, ``high``, ``low``,
                  ``close``, ``volume``, ``timestamp``). Empty list is valid
                  for testing; the real model will require at least N bars
                  (N TBD from paper schema).

        Returns:
            A :class:`VisionClassification` with ``confidence=0.0`` and
            ``reasoning`` set to the stub message until the real call is wired.
            The ``pattern_type`` is always ``"no_clear_pattern"`` in stub mode.
        """
        if not is_kronos_enabled():
            return self._disabled_verdict()

        # TODO: replace stub body with real HF Inference API call
        # once Kronos paper schema is locked.  Remove the stub once verified.
        logger.info(
            "[KronosClassifier] ENABLE_KRONOS=1 but real model not yet wired — "
            "returning neutral stub verdict."
        )
        return self._stub_verdict()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _stub_verdict() -> VisionClassification:
        """Neutral stub verdict returned when flag is set but model not wired."""
        return VisionClassification(
            pattern_type="no_clear_pattern",
            signal=0.0,
            confidence=0.0,
            reasoning="stub — Kronos not yet wired",
            raw="",
        )

    @staticmethod
    def _disabled_verdict() -> VisionClassification:
        """Neutral abstention returned when ENABLE_KRONOS is not set."""
        return VisionClassification(
            pattern_type="no_clear_pattern",
            signal=0.0,
            confidence=0.0,
            reasoning="Kronos disabled (ENABLE_KRONOS not set)",
            raw="",
        )

    async def classify_to_verdict(self, bars: list[dict]) -> KronosVerdict:
        """Convenience wrapper returning the richer :class:`KronosVerdict` shape.

        Useful for tests or callers that want the ``direction`` and
        ``indicators`` fields before the debate stack normalises to
        :class:`VisionClassification`.
        """
        vc = await self.classify(bars)
        direction = "neutral"
        if vc.signal > 0.05:
            direction = "bullish"
        elif vc.signal < -0.05:
            direction = "bearish"
        return KronosVerdict(
            signal=vc.signal,
            confidence=vc.confidence,
            direction=direction,
            reasoning=vc.reasoning,
            indicators={"weight": vc.confidence},
        )


# ---------------------------------------------------------------------------
# NEXT STEPS (live-wiring follow-up, not in scope for this stub)
# ---------------------------------------------------------------------------
# 1. Lock the Kronos paper input/output schema (bar count, feature encoding).
# 2. Implement ``_call_kronos_api(bars)`` that:
#    - POSTs serialised bars to HF Inference endpoint
#    - Parses ``{"signal": float, "confidence": float, "reasoning": str}``
#    - Validates signal/confidence ranges with ``_clamp``
# 3. Replace ``_stub_verdict()`` / ``_disabled_verdict()`` calls in
#    ``classify()`` with ``_call_kronos_api(bars)`` results.
# 4. Wire into ``pipeline._run_analysts`` as 7th analyst, gated on
#    ``is_kronos_enabled()`` at pipeline init (not per-call, for perf).
# 5. Add ``ENABLE_KRONOS=`` to ``engine/.env.example`` (Amo does this step).
