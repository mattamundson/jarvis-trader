"""
Tests for the FRED silent-default guard on FundamentalistAgent (Task 7).

Scope
-----
When the keyless FRED CSV fetch fails for one or more series, _fetch_fred_macro
substitutes hardcoded FRED_DEFAULTS so the pipeline is never blocked. Before
this guard, that fallback was invisible: the macro regime would be computed from
4-month-old constants and surfaced as if it were live data. These tests verify
that the fallback is now flagged on the FundamentalReport
(macro_data_is_default / macro_defaulted_keys) so the aggregator and dashboard
can down-weight or annotate it.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agents.fundamental_analyst import (
    FRED_DEFAULTS,
    FRED_SERIES,
    FundamentalistAgent,
    FundamentalReport,
)


def _make_agent() -> FundamentalistAgent:
    """Construct an agent with a stub LLM client (synthesis is mocked out)."""
    return FundamentalistAgent(llm_client=SimpleNamespace(api_key="test-key"))


def _stub_report() -> FundamentalReport:
    """A plain LLM-synthesised report with the default-guard fields unset."""
    from datetime import datetime

    return FundamentalReport(
        symbol="MES",
        timestamp=datetime.now(),
        signal=0.2,
        confidence=0.6,
        macro_regime="RISK_ON",
        macro_tailwind=True,
        key_metrics=dict(FRED_DEFAULTS),
        summary="stub",
        reasoning="stub",
    )


@pytest.mark.asyncio
async def test_defaulted_fred_flags_report():
    """When FRED series fall back to defaults, analyze() flags the report."""
    agent = _make_agent()

    async def _fake_fred(self):
        # Simulate _fetch_fred_macro's behaviour: every series fell back.
        self._macro_defaulted_keys = list(FRED_SERIES.keys())
        return dict(FRED_DEFAULTS)

    with patch.object(
        FundamentalistAgent, "_fetch_fred_macro", _fake_fred
    ), patch.object(
        agent, "_fetch_engine_macro_snapshot", AsyncMock(return_value={})
    ), patch.object(
        agent, "_llm_synthesize", AsyncMock(return_value=_stub_report())
    ):
        report = await agent.analyze("MES", is_futures=True)

    assert report.macro_data_is_default is True
    assert set(report.macro_defaulted_keys) == set(FRED_SERIES.keys())
    assert report.to_dict()["macro_data_is_default"] is True


@pytest.mark.asyncio
async def test_live_fred_no_default_flag():
    """When all FRED series fetch live, the report carries no default flag."""
    agent = _make_agent()

    async def _fake_fred(self):
        self._macro_defaulted_keys = []  # all live
        return {"fed_funds_rate": 4.5, "us_10y_yield": 4.4, "vix": 18.0}

    with patch.object(
        FundamentalistAgent, "_fetch_fred_macro", _fake_fred
    ), patch.object(
        agent, "_fetch_engine_macro_snapshot", AsyncMock(return_value={})
    ), patch.object(
        agent, "_llm_synthesize", AsyncMock(return_value=_stub_report())
    ):
        report = await agent.analyze("MES", is_futures=True)

    assert report.macro_data_is_default is False
    assert report.macro_defaulted_keys == []


@pytest.mark.asyncio
async def test_fetch_fred_macro_records_defaults_on_http_error():
    """_fetch_fred_macro records every failed series in _macro_defaulted_keys."""
    agent = _make_agent()

    class _FailingClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            # Non-200 for every series → all fall back to defaults.
            return SimpleNamespace(status_code=503, text="")

    with patch.object(httpx, "AsyncClient", _FailingClient):
        metrics = await agent._fetch_fred_macro()

    # Every series fell back to its hardcoded default.
    assert set(agent._macro_defaulted_keys) == set(FRED_SERIES.keys())
    for key, default_val in FRED_DEFAULTS.items():
        assert metrics[key] == default_val
