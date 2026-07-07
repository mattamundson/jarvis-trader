"""Dollar-neutral cross-sectional portfolio backtester (R3/T13).

The single-instrument ``Backtester`` cannot represent a long-top / short-bottom
basket held simultaneously, so this is a purpose-built portfolio simulator. It
takes a close-price panel + signal params, forms dollar-neutral weights each
rebalance from cross-sectional momentum, holds for ``hold_bars``, and books the
realized net portfolio return per period as one "trade". It returns the SAME
metric surface the gate consumes (``profit_factor``, ``max_drawdown_pct``,
``sharpe_ratio``, ``total_trades``, ``trades[]``, ``equity_curve``) so the
discovery driver can feed it straight into the gate-v2 evaluation unchanged.

No look-ahead: the book at bar ``i`` uses momentum computed from prices at or
before ``i`` and earns the return realized from ``i`` to ``i + hold_bars``.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from analysis.cross_sectional import (
    compute_dispersion,
    compute_xs_momentum,
    dollar_neutral_weights,
)

DEFAULT_COST_BPS = 2.0  # per unit of gross turnover, in basis points of capital


def _max_drawdown_pct(curve: list[float]) -> float:
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def _profit_factor(pnls: list[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if losses > 0:
        return gains / losses
    return float("inf") if gains > 0 else 0.0


def temporal_split_verdict(
    price_panel: pd.DataFrame,
    lookback: int,
    top_k: int = 1,
    hold_bars: int = 1,
    cost_bps: float = DEFAULT_COST_BPS,
    n_segments: int = 2,
    dispersion_min: Optional[float] = None,
) -> dict:
    """Chronological H1/H2(/Hn) split -- the MANDATORY non-stationarity guard.

    The spread campaign proved a pooled bootstrap happily passes a non-stationary
    edge whose entire profit is back-loaded into one era. So an edge is only STRONG
    if EVERY chronological segment is independently profitable (with trades). A
    segment that loses -> FAIL, no matter how good the pooled record looks. Each
    segment is backtested in isolation (its own warmup), so there is no leakage of
    one era's parameters into another.
    """
    n = len(price_panel)
    seg_len = n // max(n_segments, 1)
    segments: list[dict] = []
    for k in range(n_segments):
        lo = k * seg_len
        hi = n if k == n_segments - 1 else (k + 1) * seg_len
        sub = price_panel.iloc[lo:hi]
        r = run_xs_portfolio_backtest(
            sub, lookback, top_k, hold_bars, cost_bps, dispersion_min=dispersion_min
        )
        segments.append(
            {
                "segment": k + 1,
                "total_trades": r["total_trades"],
                "profit_factor": r["profit_factor"],
                "total_return_pct": r["total_return_pct"],
            }
        )
    rets = [s["total_return_pct"] for s in segments]
    all_profitable = bool(segments) and all(
        s["total_trades"] > 0 and s["total_return_pct"] > 0 for s in segments
    )
    return {
        "n_segments": n_segments,
        "segments": segments,
        "all_profitable": all_profitable,
        "verdict": "STRONG" if all_profitable else "FAIL",
        "min_segment_return_pct": min(rets) if rets else 0.0,
    }


def run_xs_portfolio_backtest(
    price_panel: pd.DataFrame,
    lookback: int,
    top_k: int = 1,
    hold_bars: int = 1,
    cost_bps: float = DEFAULT_COST_BPS,
    capital: float = 100_000.0,
    dispersion_min: Optional[float] = None,
    periods_per_year: int = 252,
) -> dict:
    """Simulate the dollar-neutral cross-sectional book; return the gate surface.

    Rebalances every ``hold_bars`` bars starting after the ``lookback`` warmup.
    ``cost_bps`` is charged on gross turnover (the L1 change in weights, including
    the open from / unwind to flat). ``dispersion_min`` optionally flattens the
    book on bars whose cross-sectional dispersion is below the threshold (the
    regime filter -- momentum tends to pay only when the basket is spreading out).
    """
    cols = list(price_panel.columns)
    n = len(price_panel)
    empty = {
        "trades": [],
        "total_trades": 0,
        "profit_factor": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe_ratio": 0.0,
        "total_return_pct": 0.0,
        "win_rate": 0.0,
        "equity_curve": [capital],
    }
    if n <= lookback + hold_bars or len(cols) < 2 * top_k:
        return empty

    mom = compute_xs_momentum(price_panel, lookback)
    weights = dollar_neutral_weights(mom, top_k)
    if dispersion_min is not None:
        disp = compute_dispersion(price_panel)
        weights.loc[disp < dispersion_min] = 0.0

    times = price_panel.index
    prev_w = pd.Series(0.0, index=cols)
    equity = capital
    curve = [capital]
    trades: list[dict] = []
    cost_rate = cost_bps / 10_000.0

    i = lookback
    while i + hold_bars < n:
        w = weights.iloc[i]
        turnover = float((w - prev_w).abs().sum())
        # realized hold-period return of the book (sum of weighted per-leg returns).
        period_ret = 0.0
        for s in cols:
            ws = w[s]
            if ws != 0.0:
                p0 = price_panel[s].iloc[i]
                p1 = price_panel[s].iloc[i + hold_bars]
                period_ret += ws * (p1 / p0 - 1.0)
        net = period_ret - turnover * cost_rate
        pnl = equity * net
        equity += pnl
        curve.append(equity)
        trades.append(
            {
                "entry_time": str(times[i]),
                "exit_time": str(times[i + hold_bars]),
                "ret": net,
                "pnl": pnl,
            }
        )
        prev_w = w
        i += hold_bars

    if not trades:
        return empty

    rets = [t["ret"] for t in trades]
    pnls = [t["pnl"] for t in trades]
    if len(rets) > 1 and np.std(rets, ddof=1) > 0:
        ppy = periods_per_year / hold_bars
        sharpe = float(np.mean(rets) / np.std(rets, ddof=1) * np.sqrt(ppy))
    else:
        sharpe = 0.0

    return {
        "trades": trades,
        "total_trades": len(trades),
        "profit_factor": _profit_factor(pnls),
        "max_drawdown_pct": _max_drawdown_pct(curve),
        "sharpe_ratio": sharpe,
        "total_return_pct": equity / capital - 1.0,
        "win_rate": sum(1 for p in pnls if p > 0) / len(pnls),
        "equity_curve": curve,
    }
