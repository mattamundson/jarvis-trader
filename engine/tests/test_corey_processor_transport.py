"""B4 regression: CoreyCommentaryProcessor routes bias extraction through an
injected JarvisLLMClient (provider-fallback chain) when one is provided.

The direct Anthropic POST remains only for standalone contexts (CLI, MCP
server, briefing) constructed without an engine client.
"""

import os
import sys
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord.commentary_processor import CoreyCommentaryProcessor  # noqa: E402
from llm.client import LLMCallResult  # noqa: E402


def _result(success: bool, content: str = "", error: str = "") -> LLMCallResult:
    return LLMCallResult(
        success=success,
        model="gemini-2.0-flash",
        input_tokens=5,
        output_tokens=5,
        cost_usd=0.0,
        latency_ms=3,
        retries=0,
        content=content,
        error=error or None,
    )


_ROWS = [{"timestamp": "2026-06-10T09:00:00", "content": "ES looking heavy under 6000"}]

_BIAS_JSON = (
    '{"session_type": "trend_down", "directional_bias": "bearish",'
    ' "key_levels": [], "ib_bias": "unknown", "specific_triggers": [],'
    ' "conviction": 0.7, "corey_quote": "heavy under 6000"}'
)


@pytest.fixture()
def proc(tmp_path):
    def _make(llm=None):
        return CoreyCommentaryProcessor(
            db_path=str(tmp_path / "corey.db"), api_key="test-key", llm_client=llm
        )

    return _make


class TestInjectedClientRouting:
    @pytest.mark.asyncio
    async def test_extract_routes_through_injected_client(self, proc):
        llm = MagicMock()
        llm.call = AsyncMock(return_value=_result(True, content=_BIAS_JSON))
        p = proc(llm=llm)
        bias = await p._llm_extract(date(2026, 6, 10), _ROWS)
        assert llm.call.await_count == 1
        kwargs = llm.call.await_args.kwargs
        assert kwargs["agent_name"] == "corey_commentary"
        assert kwargs["model"] == CoreyCommentaryProcessor.MODEL
        assert bias.directional_bias == "bearish"
        assert bias.conviction == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_extract_failure_returns_neutral_bias(self, proc):
        llm = MagicMock()
        llm.call = AsyncMock(return_value=_result(False, error="credit balance is too low"))
        p = proc(llm=llm)
        bias = await p._llm_extract(date(2026, 6, 10), _ROWS)
        # fail-safe: neutral bias, never an exception
        assert bias.directional_bias == "neutral"
        assert bias.conviction == 0.0

    @pytest.mark.asyncio
    async def test_no_key_no_client_returns_neutral(self, tmp_path):
        p = CoreyCommentaryProcessor(db_path=str(tmp_path / "c.db"), api_key="")
        p._api_key = ""
        bias = await p._llm_extract(date(2026, 6, 10), _ROWS)
        assert bias.directional_bias == "neutral"

    @pytest.mark.asyncio
    async def test_client_without_key_still_extracts(self, tmp_path):
        """An injected client works even when no raw API key is configured."""
        llm = MagicMock()
        llm.call = AsyncMock(return_value=_result(True, content=_BIAS_JSON))
        p = CoreyCommentaryProcessor(
            db_path=str(tmp_path / "c2.db"), api_key="", llm_client=llm
        )
        p._api_key = ""
        bias = await p._llm_extract(date(2026, 6, 10), _ROWS)
        assert bias.directional_bias == "bearish"
