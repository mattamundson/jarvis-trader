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

from backtest._gate_v2_helpers import _find_latest_cache, bootstrap_pf_ci_lower
from backtest.wfo_lifecycle import compute_gate_v2

CACHE_DIR = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache")
DEFAULT_SYMBOLS = ("SPY", "QQQ", "IWM", "GLD", "DIA")
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


def grade(returns: pd.Series, n_grid_combos: int = 1) -> dict:
    """Grade a long-on-selected-days daily-return series on the honest bar."""
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
        rows.append({"symbol": symbol, "effect": name, **grade(r, n_grid_combos=n_eff)})
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
