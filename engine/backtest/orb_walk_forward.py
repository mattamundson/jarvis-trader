"""
JARVIS TRADER — ORB Walk-Forward Validator
==========================================
Walk-forward efficiency (WFE) analysis for the ORB strategy.

Splits the historical dataset into rolling train/test windows and
optimises ORB parameters on the in-sample period, then evaluates on
the out-of-sample period.

Parameters optimised:
  - volume_filter:     True | False
  - regime_filter:     True | False
  - min_or_range_pct:  0.0005 | 0.0008 | 0.0012 | 0.0015

WFE = avg_oos_return / avg_is_return (> 0.50 = approved for paper trading)

Usage (from engine/ directory with PYTHONPATH="."):
    python -m backtest.orb_walk_forward \
        --symbol MES \
        --start 2024-01-01 \
        --end 2026-03-27

Output:
    engine/backtest/results/WF_MES_1h_ORB.json
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
logger = logging.getLogger("orb_walk_forward")

# ── Parameter Grid ────────────────────────────────────────────────────────────

PARAM_GRID = list(product(
    [True, False],              # volume_filter
    [False, True],              # regime_filter
    [0.0005, 0.0008, 0.0012],   # min_or_range_pct
))

# WFE decision thresholds (shared with STC framework)
WFE_EXCELLENT = 0.70
WFE_GOOD = 0.50
WFE_MARGINAL = 0.30


# ── Data Loading ──────────────────────────────────────────────────────────────

def _load_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Fetch 1h bars via the existing data_loader (uses cache)."""
    from backtest.data_loader import BacktestDataLoader

    loader = BacktestDataLoader()
    df = loader.load(symbol=symbol, start=start, end=end, interval="1h")

    if df is None or df.empty:
        raise ValueError(f"No data returned for {symbol} {start}–{end}")

    logger.info(f"Loaded {len(df)} 1h bars for {symbol} ({start} → {end})")
    return df


# ── Single Window Optimisation ────────────────────────────────────────────────

def _score_result(result) -> float:
    """
    Composite score for in-sample optimisation.

    Combines profit factor, win rate, and trade count penalty.
    Returns -999.0 for insufficient samples (< 5 trades).
    """
    s = result.summary()
    n = s.get("total_trades", 0)
    if n < 5:
        return -999.0

    pf = s.get("profit_factor", 0.0)
    wr = s.get("win_rate", 0.0)
    net = s.get("net_pnl", 0.0)

    if pf == float("inf"):
        pf = 5.0  # Cap for scoring

    # Weighted composite: 40% PF + 30% WR + 30% net PnL sign
    pnl_sign = 1.0 if net > 0 else -0.5
    score = (0.40 * min(pf, 5.0)) + (0.30 * wr) + (0.30 * pnl_sign)
    return round(score, 6)


def _optimise_window(
    train_df: pd.DataFrame,
    symbol: str,
) -> Tuple[Optional[Dict], Optional[float]]:
    """
    Grid-search over PARAM_GRID on train_df.

    Returns (best_params, best_score) or (None, None) if no valid config.
    """
    from backtest.orb_backtester import run_orb_backtest

    best_score = -float("inf")
    best_params: Optional[Dict] = None

    for volume_filter, regime_filter, min_or_pct in PARAM_GRID:
        try:
            result = run_orb_backtest(
                train_df.copy(),
                symbol=symbol,
                volume_filter=volume_filter,
                regime_filter=regime_filter,
                min_or_range_pct=min_or_pct,
            )
            score = _score_result(result)
            if score > best_score:
                best_score = score
                best_params = {
                    "volume_filter": volume_filter,
                    "regime_filter": regime_filter,
                    "min_or_range_pct": min_or_pct,
                }
        except Exception as e:
            logger.debug(f"  Param combo failed: {e}")
            continue

    if best_params is None or best_score <= -999.0:
        return None, None

    return best_params, best_score


# ── Walk-Forward Main ─────────────────────────────────────────────────────────

def run_orb_walk_forward(
    symbol: str = "MES",
    start: str = "2024-01-01",
    end: str = "2026-03-27",
    train_months: int = 6,
    test_months: int = 3,
) -> Dict[str, Any]:
    """
    Run rolling walk-forward validation for ORB strategy.

    Returns a results dict suitable for JSON serialisation.
    """
    from backtest.orb_backtester import run_orb_backtest

    logger.info("=" * 64)
    logger.info(f"=== ORB WALK-FORWARD: {symbol} ===")
    logger.info(f"Train: {train_months}mo | Test: {test_months}mo | Grid: {len(PARAM_GRID)} combos")
    logger.info("=" * 64)

    df = _load_data(symbol, start, end)

    # Build rolling windows
    idx = pd.to_datetime(df.index)
    start_dt = idx.min()
    end_dt = idx.max()

    windows: List[Dict] = []
    is_returns: List[float] = []
    oos_returns: List[float] = []
    oos_pfs: List[float] = []
    oos_win_rates: List[float] = []

    window_num = 0
    window_start = start_dt

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
            f"\nWindow {window_num}: Train {window_start.date()} → {train_end.date()} "
            f"| Test {train_end.date()} → {test_end.date()}"
        )
        logger.info(f"  Bars: train={len(train_df)}, test={len(test_df)}")

        if len(train_df) < 200 or len(test_df) < 50:
            logger.warning(f"  [SKIP] Insufficient data (train={len(train_df)}, test={len(test_df)})")
            window_start += pd.DateOffset(months=test_months)
            continue

        # Optimise on train
        best_params, best_score = _optimise_window(train_df, symbol)
        if best_params is None:
            logger.warning("  [SKIP] No valid parameter combination found")
            window_start += pd.DateOffset(months=test_months)
            continue

        logger.info(f"  Best params: {best_params} (score={best_score:.4f})")

        # IS backtest with best params
        is_result = run_orb_backtest(train_df.copy(), symbol=symbol, **best_params)
        is_summary = is_result.summary()
        is_pnl = is_summary["net_pnl"]
        is_n = is_summary["total_trades"]

        # OOS evaluation
        oos_result = run_orb_backtest(test_df.copy(), symbol=symbol, **best_params)
        oos_summary = oos_result.summary()
        oos_pnl = oos_summary["net_pnl"]
        oos_n = oos_summary["total_trades"]
        oos_pf = oos_summary["profit_factor"]
        oos_wr = oos_summary["win_rate"]

        logger.info(
            f"  IS:  {is_n} trades, PnL=${is_pnl:+.2f}, "
            f"WR={is_summary['win_rate']:.1%}, PF={is_summary['profit_factor']:.2f}"
        )
        logger.info(
            f"  OOS: {oos_n} trades, PnL=${oos_pnl:+.2f}, "
            f"WR={oos_wr:.1%}, PF={oos_pf:.2f}"
        )

        is_returns.append(is_pnl)
        oos_returns.append(oos_pnl)
        oos_pfs.append(oos_pf)
        oos_win_rates.append(oos_wr)

        windows.append({
            "window": window_num,
            "train_start": str(window_start.date()),
            "train_end": str(train_end.date()),
            "test_start": str(train_end.date()),
            "test_end": str(test_end.date()),
            "best_params": best_params,
            "is_score": best_score,
            "is_trades": is_n,
            "is_pnl": round(is_pnl, 2),
            "is_win_rate": is_summary["win_rate"],
            "oos_trades": oos_n,
            "oos_pnl": round(oos_pnl, 2),
            "oos_win_rate": oos_wr,
            "oos_profit_factor": round(oos_pf, 3),
            "oos_sharpe": oos_summary["sharpe"],
        })

        window_start += pd.DateOffset(months=test_months)

    # Compute WFE
    # IMPORTANT: WFE = avg_oos / avg_is is only meaningful when avg_is > 0.
    # If the IS period is already unprofitable (avg_is < 0), a positive WFE is
    # mathematically deceptive — it simply means OOS loses less than IS, not
    # that the strategy has edge. We force WFE = 0.0 in that case.
    if not windows:
        logger.warning("No valid windows — WFE cannot be computed.")
        wfe = 0.0
        avg_is = 0.0
        avg_oos = 0.0
        avg_pf = 0.0
        avg_wr = 0.0
    else:
        avg_is = float(pd.Series(is_returns).mean())
        avg_oos = float(pd.Series(oos_returns).mean())
        avg_pf = float(pd.Series(oos_pfs).mean())
        avg_wr = float(pd.Series(oos_win_rates).mean())
        if avg_is > 0:
            wfe = round(avg_oos / avg_is, 4)
        else:
            # IS itself is unprofitable — no edge to retain; WFE is undefined / 0
            logger.warning(
                f"avg IS PnL={avg_is:.2f} < 0 — IS is unprofitable. "
                f"WFE forced to 0.0 (would otherwise be deceptive: {avg_oos/avg_is:.3f})"
            )
            wfe = 0.0

    profitable_windows = sum(1 for r in oos_returns if r > 0)

    logger.info("\n" + "=" * 64)
    logger.info("=== ORB WALK-FORWARD SUMMARY ===")
    logger.info(f"Symbol: {symbol} | Windows: {len(windows)}")
    logger.info(f"Avg IS PnL:    ${avg_is:+.2f}")
    logger.info(f"Avg OOS PnL:   ${avg_oos:+.2f}")
    logger.info(f"WFE:           {wfe:.4f}")
    logger.info(f"Avg OOS PF:    {avg_pf:.2f}")
    logger.info(f"Avg OOS WR:    {avg_wr:.1%}")
    logger.info(f"Profitable:    {profitable_windows}/{len(windows)}")

    # Decision gate
    if wfe >= WFE_EXCELLENT:
        verdict = "APPROVED_EXCELLENT"
        rec = f"WFE={wfe:.2f} >= {WFE_EXCELLENT} — Add MES ORB to paper_config.py immediately."
    elif wfe >= WFE_GOOD:
        verdict = "APPROVED_GOOD"
        rec = f"WFE={wfe:.2f} >= {WFE_GOOD} — Add MES ORB with tight kill thresholds."
    elif wfe >= WFE_MARGINAL:
        verdict = "MARGINAL"
        rec = f"WFE={wfe:.2f} is marginal (0.30–0.50) — extend data range and retest before paper."
    else:
        verdict = "REJECTED"
        rec = f"WFE={wfe:.2f} < {WFE_MARGINAL} — ORB strategy not approved for MES paper trading."

    logger.info(f"Verdict:       {verdict}")
    logger.info(f"Recommendation: {rec}")
    logger.info("=" * 64)

    return {
        "symbol": symbol,
        "strategy": "ORB",
        "interval": "1h",
        "generated": datetime.now().isoformat(),
        "config": {
            "start": start,
            "end": end,
            "train_months": train_months,
            "test_months": test_months,
            "grid_size": len(PARAM_GRID),
        },
        "summary": {
            "total_windows": len(windows),
            "windows_profitable": profitable_windows,
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


# ── Entry Point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ORB Walk-Forward Validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backtest.orb_walk_forward --symbol MES
  python -m backtest.orb_walk_forward --symbol MES --start 2023-01-01 --end 2026-03-27
""",
    )
    parser.add_argument("--symbol", default="MES", help="Symbol (default: MES)")
    parser.add_argument("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-03-27", help="End date (YYYY-MM-DD)")
    parser.add_argument("--train-months", type=int, default=6, help="Training window in months")
    parser.add_argument("--test-months", type=int, default=3, help="Test window in months")
    args = parser.parse_args()

    results = run_orb_walk_forward(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        train_months=args.train_months,
        test_months=args.test_months,
    )

    # Save results
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"WF_{args.symbol}_1h_ORB_walk_forward.json"

    with open(out_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"\nResults saved to: {out_file}")

    verdict = results["verdict"]
    wfe = results["summary"]["wfe"]

    if verdict.startswith("APPROVED"):
        print(f"\n{'='*60}")
        print(f"  MES ORB APPROVED: WFE={wfe:.3f} ({verdict})")
        print("  Next step: add MES_ORB_PAPER_CONFIG to paper_config.py")
        print(f"{'='*60}\n")
        sys.exit(0)
    else:
        print(f"\n{'='*60}")
        print(f"  MES ORB {verdict}: WFE={wfe:.3f}")
        print(f"  {results['recommendation']}")
        print(f"{'='*60}\n")
        sys.exit(1 if verdict == "REJECTED" else 0)


if __name__ == "__main__":
    main()
