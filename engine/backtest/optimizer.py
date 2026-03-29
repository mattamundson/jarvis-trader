"""
JARVIS TRADER — Parameter Optimizer
Grid-searches STC thresholds, ATR multiples, and regime filters
against cached backtest data. No live data fetches required.

Usage:
    python -m backtest.optimizer --symbol SPY --start 2024-01-01 --end 2025-01-01
    python -m backtest.optimizer --symbol SPY --interval 1h --start 2024-06-01 --end 2026-03-27

Auto-saves top 5 results to:
    backtest/results/{SYMBOL}_{interval}_optimal_params.json
"""
from __future__ import annotations
import argparse
import itertools
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

from backtest.data_loader import BacktestDataLoader
from backtest.signals import (
    compute_all_indicators,
    layer1_regime,
    layer2_structure,
    layer3_bias,
    layer4_entry,
)
from backtest.backtester import Backtester, BacktestResult


# ── Parameter grid ────────────────────────────────────────────────────────────

PARAM_GRID = {
    "stc_oversold":    [15, 17, 19, 21, 23],          # default=19
    "stc_overbought":  [83, 85, 88, 90, 92],          # default=88
    "atr_stop_mult":   [0.3, 0.4, 0.5, 0.6, 0.7],    # default=0.5
    "atr_target_mult": [0.8, 1.0, 1.2, 1.5, 2.0],    # default=1.0
    "regime_filter":   [True, False],                  # default=True
}

# Reduced grid for fast runs (comment out to do full grid)
FAST_GRID = {
    "stc_oversold":    [15, 19, 23],
    "stc_overbought":  [83, 88, 92],
    "atr_stop_mult":   [0.3, 0.5, 0.7],
    "atr_target_mult": [1.0, 1.5, 2.0],
    "regime_filter":   [True, False],
}


@dataclass
class OptResult:
    stc_oversold: int
    stc_overbought: int
    atr_stop_mult: float
    atr_target_mult: float
    regime_filter: bool
    trades: int
    win_rate: float
    profit_factor: float
    sharpe: float
    total_return_pct: float
    max_dd_pct: float
    score: float  # composite ranking score


def _compute_signals(
    df: pd.DataFrame,
    stc_oversold: float,
    stc_overbought: float,
    atr_stop_mult: float,
    atr_target_mult: float,
    regime_filter: bool,
    adaptive_regime: bool = False,
    volume_filter: bool = False,
    mtf_filter: bool = False,
) -> pd.DataFrame:
    """Use real signal pipeline with parameterized thresholds."""
    df = compute_all_indicators(df.copy())

    # Re-apply STC signals with parameterized thresholds (overrides the
    # hardcoded STC_OS / STC_OB baked into compute_all_indicators)
    if adaptive_regime:
        from backtest.regime import RegimeClassifier
        df = RegimeClassifier().classify(df)
        adapt_os = df['adaptive_stc_os']
        adapt_ob = df['adaptive_stc_ob']
        stc_v = df['stc_val']
        stc_prev = stc_v.shift(1).fillna(50)
        stc_cross_up = (stc_v > adapt_os) & (stc_prev <= adapt_os)
        stc_cross_down = (stc_v < adapt_ob) & (stc_prev >= adapt_ob)
        stc_signal = pd.Series('neutral', index=df.index)
        stc_signal[stc_v < adapt_os] = 'oversold'
        stc_signal[stc_v > adapt_ob] = 'overbought'
        rising_mask = (stc_v > stc_prev) & (stc_signal == 'neutral')
        falling_mask = (stc_v < stc_prev) & (stc_signal == 'neutral')
        stc_signal[rising_mask] = 'rising'
        stc_signal[falling_mask] = 'falling'
    else:
        stc_cross_up = (df['stc_val'] > stc_oversold) & (df['stc_val'].shift(1).fillna(50) <= stc_oversold)
        stc_cross_down = (df['stc_val'] < stc_overbought) & (df['stc_val'].shift(1).fillna(50) >= stc_overbought)
        stc_signal = pd.Series('neutral', index=df.index)
        stc_signal[df['stc_val'] < stc_oversold] = 'oversold'
        stc_signal[df['stc_val'] > stc_overbought] = 'overbought'
        stc_prev = df['stc_val'].shift(1).fillna(50)
        rising_mask = (df['stc_val'] > stc_prev) & (stc_signal == 'neutral')
        falling_mask = (df['stc_val'] < stc_prev) & (stc_signal == 'neutral')
        stc_signal[rising_mask] = 'rising'
        stc_signal[falling_mask] = 'falling'

    df['stc_signal'] = stc_signal
    df['stc_cross_up'] = stc_cross_up
    df['stc_cross_down'] = stc_cross_down

    # Run all 4 layers using the real layer functions from signals.py
    regimes = []
    structure_positions = []
    biases = []
    entries = []

    for idx, row in df.iterrows():
        regime = layer1_regime(row)
        if not regime_filter and regime in ('EXHAUSTED', 'COMPRESSION'):
            regime = 'RANGE_BOUND'
        structure = layer2_structure(row)
        bias = layer3_bias(row)
        entry = layer4_entry(row, regime, bias, structure)
        regimes.append(regime)
        structure_positions.append(structure['position'])
        biases.append(bias)
        entries.append(entry)

    df['regime'] = regimes
    df['structure_position'] = structure_positions
    df['bias'] = biases
    df['entry_signal'] = entries

    # Apply parameterized ATR stop/target
    atr = df['atr'].fillna(0)
    close = df['close']
    is_long = df['bias'].isin(['STRONG_BULL', 'LEAN_BULL'])

    df['stop_level'] = np.where(is_long, close - atr_stop_mult * atr, close + atr_stop_mult * atr)
    df['target_1'] = np.where(is_long, close + atr_target_mult * atr, close - atr_target_mult * atr)
    df['target_2'] = np.where(is_long, close + atr_target_mult * 1.618 * atr, close - atr_target_mult * 1.618 * atr)
    df['target_3'] = np.where(is_long, close + atr_target_mult * 2.0 * atr, close - atr_target_mult * 2.0 * atr)

    # ── Volume confirmation filter ────────────────────────────────────────
    if volume_filter and 'volume' in df.columns:
        vol_ma = df['volume'].rolling(20).mean()
        high_volume = df['volume'] > vol_ma
        df.loc[(df['entry_signal'] == 'ENTRY_NOW') & ~high_volume, 'entry_signal'] = 'LOW_VOLUME_BLOCK'

    # ── MTF (Multi-Timeframe) confirmation filter ─────────────────────────
    if mtf_filter:
        from backtest.mtf_filter import MTFFilter
        # Resample 1h bars to 4h to get higher-timeframe STC
        ohlcv_4h = df[['open', 'high', 'low', 'close', 'volume']].resample('4h').agg({
            'open': 'first', 'high': 'max', 'low': 'min',
            'close': 'last', 'volume': 'sum',
        }).dropna(subset=['open', 'high', 'low', 'close'])
        if len(ohlcv_4h) >= 20:
            ohlcv_4h['timestamp'] = ohlcv_4h.index
            df_4h = compute_all_indicators(ohlcv_4h)
            # compute_all_indicators adds stc_signal, stc_cross_up, stc_cross_down
            mtf = MTFFilter()
            aligned = mtf.check_alignment(df, df_4h)
            df.loc[(df['entry_signal'] == 'ENTRY_NOW') & ~aligned, 'entry_signal'] = 'MTF_BLOCK'

    return df


def _run_with_params(
    df_base: pd.DataFrame,
    multiplier: float,
    initial_capital: float,
    adaptive_regime: bool = False,
    volume_filter: bool = False,
    mtf_filter: bool = False,
    **params,
) -> Optional[BacktestResult]:
    """Re-signal and backtest with given parameter set."""
    try:
        df = _compute_signals(df_base, adaptive_regime=adaptive_regime, volume_filter=volume_filter, mtf_filter=mtf_filter, **params)
        backtester = Backtester(
            initial_capital=initial_capital,
            risk_per_trade=0.01,
        )
        return backtester.run(df, "OPT", multiplier)
    except Exception as e:
        return None


def _score(r: BacktestResult) -> float:
    """
    Composite ranking score — balances return, Sharpe, win rate, and trade count.
    Penalizes <3 trades (insufficient sample) and high drawdown.
    """
    if r.total_trades < 3:
        return -999.0
    pf  = min(r.profit_factor, 10.0)       # cap at 10x
    wr  = r.win_rate                       # already 0.0-1.0, NO division by 100
    sr  = min(r.sharpe_ratio, 20.0)        # cap at 20
    ret = r.total_return_pct
    dd  = max(r.max_drawdown_pct, 0.001)   # avoid div/0
    return ((pf * 0.3) + (wr * 0.2) + (sr * 0.3) + (ret * 0.1)) / dd


def run_optimization(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
    fast: bool = True,
    top_n: int = 10,
    capital: float = 100_000.0,
    output: Optional[str] = None,
) -> list[OptResult]:

    loader = BacktestDataLoader()
    df = loader.load(symbol, start, end, interval)
    if df is None or df.empty:
        print(f"[Optimizer] No data for {symbol}")
        return []

    multiplier = loader.get_multiplier(symbol)
    grid = FAST_GRID if fast else PARAM_GRID

    combos = list(itertools.product(*grid.values()))
    keys   = list(grid.keys())
    total  = len(combos)
    print(f"\n[Optimizer] {symbol} | {len(df)} bars | {total} parameter combinations")
    print("-" * 60)

    results: list[OptResult] = []

    for idx, values in enumerate(combos):
        params = dict(zip(keys, values))

        if (idx + 1) % 20 == 0 or idx == total - 1:
            print(f"  Progress: {idx + 1}/{total}", end="\r")

        r = _run_with_params(df.copy(), multiplier, capital, **params)
        if r is None:
            continue

        score = _score(r)
        results.append(OptResult(
            stc_oversold    = params["stc_oversold"],
            stc_overbought  = params["stc_overbought"],
            atr_stop_mult   = params["atr_stop_mult"],
            atr_target_mult = params["atr_target_mult"],
            regime_filter   = params["regime_filter"],
            trades          = r.total_trades,
            win_rate        = round(r.win_rate, 1),
            profit_factor   = round(min(r.profit_factor, 999.0), 2),
            sharpe          = round(r.sharpe_ratio, 2),
            total_return_pct= round(r.total_return_pct, 3),
            max_dd_pct      = round(r.max_drawdown_pct, 3),
            score           = round(score, 4),
        ))

    print()  # newline after progress
    results.sort(key=lambda x: x.score, reverse=True)
    top = results[:top_n]

    # ── Print results table ────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"OPTIMIZATION RESULTS -- TOP {top_n}: {symbol} ({start} to {end})")
    print(f"{'='*70}")
    header = f"{'Rank':>4}  {'STC_OS':>6}  {'STC_OB':>6}  {'Stop':>5}  {'T1':>5}  {'Regime':>6}  {'Trades':>6}  {'WR%':>5}  {'PF':>6}  {'Sharpe':>6}  {'Ret%':>6}  {'Score':>7}"
    print(header)
    print("-" * 70)
    for i, r in enumerate(top):
        print(
            f"{i+1:>4}  {r.stc_oversold:>6}  {r.stc_overbought:>6}  "
            f"{r.atr_stop_mult:>5.2f}  {r.atr_target_mult:>5.2f}  "
            f"{'ON' if r.regime_filter else 'OFF':>6}  "
            f"{r.trades:>6}  {r.win_rate:>5.1f}  {r.profit_factor:>6.2f}  "
            f"{r.sharpe:>6.2f}  {r.total_return_pct:>6.3f}  {r.score:>7.4f}"
        )

    # ── Identify best parameters per metric ───────────────────────────────
    valid = [r for r in results if r.trades >= 3]
    if valid:
        best_wr  = max(valid, key=lambda x: x.win_rate)
        best_pf  = max(valid, key=lambda x: x.profit_factor)
        best_sr  = max(valid, key=lambda x: x.sharpe)
        best_ret = max(valid, key=lambda x: x.total_return_pct)

        print(f"\n{'-'*70}")
        print("BEST BY INDIVIDUAL METRIC:")
        print(f"  Win Rate:     OS={best_wr.stc_oversold}  OB={best_wr.stc_overbought}  Stop={best_wr.atr_stop_mult}  T1={best_wr.atr_target_mult}  -> {best_wr.win_rate}% WR")
        print(f"  Profit Factor:OS={best_pf.stc_oversold}  OB={best_pf.stc_overbought}  Stop={best_pf.atr_stop_mult}  T1={best_pf.atr_target_mult}  -> PF {best_pf.profit_factor}")
        print(f"  Sharpe:       OS={best_sr.stc_oversold}  OB={best_sr.stc_overbought}  Stop={best_sr.atr_stop_mult}  T1={best_sr.atr_target_mult}  -> {best_sr.sharpe}")
        print(f"  Total Return: OS={best_ret.stc_oversold}  OB={best_ret.stc_overbought}  Stop={best_ret.atr_stop_mult}  T1={best_ret.atr_target_mult}  -> {best_ret.total_return_pct}%")

    # ── Auto-save top 5 to backtest/results/{SYMBOL}_{interval}_optimal_params.json ──
    top5 = results[:5]
    if top5:
        engine_root = Path(__file__).parent.parent
        results_dir = engine_root / "backtest" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        auto_filename = f"{symbol}_{interval}_optimal_params.json"
        auto_path = results_dir / auto_filename

        # Build consensus: modal (most common) value per parameter across top 5
        def _mode(values):
            counts = {}
            for v in values:
                counts[v] = counts.get(v, 0) + 1
            return max(counts, key=counts.get)

        consensus = {
            "stc_oversold":    _mode([r.stc_oversold    for r in top5]),
            "stc_overbought":  _mode([r.stc_overbought  for r in top5]),
            "atr_stop_mult":   _mode([r.atr_stop_mult   for r in top5]),
            "atr_target_mult": _mode([r.atr_target_mult for r in top5]),
            "regime_filter":   _mode([r.regime_filter   for r in top5]),
        }

        payload = {
            "symbol":    symbol,
            "interval":  interval,
            "start":     start,
            "end":       end,
            "top_params": [asdict(r) for r in top5],
            "consensus": consensus,
        }
        auto_path.write_text(json.dumps(payload, indent=2))
        print(f"\nTop-5 results saved to: {auto_path}")

    # ── Manual --output flag ───────────────────────────────────────────────────
    if output:
        data = [asdict(r) for r in top]
        Path(output).write_text(json.dumps(data, indent=2))
        print(f"\nResults saved to {output}")

    return top


def main():
    parser = argparse.ArgumentParser(description="JARVIS Parameter Optimizer")
    parser.add_argument("--symbol",   default="SPY")
    parser.add_argument("--start",    default="2024-01-01")
    parser.add_argument("--end",      default="2025-01-01")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--full",     action="store_true", help="Full grid (slow) vs fast grid")
    parser.add_argument("--top",      type=int, default=10)
    parser.add_argument("--output",   default=None, help="Save JSON results")
    args = parser.parse_args()

    run_optimization(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        interval=args.interval,
        fast=not args.full,
        top_n=args.top,
        output=args.output,
    )


if __name__ == "__main__":
    main()
