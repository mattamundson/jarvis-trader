"""Standalone daily calendar / seasonality discovery screener.

Step B of the free-daily-data discovery track. The IB free-data ceiling starved
the micro campaign on the 30-OOS-trade floor; ``free_daily_export`` lifted that for
cash ETFs (22-33yr of free daily history), and this screener systematically hunts
the calendar/seasonality strategy class -- the class the turn-of-month edge proved
is where durable, cost-surviving equity-index edge actually lives.

Standalone (like ``session_anomaly_backtest`` and ``spread_backtest``) so it never
touches the discovery factory a peer owns. Each (symbol x calendar-effect) is a
parameter-free long-on-selected-days strategy, graded on the SAME honest bar as the
rest of the campaign: bootstrap PF CI, p_edge, deflated Sharpe, max-DD, a mandatory
chronological H1/H2 stationarity split, and the canonical ``compute_gate_v2`` verdict
with a multiple-testing penalty (n_trials = number of effects screened).

LESSON BAKED IN (turn-of-month): ``p_edge >= 0.95`` is structurally impossible for a
long-beta harvest, so candidacy ranks on the DURABLE metrics (stationarity, PF-CI,
deflated Sharpe) -- p_edge is reported, not required. Candidates remain BLOCKED from
any promotion; this only surfaces a ranked research leaderboard.

    .venv/Scripts/python -m backtest.daily_calendar_discovery
    .venv/Scripts/python -m backtest.daily_calendar_discovery --symbols SPY QQQ
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from backtest._gate_v2_helpers import (
    GATE_DSR,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    _find_latest_cache,
    bootstrap_pf_ci_lower,
)
from backtest.live_promotion_gate import BETA_HARVEST_TAG, beta_harvest_gate_enforced
from backtest.wfo_lifecycle import compute_gate_v2

CACHE_DIR = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache")
# US equity indices + gold, plus cross-asset breadth. Cross-asset is what separates
# instrument quirks from real seasonals AND localizes each effect to its mechanism:
#   - pre_holiday / santa_claus  -> risk-on (equity, EM, intl, high-yield credit)
#   - last_day_of_month          -> DURATION/RATES only (TLT, LQD, XLU); NEGATIVE in equities
# The duration/credit family (TLT/LQD/XLU/HYG) was added to TEST that month-end is a
# rates phenomenon -- confirmed: LQD month-end gate-PASSes, equities go negative.
DEFAULT_SYMBOLS = (
    "SPY",
    "QQQ",
    "IWM",
    "GLD",
    "DIA",  # US equity + gold
    "TLT",
    "SLV",
    "EEM",  # Treasuries, silver, emerging mkts
    "XLU",
    "HYG",
    "LQD",
    "EFA",  # utilities, high-yield, IG credit, developed intl
)
COST_BPS = 2.0
# Durable-metric candidacy bar (p_edge intentionally excluded -- beta-harvest lesson).
CAND_PF_CI = 1.10
CAND_DSR = 0.10


# ── tiny stats helpers (standard; kept local so the screener is self-contained) ──
def _pf(r: pd.Series) -> float:
    gains = float(r[r > 0].sum())
    losses = float(r[r < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / abs(losses)


def _sharpe(r: pd.Series, ppy: int = 252) -> float:
    a = r.to_numpy(dtype=float)
    if len(a) < 2 or a.std(ddof=1) == 0:
        return 0.0
    return float(a.mean() / a.std(ddof=1) * np.sqrt(ppy))


def _max_dd_pct(r: pd.Series) -> float:
    if len(r) == 0:
        return 0.0
    eq = (1.0 + r).cumprod()
    dd = (eq - eq.cummax()) / eq.cummax()
    return float(abs(dd.min()) * 100.0)


def _window_pfs(r: pd.Series, freq: str = "ME") -> list[float]:
    idx = pd.to_datetime(pd.Series(list(r.index)))
    s = pd.Series(r.to_numpy(), index=idx)
    pfs: list[float] = []
    for _, grp in s.groupby(pd.Grouper(freq=freq)):
        if len(grp) == 0:
            continue
        pf = _pf(grp)
        if np.isfinite(pf):
            pfs.append(pf)
        elif grp.sum() > 0:
            pfs.append(5.0)  # cap degenerate all-win window
    return pfs


# ── calendar masks (pure; aligned to a sorted DatetimeIndex) ─────────────────────
def _month_ranks(idx: pd.DatetimeIndex):
    ym = np.asarray(idx.year) * 12 + np.asarray(idx.month)
    df = pd.DataFrame({"ym": ym})
    rank_start = (df.groupby("ym").cumcount() + 1).to_numpy()
    size = df.groupby("ym")["ym"].transform("size").to_numpy()
    rank_end = size - rank_start + 1
    return rank_start, rank_end, np.asarray(idx.month), size


def mask_turn_of_month(idx: pd.DatetimeIndex, n_end: int = 1, n_start: int = 3) -> np.ndarray:
    rs, re_, _, _ = _month_ranks(idx)
    return (rs <= n_start) | (re_ <= n_end)


def mask_turn_of_quarter(idx: pd.DatetimeIndex, n_end: int = 1, n_start: int = 3) -> np.ndarray:
    rs, re_, mo, _ = _month_ranks(idx)
    end = (re_ <= n_end) & np.isin(mo, [3, 6, 9, 12])
    start = (rs <= n_start) & np.isin(mo, [1, 4, 7, 10])
    return end | start


def mask_first_half_month(idx: pd.DatetimeIndex) -> np.ndarray:
    rs, _, _, size = _month_ranks(idx)
    return rs <= np.ceil(size / 2.0)


def mask_weekday(idx: pd.DatetimeIndex, wd: int) -> np.ndarray:
    return np.asarray(idx.dayofweek == wd)


def mask_months(idx: pd.DatetimeIndex, months: set[int]) -> np.ndarray:
    return np.asarray(idx.month.isin(list(months)))


def mask_pre_holiday(idx: pd.DatetimeIndex) -> np.ndarray:
    d = idx.to_series().reset_index(drop=True)
    gap = (d.shift(-1) - d).dt.days
    wd = d.dt.dayofweek
    normal = (gap == 1) | ((wd == 4) & (gap == 3))  # weekday-to-next or Fri->Mon
    return (gap.notna() & ~normal).to_numpy()


def mask_post_holiday(idx: pd.DatetimeIndex) -> np.ndarray:
    """The first trading day AFTER a market holiday -- the complement of
    ``pre_holiday``. Tests whether the holiday effect continues past the break or
    is a pre-break-only phenomenon (a contrast/control on the same anomaly)."""
    d = idx.to_series().reset_index(drop=True)
    gap = (d - d.shift(1)).dt.days  # gap to the PREVIOUS trading day
    wd = d.dt.dayofweek
    normal = (gap == 1) | ((wd == 0) & (gap == 3))  # consecutive weekday or Mon-after-Fri
    return (gap.notna() & ~normal).to_numpy()


def mask_santa_claus(idx: pd.DatetimeIndex, n_dec: int = 5, n_jan: int = 2) -> np.ndarray:
    """The Santa-Claus-rally window (Hirsch): the last ``n_dec`` trading days of
    December plus the first ``n_jan`` of January -- thin-liquidity year-end drift
    plus the tax-loss-selling reversal."""
    rs, re_, mo, _ = _month_ranks(idx)
    dec = (mo == 12) & (re_ <= n_dec)
    jan = (mo == 1) & (rs <= n_jan)
    return dec | jan


def mask_last_day_of_month(idx: pd.DatetimeIndex) -> np.ndarray:
    """ONLY the single last trading day of each month -- isolates the strongest
    turn-of-month day (month-end pension/index-fund rebalancing buy pressure),
    stripped of the surrounding TOM window."""
    _, re_, _, _ = _month_ranks(idx)
    return re_ <= 1


def mask_opex_week(idx: pd.DatetimeIndex) -> np.ndarray:
    """The options-expiration week: the Mon-Fri trading block ending on the third
    Friday of each month. Dealer gamma-hedging and pin-risk flows make this week
    a documented elevated-activity / directional-bias window."""
    ym = np.asarray(idx.year) * 12 + np.asarray(idx.month)
    dom = np.asarray(idx.day)
    isfri = np.asarray(idx.dayofweek == 4)
    df = pd.DataFrame({"ym": ym, "dom": dom, "isfri": isfri})
    fri_rank = df["isfri"].groupby(df["ym"]).cumsum()  # running Friday count within month
    fri3 = np.where(isfri & (fri_rank.to_numpy() == 3), dom, np.nan)
    df["fri3"] = fri3
    tf = df.groupby("ym")["fri3"].transform("max").to_numpy()  # 3rd-Friday dom, broadcast
    return (dom <= tf) & (dom > tf - 7)  # the 7-day (= Mon-Fri trading) block ending on it


# Scheduled FOMC announcement (decision) dates = the LAST day of every regularly
# scheduled FOMC meeting, 1994-2027. Sourced 2026-06-26 from the Federal Reserve's
# own meeting calendars + per-year historical pages (federalreserve.gov/monetarypolicy/
# fomccalendars.htm and fomchistorical{YEAR}.htm) -- NOT from memory. The FOMC began
# announcing decisions in Feb 1994 (hence the start), holding 8 scheduled meetings/yr.
# EXCLUDED on purpose (the pre-FOMC drift is an ANTICIPATED-announcement effect, so
# unanticipated actions carry no pre-drift): every emergency/intermeeting conference
# call (1998 LTCM, the 2001/2007-08 GFC cuts, 2020 March 3 + 15 COVID cuts) AND the
# cancelled 2020 March 17-18 meeting (replaced by the unscheduled Sunday 3/15 action).
FOMC_ANNOUNCEMENTS: tuple[str, ...] = (
    "1994-02-04",
    "1994-03-22",
    "1994-05-17",
    "1994-07-06",
    "1994-08-16",
    "1994-09-27",
    "1994-11-15",
    "1994-12-20",
    "1995-02-01",
    "1995-03-28",
    "1995-05-23",
    "1995-07-06",
    "1995-08-22",
    "1995-09-26",
    "1995-11-15",
    "1995-12-19",
    "1996-01-31",
    "1996-03-26",
    "1996-05-21",
    "1996-07-03",
    "1996-08-20",
    "1996-09-24",
    "1996-11-13",
    "1996-12-17",
    "1997-02-05",
    "1997-03-25",
    "1997-05-20",
    "1997-07-02",
    "1997-08-19",
    "1997-09-30",
    "1997-11-12",
    "1997-12-16",
    "1998-02-04",
    "1998-03-31",
    "1998-05-19",
    "1998-07-01",
    "1998-08-18",
    "1998-09-29",
    "1998-11-17",
    "1998-12-22",
    "1999-02-03",
    "1999-03-30",
    "1999-05-18",
    "1999-06-30",
    "1999-08-24",
    "1999-10-05",
    "1999-11-16",
    "1999-12-21",
    "2000-02-02",
    "2000-03-21",
    "2000-05-16",
    "2000-06-28",
    "2000-08-22",
    "2000-10-03",
    "2000-11-15",
    "2000-12-19",
    "2001-01-31",
    "2001-03-20",
    "2001-05-15",
    "2001-06-27",
    "2001-08-21",
    "2001-10-02",
    "2001-11-06",
    "2001-12-11",
    "2002-01-30",
    "2002-03-19",
    "2002-05-07",
    "2002-06-26",
    "2002-08-13",
    "2002-09-24",
    "2002-11-06",
    "2002-12-10",
    "2003-01-29",
    "2003-03-18",
    "2003-05-06",
    "2003-06-25",
    "2003-08-12",
    "2003-09-16",
    "2003-10-28",
    "2003-12-09",
    "2004-01-28",
    "2004-03-16",
    "2004-05-04",
    "2004-06-30",
    "2004-08-10",
    "2004-09-21",
    "2004-11-10",
    "2004-12-14",
    "2005-02-02",
    "2005-03-22",
    "2005-05-03",
    "2005-06-30",
    "2005-08-09",
    "2005-09-20",
    "2005-11-01",
    "2005-12-13",
    "2006-01-31",
    "2006-03-28",
    "2006-05-10",
    "2006-06-29",
    "2006-08-08",
    "2006-09-20",
    "2006-10-25",
    "2006-12-12",
    "2007-01-31",
    "2007-03-21",
    "2007-05-09",
    "2007-06-28",
    "2007-08-07",
    "2007-09-18",
    "2007-10-31",
    "2007-12-11",
    "2008-01-30",
    "2008-03-18",
    "2008-04-30",
    "2008-06-25",
    "2008-08-05",
    "2008-09-16",
    "2008-10-29",
    "2008-12-16",
    "2009-01-28",
    "2009-03-18",
    "2009-04-29",
    "2009-06-24",
    "2009-08-12",
    "2009-09-23",
    "2009-11-04",
    "2009-12-16",
    "2010-01-27",
    "2010-03-16",
    "2010-04-28",
    "2010-06-23",
    "2010-08-10",
    "2010-09-21",
    "2010-11-03",
    "2010-12-14",
    "2011-01-26",
    "2011-03-15",
    "2011-04-27",
    "2011-06-22",
    "2011-08-09",
    "2011-09-21",
    "2011-11-02",
    "2011-12-13",
    "2012-01-25",
    "2012-03-13",
    "2012-04-25",
    "2012-06-20",
    "2012-08-01",
    "2012-09-13",
    "2012-10-24",
    "2012-12-12",
    "2013-01-30",
    "2013-03-20",
    "2013-05-01",
    "2013-06-19",
    "2013-07-31",
    "2013-09-18",
    "2013-10-30",
    "2013-12-18",
    "2014-01-29",
    "2014-03-19",
    "2014-04-30",
    "2014-06-18",
    "2014-07-30",
    "2014-09-17",
    "2014-10-29",
    "2014-12-17",
    "2015-01-28",
    "2015-03-18",
    "2015-04-29",
    "2015-06-17",
    "2015-07-29",
    "2015-09-17",
    "2015-10-28",
    "2015-12-16",
    "2016-01-27",
    "2016-03-16",
    "2016-04-27",
    "2016-06-15",
    "2016-07-27",
    "2016-09-21",
    "2016-11-02",
    "2016-12-14",
    "2017-02-01",
    "2017-03-15",
    "2017-05-03",
    "2017-06-14",
    "2017-07-26",
    "2017-09-20",
    "2017-11-01",
    "2017-12-13",
    "2018-01-31",
    "2018-03-21",
    "2018-05-02",
    "2018-06-13",
    "2018-08-01",
    "2018-09-26",
    "2018-11-08",
    "2018-12-19",
    "2019-01-30",
    "2019-03-20",
    "2019-05-01",
    "2019-06-19",
    "2019-07-31",
    "2019-09-18",
    "2019-10-30",
    "2019-12-11",
    # 2020: the scheduled March 17-18 meeting was cancelled (Sunday 3/15 emergency
    # action instead) -> 7 scheduled announcements this year, no clean pre-FOMC day.
    "2020-01-29",
    "2020-04-29",
    "2020-06-10",
    "2020-07-29",
    "2020-09-16",
    "2020-11-05",
    "2020-12-16",
    "2021-01-27",
    "2021-03-17",
    "2021-04-28",
    "2021-06-16",
    "2021-07-28",
    "2021-09-22",
    "2021-11-03",
    "2021-12-15",
    "2022-01-26",
    "2022-03-16",
    "2022-05-04",
    "2022-06-15",
    "2022-07-27",
    "2022-09-21",
    "2022-11-02",
    "2022-12-14",
    "2023-02-01",
    "2023-03-22",
    "2023-05-03",
    "2023-06-14",
    "2023-07-26",
    "2023-09-20",
    "2023-11-01",
    "2023-12-13",
    "2024-01-31",
    "2024-03-20",
    "2024-05-01",
    "2024-06-12",
    "2024-07-31",
    "2024-09-18",
    "2024-11-07",
    "2024-12-18",
    "2025-01-29",
    "2025-03-19",
    "2025-05-07",
    "2025-06-18",
    "2025-07-30",
    "2025-09-17",
    "2025-10-29",
    "2025-12-10",
    # 2026-2027 are forward-looking (tentative until confirmed) -- kept so the live
    # forward-shadow producer knows upcoming pre-FOMC days; the day-before guard
    # ensures a future date never flags the last available bar in-sample.
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
    "2027-01-27",
    "2027-03-17",
    "2027-04-28",
    "2027-06-09",
    "2027-07-28",
    "2027-09-15",
    "2027-10-27",
    "2027-12-08",
)
_FOMC_TS = pd.DatetimeIndex(pd.to_datetime(list(FOMC_ANNOUNCEMENTS))).sort_values()


def mask_pre_fomc(idx: pd.DatetimeIndex, max_gap_days: int = 6) -> np.ndarray:
    """The single trading day immediately BEFORE each scheduled FOMC announcement
    (Lucca-Moench 2015, "The Pre-FOMC Announcement Drift": equities earn an outsized
    premium in the ~24h preceding scheduled FOMC decisions). Daily close-to-close
    proxy: hold the trading day before the decision day. Robust to the announcement
    landing on a non-trading day -- it flags the last bar strictly before it.

    ``max_gap_days`` guards the live/edge case: a FUTURE announcement (no bar yet on
    its true day-before) must NOT flag the last available bar, so a candidate day is
    only flagged when the announcement is within ``max_gap_days`` of it (a real
    pre-FOMC day is 1-5 calendar days before the decision)."""
    vals = np.asarray(idx.values)  # datetime64[ns], ascending (screen() sorts)
    out = np.zeros(len(idx), dtype=bool)
    if len(vals) == 0:
        return out
    ann = np.asarray(_FOMC_TS.values)
    pos = np.searchsorted(vals, ann, side="left") - 1  # last bar strictly before each
    for p, d in zip(pos, ann, strict=False):  # equal length by construction
        if p < 0:
            continue
        if (d - vals[p]) / np.timedelta64(1, "D") <= max_gap_days:
            out[p] = True
    return out


# The screened family. Each entry: (name, idx -> boolean mask). Every effect is a
# pre-registered, economically-documented calendar anomaly (weekday singles act as
# the null-ish controls; they die on the multiple-testing penalty, as they should).
EFFECTS: list[tuple[str, object]] = [
    ("turn_of_month", lambda idx: mask_turn_of_month(idx)),
    ("turn_of_quarter", lambda idx: mask_turn_of_quarter(idx)),
    ("first_half_month", lambda idx: mask_first_half_month(idx)),
    ("pre_holiday", lambda idx: mask_pre_holiday(idx)),
    ("post_holiday", lambda idx: mask_post_holiday(idx)),
    ("santa_claus", lambda idx: mask_santa_claus(idx)),
    ("last_day_of_month", lambda idx: mask_last_day_of_month(idx)),
    ("opex_week", lambda idx: mask_opex_week(idx)),
    ("pre_fomc", lambda idx: mask_pre_fomc(idx)),
    ("mon", lambda idx: mask_weekday(idx, 0)),
    ("tue", lambda idx: mask_weekday(idx, 1)),
    ("wed", lambda idx: mask_weekday(idx, 2)),
    ("thu", lambda idx: mask_weekday(idx, 3)),
    ("fri", lambda idx: mask_weekday(idx, 4)),
    ("nov_apr_seasonal", lambda idx: mask_months(idx, {11, 12, 1, 2, 3, 4})),
    ("january", lambda idx: mask_months(idx, {1})),
    ("december_santa", lambda idx: mask_months(idx, {12})),
    ("september", lambda idx: mask_months(idx, {9})),
]


# ── returns + grade ──────────────────────────────────────────────────────────
def effect_returns(closes: pd.Series, mask: np.ndarray, cost_bps: float = COST_BPS) -> pd.Series:
    """Close-to-close return on days the mask holds the instrument, net of a flat
    per-held-day cost (matches the turn-of-month validation's cost convention)."""
    r = closes.pct_change()
    sel = r[np.asarray(mask, dtype=bool)].dropna()
    return sel - cost_bps / 1e4


def gate_v2_verdict(r: pd.Series, n_grid_combos: int, freq: str = "YE") -> dict:
    """Canonical gate-v2 verdict over chronological (default yearly) windows."""
    s = pd.Series(r.to_numpy(), index=pd.to_datetime(pd.Series(list(r.index))))
    windows = []
    for _, grp in s.groupby(pd.Grouper(freq=freq)):
        if len(grp) == 0:
            continue
        pf = _pf(grp)
        windows.append(
            SimpleNamespace(
                total_trades=int(len(grp)),
                profit_factor=float(pf if np.isfinite(pf) else 5.0),
                max_drawdown_pct=float(_max_dd_pct(grp) / 100.0),
                sharpe_ratio=float(_sharpe(grp)),
            )
        )
    full_pf = _pf(r)
    return compute_gate_v2(
        windows,
        n_grid_combos,
        {"fixed_params_min_pf": float(full_pf if np.isfinite(full_pf) else 5.0)},
        {"cost_survives_through": "realistic"},
    )


# ── beta-harvest gate routing (R3b / Option A) ─────────────────────────────────
# Relaxed CORE p_edge floor for a beta_harvest-tagged (long-beta calendar) effect, for
# which CORE p_edge >= 0.95 ("positive in 95% of years") is structurally unmeetable.
# Mirrors the approved session_anomaly gate_v2_beta_harvest variant (0.95 -> 0.60). Kept
# LOCAL by design (Option A): the screener rescues its OWN verdict rather than swapping
# in session_anomaly's gate implementation. A future unify (Option B) would dedupe this.
BETA_HARVEST_P_EDGE_FLOOR = 0.60

#: Effects whose verdict may route through the beta-harvest variant -- the long-beta
#: seasonals for which CORE p_edge >= 0.95 is structurally unmeetable. Confirmed by Amo
#: 2026-06-29 (the four named sleeves + last_day_of_month, the single-day case of
#: turn_of_month, + december_santa, the full-December superset of santa_claus). Everything
#: else stays canonical; the controls (post_holiday, opex_week, weekday singles, september)
#: and the broader/weaker seasonals (turn_of_quarter, first_half_month, nov_apr_seasonal,
#: january) are intentionally OUT. Market-neutral / non-calendar callers (e.g.
#: daily_relval_discovery) never pass the tag -> unaffected.
BETA_HARVEST_EFFECTS: frozenset[str] = frozenset(
    {
        "turn_of_month",
        "last_day_of_month",  # single-day case of turn_of_month
        "pre_holiday",
        "santa_claus",
        "december_santa",  # full-December superset of santa_claus
        "pre_fomc",
    }
)


def _maybe_beta_harvest_rescue(gate: dict, *, stationary: bool, strategy_class: str) -> dict:
    """Option A local rescue: upgrade a beta_harvest verdict that FAILs the canonical
    CORE gate on p_edge ALONE to PASS-via-beta_harvest -- iff it is H1/H2-stationary and
    ``BETA_HARVEST_GATE_ENFORCE`` is on. Untagged strategies, the disabled flag, and any
    canonical PASS are returned UNCHANGED, so MES (never tagged) and the market-neutral RV
    screen are unaffected. Can only ever turn a FAIL into a PASS on the single p_edge axis,
    never the reverse (it tightens nothing)."""
    if strategy_class != BETA_HARVEST_TAG or not beta_harvest_gate_enforced():
        return gate
    if gate.get("verdict") == "PASS":
        return gate
    pf_ci = float(gate.get("pf_ci_lower", 0.0))
    p_edge = float(gate.get("p_edge", 0.0))
    mc_dd = float(gate.get("mc_95th_dd", 1.0))
    dsr = float(gate.get("dsr", 0.0))
    core_non_pedge_ok = pf_ci >= GATE_PF_CI_LOWER and dsr >= GATE_DSR and mc_dd <= GATE_MC_DD_CORE
    pedge_relaxed_ok = BETA_HARVEST_P_EDGE_FLOOR <= p_edge < GATE_P_EDGE
    if core_non_pedge_ok and pedge_relaxed_ok and stationary:
        return {
            **gate,
            "verdict": "PASS",
            "passed_via": "beta_harvest",
            "beta_harvest_rescued": True,
        }
    return gate


def grade(returns: pd.Series, n_grid_combos: int = 1, *, strategy_class: str = "") -> dict:
    """Grade a long-on-selected-days daily-return series on the honest bar.

    ``strategy_class="beta_harvest"`` routes the verdict through the local beta-harvest
    rescue (see ``_maybe_beta_harvest_rescue``); the default "" is the canonical gate.
    """
    r = returns.dropna()
    n = len(r)
    pfs = _window_pfs(r)
    pf = _pf(r)
    pf_ci = bootstrap_pf_ci_lower(pfs) if len(pfs) >= 2 else 0.0
    p_edge = float(np.mean([1.0 if p > 1.0 else 0.0 for p in pfs])) if pfs else 0.0
    sharpe = _sharpe(r)
    dd = _max_dd_pct(r)
    h1, h2 = r.iloc[: n // 2], r.iloc[n // 2 :]
    h1_pf, h2_pf = _pf(h1), _pf(h2)
    stationary = bool(h1_pf > 1.0 and h2_pf > 1.0)
    if n >= 8:
        gate = gate_v2_verdict(r, n_grid_combos)
        gate = _maybe_beta_harvest_rescue(
            gate, stationary=stationary, strategy_class=strategy_class
        )
    else:
        gate = {"verdict": "INSUFFICIENT", "dsr": 0.0, "p_edge": p_edge, "pf_ci_lower": pf_ci}
    dsr = float(gate.get("dsr", 0.0))
    is_candidate = bool(stationary and pf_ci >= CAND_PF_CI and dsr >= CAND_DSR and sharpe > 0)
    return {
        "n": n,
        "pf": pf,
        "pf_ci_lower": pf_ci,
        "p_edge": p_edge,
        "sharpe": sharpe,
        "max_dd_pct": dd,
        "h1_pf": h1_pf,
        "h2_pf": h2_pf,
        "stationary": stationary,
        "dsr": dsr,
        "is_candidate": is_candidate,
        "gate": gate,
    }


# ── screen + rank ────────────────────────────────────────────────────────────
def screen(symbol: str, df: pd.DataFrame, cost_bps: float = COST_BPS) -> list[dict]:
    closes = pd.Series(
        pd.to_numeric(df["close"]).to_numpy(), index=pd.to_datetime(df["timestamp"])
    ).sort_index()
    idx = closes.index
    n_eff = len(EFFECTS)
    rows = []
    for name, fn in EFFECTS:
        r = effect_returns(closes, fn(idx), cost_bps)
        sc = BETA_HARVEST_TAG if name in BETA_HARVEST_EFFECTS else ""
        rows.append(
            {"symbol": symbol, "effect": name, **grade(r, n_grid_combos=n_eff, strategy_class=sc)}
        )
    return rows


def rank(rows: list[dict]) -> list[dict]:
    """Candidates first, then by deflated Sharpe, then by PF-CI lower bound."""
    return sorted(
        rows,
        key=lambda r: (
            0 if r.get("is_candidate") else 1,
            -float(r.get("dsr", 0.0)),
            -float(r.get("pf_ci_lower", 0.0)),
        ),
    )


def _latest_cache(symbol: str, cache_dir: Path) -> Path | None:
    """Freshest (latest END-date) cache for the symbol, via the canonical selector.

    Multiple SYMBOL_*_1d.csv files coexist (deep + assorted shallow windows); a
    naive lexicographic sort keys on START date and picks a shallow recent file.
    ``_find_latest_cache`` keys on the END-date segment -- the contract's
    chronological key -- so it returns the deepest fresh pull.
    """
    try:
        p = _find_latest_cache(cache_dir, symbol, suffix="_1d.csv")
    except Exception:  # noqa: BLE001 - no-match / malformed names => skip the symbol
        return None
    return p if p and Path(p).exists() else None


def run(
    symbols=DEFAULT_SYMBOLS, *, cache_dir: Path = CACHE_DIR, cost_bps: float = COST_BPS
) -> list[dict]:
    all_rows: list[dict] = []
    for sym in symbols:
        path = _latest_cache(sym, cache_dir)
        if path is None:
            print(f"  [skip] {sym}: no _1d cache under {cache_dir}")
            continue
        df = pd.read_csv(path)
        all_rows.extend(screen(sym, df, cost_bps))
    ranked = rank(all_rows)
    print(
        f"\nDAILY CALENDAR/SEASONALITY SCREEN ({len(symbols)} symbols x {len(EFFECTS)} effects, "
        f"net @ {cost_bps:.0f}bps, deflated for {len(EFFECTS)} trials)\n"
    )
    print(
        f"{'sym':4} {'effect':17} {'n':>5} {'PFci':>6} {'p_edge':>6} {'dsr':>6} "
        f"{'shrp':>6} {'DD%':>6} {'H1/H2':>11} {'cand':>4} {'gate'}"
    )
    for r in ranked:
        flag = "YES" if r["is_candidate"] else ""
        h = f"{r['h1_pf']:.2f}/{r['h2_pf']:.2f}"
        print(
            f"{r['symbol']:4} {r['effect']:17} {r['n']:>5} {r['pf_ci_lower']:>6.3f} "
            f"{r['p_edge']:>6.3f} {r['dsr']:>6.3f} {r['sharpe']:>6.2f} {r['max_dd_pct']:>6.2f} "
            f"{h:>11} {flag:>4} {r['gate'].get('verdict')}"
        )
    cands = [r for r in ranked if r["is_candidate"]]
    print(
        f"\n{len(cands)} durable candidate(s) (stationary + PFci>={CAND_PF_CI} + dsr>={CAND_DSR}); "
        "all BLOCKED pending forward evidence + Amo review."
    )
    return ranked


def main() -> None:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description="daily calendar/seasonality discovery screen")
    ap.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    ap.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    ap.add_argument("--cost-bps", type=float, default=COST_BPS)
    args = ap.parse_args()
    run(args.symbols, cache_dir=args.cache_dir, cost_bps=args.cost_bps)


if __name__ == "__main__":  # pragma: no cover
    main()
