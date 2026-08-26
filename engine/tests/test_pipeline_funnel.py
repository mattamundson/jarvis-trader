"""
JARVIS TRADER — Pipeline Funnel Tests (T9, v2 windows-shaped endpoint)
======================================================================
Unit tests for /analytics/pipeline-funnel (v2): both 30d/90d windows in one
payload, per-stage counts (runs -> signals -> approved -> executed -> filled),
the monotone approval cap, ledger-drift notes, and the 300s TTL cache.

The endpoint reads through DatabaseManager._connect() and issues raw COUNT(*)
queries in a fixed order per window (7 queries: runs, signals, auto_signals,
paq approved, pta approved, executed, filled), so the fake DB pops canned
counts in that order and records the SQL text for cache-hit assertions.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_pipeline_funnel.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Set test environment variables BEFORE any imports
test_env_vars = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:***@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "SCHWAB_APP_KEY": "test",
    "SCHWAB_APP_SECRET": "test",
    "FINNHUB_API_KEY": "test",
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "TWILIO_ACCOUNT_SID": "test",
    "TWILIO_AUTH_TOKEN": "test",
    "TWILIO_WHATSAPP_FROM": "+123****7890",
    "WHATSAPP_TO": "+0987654321",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for key, value in test_env_vars.items():
    os.environ.setdefault(key, value)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from routers import analytics_router  # noqa: E402

# 7 COUNT queries per funnel window, in the exact order the endpoint issues them.
_QUERIES_PER_WINDOW = 7


class _FakeCursor:
    """conn.execute() result: fetchone() returns the canned row."""

    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    """Minimal sqlite3.Connection stand-in consumed by _funnel_window."""

    def __init__(self, fake_db):
        self._db = fake_db

    def execute(self, sql, params=()):
        self._db.calls.append(sql)
        n = self._db._counts.pop(0) if self._db._counts else 0
        return _FakeCursor((n,))

    def close(self):
        pass


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeDb:
    """Minimal DatabaseManager stand-in exposing the _lock/_connect surface."""

    def __init__(self, counts):
        self._counts = list(counts)
        self.calls: list[str] = []
        self._lock = _NullLock()

    def _connect(self):
        return _FakeConn(self)


@pytest.fixture
def client():
    """TestClient wrapping analytics router with rate limiting disabled."""
    with patch.object(type(analytics_router.limiter), "limit", return_value=lambda f: f):
        app = FastAPI()
        app.include_router(analytics_router.router)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _clear_funnel_cache():
    analytics_router._funnel_cache.clear()
    yield
    analytics_router._funnel_cache.clear()


def _set_db(fake):
    analytics_router.set_db_manager(fake)  # type: ignore[arg-type]


# ── _funnel_window: stage math ──────────────────────────────────────────────


def test_funnel_math_happy_path():
    # runs, signals, auto, paq, pta, executed, filled
    fake = _FakeDb([1000, 200, 150, 40, 5, 40, 38])
    result = analytics_router._funnel_window(fake._connect(), 30)

    assert result["days"] == 30
    assert result["runs"] == 1000
    assert result["signals"] == 200
    assert result["auto_signals"] == 150
    assert result["human_signals"] == 50
    assert result["queue_approved_raw"] == 45
    assert result["approved"] == 195  # 150 + min(50, 45)
    assert result["executed"] == 40
    assert result["filled"] == 38
    assert result["conversion"] == {
        "signal_rate_pct": 20.0,
        "approval_rate_pct": 97.5,
        "execution_rate_pct": 20.51,  # 40/195 = 20.5128 -> 20.51
        "fill_rate_pct": 95.0,
        "overall_fill_rate_pct": 3.8,
    }
    assert result["notes"] == []


def test_funnel_caps_approved_at_signals():
    # Approval ledger exceeds human-required signals -> approved capped at
    # signals so the funnel stays monotone, and the drift is surfaced via notes.
    fake = _FakeDb([1000, 200, 150, 1000, 0, 40, 38])
    result = analytics_router._funnel_window(fake._connect(), 30)

    assert result["queue_approved_raw"] == 1000
    assert result["approved"] == 200  # 150 + min(50, 1000) -> capped at signals
    assert any("approval ledger" in n for n in result["notes"])


def test_funnel_executions_exceed_approvals_note():
    # Orders placed outside the approval ledger must surface as a note.
    fake = _FakeDb([1000, 200, 150, 0, 0, 250, 100])
    result = analytics_router._funnel_window(fake._connect(), 30)

    assert result["approved"] == 150
    assert result["executed"] == 250
    assert any("executions" in n for n in result["notes"])


def test_funnel_zero_denominators_do_not_crash():
    fake = _FakeDb([0] * _QUERIES_PER_WINDOW)
    result = analytics_router._funnel_window(fake._connect(), 90)

    assert result["days"] == 90
    assert result["runs"] == 0
    assert result["approved"] == 0
    assert result["conversion"]["signal_rate_pct"] is None
    assert result["conversion"]["overall_fill_rate_pct"] is None
    assert result["notes"] == []


def test_funnel_cutoff_format():
    result = analytics_router._funnel_window(_FakeDb([0] * _QUERIES_PER_WINDOW)._connect(), 30)
    cutoff = result["cutoff_utc"]
    # Naive UTC "YYYY-MM-DDTHH:MM:SS" — lexicographically comparable against
    # both naive pipeline_runs timestamps and tz-aware paper_trades rows.
    assert len(cutoff) == 19
    assert cutoff[10] == "T"
    assert "+" not in cutoff and "Z" not in cutoff


# ── Endpoint: both windows + cache ──────────────────────────────────────────


def test_endpoint_returns_both_windows(client):
    counts = [
        1000, 200, 150, 40, 5, 40, 38,  # 30d
        3000, 500, 400, 300, 100, 120, 90,  # 90d
    ]
    fake = _FakeDb(counts)
    _set_db(fake)

    resp = client.get("/analytics/pipeline-funnel")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["windows"].keys()) == {"30", "90"}
    assert data["windows"]["30"]["runs"] == 1000
    assert data["windows"]["90"]["runs"] == 3000
    assert data["windows"]["90"]["conversion"]["fill_rate_pct"] == 75.0  # 90/120
    assert data["windows"]["30"]["conversion"]["overall_fill_rate_pct"] == 3.8
    assert data["cache_ttl_seconds"] == 300
    assert "generated_at" in data
    assert len(fake.calls) == _QUERIES_PER_WINDOW * 2


def test_endpoint_caches_second_call(client):
    fake = _FakeDb([1000, 200, 150, 40, 5, 40, 38] * 2)
    _set_db(fake)

    r1 = client.get("/analytics/pipeline-funnel")
    assert r1.status_code == 200
    first_calls = len(fake.calls)
    assert first_calls == _QUERIES_PER_WINDOW * 2

    r2 = client.get("/analytics/pipeline-funnel")
    assert r2.status_code == 200
    assert r2.json() == r1.json()
    # Cache hit: no additional DB queries issued.
    assert len(fake.calls) == first_calls


def test_endpoint_missing_db_returns_503(client):
    analytics_router.set_db_manager(None)  # type: ignore[arg-type]
    resp = client.get("/analytics/pipeline-funnel")
    assert resp.status_code == 503
