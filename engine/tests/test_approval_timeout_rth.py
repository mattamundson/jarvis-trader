"""Tests for approval_timeout RTH detection across the EDT/EST boundary.

is_rth() drives the approval timeout (5m RTH vs 10m overnight). The old UTC
heuristic was an hour off in EST; these tests pin the DST-correct behaviour by
exercising the pure _is_rth_at(dt) helper with ET-localized datetimes derived
from known UTC instants in both summer (EDT, UTC-4) and winter (EST, UTC-5).
"""

from __future__ import annotations

from datetime import datetime, timezone

from risk.approval_timeout import (
    _ET,
    TIMEOUT_OVERNIGHT,
    TIMEOUT_RTH,
    _is_rth_at,
    get_timeout_for_trade,
)


def _et(utc: str) -> datetime:
    """UTC ISO string -> ET-localized datetime (what is_rth feeds the helper)."""
    return datetime.fromisoformat(utc).replace(tzinfo=timezone.utc).astimezone(_ET)


# --- Summer / EDT (UTC-4): 09:30 ET = 13:30 UTC, 16:00 ET = 20:00 UTC ---

def test_edt_open_is_rth():
    assert _is_rth_at(_et("2026-07-15T13:30:00")) is True  # 09:30 ET


def test_edt_close_is_rth():
    assert _is_rth_at(_et("2026-07-15T20:00:00")) is True  # 16:00 ET


def test_edt_premarket_not_rth():
    assert _is_rth_at(_et("2026-07-15T13:00:00")) is False  # 09:00 ET


# --- Winter / EST (UTC-5): 09:30 ET = 14:30 UTC, 16:00 ET = 21:00 UTC ---

def test_est_open_is_rth():
    assert _is_rth_at(_et("2026-01-15T14:30:00")) is True  # 09:30 ET


def test_est_last_hour_is_rth():
    # The old UTC heuristic returned False here (20:30 > 20:00) — the bug.
    assert _is_rth_at(_et("2026-01-15T20:30:00")) is True  # 15:30 ET


def test_est_early_utc_window_not_rth():
    # 13:30 UTC in winter is 08:30 ET — premarket. Old heuristic wrongly said RTH.
    assert _is_rth_at(_et("2026-01-15T13:30:00")) is False  # 08:30 ET


def test_est_after_close_not_rth():
    assert _is_rth_at(_et("2026-01-15T21:30:00")) is False  # 16:30 ET


# --- Weekends ---

def test_saturday_not_rth():
    # 2026-07-18 is a Saturday; midday ET is still outside RTH.
    assert _is_rth_at(_et("2026-07-18T17:00:00")) is False


def test_sunday_not_rth():
    # 2026-07-19 is a Sunday.
    assert _is_rth_at(_et("2026-07-19T17:00:00")) is False


# --- Timeout selection plumbing ---

def test_timeout_overnight_when_not_rth(monkeypatch):
    monkeypatch.setattr("risk.approval_timeout.is_rth", lambda: False)
    assert get_timeout_for_trade({}) == TIMEOUT_OVERNIGHT


def test_timeout_rth_when_rth(monkeypatch):
    monkeypatch.setattr("risk.approval_timeout.is_rth", lambda: True)
    assert get_timeout_for_trade({}) == TIMEOUT_RTH
