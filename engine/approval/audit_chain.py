"""
JARVIS TRADER — Tamper-Evident Decision-Log Audit Chain
=======================================================
Per-record SHA-256 hash chain + daily Merkle root over the pipeline decision log.

Pattern source: mnemox-ai/tradememory-protocol (MIT) — see
docs/repo-integrations/mnemox-ai__tradememory-protocol.md. The protocol's one
genuinely novel idea relative to our existing learning/memory stack is a
cryptographic audit chain that makes the decision log tamper-evident. This module
implements that idea natively, in our own style, over the approval snapshot
produced by engine/approval/snapshot.py.

Design constraints (mirrors the disciplined, additive approach used elsewhere):
- **Passive metadata only.** Hashing observes the snapshot; it never changes an
  approval, risk, or trade decision and sits entirely outside the safety path.
  Nothing here may gate execution.
- **Deterministic.** Canonical JSON (sorted keys, no incidental whitespace) so an
  identical snapshot always yields an identical hash regardless of dict ordering.
- **Standalone.** Operates on plain snapshot dicts, so engine/approval/snapshot.py
  and the storage path are untouched. Wiring the hash into the persisted
  pipeline_runs/approval rows is a small documented follow-up: at the storage
  call site, fetch the previous row's ``audit_hash`` and call
  ``append_record(snapshot, prev_hash)``, persisting ``prev_hash`` and
  ``audit_hash`` alongside the existing snapshot.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence

__all__ = [
    "GENESIS_HASH",
    "AuditRecord",
    "ChainVerification",
    "canonical_json",
    "compute_record_hash",
    "append_record",
    "build_chain",
    "merkle_root",
    "verify_chain",
]

# Sentinel prev_hash for the first record in a chain (64 zero hex chars = the
# shape of a sha256 digest, so the genesis link is type-compatible with real
# hashes).
GENESIS_HASH = "0" * 64


def canonical_json(snapshot: Mapping[str, Any]) -> str:
    """
    Deterministically serialize a snapshot for hashing.

    ``sort_keys=True`` makes the output independent of dict insertion order;
    ``default=str`` mirrors engine/approval/snapshot.py so datetimes and odd
    types serialize the same way they are stored.
    """
    return json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    )


def compute_record_hash(
    snapshot: Mapping[str, Any],
    prev_hash: str = GENESIS_HASH,
) -> str:
    """
    SHA-256 over ``prev_hash`` concatenated with the canonical snapshot.

    Including ``prev_hash`` in the digest is what links records into a chain:
    altering any earlier record changes every subsequent hash, so tampering is
    detectable from the chain head alone.
    """
    payload = f"{prev_hash}\n{canonical_json(snapshot)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditRecord:
    """One link in the audit chain: a snapshot plus its chain hashes."""

    snapshot: Mapping[str, Any]
    prev_hash: str
    audit_hash: str

    def to_row(self) -> dict:
        """Flat dict for SQLite storage (the two hash columns + the snapshot)."""
        return {
            "prev_hash": self.prev_hash,
            "audit_hash": self.audit_hash,
            "snapshot": dict(self.snapshot),
        }


def append_record(
    snapshot: Mapping[str, Any],
    prev_hash: str = GENESIS_HASH,
) -> AuditRecord:
    """Build the next chain record for ``snapshot`` linked to ``prev_hash``."""
    return AuditRecord(
        snapshot=snapshot,
        prev_hash=prev_hash,
        audit_hash=compute_record_hash(snapshot, prev_hash),
    )


def build_chain(snapshots: Sequence[Mapping[str, Any]]) -> List[AuditRecord]:
    """Build a full chain from an ordered sequence of snapshots."""
    records: List[AuditRecord] = []
    prev = GENESIS_HASH
    for snap in snapshots:
        record = append_record(snap, prev)
        records.append(record)
        prev = record.audit_hash
    return records


def merkle_root(hashes: Sequence[str]) -> str:
    """
    Compute a Merkle root over a day's record hashes (a daily integrity anchor).

    Empty input returns ``GENESIS_HASH``. Odd layers duplicate the last node
    (Bitcoin-style) so the tree is well-formed; any single leaf change alters the
    root, giving a single value that pins an entire day's decision log.
    """
    if not hashes:
        return GENESIS_HASH
    layer = list(hashes)
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        layer = [
            hashlib.sha256((layer[i] + layer[i + 1]).encode("utf-8")).hexdigest()
            for i in range(0, len(layer), 2)
        ]
    return layer[0]


@dataclass(frozen=True)
class ChainVerification:
    """Result of verifying an audit chain."""

    ok: bool
    n_records: int
    broken_index: Optional[int] = None
    reason: str = ""


def _record_fields(record: Any) -> tuple[Mapping[str, Any], str, str]:
    """Extract (snapshot, prev_hash, audit_hash) from an AuditRecord or row dict."""
    if isinstance(record, AuditRecord):
        return record.snapshot, record.prev_hash, record.audit_hash
    if isinstance(record, Mapping):
        return (
            record.get("snapshot") or {},
            str(record.get("prev_hash", "")),
            str(record.get("audit_hash", "")),
        )
    raise TypeError(f"unsupported audit record type: {type(record)!r}")


def verify_chain(
    records: Sequence[Any],
    genesis: str = GENESIS_HASH,
) -> ChainVerification:
    """
    Verify a chain of AuditRecords (or row dicts) end to end.

    Checks, in order, for every record:
      1. its ``prev_hash`` links to the previous record's ``audit_hash``
         (the first record must link to ``genesis``);
      2. its stored ``audit_hash`` recomputes from (snapshot, prev_hash).

    Returns the first break found, or ``ok=True`` if the whole chain is intact.
    An empty chain is trivially valid.
    """
    expected_prev = genesis
    for i, record in enumerate(records):
        snapshot, prev_hash, audit_hash = _record_fields(record)
        if prev_hash != expected_prev:
            return ChainVerification(
                ok=False,
                n_records=len(records),
                broken_index=i,
                reason=(
                    f"record {i}: prev_hash {prev_hash[:12]}... does not link to "
                    f"expected {expected_prev[:12]}... (record reordered or removed)"
                ),
            )
        recomputed = compute_record_hash(snapshot, prev_hash)
        if recomputed != audit_hash:
            return ChainVerification(
                ok=False,
                n_records=len(records),
                broken_index=i,
                reason=(
                    f"record {i}: audit_hash mismatch — stored {audit_hash[:12]}... "
                    f"but snapshot hashes to {recomputed[:12]}... (snapshot tampered)"
                ),
            )
        expected_prev = audit_hash
    return ChainVerification(ok=True, n_records=len(records), reason="chain intact")
