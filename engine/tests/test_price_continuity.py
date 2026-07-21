"""Tests for the roll-splice / price-continuity detector.

Regression anchor: the live cache file `MES_2025-07-24_2026-07-16_15m_cont.csv`
carried a +3.607% step at `2026-03-23 11:00` with NO time gap, which
`cache_completeness` could not see and in fact placed inside its certified
`trustworthy_window`.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone

import pytest

from backtest.price_continuity import (
    VERDICT_REAL,
    VERDICT_SPLICE,
    VERDICT_UNVERIFIED,
    _daily_returns,
    inspect_price_continuity,
)

UTC = timezone.utc


def _write_csv(path, rows, timestamp_last: bool = False) -> str:
    """Write bars. `timestamp_last` mimics the SPY column order."""
    fields = ["open", "high", "low", "close", "volume", "timestamp"]
    if not timestamp_last:
        fields = ["timestamp", "open", "high", "low", "close", "volume"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for ts, close in rows:
            writer.writerow(
                {
                    "timestamp": ts.isoformat(),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 100,
                }
            )
    return str(path)


def _intraday(start: datetime, closes, step_minutes: int = 15):
    return [(start + timedelta(minutes=step_minutes * i), c) for i, c in enumerate(closes)]


def _daily(start: datetime, closes):
    return [(start + timedelta(days=i), c) for i, c in enumerate(closes)]


def test_detects_step_change_with_no_time_gap(tmp_path):
    """The defining shape of a splice: consecutive bars, price steps and stays."""
    closes = [6550.0] * 10 + [6790.0] * 10  # +3.7% step, no gap
    path = _write_csv(tmp_path / "MES_15m_cont.csv", _intraday(datetime(2026, 3, 23, 9, 0, tzinfo=UTC), closes))
    result = inspect_price_continuity(path, cadence_minutes=15)
    assert result["n_candidates"] == 1
    assert result["candidates"][0]["bar_return_pct"] == pytest.approx(3.664, abs=0.01)


def test_gap_straddling_pair_is_not_a_candidate(tmp_path):
    """A weekend jump belongs to cache_completeness, not here."""
    bars = _intraday(datetime(2026, 3, 20, 20, 0, tzinfo=UTC), [6550.0, 6550.0])
    bars.append((datetime(2026, 3, 23, 13, 0, tzinfo=UTC), 6790.0))  # Mon, after gap
    path = _write_csv(tmp_path / "MES_15m_cont.csv", bars)
    result = inspect_price_continuity(path, cadence_minutes=15)
    assert result["n_candidates"] == 0


def test_fails_closed_without_a_reference(tmp_path):
    """No reference means the move could not be adjudicated -- never a pass."""
    closes = [6550.0] * 5 + [6790.0] * 5
    path = _write_csv(tmp_path / "MES_15m_cont.csv", _intraday(datetime(2026, 3, 23, 9, 0, tzinfo=UTC), closes))
    result = inspect_price_continuity(path, cadence_minutes=15)
    assert result["candidates"][0]["verdict"] == VERDICT_UNVERIFIED
    assert result["verified"] is False
    assert result["trustworthy"] is False


def test_real_move_confirmed_by_reference_is_not_a_splice(tmp_path):
    """Instrument and reference move together -> genuine market action."""
    day = datetime(2026, 3, 23, 9, 0, tzinfo=UTC)
    inst = _write_csv(tmp_path / "MES_15m_cont.csv", _intraday(day, [6000.0] * 3 + [6120.0] * 3))
    ref = _write_csv(
        tmp_path / "SPY_1d.csv",
        _daily(datetime(2026, 3, 22, tzinfo=UTC), [600.0, 612.0, 612.0]),
        timestamp_last=True,
    )
    result = inspect_price_continuity(inst, cadence_minutes=15, reference_path=ref)
    assert result["candidates"][0]["verdict"] == VERDICT_REAL
    assert result["trustworthy"] is True


def test_splice_refuted_by_reference(tmp_path):
    """Instrument jumps, reference is flat -> artifact."""
    day = datetime(2026, 3, 23, 9, 0, tzinfo=UTC)
    inst = _write_csv(tmp_path / "MES_15m_cont.csv", _intraday(day, [6000.0] * 3 + [6250.0] * 3))
    ref = _write_csv(
        tmp_path / "SPY_1d.csv",
        _daily(datetime(2026, 3, 22, tzinfo=UTC), [600.0, 598.0, 598.0]),
        timestamp_last=True,
    )
    result = inspect_price_continuity(inst, cadence_minutes=15, reference_path=ref)
    assert result["candidates"][0]["verdict"] == VERDICT_SPLICE
    assert result["continuous"] is False
    assert result["trustworthy"] is False


def test_daily_series_returns_are_cross_day_not_intraday():
    """Regression: a 1-bar-per-day series must not yield a constant 0.0%.

    The intraday rule (first close -> last close within a date) returns 0.0 for
    every day of a daily series, which silently makes the reference look flat
    and converts real moves into false SPLICE findings.
    """
    ts = [datetime(2026, 3, 22, tzinfo=UTC) + timedelta(days=i) for i in range(3)]
    out = _daily_returns(ts, [600.0, 612.0, 612.0])
    assert out[ts[1].date()] == pytest.approx(2.0)
    assert out[ts[2].date()] == pytest.approx(0.0)
    assert ts[0].date() not in out  # no prior close to measure against


def test_reference_column_order_is_irrelevant(tmp_path):
    """MES puts timestamp first, SPY puts it last; both must parse."""
    day = datetime(2026, 3, 23, 9, 0, tzinfo=UTC)
    inst = _write_csv(tmp_path / "MES_15m_cont.csv", _intraday(day, [6000.0] * 3 + [6250.0] * 3))
    rows = _daily(datetime(2026, 3, 22, tzinfo=UTC), [600.0, 598.0, 598.0])
    first = _write_csv(tmp_path / "ref_first.csv", rows, timestamp_last=False)
    last = _write_csv(tmp_path / "ref_last.csv", rows, timestamp_last=True)
    a = inspect_price_continuity(inst, cadence_minutes=15, reference_path=first)
    b = inspect_price_continuity(inst, cadence_minutes=15, reference_path=last)
    assert a["candidates"][0]["verdict"] == b["candidates"][0]["verdict"] == VERDICT_SPLICE


def test_empty_or_single_bar_file_is_not_trustworthy(tmp_path):
    path = _write_csv(tmp_path / "MES_15m_cont.csv", _intraday(datetime(2026, 3, 23, 9, 0, tzinfo=UTC), [6000.0]))
    result = inspect_price_continuity(path, cadence_minutes=15)
    assert result["trustworthy"] is False
    assert "insufficient bars" in result["reason"]
