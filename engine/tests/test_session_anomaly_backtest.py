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


# ── daily OHLC decomposition (SPY etc.) ──────────────────────────────────────


def test_decompose_daily_returns():
    from backtest.session_anomaly_backtest import decompose_daily

    df = pd.DataFrame(
        {
            "date": ["2020-01-02", "2020-01-03", "2020-01-06"],
            "open": [100.0, 103.0, 108.0],
            "high": [105.0, 109.0, 110.0],
            "low": [99.0, 102.0, 107.0],
            "close": [102.0, 107.0, 109.0],
            "volume": [1, 1, 1],
        }
    )
    s = decompose_daily(df)
    assert len(s) == 3
    # intraday day1 = 102/100 - 1
    assert s.iloc[0]["intraday_ret"] == pytest.approx(0.02)
    # overnight day2 = open2/close1 - 1 = 103/102 - 1
    assert s.iloc[1]["overnight_ret"] == pytest.approx(103.0 / 102.0 - 1.0)
    assert np.isnan(s.iloc[0]["overnight_ret"])


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


# ── beta-sizing + rigorous gate-v2 verdict ───────────────────────────────────


def test_beta_size_hits_dd_budget():
    from backtest.session_anomaly_backtest import beta_size, max_drawdown_pct

    rng = np.random.default_rng(7)
    r = pd.Series(0.0005 + rng.normal(0, 0.01, 500))  # ~20%+ raw DD
    sized, scale, dd = beta_size(r, dd_budget_pct=5.0)
    assert 0 < scale < 1
    assert dd == pytest.approx(5.0, abs=1.0)  # achieved DD near the 5% budget
    assert max_drawdown_pct(sized) == pytest.approx(dd)


def test_gate_v2_verdict_returns_canonical_dict():
    from backtest.session_anomaly_backtest import gate_v2_verdict

    idx = pd.date_range("2010-01-01", periods=1500, freq="B").date
    rng = np.random.default_rng(11)
    r = pd.Series(0.0006 + rng.normal(0, 0.004, 1500), index=idx)
    v = gate_v2_verdict(r)
    # Canonical gate-v2 verdict shape from compute_gate_v2.
    assert v["verdict"] in {"PASS", "FAIL"}
    for k in ("pf_ci_lower", "p_edge", "mc_95th_dd", "dsr", "wfo_consistency"):
        assert k in v


# ── TOM as a tracked promotion-gate candidate ────────────────────────────────


def test_tom_is_tracked_but_blocked_candidate():
    from backtest.live_promotion_gate import (
        evaluate_promotion,
        turn_of_month_current_evidence,
    )

    ev = turn_of_month_current_evidence()
    assert ev["strategy_id"] == "MES_turn_of_month"
    # Strong backtest pillars pass...
    assert ev["per_window_adequate"] is True
    assert ev["leakage_clean"] is True
    assert ev["cost_robust"] is True
    assert ev["sensitivity_verdict"] == "ROBUST"
    # ...but the candidate is correctly BLOCKED (pending paper-shadow, live stability,
    # the p_edge gate-variant decision, and the systematic-strategy promotion path).
    result = evaluate_promotion(ev)
    assert result["promote"] is False
    assert "paper_shadow_passed" in result["blocks"]
    assert "live_system_stable" in result["blocks"]
    assert "robust_edge" in result["blocks"]


# ── beta-harvest CANONICAL-gate wrapper (reclassifies compute_gate_v2) ────────


def _fake_verdict(*, p_edge=0.62, fail_pf_ci=False):
    core = [
        ("FAIL pf_ci_lower=1.02 >= 1.1" if fail_pf_ci else "pf_ci_lower=1.17 >= 1.1"),
        f"FAIL p_edge={p_edge:.3f} >= 0.95",
        "mc_95th_dd_pct=4.57 <= 5.0",
        "dsr=1.000000 >= 0.1",
    ]
    return {"verdict": "FAIL", "p_edge": p_edge, "pf_ci_lower": 1.17, "core_reasons": core}


def test_beta_harvest_verdict_reclassifies_p_edge_only_fail(monkeypatch):
    import backtest.session_anomaly_backtest as sab

    monkeypatch.setattr(sab, "gate_v2_verdict", lambda r, **k: dict(_fake_verdict()))
    out = sab.gate_v2_beta_harvest_verdict(_stationary_p_edge_series())  # stationary
    assert out["verdict"] == "PASS"
    assert out["beta_harvest_reclassified"] is True


def test_beta_harvest_verdict_does_not_rescue_multi_criterion_fail(monkeypatch):
    import backtest.session_anomaly_backtest as sab

    monkeypatch.setattr(sab, "gate_v2_verdict", lambda r, **k: dict(_fake_verdict(fail_pf_ci=True)))
    out = sab.gate_v2_beta_harvest_verdict(_stationary_p_edge_series())
    assert out["verdict"] == "FAIL"  # pf_ci also fails -> not a p_edge-only rescue
    assert out["beta_harvest_reclassified"] is False


def test_beta_harvest_verdict_requires_stationarity(monkeypatch):
    import backtest.session_anomaly_backtest as sab

    monkeypatch.setattr(sab, "gate_v2_verdict", lambda r, **k: dict(_fake_verdict()))
    # Non-stationary (all losses in the 2nd half) -> the substitute fails -> no rescue.
    r = _stationary_p_edge_series(losing_months=(13, 14, 15, 16, 17, 18, 19, 20, 21))
    out = sab.gate_v2_beta_harvest_verdict(r)
    assert out["verdict"] == "FAIL"
    assert out["beta_harvest_reclassified"] is False


def test_beta_harvest_verdict_requires_p_edge_above_floor(monkeypatch):
    import backtest.session_anomaly_backtest as sab

    # p_edge below even the 0.60 floor -> no rescue.
    monkeypatch.setattr(sab, "gate_v2_verdict", lambda r, **k: dict(_fake_verdict(p_edge=0.40)))
    out = sab.gate_v2_beta_harvest_verdict(_stationary_p_edge_series())
    assert out["verdict"] == "FAIL"


def test_beta_harvest_verdict_passes_through_an_already_passing_gate(monkeypatch):
    import backtest.session_anomaly_backtest as sab

    monkeypatch.setattr(
        sab,
        "gate_v2_verdict",
        lambda r, **k: {"verdict": "PASS", "p_edge": 1.0, "core_reasons": []},
    )
    out = sab.gate_v2_beta_harvest_verdict(_stationary_p_edge_series())
    assert out["verdict"] == "PASS"
    assert out["beta_harvest_reclassified"] is False  # didn't need the variant


# ── beta-harvest gate variant (Tier-3 p_edge floor) ──────────────────────────


def _stationary_p_edge_series(losing_months=(1, 4, 7, 10, 13, 16, 19), n_months=24):
    """Daily-return series with ~70% of monthly windows profitable and both halves
    individually positive (stationary). Winning months are all-positive (PF capped
    high); losing months are all-negative (PF 0). p_edge = (n_months-len(losers))/n.
    """
    idx, vals = [], []
    base = pd.Timestamp("2010-01-01")
    for m in range(n_months):
        start = base + pd.DateOffset(months=m)
        days = pd.bdate_range(start, start + pd.offsets.MonthEnd(0))
        losing = m in losing_months
        for d in days:
            idx.append(str(d.date()))
            vals.append(-0.0004 if losing else 0.0010)
    return pd.Series(vals, index=idx)


def test_beta_harvest_uses_lower_p_edge_floor():
    from backtest.session_anomaly_backtest import grade_returns

    r = _stationary_p_edge_series()  # p_edge = 17/24 ≈ 0.708, stationary
    default = grade_returns("x", r, beta_harvest=False)
    bh = grade_returns("x", r, beta_harvest=True)
    assert 0.60 <= default.p_edge < 0.95
    assert default.stationary is True
    # Default (intraday-WFO) floor 0.95 blocks; beta-harvest floor 0.60 clears.
    assert any("p_edge" in b for b in default.blocks)
    assert not any("p_edge" in b for b in bh.blocks)


def test_beta_harvest_floor_still_exists():
    from backtest.session_anomaly_backtest import grade_returns

    # p_edge below 0.60 blocks even under the beta-harvest variant (it lowers the
    # floor, it does not remove it).
    r = _stationary_p_edge_series(losing_months=tuple(range(13)))  # 13 losers -> p_edge ~0.458
    bh = grade_returns("x", r, beta_harvest=True)
    assert bh.p_edge < 0.60
    assert any("p_edge" in b for b in bh.blocks)


def test_beta_harvest_still_requires_stationarity():
    from backtest.session_anomaly_backtest import grade_returns

    # All losses concentrated in the second half -> H2 PF < 1 -> non-stationary.
    # The beta-harvest variant must STILL block (stationarity is the substitute for
    # the 0.95 p_edge bar, not waived).
    r = _stationary_p_edge_series(losing_months=(13, 14, 15, 16, 17, 18, 19, 20, 21))
    bh = grade_returns("x", r, beta_harvest=True)
    assert bh.stationary is False
    assert any("non-stationary" in b for b in bh.blocks)


def test_beta_harvest_default_off_is_byte_for_byte_unchanged():
    from backtest.session_anomaly_backtest import grade_returns

    r = _stationary_p_edge_series()
    # Omitting the flag must equal beta_harvest=False (additive, default-off).
    assert grade_returns("x", r).blocks == grade_returns("x", r, beta_harvest=False).blocks


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
