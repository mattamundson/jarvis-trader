"""US-004 regression tests — dashboard-facing routes added/fixed 2026-06-12.

Covers:
- GET /portfolio/history/equity-curve (new)
- GET /analytics/regime + /analytics/regime/{symbol} (new)
- GET /ib/connection-test (new)
- /portfolio/paper/hold-time-stats naive/aware datetime fix
"""

from __future__ import annotations

import asyncio

import pytest

from routers import analytics_router, health_router, portfolio_router


def _run(coro):
    # asyncio.run, not get_event_loop().run_until_complete: after any earlier
    # test tears down with set_event_loop(None), get_event_loop() raises
    # "There is no current event loop" — making these tests order-dependent.
    return asyncio.run(coro)


class _FakeDB:
    def get_daily_pnl(self, days=30):
        return [
            {"date": "2026-06-09", "ending_balance": 8200.0, "realized_pnl": -73.0},
            {"date": "2026-06-08", "ending_balance": 8273.116, "realized_pnl": -41456.886},
            {"date": "2026-06-10", "ending_balance": None, "realized_pnl": 1.0},
        ]


class TestEquityCurve:
    def test_points_sorted_and_null_filtered(self, monkeypatch):
        monkeypatch.setattr(portfolio_router, "db_manager", _FakeDB())
        out = _run(portfolio_router.get_history_equity_curve(days=30))
        assert [p["date"] for p in out["points"]] == ["2026-06-08", "2026-06-09"]
        assert out["points"][0]["equity"] == pytest.approx(8273.116)
        assert out["count"] == 2

    def test_no_db_returns_empty_shape(self, monkeypatch):
        monkeypatch.setattr(portfolio_router, "db_manager", None)
        out = _run(portfolio_router.get_history_equity_curve())
        assert out["points"] == []


class TestRegimeEndpoints:
    def test_overview_shape_and_vocabulary(self):
        out = _run(analytics_router.get_regime_overview())
        assert out["regime"] in {"BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"}
        assert set(out["layers"]) == {"vix", "mtf", "stc", "ema_trend", "volume"}
        for layer in out["layers"].values():
            assert layer["status"] in {"active", "stub"}
        assert out["trade_filter"] in {"pass", "block", "unknown"}

    def test_symbol_regime_unknown_without_data(self, monkeypatch):
        monkeypatch.setattr(analytics_router, "_data_mgr", None)
        out = _run(analytics_router.get_regime_for_symbol("MES"))
        assert out["symbol"] == "MES"
        assert out["regime"] == "UNKNOWN"


class TestIBConnectionTest:
    def test_shape_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(health_router, "safety_layer", None)
        monkeypatch.setattr(health_router, "data_manager", None)
        out = _run(health_router.ib_connection_test())
        assert out["connected"] is False
        assert set(out) == {"connected", "port", "mode", "latency_ms", "account_id", "error"}
        assert out["error"] is not None

<<<<<<< HEAD
=======
    def test_connected_without_connector_port_uses_live_gateway_probe(self, monkeypatch):
        class _ConnectedNoPort:
            is_connected = True

            async def health_check(self):
                return {"status": "connected"}

        class _SafetyLayer:
            _ib_gateway = _ConnectedNoPort()

        monkeypatch.setattr(health_router, "safety_layer", _SafetyLayer())
        monkeypatch.setattr(health_router, "data_manager", None)
        monkeypatch.setattr(health_router, "_check_ibgateway_alive", lambda: (True, 4002))

        out = _run(health_router.ib_connection_test())

        assert out["connected"] is True
        assert out["port"] == 4002
        assert out["mode"] == "paper"
        assert out["error"] is None

>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

class TestHoldTimeTZFix:
    def test_mixed_naive_aware_rows_no_typeerror(self, monkeypatch):
        class _FakeTracker:
            def get_trade_history(self, *a, **k):
                return [
                    {  # aware exit, naive entry — the crash pair
                        "entry_time": "2026-06-11T10:00:00",
                        "exit_time": "2026-06-11T11:30:00+00:00",
                        "action": "buy",
                        "symbol": "MGC",
                    },
                    {  # both naive
                        "entry_time": "2026-06-10T10:00:00",
                        "exit_time": "2026-06-10T10:45:00",
                        "action": "sell",
                        "symbol": "MES",
                    },
                ]

        monkeypatch.setattr(portfolio_router, "paper_tracker", _FakeTracker())
        out = _run(portfolio_router.paper_hold_time_stats())
        # Both rows must survive the mixed naive/aware subtraction.
        assert out is not None
        assert (out.get("overall_avg_minutes") or 0) > 0


class TestSafetyStatusRateLimit:
    """US-005: /safety/status must sit in the read tier, not the 10/min trading tier."""

    def test_status_limit_is_read_tier(self):
        import inspect

        from routers import safety_router

        src = inspect.getsource(safety_router.get_safety_status)
        assert '120/minute' in src, "GET /safety/status must allow dashboard polling (120/minute)"
