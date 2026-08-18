"""
vbt_mes_sweep.py — vectorbt-powered 54-combo MES SMA-trend parameter sweep.

Replicates the JARVIS MES live strategy signal logic 1:1 from
engine/backtest/trend_signals.py::generate_sma_trend_signals (defaults:
min_rv_annualized=0.0, no VIX gates):

    Entry : fast SMA crosses above slow SMA (golden cross) — LONG only,
            requires previous bar slow SMA valid (guards spurious first-cross).
    Exit  : fast SMA crosses below slow SMA (death cross) OR ATR(14) trail hit.
    Stop  : trail = max(entry_stop, ratchet up with price - mult*ATR(14));
            trail only moves UP. Initial stop = close - mult*ATR at signal bar.
    Fill  : vectorbt Portfolio.from_signals, close-of-signal-bar fills,
            longonly, 1 contract, $0.62 fixed fee per order (MES commission).

Metrics are HONEST per JARVIS metric-defect audit (2026-08-17):
  - CAGR from total return over the real data span (not a 252-per-year assumption)
  - Sharpe deflated: per-trade returns, annualized by sqrt(actual trades/yr)
  - Profit factor / win rate from the trade log

Benchmark target: full 54-combo grid on the MES 1h deep cache (42,826 bars)
in < 5 minutes wall time. Expected: a few seconds — vectorbt broadcasts all
54 combos as columns of a single Portfolio.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import vectorbt as vbt
except ImportError as e:  # pragma: no cover
    sys.exit(f"vectorbt not installed: {e}")

ATR_PERIOD = 14
MES_POINT_VALUE = 5.0
MES_FIXED_FEE = 0.62  # $/contract/side

# 54 combos = fast(3) x slow(6) x atr_mult(3); includes certified champion 50/200/2.0
DEFAULT_GRID = {
    "fast": [40, 50, 60],
    "slow": [100, 150, 200, 250, 300, 350],
    "atr_trail_mult": [1.5, 2.0, 2.5],
}


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = ATR_PERIOD) -> np.ndarray:
    """Wilder ATR — matches trend_signals._wilder_atr (ewm alpha=1/period, adjust=False)."""
    prev_c = np.empty_like(close)
    prev_c[0] = np.nan
    prev_c[1:] = close[:-1]
    tr = np.maximum.reduce(
        [high - low, np.abs(high - prev_c), np.abs(low - prev_c)]
    )
    tr_s = pd.Series(tr)
    atr = tr_s.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean().to_numpy()
    return atr


def rolling_mean_matrix(close: np.ndarray, windows: list[int]) -> dict[int, np.ndarray]:
    """Rolling means for several windows at once, fully vectorized (cumsum)."""
    out: dict[int, np.ndarray] = {}
    cs = np.concatenate([[0.0], np.cumsum(close)])
    for w in windows:
        if w >= len(close):
            out[w] = np.full(len(close), np.nan)
            continue
        means = (cs[w:] - cs[:-w]) / w
        arr = np.full(len(close), np.nan)
        arr[w - 1:] = means
        out[w] = arr
    return out


def build_combos(grid: dict[str, list]) -> pd.DataFrame:
    rows = []
    for f in grid["fast"]:
        for s in grid["slow"]:
            for m in grid["atr_trail_mult"]:
                rows.append({"fast": f, "slow": s, "atr_trail_mult": m})
    df = pd.DataFrame(rows)
    if len(df) != 54:
        print(f"WARNING: grid produced {len(df)} combos (expected 54)", file=sys.stderr)
    return df


def generate_signals_vectorized(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    combos: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized state machine producing entries/exits (B x C) for every combo.

    Column-parallel O(B) loop; matches trend_signals.py bar-loop semantics:
    - entry at golden cross (prev slow SMA valid), resets trail, no same-bar exit
    - trail ratchets up while in trade; exit on death cross or low <= trail
    """
    b, c = len(close), len(combos)
    atr = wilder_atr(high, low, close)  # same for every combo (period fixed)
    atr_valid = ~np.isnan(atr)

    fast_windows = sorted({int(f) for f in combos["fast"]})
    slow_windows = sorted({int(s) for s in combos["slow"]})
    sma_fast_all = rolling_mean_matrix(close, fast_windows)
    sma_slow_all = rolling_mean_matrix(close, slow_windows)
    # (B x n_unique_windows) matrices + per-combo window index maps
    fast_mat = np.column_stack([sma_fast_all[w] for w in fast_windows])
    slow_mat = np.column_stack([sma_slow_all[w] for w in slow_windows])
    fast_idx = np.array([fast_windows.index(int(f)) for f in combos["fast"]])
    slow_idx = np.array([slow_windows.index(int(s)) for s in combos["slow"]])

    entries = np.zeros((b, c), dtype=bool)
    exits = np.zeros((b, c), dtype=bool)

    in_trade = np.zeros(c, dtype=bool)
    trail = np.full(c, np.nan)
    mult = combos["atr_trail_mult"].to_numpy(dtype=float)

    prev_above = np.zeros(c, dtype=bool)
    prev_slow_valid = np.zeros(c, dtype=bool)

    for i in range(b):
        f_vals = fast_mat[i][fast_idx]
        s_vals = slow_mat[i][slow_idx]
        above = f_vals > s_vals
        atr_i = atr[i]
        atr_ok = atr_valid[i]

        cross_up = above & ~prev_above & prev_slow_valid & atr_ok
        cross_dn = (~above) & prev_above & prev_slow_valid & atr_ok

        new_trade = cross_up
        entries[i] = new_trade

        # initialize trail on entry bars (engine: entry bar sets initial stop, no exit check)
        if new_trade.any():
            trail[new_trade] = close[i] - mult[new_trade] * atr_i

        in_trade = in_trade | new_trade

        # ratchet trail for continuing trades (engine: elif in_trade branch)
        cont = in_trade & ~new_trade
        if cont.any():
            cand = close[i] - mult * atr_i
            better = cand > trail
            upd = cont & better & ~np.isnan(trail)
            trail[upd] = cand[upd]

        # exit check (same-bar order as engine: ratchet first, then exit)
        hit = in_trade & ~new_trade & (atr_ok & ((low[i] <= trail) | cross_dn))
        hit = hit & ~np.isnan(trail)
        exits[i] = hit
        in_trade[hit] = False
        trail[hit] = np.nan

        prev_above = above
        prev_slow_valid = ~np.isnan(s_vals)

    return entries, exits


def honest_metrics(pf, combos: pd.DataFrame, years: float) -> pd.DataFrame:
    """Per-combo metrics with JARVIS-honest Sharpe/CAGR (deflated annualization)."""
    trades = pf.trades
    total_return = pf.total_return()
    n_trades = trades.count()
    max_dd = pf.max_drawdown()
    win_rate = trades.win_rate()
    profit_factor = trades.profit_factor()

    # per-combo pnl stats straight from the trade records frame (avoids the
    # 0.28 MappedArray single-column indexing trap)
    records = trades.records
    rec = records[["col", "pnl"]].dropna(subset=["pnl"]) if "pnl" in records.columns else None
    pnl_mu = rec.groupby("col")["pnl"].mean() if rec is not None else pd.Series(dtype=float)
    pnl_sd = rec.groupby("col")["pnl"].std() if rec is not None else pd.Series(dtype=float)

    rows = []
    for i in range(len(combos)):
        nt = int(n_trades.iloc[i])
        if nt >= 2 and i in pnl_sd.index and float(pnl_sd.loc[i]) > 0:
            mu = float(pnl_mu.loc[i])
            sd = float(pnl_sd.loc[i])
            trades_per_year = nt / years if years > 0 else 0.0
            sharpe = (mu / sd) * np.sqrt(trades_per_year)
        else:
            sharpe = np.nan
        tr_i = float(total_return.iloc[i])
        cagr = (1.0 + tr_i) ** (1.0 / years) - 1.0 if years > 0 and tr_i > -1.0 else tr_i
        rows.append(
            {
                "fast": int(combos["fast"].iloc[i]),
                "slow": int(combos["slow"].iloc[i]),
                "atr_mult": float(combos["atr_trail_mult"].iloc[i]),
                "total_return": tr_i,
                "honest_cagr": cagr,
                "trades": nt,
                "win_rate": float(win_rate.iloc[i]) if nt else np.nan,
                "profit_factor": float(profit_factor.iloc[i]) if nt else np.nan,
                "honest_sharpe": sharpe,
                "max_dd": float(max_dd.iloc[i]),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=None, help="MES 1h deep cache CSV (default: repo cache path)")
    ap.add_argument("--out-dir", default=".", help="Directory for results CSV")
    ap.add_argument("--grid-json", default=None, help="Optional JSON grid override")
    args = ap.parse_args()

    if args.csv:
        csv_path = Path(args.csv)
    else:
        csv_path = Path(r"C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache/MES_2015-01-01_2026-08-16_1h.csv")
    if not csv_path.exists():
        sys.exit(f"cache not found: {csv_path}")

    t_load = time.perf_counter()
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n_bars = len(df)
    span = (df.index[-1] - df.index[0]).total_seconds() / (365.25 * 24 * 3600)
    t_load_done = time.perf_counter()

    grid = DEFAULT_GRID
    if args.grid_json:
        with open(args.grid_json) as fh:
            grid = json.load(fh)
    combos = build_combos(grid)
    c = len(combos)
    print(f"data: {n_bars} bars, span {span:.2f} yrs, combos: {c}")

    t_sig = time.perf_counter()
    entries, exits = generate_signals_vectorized(close, high, low, combos)
    t_sig_done = time.perf_counter()

    close_df = pd.DataFrame(np.tile(close[:, None], (1, c)), index=df.index,
                            columns=[f"c{i}" for i in range(c)])

    t_pf = time.perf_counter()
    pf = vbt.Portfolio.from_signals(
        close_df,
        entries=pd.DataFrame(entries, index=df.index, columns=close_df.columns),
        exits=pd.DataFrame(exits, index=df.index, columns=close_df.columns),
        direction="longonly",
        size=1.0,
        init_cash=100_000.0,
        fixed_fees=MES_FIXED_FEE,
        freq="1h",
    )
    t_pf_done = time.perf_counter()

    t_metrics = time.perf_counter()
    res = honest_metrics(pf, combos, years=span)
    t_metrics_done = time.perf_counter()

    wall_total = t_metrics_done - t_load
    timings = {
        "load": round(t_load_done - t_load, 3),
        "signals": round(t_sig_done - t_sig, 3),
        "portfolio_build": round(t_pf_done - t_pf, 3),
        "metrics": round(t_metrics_done - t_metrics, 3),
        "total": round(wall_total, 3),
    }
    print("timings_s:", json.dumps(timings))
    print(f"TARGET < 300s: {'PASS' if wall_total < 300 else 'FAIL'} ({wall_total:.2f}s)")

    with pd.option_context("display.width", 160, "display.max_columns", 30):
        print(res.sort_values("honest_cagr", ascending=False).to_string(index=False))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res_path = out_dir / "vbt_mes_54combo_results.csv"
    res.to_csv(res_path, index=False)
    with (out_dir / "vbt_mes_54combo_timings.json").open("w") as fh:
        json.dump({"bars": n_bars, "span_years": round(span, 3), "combos": c, "timings_s": timings}, fh, indent=2)
    print(f"wrote: {res_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
