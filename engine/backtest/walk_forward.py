"""
JARVIS TRADER -- Walk-Forward Validation Framework
====================================================
The gold standard of backtesting: optimize on in-sample (IS) data, then
validate on out-of-sample (OOS) data, rolling forward through time.

The key metric is Walk-Forward Efficiency (WFE):
    WFE = avg_oos_return / avg_is_return

    > 0.50  => strategy generalises well
    0.30-0.50 => acceptable, some degradation
    < 0.30  => likely overfit

Usage:
    cd engine
    .venv/Scripts/python -m backtest.walk_forward --symbol SPY --interval 1h --start 2024-06-01 --end 2026-03-27
"""

from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.backtester import BacktestResult
from backtest.data_loader import BacktestDataLoader
from backtest.optimizer import (
    FAST_GRID,
    PARAM_GRID,
    _run_with_params,
    _score,
    build_daily_bias,
)

# ---------------------------------------------------------------------------
# Walk-Forward Validator
# ---------------------------------------------------------------------------


class WalkForwardValidator:
    """Rolling walk-forward optimisation and out-of-sample validation."""

    def __init__(
        self,
        train_months: int = 6,
        test_months: int = 3,
        step_months: int = 3,
    ):
        self.train_months = train_months
        self.test_months = test_months
        self.step_months = step_months

    # ------------------------------------------------------------------
    # Window generation
    # ------------------------------------------------------------------

    def generate_windows(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> List[Dict[str, Any]]:
        """
        Generate rolling train/test windows from a DatetimeIndex DataFrame.

        Returns a list of dicts:
            [{'train_start', 'train_end', 'test_start', 'test_end', 'window_num'}, ...]

        Test periods are non-overlapping.  Each period must contain at least
        30 trading bars to be considered valid.
        """
        if df.empty:
            return []

        data_start = df.index.min()
        data_end = df.index.max()

        windows: List[Dict[str, Any]] = []
        window_num = 1
        cursor = data_start

        while True:
            train_start = cursor
            train_end = train_start + pd.DateOffset(months=self.train_months)
            test_start = train_end
            test_end = test_start + pd.DateOffset(months=self.test_months)

            # Clamp to available data
            if test_start >= data_end:
                break

            if test_end > data_end:
                test_end = data_end

            # Check minimum bar counts
            train_bars = len(df[(df.index >= train_start) & (df.index < train_end)])
            test_bars = len(df[(df.index >= test_start) & (df.index <= test_end)])

            if train_bars < 30 or test_bars < 30:
                # Advance cursor and try next window
                cursor += pd.DateOffset(months=self.step_months)
                if cursor >= data_end:
                    break
                continue

            windows.append(
                {
                    "window_num": window_num,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "train_bars": train_bars,
                    "test_bars": test_bars,
                }
            )
            window_num += 1

            # Advance by step_months (non-overlapping test periods)
            cursor += pd.DateOffset(months=self.step_months)
            if cursor >= data_end:
                break

        return windows

    # ------------------------------------------------------------------
    # Core run
    # ------------------------------------------------------------------

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        multiplier: float = 1.0,
        capital: float = 10_000.0,
        top_n_params: int = 1,
        fast: bool = True,
        adaptive_regime: bool = False,
        volume_filter: bool = False,
        mtf_filter: bool = False,
        df_daily: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        Execute the full walk-forward validation.

        For each window:
          1. Optimise on train data (grid search, fast grid by default).
          2. Select the best parameter set (by composite score).
          3. Backtest on the OOS test data with those parameters.
          4. Record IS and OOS BacktestResults.

        When mtf_filter=True, df_daily must be provided. The daily EMA8/21/34
        bias is computed once and used to filter counter-trend 1h entries in
        each window.

        Returns a dict with 'windows' and 'summary' keys.
        """
        # Pre-compute daily bias series for MTF filter
        daily_bias_series: Optional[Any] = None
        if mtf_filter:
            if df_daily is None or df_daily.empty:
                print(
                    "[WalkForward] WARNING: --mtf-filter requested but no daily data provided. MTF filter disabled."
                )
                mtf_filter = False
            else:
                daily_bias_series = build_daily_bias(df_daily)
                bull_count = (daily_bias_series == "BULL").sum()
                bear_count = (daily_bias_series == "BEAR").sum()
                neutral_count = (daily_bias_series == "NEUTRAL").sum()
                print(
                    f"[MTF] Daily bias computed: {len(daily_bias_series)} days "
                    f"| BULL={bull_count} BEAR={bear_count} NEUTRAL={neutral_count}"
                )

        windows_spec = self.generate_windows(df, symbol)

        if not windows_spec:
            print("[WalkForward] Not enough data to form any windows.")
            return {"windows": [], "summary": self._empty_summary()}

        grid = FAST_GRID if fast else PARAM_GRID
        combos = list(itertools.product(*grid.values()))
        keys = list(grid.keys())

        mode_parts = []
        if adaptive_regime:
            mode_parts.append("adaptive-regime")
        if volume_filter:
            mode_parts.append("volume-filter")
        if mtf_filter:
            mode_parts.append("mtf-filter")
        mode_label = "+".join(mode_parts) if mode_parts else "static"
        print(f"\n{'=' * 65}")
        print(f"=== WALK-FORWARD VALIDATION: {symbol} [{mode_label}] ===")
        print(
            f"Windows: {len(windows_spec)} | Train: {self.train_months}mo | Test: {self.test_months}mo"
        )
        print(f"Grid: {len(combos)} param combos ({'fast' if fast else 'full'})")
        print(f"{'=' * 65}")

        results_windows: List[Dict[str, Any]] = []

        for win in windows_spec:
            wnum = win["window_num"]
            train_start = win["train_start"]
            train_end = win["train_end"]
            test_start = win["test_start"]
            test_end = win["test_end"]

            train_label = f"{train_start.strftime('%Y-%m')} to {(train_end - pd.Timedelta(days=1)).strftime('%Y-%m')}"
            test_label = f"{test_start.strftime('%Y-%m')} to {test_end.strftime('%Y-%m')}"

            print(f"\nWindow {wnum}: Train {train_label} | Test {test_label}")
            print(f"  Bars: train={win['train_bars']}, test={win['test_bars']}")

            # ── Slice data ────────────────────────────────────────────────
            df_train = df[(df.index >= train_start) & (df.index < train_end)].copy()
            df_test = df[(df.index >= test_start) & (df.index <= test_end)].copy()

            # ── Optimise on train data ────────────────────────────────────
            best_params, best_score, is_result = self._optimise_window(
                df_train,
                multiplier,
                capital,
                combos,
                keys,
                adaptive_regime=adaptive_regime,
                volume_filter=volume_filter,
                mtf_filter=mtf_filter,
                daily_bias=daily_bias_series,
            )

            if best_params is None or is_result is None:
                print("  [SKIP] Optimisation returned no valid results.")
                continue

            print(
                f"  Best params: STC_OS={best_params['stc_oversold']}, "
                f"STC_OB={best_params['stc_overbought']}, "
                f"Stop={best_params['atr_stop_mult']:.2f}, "
                f"T1={best_params['atr_target_mult']:.2f}"
            )
            print(
                f"  IS:  PF={is_result.profit_factor:.2f}  "
                f"Sharpe={is_result.sharpe_ratio:.2f}  "
                f"Return={is_result.total_return_pct * 100:.1f}%  "
                f"Trades={is_result.total_trades}"
            )

            # ── Backtest OOS with best params ─────────────────────────────
            oos_result = _run_with_params(
                df_test,
                multiplier,
                capital,
                adaptive_regime=adaptive_regime,
                volume_filter=volume_filter,
                mtf_filter=mtf_filter,
                daily_bias=daily_bias_series,
                **best_params,
            )

            if oos_result is None:
                print("  OOS: [FAILED] — backtest returned None")
                continue

            print(
                f"  OOS: PF={oos_result.profit_factor:.2f}  "
                f"Sharpe={oos_result.sharpe_ratio:.2f}  "
                f"Return={oos_result.total_return_pct * 100:.1f}%  "
                f"Trades={oos_result.total_trades}"
            )

            results_windows.append(
                {
                    "window": wnum,
                    "train_period": train_label,
                    "test_period": test_label,
                    "train_bars": win["train_bars"],
                    "test_bars": win["test_bars"],
                    "best_params": best_params,
                    "is_result": is_result,
                    "oos_result": oos_result,
                }
            )

        # ── Summary ───────────────────────────────────────────────────────
        summary = self._compute_summary(results_windows)
        self._print_summary(summary)

        return {"windows": results_windows, "summary": summary}

    # ------------------------------------------------------------------
    # Internal: grid-search a single window
    # ------------------------------------------------------------------

    def _optimise_window(
        self,
        df_train: pd.DataFrame,
        multiplier: float,
        capital: float,
        combos: list,
        keys: list,
        adaptive_regime: bool = False,
        volume_filter: bool = False,
        mtf_filter: bool = False,
        daily_bias: Optional[Any] = None,
    ):
        """
        Run grid optimisation on df_train.
        Returns (best_params_dict, best_score, best_BacktestResult) or (None, None, None).
        """
        best_params: Optional[dict] = None
        best_score = -999.0
        best_result: Optional[BacktestResult] = None

        total = len(combos)
        for idx, values in enumerate(combos):
            params = dict(zip(keys, values, strict=False))

            if (idx + 1) % 25 == 0 or idx == total - 1:
                print(f"  Optimising: {idx + 1}/{total}", end="\r")

            r = _run_with_params(
                df_train,
                multiplier,
                capital,
                adaptive_regime=adaptive_regime,
                volume_filter=volume_filter,
                mtf_filter=mtf_filter,
                daily_bias=daily_bias,
                **params,
            )
            if r is None:
                continue

            score = _score(r)
            if score > best_score:
                best_score = score
                best_params = params
                best_result = r

        print("  " + " " * 40, end="\r")  # clear progress line
        return best_params, best_score, best_result

    # ------------------------------------------------------------------
    # Summary computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_summary(windows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate metrics across all OOS windows."""
        if not windows:
            return WalkForwardValidator._empty_summary()

        is_returns = [w["is_result"].total_return_pct for w in windows]
        oos_returns = [w["oos_result"].total_return_pct for w in windows]
        oos_sharpes = [w["oos_result"].sharpe_ratio for w in windows]
        oos_pfs = [w["oos_result"].profit_factor for w in windows]

        avg_is = float(np.mean(is_returns))
        avg_oos = float(np.mean(oos_returns))

        # WFE: guard against zero/negative IS return
        if avg_is > 0:
            wfe = avg_oos / avg_is
        elif avg_is == 0:
            wfe = 0.0
        else:
            # Negative IS return — WFE is meaningless; set to 0
            wfe = 0.0

        windows_profitable = sum(1 for r in oos_returns if r > 0)

        return {
            "avg_is_return": round(avg_is, 6),
            "avg_oos_return": round(avg_oos, 6),
            "wfe": round(wfe, 4),
            "avg_oos_sharpe": round(float(np.mean(oos_sharpes)), 4),
            "avg_oos_profit_factor": round(float(np.mean([min(pf, 999.0) for pf in oos_pfs])), 4),
            "windows_profitable": windows_profitable,
            "total_windows": len(windows),
        }

    @staticmethod
    def _empty_summary() -> Dict[str, Any]:
        return {
            "avg_is_return": 0.0,
            "avg_oos_return": 0.0,
            "wfe": 0.0,
            "avg_oos_sharpe": 0.0,
            "avg_oos_profit_factor": 0.0,
            "windows_profitable": 0,
            "total_windows": 0,
        }

    @staticmethod
    def _print_summary(summary: Dict[str, Any]) -> None:
        wfe = summary["wfe"]
        if wfe > 0.5:
            wfe_label = "GOOD"
        elif wfe > 0.3:
            wfe_label = "ACCEPTABLE"
        else:
            wfe_label = "OVERFIT"

        print(f"\n{'=' * 65}")
        print("=== SUMMARY ===")
        print(f"Avg IS Return:  {summary['avg_is_return'] * 100:.1f}%")
        print(f"Avg OOS Return: {summary['avg_oos_return'] * 100:.1f}%")
        print(f"WFE: {wfe:.2f} ({wfe_label})")
        print(f"Avg OOS Sharpe:        {summary['avg_oos_sharpe']:.2f}")
        print(f"Avg OOS Profit Factor: {summary['avg_oos_profit_factor']:.2f}")
        print(f"OOS Windows Profitable: {summary['windows_profitable']}/{summary['total_windows']}")
        print(f"{'=' * 65}")


# ---------------------------------------------------------------------------
# Result serialisation
# ---------------------------------------------------------------------------


def _serialise_result(r: BacktestResult) -> dict:
    """Convert a BacktestResult to a JSON-safe dict (skip equity_curve for brevity)."""
    return {
        "symbol": r.symbol,
        "start_date": r.start_date,
        "end_date": r.end_date,
        "total_trades": r.total_trades,
        "win_rate": round(r.win_rate, 4),
        "profit_factor": round(min(r.profit_factor, 999.0), 3),
        "sharpe_ratio": round(r.sharpe_ratio, 3),
        "total_return_pct": round(r.total_return_pct, 6),
        "max_drawdown_pct": round(r.max_drawdown_pct, 4),
    }


def save_results(
    result: Dict[str, Any],
    symbol: str,
    interval: str,
    adaptive_regime: bool = False,
    volume_filter: bool = False,
    mtf_filter: bool = False,
) -> Path:
    """Persist walk-forward results to JSON."""
    engine_root = Path(__file__).parent.parent
    results_dir = engine_root / "backtest" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Build suffix: _adaptive, _volume, or _adaptive_volume
    suffix_parts = []
    if adaptive_regime:
        suffix_parts.append("adaptive")
    if volume_filter:
        suffix_parts.append("volume")
    if mtf_filter:
        suffix_parts.append("mtf")
    suffix = "_" + "_".join(suffix_parts) if suffix_parts else ""
    filename = f"WF_{symbol}_{interval}{suffix}_walk_forward.json"
    out_path = results_dir / filename

    payload = {
        "symbol": symbol,
        "interval": interval,
        "generated": datetime.now().isoformat(),
        "summary": result["summary"],
        "windows": [],
    }

    for w in result["windows"]:
        payload["windows"].append(
            {
                "window": w["window"],
                "train_period": w["train_period"],
                "test_period": w["test_period"],
                "train_bars": w["train_bars"],
                "test_bars": w["test_bars"],
                "best_params": w["best_params"],
                "is_result": _serialise_result(w["is_result"]),
                "oos_result": _serialise_result(w["oos_result"]),
            }
        )

    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\nResults saved to: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Programmatic entry point for experiment search
# ---------------------------------------------------------------------------


def run_walk_forward_for_params(
    symbol: str = "MES",
    timeframe: str = "1h",
    stc_os: int = 15,
    stc_ob: int = 83,
    stop_atr_mult: float = 0.50,
    t1_atr_mult: float = 1.00,
    regime_required: int = 4,
    start: str = "2024-06-01",
    end: str = "2026-03-27",
    train_months: int = 6,
    test_months: int = 3,
    capital: float = 10_000.0,
) -> dict:
    """
    Run walk-forward validation for a fixed parameter set.

    Unlike the full WalkForwardValidator (which grid-searches IS to find best params),
    this function applies the given params directly to every OOS window without IS
    optimisation.  This is appropriate for an experiment search loop where we want
    to evaluate a specific candidate config end-to-end.

    Returns a dict with keys:
        wfe, pf_insample, pf_walkforward, sharpe_walkforward,
        trade_count, window_months, windows_profitable, total_windows
    """
    from backtest.data_loader import BacktestDataLoader
    from backtest.optimizer import _run_with_params

    # Map experiment naming convention → optimizer naming convention
    params = {
        "stc_oversold": stc_os,
        "stc_overbought": stc_ob,
        "atr_stop_mult": stop_atr_mult,
        "atr_target_mult": t1_atr_mult,
        "regime_filter": regime_required > 0,
    }

    # Load price data
    loader = BacktestDataLoader()
    df = loader.load(symbol, start, end, timeframe)
    if df is None or df.empty:
        return {
            "wfe": 0.0,
            "pf_insample": 0.0,
            "pf_walkforward": 0.0,
            "sharpe_walkforward": 0.0,
            "trade_count": 0,
            "window_months": test_months,
            "windows_profitable": 0,
            "total_windows": 0,
            "error": "no_data",
        }

    multiplier = loader.get_multiplier(symbol)

    # Generate windows using the validator's machinery
    validator = WalkForwardValidator(
        train_months=train_months,
        test_months=test_months,
        step_months=test_months,
    )
    windows_spec = validator.generate_windows(df, symbol)

    if not windows_spec:
        return {
            "wfe": 0.0,
            "pf_insample": 0.0,
            "pf_walkforward": 0.0,
            "sharpe_walkforward": 0.0,
            "trade_count": 0,
            "window_months": test_months,
            "windows_profitable": 0,
            "total_windows": 0,
            "error": "no_windows",
        }

    results_windows: List[Dict[str, Any]] = []
    total_oos_trades = 0

    for win in windows_spec:
        df_train = df[(df.index >= win["train_start"]) & (df.index < win["train_end"])].copy()
        df_test = df[(df.index >= win["test_start"]) & (df.index <= win["test_end"])].copy()

        is_result = _run_with_params(df_train, multiplier, capital, **params)
        oos_result = _run_with_params(df_test, multiplier, capital, **params)

        if is_result is None or oos_result is None:
            continue

        total_oos_trades += oos_result.total_trades
        results_windows.append(
            {
                "window": win["window_num"],
                "is_result": is_result,
                "oos_result": oos_result,
            }
        )

    if not results_windows:
        return {
            "wfe": 0.0,
            "pf_insample": 0.0,
            "pf_walkforward": 0.0,
            "sharpe_walkforward": 0.0,
            "trade_count": 0,
            "window_months": test_months,
            "windows_profitable": 0,
            "total_windows": len(windows_spec),
            "error": "no_valid_windows",
        }

    summary = validator._compute_summary(results_windows)

    avg_is_pf = float(np.mean([min(w["is_result"].profit_factor, 999.0) for w in results_windows]))
    avg_oos_pf = summary["avg_oos_profit_factor"]
    avg_oos_sharpe = summary["avg_oos_sharpe"]

    return {
        "wfe": summary["wfe"],
        "pf_insample": round(avg_is_pf, 4),
        "pf_walkforward": round(avg_oos_pf, 4),
        "sharpe_walkforward": round(avg_oos_sharpe, 4),
        "trade_count": total_oos_trades,
        "window_months": test_months,
        "windows_profitable": summary["windows_profitable"],
        "total_windows": summary["total_windows"],
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="JARVIS TRADER -- Walk-Forward Validation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--symbol", default="SPY", help="Symbol to validate")
    parser.add_argument("--interval", default="1h", help="Data interval (1d, 1h, etc.)")
    parser.add_argument("--start", default="2024-06-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-03-27", help="End date (YYYY-MM-DD)")
    parser.add_argument("--train-months", type=int, default=6, help="Training window (months)")
    parser.add_argument("--test-months", type=int, default=3, help="Testing window (months)")
    parser.add_argument(
        "--step-months", type=int, default=3, help="Step size between windows (months)"
    )
    parser.add_argument("--capital", type=float, default=10_000.0, help="Initial capital")
    parser.add_argument("--full-grid", action="store_true", help="Use full parameter grid (slower)")
    parser.add_argument(
        "--adaptive-regime", action="store_true", help="Use regime-adaptive STC thresholds per bar"
    )
    parser.add_argument(
        "--volume-filter", action="store_true", help="Block entries on below-average volume bars"
    )
    parser.add_argument(
        "--mtf-filter",
        action="store_true",
        help="Apply 4h MTF confirmation filter to block counter-trend entries",
    )
    args = parser.parse_args()

    # ── Load primary (1h) data ─────────────────────────────────────────────
    loader = BacktestDataLoader()
    print(f"Loading {args.symbol} ({args.interval}) from {args.start} to {args.end}...")

    df = loader.load(args.symbol, args.start, args.end, args.interval)
    if df is None or df.empty:
        print(f"ERROR: No data loaded for {args.symbol}")
        return

    multiplier = loader.get_multiplier(args.symbol)

    # ── Load daily data for MTF filter ────────────────────────────────────
    df_daily: Optional[pd.DataFrame] = None
    if args.mtf_filter:
        print(f"Loading {args.symbol} daily data for MTF filter...")
        df_daily = loader.load(args.symbol, args.start, args.end, "1d")
        if df_daily is None or df_daily.empty:
            print("[MTF] WARNING: daily data unavailable, MTF filter will be disabled.")
            df_daily = None

    # ── Run walk-forward validation ────────────────────────────────────────
    validator = WalkForwardValidator(
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
    )

    result = validator.run(
        df=df,
        symbol=args.symbol,
        multiplier=multiplier,
        capital=args.capital,
        fast=not args.full_grid,
        adaptive_regime=args.adaptive_regime,
        volume_filter=args.volume_filter,
        mtf_filter=args.mtf_filter,
        df_daily=df_daily,
    )

    # ── Save results ───────────────────────────────────────────────────────
    out_path = save_results(
        result,
        args.symbol,
        args.interval,
        adaptive_regime=args.adaptive_regime,
        volume_filter=args.volume_filter,
        mtf_filter=args.mtf_filter,
    )
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
