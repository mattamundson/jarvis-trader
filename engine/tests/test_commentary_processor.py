"""
Tests for CoreyCommentaryProcessor LLM-fallback path.

Bug being guarded: when the LLM call raises (e.g., HTTP 400 credit-balance,
transient httpx error), the prior fallback returned data_quality='fresh'
or 'stale' if rows were present — silently masking failure. Downstream
consumers in engine/analysis/discord_correlation.py filter
data_quality IN ('fresh','stale') and would include the content-empty row
in correlation queries, polluting signal with neutral/zero-conviction noise.

The fix: data_quality must always be 'none' on LLM exception, regardless of
whether rows were fetched. 'none' is the explicit "we have no LLM-extracted
bias for this date" sentinel.

Real-world incident: 2026-05-04 / 2026-05-05 corey_session_bias rows
showed data_quality='fresh' with conviction=0, neutral, content-empty
because the Anthropic API was returning HTTP 400 (credit-balance).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from discord.commentary_processor import CoreyCommentaryProcessor


def _make_failing_async_client(exc: Exception) -> MagicMock:
    """Build an httpx.AsyncClient mock whose .post() raises the given exception."""
    client = AsyncMock()
    client.post.side_effect = exc

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


async def test_llm_extract_returns_data_quality_none_on_http_400():
    """LLM HTTP 400 must yield data_quality='none' even with fresh rows present.

    This is the silent-regression guard. Before the fix, a fresh row + 4xx
    error returned data_quality='fresh' with empty content, which downstream
    correlation queries silently included as neutral signal.
    """
    fresh_rows = [
        {
            "content": "MES holding above 5800 — initiative buyers continuing",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channel": "market-updates",
        },
    ]

    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=":memory:")

    fake_response = MagicMock(status_code=400)
    http_400 = httpx.HTTPStatusError(
        "credit balance too low",
        request=MagicMock(),
        response=fake_response,
    )

    with patch(
        "discord.commentary_processor.httpx.AsyncClient",
        return_value=_make_failing_async_client(http_400),
    ):
        result = await proc._llm_extract(date.today(), fresh_rows)

    assert result.data_quality == "none", (
        f"Expected data_quality='none' on LLM exception, got '{result.data_quality}'. "
        f"This is the silent-regression bug."
    )
    # Other fallback fields should still be the neutral defaults.
    assert result.directional_bias == "neutral"
    assert result.session_type == "uncertain"
    assert result.message_count == len(fresh_rows)
    assert result.conviction == 0.0
    assert result.corey_quote == ""
    assert result.key_levels == []
    assert result.specific_triggers == []


async def test_llm_extract_returns_data_quality_none_on_generic_exception():
    """Any LLM exception path (not just HTTP) must produce data_quality='none'."""
    rows = [
        {
            "content": "test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channel": "market-updates",
        },
    ]

    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=":memory:")

    with patch(
        "discord.commentary_processor.httpx.AsyncClient",
        return_value=_make_failing_async_client(RuntimeError("network down")),
    ):
        result = await proc._llm_extract(date.today(), rows)

    assert result.data_quality == "none"
    assert result.message_count == 1


async def test_llm_extract_returns_data_quality_none_with_empty_rows():
    """Empty rows + LLM exception still produces 'none' (regression guard for
    the existing branch — this case was already correct pre-fix, but the
    test pins the contract so a future refactor can't reintroduce drift)."""
    proc = CoreyCommentaryProcessor(api_key="test-key", db_path=":memory:")

    # _llm_extract uses rows[-1] for date computation; with empty rows, the
    # function takes the for_date branch, so this exercises the path where
    # rows is [] but data_quality is still computed before the LLM call.
    with patch(
        "discord.commentary_processor.httpx.AsyncClient",
        return_value=_make_failing_async_client(RuntimeError("boom")),
    ):
        result = await proc._llm_extract(date.today(), [])

    assert result.data_quality == "none"
    assert result.message_count == 0
