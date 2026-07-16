"""Tests for analytics.signal_outcomes — pure signal-outcome scoring.

Covers hit classification (both directions, pessimistic same-bar rule,
expiry), MFE/MAE, hypothetical P&L conventions, the no-same-bar-data rule,
and aggregation. Pure functions only — no I/O, no engine app.
"""

from datetime import date

from analytics.signal_outcomes import (
    EXPIRY_BARS,
    aggregate_outcomes,
    bars_after,
    compute_hit_status,
    compute_mfe_mae,
    compute_pnl_pct,
    evaluate_signal,
)

NOW = date(2026, 7, 16)


def _bar(day: str, high: float, low: float, close: float | None = None) -> dict:
    return {
        "timestamp": day,
        "high": high,
        "low": low,
        "close": close if close is not None else (high + low) / 2,
    }


# ── hit classification ───────────────────────────────────────────────────────


def test_long_target1_hit():
    bars = [_bar("2026-07-02", 5010.0, 4995.0), _bar("2026-07-03", 5021.0, 5005.0)]
    assert (
        compute_hit_status(long=True, stop=4980.0, target_1=5020.0, target_2=5040.0, post_bars=bars)
        == "target1_hit"
    )


def test_long_target2_beats_target1_same_bar():
    bars = [_bar("2026-07-02", 5045.0, 5005.0)]
    assert (
        compute_hit_status(long=True, stop=4980.0, target_1=5020.0, target_2=5040.0, post_bars=bars)
        == "target2_hit"
    )


def test_short_stop_hit():
    bars = [_bar("2026-07-02", 5025.0, 5001.0)]
    assert (
        compute_hit_status(long=False, stop=5020.0, target_1=4980.0, target_2=None, post_bars=bars)
        == "stop_hit"
    )


def test_same_bar_stop_and_target_resolves_to_stop():
    # Pessimistic: the bar touched both the stop and the target.
    bars = [_bar("2026-07-02", 5025.0, 4975.0)]
    assert (
        compute_hit_status(long=True, stop=4980.0, target_1=5020.0, target_2=None, post_bars=bars)
        == "stop_hit"
    )


def test_no_touch_within_expiry_is_expired():
    bars = [_bar(f"2026-07-{2 + i:02d}", 5005.0, 4995.0) for i in range(EXPIRY_BARS)]
    assert (
        compute_hit_status(long=True, stop=4980.0, target_1=5020.0, target_2=None, post_bars=bars)
        == "expired"
    )


def test_no_touch_inside_window_is_open():
    bars = [_bar("2026-07-02", 5005.0, 4995.0)]
    assert (
        compute_hit_status(long=True, stop=4980.0, target_1=5020.0, target_2=None, post_bars=bars)
        == "open"
    )


def test_no_bars_is_open():
    assert compute_hit_status(long=True, stop=1.0, target_1=2.0, target_2=None, post_bars=[]) == "open"


# ── excursions & P&L ─────────────────────────────────────────────────────────


def test_mfe_mae_long():
    bars = [_bar("2026-07-02", 5030.0, 4990.0), _bar("2026-07-03", 5010.0, 4970.0)]
    mfe, mae = compute_mfe_mae(long=True, entry=5000.0, post_bars=bars)
    assert mfe == round(30.0 / 5000.0 * 100, 4)
    assert mae == round(30.0 / 5000.0 * 100, 4)


def test_mfe_clamped_at_zero_when_never_favorable():
    bars = [_bar("2026-07-02", 4995.0, 4970.0)]
    mfe, mae = compute_mfe_mae(long=True, entry=5000.0, post_bars=bars)
    assert mfe == 0.0
    assert mae > 0


def test_pnl_target_hit_exits_at_t1_conservative():
    # Even a target2 hit books only T1 (conservative 1R).
    pnl = compute_pnl_pct(
        long=True, entry=5000.0, stop=4980.0, target_1=5020.0, hit="target2_hit", last_close=5100.0
    )
    assert pnl == round(20.0 / 5000.0 * 100, 4)


def test_pnl_stop_hit_exits_at_stop():
    pnl = compute_pnl_pct(
        long=True, entry=5000.0, stop=4980.0, target_1=5020.0, hit="stop_hit", last_close=5100.0
    )
    assert pnl == round(-20.0 / 5000.0 * 100, 4)


def test_pnl_open_marks_to_last_close_short():
    pnl = compute_pnl_pct(
        long=False, entry=5000.0, stop=5020.0, target_1=4980.0, hit="open", last_close=4990.0
    )
    assert pnl == round(10.0 / 5000.0 * 100, 4)


# ── evaluate_signal ──────────────────────────────────────────────────────────


def _decision(**overrides) -> dict:
    base = {
        "approval_id": "abc",
        "symbol": "MES",
        "action": "buy",
        "status": "pending",
        "created_at": "2026-07-01T15:00:00+00:00",
        "pipeline_snapshot": {
            "trade_decision": {
                "entry_price": 5000.0,
                "stop_price": 4980.0,
                "target_1": 5020.0,
                "target_2": 5040.0,
                "confidence": 0.7,
            }
        },
    }
    base.update(overrides)
    return base


def test_evaluate_excludes_decision_day_bars():
    # The only favorable bar is ON the decision date — must not count.
    bars = [_bar("2026-07-01", 5050.0, 4990.0), _bar("2026-07-02", 5005.0, 4995.0)]
    out = evaluate_signal(_decision(), bars, now=NOW)
    assert out["evaluable"] is True
    assert out["hit"] == "open"  # same-day target touch did NOT grade the signal


def test_evaluate_full_path_target_hit():
    bars = [_bar("2026-07-02", 5025.0, 4995.0, close=5018.0)]
    out = evaluate_signal(_decision(), bars, now=NOW)
    assert out["hit"] == "target1_hit"
    assert out["hypothetical_pnl_pct"] == round(20.0 / 5000.0 * 100, 4)
    assert out["mfe_pct"] is not None


def test_evaluate_too_young_stays_open():
    out = evaluate_signal(
        _decision(created_at="2026-07-16T09:00:00+00:00"),
        [_bar("2026-07-16", 5100.0, 5000.0)],
        now=NOW,
    )
    assert out["evaluable"] is False
    assert out["hit"] == "open"


def test_evaluate_missing_entry_not_evaluable():
    d = _decision()
    d["pipeline_snapshot"]["trade_decision"] = {"confidence": 0.5}
    d["entry_price"] = None
    out = evaluate_signal(d, [_bar("2026-07-02", 5010.0, 4990.0)], now=NOW)
    assert out["evaluable"] is False
    assert out["hypothetical_pnl_pct"] is None


def test_bars_after_strictly_excludes_start_day():
    bars = [_bar("2026-07-01", 1, 0), _bar("2026-07-02", 1, 0)]
    post = bars_after(bars, date(2026, 7, 1))
    assert len(post) == 1


# ── aggregation ──────────────────────────────────────────────────────────────


def test_aggregate_hit_rate_over_resolved_only():
    outcomes = [
        {"evaluable": True, "hit": "target1_hit", "hypothetical_pnl_pct": 0.4},
        {"evaluable": True, "hit": "stop_hit", "hypothetical_pnl_pct": -0.4},
        {"evaluable": True, "hit": "open", "hypothetical_pnl_pct": 0.1},
        {"evaluable": False, "hit": "open", "hypothetical_pnl_pct": None},
    ]
    agg = aggregate_outcomes(outcomes)
    assert agg["total_signals"] == 4
    assert agg["total_evaluated"] == 2  # open + not-evaluable excluded
    assert agg["hit_rate"] == 50.0
    assert agg["avg_hypothetical_pnl_pct"] == 0.0
    assert agg["count_by_hit"]["open"] == 2


def test_aggregate_empty_is_null_not_zero():
    agg = aggregate_outcomes([])
    assert agg["hit_rate"] is None
    assert agg["avg_hypothetical_pnl_pct"] is None
