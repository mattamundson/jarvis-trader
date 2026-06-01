"""
Tests for the /approvals/{id}/extend endpoint added to
engine/routers/approval_queue_router.py.

Covers:
  - test_extend_within_bounds        — minutes=30 → expires_at pushed forward
  - test_extend_clamped_high         — minutes=500 → clamped to 120
  - test_extend_clamped_low          — minutes=1 → clamped to 5
  - test_extend_rejects_already_approved  — cannot extend non-pending candidate
  - test_extend_rejects_rejected          — same for rejected status
  - test_extend_not_found                 — 404 on missing candidate
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from routers.approval_queue_router import (
    _ensure_schema,
    _extend_candidate_ttl,
    _get_candidate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "extend_test.db")
    _ensure_schema(db_path)
    return db_path


def _insert_candidate(
    db_path: str,
    symbol: str = "MCL",
    direction: str = "LONG",
    status: str = "pending",
    expired: bool = False,
) -> int:
    now = datetime.now(timezone.utc)
    if expired:
        expires = (now - timedelta(seconds=30)).isoformat()
    else:
        expires = (now + timedelta(seconds=1800)).isoformat()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO pipeline_approval_queue
                (created_at, symbol, direction, confidence, verdict_json, expires_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now.isoformat(), symbol, direction, 0.80, "{}", expires, status),
        )
        conn.commit()
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extend_within_bounds(tmp_path):
    """minutes=30 should push expires_at forward by roughly 30 minutes from now."""
    db_path = _fresh_db(tmp_path)
    cid = _insert_candidate(db_path)

    before = datetime.now(timezone.utc)
    new_expiry_iso = _extend_candidate_ttl(db_path, cid, 30)
    after = datetime.now(timezone.utc)

    new_expiry = datetime.fromisoformat(new_expiry_iso)

    # New expiry should be approximately 30 minutes from the call time
    lower_bound = before + timedelta(minutes=30) - timedelta(seconds=2)
    upper_bound = after + timedelta(minutes=30) + timedelta(seconds=2)

    assert (
        lower_bound <= new_expiry <= upper_bound
    ), f"Expected {lower_bound} <= {new_expiry} <= {upper_bound}"

    # Verify it was persisted
    row = _get_candidate(db_path, cid)
    assert row is not None
    assert row["expires_at"] == new_expiry_iso


def test_extend_clamped_high(tmp_path):
    """
    minutes=500 should be clamped to 120 by the endpoint layer.
    We test _extend_candidate_ttl directly with 120 (already clamped) and
    also test the endpoint's clamping logic via extend_candidate.
    """
    from unittest.mock import patch

    from routers.approval_queue_router import extend_candidate, inject_approval_queue_deps

    db_path = _fresh_db(tmp_path)
    cid = _insert_candidate(db_path)

    inject_approval_queue_deps(safety_layer=None, db_path=db_path)

    import asyncio

    result = asyncio.get_event_loop().run_until_complete(extend_candidate(cid, minutes=500))

    assert result["minutes_applied"] == 120
    assert result["status"] == "extended"
    assert result["candidate_id"] == cid

    # Verify expiry is within ~120 min + small buffer
    new_expiry = datetime.fromisoformat(result["expires_at"])
    expected = datetime.now(timezone.utc) + timedelta(minutes=120)
    delta = abs((new_expiry - expected).total_seconds())
    assert delta < 10, f"Expected ~120 min extension but got delta={delta}s"


def test_extend_clamped_low(tmp_path):
    """minutes=1 should be clamped to 5 by the endpoint."""
    from unittest.mock import patch

    from routers.approval_queue_router import extend_candidate, inject_approval_queue_deps

    db_path = _fresh_db(tmp_path)
    cid = _insert_candidate(db_path)
    inject_approval_queue_deps(safety_layer=None, db_path=db_path)

    import asyncio

    result = asyncio.get_event_loop().run_until_complete(extend_candidate(cid, minutes=1))
    assert result["minutes_applied"] == 5
    assert result["status"] == "extended"


def test_extend_rejects_already_approved(tmp_path):
    """Cannot extend a candidate whose status is 'approved' — should raise HTTP 409."""
    from fastapi import HTTPException

    from routers.approval_queue_router import extend_candidate, inject_approval_queue_deps

    db_path = _fresh_db(tmp_path)
    cid = _insert_candidate(db_path, status="approved")
    inject_approval_queue_deps(safety_layer=None, db_path=db_path)

    import asyncio

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(extend_candidate(cid, minutes=30))

    assert exc_info.value.status_code == 409
    assert "approved" in exc_info.value.detail.lower()


def test_extend_rejects_rejected(tmp_path):
    """Cannot extend a candidate whose status is 'rejected' — should raise HTTP 409."""
    from fastapi import HTTPException

    from routers.approval_queue_router import extend_candidate, inject_approval_queue_deps

    db_path = _fresh_db(tmp_path)
    cid = _insert_candidate(db_path, status="rejected")
    inject_approval_queue_deps(safety_layer=None, db_path=db_path)

    import asyncio

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(extend_candidate(cid, minutes=30))

    assert exc_info.value.status_code == 409
    assert "rejected" in exc_info.value.detail.lower()


def test_extend_not_found(tmp_path):
    """Extending a non-existent candidate ID should raise HTTP 404."""
    from fastapi import HTTPException

    from routers.approval_queue_router import extend_candidate, inject_approval_queue_deps

    db_path = _fresh_db(tmp_path)
    inject_approval_queue_deps(safety_layer=None, db_path=db_path)

    import asyncio

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(extend_candidate(9999, minutes=30))

    assert exc_info.value.status_code == 404
