"""
Regression test for the GET /analytics/performance 503.

The endpoint 503'd with "can't compare offset-naive and offset-aware datetimes"
(24 occurrences on 2026-06-05). Root cause: _compute_days_from_trades parsed a
mix of tz-naive ("...T10:00:00") and tz-aware ("...+00:00"/"Z") timestamps from
the trades DB, then called max()/min() over the mixed list. These tests assert
a mixed list no longer raises and the day-span is computed correctly.
"""

from routers.analytics_router import _compute_days_from_trades


def test_mixed_naive_and_aware_does_not_raise():
    trades = [
        {"exit_time": "2026-06-01T10:00:00"},        # tz-naive
        {"exit_time": "2026-06-04T10:00:00+00:00"},  # tz-aware
        {"exit_time": "2026-06-03T10:00:00Z"},       # tz-aware via Z
    ]
    # Previously raised TypeError; must now return the calendar span (1st..4th).
    assert _compute_days_from_trades(trades) == 4


def test_all_naive():
    trades = [
        {"entry_time": "2026-06-01T00:00:00"},
        {"entry_time": "2026-06-02T00:00:00"},
    ]
    assert _compute_days_from_trades(trades) == 2


def test_all_aware():
    trades = [
        {"exit_time": "2026-06-01T00:00:00+00:00"},
        {"exit_time": "2026-06-05T00:00:00+00:00"},
    ]
    assert _compute_days_from_trades(trades) == 5


def test_exit_time_preferred_over_entry_time():
    trades = [
        {"entry_time": "2026-06-01T00:00:00", "exit_time": "2026-06-10T00:00:00+00:00"},
        {"entry_time": "2026-06-01T00:00:00Z"},
    ]
    # Row 1 uses exit_time (6-10), row 2 falls back to entry_time (6-1) → 10 days.
    assert _compute_days_from_trades(trades) == 10


def test_single_trade_spans_one_day():
    assert _compute_days_from_trades([{"exit_time": "2026-06-01T12:00:00"}]) == 1


def test_empty_and_unparseable_return_zero():
    assert _compute_days_from_trades([]) == 0
    assert _compute_days_from_trades([{"exit_time": "not-a-date"}]) == 0
    assert _compute_days_from_trades([{"foo": "bar"}]) == 0


def test_mixed_with_offset_timezone_normalizes():
    # A non-UTC offset must be converted, not just stamped, so the span is right.
    trades = [
        {"exit_time": "2026-06-01T23:00:00-05:00"},  # == 2026-06-02T04:00:00Z
        {"exit_time": "2026-06-02T01:00:00"},        # naive, treated as UTC
    ]
    # Both fall on 2026-06-02 in UTC → single calendar day.
    assert _compute_days_from_trades(trades) == 1
