"""
JARVIS TRADER — Decision-Log Audit-Chain Persistence Tests
==========================================================
Integration tests over a real (temp-file) DatabaseManager: they verify that
insert_pending_approval writes a valid SHA-256 hash chain into
pending_trade_approvals (migration 041) and that verify_decision_audit_chain
catches tampering in the stored rows.

These complement the pure-logic tests in test_audit_chain.py — here the chain
must survive the JSON round-trip through SQLite.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

_engine_root = Path(__file__).resolve().parent.parent
if str(_engine_root) not in sys.path:
    sys.path.insert(0, str(_engine_root))

from database.manager import DatabaseManager  # noqa: E402, I001


def _snapshot(action, qty, conf):
    return {
        "final_action": action,
        "final_quantity": qty,
        "confidence": conf,
        "trade_decision": {"action": action, "quantity": qty, "reasoning": "x"},
        "requires_human": True,
    }


@pytest.fixture
def db(tmp_path):
    manager = DatabaseManager(db_path=str(tmp_path / "audit.db"))
    manager.initialize()  # create tables + run migrations (incl. 041)
    return manager


def _insert(db, symbol, action, qty, conf):
    return db.insert_pending_approval(
        symbol=symbol,
        action=action,
        quantity=qty,
        entry_price=100.0,
        pipeline_snapshot=_snapshot(action, qty, conf),
        timeframe="1h",
    )


class TestChainPersistence:
    def test_insert_populates_hash_columns(self, db):
        _insert(db, "MGC", "buy", 1, 0.7)
        chain = db.get_decision_audit_chain()
        assert len(chain) == 1
        assert chain[0]["prev_hash"]  # genesis link, non-null
        assert len(chain[0]["audit_hash"]) == 64

    def test_first_row_links_to_genesis(self, db):
        from approval.audit_chain import GENESIS_HASH

        _insert(db, "MGC", "buy", 1, 0.7)
        chain = db.get_decision_audit_chain()
        assert chain[0]["prev_hash"] == GENESIS_HASH

    def test_rows_link_into_a_chain(self, db):
        _insert(db, "MGC", "buy", 1, 0.7)
        _insert(db, "MES", "sell", 2, 0.6)
        _insert(db, "MCL", "buy", 1, 0.8)
        chain = db.get_decision_audit_chain()
        assert len(chain) == 3
        for prev, nxt in zip(chain, chain[1:], strict=False):
            assert nxt["prev_hash"] == prev["audit_hash"]

    def test_intact_chain_verifies(self, db):
        _insert(db, "MGC", "buy", 1, 0.7)
        _insert(db, "MES", "sell", 2, 0.6)
        result = db.verify_decision_audit_chain()
        assert result["ok"] is True
        assert result["n_records"] == 2
        assert result["broken_index"] is None

    def test_empty_chain_verifies(self, db):
        result = db.verify_decision_audit_chain()
        assert result["ok"] is True
        assert result["n_records"] == 0


class TestTamperDetection:
    def _tamper_snapshot(self, db_path, approval_id, new_json):
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE pending_trade_approvals SET pipeline_snapshot_json = ? "
                "WHERE approval_id = ?",
                (new_json, approval_id),
            )
            conn.commit()
        finally:
            conn.close()

    def test_mutating_stored_snapshot_breaks_verification(self, db, tmp_path):
        aid = _insert(db, "MGC", "buy", 1, 0.7)
        _insert(db, "MES", "sell", 2, 0.6)
        # Attacker rewrites the first decision's stored snapshot directly in SQLite.
        self._tamper_snapshot(
            str(tmp_path / "audit.db"),
            aid,
            '{"final_action": "buy", "final_quantity": 99}',
        )
        result = db.verify_decision_audit_chain()
        assert result["ok"] is False
        assert result["broken_index"] == 0
        assert result["broken_approval_id"] == aid
        assert "tampered" in result["reason"]

    def test_forging_audit_hash_is_detected(self, db, tmp_path):
        _insert(db, "MGC", "buy", 1, 0.7)
        aid2 = _insert(db, "MES", "sell", 2, 0.6)
        conn = sqlite3.connect(str(tmp_path / "audit.db"))
        try:
            conn.execute(
                "UPDATE pending_trade_approvals SET audit_hash = ? WHERE approval_id = ?",
                ("f" * 64, aid2),
            )
            conn.commit()
        finally:
            conn.close()
        result = db.verify_decision_audit_chain()
        assert result["ok"] is False
        assert result["broken_index"] == 1


class TestMerkleRoot:
    def test_root_present_and_stable(self, db):
        _insert(db, "MGC", "buy", 1, 0.7)
        _insert(db, "MES", "sell", 2, 0.6)
        root1 = db.decision_merkle_root()
        root2 = db.decision_merkle_root()
        assert len(root1) == 64
        assert root1 == root2

    def test_root_changes_when_a_row_changes(self, db, tmp_path):
        _insert(db, "MGC", "buy", 1, 0.7)
        _insert(db, "MES", "sell", 2, 0.6)
        root_before = db.decision_merkle_root()
        conn = sqlite3.connect(str(tmp_path / "audit.db"))
        try:
            conn.execute(
                "UPDATE pending_trade_approvals SET audit_hash = ? WHERE id = 1",
                ("a" * 64,),
            )
            conn.commit()
        finally:
            conn.close()
        assert db.decision_merkle_root() != root_before

    def test_empty_root_is_genesis(self, db):
        from approval.audit_chain import GENESIS_HASH

        assert db.decision_merkle_root() == GENESIS_HASH


class TestNonFatal:
    def test_insert_still_returns_id(self, db):
        # A normal insert returns a UUID even though hashing is best-effort.
        aid = _insert(db, "MGC", "buy", 1, 0.7)
        assert isinstance(aid, str) and len(aid) == 36
