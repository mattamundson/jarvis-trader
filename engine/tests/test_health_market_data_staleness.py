"""/health must degrade when the market-data feed is blind or stale.

Root cause (2026-07-21 audit): ``/health`` reported ``status="ok"`` and
``tradingview_mcp_healthy=true`` while the engine could not obtain a single real
price. Neither field was capable of detecting that:

  - ``_check_tradingview_mcp_health`` opens a socket to 127.0.0.1:9222 and GETs
    the Chrome DevTools ``/json/version`` endpoint. It proves a *browser* is
    listening. TV Desktop parked on a login screen, or a Redis fabric 20 days
    stale, passes it unchanged -- no price is ever requested.
  - Overall status was ``"ok" if (db_ok and llm_path_healthy) else "degraded"``.
    Market-data freshness was not a term in that expression at all.

The consequence was not merely cosmetic. A blind feed is exactly the condition
under which ``IBGatewayConnector.get_quote`` fell through to its frozen mock
table and booked paper fills at a 2024 constant (see
``test_paper_fill_refuses_mock_price.py``). The engine was manufacturing a track
record while every health surface it exposed was green.

The contract pinned here: ``/health`` asks the real market-data manager for a
real price, reports its provenance honestly via the existing DataEnvelope
machinery, and refuses to say ``ok`` when nothing live is arriving.
"""

from __future__ import annotations

import time

import pytest

from routers import health_router


class _LiveFeed:
    """A healthy feed: live tier, fresh timestamp."""

    async def get_current_price_envelope(self, symbol, is_futures=False, stale_after_s=None):
        return {
            "value": 7490.25,
            "source": "ibkr",
            "as_of": time.time(),
            "is_live": True,
            "stale_after_s": 60.0,
        }


class _StaleFeed:
    """The 20-day-stale-fabric shape: live tier, but the value is ancient."""

    async def get_current_price_envelope(self, symbol, is_futures=False, stale_after_s=None):
        return {
            "value": 5300.10,
            "source": "redis_fabric",
            "as_of": time.time() - 86_400.0,
            "is_live": False,
            "stale_after_s": 60.0,
        }


class _BlindFeed:
    """The production failure mode: attached, reachable, returns nothing."""

    async def get_current_price_envelope(self, symbol, is_futures=False, stale_after_s=None):
        return {
            "value": None,
            "source": "unavailable",
            "as_of": None,
            "is_live": False,
            "stale_after_s": 60.0,
        }


class _RaisingFeed:
    async def get_current_price_envelope(self, symbol, is_futures=False, stale_after_s=None):
        raise RuntimeError("feed exploded")


@pytest.mark.asyncio
async def test_live_feed_reports_fresh() -> None:
    fresh, details, age_s, source = await health_router._check_market_data_freshness(_LiveFeed())

    assert fresh is True
    assert source == "ibkr"
    assert details is None
    assert age_s is not None and age_s < 60.0


@pytest.mark.asyncio
async def test_stale_feed_is_not_fresh() -> None:
    """A live-tier source with an ancient timestamp must not read as healthy."""
    fresh, details, age_s, source = await health_router._check_market_data_freshness(_StaleFeed())

    assert fresh is False
    assert source == "redis_fabric"
    assert details, "a stale feed must explain itself"
    assert age_s is not None and age_s > 60.0


@pytest.mark.asyncio
async def test_blind_feed_is_not_fresh() -> None:
    """No price at all is the condition that triggered phantom mock fills."""
    fresh, details, _age_s, source = await health_router._check_market_data_freshness(_BlindFeed())

    assert fresh is False
    assert source == "unavailable"
    assert details


@pytest.mark.asyncio
async def test_missing_manager_is_not_fresh() -> None:
    """No manager wired at all must fail closed, not default to healthy."""
    fresh, details, _age_s, _source = await health_router._check_market_data_freshness(None)

    assert fresh is False
    assert details


@pytest.mark.asyncio
async def test_raising_feed_is_not_fresh() -> None:
    """An exploding feed must degrade, never 500 the endpoint or read as ok."""
    fresh, details, _age_s, _source = await health_router._check_market_data_freshness(
        _RaisingFeed()
    )

    assert fresh is False
    assert details


def test_freshness_fields_are_declared_on_the_response_model() -> None:
    """HealthResponse has no extra="allow", so undeclared keys are silently dropped.

    This has bitten twice already and both incidents are recorded in
    api/models.py: ``llm_providers`` was populated by the handler but missing
    from the model, so FastAPI stripped it from /health until 2026-06-06;
    ``futures_sentiment`` had the identical defect until 2026-06-30. In both
    cases the dict was correct and the endpoint still lied.

    Without this test the staleness gate would degrade the status correctly while
    every field explaining *why* disappeared before reaching the dashboard.
    """
    from api.models import HealthResponse

    for field in (
        "market_data_fresh",
        "market_data_source",
        "market_data_age_s",
        "market_data_details",
    ):
        assert field in HealthResponse.model_fields, (
            f"{field} is set by the /health handler but not declared on "
            f"HealthResponse -- FastAPI will strip it from the response"
        )


def test_overall_status_requires_market_data_freshness() -> None:
    """The status expression must include freshness as a term.

    Guards against the exact regression: db_ok and llm_path_healthy both True
    while the engine is blind used to yield "ok".
    """
    assert health_router._derive_overall_status(
        db_ok=True, llm_path_healthy=True, market_data_fresh=True
    ) == "ok"
    assert health_router._derive_overall_status(
        db_ok=True, llm_path_healthy=True, market_data_fresh=False
    ) == "degraded"
    assert health_router._derive_overall_status(
        db_ok=False, llm_path_healthy=True, market_data_fresh=True
    ) == "degraded"
    assert health_router._derive_overall_status(
        db_ok=True, llm_path_healthy=False, market_data_fresh=True
    ) == "degraded"
