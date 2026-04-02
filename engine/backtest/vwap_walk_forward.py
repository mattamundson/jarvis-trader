"""
JARVIS TRADER — VWAP Reversion Walk-Forward Validator
======================================================
Walk-forward efficiency (WFE) for the VWAP Deviation Reversion strategy on MES 1h.

Parameter grid:
  - band_mult:            1.0, 1.5, 2.0, 2.5
  - stop_mult:            0.25, 0.50, 0.75
  - require_reversal_bar: True, False

Scoring: composite of profit_factor × win_rate × sign(net_pnl)

Usage:
  python -m backtest.vwap_walk_forward --symbol MES --start 2024-01-01 --end 2026-03-27
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("vwap_walk_forward")

PARAM_GRID = list(product(
    [1.5, 2.0, 2.5],               # band_mult (dropped 1.0 — too noisy)
    [0.25, 0.50, 0.75],            # stop_mult
    [True, False],                 # require_reversal_bar
    [True, False],                 # regime_filter (skip entries in TRENDING regime)
))

WFE_EXCELLENT = 0.70
WFE_GOOD = 0.50
WFE_MARGINAL = 0.30


def _load_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    from backtest.data_loader import BacktestDataLoader
    loader = BacktestDataLoader()
    df = loader.load(symbol=symbol, start=start, end=end, interval="1h")
    if df is None or df.empty:
        raise ValueError(f"No data for {symbol} {start}–{end}")
    logger.info(f"Loaded {len(df)} 1h bars for {symbol}")
    return df


def _score(result) -> float:
    s = result.summary()
    n = s.get("total_trades", 0)
    if n < 5:
        return -999.0
    pf = min(s.get("profit_factor", 0.0), 5.0)
    wr = s.get("win_rate", 0.0)
    net = s.get("net_pnl", 0.0)
    sign = 1.0 if net > 0 else -0.5
    return round(0.40 * pf + 0.30 * wr + 0.30 * sign, 6)


def _optimise(train_df: pd.DataFrame, symbol: str) -> Tuple[Optional[Dict], Optional[float]]:
    from backtest.vwap_backtester import run_vwap_backtest

    best_score = -float("inf")
    best_params: Optional[Dict] = None

    for band_mult, stop_mult, reversal, regime_filter in PARAM_GRID:
        try:
            r = run_vwap_backtest(
                train_df.copy(), symbol=symbol,
                band_mult=band_mult, stop_mult=stop_mult,
                require_reversal_bar=reversal,
                regime_filter=regime_filter,
            )
            sc = _score(r)
            if sc > best_score:
                best_score = sc
                best_params = {
                    "band_mult": band_mult,
                    "stop_mult": stop_mult,
                    "require_reversal_bar": reversal,
                    "regime_filter": regime_filter,
                }
        except Exception as e:
            logger.debug(f"  Param combo failed: {e}")

    if best_params is None or best_score <= -999.0:
        return None, None
    return best_params, best_score


def run_vwap_walk_forward(
    symbol: str = "MES",
    start: str = "2024-01-01",
    end: str = "2026-03-27",
    train_months: int = 6,
    test_months: int = 3,
) -> Dict[str, Any]:
    from backtest.vwap_backtester import run_vwap_backtest

    logger.info("=" * 64)
    logger.info(f"=== VWAP WALK-FORWARD: {symbol} ===")
    logger.info(f"Train: {train_months}mo | Test: {test_months}mo | Grid: {len(PARAM_GRID)} combos")
    logger.info("=" * 64)

    df = _load_data(symbol, start, end)
    idx = pd.to_datetime(df.index)
    end_dt = idx.max()

    windows: List[Dict] = []
    is_returns: List[float] = []
    oos_returns: List[float] = []
    oos_pfs: List[float] = []
    oos_wrs: List[float] = []

    window_num = 0
    window_start = idx.min()

    while True:
        train_end = window_start + pd.DateOffset(months=train_months)
        test_end = train_end + pd.DateOffset(months=test_months)
        if test_end > end_dt + pd.DateOffset(days=7):
            break

        train_end = min(train_end, end_dt)
        test_end = min(test_end, end_dt)

        train_df = df[(idx >= window_start) & (idx < train_end)]
        test_df = df[(idx >= train_end) & (idx < test_end)]

        window_num += 1
        logger.info(
            f"\nWindow {window_num}: "
            f"Train {window_start.date()} → {train_end.date()} | "
            f"Test {train_end.date()} → {test_end.date()}"
        )
        logger.info(f"  Bars: train={len(train_df)}, test={len(test_df)}")

        if len(train_df) < 200 or len(test_df) < 50:
            logger.warning("  [SKIP] Insufficient data")
            window_start += pd.DateOffset(months=test_months)
            continue

        best_params, best_score = _optimise(train_df, symbol)
        if best_params is None:
            logger.warning("  [SKIP] No valid parameter combination")
            window_start += pd.DateOffset(months=test_months)
            continue

        logger.info(f"  Best params: {best_params} (score={best_score:.4f})")

        is_result = run_vwap_backtest(train_df.copy(), symbol=symbol, **best_params)  # type: ignore[arg-type]
        is_s = is_result.summary()

        oos_result = run_vwap_backtest(test_df.copy(), symbol=symbol, **best_params)  # type: ignore[arg-type]
        oos_s = oos_result.summary()

        logger.info(
            f"  IS:  {is_s['total_trades']} trades, PnL=${is_s['net_pnl']:+.2f}, "
            f"WR={is_s['win_rate']:.1%}, PF={is_s['profit_factor']:.2f}"
        )
        logger.info(
            f"  OOS: {oos_s['total_trades']} trades, PnL=${oos_s['net_pnl']:+.2f}, "
            f"WR={oos_s['win_rate']:.1%}, PF={oos_s['profit_factor']:.2f}"
        )

        is_returns.append(is_s["net_pnl"])
        oos_returns.append(oos_s["net_pnl"])
        oos_pfs.append(oos_s["profit_factor"])
        oos_wrs.append(oos_s["win_rate"])

        windows.append({
            "window": window_num,
            "train_start": str(window_start.date()),
            "train_end": str(train_end.date()),
            "test_start": str(train_end.date()),
            "test_end": str(test_end.date()),
            "best_params": best_params,
            "is_score": best_score,
            "is_trades": is_s["total_trades"],
            "is_pnl": round(is_s["net_pnl"], 2),
            "is_win_rate": is_s["win_rate"],
            "oos_trades": oos_s["total_trades"],
            "oos_pnl": round(oos_s["net_pnl"], 2),
            "oos_win_rate": oos_s["win_rate"],
            "oos_profit_factor": round(oos_s["profit_factor"], 3),
            "oos_sharpe": oos_s["sharpe"],
        })
        window_start += pd.DateOffset(months=test_months)

    if not windows:
        logger.warning("No valid windows.")
        wfe = 0.0
        avg_is = avg_oos = avg_pf = avg_wr = 0.0
    else:
        avg_is = float(pd.Series(is_returns).mean())
        avg_oos = float(pd.Series(oos_returns).mean())
        avg_pf = float(pd.Series(oos_pfs).mean())
        avg_wr = float(pd.Series(oos_wrs).mean())
        if avg_is > 0:
            wfe = round(avg_oos / avg_is, 4)
        else:
            logger.warning(f"avg IS PnL={avg_is:.2f} < 0 — WFE forced to 0.0")
            wfe = 0.0

    profitable = sum(1 for r in oos_returns if r > 0)

    logger.info("\n" + "=" * 64)
    logger.info("=== VWAP WALK-FORWARD SUMMARY ===")
    logger.info(f"Symbol: {symbol} | Windows: {len(windows)}")
    logger.info(f"Avg IS PnL:  ${avg_is:+.2f}")
    logger.info(f"Avg OOS PnL: ${avg_oos:+.2f}")
    logger.info(f"WFE:         {wfe:.4f}")
    logger.info(f"Avg OOS PF:  {avg_pf:.2f}")
    logger.info(f"Avg OOS WR:  {avg_wr:.1%}")
    logger.info(f"Profitable:  {profitable}/{len(windows)}")

    if wfe >= WFE_EXCELLENT:
        verdict = "APPROVED_EXCELLENT"
        rec = f"WFE={wfe:.2f} — Add MES VWAP to paper_config.py."
    elif wfe >= WFE_GOOD:
        verdict = "APPROVED_GOOD"
        rec = f"WFE={wfe:.2f} — Add MES VWAP with tight kill thresholds."
    elif wfe >= WFE_MARGINAL:
        verdict = "MARGINAL"
        rec = f"WFE={wfe:.2f} — Extend history and retest before paper."
    else:
        verdict = "REJECTED"
        rec = f"WFE={wfe:.2f} — VWAP reversion not approved for MES paper trading."

    logger.info(f"Verdict: {verdict}")
    logger.info(f"Rec:     {rec}")
    logger.info("=" * 64)

    return {
        "symbol": symbol, "strategy": "VWAP_REVERSION", "interval": "1h",
        "generated": datetime.now().isoformat(),
        "config": {"start": start, "end": end,
                   "train_months": train_months, "test_months": test_months,
                   "grid_size": len(PARAM_GRID)},
        "summary": {
            "total_windows": len(windows),
            "windows_profitable": profitable,
            "avg_is_pnl": round(avg_is, 2),
            "avg_oos_pnl": round(avg_oos, 2),
            "wfe": wfe,
            "avg_oos_profit_factor": round(avg_pf, 3),
            "avg_oos_win_rate": round(avg_wr, 4),
        },
        "verdict": verdict,
        "recommendation": rec,
        "windows": windows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VWAP Reversion Walk-Forward")
    parser.add_argument("--symbol", default="MES")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-03-27")
    parser.add_argument("--train-months", type=int, default=6)
    parser.add_argument("--test-months", type=int, default=3)
    args = parser.parse_args()

    results = run_vwap_walk_forward(
        symbol=args.symbol, start=args.start, end=args.end,
        train_months=args.train_months, test_months=args.test_months,
    )

    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"WF_{args.symbol}_1h_VWAP_walk_forward.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"\nResults saved to: {out_file}")

    verdict = results["verdict"]
    wfe = results["summary"]["wfe"]
    marker = "✅" if verdict.startswith("APPROVED") else "❌"
    print(f"\n{'='*60}")
    print(f"  {marker} MES VWAP {verdict}: WFE={wfe:.3f}")
    print(f"  {results['recommendation']}")
    print(f"{'='*60}\n")
    sys.exit(0 if verdict != "REJECTED" else 1)


if __name__ == "__main__":
    main()
