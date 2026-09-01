"""Tests -- /system/data-integrity honest staleness threshold (P3-1).

Prior bug: the endpoint hardcoded `latency < 10` (10 seconds) to decide
healthy/stale, with no citation and no relationship to the tolerance the
system actually enforces. The real-money-readiness gate (gates.py,
FEED_STALE_SEC=900) and every dashboard consumer of this endpoint's `status`
field treated 900s as the honest fresh/stale line -- so a source 60s old (well
within the real tolerance) read "stale" here while the fund-ability gate
would have called it fine. Two disagreeing staleness verdicts for the same
underlying data is the "stale-Redis lie" this closes: the badge Amo looks at
must agree with the gate that decides fundability.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import health_router


class _FakeAsyncRedis:
    def __init__(self, entries: dict[str, str]):
        self._entries = entries

    async def keys(self, pattern):
        assert pattern == "datasource:*:last_update"
        return list(self._entries.keys())

    async def get(self, key):
        return self._entries.get(key)

    async def close(self):
        pass


def _client(monkeypatch, entries: dict[str, str]) -> TestClient:
    class _FakeRedisAsyncModule:
        @staticmethod
        def from_url(*_args, **_kwargs):
            return _FakeAsyncRedis(entries)

    # `import redis.asyncio as redis` inside get_data_integrity() resolves via
    # attribute access on the already-imported `redis` package (compiler walks
    # the dotted path as getattr, not a bare sys.modules['redis.asyncio']
    # lookup) -- patch both so this doesn't silently fall through to a real
    # local Redis and assert against live production data.
    import sys

    import redis as _real_redis_pkg

    fake_mod = _FakeRedisAsyncModule()
    monkeypatch.setattr(_real_redis_pkg, "asyncio", fake_mod, raising=False)
    monkeypatch.setitem(sys.modules, "redis.asyncio", fake_mod)

    app = FastAPI()
    app.include_router(health_router.router)
    return TestClient(app)


def _ts(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def test_source_within_documented_tolerance_reads_healthy(monkeypatch):
    """60s old used to read 'stale' under the old 10s cutoff -- must now read healthy."""
    client = _client(monkeypatch, {"datasource:ticks:MES1!:last_update": _ts(60.0)})
    body = client.get("/system/data-integrity").json()
    source = next(s for s in body["sources"] if s["source"] == "ticks:MES1!")
    assert source["status"] == "healthy"
    assert source["kind"] == "market_data"
    assert source["age_seconds"] == source["latency_sec"]
    assert source["cache_key"] == "datasource:ticks:MES1!:last_update"
    assert body["cache_age"]["status"] == "fresh"
    assert body["bar_freshness"]["status"] == "fresh"
    assert body["source_parity"]["status"] == "not_wired"
    assert body["provider_tier"]["status"] == "unknown"
    assert body["trade_enablement"]["status"] == "blocked"
    assert "source_parity_not_wired" in body["trade_enablement"]["blocking_reasons"]


def test_source_beyond_documented_tolerance_reads_stale(monkeypatch):
    client = _client(monkeypatch, {"datasource:ticks:MCL1!:last_update": _ts(950.0)})
    body = client.get("/system/data-integrity").json()
    source = next(s for s in body["sources"] if s["source"] == "ticks:MCL1!")
    assert source["status"] == "stale"
    assert body["cache_age"]["status"] == "stale"
    assert body["bar_freshness"]["status"] == "stale"
    assert "cache_age_stale" in body["trade_enablement"]["blocking_reasons"]
    assert "bar_freshness_stale" in body["trade_enablement"]["blocking_reasons"]


def test_threshold_matches_readiness_gate_constant(monkeypatch):
    """Pin the boundary to gates.py's FEED_STALE_SEC=900 so the two never drift apart again."""
    assert health_router.DATA_INTEGRITY_STALE_AFTER_S == 900.0

    just_inside = _client(
        monkeypatch, {"datasource:tv_stream:last_update": _ts(899.0)}
    ).get("/system/data-integrity").json()
    assert just_inside["sources"][0]["status"] == "healthy"

    just_outside = _client(
        monkeypatch, {"datasource:tv_stream:last_update": _ts(901.0)}
    ).get("/system/data-integrity").json()
    assert just_outside["sources"][0]["status"] == "stale"


def test_empty_data_integrity_response_is_explicitly_not_green(monkeypatch):
    body = _client(monkeypatch, {}).get("/system/data-integrity").json()
    assert body["status"] == "degraded"
    assert body["count"] == 0
    assert body["cache_age"]["status"] == "empty"
    assert body["bar_freshness"]["status"] == "empty"
    assert body["provider_tier"]["status"] == "unknown"
    assert body["source_parity"]["status"] == "not_wired"
    assert body["trade_enablement"]["status"] == "blocked"


def test_provider_tier_reports_configured_market_data_metadata(monkeypatch):
    monkeypatch.setattr(
        health_router.settings, "MARKET_DATA_ACTIVE_PROVIDER", "tradingview_mcp"
    )
    monkeypatch.setattr(
        health_router.settings, "MARKET_DATA_PRIMARY_PROVIDER", "tradingview_mcp"
    )
    monkeypatch.setattr(
        health_router.settings, "MARKET_DATA_FALLBACK_PROVIDERS", "ibkr,polygon"
    )

    body = _client(
        monkeypatch, {"datasource:ticks:MES1!:last_update": _ts(60.0)}
    ).get("/system/data-integrity").json()

    assert body["provider_tier"] == {
        "status": "known",
        "active": "tradingview_mcp",
        "primary": "tradingview_mcp",
        "fallbacks": ["ibkr", "polygon"],
        "reason": None,
    }
    assert "provider_tier_unknown" not in body["trade_enablement"]["blocking_reasons"]


def test_openapi_exposes_expanded_data_integrity_contract(monkeypatch):
    app = _client(monkeypatch, {}).app
    schema = app.openapi()

    response_schema = schema["paths"]["/system/data-integrity"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert response_schema["$ref"] == "#/components/schemas/DataIntegrityResponse"

    components = schema["components"]["schemas"]
    properties = components["DataIntegrityResponse"]["properties"]
    for field in [
        "timestamp",
        "status",
        "stale_after_seconds",
        "sources",
        "count",
        "cache_age",
        "provider_tier",
        "bar_freshness",
        "source_parity",
        "trade_enablement",
        "error",
    ]:
        assert field in properties

    assert (
        properties["sources"]["items"]["$ref"]
        == "#/components/schemas/DataIntegritySource"
    )
    assert (
        properties["cache_age"]["$ref"]
        == "#/components/schemas/DataIntegrityCacheAge"
    )
    assert (
        properties["provider_tier"]["$ref"]
        == "#/components/schemas/DataIntegrityProviderTier"
    )
    assert (
        properties["bar_freshness"]["$ref"]
        == "#/components/schemas/DataIntegrityBarFreshness"
    )
    assert (
        properties["source_parity"]["$ref"]
        == "#/components/schemas/DataIntegritySourceParity"
    )
    assert (
        properties["trade_enablement"]["$ref"]
        == "#/components/schemas/DataIntegrityTradeEnablement"
    )
