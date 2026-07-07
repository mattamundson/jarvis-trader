"""
JARVIS TRADER — Cross-modal supervisor fallback
================================================
Secondary-model fallback routing for notifier/supervisor calls.

Pattern source
--------------
Adapted from garrytan/gbrain (github.com/garrytan/gbrain) ``cross-modal-review``
skill. The load-bearing idea: when a primary model refuses or errors on a
classification task, silently route to a secondary model instead of
propagating the failure to the user. Refusals are a known failure mode of
frontier models on edge-case prompts (safety-tripwire false positives,
content-policy overlaps, transient 4xx errors), and the fix is almost
always "try a different model."

JARVIS adaptation
-----------------
Jarvis-trader already has ``SupervisorAgent`` (fail-open escalate on any
exception) and ``JarvisLLMClient`` (its own fallback chain for 5xx/rate-limit).
This module adds a *refusal detection* layer that sits between them —
specifically for the case where the primary model returns a successful
response that is itself a refusal ("I can't help with that", "I'm not able
to assess..."). That is distinct from an HTTP/API failure and is NOT
handled by JarvisLLMClient's provider-fallback chain.

Contract
--------
  detect_refusal(text) -> bool
      Heuristic classifier. Returns True for text that *looks like* a
      model refusal, regardless of which provider produced it.

  try_with_fallback(primary, fallback, *args, **kwargs)
      Call ``primary(*args, **kwargs)``. If the result is a refusal or
      raises, call ``fallback(*args, **kwargs)`` and return that instead.
      Logs the fallback trigger reason for telemetry.

Scope
-----
This is a *helper*, not a framework. It is intentionally narrow:

  * Only detects refusals from response text — does not retry on HTTP codes
    (``JarvisLLMClient`` owns that layer).
  * Does not persist decisions — the caller persists, e.g. ``SupervisorAgent``
    via its ``_record()`` hook.
  * Keeps the primary/fallback callables opaque — no assumptions about
    Anthropic vs. OpenAI vs. local Ollama.

License
-------
gbrain is MIT. Pattern port, not code port. Attribution preserved here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Refusal detector
# ---------------------------------------------------------------------------


# Phrase fragments that strongly indicate a model refusal. Matched
# case-insensitively with word boundaries; the list favors precision
# (avoid flagging legitimate trade analysis that mentions "can't" in
# passing) over recall.
_REFUSAL_PATTERNS: tuple[str, ...] = (
    r"\bi can(?:'|no)t (?:help|assist|provide|do|comply|analyze|give)\b",
    r"\bi(?:'m| am) (?:not able|unable) to\b",
    r"\bi(?:'m| am) sorry,? (?:but )?i can(?:'|no)t\b",
    r"\bi cannot (?:help|assist|provide|comply|analyze)\b",
    r"\bi (?:will not|won't) (?:help|assist|provide|comply|analyze)\b",
    r"\bi(?:'m| am) not (?:comfortable|willing|able) (?:to|with)\b",
    r"\bi must (?:refuse|decline)\b",
    r"\b(?:as an ai|i am an ai).*(?:cannot|can't|unable)\b",
    r"\brefus(?:e|al)\b.*\b(?:assist|help|provide|comply)\b",
)

_REFUSAL_REGEX = re.compile("|".join(_REFUSAL_PATTERNS), re.IGNORECASE | re.DOTALL)


def detect_refusal(text: Optional[str]) -> bool:
    """Return True iff ``text`` looks like a model refusal.

    Empty/None text is treated as non-refusal (a missing response is a
    different class of failure — the caller's exception handler owns that
    path). False positives cost one extra LLM call; false negatives cost a
    bad classification passed through to the user — so the matcher leans
    slightly generous (wide phrasing coverage) while requiring at least
    one of the canonical refusal phrases.
    """
    if not text:
        return False
    return _REFUSAL_REGEX.search(text) is not None


# ---------------------------------------------------------------------------
# Fallback dataclass + helper
# ---------------------------------------------------------------------------


@dataclass
class FallbackResult:
    """Carries both the chosen result and the fallback-trigger reason.

    ``source`` is one of:

      * ``"primary"``        — primary succeeded, no fallback needed.
      * ``"fallback:refusal"`` — primary returned a refusal; fallback used.
      * ``"fallback:error"``   — primary raised; fallback used.
      * ``"both_failed"``      — primary refused/raised AND fallback raised.
                                 ``value`` is the fallback exception in
                                 that case (not the result).
    """

    value: Any
    source: str
    primary_error: Optional[BaseException] = None


async def try_with_fallback(
    primary: Callable[..., Awaitable[T]],
    fallback: Callable[..., Awaitable[T]],
    *args: Any,
    refusal_detector: Callable[[Any], bool] = lambda r: detect_refusal(str(r) if r is not None else None),
    **kwargs: Any,
) -> FallbackResult:
    """Call ``primary``; fall back to ``fallback`` on refusal or exception.

    Both callables must be async and accept the same ``*args, **kwargs``.

    Args:
        primary: First-choice async callable.
        fallback: Second-choice async callable, called if primary refuses
            or raises.
        refusal_detector: Predicate applied to the primary result. Default
            stringifies the result and runs ``detect_refusal``; callers
            that work with structured responses (e.g. ``LLMResult`` with
            a ``content`` attribute) can pass a custom detector.

    Returns:
        A ``FallbackResult`` describing which path produced the value.
    """
    primary_error: Optional[BaseException] = None

    try:
        result = await primary(*args, **kwargs)
        if not refusal_detector(result):
            return FallbackResult(value=result, source="primary")
        logger.info(
            "[cross_modal_fallback] primary returned a refusal — routing to fallback"
        )
    except Exception as exc:
        primary_error = exc
        logger.info(
            "[cross_modal_fallback] primary raised %s — routing to fallback",
            type(exc).__name__,
        )

    source = "fallback:refusal" if primary_error is None else "fallback:error"
    try:
        fb_result = await fallback(*args, **kwargs)
        return FallbackResult(value=fb_result, source=source, primary_error=primary_error)
    except Exception as fb_exc:
        logger.warning(
            "[cross_modal_fallback] fallback also failed: %s", type(fb_exc).__name__
        )
        return FallbackResult(
            value=fb_exc,
            source="both_failed",
            primary_error=primary_error,
        )
