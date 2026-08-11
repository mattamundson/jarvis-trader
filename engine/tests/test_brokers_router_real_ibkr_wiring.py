"""Regression test for the 2026-08-10 finding: GET /brokers/positions and
GET /brokers/status read live IBKR state from the paper-sim order-routing
mock (`_ibkr`) instead of the real ib_async connection (`_real_ibkr`).

The mock always reports its own internal paper-sim book, completely
disconnected from the actual IB Gateway session -- so a real position (or a
real disconnect) never surfaces through these endpoints. Confirmed live: IB
Gateway held 2 MES contracts (verified via direct reqPositionsAsync/
reqExecutionsAsync queries) while GET /brokers/positions returned
ibkr.positions=[] with ibkr.connected=true, reproducing the exact 2026-08-03
dashboard blind spot.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_brokers_router_real_ibkr_wiring.py -v
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

os.environ.setdefault("API_KEY", "test-key")


def _build_client(mock_paper_sim_ibkr, mock_real_ibkr, data_manager=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.brokers_router import inject_dependencies
    from routers.brokers_router import router as brokers_router

    if data_manager is None:
        data_manager = SimpleNamespace(ibkr=mock_real_ibkr)

    inject_dependencies(ibkr=mock_paper_sim_ibkr, data_manager=data_manager)

    app = FastAPI()
    app.include_router(brokers_router)
    return TestClient(app, headers={"X-API-Key": os.environ["API_KEY"]})


def _make_mock(*, connected: bool, positions: list[dict]):
    mock = MagicMock()
    mock.is_connected = MagicMock(return_value=connected)
    mock.get_positions = AsyncMock(return_value=positions)
    return mock


def test_positions_reads_real_ibkr_not_paper_sim_mock():
    """A live MES position on the REAL connection must surface even though
    the paper-sim mock reports a totally different (or empty) book."""
    paper_sim_mock = _make_mock(connected=False, positions=[])  # would 404/empty if used
    real_mock = _make_mock(
        connected=True,
        positions=[
            {
                "symbol": "MES",
                "sec_type": "FUT",
                "exchange": "CME",
                "currency": "USD",
                "position": 2.0,
                "avg_cost": 37598.86,
                "market_price": None,
                "market_value": None,
                "unrealized_pnl": None,
                "account": "DUR375089",
            }
        ],
    )

    client = _build_client(paper_sim_mock, real_mock)
    resp = client.get("/brokers/positions")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ibkr"]["connected"] is True, (
        "connected flag must come from the real ib_async connection, not the "
        "paper-sim mock (which reports disconnected here)"
    )
    symbols = {p["symbol"] for p in body["ibkr"]["positions"]}
    assert "MES" in symbols, (
        f"real IBKR position invisible at GET /brokers/positions -- got "
        f"{body['ibkr']['positions']!r} (this is the 2026-08-03/08-10 blind spot)"
    )
    real_mock.get_positions.assert_awaited_once()
    paper_sim_mock.get_positions.assert_not_called()


def test_status_connected_flag_reads_real_ibkr():
    """GET /brokers/status connected flag must reflect the real connection,
    not the always-available paper-sim mock."""
    paper_sim_mock = _make_mock(connected=True, positions=[])  # mock is "connected" to itself
    real_mock = _make_mock(connected=False, positions=[])  # but Gateway is actually down

    client = _build_client(paper_sim_mock, real_mock)
    resp = client.get("/brokers/status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ibkr"]["connected"] is False, (
        "status must reflect the real Gateway session being down, not the "
        "paper-sim mock's own (unrelated) connected state"
    )
    assert body["order_router"]["futures_broker"] == "unavailable"
