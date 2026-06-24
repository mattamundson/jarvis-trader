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


def evaluate_leg(sessions: pd.DataFrame, leg: str, *, net: bool = True) -> LegVerdict:
    """Full honest evaluation of one session leg, incl. chronological H1/H2 split."""
    r = leg_returns(sessions, leg, net=net)
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
    if p_edge < P_EDGE_MIN:
        blocks.append(f"p_edge {p_edge:.3f}<{P_EDGE_MIN}")
    if annualized_sharpe(r) < DSR_MIN:
        blocks.append(f"sharpe<{DSR_MIN}")
    if max_drawdown_pct(r) > MAX_DD_PCT:
        blocks.append(f"max_dd {max_drawdown_pct(r):.2f}%>{MAX_DD_PCT}%")
    if not stationary:
        blocks.append(f"non-stationary (H1_pf {h1_pf:.2f} / H2_pf {h2_pf:.2f})")

    return LegVerdict(
        leg=leg,
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
    print(f"MES session-anomaly backtest — {csv_path.name}  ({len(sessions)} RTH days)\n")
    for v in results.values():
        print(_format_verdict(v))
        print()
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="MES overnight-drift / session anomaly backtest")
    ap.add_argument("--csv", type=Path, default=None, help="explicit MES intraday CSV")
    ap.add_argument("--cache-dir", type=Path, default=_DEFAULT_CACHE)
    ap.add_argument("--gross", action="store_true", help="evaluate gross of cost")
    args = ap.parse_args()
    csv = args.csv
    if csv is None:
        cands = sorted(args.cache_dir.glob("MES_*_5m_cont.csv"))
        if not cands:
            raise SystemExit(f"no MES 5m cache CSV under {args.cache_dir}")
        csv = max(cands, key=lambda p: p.stat().st_size)
    run(csv, net=not args.gross)


if __name__ == "__main__":
    main()
