"""
JARVIS TRADER — Pending Approvals Tests
Comprehensive testing of PendingApprovalsMixin (pending trade approvals).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from database.manager import DatabaseManager


class TestInsertPendingApproval:
    """Test insertion of pending trade approvals."""

    def test_insert_returns_uuid(self, tmp_path: Path) -> None:
        """insert_pending_approval returns a UUID string."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={"test": "data"},
        )

        assert isinstance(approval_id, str)
        assert len(approval_id) == 36  # UUID format: 8-4-4-4-12
        assert approval_id.count("-") == 4  # Standard UUID separator count

    def test_insert_uppercase_symbol(self, tmp_path: Path) -> None:
        """insert_pending_approval converts symbol to uppercase."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="mes",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["symbol"] == "MES"

    def test_insert_lowercase_action(self, tmp_path: Path) -> None:
        """insert_pending_approval converts action to lowercase."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="BUY",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["action"] == "buy"

    def test_insert_none_entry_price(self, tmp_path: Path) -> None:
        """insert_pending_approval accepts None for entry_price."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=None,
            pipeline_snapshot={},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["entry_price"] is None

    def test_insert_sets_status_pending(self, tmp_path: Path) -> None:
        """insert_pending_approval always sets status=pending."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["status"] == "pending"


class TestListPendingApprovals:
    """Test listing pending approvals."""

    def test_list_pending_returns_inserted(self, tmp_path: Path) -> None:
        """list_pending_approvals returns inserted row."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={"test": "data"},
        )

        rows = db.list_pending_approvals()
        assert len(rows) == 1
        assert rows[0]["approval_id"] == approval_id
        assert rows[0]["symbol"] == "MES"
        assert rows[0]["action"] == "buy"

    def test_list_pending_excludes_resolved(self, tmp_path: Path) -> None:
        """list_pending_approvals excludes resolved (non-pending) rows."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id_1 = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )
        approval_id_2 = db.insert_pending_approval(
            symbol="MNQ",
            action="sell",
            quantity=1.0,
            entry_price=20000.0,
            pipeline_snapshot={},
        )

        # Resolve first one
        db.resolve_pending_approval(
            approval_id_1,
            new_status="approved",
            resolved_by="test_user",
        )

        # List should only return the unresolved one
        rows = db.list_pending_approvals()
        assert len(rows) == 1
        assert rows[0]["approval_id"] == approval_id_2

    def test_list_pending_respects_limit(self, tmp_path: Path) -> None:
        """list_pending_approvals respects limit parameter."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        # Insert 5 approvals
        for i in range(5):
            db.insert_pending_approval(
                symbol="MES",
                action="buy",
                quantity=float(i + 1),
                entry_price=5800.0 + i,
                pipeline_snapshot={},
            )

        # Test with limit=2
        rows = db.list_pending_approvals(limit=2)
        assert len(rows) == 2

        # Test with limit=10 (more than inserted)
        rows = db.list_pending_approvals(limit=10)
        assert len(rows) == 5

    def test_list_pending_orders_newest_first(self, tmp_path: Path) -> None:
        """list_pending_approvals returns rows newest first."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        id_1 = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )
        id_2 = db.insert_pending_approval(
            symbol="MNQ",
            action="sell",
            quantity=1.0,
            entry_price=20000.0,
            pipeline_snapshot={},
        )

        rows = db.list_pending_approvals()
        assert len(rows) == 2
        assert rows[0]["approval_id"] == id_2  # Second one should be first
        assert rows[1]["approval_id"] == id_1


class TestGetPendingApproval:
    """Test fetching individual pending approval by ID."""

    def test_get_pending_approval_by_id(self, tmp_path: Path) -> None:
        """get_pending_approval returns correct row by id."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.5,
            entry_price=5800.0,
            pipeline_snapshot={"key": "value"},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["approval_id"] == approval_id
        assert row["symbol"] == "MES"
        assert row["action"] == "buy"
        assert row["quantity"] == 1.5
        assert row["entry_price"] == 5800.0
        assert row["status"] == "pending"

    def test_get_pending_approval_not_found(self, tmp_path: Path) -> None:
        """get_pending_approval returns None for unknown id."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        row = db.get_pending_approval("nonexistent-uuid-1234")
        assert row is None

    def test_get_pending_approval_returns_all_columns(self, tmp_path: Path) -> None:
        """get_pending_approval returns all table columns."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None

        # Check all expected columns exist
        expected_columns = [
            "id",
            "approval_id",
            "symbol",
            "action",
            "quantity",
            "entry_price",
            "status",
            "pipeline_snapshot",
            "created_at",
            "resolved_at",
            "resolved_by",
            "rejection_reason",
            "paper_trade_id",
            "ib_order_id",
        ]
        for col in expected_columns:
            assert col in row


class TestResolvePendingApproval:
    """Test resolving (approving/rejecting) pending approvals."""

    def test_resolve_approve(self, tmp_path: Path) -> None:
        """resolve_pending_approval with 'approved' status returns True and updates row."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        result = db.resolve_pending_approval(
            approval_id,
            new_status="approved",
            resolved_by="test_user",
        )

        assert result is True

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["status"] == "approved"
        assert row["resolved_by"] == "test_user"
        assert row["resolved_at"] is not None

    def test_resolve_reject(self, tmp_path: Path) -> None:
        """resolve_pending_approval with 'rejected' status returns True and updates row."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        result = db.resolve_pending_approval(
            approval_id,
            new_status="rejected",
            resolved_by="test_user",
            rejection_reason="Insufficient margin",
        )

        assert result is True

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["status"] == "rejected"
        assert row["resolved_by"] == "test_user"
        assert row["rejection_reason"] == "Insufficient margin"
        assert row["resolved_at"] is not None

    def test_resolve_with_trade_id(self, tmp_path: Path) -> None:
        """resolve_pending_approval can record paper_trade_id."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        result = db.resolve_pending_approval(
            approval_id,
            new_status="approved",
            resolved_by="test_user",
            paper_trade_id="trade-uuid-123",
        )

        assert result is True

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["paper_trade_id"] == "trade-uuid-123"

    def test_resolve_with_ib_order_id(self, tmp_path: Path) -> None:
        """resolve_pending_approval can record ib_order_id."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        result = db.resolve_pending_approval(
            approval_id,
            new_status="approved",
            resolved_by="test_user",
            ib_order_id="12345",
        )

        assert result is True

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["ib_order_id"] == "12345"

    def test_double_resolve_returns_false(self, tmp_path: Path) -> None:
        """Second resolve on same id returns False (guards idempotency)."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        # First resolve should succeed
        result_1 = db.resolve_pending_approval(
            approval_id,
            new_status="approved",
            resolved_by="test_user",
        )
        assert result_1 is True

        # Second resolve on same id should fail (status no longer pending)
        result_2 = db.resolve_pending_approval(
            approval_id,
            new_status="rejected",
            resolved_by="another_user",
        )
        assert result_2 is False

        # Original status should still be 'approved'
        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["status"] == "approved"
        assert row["resolved_by"] == "test_user"

    def test_resolve_nonexistent_id_returns_false(self, tmp_path: Path) -> None:
        """resolve_pending_approval on nonexistent id returns False."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        result = db.resolve_pending_approval(
            "nonexistent-uuid-123",
            new_status="approved",
            resolved_by="test_user",
        )

        assert result is False


class TestPipelineSnapshot:
    """Test pipeline_snapshot serialization/deserialization."""

    def test_pipeline_snapshot_roundtrip(self, tmp_path: Path) -> None:
        """pipeline_snapshot dict is stored and retrieved correctly."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        snapshot = {
            "symbol": "MES",
            "analyst_reports": {
                "technical": {"signal": 0.8, "confidence": 0.85},
                "news": {"sentiment": "bullish", "score": 0.65},
            },
            "debate_result": {"verdict": "bull", "margin": 5.0},
            "trade_decision": {
                "action": "BUY",
                "quantity": 1,
                "entry_price": 5800.0,
                "stop_price": 5785.0,
            },
        }

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot=snapshot,
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["pipeline_snapshot"] == snapshot

    def test_pipeline_snapshot_with_complex_types(self, tmp_path: Path) -> None:
        """pipeline_snapshot handles complex types via default=str."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        # Create a snapshot with various types
        from datetime import datetime

        snapshot = {
            "timestamp": datetime(2026, 3, 29, 10, 0, 0),
            "nested": {
                "list": [1, 2, 3],
                "dict": {"a": 1, "b": 2},
            },
            "float_value": 123.456,
        }

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot=snapshot,
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        snapshot_retrieved = row["pipeline_snapshot"]

        # datetime should be converted to string
        assert isinstance(snapshot_retrieved["timestamp"], str)
        assert snapshot_retrieved["nested"]["list"] == [1, 2, 3]
        assert snapshot_retrieved["nested"]["dict"] == {"a": 1, "b": 2}
        assert snapshot_retrieved["float_value"] == 123.456

    def test_pipeline_snapshot_empty_dict(self, tmp_path: Path) -> None:
        """pipeline_snapshot accepts empty dict."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["pipeline_snapshot"] == {}


class TestDatabaseInitialization:
    """Test database initialization for approvals."""

    def test_initialize_creates_table(self, tmp_path: Path) -> None:
        """initialize() creates pending_trade_approvals table."""
        db_path = str(tmp_path / "test.db")
        db = DatabaseManager(db_path)
        db.initialize()

        # Should be able to insert without errors
        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        assert isinstance(approval_id, str)

    def test_multiple_initializations_are_safe(self, tmp_path: Path) -> None:
        """initialize() can be called multiple times safely."""
        db_path = str(tmp_path / "test.db")

        db1 = DatabaseManager(db_path)
        db1.initialize()

        approval_id_1 = db1.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        db2 = DatabaseManager(db_path)
        db2.initialize()

        # Should find the previously inserted row
        row = db2.get_pending_approval(approval_id_1)
        assert row is not None
        assert row["approval_id"] == approval_id_1


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_special_characters_in_symbol(self, tmp_path: Path) -> None:
        """Symbols with special characters are handled."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        # Some symbols might have dashes or special chars
        approval_id = db.insert_pending_approval(
            symbol="mes",  # Will be uppercased
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["symbol"] == "MES"

    def test_large_quantity(self, tmp_path: Path) -> None:
        """Large quantities are handled correctly."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=100.5,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["quantity"] == 100.5

    def test_zero_quantity(self, tmp_path: Path) -> None:
        """Zero quantity is accepted (edge case)."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=0.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["quantity"] == 0.0

    def test_very_large_entry_price(self, tmp_path: Path) -> None:
        """Very large entry prices are handled."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=999999.99,
            pipeline_snapshot={},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["entry_price"] == 999999.99

    def test_long_rejection_reason(self, tmp_path: Path) -> None:
        """Long rejection reasons are handled."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        long_reason = "X" * 1000  # Very long rejection reason

        result = db.resolve_pending_approval(
            approval_id,
            new_status="rejected",
            resolved_by="test_user",
            rejection_reason=long_reason,
        )

        assert result is True

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["rejection_reason"] == long_reason

    def test_limit_boundary_min(self, tmp_path: Path) -> None:
        """list_pending_approvals with limit=1 returns 1 row."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        for _i in range(3):
            db.insert_pending_approval(
                symbol="MES",
                action="buy",
                quantity=1.0,
                entry_price=5800.0,
                pipeline_snapshot={},
            )

        rows = db.list_pending_approvals(limit=1)
        assert len(rows) == 1

    def test_limit_boundary_max(self, tmp_path: Path) -> None:
        """list_pending_approvals with limit=200 respects hardcoded max."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        # Insert 3 rows
        for _i in range(3):
            db.insert_pending_approval(
                symbol="MES",
                action="buy",
                quantity=1.0,
                entry_price=5800.0,
                pipeline_snapshot={},
            )

        # Request limit > 200 should be clamped to 200
        rows = db.list_pending_approvals(limit=999)
        # Should get all 3 rows (since we only inserted 3)
        assert len(rows) == 3

    def test_limit_zero_treated_as_one(self, tmp_path: Path) -> None:
        """list_pending_approvals with limit=0 is treated as limit=1."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES",
            action="buy",
            quantity=1.0,
            entry_price=5800.0,
            pipeline_snapshot={},
        )

        # limit=0 should be clamped to 1
        rows = db.list_pending_approvals(limit=0)
        assert len(rows) == 1


class TestAuditChainWiring:
    """insert_pending_approval links every row into the tamper-evident audit
    chain (approval/audit_chain.py). Regression coverage for the migration_041
    + insert_pending_approval wiring -- passive metadata only, never gates
    an approval."""

    def test_first_row_links_to_genesis(self, tmp_path: Path) -> None:
        from approval.audit_chain import GENESIS_HASH, compute_record_hash

        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        snap = {"summary": "first trade", "confidence": 0.8}
        approval_id = db.insert_pending_approval(
            symbol="MES", action="buy", quantity=1.0, entry_price=5800.0,
            pipeline_snapshot=snap,
        )

        row = db.get_pending_approval(approval_id)
        assert row["prev_hash"] == GENESIS_HASH
        assert row["audit_hash"] == compute_record_hash(snap, GENESIS_HASH)

    def test_second_row_links_to_first(self, tmp_path: Path) -> None:
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        id1 = db.insert_pending_approval(
            symbol="MES", action="buy", quantity=1.0, entry_price=5800.0,
            pipeline_snapshot={"summary": "first"},
        )
        id2 = db.insert_pending_approval(
            symbol="MGC", action="sell", quantity=1.0, entry_price=2400.0,
            pipeline_snapshot={"summary": "second"},
        )

        row1 = db.get_pending_approval(id1)
        row2 = db.get_pending_approval(id2)
        assert row2["prev_hash"] == row1["audit_hash"]
        assert row1["audit_hash"] != row2["audit_hash"]

    def test_full_chain_verifies_and_detects_tampering(self, tmp_path: Path) -> None:
        from approval.audit_chain import verify_chain

        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        for i in range(3):
            db.insert_pending_approval(
                symbol="MES", action="buy", quantity=1.0, entry_price=5800.0 + i,
                pipeline_snapshot={"summary": f"trade {i}"},
            )

        rows = db.get_recent_approvals_all_statuses(limit=10)
        chain_order = list(reversed(rows))  # oldest first
        records = [
            {"snapshot": r["pipeline_snapshot"], "prev_hash": r["prev_hash"], "audit_hash": r["audit_hash"]}
            for r in chain_order
        ]

        verification = verify_chain(records)
        assert verification.ok is True
        assert verification.n_records == 3

        tampered = [dict(r) for r in records]
        tampered[1] = {**tampered[1], "snapshot": {"summary": "TAMPERED"}}
        tampered_verification = verify_chain(tampered)
        assert tampered_verification.ok is False
        assert tampered_verification.broken_index == 1

    def test_hashing_failure_does_not_block_insert(self, tmp_path: Path, monkeypatch) -> None:
        """Passive-metadata design constraint: a hashing error must never
        block the approval from being inserted -- it degrades to NULL hashes."""
        import approval.audit_chain as audit_chain_module

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated hashing failure")

        monkeypatch.setattr(audit_chain_module, "append_record", _boom)

        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        approval_id = db.insert_pending_approval(
            symbol="MES", action="buy", quantity=1.0, entry_price=5800.0,
            pipeline_snapshot={"summary": "should still insert"},
        )

        row = db.get_pending_approval(approval_id)
        assert row is not None
        assert row["prev_hash"] is None
        assert row["audit_hash"] is None

    def test_list_and_recent_endpoints_include_hash_fields(self, tmp_path: Path) -> None:
        """list_pending_approvals and get_recent_approvals_all_statuses must
        surface prev_hash/audit_hash (dashboard reads these from here)."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        db.insert_pending_approval(
            symbol="MES", action="buy", quantity=1.0, entry_price=5800.0,
            pipeline_snapshot={"summary": "test"},
        )

        pending_rows = db.list_pending_approvals()
        recent_rows = db.get_recent_approvals_all_statuses()
        assert "audit_hash" in pending_rows[0]
        assert "prev_hash" in pending_rows[0]
        assert "audit_hash" in recent_rows[0]
        assert "prev_hash" in recent_rows[0]
