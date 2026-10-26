from __future__ import annotations

import json
import os
import sys
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import Limiter

# Keep config imports satisfied without reading real secrets.
os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


class _FakeDb:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any] | None] = {
            "pipeline_runs": {
                "id": 99,
                "created_at": "2026-09-24T13:33:36",
                "symbol": "MES",
                "final_action": "buy",
                "requires_human": 0,
                "source": "scanner",
            },
            "pipeline_approval_queue": {
                "id": 10,
                "created_at": "2026-09-18T19:13:54+00:00",
                "symbol": "MES",
                "direction": "LONG",
                "status": "expired",
            },
            "pending_trade_approvals": {
                "id": 5,
                "created_at": "2026-08-11T16:03:24",
                "symbol": "MES",
                "action": "buy",
                "status": "rejected",
            },
            "paper_trades": {
                "id": 344,
                "entry_time": "2026-08-18T13:49:41+00:00",
                "symbol": "MES",
                "side": "buy",
                "status": "phantom",
            },
            "ibkr_fills": {
                "id": 6,
                "fill_time": "2026-06-01 09:06:14+00:00",
                "symbol": "ES",
                "action": "BUY",
            },
        }
        self.counts = {
            "pipeline_runs": 19148,
            "pipeline_approval_queue": 905,
            "pending_trade_approvals": 373,
            "paper_trades": 120,
            "ibkr_fills": 6,
        }
        self.decision_rows = [
            {
                "id": 19085,
                "timestamp": "2026-09-22T11:23:57",
                "symbol": "MES",
                "action": "buy",
                "confidence": 0.8,
                "signal_data_json": json.dumps(
                    {"data_provenance": {"last_bar_source": "ibkr", "serve_age_s": 102.4}}
                ),
                "full_pipeline_json": json.dumps(
                    {
                        "requires_human": False,
                        "trade_decision": {"entry_price": 7835.5, "stop_price": 7824.7},
                        "analyst_reports": {
                            "technical": {"indicators": {"stark_signal": "SHORT_GAP_FILL"}}
                        },
                    }
                ),
            },
            {
                "id": 19084,
                "timestamp": "2026-09-22T11:23:55",
                "symbol": "MNQ",
                "action": "sell",
                "confidence": 0.7,
                "signal_data_json": "{}",
                "full_pipeline_json": json.dumps(
                    {
                        "requires_human": False,
                        "trade_decision": {"entry_price": 30790.0, "stop_price": 30837.7},
                        "analyst_reports": {
                            "technical": {"indicators": {"stark_signal": "SHORT_GAP_FILL"}}
                        },
                    }
                ),
            },
        ]

    def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        if "COUNT(*) AS n FROM" in sql:
            table = sql.split("FROM", 1)[1].strip().split()[0]
            return {"n": self.counts[table]}
        for table, row in self.rows.items():
            if f"FROM {table}" in sql:
                return row
        raise AssertionError(f"unexpected fetch_one SQL: {sql}")

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        if "FROM decisions" in sql:
            return self.decision_rows[: params[0]]
        raise AssertionError(f"unexpected fetch_all SQL: {sql}")


def test_build_operator_handoff_status_explains_stale_handoff() -> None:
    from routers.analytics_router import _build_operator_handoff_status

    data = _build_operator_handoff_status(_FakeDb())

    assert data["status"] == "blocked"
    assert data["counts"]["pipeline_runs"] == 19148
    assert any("validation-only" in blocker for blocker in data["blockers"])
    assert any("DO_NOT_TRADE" in blocker for blocker in data["blockers"])
    assert any("skips pending approval rows" in blocker for blocker in data["blockers"])
    reasons = data["recent_directional_decisions"][1]["skip_reasons"]
    assert "do_not_trade_symbol" in reasons
    assert "validation_only_strategy" in data["recent_directional_decisions"][0]["skip_reasons"]


def test_operator_handoff_endpoint_returns_diagnostic_body() -> None:
    import sys

    for key in list(sys.modules.keys()):
        if "analytics_router" in key:
            del sys.modules[key]
    with patch.object(Limiter, "limit", return_value=lambda f: f):
        from routers import analytics_router as mod

    mod.set_db_manager(_FakeDb())  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(mod.router)
    client = TestClient(app, raise_server_exceptions=True)

    response = client.get("/analytics/operator-handoff")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "blocked"
    assert data["latest"]["pipeline_run"]["symbol"] == "MES"
    assert data["safety_note"].startswith("Read-only diagnostic")
