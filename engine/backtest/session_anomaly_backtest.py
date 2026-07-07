"""Standalone session-structure anomaly backtest for MES (overnight drift).

A *fresh, non-overlapping* edge track: every prior JARVIS attempt was trend-
direction, fill-magnet, or spread. This tests a structurally different and well-
documented equity-index anomaly — the **overnight drift**: historically most of
the index's return accrues in the *overnight* session (RTH close -> next RTH open)
rather than intraday (RTH open -> RTH close).

It is deliberately standalone (like the ES-NQ spread module) so it never touches
the discovery factory a peer session owns. It reuses the canonical honesty
helpers (``bootstrap_pf_ci_lower``, ``classify_wfo_consistency``) and applies a
**mandatory chronological H1/H2 split** — the lesson from the ES-NQ spread, where a
pooled bootstrap happily passed a non-stationary, back-loaded edge.

Strategy primitives (parameter-free, so there is nothing to overfit):
  - OVERNIGHT leg: long from each RTH close to the next RTH open.
  - INTRADAY  leg: long from each RTH open to the same day's RTH close.
Both are evaluated gross and net of realistic MES round-trip cost.

No look-ahead: the RTH open price is the *open* of the first RTH bar (known at the
open); the RTH close price is the *close* of the last RTH bar (known at the close).
An overnight position enters at a known close and exits at a known open.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

try:  # canonical honesty helpers (reused, not reimplemented)
    from backtest._gate_v2_helpers import bootstrap_pf_ci_lower, classify_wfo_consistency
except ImportError:  # pragma: no cover - allow running as a loose script
    from _gate_v2_helpers import bootstrap_pf_ci_lower, classify_wfo_consistency

# ── MES contract + cost constants ────────────────────────────────────────────
MES_POINT_VALUE = 5.0  # $ per index point per contract
MES_COMMISSION_RT = 1.70  # $ round-trip (~$0.85/side)
MES_SLIPPAGE_PTS_RT = 1.0  # ~0.5 pt each side, conservative for a liquid micro

# RTH session in US/Eastern (handles DST via tz conversion).
_RTH_TZ = "America/New_York"
_RTH_OPEN = (9, 30)
_RTH_CLOSE = (16, 0)

# Honest-gate thresholds (mirror gate-v2 core where applicable).
PF_CI_LOWER_MIN = 1.10
P_EDGE_MIN = 0.95
# Beta-harvest gate variant (Tier-3 proposal, BETA_HARVEST_GATE_PROPOSAL.md): the
# 0.95 p_edge bar is mis-calibrated for a low-frequency long-beta harvest (no
# long-only strategy is profitable in 95% of windows). For a strategy explicitly
# graded `beta_harvest=True`, the chronological H1/H2 stationarity guard (already
# required in both modes) SUBSTITUTES for the near-deterministic win-rate, and the
# p_edge floor drops to 0.60 (clearly better than a coin). This is opt-in and
# default-off: it can only ever de-authorize less, never more.
BETA_HARVEST_P_EDGE_MIN = 0.60
DSR_MIN = 0.10  # we report annualized Sharpe as the risk-adjusted proxy
MAX_DD_PCT = 5.0


def _minutes(hm: tuple[int, int]) -> int:
    return hm[0] * 60 + hm[1]


def decompose_sessions(
    df: pd.DataFrame,
    *,
    tz: str = _RTH_TZ,
    rth_open: tuple[int, int] = _RTH_OPEN,
    rth_close: tuple[int, int] = _RTH_CLOSE,
) -> pd.DataFrame:
    """Decompose intraday bars into per-RTH-day open/close + session returns.

    Input: a DataFrame with a tz-aware (or UTC-naive) ``timestamp`` column and
    OHLC columns. Returns a DataFrame indexed by ET trading date with:
      - ``rth_open_px``  : open of the first RTH bar (>= 09:30 ET)
      - ``rth_close_px`` : close of the last RTH bar (<= 16:00 ET)
      - ``overnight_ret``: prior rth_close -> today rth_open  (held overnight)
      - ``intraday_ret`` : today rth_open  -> today rth_close (held intraday)
    """
    ts = pd.to_datetime(df["timestamp"], utc=True)
    et = ts.dt.tz_convert(tz)
    work = pd.DataFrame(
        {
            "date": et.dt.date,
            "tod_min": et.dt.hour * 60 + et.dt.minute,
            "open": df["open"].to_numpy(dtype=float),
            "close": df["close"].to_numpy(dtype=float),
        }
    )
    o_min, c_min = _minutes(rth_open), _minutes(rth_close)
    rth = work[(work["tod_min"] >= o_min) & (work["tod_min"] <= c_min)]
    if rth.empty:
        return pd.DataFrame(
            columns=["rth_open_px", "rth_close_px", "overnight_ret", "intraday_ret"]
        )

    rows = []
    for day, grp in rth.groupby("date", sort=True):
        grp = grp.sort_values("tod_min")
        rows.append((day, float(grp.iloc[0]["open"]), float(grp.iloc[-1]["close"])))
    out = pd.DataFrame(rows, columns=["date", "rth_open_px", "rth_close_px"]).set_index("date")

    prior_close = out["rth_close_px"].shift(1)
    out["overnight_ret"] = out["rth_open_px"] / prior_close - 1.0
    out["intraday_ret"] = out["rth_close_px"] / out["rth_open_px"] - 1.0
    return out


def decompose_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Decompose *daily* OHLC bars into the same session frame.

    For a daily bar the official open IS the RTH open and the close IS the RTH
    close, so no intraday-bar grouping is needed:
      - overnight_ret = today_open / prior_close - 1
      - intraday_ret  = today_close / today_open - 1
    Accepts a ``date`` (or ``timestamp``) column plus open/close.
    """
    date_col = "date" if "date" in df.columns else "timestamp"
    d = pd.to_datetime(df[date_col]).dt.date
    out = pd.DataFrame(
        {
            "rth_open_px": df["open"].to_numpy(dtype=float),
            "rth_close_px": df["close"].to_numpy(dtype=float),
        },
        index=list(d),
    )
    prior_close = out["rth_close_px"].shift(1)
    out["overnight_ret"] = out["rth_open_px"] / prior_close - 1.0
    out["intraday_ret"] = out["rth_close_px"] / out["rth_open_px"] - 1.0
    return out


def _cost_ret(entry_px: float) -> float:
    """Realistic MES round-trip cost expressed as a return on notional."""
    if entry_px <= 0:
        return 0.0
    cost_pts = (MES_COMMISSION_RT / MES_POINT_VALUE) + MES_SLIPPAGE_PTS_RT
    return cost_pts / entry_px


def leg_returns(sessions: pd.DataFrame, leg: str, *, net: bool = True) -> pd.Series:
    """Per-day long-leg return series, optionally net of round-trip cost."""
    if leg == "overnight":
        gross = sessions["overnight_ret"].copy()
        entry = sessions["rth_close_px"].shift(1)  # entered at prior close
    elif leg == "intraday":
        gross = sessions["intraday_ret"].copy()
        entry = sessions["rth_open_px"]  # entered at today's open
    else:  # pragma: no cover - guarded by callers
        raise ValueError(f"unknown leg {leg!r}")
    s = gross.dropna()
    if net:
        cost = entry.reindex(s.index).map(_cost_ret).fillna(0.0)
        s = s - cost
    return s


def profit_factor(returns: pd.Series) -> float:
    gains = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / abs(losses))


def _window_pfs(returns: pd.Series, freq: str = "ME") -> list[float]:
    """Profit factor per calendar window (default monthly)."""
    idx = pd.to_datetime(pd.Series(returns.index.astype(str)))
    s = pd.Series(returns.to_numpy(), index=idx)
    pfs: list[float] = []
    for _, grp in s.groupby(pd.Grouper(freq=freq)):
        if len(grp) == 0:
            continue
        pf = profit_factor(grp)
        if np.isfinite(pf):
            pfs.append(pf)
        elif grp.sum() > 0:
            pfs.append(5.0)  # cap degenerate all-win window (avoid inf in CI)
    return pfs


def annualized_sharpe(returns: pd.Series, periods_per_year: int = 252) -> float:
    r = returns.to_numpy(dtype=float)
    if r.std(ddof=1) == 0 or len(r) < 2:
        return 0.0
    return float(np.mean(r) / np.std(r, ddof=1) * np.sqrt(periods_per_year))


def max_drawdown_pct(returns: pd.Series) -> float:
    eq = (1.0 + returns).cumprod()
    peak = eq.cummax()
    dd = (eq - peak) / peak
    return float(abs(dd.min()) * 100.0)


@dataclass
class LegVerdict:
    leg: str
    net: bool
    n_days: int
    total_ret_pct: float
    pf: float
    pf_ci_lower: float
    p_edge: float
    sharpe: float
    max_dd_pct: float
    consistency: str
    n_windows: int
    h1_pf: float
    h2_pf: float
    h1_mean_bps: float
    h2_mean_bps: float
    stationary: bool
    verdict: str
    blocks: list[str] = field(default_factory=list)


def grade_returns(
    label: str, r: pd.Series, *, net: bool = True, beta_harvest: bool = False
) -> LegVerdict:
    """Grade an arbitrary daily-return series with the full honest gate.

    Shared by the session legs and the calendar tracks so every candidate is
    judged on the identical bar (gate-v2 thresholds + chronological H1/H2 split).

    ``beta_harvest`` (default-off) selects the Tier-3 beta-harvest variant: the
    p_edge floor drops from ``P_EDGE_MIN`` (0.95) to ``BETA_HARVEST_P_EDGE_MIN``
    (0.60), because for a long-beta harvest the chronological H1/H2 stationarity
    guard (still required) is the right substitute for a near-deterministic
    win-rate. Every other threshold (pf_ci_lower, Sharpe, max_dd, stationarity) is
    unchanged. Passing it is the *evaluation* opt-in; activating it for live
    promotion stays an Amo Tier-3 flip.
    """
    p_edge_floor = BETA_HARVEST_P_EDGE_MIN if beta_harvest else P_EDGE_MIN
    pfs = _window_pfs(r)
    pf = profit_factor(r)
    pf_ci = bootstrap_pf_ci_lower(pfs) if len(pfs) >= 2 else 0.0
    p_edge = float(np.mean([1.0 if p > 1.0 else 0.0 for p in pfs])) if pfs else 0.0
    consistency = classify_wfo_consistency(pfs) if pfs else "NONE"

    # Chronological H1/H2 split — the ES-NQ non-stationarity guard.
    n = len(r)
    h1, h2 = r.iloc[: n // 2], r.iloc[n // 2 :]
    h1_pf, h2_pf = profit_factor(h1), profit_factor(h2)
    h1_mean_bps, h2_mean_bps = h1.mean() * 1e4, h2.mean() * 1e4
    # Stationary if BOTH halves are individually profitable (PF>1) and neither
    # half carries an outsized share — i.e. the weaker half is still > 1.0.
    stationary = bool(h1_pf > 1.0 and h2_pf > 1.0)

    blocks: list[str] = []
    if pf_ci < PF_CI_LOWER_MIN:
        blocks.append(f"pf_ci_lower {pf_ci:.3f}<{PF_CI_LOWER_MIN}")
    if p_edge < p_edge_floor:
        blocks.append(f"p_edge {p_edge:.3f}<{p_edge_floor}")
    if annualized_sharpe(r) < DSR_MIN:
        blocks.append(f"sharpe<{DSR_MIN}")
    if max_drawdown_pct(r) > MAX_DD_PCT:
        blocks.append(f"max_dd {max_drawdown_pct(r):.2f}%>{MAX_DD_PCT}%")
    if not stationary:
        blocks.append(f"non-stationary (H1_pf {h1_pf:.2f} / H2_pf {h2_pf:.2f})")

    return LegVerdict(
        leg=label,
        net=net,
        n_days=n,
        total_ret_pct=float(((1.0 + r).prod() - 1.0) * 100.0),
        pf=pf,
        pf_ci_lower=pf_ci,
        p_edge=p_edge,
        sharpe=annualized_sharpe(r),
        max_dd_pct=max_drawdown_pct(r),
        consistency=consistency,
        n_windows=len(pfs),
        h1_pf=h1_pf,
        h2_pf=h2_pf,
        h1_mean_bps=float(h1_mean_bps),
        h2_mean_bps=float(h2_mean_bps),
        stationary=stationary,
        verdict="PASS" if not blocks else "FAIL",
        blocks=blocks,
    )


def evaluate_leg(sessions: pd.DataFrame, leg: str, *, net: bool = True) -> LegVerdict:
    """Honest evaluation of one session leg (overnight | intraday)."""
    return grade_returns(leg, leg_returns(sessions, leg, net=net), net=net)


# ── calendar / seasonality track (turn-of-month) ─────────────────────────────


def daily_close_returns(sessions: pd.DataFrame, *, net: bool = True) -> pd.Series:
    """Close-to-close daily returns (RTH close to RTH close), optional cost."""
    px = sessions["rth_close_px"].astype(float)
    r = px.pct_change().dropna()
    if net:
        cost = px.shift(1).reindex(r.index).map(_cost_ret).fillna(0.0)
        r = r - cost
    return r


def turn_of_month_mask(index, *, n_end: int = 1, n_start: int = 3) -> pd.Series:
    """Boolean mask: True on the last ``n_end`` trading days of a month and the
    first ``n_start`` trading days of the next (the turn-of-month window).

    Trading-day based (not calendar-day), computed from the actual session dates.
    """
    dt = pd.to_datetime(pd.Series(list(index)))
    ym = dt.dt.year * 12 + dt.dt.month
    # rank within month (1 = first trading day) and from-end rank (1 = last).
    grp = pd.Series(range(len(dt))).groupby(ym.to_numpy())
    rank_from_start = grp.cumcount() + 1
    size = ym.map(ym.value_counts())
    rank_from_end = size.to_numpy() - rank_from_start.to_numpy() + 1
    is_start = rank_from_start.to_numpy() <= n_start
    is_end = rank_from_end <= n_end
    return pd.Series((is_start | is_end), index=list(index))


def evaluate_turn_of_month(
    sessions: pd.DataFrame, *, net: bool = True, beta_harvest: bool = False
) -> LegVerdict:
    """Long MES only during the turn-of-month window, flat otherwise."""
    r = daily_close_returns(sessions, net=net)
    mask = turn_of_month_mask(r.index)
    tom = r[mask.to_numpy()]
    return grade_returns("turn_of_month", tom, net=net, beta_harvest=beta_harvest)


def day_of_week_summary(sessions: pd.DataFrame, *, net: bool = True) -> pd.DataFrame:
    """Descriptive mean close-to-close return (bps) and PF by weekday."""
    r = daily_close_returns(sessions, net=net)
    dt = pd.to_datetime(pd.Series(list(r.index)))
    out = []
    for wd in range(5):  # Mon..Fri
        sel = r[(dt.dt.dayofweek == wd).to_numpy()]
        if len(sel):
            out.append(
                {
                    "weekday": ["Mon", "Tue", "Wed", "Thu", "Fri"][wd],
                    "n": len(sel),
                    "mean_bps": float(sel.mean() * 1e4),
                    "pf": round(profit_factor(sel), 3),
                }
            )
    return pd.DataFrame(out)


def beta_size(r: pd.Series, *, dd_budget_pct: float = MAX_DD_PCT) -> tuple[pd.Series, float, float]:
    """Scale a long-beta return series down to a target max-drawdown budget.

    A long-equity harvest (overnight/TOM) inherits equity-like drawdown; sizing it
    to a fixed DD budget is the deployable form. Returns (scaled, scale, achieved_dd%).
    """
    dd = max_drawdown_pct(r)
    if dd <= 0:
        return r, 1.0, 0.0
    scale = dd_budget_pct / dd
    rs = r * scale
    return rs, scale, max_drawdown_pct(rs)


def gate_v2_verdict(
    r: pd.Series,
    *,
    freq: str = "YE",
    n_grid_combos: int = 1,
    cost_survives: str = "realistic",
) -> dict:
    """Rigorous gate-v2 verdict via the canonical ``compute_gate_v2``.

    Feeds chronological (default yearly) windows of the return series as OOS
    results. ``n_grid_combos=1`` because the strategy is parameter-free (no
    multiple-testing penalty on the deflated Sharpe). ``fixed_params_min_pf`` is the
    full-sample PF -- the only params there are. DD is passed as a fraction to match
    the gate convention (GATE_MC_DD_CORE = 0.05).
    """
    from types import SimpleNamespace

    from backtest.wfo_lifecycle import compute_gate_v2

    idx = pd.to_datetime(pd.Series(list(r.index)))
    s = pd.Series(r.to_numpy(), index=idx)
    windows = []
    for _, grp in s.groupby(pd.Grouper(freq=freq)):
        if len(grp) == 0:
            continue
        pf = profit_factor(grp)
        windows.append(
            SimpleNamespace(
                total_trades=int(len(grp)),
                profit_factor=float(pf if np.isfinite(pf) else 5.0),
                max_drawdown_pct=float(max_drawdown_pct(grp) / 100.0),
                sharpe_ratio=float(annualized_sharpe(grp)),
            )
        )
    full_pf = profit_factor(r)
    return compute_gate_v2(
        windows,
        n_grid_combos,
        {"fixed_params_min_pf": float(full_pf if np.isfinite(full_pf) else 5.0)},
        {"cost_survives_through": cost_survives},
    )


def gate_v2_beta_harvest_verdict(r: pd.Series, **kwargs) -> dict:
    """Beta-harvest variant of the CANONICAL gate-v2 verdict (Tier-3 proposal).

    Wraps — never modifies — ``compute_gate_v2`` (via ``gate_v2_verdict``). If the
    canonical verdict FAILs the core path on ONE criterion that is exactly p_edge,
    AND p_edge clears the lower beta-harvest floor (``BETA_HARVEST_P_EDGE_MIN``),
    AND the series is chronologically stationary (H1 and H2 PF both > 1 — the
    substitute for the near-deterministic win-rate), the verdict is reclassified to
    PASS. Any other failing criterion (pf_ci_lower, dsr, mc_dd) is NOT rescued, so
    this can only ever de-authorize less, never more — the canonical gate is the
    source of truth and this is an explicit, tagged overlay for a beta-harvest
    strategy class. Activating it for live promotion remains an Amo Tier-3 flip.
    """
    v = gate_v2_verdict(r, **kwargs)
    out = dict(v)
    out["beta_harvest"] = True
    out["beta_harvest_reclassified"] = False
    if v.get("verdict") == "PASS":
        return out  # already passes the canonical core/alt path; nothing to do

    failed = [c for c in v.get("core_reasons", []) if c.strip().upper().startswith("FAIL")]
    only_p_edge = len(failed) == 1 and "p_edge" in failed[0]

    n = len(r)
    h1, h2 = r.iloc[: n // 2], r.iloc[n // 2 :]
    stationary = bool(profit_factor(h1) > 1.0 and profit_factor(h2) > 1.0)
    p_edge = float(v.get("p_edge", 0.0))

    if only_p_edge and p_edge >= BETA_HARVEST_P_EDGE_MIN and stationary:
        out["verdict"] = "PASS"
        out["beta_harvest_reclassified"] = True
        out["beta_harvest_note"] = (
            f"canonical core FAILs only on p_edge ({p_edge:.3f} < {P_EDGE_MIN}); "
            f"beta-harvest variant clears it (p_edge {p_edge:.3f} >= "
            f"{BETA_HARVEST_P_EDGE_MIN} AND stationary H1/H2 PF>1)"
        )
    return out


_DEFAULT_CACHE = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache")


def _format_verdict(v: LegVerdict) -> str:
    head = "PASS" if v.verdict == "PASS" else "FAIL"
    lines = [
        f"--- MES {v.leg.upper()} leg ({'net' if v.net else 'gross'} of cost): {head} ---",
        f"  days={v.n_days}  total_ret={v.total_ret_pct:+.2f}%  PF={v.pf:.3f}  "
        f"PF_ci_lower={v.pf_ci_lower:.3f}",
        f"  p_edge={v.p_edge:.3f}  sharpe={v.sharpe:.3f}  maxDD={v.max_dd_pct:.2f}%  "
        f"consistency={v.consistency} (n_win={v.n_windows})",
        f"  H1_pf={v.h1_pf:.2f} ({v.h1_mean_bps:+.2f}bps/day)  "
        f"H2_pf={v.h2_pf:.2f} ({v.h2_mean_bps:+.2f}bps/day)  stationary={v.stationary}",
    ]
    if v.blocks:
        lines.append("  blocked by: " + "; ".join(v.blocks))
    return "\n".join(lines)


def run(csv_path: Path, *, net: bool = True) -> dict[str, LegVerdict]:
    df = pd.read_csv(csv_path)
    sessions = decompose_sessions(df)
    results = {leg: evaluate_leg(sessions, leg, net=net) for leg in ("overnight", "intraday")}
    results["turn_of_month"] = evaluate_turn_of_month(sessions, net=net)
    print(f"MES session-anomaly backtest — {csv_path.name}  ({len(sessions)} RTH days)\n")
    for v in results.values():
        print(_format_verdict(v))
        print()
    print("Day-of-week (close-to-close, net):")
    print(day_of_week_summary(sessions, net=net).to_string(index=False))
    return results


def overnight_era_table(sessions: pd.DataFrame, *, years: int = 5) -> pd.DataFrame:
    """Overnight-leg PF and mean bps by multi-year era — the regime-stationarity view."""
    r = leg_returns(sessions, "overnight", net=False)
    dt = pd.to_datetime(pd.Series(list(r.index)))
    era = (dt.dt.year // years) * years
    out = []
    for e, grp in pd.Series(r.to_numpy(), index=era.to_numpy()).groupby(level=0):
        out.append(
            {
                "era": f"{int(e)}-{int(e) + years - 1}",
                "n": len(grp),
                "mean_bps": round(float(grp.mean() * 1e4), 2),
                "pf": round(profit_factor(grp), 3),
            }
        )
    return pd.DataFrame(out)


def run_daily(csv_path: Path, *, net: bool = False) -> dict[str, LegVerdict]:
    """Run the session + calendar tracks on a *daily* OHLC series (e.g. SPY)."""
    df = pd.read_csv(csv_path)
    sessions = decompose_daily(df)
    results = {leg: evaluate_leg(sessions, leg, net=net) for leg in ("overnight", "intraday")}
    results["turn_of_month"] = evaluate_turn_of_month(sessions, net=net)
    span = f"{sessions.index[0]}..{sessions.index[-1]}"
    print(
        f"DAILY session-anomaly backtest — {csv_path.name}  "
        f"({len(sessions)} days, {span}, {'net' if net else 'gross'})\n"
    )
    for v in results.values():
        print(_format_verdict(v))
        print()
    print("Overnight PF by era (regime-stationarity view):")
    print(overnight_era_table(sessions).to_string(index=False))
    print("\nDay-of-week (close-to-close):")
    print(day_of_week_summary(sessions, net=net).to_string(index=False))
    return results


def _tom_series(sessions: pd.DataFrame, *, net: bool) -> pd.Series:
    r = daily_close_returns(sessions, net=net)
    return r[turn_of_month_mask(r.index).to_numpy()]


def validate_tom(
    spy_csv: Path,
    mes_csv: Path | None = None,
    *,
    cost_bps: float = 2.0,
    dd_budget: float = MAX_DD_PCT,
) -> dict:
    """Productionize the turn-of-month candidate: rigorous gate-v2 on SPY (powered
    sample), beta-sized to the DD budget, plus the MES transfer check."""
    spy = decompose_daily(pd.read_csv(spy_csv))
    tom = _tom_series(spy, net=False)
    tom_net = tom - cost_bps / 1e4
    sized, scale, dd = beta_size(tom_net, dd_budget_pct=dd_budget)
    out = {
        "spy_n": len(tom),
        "sharpe_gross": annualized_sharpe(tom),
        "sharpe_net": annualized_sharpe(tom_net),
        "raw_dd_pct": max_drawdown_pct(tom_net),
        "beta_scale": scale,
        "sized_dd_pct": dd,
        "gate_gross": gate_v2_verdict(tom),
        "gate_net": gate_v2_verdict(tom_net),
        "gate_net_sized": gate_v2_verdict(sized),
    }
    print(
        f"SPY turn-of-month: n={out['spy_n']}  Sharpe {out['sharpe_gross']:.3f} gross / "
        f"{out['sharpe_net']:.3f} net@{cost_bps:.0f}bps  rawDD={out['raw_dd_pct']:.1f}%  "
        f"beta-size x{scale:.3f} -> DD {dd:.2f}%\n"
    )
    for k in ("gate_gross", "gate_net", "gate_net_sized"):
        v = out[k]
        print(
            f"  {k:14s}: {v.get('verdict')} (via {v.get('passed_via')})  "
            f"pf_ci={v.get('pf_ci_lower'):.3f} p_edge={v.get('p_edge'):.3f} "
            f"mc95_dd={v.get('mc_95th_dd'):.4f} dsr={v.get('dsr'):.3f} wfo={v.get('wfo_consistency')}"
        )
    if mes_csv is not None and Path(mes_csv).exists():
        mtom = _tom_series(decompose_sessions(pd.read_csv(mes_csv)), net=True)
        out["mes_transfer"] = {
            "n": len(mtom),
            "sharpe": annualized_sharpe(mtom),
            "pf": profit_factor(mtom),
            "mean_bps": float(mtom.mean() * 1e4),
        }
        m = out["mes_transfer"]
        print(
            f"\n  MES transfer (net of MES cost): n={m['n']}  Sharpe {m['sharpe']:.3f}  "
            f"PF {m['pf']:.3f}  mean {m['mean_bps']:.2f} bps/day"
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="overnight-drift / session anomaly backtest")
    ap.add_argument("--csv", type=Path, default=None, help="explicit CSV")
    ap.add_argument("--cache-dir", type=Path, default=_DEFAULT_CACHE)
    ap.add_argument("--gross", action="store_true", help="evaluate gross of cost")
    ap.add_argument("--daily", action="store_true", help="input is daily OHLC (e.g. SPY)")
    ap.add_argument("--validate-tom", action="store_true", help="productionize turn-of-month")
    args = ap.parse_args()
    csv = args.csv
    if args.validate_tom:
        spy = args.csv or (args.cache_dir / "SPY_daily.csv")
        mes_cands = sorted(args.cache_dir.glob("MES_*_5m_cont.csv"))
        mes = max(mes_cands, key=lambda p: p.stat().st_size) if mes_cands else None
        validate_tom(spy, mes)
        return
    if args.daily:
        if csv is None:
            csv = args.cache_dir / "SPY_daily.csv"
        run_daily(csv, net=not args.gross)
        return
    if csv is None:
        cands = sorted(args.cache_dir.glob("MES_*_5m_cont.csv"))
        if not cands:
            raise SystemExit(f"no MES 5m cache CSV under {args.cache_dir}")
        csv = max(cands, key=lambda p: p.stat().st_size)
    run(csv, net=not args.gross)


if __name__ == "__main__":
    main()
