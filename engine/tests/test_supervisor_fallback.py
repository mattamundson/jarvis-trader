"""Tests for engine/notifications/supervisor_fallback.py.

Covers:

1. ``detect_refusal`` matches canonical refusal phrasing while avoiding
   false positives on trade analysis prose that happens to contain "can't".
2. ``try_with_fallback`` routes cleanly through all four outcomes:
   primary-success, fallback-on-refusal, fallback-on-exception, both-fail.
3. The default refusal detector composes with custom detectors for
   structured response types (e.g. objects with a ``.content`` attribute).

Offline — no LLM calls, no network.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from notifications.supervisor_fallback import (
    FallbackResult,
    detect_refusal,
    try_with_fallback,
)

# ---------------------------------------------------------------------------
# detect_refusal — positive cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "I can't help with that.",
        "I cannot help with that request.",
        "I'm not able to assess this trade.",
        "I am unable to provide that analysis.",
        "I'm sorry, but I can't comply.",
        "I will not help with that.",
        "I won't provide trading advice here.",
        "I'm not comfortable with this prompt.",
        "I must decline to answer.",
        "As an AI, I cannot analyze this.",
    ],
)
def test_detect_refusal_positive(phrase: str):
    assert detect_refusal(phrase) is True


# ---------------------------------------------------------------------------
# detect_refusal — negative cases (avoid false positives on trade analysis)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "The pattern can't be confirmed without more bars.",
        "We won't see breakout confirmation until VWAP reclaim.",
        "I'm not sure whether this is a reversal or continuation.",
        "Signal is mixed — analysts can't agree on direction.",
        "",
        "BUY MCL 1 contract — debate bull, risk approved",
        "The model could not find a clear pattern in this window.",
    ],
)
def test_detect_refusal_negative(phrase: str):
    assert detect_refusal(phrase) is False


def test_detect_refusal_none_input():
    assert detect_refusal(None) is False


def test_detect_refusal_case_insensitive():
    assert detect_refusal("I CAN'T HELP WITH THAT") is True
    assert detect_refusal("i can't help with that") is True


# ---------------------------------------------------------------------------
# try_with_fallback — outcome matrix
# ---------------------------------------------------------------------------


async def _returns(value):
    return value


async def _raises(_exc: Exception):
    raise _exc


@pytest.mark.asyncio
async def test_try_with_fallback_primary_success():
    async def primary():
        return "clean trade analysis"

    async def fallback():  # pragma: no cover — should not be invoked
        return "FALLBACK"

    result = await try_with_fallback(primary, fallback)
    assert isinstance(result, FallbackResult)
    assert result.value == "clean trade analysis"
    assert result.source == "primary"
    assert result.primary_error is None


@pytest.mark.asyncio
async def test_try_with_fallback_primary_refusal_uses_fallback():
    async def primary():
        return "I can't help with that."

    async def fallback():
        return "ok from fallback"

    result = await try_with_fallback(primary, fallback)
    assert result.value == "ok from fallback"
    assert result.source == "fallback:refusal"
    assert result.primary_error is None


@pytest.mark.asyncio
async def test_try_with_fallback_primary_exception_uses_fallback():
    async def primary():
        raise RuntimeError("api 500")

    async def fallback():
        return "recovered"

    result = await try_with_fallback(primary, fallback)
    assert result.value == "recovered"
    assert result.source == "fallback:error"
    assert isinstance(result.primary_error, RuntimeError)


@pytest.mark.asyncio
async def test_try_with_fallback_both_fail_returns_fallback_exception():
    async def primary():
        raise ValueError("primary down")

    async def fallback():
        raise RuntimeError("fallback also down")

    result = await try_with_fallback(primary, fallback)
    assert result.source == "both_failed"
    assert isinstance(result.value, RuntimeError)
    assert isinstance(result.primary_error, ValueError)


# ---------------------------------------------------------------------------
# Custom refusal detector for structured responses
# ---------------------------------------------------------------------------


@dataclass
class _FakeLLMResult:
    content: str
    success: bool = True


@pytest.mark.asyncio
async def test_try_with_fallback_structured_response_via_custom_detector():
    async def primary():
        return _FakeLLMResult(content="I'm not able to assess that.")

    async def fallback():
        return _FakeLLMResult(content="fallback classification")

    def _is_refusal(r):
        return detect_refusal(r.content) if r is not None else False

    result = await try_with_fallback(primary, fallback, refusal_detector=_is_refusal)
    assert result.source == "fallback:refusal"
    assert result.value.content == "fallback classification"


@pytest.mark.asyncio
async def test_try_with_fallback_passes_args_through():
    async def primary(a, b, *, c):
        return f"primary saw {a}+{b}+{c}"

    async def fallback(a, b, *, c):  # pragma: no cover
        return "fallback"

    result = await try_with_fallback(primary, fallback, 1, 2, c=3)
    assert result.value == "primary saw 1+2+3"
    assert result.source == "primary"
