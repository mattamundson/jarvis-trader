"""CLI runner for the permutation tests against real (or sample) jarvis-trader data.

Three subcommands:

    prices  -- load a 1h OHLC cache CSV for a symbol and run the bar-permutation MCPT
               (analytics.permutation_test.validate_strategy) with a reference SMA-trend
               optimizer in the approved MES/MGC family.
    trades  -- load closed paper trades (SQLite paper_trades, or a CSV with a 'pnl'
               column) and run the trade-sign permutation test (permute_and_score).
    make-sample -- write a CLEARLY-LABELED synthetic OHLC CSV and a sample paper_trades
               SQLite DB so the plumbing can be exercised before real data lands.

IMPORTANT -- data integrity:
  * Real verdicts require REAL data. The make-sample outputs are synthetic and named with
    a SAMPLE_ prefix; any p-value computed on them is meaningless and the runner prints a
    loud warning when it detects sample inputs.
  * The bundled optimizer is a SIMPLIFIED SMA-trend proxy (no ATR trailing / targets /
    cost model), so a `prices` verdict is INDICATIVE, not the gate-v2 authority. Wiring
    the real ``backtest.backtester.Backtester`` as the optimize_fn is the production step
    (and any move from diagnostic to blocking gate is a separate [safety-review] change).

Examples:
    python -m backtest.run_mcpt make-sample --symbol MES
    python -m backtest.run_mcpt prices --symbol MES
    python -m backtest.run_mcpt trades --db data/jarvis_trader.db --symbol MES
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from analytics.permutation_test import permute_and_score, run_insample_mcpt, validate_strategy

_HERE = Path(__file__).resolve().parent
CACHE_DIR = _HERE / "cache"
DEFAULT_DB = _HERE.parent / "data" / "jarvis_trader.db"
_SAMPLE_PREFIX = "SAMPLE_"
_OHLC = ["open", "high", "low", "close"]

# Reference SMA-trend grid (brackets the approved MES SMA(60,200) / MGC SMA(50,120)).
_SMA_PAIRS = [(f, s) for f in (10, 20, 30, 50, 60) for s in (100, 120, 150, 200) if f < s]


# ── reference strategy (simplified SMA-trend proxy) ─────────────────────────────

def _pf(close: np.ndarray, fast: int, slow: int) -> float:
    """Profit factor of 'long when fast SMA > slow SMA', decided at t-1 (no look-ahead)."""
    c = pd.Series(close)
    pos = (c.rolling(fast).mean() > c.rolling(slow).mean()).astype(float).shift(1).to_numpy()
    r = np.diff(np.log(close), prepend=np.log(close[0]))
    pnl = (pos * r)[~np.isnan(pos)]
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl < 0].sum())
    return gp / gl if gl > 0 else (gp if gp > 0 else 0.0)


def _optimize_fn(df: pd.DataFrame) -> tuple[tuple[int, int], float]:
    c = df["close"].to_numpy(dtype=float)
    return max(((p, _pf(c, *p)) for p in _SMA_PAIRS), key=lambda x: x[1])


def _walkforward_fn(df: pd.DataFrame, train_window: int, step: int = 250) -> float:
    c = df["close"].to_numpy(dtype=float)
    n = len(c)
    pnls: list[np.ndarray] = []
    start = train_window
    while start < n - 1:
        bp = max(_SMA_PAIRS, key=lambda p: _pf(c[start - train_window:start], *p))
        end = min(start + step, n)
        seg = c[start - max(bp):end]
        s = pd.Series(seg)
        pos = (s.rolling(bp[0]).mean() > s.rolling(bp[1]).mean()).astype(float).shift(1).to_numpy()
        r = np.diff(np.log(seg), prepend=np.log(seg[0]))
        pnls.append((pos * r)[-(end - start):][~np.isnan((pos * r)[-(end - start):])])
        start = end
    pnl = np.concatenate(pnls) if pnls else np.array([0.0])
    gp = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl < 0].sum())
    return gp / gl if gl > 0 else (gp if gp > 0 else 0.0)


# ── loaders ─────────────────────────────────────────────────────────────────────

def _find_cache(symbol: str) -> Path | None:
    real = sorted(CACHE_DIR.glob(f"{symbol.upper()}_*_1h.csv"))
    if real:
        return real[-1]
    sample = sorted(CACHE_DIR.glob(f"{_SAMPLE_PREFIX}{symbol.upper()}_*_1h.csv"))
    return sample[-1] if sample else None


def _load_ohlc(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts] = pd.to_datetime(df[ts])
    df = df.set_index(ts).sort_index()
    missing = set(_OHLC) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} missing columns: {missing}")
    return df


def _load_trade_pnls(db: Path | None, csv: Path | None, symbol: str | None) -> list[float]:
    if csv is not None:
        d = pd.read_csv(csv)
        d.columns = [c.lower() for c in d.columns]
        if symbol and "symbol" in d.columns:
            d = d[d["symbol"].str.upper() == symbol.upper()]
        return [float(x) for x in d["pnl"].dropna()]
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        if symbol:
            rows = conn.execute(
                "SELECT pnl FROM paper_trades WHERE status='closed' AND symbol=? AND pnl IS NOT NULL",
                (symbol.upper(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT pnl FROM paper_trades WHERE status='closed' AND pnl IS NOT NULL"
            ).fetchall()
        return [float(r["pnl"]) for r in rows]
    finally:
        conn.close()


# ── sample-data generation (synthetic — for plumbing only) ──────────────────────

def _make_sample(symbol: str, n_bars: int = 2500, n_trades: int = 80, seed: int = 0) -> tuple[Path, Path]:
    rng = np.random.default_rng(seed)
    # Regime-switching drift so the SMA-trend proxy has *some* structure to find.
    drift = np.concatenate([np.full(120, d) for d in
                            rng.choice((0.0008, -0.0008), size=n_bars // 120 + 1)])[:n_bars]
    close = 4000.0 * np.exp(np.cumsum(drift + rng.normal(0, 0.004, n_bars)))
    open_ = np.empty(n_bars)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="h")
    csv = CACHE_DIR / f"{_SAMPLE_PREFIX}{symbol.upper()}_2024-01-01_2024-12-31_1h.csv"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "timestamp": idx, "open": open_,
        "high": np.maximum(open_, close) * 1.0006,
        "low": np.minimum(open_, close) * 0.9994, "close": close,
    }).to_csv(csv, index=False)

    db = _HERE.parent / "data" / f"{_SAMPLE_PREFIX.lower()}paper_trades_{symbol.lower()}.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS paper_trades (id INTEGER PRIMARY KEY, symbol TEXT, "
            "status TEXT, entry_time TEXT, exit_time TEXT, pnl REAL, strategy_params TEXT)"
        )
        conn.execute("DELETE FROM paper_trades")
        pnls = rng.normal(12.0, 90.0, n_trades)  # slight positive mean -> plausible edge
        for i, p in enumerate(pnls):
            et = (pd.Timestamp("2025-01-01") + pd.Timedelta(days=2 * i)).isoformat()
            conn.execute(
                "INSERT INTO paper_trades (symbol, status, entry_time, exit_time, pnl, strategy_params) "
                "VALUES (?,?,?,?,?,?)",
                (symbol.upper(), "closed", et, et, float(p), "{}"),
            )
        conn.commit()
    finally:
        conn.close()
    return csv, db


def _is_sample(path: Path) -> bool:
    return path.name.startswith(_SAMPLE_PREFIX) or path.name.startswith(_SAMPLE_PREFIX.lower())


# ── commands ──────────────────────────────────────────────────────────────────

def _warn_if_sample(path: Path) -> None:
    if _is_sample(path):
        print(f"  !! WARNING: {path.name} is SYNTHETIC sample data — this verdict is "
              "plumbing-only and statistically meaningless. Replace with real data.\n")


def cmd_prices(args: argparse.Namespace) -> int:
    path = Path(args.csv) if args.csv else _find_cache(args.symbol)
    if path is None or not path.exists():
        print(f"No 1h cache for {args.symbol} in {CACHE_DIR} (real or SAMPLE_). "
              "Run 'make-sample' or drop a real CSV in.")
        return 2
    df = _load_ohlc(path)
    print(f"Loaded {path.name}: {len(df)} bars, {df.index[0].date()} -> {df.index[-1].date()}")
    _warn_if_sample(path)
    tw = args.train_window
    is_res = run_insample_mcpt(df, _optimize_fn, n_permutations=args.insample_perms, seed=0)
    print(f"in-sample MCPT : best={is_res['real_params']} real_pf={is_res['real_pf']} "
          f"perm_mean={is_res['perm_pf_mean']} p={is_res['p_value']} pass={is_res['passes']}")
    out = validate_strategy(df, _optimize_fn, _walkforward_fn, train_window=tw,
                            n_insample_perms=args.insample_perms, n_wf_perms=args.wf_perms,
                            seed=0, long_history=args.long_history)
    print(f"VERDICT: {out['verdict']}")
    for k in ("is_pf", "is_pval", "wf_pf", "wf_pval"):
        if k in out:
            print(f"   {k} = {out[k]}")
    print("\n(Reference SMA-trend proxy — indicative, not the gate-v2 authority.)")
    return 0


def cmd_trades(args: argparse.Namespace) -> int:
    db = Path(args.db) if args.db else (DEFAULT_DB if DEFAULT_DB.exists() else None)
    csv = Path(args.csv) if args.csv else None
    if db is None and csv is None:
        print("No trades source. Pass --db <sqlite> or --csv <file with pnl column>.")
        return 2
    pnls = _load_trade_pnls(db, csv, args.symbol)
    src = csv or db
    print(f"Loaded {len(pnls)} closed trades from {Path(src).name}"
          f"{' for ' + args.symbol if args.symbol else ''}")
    if src and _is_sample(Path(src)):
        _warn_if_sample(Path(src))
    res = permute_and_score(pnls, n_iters=args.iters, metric=args.metric)
    print(f"trade-sign test ({res['metric']}): real_score={res['real_score']} "
          f"p={res['p_value']} pass(<{res['alpha']})={res['passes']} n_trades={res['n_trades']}")
    return 0


def cmd_make_sample(args: argparse.Namespace) -> int:
    csv, db = _make_sample(args.symbol)
    print(f"Wrote SAMPLE price cache : {csv}")
    print(f"Wrote SAMPLE trades DB   : {db}")
    print("\nThese are SYNTHETIC. Use for plumbing only:")
    print(f"  python -m backtest.run_mcpt prices --symbol {args.symbol}")
    print(f"  python -m backtest.run_mcpt trades --db {db} --symbol {args.symbol}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run_mcpt", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("prices", help="bar-permutation MCPT on a 1h OHLC cache")
    pp.add_argument("--symbol", default="MES")
    pp.add_argument("--csv", default=None, help="explicit CSV path (overrides cache lookup)")
    pp.add_argument("--train-window", type=int, default=600)
    pp.add_argument("--insample-perms", type=int, default=300)
    pp.add_argument("--wf-perms", type=int, default=100)
    pp.add_argument("--long-history", action="store_true", help="use stricter walk-forward alpha")
    pp.set_defaults(func=cmd_prices)

    pt = sub.add_parser("trades", help="trade-sign permutation test on closed trades")
    pt.add_argument("--db", default=None, help="SQLite DB with a paper_trades table")
    pt.add_argument("--csv", default=None, help="CSV with a 'pnl' column")
    pt.add_argument("--symbol", default=None)
    pt.add_argument("--metric", default="mean", choices=("mean", "total", "sharpe", "profit_factor"))
    pt.add_argument("--iters", type=int, default=500)
    pt.set_defaults(func=cmd_trades)

    ps = sub.add_parser("make-sample", help="write synthetic sample price CSV + trades DB")
    ps.add_argument("--symbol", default="MES")
    ps.set_defaults(func=cmd_make_sample)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
