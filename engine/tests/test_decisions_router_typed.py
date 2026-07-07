"""Integration tests for decisions_router /detail typed + fallback paths.

Exercises the router in-process via FastAPI TestClient with an injected
fake DatabaseManager. No real SQLite, no engine startup. Verifies:

1. The typed DecisionRecord path produces the same response shape as the
   original dict-based code (public contract preserved).
2. When ``full_pipeline_json`` is missing (pre-migration-019 row), the
   pre-019 note path still fires.
3. When the row shape would fail Pydantic validation (e.g. unknown action
   string), the raw-dict fallback path produces a response instead of 500.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import decisions_router


class _FakeDBManager:
    def __init__(self, rows: dict[int, Optional[dict[str, Any]]]):
        self.rows = rows
        self.inserted: list[dict] = []

    def get_decision_by_id(self, decision_id: int) -> Optional[dict[str, Any]]:
        return self.rows.get(decision_id)

    def get_decisions(self, symbol: Optional[str] = None, limit: int = 100):
        return list(self.rows.values())[:limit]

    def insert_decision(self, **kwargs: Any) -> int:
        self.inserted.append(kwargs)
        return len(self.inserted)


def _mk_client(rows: dict[int, Optional[dict[str, Any]]]) -> TestClient:
    """Build an isolated FastAPI app mounting only the decisions router."""
    app = FastAPI()
    app.include_router(decisions_router.router)
    decisions_router.set_db_manager(_FakeDBManager(rows))
    return TestClient(app)


def _full_pipeline_payload() -> dict:
    return {
        "analyst_reports": {
            "technical": {
                "signal": 0.4,
                "confidence": 0.65,
                "summary": "Bullish STC cross-above OS",
                "regime": "trending",
                "trend": "uptrend",
                "stc_context": "crossed OS=15",
            },
            "news": {
                "signal": 0.0,
                "confidence": 0.0,
                "summary": "news analyst abstained",
                "regime": None,
                "trend": None,
            },
        },
        "debate_result": {
            "verdict": "bull",
            "debate_score": 0.42,
            "bull_score": 0.68,
            "bear_score": 0.26,
            "summary": "Bull case supported",
            "scoring_failed": False,
        },
        "trade_decision": {
            "action": "buy",
            "confidence": 0.55,
            "reasoning": "Enter on 15m close above VWAP",
            "entry_price": 82.15,
            "stop_price": 81.45,
            "limit_price": 82.20,
            "forced_hold": False,
        },
        "risk_decision": {
            "approved": True,
            "risk_score": 0.22,
            "reasoning": "Within daily loss budget",
            "forced_hold": False,
        },
        "fund_decision": {
            "approved": True,
            "final_quantity": 1,
            "priority": "normal",
            "reasoning": "Standard 1-contract sizing",
        },
        "confidence_gate_triggered": False,
        "raw_confidence": 0.55,
        "boosted_confidence": 0.58,
        "confidence_threshold": 0.50,
        "confidence_gate_reason": None,
        "confidence_scorer_adjustment": 0.03,
        "final_action": "buy",
        "final_quantity": 1,
        "requires_human": False,
        "summary": "BUY MCL 1 contract",
        "errors": [],
        "completed_at": "2026-04-17T16:30:00Z",
    }


def _post_019_row() -> dict:
    return {
        "id": 42,
        "symbol": "MCL",
        "timestamp": "2026-04-17T16:30:00Z",
        "action": "buy",
        "confidence": 0.55,
        "regime": "trending",
        "reasoning": "Full debate approved long",
        "signal_data_json": {"stc": 18.2, "atr": 0.72},
        "full_pipeline_json": _full_pipeline_payload(),
    }


def _pre_019_row() -> dict:
    return {
        "id": 7,
        "symbol": "MNQ",
        "timestamp": "2026-03-01T09:30:00Z",
        "action": "sell",
        "confidence": 0.4,
        "regime": "ranging",
        "reasoning": "Pre-019 legacy row",
        "signal_data_json": {"stc": 85.0},
        "full_pipeline_json": None,
    }


# ---------------------------------------------------------------------------
# Happy path — typed DecisionRecord wiring
# ---------------------------------------------------------------------------


def test_detail_typed_path_preserves_public_contract():
    client = _mk_client({42: _post_019_row()})

    resp = client.get("/decisions/42/detail")

    assert resp.status_code == 200
    body = resp.json()

    # Top-level
    assert body["id"] == 42
    assert body["symbol"] == "MCL"
    assert body["action"] == "buy"
    assert body["confidence"] == pytest.approx(0.55)
    assert body["regime"] == "trending"

    # Stage 1 — analyst summaries
    s1 = body["stage1_analysts"]
    assert "technical" in s1
    assert s1["technical"]["signal"] == pytest.approx(0.4)
    assert s1["technical"]["confidence"] == pytest.approx(0.65)
    assert s1["technical"]["summary"] == "Bullish STC cross-above OS"

    # Stage 2 — debate
    assert body["stage2_debate"]["verdict"] == "bull"
    assert body["stage2_debate"]["scoring_failed"] is False

    # Stage 3 — trader
    assert body["stage3_trader"]["action"] == "buy"
    assert body["stage3_trader"]["entry_price"] == pytest.approx(82.15)
    assert body["stage3_trader"]["forced_hold"] is False

    # Stage 4 — risk
    assert body["stage4_risk"]["approved"] is True
    assert body["stage4_risk"]["risk_score"] == pytest.approx(0.22)

    # Stage 5 — fund
    assert body["stage5_fund"] is not None
    assert body["stage5_fund"]["final_quantity"] == 1
    assert body["stage5_fund"]["priority"] == "normal"

    # Confidence gate
    g = body["confidence_gate"]
    assert g["triggered"] is False
    assert g["raw_confidence"] == pytest.approx(0.55)
    assert g["boosted_confidence"] == pytest.approx(0.58)
    assert g["threshold"] == pytest.approx(0.50)
    assert g["scorer_adjustment"] == pytest.approx(0.03)

    # Final outcome
    assert body["final_action"] == "buy"
    assert body["final_quantity"] == 1
    assert body["requires_human"] is False
    assert body["errors"] == []

    # Raw full pipeline preserved for deep inspection
    assert body["full_pipeline"]["analyst_reports"]["technical"]["signal"] == pytest.approx(0.4)


def test_detail_typed_path_handles_missing_fund_decision():
    row = _post_019_row()
    row["full_pipeline_json"]["fund_decision"] = None
    client = _mk_client({42: row})

    resp = client.get("/decisions/42/detail")
    assert resp.status_code == 200
    assert resp.json()["stage5_fund"] is None


def test_detail_typed_path_handles_partial_debate_failure():
    row = _post_019_row()
    row["full_pipeline_json"]["debate_result"] = {
        "verdict": None,
        "scoring_failed": True,
        "summary": "scoring math broke",
    }
    client = _mk_client({42: row})

    resp = client.get("/decisions/42/detail")
    assert resp.status_code == 200
    assert resp.json()["stage2_debate"]["scoring_failed"] is True
    assert resp.json()["stage2_debate"]["verdict"] is None


# ---------------------------------------------------------------------------
# Pre-migration-019 path
# ---------------------------------------------------------------------------


def test_detail_pre_019_row_returns_note():
    client = _mk_client({7: _pre_019_row()})

    resp = client.get("/decisions/7/detail")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 7
    assert body["symbol"] == "MNQ"
    assert body["full_pipeline"] is None
    assert "note" in body
    assert "migration 019" in body["note"]


# ---------------------------------------------------------------------------
# Fallback path — schema-unparseable row doesn't 500
# ---------------------------------------------------------------------------


def test_detail_schema_validation_failure_falls_through_to_raw_dict():
    # Unknown top-level action ("teleport") — fails DecisionRecord validation.
    # Handler must log + serve raw-dict response, NOT 500.
    row = _post_019_row()
    row["id"] = 99
    row["action"] = "teleport"
    client = _mk_client({99: row})

    resp = client.get("/decisions/99/detail")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 99
    assert body["action"] == "teleport"  # passes through via raw-dict path
    # Stage flattening still works in raw-dict mode
    assert body["stage2_debate"]["verdict"] == "bull"
    assert body["stage3_trader"]["action"] == "buy"


def test_detail_404_on_missing_decision():
    client = _mk_client({})
    resp = client.get("/decisions/999/detail")
    assert resp.status_code == 404


def test_detail_503_when_db_not_wired():
    # Reset the module-level db to None to simulate engine startup incomplete.
    app = FastAPI()
    app.include_router(decisions_router.router)
    decisions_router._db_manager = None  # type: ignore[attr-defined]
    client = TestClient(app)
    try:
        resp = client.get("/decisions/1/detail")
        assert resp.status_code == 503
    finally:
        # Leave the module state clean for other tests in the process
        decisions_router._db_manager = None  # type: ignore[attr-defined]


# ── /decisions/log POST persistence tests ────────────────────────────────────


def _mk_client_with_db() -> tuple[TestClient, _FakeDBManager]:
    """Build a test client with a _FakeDBManager wired in."""
    db = _FakeDBManager({})
    app = FastAPI()
    app.include_router(decisions_router.router)
    decisions_router.set_db_manager(db)
    return TestClient(app), db


def test_log_decision_persists_to_sqlite():
    client, db = _mk_client_with_db()
    payload = {
        "symbol": "MES",
        "action": "buy",
        "confidence": 0.82,
        "source": "pipeline",
        "summary": "STC cross-above",
        "reasoning": "trend confirmed",
        "regime": "trending",
    }
    resp = client.post("/decisions/log", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert len(db.inserted) == 1
    call = db.inserted[0]
    assert call["symbol"] == "MES"
    assert call["action"] == "buy"
    assert abs(call["confidence"] - 0.82) < 1e-6
    assert call["regime"] == "trending"
    assert call["reasoning"] == "trend confirmed"


def test_log_decision_memory_fallback_when_no_db():
    """When _db_manager is None, decision lands in memory ring buffer only."""
    app = FastAPI()
    app.include_router(decisions_router.router)
    decisions_router._db_manager = None  # type: ignore[attr-defined]
    client = TestClient(app)
    try:
        decisions_router._decision_log.clear()
        resp = client.post("/decisions/log", json={"symbol": "MGC", "action": "hold"})
        assert resp.status_code == 200
        assert any(e["symbol"] == "MGC" for e in decisions_router._decision_log)
    finally:
        decisions_router._db_manager = None  # type: ignore[attr-defined]
        decisions_router._decision_log.clear()
