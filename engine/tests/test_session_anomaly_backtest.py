"""Tests for the standalone MES session-anomaly (overnight-drift) backtest.

Synthetic 5m UTC bars with known prices pin the RTH session decomposition,
the cost model, and the chronological H1/H2 stationarity guard. Summer (EDT)
dates are used so 09:30 ET = 13:30 UTC and 16:00 ET = 20:00 UTC, sidestepping
DST ambiguity in the fixtures.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.session_anomaly_backtest import (
    LegVerdict,
    _cost_ret,
    annualized_sharpe,
    decompose_sessions,
    evaluate_leg,
    leg_returns,
    max_drawdown_pct,
    profit_factor,
)


def _rth_day(date: str, open_px: float, close_px: float) -> list[dict]:
    """Build 5m RTH bars 13:30..20:00 UTC (=09:30..16:00 ET) for one day.

    First bar's open = ``open_px``; last bar's close = ``close_px``.
    """
    times = pd.date_range(f"{date} 13:30:00+00:00", f"{date} 20:00:00+00:00", freq="5min")
    bars = []
    for i, t in enumerate(times):
        o = open_px if i == 0 else (open_px + close_px) / 2
        c = close_px if i == len(times) - 1 else (open_px + close_px) / 2
        bars.append(
            {
                "timestamp": str(t),
                "open": o,
                "high": max(o, c),
                "low": min(o, c),
                "close": c,
                "volume": 100.0,
            }
        )
    return bars


# ── decompose_sessions ───────────────────────────────────────────────────────


def test_decompose_open_close_per_day():
    bars = _rth_day("2025-06-02", 100.0, 110.0) + _rth_day("2025-06-03", 121.0, 130.0)
    s = decompose_sessions(pd.DataFrame(bars))
    assert len(s) == 2
    assert s.iloc[0]["rth_open_px"] == pytest.approx(100.0)
    assert s.iloc[0]["rth_close_px"] == pytest.approx(110.0)
    assert s.iloc[1]["rth_open_px"] == pytest.approx(121.0)
    assert s.iloc[1]["rth_close_px"] == pytest.approx(130.0)


def test_decompose_overnight_and_intraday_returns():
    bars = _rth_day("2025-06-02", 100.0, 110.0) + _rth_day("2025-06-03", 121.0, 130.0)
    s = decompose_sessions(pd.DataFrame(bars))
    # overnight day2 = today_open / prior_close - 1 = 121/110 - 1
    assert s.iloc[1]["overnight_ret"] == pytest.approx(121.0 / 110.0 - 1.0)
    # intraday day1 = close/open - 1 = 110/100 - 1
    assert s.iloc[0]["intraday_ret"] == pytest.approx(0.10)
    # day1 overnight is NaN (no prior day)
    assert np.isnan(s.iloc[0]["overnight_ret"])


def test_decompose_excludes_non_rth_bars():
    bars = _rth_day("2025-06-02", 100.0, 110.0)
    # Add Globex bars OUTSIDE RTH (e.g. 02:00 UTC = 22:00 ET prior day, and 21:00 UTC)
    extra = [
        {
            "timestamp": "2025-06-02 02:00:00+00:00",
            "open": 999.0,
            "high": 999.0,
            "low": 999.0,
            "close": 999.0,
            "volume": 1.0,
        },
        {
            "timestamp": "2025-06-02 21:00:00+00:00",
            "open": 888.0,
            "high": 888.0,
            "low": 888.0,
            "close": 888.0,
            "volume": 1.0,
        },
    ]
    s = decompose_sessions(pd.DataFrame(bars + extra))
    # The 999/888 outside-RTH bars must not become the open/close.
    assert s.iloc[0]["rth_open_px"] == pytest.approx(100.0)
    assert s.iloc[0]["rth_close_px"] == pytest.approx(110.0)


def test_decompose_empty_returns_empty():
    s = decompose_sessions(pd.DataFrame({"timestamp": [], "open": [], "close": []}))
    assert s.empty


# ── cost + leg returns ───────────────────────────────────────────────────────


def test_cost_ret_positive_and_small():
    c = _cost_ret(5800.0)
    assert 0 < c < 0.001  # a few bps on a ~5800 instrument


def test_leg_returns_net_is_below_gross():
    bars = _rth_day("2025-06-02", 100.0, 110.0) + _rth_day("2025-06-03", 121.0, 130.0)
    s = decompose_sessions(pd.DataFrame(bars))
    gross = leg_returns(s, "overnight", net=False)
    net = leg_returns(s, "overnight", net=True)
    assert (net <= gross + 1e-12).all()
    assert net.iloc[0] < gross.iloc[0]  # cost subtracted


def test_leg_returns_unknown_leg_raises():
    s = pd.DataFrame(
        {
            "overnight_ret": [0.01],
            "intraday_ret": [0.01],
            "rth_open_px": [100.0],
            "rth_close_px": [100.0],
        }
    )
    with pytest.raises(ValueError):
        leg_returns(s, "weekly")


# ── metric primitives ────────────────────────────────────────────────────────


def test_profit_factor_known():
    r = pd.Series([0.02, -0.01, 0.03, -0.02])  # gains .05 losses .03
    assert profit_factor(r) == pytest.approx(0.05 / 0.03)


def test_profit_factor_all_wins_is_inf():
    assert profit_factor(pd.Series([0.01, 0.02])) == float("inf")


def test_max_drawdown_pct_monotonic_up_is_zero():
    assert max_drawdown_pct(pd.Series([0.01, 0.01, 0.01])) == pytest.approx(0.0)


def test_annualized_sharpe_zero_variance():
    assert annualized_sharpe(pd.Series([0.0, 0.0, 0.0])) == 0.0


# ── evaluate_leg: verdict + H1/H2 stationarity guard ─────────────────────────


def _sessions_from_overnight(rets: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rets), freq="D").date
    return pd.DataFrame(
        {
            "rth_open_px": [5000.0] * len(rets),
            "rth_close_px": [5000.0] * len(rets),
            "overnight_ret": rets,
            "intraday_ret": [0.0] * len(rets),
        },
        index=idx,
    )


def test_evaluate_leg_returns_legverdict():
    s = _sessions_from_overnight([0.001, -0.0005] * 60)
    v = evaluate_leg(s, "overnight", net=False)
    assert isinstance(v, LegVerdict)
    assert v.leg == "overnight"
    assert v.n_days == 120


def test_non_stationary_edge_is_flagged_and_blocked():
    # Profitable first half, losing second half -> non-stationary (ES-NQ lesson).
    rets = [0.002] * 60 + [-0.002] * 60
    v = evaluate_leg(_sessions_from_overnight(rets), "overnight", net=False)
    assert v.stationary is False
    assert any("non-stationary" in b for b in v.blocks)
    assert v.verdict == "FAIL"


def test_consistently_profitable_edge_is_stationary():
    rng = np.random.default_rng(42)
    # Small positive drift both halves, low noise -> both halves PF > 1.
    rets = list(0.0008 + rng.normal(0, 0.0003, 200))
    v = evaluate_leg(_sessions_from_overnight(rets), "overnight", net=False)
    assert v.h1_pf > 1.0 and v.h2_pf > 1.0
    assert v.stationary is True


# ── calendar / turn-of-month track ───────────────────────────────────────────


def test_turn_of_month_mask_marks_end_and_start():
    from backtest.session_anomaly_backtest import turn_of_month_mask

    # 5 trading days in Jan, 5 in Feb (weekday business days).
    idx = list(pd.bdate_range("2025-01-27", periods=10).date)  # Jan27-31, Feb3-7
    m = turn_of_month_mask(idx, n_end=1, n_start=3)
    flags = [bool(x) for x in m.to_numpy()]
    # Jan: last trading day (idx 4 = Jan31) is the end-of-month flag.
    assert flags[4] is True
    # Feb: first 3 trading days (idx 5,6,7) are start-of-month.
    assert all(flags[i] for i in (5, 6, 7))
    # Genuine mid-month days (rank 4 from start, 2 from end) are NOT in the window:
    # idx 3 = Jan30 and idx 8 = Feb6.
    assert flags[3] is False
    assert flags[8] is False


def test_daily_close_returns_net_below_gross():
    from backtest.session_anomaly_backtest import daily_close_returns

    bars = _rth_day("2025-06-02", 100.0, 110.0) + _rth_day("2025-06-03", 121.0, 130.0)
    s = decompose_sessions(pd.DataFrame(bars))
    gross = daily_close_returns(s, net=False)
    net = daily_close_returns(s, net=True)
    assert (net <= gross + 1e-12).all()


def test_evaluate_turn_of_month_returns_legverdict():
    from backtest.session_anomaly_backtest import evaluate_turn_of_month

    idx = pd.date_range("2024-01-01", periods=200, freq="B").date
    s = pd.DataFrame(
        {
            "rth_open_px": np.linspace(5000, 5200, 200),
            "rth_close_px": np.linspace(5000, 5200, 200),
            "overnight_ret": [0.0] * 200,
            "intraday_ret": [0.0] * 200,
        },
        index=idx,
    )
    v = evaluate_turn_of_month(s, net=False)
    assert isinstance(v, LegVerdict)
    assert v.leg == "turn_of_month"
    assert v.n_days < 200  # only the TOM window days are held


def test_day_of_week_summary_shape():
    from backtest.session_anomaly_backtest import day_of_week_summary

    idx = pd.date_range("2024-01-01", periods=60, freq="B").date
    s = pd.DataFrame(
        {
            "rth_open_px": np.linspace(5000, 5100, 60),
            "rth_close_px": np.linspace(5000, 5100, 60),
            "overnight_ret": [0.0] * 60,
            "intraday_ret": [0.0] * 60,
        },
        index=idx,
    )
    tbl = day_of_week_summary(s, net=False)
    assert list(tbl["weekday"]) == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert (tbl["n"] > 0).all()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
