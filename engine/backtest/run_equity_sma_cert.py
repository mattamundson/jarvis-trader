#!/usr/bin/env python
"""
SMA-trend gate-v2 certification runner (env-parameterized).

Certifies an SMA crossover + ATR-trail strategy through the real gate-v2
battery (WFO windows, p_edge, MC DD, cost tiers) — the same referee as the
futures runners. Env-parameterized so the iterate.py screen winners can be
certified without a new runner (S4A pipeline: scripts/screen_and_certify.sh).

USAGE (from engine/):
    # Equity (defaults: multiplier 1.0, $0 commission, no slippage):
    EQ_CERT_SYMBOL=SPY EQ_CERT_FAST=10 EQ_CERT_SLOW=40 EQ_CERT_ATR=2.0 \\
        .venv/Scripts/python backtest/run_equity_sma_cert.py
    # Futures class (contract-aware costs via CERT_* env):
    CERT_SYMBOL=MES CERT_FAST=50 CERT_SLOW=200 CERT_ATR=2.0 \\
        CERT_MULT=5.0 CERT_COMMISSION=0.62 CERT_SLIPPAGE_TICKS=2.0 \\
        CERT_CACHE=backtest/cache/MES_2015-01-01_2026-08-16_1h.csv \\
        .venv/Scripts/python backtest/run_equity_sma_cert.py
    # Wiring smoke (last 30 months, max 3 windows):
    EQ_CERT_SYMBOL=SPY CERT_SMOKE=1 .venv/Scripts/python backtest/run_equity_sma_cert.py

Grid: the env params are the ONLY combo (certifying a specific candidate);
TIER_BLOCK grid is disabled (equities have no VIX-regime hypothesis yet).

Env keys (EQ_CERT_* legacy aliases still work):
  CERT_SYMBOL | EQ_CERT_SYMBOL   symbol (default SPY)
  CERT_FAST   | EQ_CERT_FAST     fast SMA (default 10)
  CERT_SLOW   | EQ_CERT_SLOW     slow SMA (default 40)
  CERT_ATR    | EQ_CERT_ATR      ATR trail multiplier (default 2.0)
  CERT_MULT                       contract/share multiplier (default 1.0)
  CERT_COMMISSION                 per-contract commission (default 0.0)
  CERT_SLIPPAGE_TICKS             slippage in ticks (default 0.0)
  CERT_CACHE                      cache CSV path override (default:
                                  backtest/cache/<SYM>_2015-01-01_2026-08-17_1d.csv)
  CERT_SMOKE                      "1" = last-30-month slice, max 3 windows
  GATE_V2_VERDICTS_DIR            verdict + journal output dir (default:
                                  engine/data/gate_v2_verdicts/)

Writes: <GATE_V2_VERDICTS_DIR>/<SYMBOL>_sma_cert_<fast>_<slow>_<atr>.json
and appends one row to <GATE_V2_VERDICTS_DIR>/_journal.csv.
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
from backtest.screen_cert_pipeline import append_journal  # noqa: E402
from backtest.screen_cert_pipeline import append_journal, cap_pf  # noqa: E402
from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402

# ---------------------------------------------------------------------------
# Config from env (EQ_CERT_* aliases preserved for backward compatibility)
# ---------------------------------------------------------------------------
SYMBOL = (os.environ.get("CERT_SYMBOL") or os.environ.get("EQ_CERT_SYMBOL", "SPY")).upper()
FAST = int(os.environ.get("CERT_FAST") or os.environ.get("EQ_CERT_FAST", "10"))
SLOW = int(os.environ.get("CERT_SLOW") or os.environ.get("EQ_CERT_SLOW", "40"))
ATR_TRAIL_MULT = float(os.environ.get("CERT_ATR") or os.environ.get("EQ_CERT_ATR", "2.0"))
MULTIPLIER = float(os.environ.get("CERT_MULT", "1.0"))
COMMISSION = float(os.environ.get("CERT_COMMISSION", "0.0"))
SLIPPAGE_TICKS = float(os.environ.get("CERT_SLIPPAGE_TICKS", "0.0"))
CACHE_OVERRIDE = os.environ.get("CERT_CACHE")
SMOKE = os.environ.get("CERT_SMOKE", "0") == "1"
VERDICTS_DIR = Path(
    os.environ.get("GATE_V2_VERDICTS_DIR")
    or (engine_root / "data" / "gate_v2_verdicts")
)
FIXED_CONTRACTS = None  # sizing: risk-based (multiplier = shares/contracts)

CAPITAL = 50_000.0

TRAIN_MONTHS = 24
TEST_MONTHS = 3
STEP_MONTHS = 1

# Gate thresholds (mirror gate v2 ALT path)
DSR_FLOOR = 0.30
MC_DD_CEILING = 7.0  # %
FIXED_MIN_PF = 1.2
MIN_OOS_TRADES = 10


def load_data(symbol: str) -> pd.DataFrame:
    if CACHE_OVERRIDE:
        cand = Path(CACHE_OVERRIDE)
    else:
        cand = Path(f"backtest/cache/{symbol}_2015-01-01_2026-08-17_1d.csv")
    if not cand.exists():
        raise FileNotFoundError(f"cache not found: {cand}")
    df = pd.read_csv(cand)    # Cache provenance (2026-09-17 audit: 0/76 verdicts recorded which cache they ran on).
    from backtest._gate_v2_helpers import cache_provenance as _cp  # noqa: E402
    df.attrs["cache_provenance"] = _cp(cand)

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
    _ = bt.run(df_sig, symbol=SYMBOL, multiplier=MULTIPLIER)

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
    res = bt2.run(test_sig, symbol=SYMBOL, multiplier=MULTIPLIER)
    oos_pf = res.profit_factor if res.total_trades else None
    return {
        "oos_pf": float(oos_pf) if oos_pf is not None else None,
        "oos_trades": int(res.total_trades),
        "oos_dd": float(res.max_drawdown_pct),
    }


def main() -> int:
    df = load_data(SYMBOL)
    if SMOKE:
        # Wiring proof: last 30 months of data, capped at 3 windows.
        start = df.index.max() - pd.DateOffset(months=30)
        df = df.loc[start:]
        print(f"[SMOKE] sliced to last 30 months -> {len(df)} bars")
    windows = make_windows(df)
    if SMOKE:
        windows = windows[:3]
    print(f"Windows: {len(windows)} | train {TRAIN_MONTHS}mo test {TEST_MONTHS}mo step {STEP_MONTHS}mo")

    results = [run_window(df, w) for w in windows]
    # Cap non-finite PFs (all-profitable windows yield +inf) so the verdict
    # JSON stays strict-JSON (no Infinity/NaN literals) and journal cells stay
    # clean. Cap matches bootstrap_pf_ci_lower's ceiling (PF_CAP=5.0).
    pfs = [cap_pf(r["oos_pf"]) for r in results if r["oos_pf"] is not None]
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
        "family": "trend",  # SMA-trend family: policy-compatible with sma_trend routing
        "rank": 0,  # param-specific cert, not a rank grid
        "params": {"fast": FAST, "slow": SLOW, "atr_trail_mult": ATR_TRAIL_MULT},
        "verdict": verdict,
        "passed_via": "alt" if verdict == "PASS" else None,
        "core_verdict": "FAIL",  # ALT-path cert: CORE battery not scored
        "alt_verdict": verdict,
        "n_core_passed": 0,
        "n_alt_passed": 1 if verdict == "PASS" else 0,
        "wfo_config": {
            "n_windows": len(windows),
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
        },
        "aux_freshness": {},
        "gate_v2": {},
        "gate_v2_metrics": {
            "oos_pfs": [round(float(p), 4) for p in pfs],
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

    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    out = VERDICTS_DIR / f"{SYMBOL}_sma_cert_{FAST}_{SLOW}_{ATR_TRAIL_MULT}.json"
    # Record the provenance carried on the frame (see loader).
    from backtest._gate_v2_helpers import inject_cache_provenance as _ip  # noqa: E402
    metrics = _ip(metrics, df=df)
    out.write_text(json.dumps(metrics, indent=2))
    # allow_nan=False: any missed NaN/Infinity raises instead of writing
    # invalid strict JSON that downstream consumers may reject.
    out.write_text(json.dumps(metrics, indent=2, allow_nan=False))
    journal = append_journal(VERDICTS_DIR, metrics, source_file=out.name)
    print(f"\n=== {SYMBOL} ({FAST},{SLOW},{ATR_TRAIL_MULT}) ===")
    print(f"  windows={len(windows)} with_trades={windows_with_trades} total_oos={total_oos}")
    print(f"  mean_pf={mean_pf:.4f} median_pf={median_pf:.4f} p_edge={p_edge:.4f}")
    print(f"  p95_dd={p95_dd*100:.2f}%  verdict={verdict}")
    print(f"  Wrote -> {out}")
    print(f"  Journal -> {journal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
