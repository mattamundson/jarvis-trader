"""
JARVIS TRADER - Parameter Optimizer
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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from backtest.backtester import Backtester, BacktestResult
from backtest.data_loader import BacktestDataLoader
from backtest.indicators import (
    ema_ribbon,
    kama,
    phase_oscillator,
    stc,
    wilder_atr,
)

# ── Parameter grid ────────────────────────────────────────────────────────────

PARAM_GRID = {
    "stc_oversold": [15, 17, 19, 21, 23],  # default=19
    "stc_overbought": [83, 85, 88, 90, 92],  # default=88
    "atr_stop_mult": [0.3, 0.4, 0.5, 0.6, 0.7],  # default=0.5
    "atr_target_mult": [0.8, 1.0, 1.2, 1.5, 2.0],  # default=1.0
    "regime_filter": [True, False],  # default=True
}

# Reduced grid for fast runs (comment out to do full grid)
FAST_GRID = {
    "stc_oversold": [15, 19, 23],
    "stc_overbought": [83, 88, 92],
    "atr_stop_mult": [0.3, 0.5, 0.7],
    "atr_target_mult": [1.0, 1.5, 2.0],
    "regime_filter": [True, False],
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
    calmar_ratio: float
    exposure_time_pct: float
    total_return_pct: float
    max_dd_pct: float
    score: float  # composite ranking score
    verdict: str = "UNKNOWN"  # ELIGIBLE | DISCARD_RISK | DISCARD_PROFIT | INVALID
    violations: list = field(default_factory=list)


def validate_backtest_result(stats: dict) -> dict:
    """
    Two-layer validation: RISK gate (drawdown) + PROFIT gate (quality).
    Returns verdict: ELIGIBLE | DISCARD_RISK | DISCARD_PROFIT | INVALID
    """
    n_trades = stats.get("n_trades", 0)
    if n_trades == 0 or stats.get("profit_factor") is None:
        return {
            "verdict": "INVALID",
            "risk_passed": False,
            "profit_passed": False,
            "violations": ["Zero trades or null metrics"],
        }

    violations = []

    # RISK GATE: drawdown
    max_dd = abs(stats.get("max_drawdown_pct", 0))
    if max_dd > 15.0:
        violations.append(f"Max DD {max_dd:.1f}% exceeds 15% limit")
    risk_passed = len(violations) == 0

    # PROFIT GATE
    profit_violations = []
    if n_trades < 20:
        profit_violations.append(f"Only {n_trades} trades (need ≥20)")
    if stats.get("exposure_time_pct", 100) < 25.0:
        profit_violations.append(f"Exposure {stats.get('exposure_time_pct', 100):.1f}% < 25%")
    if stats.get("sharpe", 0) < 1.2:
        profit_violations.append(f"Sharpe {stats.get('sharpe', 0):.2f} < 1.2")
    if stats.get("calmar_ratio", 0) < 0.8:
        profit_violations.append(f"Calmar {stats.get('calmar_ratio', 0):.2f} < 0.8")
    if stats.get("profit_factor", 0) < 1.8:
        profit_violations.append(f"PF {stats.get('profit_factor', 0):.2f} < 1.8")
    # CVaR gate: expected shortfall at 95% should not exceed -5% per day
    cvar_daily = stats.get("cvar_95", 0)
    if cvar_daily < -0.05:
        profit_violations.append(f"CVaR-95 {cvar_daily:.2%} exceeds -5% daily threshold")

    profit_passed = len(profit_violations) == 0
    all_violations = violations + profit_violations

    if not risk_passed:
        verdict = "DISCARD_RISK"
    elif not profit_passed:
        verdict = "DISCARD_PROFIT"
    else:
        verdict = "ELIGIBLE"

    return {
        "verdict": verdict,
        "risk_passed": risk_passed,
        "profit_passed": profit_passed,
        "violations": all_violations,
    }


def build_daily_bias(df_daily: pd.DataFrame) -> pd.Series:
    """
    Compute daily EMA8/21/34 directional bias from a daily OHLCV DataFrame.

    Returns a pd.Series indexed by date (tz-naive) with values:
        'BULL'   -- EMA8 > EMA21 > EMA34  (allow longs, filter shorts)
        'BEAR'   -- EMA8 < EMA21 < EMA34  (allow shorts, filter longs)
        'NEUTRAL'-- mixed alignment        (filter both directions)
    """
    close = df_daily["close"]
    ema8, ema21, ema34 = ema_ribbon(close)

    # Index normalised to date only (drop time component)
    idx = pd.to_datetime(df_daily.index).normalize()

    bull_mask = (ema8 > ema21) & (ema21 > ema34)
    bear_mask = (ema8 < ema21) & (ema21 < ema34)

    bias = pd.Series("NEUTRAL", index=idx)
    bias.loc[bull_mask.values] = "BULL"
    bias.loc[bear_mask.values] = "BEAR"

    # Remove duplicate dates (shouldn't occur on daily data but guard anyway)
    bias = bias[~bias.index.duplicated(keep="last")]
    return bias


def _apply_mtf_filter(df: pd.DataFrame, daily_bias: pd.Series) -> tuple:
    """
    Apply MTF daily-bias filter to a 1h DataFrame's entry_signal column.
    Vectorized implementation - O(N) merge instead of O(N*M) row loop.

    Rules:
        BULL day  -> only allow STRONG_BULL (long) entries
        BEAR day  -> only allow STRONG_BEAR (short) entries
        NEUTRAL   -> block all entries

    Direction is inferred from the bias column already computed by _compute_signals.
    Uses pandas merge_asof to forward-fill daily bias onto 1h bars efficiently.
    """
    df = df.copy()

    # Build a sorted daily bias DataFrame for merge_asof
    daily_df = daily_bias.rename("daily_bias").reset_index()
    daily_df.columns = ["date", "daily_bias"]
    daily_df["date"] = pd.to_datetime(daily_df["date"])
    daily_df = daily_df.sort_values("date")

    # Build 1h bar date column (normalized to midnight, tz-naive)
    bar_dates = pd.to_datetime(df.index).normalize().tz_localize(None)
    hourly_df = pd.DataFrame({"bar_ts": bar_dates}).reset_index(drop=True)

    # Forward-fill daily bias to each 1h bar (tolerance=7 days for weekend gaps)
    merged = pd.merge_asof(
        hourly_df.sort_values("bar_ts"),
        daily_df,
        left_on="bar_ts",
        right_on="date",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    )
    # Re-align to original df order
    d_bias_arr = merged["daily_bias"].fillna("NEUTRAL").values

    # Vectorized filter masks
    entry_mask = df["entry_signal"].values == "ENTRY_NOW"
    bar_bias_arr = df["bias"].values

    # Conditions to BLOCK (convert ENTRY_NOW -> NO_TRADE)
    d_neutral = d_bias_arr == "NEUTRAL"
    d_bull_but_not_bull = (d_bias_arr == "BULL") & (bar_bias_arr != "STRONG_BULL")
    d_bear_but_not_bear = (d_bias_arr == "BEAR") & (bar_bias_arr != "STRONG_BEAR")

    block_mask = entry_mask & (d_neutral | d_bull_but_not_bull | d_bear_but_not_bear)
    filtered_count = int(block_mask.sum())

    df.loc[df.index[block_mask], "entry_signal"] = "NO_TRADE"

    return df, filtered_count


def _compute_signals(
    df: pd.DataFrame,
    stc_oversold: float,
    stc_overbought: float,
    atr_stop_mult: float,
    atr_target_mult: float,
    regime_filter: bool,
    daily_bias: "pd.Series | None" = None,
) -> pd.DataFrame:
    """Recompute signals with given parameters."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    df["volume"]

    atr_vals = wilder_atr(high, low, close, 14)
    stc_vals = stc(close, fast=23, slow=50, k_period=10, d_period=3)
    phase_vals, phase_compression = phase_oscillator(close, high, low)
    ema8, ema21, ema34 = ema_ribbon(close)
    # range_consumed_pct takes scalars - compute as series inline
    consumed = ((close - close.shift(1)).abs() / atr_vals.replace(0, float("nan"))) * 100
    kama_vals = kama(close)

    signals = []
    for i in range(len(df)):
        row = df.iloc[i]
        atr_i = atr_vals.iloc[i]
        stc_i = stc_vals.iloc[i]
        phase_i = phase_vals.iloc[i]
        e8, e21, e34 = ema8.iloc[i], ema21.iloc[i], ema34.iloc[i]
        cons = consumed.iloc[i]
        kama_i = kama_vals.iloc[i]

        entry = "NO_TRADE"

        if pd.isna(atr_i) or pd.isna(stc_i):
            signals.append(entry)
            continue

        # Layer 1: Regime filter
        if regime_filter:
            if cons > 90:
                signals.append("NO_TRADE")
                continue
            # Phase compression check (skip if already extended)
            if not pd.isna(phase_i) and abs(phase_i) > 80:
                signals.append("NO_TRADE")
                continue

        # Layer 3: Bias
        bullish_ema = (not pd.isna(e8)) and (not pd.isna(e34)) and (e8 > e21 > e34)
        bearish_ema = (not pd.isna(e8)) and (not pd.isna(e34)) and (e8 < e21 < e34)
        close_above_kama = (not pd.isna(kama_i)) and (row["close"] > kama_i)

        # Layer 4: Entry timing with parameterized STC thresholds
        # Long entry: STC oversold crossover with bullish bias
        if stc_i < stc_oversold and (bullish_ema or close_above_kama):
            entry = "ENTRY_NOW"
        # Short entry: STC overbought crossover with bearish bias
        elif stc_i > stc_overbought and (bearish_ema or not close_above_kama):
            entry = "ENTRY_NOW"

        signals.append(entry)

    df = df.copy()
    df["entry_signal"] = signals
    df["atr"] = atr_vals.values

    # Columns required by backtester
    df["stop_level"] = df["close"] - atr_stop_mult * df["atr"]
    df["target_1"] = df["close"] + atr_target_mult * df["atr"]
    df["target_2"] = df["close"] + atr_target_mult * 1.618 * df["atr"]
    df["target_3"] = df["close"] + atr_target_mult * 2.0 * df["atr"]

    # Bias column: derive from EMA ribbon
    ema8_s, ema21_s, ema34_s = ema_ribbon(df["close"])
    bull_mask = (ema8_s > ema21_s) & (ema21_s > ema34_s)
    bear_mask = (ema8_s < ema21_s) & (ema21_s < ema34_s)
    df["bias"] = "NEUTRAL"
    df.loc[bull_mask, "bias"] = "STRONG_BULL"
    df.loc[bear_mask, "bias"] = "STRONG_BEAR"

    # Regime column: simple consumed-ATR proxy
    consumed_s = (
        (df["close"] - df["close"].shift(1)).abs() / atr_vals.replace(0, float("nan"))
    ) * 100
    df["regime"] = "TRENDING_BULL"
    df.loc[consumed_s > 90, "regime"] = "EXHAUSTED"

    # MTF filter: apply daily EMA bias to block counter-trend 1h entries
    if daily_bias is not None:
        df, filtered_count = _apply_mtf_filter(df, daily_bias)

    return df


def _run_with_params(
    df_base: pd.DataFrame,
    multiplier: float,
    initial_capital: float,
    **params,
) -> Optional[BacktestResult]:
    """Re-signal and backtest with given parameter set."""
    try:
        # Filter to only the params that _compute_signals accepts
        signal_keys = {
            "stc_oversold",
            "stc_overbought",
            "atr_stop_mult",
            "atr_target_mult",
            "regime_filter",
        }
        signal_params = {k: v for k, v in params.items() if k in signal_keys}

        # Pass daily_bias through if present (MTF filter)
        daily_bias = params.get("daily_bias", None)

        df = _compute_signals(df_base, **signal_params, daily_bias=daily_bias)
        backtester = Backtester(
            initial_capital=initial_capital,
            risk_per_trade=0.01,
        )
        return backtester.run(df, "OPT", multiplier)
    except Exception:
        return None


def _score(r: BacktestResult) -> float:
    """
    Composite ranking score - balances return, Sharpe, win rate, and trade count.
    Penalizes <3 trades (insufficient sample) and high drawdown.
    """
    if r.total_trades < 3:
        return -999.0
    pf = min(r.profit_factor, 10.0)  # cap at 10x
    wr = r.win_rate / 100.0
    sr = min(r.sharpe_ratio, 20.0)  # cap at 20
    ret = r.total_return_pct
    dd = max(r.max_drawdown_pct, 0.001)  # avoid div/0
    return (pf * 0.3 + wr * 0.2 + sr * 0.3 + ret * 0.1) / dd * 0.1


def run_optimization(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
    fast: bool = True,
    top_n: int = 10,
    capital: float = 10_000.0,
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
    keys = list(grid.keys())
    total = len(combos)
    print(f"\n[Optimizer] {symbol} | {len(df)} bars | {total} parameter combinations")
    print("-" * 60)

    results: list[OptResult] = []

    for idx, values in enumerate(combos):
        params = dict(zip(keys, values, strict=False))

        if (idx + 1) % 20 == 0 or idx == total - 1:
            print(f"  Progress: {idx + 1}/{total}", end="\r")

        r = _run_with_params(df.copy(), multiplier, capital, **params)
        if r is None:
            continue

        score = _score(r)
        # Build validation-compatible stats dict for dual-gate check
        stats_for_validation = {
            "n_trades": r.total_trades,
            "profit_factor": r.profit_factor if r.profit_factor != float("inf") else 999.0,
            "max_drawdown_pct": r.max_drawdown_pct * 100,  # convert fraction → pct
            "sharpe": r.sharpe_ratio,
            "calmar_ratio": r.calmar_ratio,
            "exposure_time_pct": r.exposure_time_pct,
        }
        validation = validate_backtest_result(stats_for_validation)
        results.append(
            OptResult(
                stc_oversold=params["stc_oversold"],
                stc_overbought=params["stc_overbought"],
                atr_stop_mult=params["atr_stop_mult"],
                atr_target_mult=params["atr_target_mult"],
                regime_filter=params["regime_filter"],
                trades=r.total_trades,
                win_rate=round(r.win_rate, 1),
                profit_factor=round(min(r.profit_factor, 999.0), 2),
                sharpe=round(r.sharpe_ratio, 2),
                calmar_ratio=round(r.calmar_ratio, 2),
                exposure_time_pct=round(r.exposure_time_pct, 1),
                total_return_pct=round(r.total_return_pct, 3),
                max_dd_pct=round(r.max_drawdown_pct, 3),
                score=round(score, 4),
                verdict=validation["verdict"],
                violations=validation["violations"],
            )
        )

    print()  # newline after progress
    results.sort(key=lambda x: x.score, reverse=True)
    top = results[:top_n]

    # ── Print results table ────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"OPTIMIZATION RESULTS -- TOP {top_n}: {symbol} ({start} to {end})")
    print(f"{'=' * 70}")
    header = f"{'Rank':>4}  {'STC_OS':>6}  {'STC_OB':>6}  {'Stop':>5}  {'T1':>5}  {'Regime':>6}  {'Trades':>6}  {'WR%':>5}  {'PF':>6}  {'Sharpe':>6}  {'Ret%':>6}  {'Score':>7}"
    print(header)
    print("-" * 70)
    for i, r in enumerate(top):
        print(
            f"{i + 1:>4}  {r.stc_oversold:>6}  {r.stc_overbought:>6}  "
            f"{r.atr_stop_mult:>5.2f}  {r.atr_target_mult:>5.2f}  "
            f"{'ON' if r.regime_filter else 'OFF':>6}  "
            f"{r.trades:>6}  {r.win_rate:>5.1f}  {r.profit_factor:>6.2f}  "
            f"{r.sharpe:>6.2f}  {r.total_return_pct:>6.3f}  {r.score:>7.4f}"
        )

    # ── Verdict summary (dual-gate validation) ────────────────────────────
    eligible_count = sum(1 for r in results if r.verdict == "ELIGIBLE")
    print(f"\n[VERDICT SUMMARY] {eligible_count}/{len(results)} parameter sets ELIGIBLE")
    top5_by_pf = sorted(results, key=lambda x: x.profit_factor, reverse=True)[:5]
    for r in top5_by_pf:
        violation_str = "; ".join(r.violations) if r.violations else "All gates pass"
        print(f"  [{r.verdict}] PF={r.profit_factor:.2f} Calmar={r.calmar_ratio:.2f} Exp={r.exposure_time_pct:.0f}%  | {violation_str}")

    # ── Identify best parameters per metric ───────────────────────────────
    valid = [r for r in results if r.trades >= 3]
    if valid:
        best_wr = max(valid, key=lambda x: x.win_rate)
        best_pf = max(valid, key=lambda x: x.profit_factor)
        best_sr = max(valid, key=lambda x: x.sharpe)
        best_ret = max(valid, key=lambda x: x.total_return_pct)

        print(f"\n{'-' * 70}")
        print("BEST BY INDIVIDUAL METRIC:")
        print(
            f"  Win Rate:     OS={best_wr.stc_oversold}  OB={best_wr.stc_overbought}  Stop={best_wr.atr_stop_mult}  T1={best_wr.atr_target_mult}  -> {best_wr.win_rate}% WR"
        )
        print(
            f"  Profit Factor:OS={best_pf.stc_oversold}  OB={best_pf.stc_overbought}  Stop={best_pf.atr_stop_mult}  T1={best_pf.atr_target_mult}  -> PF {best_pf.profit_factor}"
        )
        print(
            f"  Sharpe:       OS={best_sr.stc_oversold}  OB={best_sr.stc_overbought}  Stop={best_sr.atr_stop_mult}  T1={best_sr.atr_target_mult}  -> {best_sr.sharpe}"
        )
        print(
            f"  Total Return: OS={best_ret.stc_oversold}  OB={best_ret.stc_overbought}  Stop={best_ret.atr_stop_mult}  T1={best_ret.atr_target_mult}  -> {best_ret.total_return_pct}%"
        )

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
            "stc_oversold": _mode([r.stc_oversold for r in top5]),
            "stc_overbought": _mode([r.stc_overbought for r in top5]),
            "atr_stop_mult": _mode([r.atr_stop_mult for r in top5]),
            "atr_target_mult": _mode([r.atr_target_mult for r in top5]),
            "regime_filter": _mode([r.regime_filter for r in top5]),
        }

        payload = {
            "symbol": symbol,
            "interval": interval,
            "start": start,
            "end": end,
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
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--full", action="store_true", help="Full grid (slow) vs fast grid")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--output", default=None, help="Save JSON results")
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
