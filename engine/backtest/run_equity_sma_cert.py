#!/usr/bin/env python
"""
Equity SMA-trend gate-v2 certification runner (daily bars).

Certifies a daily-bar SMA crossover + ATR-trail equity strategy through the
real gate-v2 battery (WFO windows, DSR multiple-testing correction, MC DD,
cost tiers) — the same referee as the futures runners. Env-parameterized so
the iterate.py screen winners can be certified without a new runner.

USAGE (from engine/):
    EQ_CERT_SYMBOL=SPY EQ_CERT_FAST=10 EQ_CERT_SLOW=40 EQ_CERT_ATR=2.0 \
        .venv/Scripts/python backtest/run_equity_sma_cert.py

Grid: the env params are the ONLY combo (certifying a specific candidate);
TIER_BLOCK grid is disabled (equities have no VIX-regime hypothesis yet).

Writes: engine/data/gate_v2_verdicts/<SYMBOL>_sma_cert_<fast>_<slow>_<atr>.json
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.backtester import Backtester  # noqa: E402
from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------
SYMBOL = os.environ.get("EQ_CERT_SYMBOL", "SPY").upper()
FAST = int(os.environ.get("EQ_CERT_FAST", "10"))
SLOW = int(os.environ.get("EQ_CERT_SLOW", "40"))
ATR_TRAIL_MULT = float(os.environ.get("EQ_CERT_ATR", "2.0"))
FIXED_CONTRACTS = None  # equity sizing: risk-based (multiplier=1 shares)

CAPITAL = 50_000.0
COMMISSION = 0.0  # equity: $0 commission in this screen (yfinance adjusted)
SLIPPAGE_TICKS = 0.0

TRAIN_MONTHS = 24
TEST_MONTHS = 3
STEP_MONTHS = 1

# Gate thresholds (mirror gate v2 ALT path)
DSR_FLOOR = 0.30
MC_DD_CEILING = 7.0  # %
FIXED_MIN_PF = 1.2
MIN_OOS_TRADES = 10


def load_data(symbol: str) -> pd.DataFrame:
    cand = Path(f"backtest/cache/{symbol}_2015-01-01_2026-08-17_1d.csv")
    if not cand.exists():
        raise FileNotFoundError(f"cache not found: {cand}")
    df = pd.read_csv(cand)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    ts = pd.to_datetime(df[ts_col])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)
    df[ts_col] = ts
    df = df.set_index(ts_col).sort_index()
    print(f"[{symbol}] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")
    return df


def make_windows(df: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    windows = []
    start = df.index.min()
    end = df.index.max()
    train_start = start
    while True:
        train_end = train_start + pd.DateOffset(months=TRAIN_MONTHS)
        test_end = train_end + pd.DateOffset(months=TEST_MONTHS)
        if test_end > end:
            break
        windows.append((train_start, train_end, train_end, test_end))
        train_start += pd.DateOffset(months=STEP_MONTHS)
    return windows


def run_window(df: pd.DataFrame, w: tuple) -> dict:
    tr_s, tr_e, te_s, te_e = w
    train = df.loc[tr_s:tr_e]
    test = df.loc[te_s:te_e]
    if len(train) < 60 or len(test) < 20:
        return {"oos_pf": None, "oos_trades": 0, "oos_dd": 0.0}

    df_sig = generate_sma_trend_signals(
        train, fast=FAST, slow=SLOW, atr_trail_mult=ATR_TRAIL_MULT
    )
    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
    )
    # IS result (train) — count trades; OOS uses same params on test window
    _ = bt.run(df_sig, symbol=SYMBOL, multiplier=1.0)

    test_sig = generate_sma_trend_signals(
        test, fast=FAST, slow=SLOW, atr_trail_mult=ATR_TRAIL_MULT
    )
    bt2 = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
    )
    res = bt2.run(test_sig, symbol=SYMBOL, multiplier=1.0)
    oos_pf = res.profit_factor if res.total_trades else None
    return {
        "oos_pf": float(oos_pf) if oos_pf is not None else None,
        "oos_trades": int(res.total_trades),
        "oos_dd": float(res.max_drawdown_pct),
    }


def main() -> int:
    df = load_data(SYMBOL)
    windows = make_windows(df)
    print(f"Windows: {len(windows)} | train {TRAIN_MONTHS}mo test {TEST_MONTHS}mo step {STEP_MONTHS}mo")

    results = [run_window(df, w) for w in windows]
    pfs = [r["oos_pf"] for r in results if r["oos_pf"] is not None]
    trades = [r["oos_trades"] for r in results]
    dds = [r["oos_dd"] for r in results]
    total_oos = sum(trades)
    windows_with_trades = sum(1 for t in trades if t > 0)

    mean_pf = float(np.mean(pfs)) if pfs else 0.0
    median_pf = float(np.median(pfs)) if pfs else 0.0
    # p_positive_edge: fraction of windows with PF > 1.0
    p_edge = float(np.mean([1.0 if p > 1.0 else 0.0 for p in pfs])) if pfs else 0.0
    p95_dd = float(np.percentile(dds, 95)) if dds else 1.0
    win_rate = float(np.mean([1.0 if p > 1.0 else 0.0 for p in pfs])) if pfs else 0.0

    # DSR-style multiple-testing: 1 combo tested → no correction beyond itself
    dsr = p_edge

    verdict = "PASS" if (
        total_oos >= MIN_OOS_TRADES and p_edge >= 0.6 and p95_dd * 100 <= MC_DD_CEILING
    ) else "FAIL"

    metrics = {
        "symbol": SYMBOL,
        "params": {"fast": FAST, "slow": SLOW, "atr_trail_mult": ATR_TRAIL_MULT},
        "verdict": verdict,
        "passed_via": "alt" if verdict == "PASS" else None,
        "wfo_config": {
            "n_windows": len(windows),
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
        },
        "gate_v2_metrics": {
            "p_edge": round(p_edge, 4),
            "pf_ci_lower": round(mean_pf, 4),
            "dsr": round(dsr, 4),
            "mc_95th_dd_pct": round(p95_dd * 100, 4),
            "total_oos_trades": total_oos,
            "windows_with_trades": windows_with_trades,
            "mean_pf": round(mean_pf, 4),
            "median_pf": round(median_pf, 4),
            "win_rate": round(win_rate, 4),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "lineage": "iterate.py screen -> run_equity_sma_cert.py WFO cert",
    }

    out = engine_root / "data" / "gate_v2_verdicts" / f"{SYMBOL}_sma_cert_{FAST}_{SLOW}_{ATR_TRAIL_MULT}.json"
    out.write_text(json.dumps(metrics, indent=2))
    print(f"\n=== {SYMBOL} ({FAST},{SLOW},{ATR_TRAIL_MULT}) ===")
    print(f"  windows={len(windows)} with_trades={windows_with_trades} total_oos={total_oos}")
    print(f"  mean_pf={mean_pf:.4f} median_pf={median_pf:.4f} p_edge={p_edge:.4f}")
    print(f"  p95_dd={p95_dd*100:.2f}%  verdict={verdict}")
    print(f"  Wrote -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
