"""
Tests for the TOS derived-indicator engine.

These pin the arithmetic that mirrors Matt's TOS /ES chart studies:
ATR(14), Keltner Channels (20, 3.5), multi-timeframe S/R, day-range gauge.

The engine computes from the live RTD price stream rather than reading
ThinkScript study topics (TOS's RTD only answers LAST/BID/ASK/CLOSE — see
``data/tos_indicator_engine.py``). These tests use synthetic bars so they run
offline and assert exact expected values.

Why hand-computed expectations instead of golden files: the formulas are simple
enough that a wrong answer is trivially detectable, and a test that re-derives
the result with the same code would pass a broken implementation.
"""

from __future__ import annotations

import pytest

from data.tos_indicator_engine import (
    Bar,
    IndicatorEngine,
    IndicatorRegistry,
    _ema,
    _tr,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _feed_bars(engine: IndicatorEngine, bars: list[tuple[float, float, float, float]]):
    """Feed (open, high, low, close) tuples; return the final snapshot."""
    snap = None
    for o, h, low, c in bars:
        snap = engine.ingest(Bar(open=o, high=h, low=low, close=c))
    return snap


def _flat_bars(n: int, price: float = 100.0, spread: float = 1.0):
    """n bars with a stable range — makes TR and ATR exactly predictable."""
    return [(price, price + spread, price - spread, price) for _ in range(n)]


# ── true range / EMA primitives ──────────────────────────────────────────────


def test_true_range_uses_the_largest_of_the_three_measures():
    # high-low = 5, |high-prev_close| = |105-125| = 20, |low-prev_close| = |100-125| = 25
    # The largest is 25, so TR must be 25 (not the naive high-low of 5).
    assert _tr(high=105.0, low=100.0, prev_close=125.0) == 25.0


def test_ema_seeded_on_first_value_and_same_length_as_input():
    series = [10.0, 20.0, 30.0]
    out = _ema(series, period=2)
    assert len(out) == len(series)
    assert out[0] == 10.0
    # k = 2/(2+1) = 0.6667 ; 20*0.6667 + 10*0.3333 = 16.667
    assert out[1] == pytest.approx(16.6667, abs=1e-3)


# ── ATR ──────────────────────────────────────────────────────────────────────


def test_atr_is_none_until_at_least_two_bars():
    engine = IndicatorEngine("SPY")
    snap = engine.ingest(Bar(open=100.0, high=101.0, low=99.0, close=100.0))
    assert snap.atr.value is None
    assert snap.atr.bars_used == 0


def test_atr_on_constant_range_equals_that_range():
    # Every bar has high-low = 2 and prev_close == 100 inside the range, so
    # each TR is exactly 2 and the mean is exactly 2.
    engine = IndicatorEngine("SPY")
    snap = _feed_bars(engine, _flat_bars(16, price=100.0, spread=1.0))
    assert snap.atr.value == pytest.approx(2.0, abs=1e-9)
    assert snap.atr.bars_used == 14  # capped at the ATR period


def test_atr_caps_bars_used_at_the_period():
    engine = IndicatorEngine("SPY")
    snap = _feed_bars(engine, _flat_bars(40, price=100.0))
    assert snap.atr.bars_used == 14


# ── Keltner Channels ─────────────────────────────────────────────────────────


def test_keltner_is_none_until_twenty_bars():
    engine = IndicatorEngine("SPY")
    snap = _feed_bars(engine, _flat_bars(19, price=100.0))
    assert snap.keltner.upper is None
    assert snap.keltner.mid is None
    assert snap.keltner.lower is None


def test_keltner_band_is_mid_plus_minus_3_5_atr():
    engine = IndicatorEngine("SPY")
    snap = _feed_bars(engine, _flat_bars(25, price=100.0, spread=1.0))

    # ATR = 2.0; EMA of a constant series = the constant (100.0).
    atr = snap.atr.value
    mid = snap.keltner.mid
    assert atr == pytest.approx(2.0, abs=1e-9)
    assert mid == pytest.approx(100.0, abs=1e-6)
    assert snap.keltner.upper == pytest.approx(mid + 3.5 * atr, abs=1e-6)
    assert snap.keltner.lower == pytest.approx(mid - 3.5 * atr, abs=1e-6)
    assert snap.keltner.atr_multiplier == 3.5
    assert snap.keltner.ema_period == 20


# ── multi-timeframe S/R ──────────────────────────────────────────────────────


def test_sr_levels_cover_5_15_and_30_minute_windows():
    engine = IndicatorEngine("SPY")
    bars = _flat_bars(40, price=100.0, spread=1.0)
    # Make the most recent bar an outlier so the 5m window must reflect it.
    bars[-1] = (100.0, 150.0, 50.0, 100.0)
    snap = _feed_bars(engine, bars)

    windows = {sr.tf_minutes: sr for sr in snap.sr_levels}
    assert set(windows) == {5, 15, 30}

    # The 150/50 spike lands in every window (all windows include the last bar).
    for tf in (5, 15, 30):
        assert windows[tf].top == pytest.approx(150.0)
        assert windows[tf].bottom == pytest.approx(50.0)


def test_sr_top_and_bottom_come_from_their_own_windows():
    engine = IndicatorEngine("SPY")
    # 40 bars: a single high spike early, then a long quiet tail so the 5m
    # window no longer contains the spike.
    bars = _flat_bars(40, price=100.0, spread=1.0)
    bars[0] = (100.0, 200.0, 100.0, 100.0)
    snap = _feed_bars(engine, bars)

    windows = {sr.tf_minutes: sr for sr in snap.sr_levels}
    # 5m window (last 5 bars) excludes the early spike → back to the quiet range.
    assert windows[5].top == pytest.approx(101.0)
    # 30m window is still shallow here (40 bars total) — the spike at index 0
    # is outside the last 30, so it also excludes it.
    assert windows[30].top == pytest.approx(101.0)


# ── day-range gauge ──────────────────────────────────────────────────────────


def test_day_range_tracks_running_high_and_low_across_ticks():
    engine = IndicatorEngine("SPY")
    engine.tick(100.0)
    engine.tick(105.0)
    snap = engine.tick(98.0)

    assert snap.day_range.day_high == pytest.approx(105.0)
    assert snap.day_range.day_low == pytest.approx(98.0)
    assert snap.day_range.day_range == pytest.approx(7.0)


def test_day_range_pct_is_none_without_atr():
    engine = IndicatorEngine("SPY")
    snap = engine.tick(100.0)
    assert snap.day_range.range_pct is None


def test_day_range_pct_uses_atr_once_warm():
    engine = IndicatorEngine("SPY")
    _feed_bars(engine, _flat_bars(20, price=100.0, spread=1.0))  # ATR = 2.0
    engine.reset_day_range()
    engine.tick(100.0)
    engine.tick(110.0)  # day range = 10
    snap = engine._compute(110.0)

    assert snap.atr.value == pytest.approx(2.0, abs=1e-9)
    assert snap.day_range.day_range == pytest.approx(10.0)
    # 10 / 2.0 * 100 = 500 %
    assert snap.day_range.range_pct == pytest.approx(500.0, abs=1e-6)


def test_reset_day_range_clears_the_accumulator():
    engine = IndicatorEngine("SPY")
    engine.tick(100.0)
    engine.tick(110.0)
    assert engine.snapshot.day_range.day_high == pytest.approx(110.0)

    engine.reset_day_range()
    engine.tick(90.0)
    assert engine.snapshot.day_range.day_high == pytest.approx(90.0)
    assert engine.snapshot.day_range.day_low == pytest.approx(90.0)


# ── tick vs bar semantics ────────────────────────────────────────────────────


def test_tick_updates_price_without_touching_bar_indicators():
    engine = IndicatorEngine("SPY")
    _feed_bars(engine, _flat_bars(20, price=100.0, spread=1.0))
    atr_before = engine.snapshot.atr.value

    snap = engine.tick(123.0)

    assert snap.last_price == pytest.approx(123.0)
    # A tick is not a bar close — ATR must not move.
    assert snap.atr.value == atr_before


def test_snapshot_is_none_safe_before_any_data():
    engine = IndicatorEngine("SPY")
    snap = engine.snapshot
    assert snap.last_price is None
    assert snap.atr.value is None
    assert snap.sr_levels == []


# ── registry ─────────────────────────────────────────────────────────────────


def test_registry_returns_a_stable_engine_per_symbol():
    reg = IndicatorRegistry()
    a = reg.get("spy")
    b = reg.get("SPY")
    assert a is b  # case-insensitive, same instance
    assert a.symbol == "SPY"


def test_registry_separates_symbols():
    reg = IndicatorRegistry()
    reg.get("SPY").tick(100.0)
    reg.get("QQQ").tick(200.0)

    assert reg.snapshot("SPY").last_price == pytest.approx(100.0)
    assert reg.snapshot("QQQ").last_price == pytest.approx(200.0)


def test_all_snapshots_returns_every_registered_symbol():
    reg = IndicatorRegistry()
    reg.get("SPY")
    reg.get("QQQ")
    assert set(reg.all_snapshots()) == {"SPY", "QQQ"}


# ── connector warm-up reporting (regression) ─────────────────────────────────


def test_warm_flag_is_true_for_a_legitimately_zero_atr():
    """A flat tape yields ATR == 0.0 and must still report `warm`.

    Regression: the status block used ``bool(snap.atr.value)``, so a quiet
    overnight tape (high == low == close → TR == 0) reported ``warm: False``
    even though the ATR had been computed. `warm` must mean "ATR computed",
    not "ATR non-zero".
    """
    from data.tos_rtd_adapter import TOSRTDConnector

    conn = TOSRTDConnector()
    engine = conn._indicators.get("SPY")
    # 16 identical bars → every TR is exactly 0.
    for _ in range(16):
        engine.ingest(Bar(open=100.0, high=100.0, low=100.0, close=100.0))

    status = conn.indicators_status()
    spy = next(s for s in status if s["symbol"] == "SPY")

    assert spy["atr"] == pytest.approx(0.0)
    assert spy["warm"] is True, "ATR == 0.0 must still count as warm"


def test_warm_flag_is_false_before_any_bars():
    from data.tos_rtd_adapter import TOSRTDConnector

    conn = TOSRTDConnector()
    status = conn.indicators_status()
    spy = next(s for s in status if s["symbol"] == "SPY")

    assert spy["atr"] is None
    assert spy["warm"] is False
