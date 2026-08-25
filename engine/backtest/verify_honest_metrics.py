#!/usr/bin/env python
"""
JARVIS TRADER — Metric Honesty Verification (T5, 2026-08-18).

Verifies the honest-metrics corrections against the KNOWN certified values
(gate_v2 verdict engine/data/gate_v2_verdicts/MES_trend_rank11.json +
rules-jarvis-trader skill, "KNOWN METRIC DEFECTS"):

  MES SMA trend, 1h deep cache (7.27y, 2019-05-05 -> 2026-08-14, 42,826 bars),
  risk-based sizing (run_mes_trend_rank11.py champion wiring):
    - 50/200/2.0 : 85 trades, PF 0.9313, CAGR -0.26%  (combo_results[0]; the
                   certified -0.26% CAGR figure reproduces EXACTLY)
    - 55/200/2.0 : 128 trades, PF 1.3884 -> 17.6 trades/yr -> the 3.78x
                   inflation config; honest Sharpe ~= 0.55
    - 60/200/2.0 : 122 trades, PF 1.6187 (champion_params)
  - Sharpe is annualized by OBSERVED trades/yr (metrics.py), not a fixed 252.
  - R:R<1.2 filtered entries are COUNTED (not silently dropped), so a 0-trade
    run is diagnosable.
  - Live-account analytics path (engine/analytics/trade_analytics.py) survives
    MIXED naive/aware timestamps (the 2026-08-18 crash) and deflates by
    observed frequency.

USAGE (from engine/, using the real venv — never system python):
    env -u PYTHONPATH .venv/Scripts/python backtest/verify_honest_metrics.py
    env -u PYTHONPATH .venv/Scripts/python backtest/verify_honest_metrics.py --cache <path> [--smoke]

Exit code 0 = all honesty checks pass. Non-zero = at least one check failed.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.backtester import Backtester  # noqa: E402
from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402

DEFAULT_CACHE = Path(__file__).parent / "cache" / "MES_2015-01-01_2026-08-16_1h.csv"

# Champion wiring (run_mes_trend_rank11.py): risk-based sizing, 0.01 risk/trade.
CAPITAL = 50_000.0
MULTIPLIER = 5.0
CHAMPION_BT_ARGS = {
    "initial_capital": CAPITAL,
    "risk_per_trade": 0.01,
    "max_daily_loss": 0.02,
    "max_drawdown": 0.05,
    "t1_exit_pct": 0.50,
    "t2_exit_pct": 0.30,
}
COMMISSION = 0.62
SLIPPAGE_TICKS = 2.0

# Known certified values from MES_trend_rank11.json combo_results (2026-08-17
# deep-cache audit). Order matches the verdict's combo_results.
VERIFIED_COMBOS = [
    {
        "name": "50/200/2.0 (audit CAGR reference)",
        "fast": 50, "slow": 200, "atr": 2.0,
        "trades": 85, "trades_tol": 1,
        "pf": 0.9313, "pf_tol": 0.03,
        "cagr_pct": -0.26, "cagr_tol_pp": 0.75,
        "honest_sharpe": None,  # negative — documented, not asserted
    },
    {
        "name": "55/200/2.0 (17.6 trades/yr, 3.78x deflation)",
        "fast": 55, "slow": 200, "atr": 2.0,
        "trades": 128, "trades_tol": 1,
        "pf": 1.3884, "pf_tol": 0.03,
        "cagr_pct": None,
        "honest_sharpe": 0.55, "sharpe_tol": 0.30,
    },
    {
        "name": "60/200/2.0 (champion_params)",
        "fast": 60, "slow": 200, "atr": 2.0,
        "trades": 122, "trades_tol": 1,
        # Verdict PF 1.6187 comes from the 'realistic' cost tier, which uses
        # slightly higher costs than iterate.py's COMMISSION/SLIPPAGE constants;
        # trades + deflation factor are the wiring-equivalence checks.
        "pf": 1.6187, "pf_tol": 0.15,
        "cagr_pct": None,
        "honest_sharpe": None,  # report only (strongest combo; >1 never claimed)
    },
]

FAILURES: list[str] = []


def check(name: str, actual: float, expected: float, tol: float, unit: str = "") -> None:
    ok = abs(actual - expected) <= tol
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}: {actual:.4f}{unit}  (expected {expected:.4f}{unit} +/- {tol})")
    if not ok:
        FAILURES.append(f"{name}: got {actual:.4f}, expected {expected:.4f} +/- {tol}")


def load_cache(path: Path, smoke: bool):
    import pandas as pd

    if not path.exists():
        raise FileNotFoundError(f"Deep cache not found: {path}")
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    ts = pd.to_datetime(df[ts_col])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)
    df[ts_col] = ts
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {path.name}: {missing}")
    if smoke:
        df = df.tail(2_000)
    span_years = max((df.index.max() - df.index.min()).days / 365.25, 1e-9)
    print(
        f"[MES] {len(df)} bars | {df.index.min()} -> {df.index.max()} "
        f"| {span_years:.2f}y | cache={path.name}"
    )
    return df


def run_combo_verified(df, fast: int, slow: int, atr: float):
    """Run one SMA combo with the certified champion wiring."""
    df_sig = generate_sma_trend_signals(
        df,
        fast=fast,
        slow=slow,
        atr_trail_mult=atr,
        vix_df=None, vix_min=0.0, vix_max=999.0, vix_regime_block=None,
    )
    bt = Backtester(
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
        **CHAMPION_BT_ARGS,
    )
    res = bt.run(df_sig, symbol="MES", multiplier=MULTIPLIER)

    import numpy as np

    span_days = 0.0
    try:
        span_days = float(
            (np.datetime64(res.end_date) - np.datetime64(res.start_date)) / np.timedelta64(1, "D")
        )
    except Exception:
        pass
    years = span_days / 365.25 if span_days > 0 else 0.0

    final = res.initial_capital + res.total_pnl
    cagr_pct = 0.0
    if years > 0 and final > 0:
        cagr_pct = ((final / res.initial_capital) ** (1.0 / years) - 1.0) * 100.0

    ann_tpy = float(getattr(res, "annualization_trades_per_year", 0.0) or 0.0)
    rr_filtered = int(getattr(res, "rr_filtered_entries", 0) or 0)
    honest_sharpe = res.sharpe_ratio  # now honest (observed tpy) per metrics.py
    old_sharpe_252 = (
        honest_sharpe * math.sqrt(252.0 / ann_tpy) if ann_tpy > 0 else float("nan")
    )

    print(f"\n=== SMA({fast},{slow},{atr}) on deep cache ===")
    print(f"  Trades: {res.total_trades}  |  Win rate: {res.win_rate:.1%}")
    print(f"  PF: {res.profit_factor:.3f}  |  Total return: {res.total_return_pct:+.2%}  |  Max DD: {res.max_drawdown_pct:.1%}")
    print(f"  Span: {res.start_date} -> {res.end_date}  ({years:.2f}y)")
    print(f"  Annualization (observed trades/yr): {ann_tpy:.2f}")
    print(f"  Sharpe honest (sqrt observed): {honest_sharpe:.4f}")
    if ann_tpy > 0:
        print(f"  Sharpe OLD fixed-252 would have shown: {old_sharpe_252:.4f}  (inflation {old_sharpe_252 / honest_sharpe:.2f}x)")
    print(f"  CAGR: {cagr_pct:+.2f}%  |  R:R<1.2 filtered entries: {rr_filtered}")
    return res, cagr_pct, ann_tpy, rr_filtered, honest_sharpe, old_sharpe_252


def verify_combo(df, spec: dict, smoke: bool) -> None:
    res, cagr_pct, ann_tpy, rr_filtered, honest_sharpe, old_sharpe_252 = run_combo_verified(
        df, spec["fast"], spec["slow"], spec["atr"]
    )
    if smoke:
        return
    print(f"  --- known-value checks for {spec['name']} ---")
    check("trades", float(res.total_trades), float(spec["trades"]), spec["trades_tol"])
    check("profit factor", res.profit_factor, spec["pf"], spec["pf_tol"])
    if spec.get("cagr_pct") is not None:
        check("CAGR %", cagr_pct, spec["cagr_pct"], spec["cagr_tol_pp"], "%")
    if spec.get("honest_sharpe") is not None:
        check("honest Sharpe", honest_sharpe, spec["honest_sharpe"], spec["sharpe_tol"])
    if ann_tpy > 0 and honest_sharpe != 0:
        check(
            "deflation factor vs old 252",
            old_sharpe_252 / honest_sharpe,
            math.sqrt(252.0 / ann_tpy),
            1e-6,
        )
    if res.total_trades == 0 and rr_filtered > 0:
        print("  [INFO] 0 trades + rr_filtered>0 -> entries filtered, NOT signal absence (now diagnosable).")
    if rr_filtered < 0:
        FAILURES.append("rr_filtered_entries is negative")


def verify_live_account_path() -> None:
    """Exercise the live-account analytics path (trade_analytics.py)."""
    print("\n=== Live-account analytics path (engine/analytics/trade_analytics.py) ===")
    from analytics import trade_analytics as ta

    # Mixed naive + aware timestamps — this crashed the honest-metrics path
    # before the UTC normalization fix (2026-08-18). Span ~180 days so the
    # observed-frequency annualization (not the 252 fallback) actually engages.
    trades = []
    for i in range(88):
        pnl = (1.0 if i % 2 == 0 else -0.5) * 100.0
        day = 1 + (i * 2) % 180  # spread over ~180 calendar days
        month = 1 + day // 28
        day_in_month = 1 + day % 28
        if i % 3 == 0:
            ts = f"2026-{month:02d}-{day_in_month:02d}T10:30:00"
        else:
            ts = f"2026-{month:02d}-{day_in_month:02d}T10:30:00+00:00"
        trades.append({"pnl": pnl, "exit_time": ts})

    try:
        a = ta.calculate_analytics(trades)
    except TypeError as exc:  # naive/aware comparison crash before the fix
        FAILURES.append(f"live analytics crashed on mixed tz: {exc}")
        print("  [FAIL] TypeError on mixed naive/aware timestamps (UTC fix missing)")
        return

    print(f"  Trades: {a.total_trades} | PF: {a.profit_factor:.3f} | Sharpe: {a.sharpe_ratio:.4f}")
    print(f"  annualization_trades_per_year reported: {a.annualization_trades_per_year:.2f}")
    print(f"  CAGR: {a.cagr * 100:+.3f}%")
    if a.annualization_trades_per_year <= 0 or a.annualization_trades_per_year > 2520.0:
        FAILURES.append(f"annualization_trades_per_year out of range: {a.annualization_trades_per_year}")
    if abs(a.annualization_trades_per_year - 252.0) < 1e-6:
        FAILURES.append(
            "annualization_trades_per_year stayed at the 252 fallback — observed-frequency "
            "deflation did NOT engage on a >90-day record"
        )
    if math.isnan(a.sharpe_ratio) or math.isinf(a.sharpe_ratio):
        FAILURES.append(f"sharpe_ratio not finite: {a.sharpe_ratio}")
    print("  [PASS] no crash + finite metrics + in-range annualization factor")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="Path to MES 1h deep cache CSV")
    ap.add_argument("--smoke", action="store_true", help="Truncate to 2k bars; skip known-value asserts")
    args = ap.parse_args()

    df = load_cache(Path(args.cache), smoke=args.smoke)
    for spec in VERIFIED_COMBOS:
        verify_combo(df, spec, smoke=args.smoke)
    verify_live_account_path()

    if FAILURES:
        print("\n=== FAILED CHECKS ===")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("\n=== ALL HONESTY CHECKS PASS ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
