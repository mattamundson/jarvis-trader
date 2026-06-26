"""Router-level tests for GET /trading-status/live — verifies the config+live
merge and summary composition. Monkeypatches the wiring callables so no DB is
touched (the module imports ``database`` lazily inside each wiring function).
"""

from __future__ import annotations

import routers.trading_status_router as tsr


def test_live_endpoint_merges_config_and_live(monkeypatch):
    monkeypatch.setattr(tsr, "_all_symbols", lambda: ["MES", "MGC"])
    monkeypatch.setattr(tsr, "_enabled_for", lambda s: True)
    monkeypatch.setattr(tsr, "_authorized_for", lambda s: True)
    monkeypatch.setattr(
        tsr,
        "_verdict_for",
        lambda s: {"verdict": "PASS", "family": "trend", "created_at": None, "oos_trades": 5},
    )
    monkeypatch.setattr(
        tsr,
        "_last_signal_for",
        lambda s: (
            {"timestamp": None, "action": "buy", "confidence": 0.9, "regime": "trend"}
            if s == "MES"
            else None
        ),
    )
    monkeypatch.setattr(tsr, "_last_order_for", lambda s: None)
    monkeypatch.setattr(
        tsr,
        "_open_position_for",
        lambda s: (
            {"trade_id": "T1", "side": "buy", "quantity": 1, "entry_price": 100, "entry_time": None}
            if s == "MES"
            else None
        ),
    )
    monkeypatch.setattr(tsr, "_realized_pnl_for", lambda s: 7.0 if s == "MGC" else None)
    monkeypatch.setattr(tsr, "_account_pnl", lambda: {"date": "2026-06-22", "realized_pnl": 7.0})

    out = tsr.get_trading_status_live()

    by = {r["symbol"]: r for r in out["symbols"]}
    assert set(by) == {"MES", "MGC"}
    # config fields survive the merge
    assert by["MES"]["tradeable"] is True
    assert by["MES"]["verdict"] == "PASS"
    # live block is nested and does not duplicate the symbol key
    assert "symbol" not in by["MES"]["live"]
    assert by["MES"]["live"]["has_open_position"] is True
    assert by["MES"]["live"]["last_signal"]["action"] == "buy"
    assert by["MGC"]["live"]["realized_pnl"] == 7.0
    assert by["MGC"]["live"]["has_open_position"] is False
    # summary composes config + live + account_pnl
    assert out["summary"]["total"] == 2
    assert out["summary"]["tradeable"] == 2
    assert out["summary"]["live"]["with_open_position"] == 1
    assert out["summary"]["live"]["with_signal"] == 1
    assert out["summary"]["account_pnl"]["realized_pnl"] == 7.0


def test_live_wiring_returns_none_when_db_unavailable(monkeypatch):
    # Force the lazy ``from database import get_db`` to yield a get_db that raises;
    # each wiring function must swallow it and return a safe default, never raise.
    import database

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(database, "get_db", _boom)

    assert tsr._last_signal_for("MES") is None
    assert tsr._last_order_for("MES") is None
    assert tsr._open_position_for("MES") is None
    assert tsr._realized_pnl_for("MES") is None
    assert tsr._account_pnl() is None
