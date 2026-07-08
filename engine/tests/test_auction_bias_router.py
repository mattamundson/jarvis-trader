"""Endpoint tests for /auction/bias/{symbol} with a fake data provider.

Exercises the router's synthesis + provenance wiring end-to-end through a
FastAPI TestClient, without needing the live engine, IB Gateway, or the concrete
data provider (which is wired in main.py on the host).
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import auction_bias_router as mod

# Same screenshot fixture as test_auction_bias_parity, in provider shape.
FIXTURE = {
    "price": 7526.75,
    "prior_close": 7551.75,
    "atr": 102.161,
    "day_range": 94.5,
    "tpo": {"value_area": 7500, "profile_target": 7624.25, "fail_target": 7529.75, "failed": True},
    "corey": {
        "bias": "bearish",
        "sellers_in_control_below": 7546.25,
        "buyers_offside_below": 7530.75,
        "data_quality": "stale",
    },
}


class FakeProvider:
    def __init__(self, inputs, source="ibkr", ibkr_connected=True, as_of=None):
        self._inputs = inputs
        self._source = source
        self._ibkr = ibkr_connected
        self._as_of = as_of

    def get_inputs(self, symbol):
        if self._inputs is None:
            return None
        return {
            **self._inputs,
            "source": self._source,
            "ibkr_connected": self._ibkr,
            "as_of": self._as_of if self._as_of is not None else time.time(),
        }


def _client(provider):
    mod.inject_dependencies(provider)
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app)


def test_live_ibkr_source_renders_live_and_correct_synthesis():
    client = _client(FakeProvider(FIXTURE, source="ibkr", ibkr_connected=True))
    r = client.get("/auction/bias/MES")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["provenance"]["is_live"] is True
    assert body["saty"]["bias"] == "short"
    assert abs(body["synthesis"]["line_in_sand"] - 7530.75) <= 0.25
    assert body["engine_derived"] is True and body["chart_parity"] is False


def test_stale_source_renders_static_not_live():
    # csv_cache is not a live tier -> is_live must be False even with fresh as_of.
    client = _client(FakeProvider(FIXTURE, source="csv_cache", ibkr_connected=False))
    body = client.get("/auction/bias/MES").json()
    assert body["available"] is True
    assert body["provenance"]["is_live"] is False
    assert body["provenance"]["source"] == "csv_cache"


def test_ibkr_leg_down_is_not_live():
    client = _client(FakeProvider(FIXTURE, source="ibkr", ibkr_connected=False))
    body = client.get("/auction/bias/MES").json()
    assert body["provenance"]["is_live"] is False


def test_unknown_symbol_rejected():
    client = _client(FakeProvider(FIXTURE))
    assert client.get("/auction/bias/MNQ").status_code == 400


def test_insufficient_data_returns_unavailable_not_error():
    client = _client(FakeProvider(None))
    r = client.get("/auction/bias/MES")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["is_live"] is False


def test_provider_not_wired_returns_503():
    mod.inject_dependencies(None)
    app = FastAPI()
    app.include_router(mod.router)
    client = TestClient(app)
    assert client.get("/auction/bias/MES").status_code == 503
    # restore for any later tests in the session
    mod.inject_dependencies(FakeProvider(FIXTURE))
