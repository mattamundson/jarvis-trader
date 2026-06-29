"""Tests for backtest.daily_calendar_discovery -- standalone calendar/seasonality
screener over deep free daily ETF data.

Covers the pure logic: calendar masks (turn-of-month, weekday, months, pre-holiday),
long-on-mask return extraction net of cost, the honest grade (pf_ci/p_edge/sharpe/
H1-H2 stationarity + canonical gate-v2 verdict), and screen/rank wiring. Synthetic
data only -- no network, no cache files.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import daily_calendar_discovery as dcd


def _bdays(start, end):
    return pd.DatetimeIndex(pd.bdate_range(start, end))


# ----------------------------------------------------------------- calendar masks
def test_mask_weekday_selects_single_day():
    idx = _bdays("2024-01-01", "2024-01-31")
    m = dcd.mask_weekday(idx, 0)  # Monday
    assert m.dtype == bool
    assert set(idx[m].dayofweek) == {0}
    assert m.sum() == (idx.dayofweek == 0).sum()


def test_mask_months_selects_given_months():
    idx = _bdays("2024-01-01", "2024-12-31")
    m = dcd.mask_months(idx, {1, 12})
    assert set(idx[m].month) == {1, 12}


def test_mask_turn_of_month_flags_month_edges():
    idx = _bdays("2024-01-01", "2024-02-29")
    m = dcd.mask_turn_of_month(idx, n_end=1, n_start=3)
    flagged = {str(d.date()) for d in idx[m]}
    # last trading day of Jan 2024 is the 31st; first 3 of Feb are 1,2,5 (Mon).
    assert "2024-01-31" in flagged
    assert "2024-02-01" in flagged and "2024-02-02" in flagged and "2024-02-05" in flagged
    # a mid-month day must NOT be flagged
    assert "2024-01-17" not in flagged


def test_mask_pre_holiday_detects_gap():
    # Drop Wed 2024-01-17 to simulate a mid-week holiday; the 16th precedes the gap.
    idx = _bdays("2024-01-15", "2024-01-19").delete(2)  # remove the 17th
    m = dcd.mask_pre_holiday(idx)
    flagged = {str(d.date()) for d in idx[m]}
    assert "2024-01-16" in flagged


def test_mask_post_holiday_detects_day_after_gap():
    # Drop Wed 2024-01-17; the 18th is the first trading day AFTER the gap.
    idx = _bdays("2024-01-15", "2024-01-19").delete(2)  # remove the 17th
    m = dcd.mask_post_holiday(idx)
    flagged = {str(d.date()) for d in idx[m]}
    assert "2024-01-18" in flagged
    assert "2024-01-16" not in flagged  # that's the PRE-holiday day, not post
    # a normal Monday-after-Friday must NOT be flagged as post-holiday
    assert "2024-01-16" not in flagged


def test_mask_santa_claus_spans_year_boundary():
    idx = _bdays("2023-12-01", "2024-01-31")
    m = dcd.mask_santa_claus(idx, n_dec=5, n_jan=2)
    flagged = {str(d.date()) for d in idx[m]}
    # last trading day of Dec 2023 is the 29th (Fri); first 2 of Jan 2024 are 1(holiday-free bday)/2
    assert "2023-12-29" in flagged  # within last 5 of December
    assert "2024-01-01" in flagged or "2024-01-02" in flagged  # within first 2 of January
    assert "2023-12-15" not in flagged  # mid-December excluded
    # never selects a non Dec/Jan month
    assert set(idx[m].month) <= {12, 1}


def test_mask_last_day_of_month_is_single_day_per_month():
    idx = _bdays("2024-01-01", "2024-03-31")
    m = dcd.mask_last_day_of_month(idx)
    flagged = sorted(str(d.date()) for d in idx[m])
    # exactly one day per month, each the month's final trading day
    assert flagged == ["2024-01-31", "2024-02-29", "2024-03-29"]


def test_mask_opex_week_ends_on_third_friday():
    idx = _bdays("2024-01-01", "2024-01-31")
    m = dcd.mask_opex_week(idx)
    flagged = {str(d.date()) for d in idx[m]}
    # Jan 2024 3rd Friday = the 19th; its Mon-Fri week is the 16th-19th (15th is MLK holiday
    # but present in a bday index). The 3rd Friday itself must be in; a prior week must not.
    assert "2024-01-19" in flagged
    assert "2024-01-18" in flagged  # Thursday of opex week
    assert "2024-01-12" not in flagged  # 2nd Friday, prior week
    assert "2024-01-26" not in flagged  # 4th Friday, following week


def test_mask_pre_fomc_flags_day_before_each_scheduled_announcement():
    # 2024 scheduled FOMC announcement (last-day) dates and their pre-FOMC days:
    #   01-31->01-30, 03-20->03-19, 05-01->04-30, 06-12->06-11,
    #   07-31->07-30, 09-18->09-17, 11-07->11-06, 12-18->12-17
    idx = _bdays("2024-01-01", "2024-12-31")
    flagged = {str(d.date()) for d in idx[dcd.mask_pre_fomc(idx)]}
    expected = {
        "2024-01-30",
        "2024-03-19",
        "2024-04-30",
        "2024-06-11",
        "2024-07-30",
        "2024-09-17",
        "2024-11-06",
        "2024-12-17",
    }
    assert flagged == expected
    # the announcement day itself is NOT the pre-FOMC day
    assert "2024-01-31" not in flagged


def test_mask_pre_fomc_does_not_flag_last_bar_for_a_future_meeting():
    # Window ends 2024-02-15, between the Jan (pre-day 01-30) and Mar (pre-day 03-19)
    # meetings -> no pre-FOMC day falls inside, and the future March meeting must NOT
    # cause the last bar to be flagged (the day-before guard).
    idx = _bdays("2024-02-05", "2024-02-15")
    assert not dcd.mask_pre_fomc(idx).any()


def test_fomc_announcement_table_integrity():
    ts = dcd._FOMC_TS
    # sorted, unique, ~8/yr from 1994 onward
    assert list(ts) == sorted(ts)
    assert len(set(ts)) == len(ts)
    assert ts.min().year == 1994 and ts.max().year >= 2026
    # the first-ever FOMC announcement (1994-02-04) anchors the series
    assert pd.Timestamp("1994-02-04") in set(ts)
    # the cancelled 2020 March meeting (would have ended 03-18) is excluded
    assert pd.Timestamp("2020-03-18") not in set(ts)
    # emergency intermeeting cuts are excluded (e.g. 2008-10-08 coordinated cut)
    assert pd.Timestamp("2008-10-08") not in set(ts)


# --------------------------------------------------------------- returns + grade
def test_effect_returns_long_on_mask_net_of_cost():
    idx = _bdays("2024-01-01", "2024-01-10")
    closes = pd.Series(np.arange(100, 100 + len(idx), dtype=float), index=idx)
    mask = dcd.mask_weekday(idx, idx[5].dayofweek)  # hold one weekday
    r = dcd.effect_returns(closes, mask, cost_bps=2.0)
    assert (r.index.dayofweek == idx[5].dayofweek).all()
    assert len(r) >= 1  # at least one held day with a prior close


def test_grade_returns_expected_keys_and_stationarity():
    idx = _bdays("2015-01-01", "2025-01-01")
    rng = np.random.default_rng(7)
    # Mildly positive drift -> profitable, broadly stationary.
    r = pd.Series(rng.normal(0.0006, 0.004, len(idx)), index=idx)
    g = dcd.grade(r, n_grid_combos=10)
    for k in (
        "pf",
        "pf_ci_lower",
        "p_edge",
        "sharpe",
        "max_dd_pct",
        "h1_pf",
        "h2_pf",
        "stationary",
        "n",
        "gate",
    ):
        assert k in g
    assert g["n"] == len(idx)
    assert "verdict" in g["gate"]


# ------------------------------------------------------------------ screen + rank
def _synth_df(start, end, drift=0.0003, seed=0):
    idx = _bdays(start, end)
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(drift, 0.01, len(idx)))
    return pd.DataFrame(
        {
            "timestamp": [str(d.date()) for d in idx],
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
        }
    )


def test_screen_returns_row_per_effect():
    df = _synth_df("2016-01-01", "2025-01-01")
    rows = dcd.screen("SPY", df, cost_bps=2.0)
    assert len(rows) == len(dcd.EFFECTS)
    assert all(r["symbol"] == "SPY" for r in rows)
    assert all("effect" in r and "pf_ci_lower" in r and "dsr" in r for r in rows)


def test_rank_orders_candidates_first_then_dsr():
    rows = [
        {"effect": "a", "is_candidate": False, "dsr": 0.9, "pf_ci_lower": 2.0},
        {"effect": "b", "is_candidate": True, "dsr": 0.2, "pf_ci_lower": 1.2},
        {"effect": "c", "is_candidate": True, "dsr": 0.5, "pf_ci_lower": 1.3},
    ]
    ordered = dcd.rank(rows)
    assert [r["effect"] for r in ordered] == ["c", "b", "a"]


# ------------------------------------------------------------- cache selection
def test_latest_cache_picks_deepest_by_end_date(tmp_path):
    # A shallow recent-START file must NOT beat the deep file: a naive lexicographic
    # sort keys on start-date and would mis-pick SPY_2025-... over SPY_1993-...
    (tmp_path / "SPY_2025-01-01_2026-03-27_1d.csv").write_text("timestamp,close\n2025-01-02,1\n")
    (tmp_path / "SPY_1993-01-29_2026-06-24_1d.csv").write_text("timestamp,close\n1993-01-29,1\n")
    picked = dcd._latest_cache("SPY", tmp_path)
    assert picked is not None
    assert picked.name == "SPY_1993-01-29_2026-06-24_1d.csv"  # latest END date


def test_latest_cache_none_when_missing(tmp_path):
    assert dcd._latest_cache("NOPE", tmp_path) is None


# ------------------------------------------ beta-harvest gate routing (R3b / Option A)
# Option A: the calendar screener's OWN local beta-harvest rescue. When a calendar
# (beta_harvest-tagged) effect FAILs the canonical CORE gate on p_edge ALONE (0.60 <=
# p_edge < 0.95) and is H1/H2-stationary, and BETA_HARVEST_GATE_ENFORCE is on, its
# verdict is upgraded to PASS-via-beta_harvest. Default-OFF; untagged effects (and the
# RV screen that shares grade()) are unchanged; can only ever turn a FAIL into a PASS on
# the single p_edge axis -- never the reverse. Mirrors the approved session_anomaly
# gate_v2_beta_harvest variant WITHOUT swapping the screener's gate implementation.
def _stationary_returns(n=20):
    # both halves clearly profitable (per-half PF 0.05/0.02 = 2.5) -> grade() marks
    # stationary True, independent of the (monkeypatched) gate verdict.
    base = [0.01] * 5 + [-0.004] * 5
    vals = (base * (n // len(base) + 1))[:n]
    return pd.Series(vals, index=pd.bdate_range("2015-01-01", periods=len(vals)))


def _pedge_only_fail_gate(**over):
    # a canonical CORE FAIL whose ONLY failing core criterion is p_edge
    g = {
        "verdict": "FAIL",
        "passed_via": None,
        "pf_ci_lower": 1.20,  # >= GATE_PF_CI_LOWER (1.10)
        "p_edge": 0.70,  # in [0.60, 0.95): the relaxed-but-not-core band
        "mc_95th_dd": 0.03,  # <= GATE_MC_DD_CORE (0.05)
        "dsr": 0.50,  # >= GATE_DSR (0.10)
    }
    g.update(over)
    return g


def test_beta_harvest_rescues_pedge_only_fail_when_enforced(monkeypatch):
    monkeypatch.setattr(dcd, "gate_v2_verdict", lambda r, n: _pedge_only_fail_gate())
    monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", "1")
    g = dcd.grade(_stationary_returns(), n_grid_combos=10, strategy_class="beta_harvest")
    assert g["gate"]["verdict"] == "PASS"
    assert g["gate"]["passed_via"] == "beta_harvest"
    assert g["gate"].get("beta_harvest_rescued") is True


def test_beta_harvest_no_rescue_when_flag_off(monkeypatch):
    monkeypatch.setattr(dcd, "gate_v2_verdict", lambda r, n: _pedge_only_fail_gate())
    monkeypatch.delenv("BETA_HARVEST_GATE_ENFORCE", raising=False)
    g = dcd.grade(_stationary_returns(), n_grid_combos=10, strategy_class="beta_harvest")
    assert g["gate"]["verdict"] == "FAIL"  # approved but not activated -> canonical


def test_beta_harvest_no_rescue_for_untagged_even_when_enforced(monkeypatch):
    monkeypatch.setattr(dcd, "gate_v2_verdict", lambda r, n: _pedge_only_fail_gate())
    monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", "1")
    g = dcd.grade(_stationary_returns(), n_grid_combos=10, strategy_class="")
    assert g["gate"]["verdict"] == "FAIL"  # RV / untagged stays canonical (MES-safe shape)


def test_beta_harvest_no_rescue_when_another_core_criterion_fails(monkeypatch):
    # pf_ci_lower ALSO below the core floor -> p_edge is not the SOLE failure
    monkeypatch.setattr(
        dcd, "gate_v2_verdict", lambda r, n: _pedge_only_fail_gate(pf_ci_lower=0.90)
    )
    monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", "1")
    g = dcd.grade(_stationary_returns(), n_grid_combos=10, strategy_class="beta_harvest")
    assert g["gate"]["verdict"] == "FAIL"


def test_beta_harvest_no_rescue_when_pedge_below_relaxed_floor(monkeypatch):
    monkeypatch.setattr(dcd, "gate_v2_verdict", lambda r, n: _pedge_only_fail_gate(p_edge=0.50))
    monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", "1")
    g = dcd.grade(_stationary_returns(), n_grid_combos=10, strategy_class="beta_harvest")
    assert g["gate"]["verdict"] == "FAIL"


def test_beta_harvest_no_rescue_when_not_stationary(monkeypatch):
    monkeypatch.setattr(dcd, "gate_v2_verdict", lambda r, n: _pedge_only_fail_gate())
    monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", "1")
    # second half all negative -> h2_pf < 1 -> not stationary -> no rescue
    idx = pd.bdate_range("2015-01-01", periods=20)
    r = pd.Series([0.01] * 10 + [-0.01] * 10, index=idx)
    g = dcd.grade(r, n_grid_combos=10, strategy_class="beta_harvest")
    assert g["gate"]["verdict"] == "FAIL"


def test_beta_harvest_leaves_canonical_pass_untouched(monkeypatch):
    passing = {
        "verdict": "PASS",
        "passed_via": "core",
        "pf_ci_lower": 1.5,
        "p_edge": 0.97,
        "mc_95th_dd": 0.02,
        "dsr": 0.6,
    }
    monkeypatch.setattr(dcd, "gate_v2_verdict", lambda r, n: dict(passing))
    monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", "1")
    g = dcd.grade(_stationary_returns(), n_grid_combos=10, strategy_class="beta_harvest")
    assert g["gate"]["verdict"] == "PASS"
    assert g["gate"]["passed_via"] == "core"  # not relabeled to beta_harvest


def test_screen_tags_only_beta_harvest_effects(monkeypatch):
    # screen() routes the beta_harvest tag to grade() for exactly the tagged effects,
    # and "" (canonical) for every other effect -- robust to whatever set is confirmed.
    monkeypatch.setattr(
        dcd,
        "grade",
        lambda r, n_grid_combos=1, *, strategy_class="": {
            "sc": strategy_class,
            "pf_ci_lower": 0.0,
            "dsr": 0.0,
            "is_candidate": False,
        },
    )
    df = _synth_df("2018-01-01", "2025-01-01")
    rows = dcd.screen("SPY", df, cost_bps=2.0)
    for row in rows:
        expected = dcd.BETA_HARVEST_TAG if row["effect"] in dcd.BETA_HARVEST_EFFECTS else ""
        assert row["sc"] == expected, f"{row['effect']} tagged '{row['sc']}', expected '{expected}'"
