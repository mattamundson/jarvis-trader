"""
E2E test: pending approval → approve → IB order routed.

Tests the full human-gate pipeline offline:
  insert_pending_approval() → POST /pipeline/pending-approvals/{id}/approve → order routed

Uses FastAPI TestClient + in-memory SQLite + mocked OrderRouter.

Router prefix is /pipeline (see approval_router.py line 16).
Endpoints:
  GET  /pipeline/pending-approvals
  GET  /pipeline/pending-approvals/{approval_id}
  POST /pipeline/pending-approvals/{approval_id}/approve
  POST /pipeline/pending-approvals/{approval_id}/reject
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest.mock as mock
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# sys.modules mocking — must happen before importing main
# ---------------------------------------------------------------------------

_MODULES_TO_MOCK = [
    "data.market_data",
    "risk.safety_layer",
    "risk.pnl_monitor",
    "agents.bear_researcher",
    "agents.bull_researcher",
    "agents.debate",
    "agents.fund_manager",
    "agents.fundamental_analyst",
    "agents.news_analyst",
    "agents.risk_manager",
    "agents.social_analyst",
    "agents.technical_analyst",
    "agents.thinkscript_generator",
    "agents.trader",
    "portfolio.tracker",
    "database.schema",
    "schedulers.eod_scheduler",
    "routers.journal_router",
    "routers.webhook_router",
    "execution.ib_order_manager",
    "notifications.whatsapp",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
    "apscheduler.triggers.cron",
    "apscheduler.triggers.interval",
]

_saved_modules: dict = {}
for _mod_name in _MODULES_TO_MOCK:
    _saved_modules[_mod_name] = sys.modules.get(_mod_name)
    sys.modules[_mod_name] = mock.MagicMock()

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from config import settings  # noqa: E402

app = main.app

# Restore real modules after app is imported
for _mod_name, _original in _saved_modules.items():
    if _original is None:
        sys.modules.pop(_mod_name, None)
    else:
        sys.modules[_mod_name] = _original

# Clean parent module attributes for dotted names
for _mod_name in _MODULES_TO_MOCK:
    if "." in _mod_name:
        _parent, _attr = _mod_name.rsplit(".", 1)
        _parent_mod = sys.modules.get(_parent)
        if _parent_mod is not None and hasattr(_parent_mod, _attr):
            try:
                delattr(_parent_mod, _attr)
            except AttributeError:
                pass

# ---------------------------------------------------------------------------
# Fake DB manager backed by a real SQLite temp file
# ---------------------------------------------------------------------------


class _FakeDbManagerWithApprovals:
    """Full db_manager shim with pending_trade_approvals support.

    Mirrors the real PendingApprovalsMixin contract including the
    pipeline_snapshot_json → pipeline_snapshot decode performed by _row_to_dict.
    """

    def __init__(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self._db_path = Path(tmp.name)
        self._lock = threading.Lock()

        conn = sqlite3.connect(str(self._db_path))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                trade_id    TEXT PRIMARY KEY,
                symbol      TEXT NOT NULL,
                side        TEXT NOT NULL DEFAULT 'LONG',
                entry_price REAL,
                exit_price  REAL,
                quantity    INTEGER DEFAULT 1,
                pnl         REAL DEFAULT 0.0,
                status      TEXT DEFAULT 'OPEN',
                entry_time  TEXT,
                exit_time   TEXT,
                strategy_params TEXT,
                notes       TEXT
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT,
                status     TEXT,
                message    TEXT,
                created_at TEXT
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_trade_approvals (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                approval_id            TEXT UNIQUE NOT NULL,
                symbol                 TEXT NOT NULL,
                action                 TEXT NOT NULL,
                quantity               REAL NOT NULL,
                entry_price            REAL,
                status                 TEXT NOT NULL DEFAULT 'pending',
                pipeline_snapshot_json TEXT,
                created_at             TEXT,
                resolved_at            TEXT,
                resolved_by            TEXT,
                rejection_reason       TEXT,
                paper_trade_id         TEXT,
                ib_order_id            TEXT
            )
        """
        )
        conn.commit()
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Decode pipeline_snapshot_json → pipeline_snapshot (mirrors real mixin)."""
        d = dict(row)
        raw = d.pop("pipeline_snapshot_json", None)
        if isinstance(raw, str):
            try:
                d["pipeline_snapshot"] = json.loads(raw)
            except json.JSONDecodeError:
                d["pipeline_snapshot"] = {}
        else:
            d["pipeline_snapshot"] = {}
        return d

    # ── Methods called by tests directly ──────────────────────────────────

    def get_trade_history(self, limit: int = 10000, **kwargs) -> list:
        return []

    def get_closed_trades(self, limit: int = 10000, symbol=None) -> list:
        return []

    def get_alert_history(self, limit: int = 100, alert_type=None) -> list:
        return []

    # ── PendingApprovals methods (mirrors real mixin) ──────────────────────

    def insert_pending_approval(
        self,
        *,
        symbol: str,
        action: str,
        quantity: float,
        entry_price=None,
        pipeline_snapshot: dict,
    ) -> str:
        approval_id = str(uuid.uuid4())
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO pending_trade_approvals
                        (approval_id, symbol, action, quantity, entry_price, status,
                         pipeline_snapshot_json, created_at)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        approval_id,
                        symbol.upper(),
                        action.lower(),
                        float(quantity),
                        float(entry_price) if entry_price is not None else None,
                        json.dumps(pipeline_snapshot, default=str),
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return approval_id

    def list_pending_approvals(self, limit: int = 50) -> list:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT id, approval_id, symbol, action, quantity, entry_price, status,
                           pipeline_snapshot_json, created_at, resolved_at, resolved_by,
                           rejection_reason, paper_trade_id, ib_order_id
                    FROM pending_trade_approvals
                    WHERE status = 'pending'
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
            finally:
                conn.close()

    def get_pending_approval(self, approval_id: str):
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT id, approval_id, symbol, action, quantity, entry_price, status,
                           pipeline_snapshot_json, created_at, resolved_at, resolved_by,
                           rejection_reason, paper_trade_id, ib_order_id
                    FROM pending_trade_approvals
                    WHERE approval_id = ?
                    """,
                    (approval_id,),
                ).fetchone()
                return self._row_to_dict(row) if row else None
            finally:
                conn.close()

    def resolve_pending_approval(
        self,
        approval_id: str,
        *,
        new_status: str,
        resolved_by: str,
        rejection_reason=None,
        paper_trade_id=None,
        ib_order_id=None,
    ) -> bool:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    UPDATE pending_trade_approvals
                    SET status = ?, resolved_at = ?, resolved_by = ?,
                        rejection_reason = ?, paper_trade_id = ?, ib_order_id = ?
                    WHERE approval_id = ? AND status = 'pending'
                    """,
                    (
                        new_status,
                        now,
                        resolved_by,
                        rejection_reason,
                        paper_trade_id,
                        ib_order_id,
                        approval_id,
                    ),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def open_paper_trade(
        self, *, symbol, side, entry_price, quantity, strategy_params=None, notes=None
    ) -> str:
        trade_id = str(uuid.uuid4())
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO paper_trades
                        (trade_id, symbol, side, entry_price, quantity, status,
                         entry_time, strategy_params, notes)
                    VALUES (?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
                    """,
                    (
                        trade_id,
                        symbol,
                        side,
                        entry_price,
                        quantity,
                        now,
                        json.dumps(strategy_params or {}),
                        notes,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return trade_id


# ---------------------------------------------------------------------------
# Fake safety layer
# ---------------------------------------------------------------------------


class _FakeSafetyLayer:
    """Minimal safety_layer stand-in — kill switch OFF by default."""

    def check_circuit_breakers(self) -> dict:
        return {"daily_limit_breached": False, "drawdown_breached": False}

    def get_status(self) -> dict:
        # The approve endpoint checks: _safety_layer.get_status().get("kill_switch_active")
        return {"kill_switch": False, "kill_switch_active": False, "circuit_breakers": {}}

    def get_lockout_status(self, symbol: str) -> dict:
        return {"locked": False}

    async def submit_paper_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "MKT",
        limit_price: float | None = None,
    ) -> dict:
        """Mock paper order submission — always approves."""
        return {
            "approved": True,
            "reason": "Fake safety layer — approved for testing",
            "order_id": None,
            "routed_to_ib": False,
        }


class _KillSwitchSafetyLayer(_FakeSafetyLayer):
    """Safety layer with kill switch ON — should block approvals."""

    def get_status(self) -> dict:
        # ensure_approval_allowed reads the `is_killed` key (family-fdr dual-key
        # contract); keep the legacy keys too so every consumer sees a consistent
        # status. Without is_killed the kill-switch branch never fires and the
        # approval falls through to the symbol-authorization gate.
        return {
            "is_killed": True,
            "kill_switch": True,
            "kill_switch_active": True,
            "circuit_breakers": {},
        }


# ---------------------------------------------------------------------------
# Helper: build a mock paper_tracker
#
# approval_router.approve_pending calls:
#   trade_id = _paper_tracker.open_trade(
#       symbol=sym, action=action, quantity=qty, price=float(price), notes=notes
#   )
# ---------------------------------------------------------------------------


def _make_paper_tracker() -> MagicMock:
    pt = MagicMock()
    pt.open_trade.return_value = str(uuid.uuid4())
    pt.get_position.return_value = None
    return pt


# ---------------------------------------------------------------------------
# Helper: build a mock order router
# ---------------------------------------------------------------------------


def _make_order_router() -> MagicMock:
    or_ = MagicMock()
    or_.route_order = AsyncMock(return_value={"order_id": "MOCK-001", "status": "submitted"})
    return or_


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------

_AUTH = {"X-API-Key": settings.API_KEY}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestApprovalToOrderE2E:
    """E2E: insert pending approval → approve via API → verify order routed."""

    def _make_client_and_db(
        self,
        safety: _FakeSafetyLayer | None = None,
    ) -> tuple[TestClient, _FakeDbManagerWithApprovals]:
        """Return a TestClient + FakeDb with all dependencies injected."""
        db = _FakeDbManagerWithApprovals()
        sl = safety or _FakeSafetyLayer()
        pt = _make_paper_tracker()
        or_ = _make_order_router()

        # Inject into main module globals
        main.db_manager = db
        main.safety_layer = sl

        # Inject into approval_router module-level globals via inject_dependencies
        from routers import approval_router as _ar

        _ar.inject_dependencies(
            safety_layer=sl,
            paper_tracker=pt,
            db_manager=db,
            order_router=or_,
        )

        client = TestClient(app, raise_server_exceptions=False)
        return client, db

    # ── Test 1: insert + list pending approvals ────────────────────────────

    def test_insert_and_list_pending_approvals(self):
        """Inserted pending approval appears in GET /pipeline/pending-approvals."""
        client, db = self._make_client_and_db()

        approval_id = db.insert_pending_approval(
            symbol="MNQ",
            action="BUY",
            quantity=1,
            entry_price=21000.0,
            pipeline_snapshot={"signal": "long", "confidence": 0.85},
        )
        assert approval_id, "insert_pending_approval must return a non-empty ID"

        # Verify it's in the DB directly
        row = db.get_pending_approval(approval_id)
        assert row is not None, "Row must exist after insertion"
        assert row["symbol"] == "MNQ"
        assert row["status"] == "pending"
        assert row["pipeline_snapshot"]["signal"] == "long"

        # Verify it appears in the list endpoint
        r = client.get("/pipeline/pending-approvals", headers=_AUTH)
        assert (
            r.status_code == 200
        ), f"GET /pipeline/pending-approvals returned {r.status_code}: {r.text}"
        body = r.json()
        # Router returns {"pending": [...], "count": N}
        pending_list = body.get("pending", body if isinstance(body, list) else [])
        ids = [a.get("approval_id") for a in pending_list]
        assert approval_id in ids, f"Approval {approval_id[:8]} not in list response: {body}"

    # ── Test 2: approve endpoint resolves the DB row ───────────────────────

    def test_approve_endpoint_resolves_approval(self):
        """POST /pipeline/pending-approvals/{id}/approve resolves row to 'approved'."""
        client, db = self._make_client_and_db()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="BUY",
            quantity=1,
            entry_price=5823.50,
            pipeline_snapshot={"signal": "long", "summary": "Bull regime"},
        )

        # Patch the gate v2 authorization check: this test exercises the approval
        # flow (DB row → paper trade), not the instrument authorization gate.
        # VALIDATION_ONLY_INSTRUMENTS check is covered by test_approval_service.py.
        with patch(
            "backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "test bypass")
        ):
            r = client.post(
                f"/pipeline/pending-approvals/{approval_id}/approve",
                headers=_AUTH,
            )

        assert r.status_code == 200, f"Approve returned {r.status_code}: {r.text}"

        body = r.json()
        assert body.get("status") == "approved", f"Unexpected body status: {body}"
        assert body.get("approval_id") == approval_id
        assert body.get("symbol") == "MES"

        # Verify DB row is resolved
        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["status"] == "approved", f"Expected 'approved', got: {row['status']}"
        assert row["paper_trade_id"] is not None, "paper_trade_id must be set after approve"
        assert row["resolved_by"] == "api"

    # ── Test 3: approve routes order to IB ────────────────────────────────

    def test_approve_routes_order_to_ib(self):
        """Approve populates execution result from OrderRouter."""
        db = _FakeDbManagerWithApprovals()
        sl = _FakeSafetyLayer()
        pt = _make_paper_tracker()
        or_ = _make_order_router()

        from routers import approval_router as _ar

        _ar.inject_dependencies(
            safety_layer=sl,
            paper_tracker=pt,
            db_manager=db,
            order_router=or_,
        )
        main.db_manager = db
        main.safety_layer = sl

        # Use MES (in default config watchlist), not MGC (only in .env override).
        # Tests run from project root where engine/.env isn't on load_dotenv() path.
        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="BUY",
            quantity=2,
            entry_price=5823.50,
            pipeline_snapshot={"signal": "long"},
        )

        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "test bypass")
        ):
            r = client.post(
                f"/pipeline/pending-approvals/{approval_id}/approve",
                headers=_AUTH,
            )

        assert r.status_code == 200, f"Approve returned {r.status_code}: {r.text}"
        body = r.json()

        # execution block must be present — routed through submit_paper_order
        # (post-refactor 7f1f0e0: approval flow calls SafetyLayer.submit_paper_order
        # instead of OrderRouter.route_order directly)
        execution = body.get("execution")
        assert execution is not None, f"No 'execution' field in response: {body}"
        assert execution.get("approved") is True, f"Expected approved=True, got: {execution}"

    # ── Test 4: reject endpoint resolves the DB row ────────────────────────

    def test_reject_endpoint_resolves_approval(self):
        """POST /pipeline/pending-approvals/{id}/reject resolves row to 'rejected'."""
        client, db = self._make_client_and_db()

        approval_id = db.insert_pending_approval(
            symbol="MNQ",
            action="SELL",
            quantity=1,
            entry_price=21500.0,
            pipeline_snapshot={"signal": "short"},
        )

        r = client.post(
            f"/pipeline/pending-approvals/{approval_id}/reject",
            json={"reason": "Manual override — test"},
            headers=_AUTH,
        )
        assert r.status_code == 200, f"Reject returned {r.status_code}: {r.text}"

        body = r.json()
        assert body.get("status") == "rejected", f"Unexpected body status: {body}"
        assert body.get("approval_id") == approval_id

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["status"] == "rejected", f"Expected 'rejected', got: {row['status']}"
        assert (
            "override" in (row.get("rejection_reason") or "").lower()
        ), f"Rejection reason not persisted: {row.get('rejection_reason')}"

    # ── Test 5: double-approve returns 409 ────────────────────────────────

    def test_double_approve_returns_409(self):
        """Second approve on an already-resolved approval must return 409 Conflict."""
        client, db = self._make_client_and_db()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="BUY",
            quantity=1,
            entry_price=5823.50,
            pipeline_snapshot={},
        )

        with patch(
            "backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "test bypass")
        ):
            # First approve
            r1 = client.post(
                f"/pipeline/pending-approvals/{approval_id}/approve",
                headers=_AUTH,
            )
            assert r1.status_code == 200, f"First approve failed: {r1.status_code} — {r1.text}"

            # Second approve — must be 409 (already resolved)
            r2 = client.post(
                f"/pipeline/pending-approvals/{approval_id}/approve",
                headers=_AUTH,
            )
        assert (
            r2.status_code == 409
        ), f"Expected 409 on double-approve, got {r2.status_code} — {r2.text}"

    # ── Test 6: approve unknown ID returns 404 ─────────────────────────────

    def test_approve_unknown_id_returns_404(self):
        """Approving a non-existent approval_id must return 404."""
        client, db = self._make_client_and_db()

        fake_id = str(uuid.uuid4())
        r = client.post(
            f"/pipeline/pending-approvals/{fake_id}/approve",
            headers=_AUTH,
        )
        assert (
            r.status_code == 404
        ), f"Expected 404 for unknown approval, got {r.status_code} — {r.text}"

    # ── Test 7: kill switch blocks approve ─────────────────────────────────

    def test_kill_switch_blocks_approve(self):
        """When kill switch is active, approve must return 409 (kill switch active)."""
        client, db = self._make_client_and_db(safety=_KillSwitchSafetyLayer())

        approval_id = db.insert_pending_approval(
            symbol="MNQ",
            action="BUY",
            quantity=1,
            entry_price=21000.0,
            pipeline_snapshot={},
        )

        r = client.post(
            f"/pipeline/pending-approvals/{approval_id}/approve",
            headers=_AUTH,
        )
        # approval_router raises HTTPException(409, "Kill switch active — cannot approve")
        assert (
            r.status_code == 409
        ), f"Expected 409 with kill switch active, got {r.status_code} — {r.text}"
        assert "kill switch" in r.text.lower(), f"Response should mention kill switch: {r.text}"

    # ── Test 8: approve with price override ────────────────────────────────

    def test_approve_with_price_override(self):
        """POST body entry_price overrides the stored entry_price."""
        db = _FakeDbManagerWithApprovals()
        sl = _FakeSafetyLayer()
        pt = _make_paper_tracker()
        or_ = _make_order_router()

        from routers import approval_router as _ar

        _ar.inject_dependencies(
            safety_layer=sl,
            paper_tracker=pt,
            db_manager=db,
            order_router=or_,
        )
        main.db_manager = db
        main.safety_layer = sl

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="BUY",
            quantity=1,
            entry_price=5823.50,
            pipeline_snapshot={},
        )

        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "test bypass")
        ):
            r = client.post(
                f"/pipeline/pending-approvals/{approval_id}/approve",
                json={"entry_price": 5825.0},
                headers=_AUTH,
            )

        assert r.status_code == 200, f"Approve with override returned {r.status_code}: {r.text}"
        body = r.json()
        assert (
            body.get("entry_price") == 5825.0
        ), f"Expected overridden price 5825.0, got {body.get('entry_price')}"
        # Verify open_trade was called with the overridden price
        call_kwargs = pt.open_trade.call_args
        assert call_kwargs is not None
        assert (
            call_kwargs.kwargs.get("price") == 5825.0
        ), f"open_trade price mismatch: {call_kwargs}"

    # ── Test 9: get single pending approval ────────────────────────────────

    def test_get_single_pending_approval(self):
        """GET /pipeline/pending-approvals/{id} returns the approval row."""
        client, db = self._make_client_and_db()

        approval_id = db.insert_pending_approval(
            symbol="MCL",
            action="BUY",
            quantity=3,
            entry_price=68.5,
            pipeline_snapshot={"confidence": 0.9},
        )

        r = client.get(
            f"/pipeline/pending-approvals/{approval_id}",
            headers=_AUTH,
        )
        assert r.status_code == 200, f"GET single approval returned {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("approval_id") == approval_id
        assert body.get("symbol") == "MCL"
        assert body.get("quantity") == 3.0
        assert body.get("status") == "pending"
