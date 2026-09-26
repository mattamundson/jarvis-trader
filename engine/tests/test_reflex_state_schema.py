"""Reflex layer: causal snapshot + decision contract.

Expected values are hand-computed from the inputs, not read back from the code.
"""

import math
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from reflex.schema import Direction, ReflexDecision, RiskState, more_conservative, parse_decision
from reflex.state import (
    SNAPSHOT_TOKEN_BUDGET,
    AccountState,
    Bar,
    CausalityError,
    Quote,
    build_snapshot,
)

T0 = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
STEP = timedelta(minutes=5)


def _bars(closes, spread=1.0):
    return [
        Bar(close_ts=T0 + i * STEP, open=c, high=c + spread, low=c - spread, close=c, volume=100)
        for i, c in enumerate(closes)
    ]


def _account(ts, equity=10_000.0, peak=10_000.0, day_start=10_000.0, position=0):
    return AccountState(ts=ts, equity=equity, peak_equity=peak, day_start_equity=day_start, position=position)


# ── causality ────────────────────────────────────────────────────────────────


def test_bar_closing_exactly_at_as_of_is_allowed():
    bars = _bars([100, 101, 102])
    snap = build_snapshot("MES", bars[-1].close_ts, bars, _account(bars[-1].close_ts))
    assert snap.last == 102


def test_future_bar_raises():
    bars = _bars([100, 101, 102])
    as_of = bars[-1].close_ts - timedelta(seconds=1)
    with pytest.raises(CausalityError):
        build_snapshot("MES", as_of, bars, _account(as_of))


def test_future_quote_raises():
    bars = _bars([100, 101])
    as_of = bars[-1].close_ts
    q = Quote(ts=as_of + timedelta(milliseconds=1), bid=100, ask=100.25)
    with pytest.raises(CausalityError):
        build_snapshot("MES", as_of, bars, _account(as_of), quote=q)


def test_future_account_state_raises():
    bars = _bars([100, 101])
    as_of = bars[-1].close_ts
    with pytest.raises(CausalityError):
        build_snapshot("MES", as_of, bars, _account(as_of + timedelta(seconds=1)))


def test_non_monotonic_bars_raise():
    bars = _bars([100, 101, 102])
    bars = [bars[0], bars[2], bars[1]]
    as_of = T0 + 10 * STEP
    with pytest.raises(CausalityError):
        build_snapshot("MES", as_of, bars, _account(as_of))


def test_fewer_than_two_bars_raises():
    bars = _bars([100])
    with pytest.raises(ValueError):
        build_snapshot("MES", bars[0].close_ts, bars, _account(bars[0].close_ts))


# ── derived numbers (hand-computed) ──────────────────────────────────────────


def test_quote_fields_hand_computed():
    bars = _bars([100, 100])
    as_of = bars[-1].close_ts
    q = Quote(ts=as_of - timedelta(seconds=2), bid=99.99, ask=100.01, bid_size=30, ask_size=10)
    snap = build_snapshot("MES", as_of, bars, _account(as_of), quote=q)
    assert snap.mid == pytest.approx(100.0)
    assert snap.spread_bps == pytest.approx(2.0)  # 0.02 / 100 * 1e4
    assert snap.imbalance == pytest.approx(0.5)  # (30-10)/40
    assert snap.quote_age_s == pytest.approx(2.0)


def test_crossed_quote_is_ignored_not_trusted():
    bars = _bars([100, 100])
    as_of = bars[-1].close_ts
    q = Quote(ts=as_of, bid=100.5, ask=100.0, bid_size=5, ask_size=5)
    snap = build_snapshot("MES", as_of, bars, _account(as_of), quote=q)
    assert snap.mid is None and snap.spread_bps is None and snap.imbalance is None


def test_account_fields_hand_computed():
    bars = _bars([100, 100])
    as_of = bars[-1].close_ts
    snap = build_snapshot("MES", as_of, bars, _account(as_of, equity=9_900, peak=11_000, day_start=10_000, position=-1))
    assert snap.drawdown_pct == pytest.approx(10.0)  # (11000-9900)/11000
    assert snap.daily_pnl_pct == pytest.approx(-1.0)
    assert snap.position == -1


def test_rv_momentum_atr_hand_computed():
    # closes 100 -> 101 -> 100: returns ln(1.01), ln(100/101)
    bars = _bars([100, 101, 100], spread=1.0)
    as_of = bars[-1].close_ts
    snap = build_snapshot("MES", as_of, bars, _account(as_of))
    r1, r2 = math.log(1.01), math.log(100 / 101)
    m = (r1 + r2) / 2
    expected_rv = math.sqrt(((r1 - m) ** 2 + (r2 - m) ** 2) / 1) * 1e4
    assert snap.rv_bps == pytest.approx(expected_rv)
    assert snap.momentum_bps == pytest.approx(0.0, abs=1e-9)  # back to 100
    # TR bar1: max(2, |102-100|, |100-100|)=2 ; bar2: max(2, |101-101|, |99-101|)=2
    assert snap.atr == pytest.approx(2.0)


def test_compact_snapshot_fits_token_budget():
    closes = [5000 + math.sin(i / 3) * 10 for i in range(200)]
    bars = _bars(closes, spread=2.5)
    as_of = bars[-1].close_ts
    q = Quote(ts=as_of, bid=4999.75, ask=5000.0, bid_size=123, ask_size=456)
    snap = build_snapshot("MES", as_of, bars, _account(as_of, equity=9_812.37, peak=10_433.9), quote=q)
    assert snap.token_estimate() <= SNAPSHOT_TOKEN_BUDGET
    assert set(snap.to_compact()) >= {"px", "mid", "spr_bps", "imb", "rv_bps", "atr", "dd_pct", "pos"}


# ── decision contract ───────────────────────────────────────────────────────

VALID = {
    "regime": "trending",
    "direction": "long",
    "direction_confidence": 0.85,
    "toxic_flow": False,
    "setup_quality": 2,
    "risk_state": "safe",
}


def test_valid_decision_parses_from_json_and_dict():
    import json

    assert parse_decision(json.dumps(VALID)).direction == Direction.LONG
    assert parse_decision(VALID).setup_quality == 2


@pytest.mark.parametrize(
    "patch",
    [
        {"direction_confidence": 1.2},
        {"direction_confidence": -0.1},
        {"setup_quality": 4},
        {"regime": "bullish"},
        {"size": 3},  # judge may not name a size
        {"risk_state": None},
        {"direction_confidence": float("nan")},
        {"direction_confidence": float("inf")},
    ],
)
def test_invalid_decision_fails_closed(patch):
    assert parse_decision({**VALID, **patch}) is None


def test_missing_field_and_garbage_fail_closed():
    partial = dict(VALID)
    partial.pop("toxic_flow")
    assert parse_decision(partial) is None
    assert parse_decision("not json {") is None
    assert parse_decision(None) is None


def test_decision_is_immutable():
    d = ReflexDecision(**VALID)
    with pytest.raises(ValidationError):
        d.direction_confidence = 0.99


def test_more_conservative_never_loosens():
    assert more_conservative(RiskState.REDUCE, RiskState.SAFE) == RiskState.REDUCE
    assert more_conservative(RiskState.SAFE, RiskState.NEAR_LIMIT) == RiskState.NEAR_LIMIT
    assert more_conservative(RiskState.SAFE, RiskState.SAFE) == RiskState.SAFE
