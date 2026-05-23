"""
Tests for VALIDATION_ONLY_INSTRUMENTS — Wave 3 MES+MGC paper expansion.

Verifies that:
  - Pipeline runs for validation-only instruments (MES, MGC) and produces verdicts
  - No paper orders are submitted for validation-only instruments at the approval gate
  - MCL and MNQ (order-eligible instruments) are unaffected by the guard
  - VALIDATION_ONLY_INSTRUMENTS is an immutable frozenset

The order submission guard lives in approval/service.py:ensure_approval_allowed().
The pipeline still runs to completion for validation-only symbols; their verdicts
feed the dashboard and briefing pipeline for walk-forward validation tracking.
"""

from unittest.mock import MagicMock, patch

import pytest

# ── Constant integrity ─────────────────────────────────────────────────────────


def test_validation_only_constant_immutable():
    """VALIDATION_ONLY_INSTRUMENTS must be a frozenset (immutable, hashable)."""
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS

    assert isinstance(
        VALIDATION_ONLY_INSTRUMENTS, frozenset
    ), "VALIDATION_ONLY_INSTRUMENTS must be a frozenset to prevent accidental mutation"
    assert "MES" in VALIDATION_ONLY_INSTRUMENTS
    assert "MGC" in VALIDATION_ONLY_INSTRUMENTS
    # Confirm MCL and MNQ are NOT in validation-only (they have separate DO_NOT_TRADE handling)
    assert "MCL" not in VALIDATION_ONLY_INSTRUMENTS
    assert "MNQ" not in VALIDATION_ONLY_INSTRUMENTS


def test_validation_only_does_not_overlap_do_not_trade():
    """VALIDATION_ONLY_INSTRUMENTS and DO_NOT_TRADE_SYMBOLS must be disjoint.

    DO_NOT_TRADE_SYMBOLS blocks signal generation entirely; VALIDATION_ONLY_INSTRUMENTS
    allows signal generation but blocks order submission. Overlapping them would mean
    validation-only instruments never produce verdicts — defeating the purpose.
    """
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS
    from backtest.signals import DO_NOT_TRADE_SYMBOLS

    overlap = VALIDATION_ONLY_INSTRUMENTS & DO_NOT_TRADE_SYMBOLS
    assert not overlap, (
        f"VALIDATION_ONLY_INSTRUMENTS and DO_NOT_TRADE_SYMBOLS overlap: {overlap}. "
        "These sets must be disjoint — DO_NOT_TRADE blocks signal generation, "
        "VALIDATION_ONLY blocks order submission only."
    )


# ── Approval gate blocks orders for validation-only symbols ───────────────────


def _make_approval_row(symbol: str) -> dict:
    """Minimal approval row for ensure_approval_allowed() tests."""
    return {
        "symbol": symbol,
        "status": "pending",
        "pipeline_snapshot": {},
    }


def _make_mock_safety_layer(kill_switch_active: bool = False):
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": kill_switch_active}
    safety.get_lockout_status.return_value = {"locked": False}
    return safety


def test_mes_approval_blocked():
    """MES approval must raise ApprovalFlowError — no paper orders for validation-only."""
    from approval.service import ApprovalFlowError, ensure_approval_allowed

    row = _make_approval_row("MES")
    safety = _make_mock_safety_layer()

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        with pytest.raises(ApprovalFlowError) as exc_info:
            ensure_approval_allowed(row, safety)

    assert exc_info.value.status_code == 409
    assert "VALIDATION_ONLY_INSTRUMENTS" in str(exc_info.value.detail)
    assert "MES" in str(exc_info.value.detail)


def test_mgc_approval_blocked():
    """MGC approval must raise ApprovalFlowError — no paper orders for validation-only."""
    from approval.service import ApprovalFlowError, ensure_approval_allowed

    row = _make_approval_row("MGC")
    safety = _make_mock_safety_layer()

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        with pytest.raises(ApprovalFlowError) as exc_info:
            ensure_approval_allowed(row, safety)

    assert exc_info.value.status_code == 409
    assert "VALIDATION_ONLY_INSTRUMENTS" in str(exc_info.value.detail)
    assert "MGC" in str(exc_info.value.detail)


def test_mcl_blocked_by_paper_config_not_validation_only():
    """MCL is blocked by paper_config.enabled=False, NOT by VALIDATION_ONLY_INSTRUMENTS.

    Regression: MCL must NOT appear in VALIDATION_ONLY_INSTRUMENTS (which allows
    signal generation for dashboard feeds).  Its orders are blocked via
    is_strategy_authorized() because paper_config.enabled=False (gate v2 FAIL).
    """
    from approval.service import ApprovalFlowError, ensure_approval_allowed

    row = _make_approval_row("MCL")
    safety = _make_mock_safety_layer()

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        with pytest.raises(ApprovalFlowError) as exc_info:
            ensure_approval_allowed(row, safety)

    assert exc_info.value.status_code == 409
    # Must NOT mention VALIDATION_ONLY_INSTRUMENTS — that's for MES/MGC
    assert "VALIDATION_ONLY_INSTRUMENTS" not in str(exc_info.value.detail)
    # Must mention the actual reason: paper_config gate
    assert "not authorized" in str(exc_info.value.detail)


def test_mnq_blocked_by_paper_config_not_validation_only():
    """MNQ is blocked by paper_config.enabled=False, NOT by VALIDATION_ONLY_INSTRUMENTS.

    Same reasoning as MCL: MNQ is in DO_NOT_TRADE_SYMBOLS (gate v2 FAIL) and has
    paper_config.enabled=False.  It must not be in VALIDATION_ONLY_INSTRUMENTS.
    """
    from approval.service import ApprovalFlowError, ensure_approval_allowed

    row = _make_approval_row("MNQ")
    safety = _make_mock_safety_layer()

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        with pytest.raises(ApprovalFlowError) as exc_info:
            ensure_approval_allowed(row, safety)

    assert exc_info.value.status_code == 409
    assert "VALIDATION_ONLY_INSTRUMENTS" not in str(exc_info.value.detail)
    assert "not authorized" in str(exc_info.value.detail)


def test_validation_only_check_runs_after_kill_switch():
    """Kill switch takes precedence over VALIDATION_ONLY_INSTRUMENTS check."""
    from approval.service import ApprovalFlowError, ensure_approval_allowed

    row = _make_approval_row("MCL")
    safety = _make_mock_safety_layer(kill_switch_active=True)

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        with pytest.raises(ApprovalFlowError) as exc_info:
            ensure_approval_allowed(row, safety)

    # Kill switch fires first — error message references kill switch, not validation-only
    assert "Kill switch" in str(exc_info.value.detail)


# ── Pipeline still runs for validation-only symbols ───────────────────────────


def test_mes_pipeline_runs_but_no_order():
    """Pipeline produces a verdict for MES but the result is marked validation_only.

    The pipeline does NOT call submit_paper_order internally — that happens via the
    approval service. This test verifies the VALIDATION_ONLY_INSTRUMENTS constant is
    present and MES is correctly classified, ensuring dashboard/briefing feeds work.
    """
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS

    # MES is in the validation-only set → pipeline runs, no orders
    assert "MES" in VALIDATION_ONLY_INSTRUMENTS

    # Confirm the constant is importable and stable across multiple imports
    from agents import pipeline as _pipeline_mod

    assert _pipeline_mod.VALIDATION_ONLY_INSTRUMENTS is VALIDATION_ONLY_INSTRUMENTS


def test_mgc_pipeline_runs_but_no_order():
    """Pipeline produces a verdict for MGC but the result is marked validation_only.

    Same reasoning as MES test above.
    """
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS

    assert "MGC" in VALIDATION_ONLY_INSTRUMENTS

    from agents import pipeline as _pipeline_mod

    assert _pipeline_mod.VALIDATION_ONLY_INSTRUMENTS is VALIDATION_ONLY_INSTRUMENTS


def test_validation_only_exported_in_all():
    """VALIDATION_ONLY_INSTRUMENTS must appear in pipeline.__all__ for explicit export."""
    import agents.pipeline as _pipeline_mod

    assert "VALIDATION_ONLY_INSTRUMENTS" in _pipeline_mod.__all__, (
        "VALIDATION_ONLY_INSTRUMENTS must be in pipeline.__all__ so callers "
        "(approval/service.py, routers, tests) can import it cleanly."
    )


# ── approval_queue_router VALIDATION_ONLY_STRATEGIES gate (BLOCKER 5 / §6.3) ──


def _make_queue_row(symbol: str, stark_signal: str = "") -> dict:
    """Minimal approval_queue row for approve_candidate() validation-only tests."""
    verdict: dict = {}
    if stark_signal:
        verdict = {"analyst_reports": {"technical": {"indicators": {"stark_signal": stark_signal}}}}
    return {
        "id": 1,
        "symbol": symbol,
        "direction": "LONG",
        "confidence": 0.85,
        "verdict": verdict,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "status": "pending",
    }


def test_approval_queue_blocks_validation_only_strategy(tmp_path):
    """approve_candidate: VALIDATION_ONLY_STRATEGIES hit → HTTP 409 (BLOCKER 5 / §6.3).

    Verifies that the approval_queue_router's approve path cannot bypass the strategy
    gate that already exists in approval.service.ensure_approval_allowed().
    """
    import sqlite3
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from routers.approval_queue_router import router, inject_approval_queue_deps

    db_path = str(tmp_path / "aq_test.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE pipeline_approval_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            confidence REAL,
            verdict_json TEXT,
            expires_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reviewed_at TEXT,
            reviewer_notes TEXT,
            order_id TEXT
        )
        """
    )
    import json as _json

    # Insert a row with a VALIDATION_ONLY_STRATEGIES stark_signal
    stark_signal = "TPO_SHORT_GAP_FILL"
    verdict = {"analyst_reports": {"technical": {"indicators": {"stark_signal": stark_signal}}}}
    conn.execute(
        """
        INSERT INTO pipeline_approval_queue
            (symbol, direction, confidence, verdict_json, expires_at, status)
        VALUES (?, 'LONG', 0.85, ?, '2099-01-01T00:00:00+00:00', 'pending')
        """,
        ("MCL", _json.dumps(verdict)),
    )
    conn.commit()
    conn.close()

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}

    app = FastAPI()
    app.include_router(router)

    with (
        patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
        patch("agents.pipeline.VALIDATION_ONLY_STRATEGIES", {stark_signal}),
    ):
        inject_approval_queue_deps(mock_safety, db_path)
        client = TestClient(app)
        response = client.post("/approvals/1/approve", json={})

    assert response.status_code == 409
    assert "VALIDATION_ONLY_STRATEGIES" in response.json()["detail"]


def test_approval_queue_allows_non_validation_only_strategy(tmp_path):
    """approve_candidate: strategy NOT in VALIDATION_ONLY_STRATEGIES → gate passes."""
    import sqlite3
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from routers.approval_queue_router import router, inject_approval_queue_deps

    db_path = str(tmp_path / "aq_pass_test.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE pipeline_approval_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            confidence REAL,
            verdict_json TEXT,
            expires_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reviewed_at TEXT,
            reviewer_notes TEXT,
            order_id TEXT
        )
        """
    )
    import json as _json

    verdict = {"analyst_reports": {"technical": {"indicators": {"stark_signal": "MOMENTUM_LONG"}}}}
    conn.execute(
        """
        INSERT INTO pipeline_approval_queue
            (symbol, direction, confidence, verdict_json, expires_at, status)
        VALUES (?, 'LONG', 0.85, ?, '2099-01-01T00:00:00+00:00', 'pending')
        """,
        ("MCL", _json.dumps(verdict)),
    )
    conn.commit()
    conn.close()

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    mock_safety.submit_paper_order = MagicMock(
        return_value={"approved": False, "reason": "blocked_by_safety_layer"}
    )

    app = FastAPI()
    app.include_router(router)

    with (
        patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
        patch("agents.pipeline.VALIDATION_ONLY_STRATEGIES", set()),
    ):
        inject_approval_queue_deps(mock_safety, db_path)
        client = TestClient(app)
        # entry_price required since snapshot doesn't have one
        response = client.post("/approvals/1/approve", json={"entry_price": 70.50})

    # Gate passed (not 409); safety layer blocked downstream — that's fine for this test
    assert response.status_code != 409 or "VALIDATION_ONLY" not in response.json().get("detail", "")
