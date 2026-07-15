"""sd-116/MES_VA30 session-close: force-close at 16:00 America/New_York.

sd-116's backtest (run_value_area_reentry_sd116.py) force-closes every trade
at RTH session end -- it never validated carrying a position overnight.
manage_open_position() enforces this only for configs that set
cfg["session_close"] = True (MES_VA30); strategies validated to hold
overnight (MES/MGC trend) omit the flag and must be unaffected even on a
bar timestamped after 16:00 ET.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest import paper_runner


def _cfg(session_close: bool) -> dict:
    cfg = {
        "multiplier": 5.0,
        "tick_size": 0.25,
        "commission_per_contract": 0.62,
        "slippage_ticks": 1,
    }
    if session_close:
        cfg["session_close"] = True
    return cfg


def _pos(**overrides) -> dict:
    pos = {
        "entry_date": "2026-06-05T13:30:00+00:00",
        "entry_price": 100.0,
        "side": "long",
        "stop": 90.0,  # far away -- must not be hit by the test bars
        "targets": [200.0],  # far away -- must not be hit by the test bars
        "contracts_remaining": 2,
    }
    pos.update(overrides)
    return pos


def _bar(*, high=101.0, low=99.0, close=100.0) -> pd.Series:
    return pd.Series({"open": 100.0, "high": high, "low": low, "close": close})


class _FakeTracker:
    def __init__(self):
        self.added = []

    def add_trade(self, record):
        self.added.append(record)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(paper_runner, "_try_sync_engine_close", lambda *a, **k: None)
    monkeypatch.setattr(paper_runner, "_notify", lambda *a, **k: None)


def test_session_close_fires_at_rth_end_when_opted_in():
    """MES_VA30-style config: bar at 20:05 UTC (16:05 ET) force-closes."""
    tracker = _FakeTracker()
    pos, record = paper_runner.manage_open_position(
        "MES_VA30",
        _pos(),
        _bar(),
        "2026-06-05T20:05:00+00:00",  # 16:05 America/New_York
        _cfg(session_close=True),
        tracker,
    )

    assert pos is None  # fully closed
    assert record is not None
    assert record["exit_reason"] == "session_close"
    assert record["contracts"] == 2
    assert tracker.added == [record]


def test_session_close_does_not_fire_before_rth_end():
    """Same config, but the bar is still inside RTH (19:00 UTC = 15:00 ET)."""
    tracker = _FakeTracker()
    pos, record = paper_runner.manage_open_position(
        "MES_VA30",
        _pos(),
        _bar(),
        "2026-06-05T19:00:00+00:00",  # 15:00 America/New_York
        _cfg(session_close=True),
        tracker,
    )

    assert pos is not None  # still open
    assert record is None
    assert tracker.added == []


def test_overnight_hold_strategy_unaffected_by_rth_close():
    """MES/MGC-trend-style config (no session_close flag): must NOT force-close
    even on a bar well past 16:00 ET -- these strategies are validated to hold
    overnight/multi-day."""
    tracker = _FakeTracker()
    pos, record = paper_runner.manage_open_position(
        "MES",
        _pos(),
        _bar(),
        "2026-06-05T23:00:00+00:00",  # 19:00 America/New_York -- well past RTH close
        _cfg(session_close=False),
        tracker,
    )

    assert pos is not None  # still open -- unaffected
    assert record is None
    assert tracker.added == []


def test_stop_takes_priority_over_session_close_on_same_bar():
    """Matches sd-116's own exit priority (stop -> target -> session_close):
    if both the stop and RTH-close conditions are true on the same bar, the
    close reason must be 'stop', not 'session_close'."""
    tracker = _FakeTracker()
    pos, record = paper_runner.manage_open_position(
        "MES_VA30",
        _pos(stop=99.5),  # bar low (99.0) <= stop -- stop hit
        _bar(low=99.0),
        "2026-06-05T20:05:00+00:00",  # also past RTH close
        _cfg(session_close=True),
        tracker,
    )

    assert pos is None
    assert record["exit_reason"] == "stop"
