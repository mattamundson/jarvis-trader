"""Unit tests for RTH detection in risk.approval_timeout.

These exercise is_rth() with injected reference instants so the DST-aware
behavior is verified deterministically (no dependency on the wall clock, the
engine, or the DB).
"""

from datetime import datetime, timezone

from risk import approval_timeout as at

UTC = timezone.utc


# --- DST correctness: the same UTC wall-time maps to different ET hours ------

def test_summer_edt_is_rth_when_winter_est_is_not():
    # 13:45 UTC -> 09:45 EDT (RTH) in July, but 08:45 EST (pre-open) in January.
    # The old fixed-offset heuristic could not tell these apart.
    summer = datetime(2026, 7, 15, 13, 45, tzinfo=UTC)  # Wednesday
    winter = datetime(2026, 1, 15, 13, 45, tzinfo=UTC)  # Thursday
    assert at.is_rth(summer) is True
    assert at.is_rth(winter) is False


def test_winter_open_boundary():
    # 14:30 UTC -> 09:30 EST exactly at the open in January.
    assert at.is_rth(datetime(2026, 1, 15, 14, 30, tzinfo=UTC)) is True


# --- RTH window boundaries (summer) -----------------------------------------

def test_summer_open_and_close_boundaries():
    assert at.is_rth(datetime(2026, 7, 15, 13, 30, tzinfo=UTC)) is True   # 09:30 EDT
    assert at.is_rth(datetime(2026, 7, 15, 20, 0, tzinfo=UTC)) is True    # 16:00 EDT


def test_before_open_and_after_close():
    assert at.is_rth(datetime(2026, 7, 15, 13, 0, tzinfo=UTC)) is False   # 09:00 EDT
    assert at.is_rth(datetime(2026, 7, 15, 20, 30, tzinfo=UTC)) is False  # 16:30 EDT


# --- Weekends are never RTH even during ET trading hours --------------------

def test_weekend_is_never_rth():
    saturday = datetime(2026, 7, 18, 17, 0, tzinfo=UTC)  # 13:00 EDT, Saturday
    sunday = datetime(2026, 7, 19, 17, 0, tzinfo=UTC)    # 13:00 EDT, Sunday
    assert at.is_rth(saturday) is False
    assert at.is_rth(sunday) is False


# --- Naive datetimes are treated as UTC -------------------------------------

def test_naive_datetime_treated_as_utc():
    naive = datetime(2026, 7, 15, 14, 0)  # no tzinfo -> UTC -> 10:00 EDT
    assert at.is_rth(naive) is True


# --- Timeout selection downstream of is_rth ---------------------------------

def test_timeout_selection(monkeypatch):
    monkeypatch.setattr(at, "is_rth", lambda *a, **k: True)
    assert at.get_timeout_for_trade({}) == at.TIMEOUT_RTH
    monkeypatch.setattr(at, "is_rth", lambda *a, **k: False)
    assert at.get_timeout_for_trade({}) == at.TIMEOUT_OVERNIGHT
