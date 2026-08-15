#!/usr/bin/env python
"""
Strategy-enhancement overlay candidates -- before/after backtest harness.

Measures the marginal effect of each overlay in strategy_overlays.py against
the unmodified live-strategy baseline (trend_signals.generate_sma_trend_signals,
champion params from SMA_TREND_PARAMS), on the SAME MES 1h cache used to
validate the live strategy (widest available window, picked the same way
run_mes_trend_rank11.py picks it -- _find_latest_cache).

Variants:
  baseline              -- unmodified champion SMA(50,200)+2.0xATR (Backtester)
  regime_filter_200d    -- baseline + apply_regime_filter(window=200) (Backtester)
  atr_trim_3x_50pct     -- baseline entries/exits, + trim 50% of position when
                            price extends >= 3.0xATR beyond SMA50 (standalone sim)
  atr_trim_2.5x_33pct   -- same mechanic, tighter trigger / smaller trim size
  regime_filter_100d    -- apply_regime_filter(window=100), a shorter macro
                            lookback for comparison against the 200-session default

BUILD-AND-BACKTEST ONLY -- does not modify trend_signals.py, SMA_TREND_PARAMS,
or any live signal-generation code. Writes a comparison JSON to
engine/backtest/results/ (per backtest-signals.md convention: always record
symbol, TF, period, trades, win_rate, PF, Sharpe, return, max_DD).

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_strategy_overlay_backtest.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest._gate_v2_helpers import _find_latest_cache  # noqa: E402
from backtest.backtester import Backtester  # noqa: E402
from backtest.strategy_overlays import (  # noqa: E402
    apply_regime_filter,
    rank_by_payout_ratio,
    simulate_atr_extension_trim,
)
from backtest.trade_manager import BacktestResult  # noqa: E402
from backtest.trend_signals import SMA_TREND_PARAMS, generate_sma_trend_signals  # noqa: E402

SYMBOL = "MES"
MULTIPLIER = 5.0  # $ per point, Micro E-mini S&P 500
TICK_SIZE = 0.25
CAPITAL = 50_000.0  # matches run_mes_trend_rank11.py (ALT-path account size)
COMMISSION = 0.62  # $/contract round-trip
SLIPPAGE_TICKS = 2.0


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    return df


def _run_baseline_backtest(df: pd.DataFrame, fast: int, slow: int, atr_trail_mult: float) -> BacktestResult:
    df_sig = generate_sma_trend_signals(df, fast=fast, slow=slow, atr_trail_mult=atr_trail_mult)
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
    return bt.run(df_sig, symbol=SYMBOL, multiplier=MULTIPLIER)


def _run_regime_filter_backtest(
    df: pd.DataFrame, fast: int, slow: int, atr_trail_mult: float, regime_window: int
) -> BacktestResult:
    df_sig = generate_sma_trend_signals(df, fast=fast, slow=slow, atr_trail_mult=atr_trail_mult)
    df_filtered = apply_regime_filter(df_sig, regime_window=regime_window)
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
    return bt.run(df_filtered, symbol=SYMBOL, multiplier=MULTIPLIER)


def _summary_row(name: str, result: BacktestResult) -> dict:
    return {
        "variant": name,
        "symbol": result.symbol,
        "period": f"{result.start_date} -> {result.end_date}",
        "trades": result.total_trades,
        "win_rate": round(result.win_rate, 4),
        "profit_factor": round(result.profit_factor, 3),
        "payoff_ratio": round(result.payoff_ratio, 3),
        "sharpe_ratio": round(result.sharpe_ratio, 3),
        "total_return_pct": round(result.total_return_pct, 4),
        "max_drawdown_pct": round(result.max_drawdown_pct, 4),
        "expectancy": round(result.expectancy, 2),
        "final_capital": round(result.final_capital, 2),
    }


def main() -> None:
    champion = SMA_TREND_PARAMS[SYMBOL]  # {"fast": 50, "slow": 200, "atr_trail_mult": 2.0}
    fast, slow, atr_trail_mult = champion["fast"], champion["slow"], champion["atr_trail_mult"]

    # Use the exact cache the champion (SMA_TREND_PARAMS["MES"]) was validated on in
    # run_mes_trend_rank11.py ("Data: MES 1h, 2024-01-01 to 2026-03-28 (widest available)")
    # rather than the latest cache -- the task is to compare each overlay against the
    # live strategy on the SAME period it was validated on, not to re-extend the window.
    # Sanity check (2026-07-10): baseline on this exact file reproduces PF=1.3506 for
    # fast=50, matching rank11's documented "fixed_params PF: fast=50->1.351" figure --
    # confirms this harness is faithful to the champion's own validation methodology.
    data_dir = engine_root / "backtest" / "cache"
    validated_window_file = data_dir / "MES_2024-01-01_2026-03-27_1h.csv"
    if validated_window_file.exists():
        data_file = validated_window_file
    else:
        data_file = _find_latest_cache(data_dir, SYMBOL)
        print(f"[overlay-bt] WARNING: validated-window cache not found, falling back to latest: {data_file.name}")
    print(f"[overlay-bt] {SYMBOL} champion params: {champion}")
    print(f"[overlay-bt] Selected cache: {data_file.name}")

    df = _load_data(data_file)
    print(f"[overlay-bt] {len(df)} bars | {df.index.min()} -> {df.index.max()}")
    print(f"{'=' * 78}")

    variants: dict[str, BacktestResult] = {}

    print("\n[1/5] baseline (unmodified live strategy)...")
    variants["baseline"] = _run_baseline_backtest(df, fast, slow, atr_trail_mult)

    print("[2/5] regime_filter_200d (200-session macro SMA confirmation)...")
    variants["regime_filter_200d"] = _run_regime_filter_backtest(df, fast, slow, atr_trail_mult, 200)

    print("[3/5] regime_filter_100d (100-session macro SMA confirmation)...")
    variants["regime_filter_100d"] = _run_regime_filter_backtest(df, fast, slow, atr_trail_mult, 100)

    print("[4/5] atr_trim_3x_50pct (trim 50% at +3.0xATR beyond SMA50)...")
    variants["atr_trim_3x_50pct"] = simulate_atr_extension_trim(
        df,
        symbol=SYMBOL,
        multiplier=MULTIPLIER,
        fast=fast,
        slow=slow,
        atr_trail_mult=atr_trail_mult,
        trim_atr_mult=3.0,
        trim_pct=0.5,
        initial_capital=CAPITAL,
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
        tick_size=TICK_SIZE,
    )

    print("[5/5] atr_trim_2.5x_33pct (trim 33% at +2.5xATR beyond SMA50)...")
    variants["atr_trim_2.5x_33pct"] = simulate_atr_extension_trim(
        df,
        symbol=SYMBOL,
        multiplier=MULTIPLIER,
        fast=fast,
        slow=slow,
        atr_trail_mult=atr_trail_mult,
        trim_atr_mult=2.5,
        trim_pct=0.33,
        initial_capital=CAPITAL,
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
        tick_size=TICK_SIZE,
    )

    print(f"\n{'=' * 78}")
    print("=== BEFORE / AFTER: win-rate ranking ===")
    header = f"{'variant':<22}{'trades':>7}{'win%':>8}{'PF':>8}{'payoff':>8}{'sharpe':>8}{'return%':>9}{'maxDD%':>8}"
    print(header)
    rows = [_summary_row(name, result) for name, result in variants.items()]
    for r in sorted(rows, key=lambda r: r["win_rate"], reverse=True):
        print(
            f"{r['variant']:<22}{r['trades']:>7}{r['win_rate'] * 100:>7.1f}%"
            f"{r['profit_factor']:>8.2f}{r['payoff_ratio']:>8.2f}{r['sharpe_ratio']:>8.2f}"
            f"{r['total_return_pct'] * 100:>8.1f}%{r['max_drawdown_pct'] * 100:>7.1f}%"
        )

    print(f"\n{'=' * 78}")
    print("=== PAYOUT-RATIO RANKING (rank_by_payout_ratio) ===")
    ranked = rank_by_payout_ratio(variants)
    print(f"{'variant':<22}{'payout_rk':>10}{'win_rk':>8}{'delta':>7}{'payoff':>8}{'win%':>8}{'PF':>8}")
    for r in ranked:
        print(
            f"{r['variant']:<22}{r['payout_rank']:>10}{r['win_rate_rank']:>8}{r['rank_delta']:>+7}"
            f"{r['payoff_ratio']:>8.2f}{r['win_rate'] * 100:>7.1f}%{r['profit_factor']:>8.2f}"
        )
    reversals = [r for r in ranked if r["rank_delta"] != 0]
    if reversals:
        print("\n  Rank reversals (win-rate-only ranking would have ordered these differently):")
        for r in reversals:
            direction = "PROMOTED" if r["rank_delta"] > 0 else "DEMOTED"
            print(
                f"    {r['variant']}: win_rate_rank={r['win_rate_rank']} -> "
                f"payout_rank={r['payout_rank']}  ({direction} by payout-ratio ranking)"
            )
    else:
        print("\n  No rank reversals on this variant set -- win-rate and payout-ratio orderings agree.")

    print(f"{'=' * 78}")

    results_dir = engine_root / "backtest" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_file = results_dir / f"strategy_overlay_candidates_{SYMBOL}.json"
    out_doc = {
        "symbol": SYMBOL,
        "timeframe": "1h",
        "data_file": data_file.name,
        "period": f"{df.index.min().date()} -> {df.index.max().date()}",
        "champion_params": champion,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "variants": {name: result.to_dict() for name, result in variants.items()},
        "summary": rows,
        "payout_ratio_ranking": ranked,
    }
    out_file.write_text(json.dumps(out_doc, indent=2, default=str))
    print(f"\n[overlay-bt] Full results -> {out_file}")


if __name__ == "__main__":
    main()
