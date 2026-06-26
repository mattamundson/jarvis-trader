"""The discovery funnel: smoke -> robustness, on the existing backtest engine.

Phase 2 (smoke): one full-sample backtest per candidate on its NATIVE timeframe
and instrument, default params, pre-cost; kill Sharpe < 0.5 or PF < 1.0 under
realistic cost. Phase 3 (robustness): walk-forward (IS grid -> OOS), the shared
`compute_gate_v2`, plus PBO across windows and a Deflated Sharpe deflated by the
GLOBAL trial count. Phase 4 (combinations) is layered after the pilot.

Only generic column-emitting generators (meanrev/donchian/saty/keltner/...) run
through `Backtester`. Strategies with dedicated engines (ORB, TPO) get their own
adapter later -- out of pilot scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd

from backtest.backtester import Backtester
from backtest.deflated_sharpe import deflated_sharpe_ratio
from backtest.factory.pbo import probability_of_backtest_overfitting
from backtest.factory.signal_adapter import build_signal_frame
from backtest.factory.strategy_card import StrategyCard
from backtest.wfo_lifecycle import OOSResult, compute_gate_v2

# Smoke-test kill thresholds.
SMOKE_MIN_SHARPE = 0.5
SMOKE_MIN_PF = 1.0
# Below this, there is no meaningful pre-cost metric to judge -> kill.
SMOKE_MIN_TRADES = 5
# Between SMOKE_MIN_TRADES and this, the strategy is low-frequency (e.g. a daily
# SMA cross fires ~15x in 33yr). That is NOT a reason to kill -- it is the nature
# of the strategy. Flag it `low_sample` and let robustness judge it honestly via
# the bootstrap PF-CI + DSR, which already price in small-sample uncertainty.
SMOKE_LOW_SAMPLE_TRADES = 30
# Realistic cost tier (matches COST_SWEEP_TIERS["realistic"]).
REALISTIC_COMMISSION = 0.62
REALISTIC_SLIPPAGE_TICKS = 2.0
# WFO geometry (matches the canonical per-strategy runners).
TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1
MIN_BARS_PER_SPLIT = 30


@dataclass
class BacktestMetrics:
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    total_trades: int


def backtest_once(
    card: StrategyCard,
    bars: pd.DataFrame,
    params: dict,
    symbol: str,
    multiplier: float,
    *,
    commission: float | None = None,
    slippage_ticks: float | None = None,
    capital: float = 50_000.0,
) -> BacktestMetrics:
    """Build signals from the card's generator and run one backtest."""
    df_sig = build_signal_frame(card.signal_ref, bars, params)
    bt = Backtester(
        initial_capital=capital,
        commission_per_contract=commission,
        slippage_ticks=slippage_ticks,
        trailing_stop=True,
    )
    res = bt.run(df_sig, symbol=symbol, multiplier=multiplier)
    return BacktestMetrics(
        profit_factor=float(res.profit_factor),
        sharpe_ratio=float(res.sharpe_ratio),
        max_drawdown_pct=float(res.max_drawdown_pct),
        total_trades=int(res.total_trades),
    )


def smoke_test(
    card: StrategyCard,
    bars: pd.DataFrame,
    symbol: str,
    multiplier: float,
) -> tuple[bool, dict]:
    """Pre-cost Sharpe gate, then a realistic-cost survival check.

    Returns (survives, metrics_dict). A card survives only if pre-cost Sharpe and
    PF clear the floor AND it still profits (PF > 1) under realistic cost.
    """
    pre = backtest_once(
        card,
        bars,
        card.default_params,
        symbol,
        multiplier,
        commission=0.0,
        slippage_ticks=0.0,
    )
    low_sample = pre.total_trades < SMOKE_LOW_SAMPLE_TRADES
    base = {
        "stage": "smoke",
        "pre_sharpe": pre.sharpe_ratio,
        "pre_pf": pre.profit_factor,
        "trades": pre.total_trades,
        "low_sample": low_sample,
    }
    # Too few trades to compute a trustworthy pre-cost metric at all.
    if pre.total_trades < SMOKE_MIN_TRADES:
        return False, {
            **base,
            "kill_reason": f"insufficient trades to evaluate (<{SMOKE_MIN_TRADES})",
        }
    # Kill only on a genuinely absent pre-cost edge -- NOT on low frequency.
    if pre.sharpe_ratio < SMOKE_MIN_SHARPE or pre.profit_factor < SMOKE_MIN_PF:
        return False, {**base, "kill_reason": "pre-cost sharpe/pf below floor"}
    post = backtest_once(
        card,
        bars,
        card.default_params,
        symbol,
        multiplier,
        commission=REALISTIC_COMMISSION,
        slippage_ticks=REALISTIC_SLIPPAGE_TICKS,
    )
    survives = post.profit_factor > SMOKE_MIN_PF
    return survives, {
        **base,
        "post_cost_pf": post.profit_factor,
        "post_cost_sharpe": post.sharpe_ratio,
        "kill_reason": None if survives else "does not survive realistic cost",
    }


def _windows(bars: pd.DataFrame) -> list[dict]:
    start, end = bars.index.min(), bars.index.max()
    out, cursor, wnum = [], start, 1
    while True:
        tr_s = cursor
        tr_e = tr_s + pd.DateOffset(months=TRAIN_MONTHS)
        te_s = tr_e
        te_e = te_s + pd.DateOffset(months=TEST_MONTHS)
        if te_s >= end:
            break
        te_e = min(te_e, end)
        n_tr = ((bars.index >= tr_s) & (bars.index < tr_e)).sum()
        n_te = ((bars.index >= te_s) & (bars.index <= te_e)).sum()
        if n_tr >= MIN_BARS_PER_SPLIT and n_te >= MIN_BARS_PER_SPLIT:
            out.append({"n": wnum, "tr_s": tr_s, "tr_e": tr_e, "te_s": te_s, "te_e": te_e})
            wnum += 1
        cursor += pd.DateOffset(months=STEP_MONTHS)
        if cursor >= end:
            break
    return out


def _grid(card: StrategyCard) -> list[dict]:
    if not card.param_grid:
        return [dict(card.default_params)]
    keys = list(card.param_grid)
    return [
        dict(zip(keys, combo, strict=True))
        for combo in product(*(card.param_grid[k] for k in keys))
    ]


def robustness_gauntlet(
    card: StrategyCard,
    bars: pd.DataFrame,
    symbol: str,
    multiplier: float,
    global_trial_count: int,
) -> dict:
    """Walk-forward + gate-v2 + PBO + globally-deflated Sharpe for one survivor."""
    windows = _windows(bars)
    grid = _grid(card)
    n_combos = len(grid)
    if not windows:
        return {"verdict": "FAIL", "reason": "insufficient data for WFO windows"}

    oos_results: list[OOSResult] = []

    for win in windows:
        df_tr = bars[(bars.index >= win["tr_s"]) & (bars.index < win["tr_e"])]
        df_te = bars[(bars.index >= win["te_s"]) & (bars.index <= win["te_e"])]

        # IS grid search -> champion by profit factor.
        best_pf, best_params = -1.0, None
        for params in grid:
            try:
                m = backtest_once(
                    card, df_tr, params, symbol, multiplier, commission=0.0, slippage_ticks=0.0
                )
            except Exception:
                continue
            pf = min(m.profit_factor, 5.0) if np.isfinite(m.profit_factor) else 5.0
            if m.total_trades >= 5 and pf > best_pf:
                best_pf, best_params = pf, params
        if best_params is None:
            continue

        try:
            oos = backtest_once(
                card,
                df_te,
                best_params,
                symbol,
                multiplier,
                commission=REALISTIC_COMMISSION,
                slippage_ticks=REALISTIC_SLIPPAGE_TICKS,
            )
        except Exception:
            continue

        oos_results.append(
            OOSResult(
                window_idx=win["n"],
                best_params=best_params,
                profit_factor=oos.profit_factor,
                max_drawdown_pct=oos.max_drawdown_pct,
                sharpe_ratio=oos.sharpe_ratio,
                total_trades=oos.total_trades,
            )
        )

    if not oos_results:
        return {"verdict": "FAIL", "reason": "no OOS windows produced trades"}

    # Fixed-params sweep (min PF across the grid on the full sample).
    fixed_pfs = []
    for params in grid:
        try:
            m = backtest_once(
                card,
                bars,
                params,
                symbol,
                multiplier,
                commission=REALISTIC_COMMISSION,
                slippage_ticks=REALISTIC_SLIPPAGE_TICKS,
            )
            if m.total_trades >= 5 and np.isfinite(m.profit_factor):
                fixed_pfs.append(m.profit_factor)
        except Exception:
            continue
    fixed_metrics = {"fixed_params_min_pf": float(min(fixed_pfs)) if fixed_pfs else 0.0}

    # Cost survival: champion at realistic vs pessimistic.
    cost_metrics = {
        "cost_survives_through": "realistic" if fixed_pfs and min(fixed_pfs) > 1.0 else "none"
    }

    # Shared gate-v2 (same function the canonical runners use).
    gate = compute_gate_v2(oos_results, n_combos, fixed_metrics, cost_metrics)

    # GLOBAL multiple-testing correction: re-deflate the mean OOS Sharpe by the
    # factory's TOTAL trial count, not just this card's grid.
    mean_sharpe = float(np.mean([r.sharpe_ratio for r in oos_results]))
    total_oos_trades = sum(r.total_trades for r in oos_results)
    dsr_global = deflated_sharpe_ratio(
        sharpe=mean_sharpe,
        n_trials=max(global_trial_count, n_combos),
        n_obs=max(total_oos_trades, 30),
    )
    dsr_global_val = (
        dsr_global.get("dsr", 0.0) if isinstance(dsr_global, dict) else float(dsr_global)
    )

    # PBO across windows: matrix of (windows x grid) IS profit-factor proxies.
    pbo_val = None
    if len(oos_results) >= 4 and n_combos >= 2:
        try:
            pf_matrix = _is_pf_matrix(card, bars, grid, symbol, multiplier)
            if pf_matrix is not None and pf_matrix.shape[0] >= 4:
                s = min(pf_matrix.shape[0] - (pf_matrix.shape[0] % 2), 10)
                if s >= 2:
                    pbo_val = probability_of_backtest_overfitting(pf_matrix, n_partitions=s).pbo
        except Exception:
            pbo_val = None

    gate["dsr_global"] = round(dsr_global_val, 6)
    gate["pbo"] = pbo_val
    gate["n_grid_combos"] = n_combos
    gate["global_trial_count"] = global_trial_count
    return gate


def _is_pf_matrix(card, bars, grid, symbol, multiplier) -> np.ndarray | None:
    """Per-window x per-combo PF proxy matrix for PBO (rows=windows, cols=combos)."""
    wins = _windows(bars)
    rows = []
    for win in wins:
        seg = bars[(bars.index >= win["tr_s"]) & (bars.index <= win["te_e"])]
        row = []
        for params in grid:
            try:
                m = backtest_once(
                    card, seg, params, symbol, multiplier, commission=0.0, slippage_ticks=0.0
                )
                row.append(m.profit_factor if np.isfinite(m.profit_factor) else 5.0)
            except Exception:
                row.append(0.0)
        rows.append(row)
    if not rows:
        return None
    return np.asarray(rows, dtype=float)
