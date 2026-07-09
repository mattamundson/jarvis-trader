"""
Tests for the amo-arbitrage signal client (integrations.amoarb_signals).

Covers the invariant this module exists for: it NEVER raises, regardless of
what amo-arbitrage's endpoint does (down, slow, malformed) -- a dead upstream
must degrade to an honest {available: False, error: ...}, never take down
jarvis-trader's own /brief/session.
"""

from __future__ import annotations

import httpx
import pytest

from integrations.amoarb_signals import fetch_amoarb_signals


class _MockResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


class _MockAsyncClient:
    _next_response = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        return _MockAsyncClient._next_response


@pytest.mark.asyncio
async def test_happy_path(monkeypatch):
    rows = [
        {"symbol": "ZC", "signal": "buy", "prob_up": 0.61, "ic_overall": 0.08,
         "win_rate_oos": 0.54, "signal_date": "2026-07-09"},
    ]
    _MockAsyncClient._next_response = _MockResponse(rows)
    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)

    result = await fetch_amoarb_signals()

    assert result["available"] is True
    assert result["signals"] == rows
    assert result["error"] is None
    assert result["fetched_at"]


@pytest.mark.asyncio
async def test_connection_error(monkeypatch):
    class _RaisingClient(_MockAsyncClient):
        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", _RaisingClient)

    result = await fetch_amoarb_signals()

    assert result["available"] is False
    assert result["signals"] == []
    assert result["error"]


@pytest.mark.asyncio
async def test_timeout(monkeypatch):
    class _TimeoutClient(_MockAsyncClient):
        async def get(self, *args, **kwargs):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "AsyncClient", _TimeoutClient)

    result = await fetch_amoarb_signals()

    assert result["available"] is False
    assert result["error"]


@pytest.mark.asyncio
async def test_malformed_json(monkeypatch):
    class _BadJsonResponse(_MockResponse):
        def json(self):
            raise ValueError("not JSON")

    _MockAsyncClient._next_response = _BadJsonResponse(None)
    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)

    result = await fetch_amoarb_signals()

    assert result["available"] is False
    assert result["signals"] == []
    assert result["error"]


@pytest.mark.asyncio
async def test_non_200_status(monkeypatch):
    _MockAsyncClient._next_response = _MockResponse({"detail": "error"}, status_code=500)
    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)

    result = await fetch_amoarb_signals()

    assert result["available"] is False
    assert result["error"]
