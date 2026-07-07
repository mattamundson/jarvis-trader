"""
JARVIS TRADER — Decision-Log Audit Chain Tests
==============================================
Verifies the tamper-evident hash chain in engine/approval/audit_chain.py.

The headline guarantee — mutating any stored snapshot breaks verification — is
the `TestTamperDetection` class. The rest pin determinism, the Merkle anchor, and
that hashing is passive (it never alters the snapshot it observes).
"""

import copy

from approval.audit_chain import (
    GENESIS_HASH,
    AuditRecord,
    append_record,
    build_chain,
    canonical_json,
    compute_record_hash,
    merkle_root,
    verify_chain,
)


def _snap(action, qty, conf):
    return {
        "final_action": action,
        "final_quantity": qty,
        "confidence": conf,
        "trade_decision": {"action": action, "quantity": qty},
        "requires_human": True,
    }


class TestCanonicalAndHash:
    def test_canonical_json_is_key_order_independent(self):
        a = {"b": 1, "a": 2, "c": {"y": 1, "x": 2}}
        b = {"c": {"x": 2, "y": 1}, "a": 2, "b": 1}
        assert canonical_json(a) == canonical_json(b)

    def test_identical_snapshots_hash_identically(self):
        s1 = _snap("buy", 1, 0.7)
        s2 = _snap("buy", 1, 0.7)
        assert compute_record_hash(s1) == compute_record_hash(s2)

    def test_different_snapshots_hash_differently(self):
        assert compute_record_hash(_snap("buy", 1, 0.7)) != compute_record_hash(
            _snap("sell", 1, 0.7)
        )

    def test_prev_hash_changes_record_hash(self):
        snap = _snap("buy", 1, 0.7)
        assert compute_record_hash(snap, GENESIS_HASH) != compute_record_hash(snap, "a" * 64)

    def test_hash_is_sha256_hex(self):
        h = compute_record_hash(_snap("hold", 0, 0.0))
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hashing_does_not_mutate_snapshot(self):
        snap = _snap("buy", 2, 0.9)
        before = copy.deepcopy(snap)
        compute_record_hash(snap)
        append_record(snap)
        assert snap == before  # passive: observation only


class TestChainConstruction:
    def test_first_record_links_to_genesis(self):
        records = build_chain([_snap("buy", 1, 0.7)])
        assert records[0].prev_hash == GENESIS_HASH

    def test_each_record_links_to_previous(self):
        records = build_chain([_snap("buy", 1, 0.7), _snap("sell", 1, 0.6), _snap("hold", 0, 0.0)])
        for prev, nxt in zip(records, records[1:], strict=False):
            assert nxt.prev_hash == prev.audit_hash

    def test_build_chain_verifies(self):
        records = build_chain([_snap("buy", 1, 0.7), _snap("sell", 2, 0.8)])
        result = verify_chain(records)
        assert result.ok
        assert result.n_records == 2

    def test_empty_chain_is_valid(self):
        assert verify_chain([]).ok
        assert merkle_root([]) == GENESIS_HASH

    def test_to_row_roundtrips_through_verify(self):
        records = build_chain([_snap("buy", 1, 0.7), _snap("hold", 0, 0.0)])
        rows = [r.to_row() for r in records]
        assert verify_chain(rows).ok  # dict rows verify like AuditRecords


class TestTamperDetection:
    def test_mutating_a_snapshot_breaks_verification(self):
        # The headline guarantee from the integration proposal.
        records = build_chain([_snap("buy", 1, 0.7), _snap("sell", 1, 0.6), _snap("hold", 0, 0.0)])
        rows = [r.to_row() for r in records]

        # An attacker rewrites a stored decision (buy 1 -> buy 5) but cannot
        # recompute the downstream chain.
        rows[0]["snapshot"]["final_quantity"] = 5
        result = verify_chain(rows)
        assert not result.ok
        assert result.broken_index == 0
        assert "tampered" in result.reason

    def test_forging_audit_hash_is_detected(self):
        records = build_chain([_snap("buy", 1, 0.7), _snap("sell", 1, 0.6)])
        rows = [r.to_row() for r in records]
        rows[1]["audit_hash"] = "f" * 64  # forged
        result = verify_chain(rows)
        assert not result.ok
        assert result.broken_index == 1

    def test_reordering_records_breaks_chain(self):
        records = build_chain([_snap("buy", 1, 0.7), _snap("sell", 1, 0.6), _snap("hold", 0, 0.0)])
        rows = [r.to_row() for r in records]
        rows[1], rows[2] = rows[2], rows[1]  # swap -> prev_hash links break
        result = verify_chain(rows)
        assert not result.ok

    def test_deleting_a_record_breaks_chain(self):
        records = build_chain([_snap("buy", 1, 0.7), _snap("sell", 1, 0.6), _snap("hold", 0, 0.0)])
        rows = [r.to_row() for r in records]
        del rows[1]  # removing the middle record severs the link
        result = verify_chain(rows)
        assert not result.ok
        assert result.broken_index == 1


class TestMerkleRoot:
    def test_root_is_deterministic(self):
        hashes = [compute_record_hash(_snap("buy", i, 0.5)) for i in range(5)]
        assert merkle_root(hashes) == merkle_root(list(hashes))

    def test_single_leaf_root_is_that_leaf(self):
        h = compute_record_hash(_snap("buy", 1, 0.7))
        assert merkle_root([h]) == h

    def test_changing_any_leaf_changes_root(self):
        hashes = [compute_record_hash(_snap("buy", i, 0.5)) for i in range(4)]
        root_before = merkle_root(hashes)
        hashes[2] = compute_record_hash(_snap("sell", 2, 0.5))
        assert merkle_root(hashes) != root_before

    def test_odd_leaf_count_is_handled(self):
        hashes = [compute_record_hash(_snap("buy", i, 0.5)) for i in range(3)]
        root = merkle_root(hashes)
        assert len(root) == 64


class TestRecordTypes:
    def test_unsupported_record_type_raises(self):
        import pytest

        with pytest.raises(TypeError):
            verify_chain(["not-a-record"])

    def test_audit_record_is_frozen(self):
        import dataclasses

        import pytest

        rec = append_record(_snap("buy", 1, 0.7))
        assert isinstance(rec, AuditRecord)
        with pytest.raises(dataclasses.FrozenInstanceError):
            rec.audit_hash = "x"  # type: ignore[misc]
