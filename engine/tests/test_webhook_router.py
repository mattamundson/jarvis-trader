"""
Tests for engine/routers/webhook_router.py (TradingView inbound webhook surface).

Mounts ONLY the router on a minimal app. Resets the module's dedup cache, ring
buffer, secret, and pipeline callback around every test so tests don't leak
state into each other (all are module-level mutable globals).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.webhook_router as mod
from routers.webhook_router import router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _client() -> TestClient:
    return TestClient(_app())


@pytest.fixture(autouse=True)
def _reset_module_state():
    original_secret = mod.WEBHOOK_SECRET
    original_callback = mod._pipeline_callback
    mod.WEBHOOK_SECRET = ""
    mod._pipeline_callback = None
    mod._recent_webhooks.clear()
    mod._dedup_cache.clear()
    yield
    mod.WEBHOOK_SECRET = original_secret
    mod._pipeline_callback = original_callback
    mod._recent_webhooks.clear()
    mod._dedup_cache.clear()


def _payload(**overrides):
    base = {"symbol": "mes", "action": "long", "price": 5300.25}
    base.update(overrides)
    return base


# ── GET /webhook/tradingview/test ───────────────────────────────────────────


def test_webhook_liveness_probe():
    r = _client().get("/webhook/tradingview/test")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["secret_configured"] is False


def test_webhook_liveness_probe_reflects_secret_configured():
    mod.WEBHOOK_SECRET = "shh"
    r = _client().get("/webhook/tradingview/test")
    assert r.status_code == 200
    assert r.json()["secret_configured"] is True


# ── POST /webhook/tradingview ───────────────────────────────────────────────


def test_webhook_no_pipeline_registered_still_acknowledges():
    """No pipeline callback wired yet (engine still starting) -> signal is
    logged/accepted, not dropped or errored."""
    r = _client().post("/webhook/tradingview", json=_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "received"
    assert body["symbol"] == "MES"
    assert body["action"] == "LONG"
    assert body["pipeline_triggered"] is False


def test_webhook_forwards_to_pipeline_callback():
    callback = AsyncMock(return_value={"status": "trade_opened"})
    mod.set_pipeline_callback(callback)

    r = _client().post("/webhook/tradingview", json=_payload(symbol="mgc", action="short"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pipeline_triggered"] is True
    assert body["status"] == "trade_opened"
    assert body["result"] == {"status": "trade_opened"}

    callback.assert_awaited_once()
    call_kwargs = callback.call_args.kwargs
    assert call_kwargs["symbol"] == "MGC"
    assert call_kwargs["action"] == "SHORT"
    assert call_kwargs["price"] == 5300.25


def test_webhook_hold_action_never_triggers_pipeline():
    callback = AsyncMock(return_value={"status": "should_not_run"})
    mod.set_pipeline_callback(callback)

    r = _client().post("/webhook/tradingview", json=_payload(action="hold"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pipeline_triggered"] is False
    assert body["status"] == "received"
    callback.assert_not_awaited()


def test_webhook_invalid_action_rejected_with_400():
    r = _client().post("/webhook/tradingview", json=_payload(action="YOLO"))
    assert r.status_code == 400
    assert "Invalid action" in r.json()["detail"]


def test_webhook_missing_required_field_rejected_with_422():
    """symbol/action are required -- an alert template with a typo'd field
    name must fail validation, not silently drop signal data."""
    r = _client().post("/webhook/tradingview", json={"price": 5300.25})
    assert r.status_code == 422


def test_webhook_secret_mismatch_rejected_with_403():
    mod.WEBHOOK_SECRET = "correct-horse-battery-staple"
    r = _client().post("/webhook/tradingview", json=_payload(secret="wrong-secret"))
    assert r.status_code == 403


def test_webhook_secret_match_is_accepted():
    mod.WEBHOOK_SECRET = "correct-horse-battery-staple"
    r = _client().post(
        "/webhook/tradingview", json=_payload(secret="correct-horse-battery-staple")
    )
    assert r.status_code == 200, r.text


def test_webhook_duplicate_signal_within_window_is_rejected():
    first = _client().post("/webhook/tradingview", json=_payload())
    assert first.status_code == 200
    assert first.json()["status"] == "received"

    second = _client().post("/webhook/tradingview", json=_payload())
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "duplicate"


def test_webhook_pipeline_exception_reported_not_raised():
    """A pipeline callback that raises must surface as a structured 200 error
    response, not an unhandled 500 -- TradingView retries aggressively on
    non-2xx and would hammer the endpoint."""
    callback = AsyncMock(side_effect=RuntimeError("pipeline exploded"))
    mod.set_pipeline_callback(callback)

    r = _client().post("/webhook/tradingview", json=_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "error"
    assert body["pipeline_triggered"] is False
    assert "pipeline exploded" in body["error"]


# ── GET /webhook/dedup-stats ─────────────────────────────────────────────────


def test_dedup_stats_reflects_active_entries():
    r = _client().post("/webhook/tradingview", json=_payload())
    assert r.status_code == 200

    r = _client().get("/webhook/dedup-stats")
    assert r.status_code == 200
    body = r.json()
    assert body["active_entries"] == 1
    assert body["window_seconds"] == 30.0
    assert list(body["entries"].keys()) == ["MES:LONG:5300.25"]


def test_dedup_stats_empty_when_no_webhooks_received():
    r = _client().get("/webhook/dedup-stats")
    assert r.status_code == 200
    body = r.json()
    assert body["active_entries"] == 0
    assert body["entries"] == {}


# ── GET /signals/stats ───────────────────────────────────────────────────────


def test_signals_stats_reports_recent_webhooks():
    r = _client().post("/webhook/tradingview", json=_payload())
    assert r.status_code == 200

    r = _client().get("/signals/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_received"] == 1
    assert len(body["recent_webhooks"]) == 1
    assert body["recent_webhooks"][0]["symbol"] == "MES"
    assert body["dedup_cache_size"] == 1


def test_signals_stats_empty_when_no_webhooks_received():
    r = _client().get("/signals/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_received"] == 0
    assert body["recent_webhooks"] == []
    assert body["dedup_cache_size"] == 0
