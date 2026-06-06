"""
Tolerant JSON extraction for LLM responses.

Trading agents ask the LLM for a strict JSON object, but models routinely wrap
it in markdown fences, prepend a sentence ("Here is the analysis:"), append a
trailing note, or emit a trailing comma. The historical inline pattern in every
analyst —

    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        ...
    result = json.loads(response_text)

— is fragile: a fence anywhere but the very start, any leading prose, or a
trailing comma makes ``json.loads`` raise ``Expecting value: line N column M``,
which the agent catches and turns into a zero-signal empty report. On 2026-06-04
this surfaced as a wave of "LLM synthesis failed" errors across the technical,
news, social, and fundamental analysts — every one a discarded decision.

``parse_llm_json`` recovers the object the model actually returned:

  1. strip a ```/```json fence found anywhere in the text;
  2. direct ``json.loads``;
  3. brace-match the first balanced ``{...}`` object (handles leading/trailing
     prose), respecting strings and escapes;
  4. a light repair pass (drop trailing commas) before each parse attempt.

If nothing yields a dict it raises ``LLMJsonError`` so callers keep their
existing "degrade to a safe empty report" behavior — the change only converts
*recoverable* responses from failure to success, never the reverse.
"""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = ["parse_llm_json", "LLMJsonError"]


class LLMJsonError(json.JSONDecodeError):
    """Raised when no JSON object can be extracted from an LLM response.

    Subclasses ``json.JSONDecodeError`` (itself a ``ValueError``) so that every
    adopter — whether its except clause catches ``json.JSONDecodeError``,
    ``ValueError``, or ``Exception`` — handles this exactly as it handled the
    ``json.loads()`` call this util replaces. ``doc``/``pos`` are best-effort
    context, not a meaningful decode position.
    """

    def __init__(self, msg: str, doc: str = "", pos: int = 0):
        super().__init__(msg, doc, pos)


# ```json ... ```  or  ``` ... ```  — non-greedy, anywhere in the text.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
# Trailing comma before a closing } or ] — invalid JSON but a common LLM tic.
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _strip_fence(text: str) -> str:
    """Return the contents of the first markdown code fence, else the text."""
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _repair(candidate: str) -> str:
    """Light, safe repairs that don't change semantics: drop trailing commas."""
    return _TRAILING_COMMA_RE.sub(r"\1", candidate)


def _first_balanced_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` substring, respecting strings/escapes.

    Handles braces inside string values and escaped quotes so prose containing
    ``{`` or a JSON string like ``"a } b"`` does not confuse the matcher.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _try_load_dict(candidate: str) -> dict[str, Any] | None:
    """Attempt json.loads (raw then repaired); return the dict or None."""
    for attempt in (candidate, _repair(candidate)):
        try:
            obj = json.loads(attempt)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def parse_llm_json(text: Any) -> dict[str, Any]:
    """Extract a JSON object from a (possibly messy) LLM response.

    Args:
        text: the raw model output (str; other types are coerced via ``str``).

    Returns:
        The parsed JSON object as a dict.

    Raises:
        LLMJsonError: if no JSON object can be recovered.
    """
    if text is None:
        raise LLMJsonError("empty LLM response (None)")
    raw = str(text)

    # 1) fence-stripped direct/repaired parse
    stripped = _strip_fence(raw)
    obj = _try_load_dict(stripped)
    if obj is not None:
        return obj

    # 2) brace-match within the fence-stripped text (leading/trailing prose)
    extracted = _first_balanced_object(stripped)
    if extracted is not None:
        obj = _try_load_dict(extracted)
        if obj is not None:
            return obj

    # 3) last resort: brace-match within the original (un-stripped) text
    extracted_raw = _first_balanced_object(raw)
    if extracted_raw is not None and extracted_raw != extracted:
        obj = _try_load_dict(extracted_raw)
        if obj is not None:
            return obj

    raise LLMJsonError(f"no JSON object found in LLM response: {raw[:160]!r}")
