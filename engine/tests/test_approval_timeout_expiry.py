"""
Coverage gap fix (US-103): risk/approval_timeout.py was at 51% coverage —
``is_rth()`` and ``get_timeout_for_trade()`` are covered by
tests/test_approval_timeout_rth.py (the 2026 DST-bug regression suite), but
``is_expired()`` — the function that actually decides whether a pending
approval has aged out and must be auto-expired — had zero direct coverage.

is_expired() sits directly upstream of REQUIRE_HUMAN_APPROVAL: a pending
approval that is wrongly kept alive (or wrongly expired) changes whether a
human gets to review a trade before it executes, so its edge cases —
missing/malformed timestamps, timezone-naive vs. aware inputs, the exact
boundary, and the fail-closed (never-crash) exception path — are worth
covering explicitly.

Test-only: no changes to risk/approval_timeout.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from risk.approval_timeout import TIMEOUT_RTH, is_expired


def _iso_minutes_ago(minutes: float, *, tz_suffix: str = "+00:00") -> str:
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return ts.isoformat().replace("+00:00", tz_suffix)


def test_missing_created_at_is_never_expired():
    """No timestamp to judge age from -> fail closed as NOT expired (never
    silently auto-expire an approval we can't actually age-check)."""
    assert is_expired({"symbol": "MES"}) is False
    assert is_expired({"symbol": "MES", "created_at": None}) is False


def test_fresh_approval_within_timeout_is_not_expired(monkeypatch):
    import risk.approval_timeout as mod

    monkeypatch.setattr(mod, "is_rth", lambda *a, **k: True)
    row = {"symbol": "MES", "created_at": _iso_minutes_ago(1)}
    assert is_expired(row) is False


def test_stale_approval_past_timeout_is_expired(monkeypatch):
    import risk.approval_timeout as mod

    monkeypatch.setattr(mod, "is_rth", lambda *a, **k: True)
    # RTH timeout is 5 minutes; an approval created 10 minutes ago must expire.
    row = {"symbol": "MES", "created_at": _iso_minutes_ago(TIMEOUT_RTH + 5)}
    assert is_expired(row) is True


def test_z_suffix_utc_timestamp_is_parsed(monkeypatch):
    """created_at as returned by many JSON/DB layers uses a trailing 'Z' rather
    than '+00:00' — is_expired must normalize it, not treat it as malformed."""
    import risk.approval_timeout as mod

    monkeypatch.setattr(mod, "is_rth", lambda *a, **k: True)
    stale = (datetime.now(timezone.utc) - timedelta(minutes=TIMEOUT_RTH + 1)).isoformat()
    stale_z = stale.split("+")[0] + "Z"
    assert is_expired({"symbol": "MES", "created_at": stale_z}) is True


def test_timezone_naive_created_at_treated_as_utc(monkeypatch):
    """A naive (no tzinfo) created_at must be treated as UTC, matching the
    naive-'now' handling in is_rth(), not raise or silently mis-age."""
    import risk.approval_timeout as mod

    monkeypatch.setattr(mod, "is_rth", lambda *a, **k: True)
    naive_stale = (
        datetime.now(timezone.utc) - timedelta(minutes=TIMEOUT_RTH + 1)
    ).replace(tzinfo=None).isoformat()
    assert is_expired({"symbol": "MES", "created_at": naive_stale}) is True


def test_datetime_object_created_at_is_accepted(monkeypatch):
    """created_at may already be a datetime (not a string) depending on the
    caller (e.g. a row read straight from sqlite3 with detect_types)."""
    import risk.approval_timeout as mod

    monkeypatch.setattr(mod, "is_rth", lambda *a, **k: True)
    stale_dt = datetime.now(timezone.utc) - timedelta(minutes=TIMEOUT_RTH + 1)
    assert is_expired({"symbol": "MES", "created_at": stale_dt}) is True


def test_malformed_created_at_fails_closed_not_expired():
    """A garbage timestamp must not raise out of is_expired() (it wraps the
    parse in try/except) and must fail closed as NOT expired."""
    row = {"symbol": "MES", "created_at": "not-a-timestamp"}
    assert is_expired(row) is False


def test_overnight_timeout_is_longer_than_rth(monkeypatch):
    """Outside RTH the timeout tier is longer (10m vs 5m) — an approval aged
    past the RTH threshold but within the overnight threshold must NOT expire."""
    import risk.approval_timeout as mod

    monkeypatch.setattr(mod, "is_rth", lambda *a, **k: False)
    # 7 minutes old: past the 5m RTH tier, inside the 10m overnight tier.
    row = {"symbol": "MES", "created_at": _iso_minutes_ago(7)}
    assert is_expired(row) is False
