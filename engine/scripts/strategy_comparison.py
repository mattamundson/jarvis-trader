"""
Phase D/E — Strategy comparison: SMA trend vs Donchian vs ADX-EMA vs
RSI-breakout vs ATR-channel.

All strategies are run on MES 1h (2024-06-01 → 2026-03-27) using the same
Backtester configuration and capital. Champion params are chosen by a simple
grid search; WFE is computed over one fixed train/test split matching the
original SMA WFO split (train→2025-06-01, test 2025-06→2026-03-27).

Output: side-by-side metrics table + JSON saved to backtest/results/.

Usage (from engine/):
  .venv/Scripts/python -m scripts.strategy_comparison
"""

from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import pandas as pd

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from backtest import BacktestDataLoader, Backtester  # noqa: E402
from backtest.adx_ema_signals import generate_adx_ema_signals  # noqa: E402
from backtest.atr_channel_signals import generate_atr_channel_signals  # noqa: E402
from backtest.donchian_signals import generate_donchian_signals  # noqa: E402
from backtest.rsi_breakout_signals import generate_rsi_breakout_signals  # noqa: E402
from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402

SYMBOL = "MES"
MULTIPLIER = 5.0
CAPITAL = 10_000.0
TRAIN_END = "2025-06-01"
TEST_END = "2026-03-27"
FULL_START = "2024-06-01"

# Backtester config shared across all strategies
_BT_KWARGS = {
    "initial_capital": CAPITAL,
    "trailing_stop": True,
    "t1_exit_pct": 1.0,
    "t2_exit_pct": 0.0,
    "strict_trailing": True,
    "eod_close": False,
    "use_targets": False,
    "fixed_contracts": 1,
    "max_drawdown": 0.99,
    "max_daily_loss": 0.99,
}

# Grids
SMA_GRID = {
    "fast": [40, 50, 60],
    "slow": [175, 200, 225],
    "atr_trail": [1.5, 2.0, 2.5],
}

DONCHIAN_GRID = {
    "lookback_entry": [10, 15, 20, 25, 30],
    "lookback_exit":  [5,  7,  10, 12],
    "atr_trail":      [1.5, 2.0, 2.5],
}

ADX_EMA_GRID = {
    "adx_threshold": [20.0, 25.0, 30.0],
    "ema_period":    [13, 21, 34],
    "atr_trail":     [2.0, 2.5, 3.0],
}

RSI_BREAKOUT_GRID = {
    "rsi_oversold":  [20.0, 25.0, 30.0],
    "entry_period":  [15, 20, 25],
    "atr_trail":     [1.5, 2.0, 2.5],
}

ATR_CHANNEL_GRID = {
    "atr_mult":      [1.5, 2.0, 2.5, 3.0],
    "ema_period":    [13, 20],
    "atr_trail":     [1.5, 2.0],
}

# Minimum trades required in train window for a combo to be considered
MIN_TRAIN_TRADES = 5


def _run_bt(df_sig: pd.DataFrame, atr_trail: float) -> dict:
    bt = Backtester(**_BT_KWARGS, trailing_atr_mult=atr_trail)
    r = bt.run(df_sig, SYMBOL, MULTIPLIER)
    return {
        "pf": r.profit_factor,
        "sharpe": r.sharpe_ratio,
        "n_trades": r.total_trades,
        "win_rate": r.win_rate,
        "max_dd": r.max_drawdown_pct,
        "total_return_pct": r.total_return_pct,
        "kelly": r.kelly_fraction,
    }


def _grid_search_sma(df_train: pd.DataFrame) -> tuple[dict, dict]:
    """Return (best_params, best_metrics) from SMA grid on train slice."""
    best_pf, best_params, best_metrics = -1, None, None
    for fast, slow, trail in product(SMA_GRID["fast"], SMA_GRID["slow"], SMA_GRID["atr_trail"]):
        if fast >= slow:
            continue
        try:
            sig = generate_sma_trend_signals(df_train.copy(), fast=fast, slow=slow, atr_trail_mult=trail)
            m = _run_bt(sig, trail)
            if m["n_trades"] >= MIN_TRAIN_TRADES and m["pf"] > best_pf:
                best_pf = m["pf"]
                best_params = {"fast": fast, "slow": slow, "atr_trail": trail}
                best_metrics = m
        except Exception:
            continue
    return best_params, best_metrics


def _grid_search_donchian(df_train: pd.DataFrame) -> tuple[dict, dict]:
    """Return (best_params, best_metrics) from Donchian grid on train slice."""
    best_pf, best_params, best_metrics = -1, None, None
    for entry_lb, exit_lb, trail in product(
        DONCHIAN_GRID["lookback_entry"],
        DONCHIAN_GRID["lookback_exit"],
        DONCHIAN_GRID["atr_trail"],
    ):
        if entry_lb <= exit_lb:
            continue
        try:
            sig = generate_donchian_signals(df_train.copy(), lookback_entry=entry_lb, lookback_exit=exit_lb, atr_trail_mult=trail)
            m = _run_bt(sig, trail)
            if m["n_trades"] >= MIN_TRAIN_TRADES and m["pf"] > best_pf:
                best_pf = m["pf"]
                best_params = {"lookback_entry": entry_lb, "lookback_exit": exit_lb, "atr_trail": trail}
                best_metrics = m
        except Exception:
            continue
    return best_params, best_metrics


def _run_strategy(
    name: str,
    df_full: pd.DataFrame,
    grid_fn,
    apply_fn,
) -> dict:
    """Run grid search on train, apply champion to test, compute WFE."""
    train_mask = (df_full.index >= FULL_START) & (df_full.index < TRAIN_END)
    test_mask  = (df_full.index >= TRAIN_END)  & (df_full.index < TEST_END)

    df_train = df_full[train_mask].copy()
    df_test  = df_full[test_mask].copy()

    print(f"  [{name}] Grid search on train ({len(df_train)} bars)...", end=" ", flush=True)
    best_params, train_m = grid_fn(df_train)
    if best_params is None:
        print("NO VALID COMBOS")
        return {"strategy": name, "error": "no valid train combos"}
    print(f"champion={best_params}  train_PF={train_m['pf']:.3f}  n={train_m['n_trades']}")

    print(f"  [{name}] Applying champion to test ({len(df_test)} bars)...", end=" ", flush=True)
    try:
        test_sig = apply_fn(df_test.copy(), best_params)
        atr_trail = best_params.get("atr_trail", 2.0)
        test_m = _run_bt(test_sig, atr_trail)
        wfe = test_m["pf"] / train_m["pf"] if train_m["pf"] > 0 else 0.0
        print(f"test_PF={test_m['pf']:.3f}  WFE={wfe:.3f}  n={test_m['n_trades']}")
    except Exception as e:
        print(f"ERROR: {e}")
        return {"strategy": name, "champion_params": best_params, "error": str(e)}

    # Full-period backtest with champion params
    print(f"  [{name}] Full-period backtest...", end=" ", flush=True)
    try:
        full_sig = apply_fn(df_full.copy(), best_params)
        full_m = _run_bt(full_sig, atr_trail)
        print(f"PF={full_m['pf']:.3f}  Sharpe={full_m['sharpe']:.3f}  n={full_m['n_trades']}")
    except Exception as e:
        full_m = {}
        print(f"FULL PERIOD ERROR: {e}")

    return {
        "strategy": name,
        "champion_params": best_params,
        "train": {k: round(v, 4) for k, v in train_m.items()},
        "test": {k: round(v, 4) for k, v in test_m.items()},
        "wfe": round(wfe, 4),
        "full_period": {k: round(v, 4) for k, v in full_m.items()} if full_m else {},
    }


def _apply_sma(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    return generate_sma_trend_signals(df, fast=params["fast"], slow=params["slow"], atr_trail_mult=params["atr_trail"])


def _apply_donchian(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    return generate_donchian_signals(df, lookback_entry=params["lookback_entry"], lookback_exit=params["lookback_exit"], atr_trail_mult=params["atr_trail"])


def _apply_adx_ema(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    return generate_adx_ema_signals(
        df,
        adx_threshold=params["adx_threshold"],
        ema_period=params["ema_period"],
        atr_trail_mult=params["atr_trail"],
    )


def _apply_rsi_breakout(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    return generate_rsi_breakout_signals(
        df,
        rsi_oversold=params["rsi_oversold"],
        rsi_overbought=100.0 - params["rsi_oversold"],  # mirror symmetric
        entry_period=params["entry_period"],
        atr_stop_mult=params["atr_trail"],
    )


def _apply_atr_channel(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    return generate_atr_channel_signals(
        df,
        atr_mult=params["atr_mult"],
        ema_period=params["ema_period"],
        atr_stop_mult=params["atr_trail"],
    )


def _grid_search_adx_ema(df_train: pd.DataFrame) -> tuple[dict, dict]:
    best_pf, best_params, best_metrics = -1, None, None
    for adx_t, ema_p, trail in product(
        ADX_EMA_GRID["adx_threshold"], ADX_EMA_GRID["ema_period"], ADX_EMA_GRID["atr_trail"],
    ):
        try:
            sig = _apply_adx_ema(df_train.copy(), {"adx_threshold": adx_t, "ema_period": ema_p, "atr_trail": trail})
            m = _run_bt(sig, trail)
            if m["n_trades"] >= MIN_TRAIN_TRADES and m["pf"] > best_pf:
                best_pf = m["pf"]
                best_params = {"adx_threshold": adx_t, "ema_period": ema_p, "atr_trail": trail}
                best_metrics = m
        except Exception:
            continue
    return best_params, best_metrics


def _grid_search_rsi_breakout(df_train: pd.DataFrame) -> tuple[dict, dict]:
    best_pf, best_params, best_metrics = -1, None, None
    for rsi_os, entry_p, trail in product(
        RSI_BREAKOUT_GRID["rsi_oversold"], RSI_BREAKOUT_GRID["entry_period"], RSI_BREAKOUT_GRID["atr_trail"],
    ):
        try:
            sig = _apply_rsi_breakout(df_train.copy(), {"rsi_oversold": rsi_os, "entry_period": entry_p, "atr_trail": trail})
            m = _run_bt(sig, trail)
            if m["n_trades"] >= MIN_TRAIN_TRADES and m["pf"] > best_pf:
                best_pf = m["pf"]
                best_params = {"rsi_oversold": rsi_os, "entry_period": entry_p, "atr_trail": trail}
                best_metrics = m
        except Exception:
            continue
    return best_params, best_metrics


def _grid_search_atr_channel(df_train: pd.DataFrame) -> tuple[dict, dict]:
    best_pf, best_params, best_metrics = -1, None, None
    for am, ep, trail in product(
        ATR_CHANNEL_GRID["atr_mult"], ATR_CHANNEL_GRID["ema_period"], ATR_CHANNEL_GRID["atr_trail"],
    ):
        try:
            sig = _apply_atr_channel(df_train.copy(), {"atr_mult": am, "ema_period": ep, "atr_trail": trail})
            m = _run_bt(sig, trail)
            if m["n_trades"] >= MIN_TRAIN_TRADES and m["pf"] > best_pf:
                best_pf = m["pf"]
                best_params = {"atr_mult": am, "ema_period": ep, "atr_trail": trail}
                best_metrics = m
        except Exception:
            continue
    return best_params, best_metrics


def main():
    loader = BacktestDataLoader()
    df_full = loader.load(SYMBOL, FULL_START, TEST_END, "1h")
    if df_full is None or df_full.empty:
        print(f"ERROR: No cached data for {SYMBOL}")
        return 1

    print(f"MES Strategy Comparison — {len(df_full)} bars ({FULL_START}→{TEST_END})")
    print(f"Train: {FULL_START}→{TRAIN_END}  |  Test: {TRAIN_END}→{TEST_END}")
    print()

    results = []

    print("── SMA Trend (50,200,2.0) — fixed champion, no grid search ──")
    # Use the validated champion directly (no overfit risk on fixed params)
    fixed_sma_params = {"fast": 50, "slow": 200, "atr_trail": 2.0}
    train_mask = (df_full.index >= FULL_START) & (df_full.index < TRAIN_END)
    test_mask  = (df_full.index >= TRAIN_END)
    df_train_sma = df_full[train_mask].copy()
    df_test_sma  = df_full[test_mask].copy()
    train_sig = _apply_sma(df_train_sma, fixed_sma_params)
    test_sig  = _apply_sma(df_test_sma,  fixed_sma_params)
    full_sig  = _apply_sma(df_full.copy(), fixed_sma_params)
    train_m_sma = _run_bt(train_sig, 2.0)
    test_m_sma  = _run_bt(test_sig,  2.0)
    full_m_sma  = _run_bt(full_sig,  2.0)
    wfe_sma = test_m_sma["pf"] / train_m_sma["pf"] if train_m_sma["pf"] > 0 else 0.0
    print(f"  train PF={train_m_sma['pf']:.3f} n={train_m_sma['n_trades']}  "
          f"test PF={test_m_sma['pf']:.3f} n={test_m_sma['n_trades']}  "
          f"WFE={wfe_sma:.3f}  full PF={full_m_sma['pf']:.3f}")
    results.append({
        "strategy": "SMA(50,200,2.0) — fixed champion",
        "champion_params": fixed_sma_params,
        "train": {k: round(v, 4) for k, v in train_m_sma.items()},
        "test": {k: round(v, 4) for k, v in test_m_sma.items()},
        "wfe": round(wfe_sma, 4),
        "full_period": {k: round(v, 4) for k, v in full_m_sma.items()},
    })
    print()

    print("── Donchian Channel Breakout — grid search ──")
    results.append(_run_strategy("Donchian", df_full, _grid_search_donchian, _apply_donchian))
    print()

    print("── SMA Trend — grid search (for comparison vs fixed-champion) ──")
    results.append(_run_strategy("SMA-grid", df_full, _grid_search_sma, _apply_sma))
    print()

    print("── ADX-EMA Trend — grid search ──")
    results.append(_run_strategy("ADX-EMA", df_full, _grid_search_adx_ema, _apply_adx_ema))
    print()

    print("── RSI-Breakout — grid search ──")
    results.append(_run_strategy("RSI-Breakout", df_full, _grid_search_rsi_breakout, _apply_rsi_breakout))
    print()

    print("── ATR-Channel — grid search ──")
    results.append(_run_strategy("ATR-Channel", df_full, _grid_search_atr_channel, _apply_atr_channel))
    print()

    # Summary table
    print()
    print("=" * 80)
    print("  Strategy Comparison Summary")
    print("=" * 80)
    hdr = f"  {'Strategy':<35} {'Train PF':>9} {'Test PF':>9} {'WFE':>7} {'Full PF':>9} {'Sharpe':>8} {'n_full':>7}"
    print(hdr)
    print("  " + "-" * 78)
    for r in results:
        if "error" in r:
            print(f"  {r['strategy']:<35} ERROR: {r['error']}")
            continue
        fp = r.get("full_period", {})
        print(f"  {r['strategy']:<35} "
              f"{r['train']['pf']:>9.3f} "
              f"{r['test']['pf']:>9.3f} "
              f"{r['wfe']:>7.3f} "
              f"{fp.get('pf', 0.0):>9.3f} "
              f"{fp.get('sharpe', 0.0):>8.3f} "
              f"{fp.get('n_trades', 0):>7}")
    print("=" * 80)
    print()
    print("WFE interpretation: ≥0.50 = edge holds OOS | <0.50 = likely overfit")

    out = {
        "metadata": {
            "symbol": SYMBOL,
            "multiplier": MULTIPLIER,
            "full_start": FULL_START,
            "train_end": TRAIN_END,
            "test_end": TEST_END,
            "capital": CAPITAL,
        },
        "results": results,
    }
    out_path = ENGINE_DIR / "backtest" / "results" / "MES_strategy_comparison.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[comparison] Saved: {out_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
