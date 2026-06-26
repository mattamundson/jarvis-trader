"""Tests for the generic calendar DARK forward paper-shadow producer."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import calendar_paper_track as cpt


def _bars(start, periods, drift=0.0005, seed=0):
    idx = pd.bdate_range(start, periods=periods)
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(drift, 0.01, periods))
    return pd.DataFrame({"date": [str(d.date()) for d in idx], "close": close})


def test_registry_only_uses_known_effects():
    for s in cpt.SLEEVES:
        assert s.effect in cpt.EFFECT_MASKS
    # SPY pre_holiday must NOT be here (already shadowed by preholiday_paper_track)
    assert cpt.Sleeve("SPY", "pre_holiday") not in cpt.SLEEVES


def test_last_day_of_month_mask_one_per_month():
    idx = pd.bdate_range("2024-01-01", "2024-03-31")
    flagged = sorted(str(d.date()) for d in idx[cpt.mask_last_day_of_month(idx)])
    assert flagged == ["2024-01-31", "2024-02-29", "2024-03-29"]


def test_held_returns_pulls_only_effect_days():
    bars = _bars("2015-01-01", 1500)
    hr = cpt.held_returns(bars, "last_day_of_month")
    # one held day per month, return present (close-to-close)
    assert len(hr) >= 24
    assert hr.notna().all()


def test_run_once_sets_inception_and_records_nothing_first(tmp_path):
    bars = _bars("2015-01-01", 1500)
    s = cpt.Sleeve("TLT", "last_day_of_month")
    res = cpt.run_once_sleeve(s, bars, track_base=tmp_path)
    # first run: inception = latest date, so zero forward days recorded
    assert res["recorded"] == 0
    assert res["inception"] == max(bars["date"])


def test_forward_days_recorded_and_idempotent(tmp_path):
    s = cpt.Sleeve("LQD", "last_day_of_month")
    early = _bars("2015-01-01", 1200)
    cpt.run_once_sleeve(s, early, track_base=tmp_path)  # sets inception
    later = _bars("2015-01-01", 1500)  # 300 more business days -> new month-ends
    r1 = cpt.run_once_sleeve(s, later, track_base=tmp_path)
    assert r1["recorded"] >= 1  # new forward month-end days recorded
    r2 = cpt.run_once_sleeve(s, later, track_base=tmp_path)  # same data again
    assert r2["recorded"] == 0  # idempotent -- no double recording


def test_report_accumulating_then_metrics(tmp_path):
    # santa_claus fires on a pure business-day index (Dec/Jan days exist); pre_holiday
    # needs real holiday gaps, which bdate_range has none of -- so use santa_claus here.
    s = cpt.Sleeve("EEM", "santa_claus")
    cpt.run_once_sleeve(s, _bars("2015-01-01", 1000), track_base=tmp_path)
    cpt.run_once_sleeve(s, _bars("2015-01-01", 1600), track_base=tmp_path)
    rep = cpt.report_sleeve(s, track_base=tmp_path)
    assert rep["forward_n"] >= 1
    assert "sharpe_net" in rep and "max_dd_pct" in rep


def test_pre_fomc_sleeves_registered():
    assert "pre_fomc" in cpt.EFFECT_MASKS
    assert cpt.Sleeve("TLT", "pre_fomc") in cpt.SLEEVES  # the gate-PASS
    assert cpt.Sleeve("SPY", "pre_fomc") in cpt.SLEEVES  # the decay-watch


def test_inline_fomc_table_matches_screener():
    # The 271-date table is duplicated (inlined) for self-containment; this guards the
    # two copies from drifting apart.
    from backtest import daily_calendar_discovery as dcd

    assert tuple(cpt._FOMC_DATES) == tuple(dcd.FOMC_ANNOUNCEMENTS)


def test_mask_pre_fomc_flags_day_before_and_is_forward_safe():
    idx = pd.DatetimeIndex(pd.bdate_range("2024-01-01", "2024-12-31"))
    flagged = {str(d.date()) for d in idx[cpt.mask_pre_fomc(idx)]}
    assert "2024-01-30" in flagged  # day before the 2024-01-31 decision
    assert "2024-01-31" not in flagged  # the decision day itself is not the pre-day
    # forward-safe: a window ending between meetings must not flag its last bar
    short = pd.DatetimeIndex(pd.bdate_range("2024-02-05", "2024-02-15"))
    assert not cpt.mask_pre_fomc(short).any()
