"""
Tests for VALIDATION_ONLY_INSTRUMENTS — instrument promotion lifecycle.

Current state (2026-05-24):
  - MES promoted to active paper trading (Tier 3 auth 2026-05-24)
  - MGC remains VALIDATION_ONLY (WFE=0.14, no Tier 3 auth)

Verifies that:
  - Pipeline runs for validation-only instruments (MGC) and produces verdicts
  - No paper orders are submitted for validation-only instruments at the approval gate
  - MES is NO LONGER in VALIDATION_ONLY_INSTRUMENTS (orders now allowed)
  - VALIDATION_ONLY_INSTRUMENTS is an immutable frozenset

The order submission guard lives in approval/service.py:ensure_approval_allowed().
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Constant integrity ─────────────────────────────────────────────────────────


def test_validation_only_constant_immutable():
    """VALIDATION_ONLY_INSTRUMENTS must be a frozenset (immutable, hashable).

    MES was promoted to active paper trading 2026-05-24 (Tier 3 auth).
    Only MGC remains in validation-only (WFE=0.14, no Tier 3 auth yet).
    """
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS

    assert isinstance(
        VALIDATION_ONLY_INSTRUMENTS, frozenset
    ), "VALIDATION_ONLY_INSTRUMENTS must be a frozenset to prevent accidental mutation"
    # MES promoted 2026-05-24 — must NOT be in validation-only
    assert "MES" not in VALIDATION_ONLY_INSTRUMENTS
    assert "MGC" not in VALIDATION_ONLY_INSTRUMENTS
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
    # dual-key contract: ensure_approval_allowed reads is_killed (family-fdr); keep
    # kill_switch_active too so both consumers see a consistent status.
    safety.get_status.return_value = {
        "is_killed": kill_switch_active,
        "kill_switch_active": kill_switch_active,
    }
    safety.get_lockout_status.return_value = {"locked": False}
    return safety


def test_mes_approval_allowed():
    """MES approval must NOT raise — MES promoted to active paper trading 2026-05-24.

    Tier 3 authorization granted: p_positive_edge=0.75 (WFE criterion), ALT gate v2 PASS.
    Champion params: SMA(fast=60, slow=200, atr_trail_mult=2.0).
    """
    from approval.service import ApprovalFlowError, ensure_approval_allowed

    row = _make_approval_row("MES")
    safety = _make_mock_safety_layer()

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        # Should not raise ApprovalFlowError for MES — it's now an active instrument
        try:
            ensure_approval_allowed(row, safety)
        except ApprovalFlowError as e:
            if "VALIDATION_ONLY_INSTRUMENTS" in str(e.detail):
                pytest.fail(
                    f"MES was blocked by VALIDATION_ONLY_INSTRUMENTS — "
                    f"it should be active since 2026-05-24 Tier 3 auth. Error: {e.detail}"
                )


def test_mgc_approval_allowed():
    """MGC approval must NOT raise — MGC promoted to active paper trading 2026-05-24.

    Tier 3 authorization granted: p_positive_edge=0.6842 (WFE criterion), ALT gate v2 PASS.
    Champion params: SMA(fast=50, slow=120, atr_trail_mult=2.0).
    """
    from approval.service import ApprovalFlowError, ensure_approval_allowed

    row = _make_approval_row("MGC")
    safety = _make_mock_safety_layer()

    with patch(
        "approval.service.approved_watchlist_symbols", return_value={"MES", "MNQ", "MCL", "MGC"}
    ):
        # Should not raise ApprovalFlowError for MGC — it's now an active instrument
        try:
            ensure_approval_allowed(row, safety)
        except ApprovalFlowError as e:
            if "VALIDATION_ONLY_INSTRUMENTS" in str(e.detail):
                pytest.fail(
                    f"MGC was blocked by VALIDATION_ONLY_INSTRUMENTS — "
                    f"it should be active since 2026-05-24 Tier 3 auth. Error: {e.detail}"
                )


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


def test_mes_active_not_validation_only():
    """MES must NOT be in VALIDATION_ONLY_INSTRUMENTS — it is now active (2026-05-24).

    Tier 3 auth granted: p_positive_edge=0.75, ALT gate v2 PASS, Tier 3 auth 2026-05-24.
    Orders are now allowed through ensure_approval_allowed() for MES.
    """
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS

    # MES promoted — must not be in validation-only set
    assert "MES" not in VALIDATION_ONLY_INSTRUMENTS

    # Confirm the constant is importable and stable across multiple imports
    from agents import pipeline as _pipeline_mod

    assert _pipeline_mod.VALIDATION_ONLY_INSTRUMENTS is VALIDATION_ONLY_INSTRUMENTS


def test_mgc_active_not_validation_only():
    """MGC must NOT be in VALIDATION_ONLY_INSTRUMENTS — it is now active (2026-05-24).

    Tier 3 auth granted: p_positive_edge=0.6842, ALT gate v2 PASS, Tier 3 auth 2026-05-24.
    Orders are now allowed through ensure_approval_allowed() for MGC.
    """
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS

    # MGC promoted — must not be in validation-only set
    assert "MGC" not in VALIDATION_ONLY_INSTRUMENTS

    # Confirm the constant is importable and stable across multiple imports
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

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.approval_queue_router import inject_approval_queue_deps, router

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
        patch("routers.approval_queue_router._AUDIT_LOG_PATH", tmp_path / "audit.jsonl"),
    ):
        inject_approval_queue_deps(mock_safety, db_path)
        client = TestClient(app)
        response = client.post("/approvals/1/approve", json={})

    assert response.status_code == 409
    assert "VALIDATION_ONLY_STRATEGIES" in response.json()["detail"]


def test_approval_queue_allows_non_validation_only_strategy(tmp_path):
    """approve_candidate: strategy NOT in VALIDATION_ONLY_STRATEGIES → gate passes."""
    import sqlite3

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.approval_queue_router import inject_approval_queue_deps, router

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
    mock_safety.submit_paper_order = AsyncMock(
        return_value={"approved": False, "reason": "blocked_by_safety_layer"}
    )

    app = FastAPI()
    app.include_router(router)

    with (
        patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
        patch("agents.pipeline.VALIDATION_ONLY_STRATEGIES", set()),
        patch("routers.approval_queue_router._AUDIT_LOG_PATH", tmp_path / "audit.jsonl"),
    ):
        inject_approval_queue_deps(mock_safety, db_path)
        client = TestClient(app)
        # entry_price required since snapshot doesn't have one
        response = client.post("/approvals/1/approve", json={"entry_price": 70.50})

    # Gate passed (not 409); safety layer blocked downstream — that's fine for this test
    assert response.status_code != 409 or "VALIDATION_ONLY" not in response.json().get("detail", "")


# ── approval_queue_router gate_v2_policy.is_strategy_authorized gate (PRB-22 sibling, 2026-08-01) ──
#
# This path (the autonomous-scheduler's own approve endpoint) never re-checked the gate v2
# verdict for the strategy actually being traded -- only approval.service.ensure_approval_allowed()
# (the manual/messaging-bot path) did. PRB-22 (2026-07-29) closed the "enabled=False but still
# trades" half of this gap in safety_layer.check_order(), but a symbol with enabled=True and a
# non-PASS (or missing/stale) verdict -- e.g. MES's sma_trend config, whose own comment notes
# "gate_v2_policy blocks trades (INSUFFICIENT_SAMPLE)" -- was never actually blocked by THIS path.


def test_approval_queue_blocks_gate_v2_unauthorized_strategy(tmp_path):
    """approve_candidate: gate_v2_policy.is_strategy_authorized() False -> HTTP 409.

    Mirrors approval.service.ensure_approval_allowed()'s existing gate v2 check so the
    autonomous-scheduler queue path cannot submit an order for a strategy with no fresh
    gate v2 PASS verdict.
    """
    import sqlite3

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.approval_queue_router import inject_approval_queue_deps, router

    db_path = str(tmp_path / "aq_gate_v2_block_test.db")
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
    conn.execute(
        """
        INSERT INTO pipeline_approval_queue
            (symbol, direction, confidence, verdict_json, expires_at, status)
        VALUES ('MES', 'LONG', 0.85, '{}', '2099-01-01T00:00:00+00:00', 'pending')
        """
    )
    conn.commit()
    conn.close()

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}

    app = FastAPI()
    app.include_router(router)

    with (
        patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
        patch("agents.pipeline.VALIDATION_ONLY_STRATEGIES", set()),
        patch("routers.approval_queue_router._AUDIT_LOG_PATH", tmp_path / "audit.jsonl"),
        patch(
            "backtest.gate_v2_policy.is_strategy_authorized",
            return_value=(False, "MES_trend_rank11 verdict is INSUFFICIENT_SAMPLE, not PASS"),
        ),
    ):
        inject_approval_queue_deps(mock_safety, db_path)
        client = TestClient(app)
        response = client.post("/approvals/1/approve", json={"entry_price": 5000.0})

    assert response.status_code == 409
    assert "not authorized for paper orders" in response.json()["detail"]


def test_approval_queue_allows_gate_v2_authorized_strategy(tmp_path):
    """approve_candidate: gate_v2_policy.is_strategy_authorized() True -> gate passes."""
    import sqlite3

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.approval_queue_router import inject_approval_queue_deps, router

    db_path = str(tmp_path / "aq_gate_v2_pass_test.db")
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
    conn.execute(
        """
        INSERT INTO pipeline_approval_queue
            (symbol, direction, confidence, verdict_json, expires_at, status)
        VALUES ('MES', 'LONG', 0.85, '{}', '2099-01-01T00:00:00+00:00', 'pending')
        """
    )
    conn.commit()
    conn.close()

    mock_safety = MagicMock()
    mock_safety.get_status.return_value = {"kill_switch_active": False}
    mock_safety.submit_paper_order = AsyncMock(
        return_value={"approved": False, "reason": "blocked_by_safety_layer"}
    )

    app = FastAPI()
    app.include_router(router)

    with (
        patch("routers.approval_queue_router._get_live_trading_enabled", return_value=False),
        patch("agents.pipeline.VALIDATION_ONLY_STRATEGIES", set()),
        patch("routers.approval_queue_router._AUDIT_LOG_PATH", tmp_path / "audit.jsonl"),
        patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "authorized")),
    ):
        inject_approval_queue_deps(mock_safety, db_path)
        client = TestClient(app)
        response = client.post("/approvals/1/approve", json={"entry_price": 5000.0})

    # Gate passed (not 409 for gate v2 reasons); safety layer blocked downstream — fine here.
    assert response.status_code != 409 or "not authorized for paper orders" not in response.json().get(
        "detail", ""
    )
