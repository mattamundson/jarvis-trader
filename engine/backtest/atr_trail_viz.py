"""Shared, dependency-light data prep for ATR-trail trade visualization.

Pure pandas/numpy (no matplotlib, no FastAPI) so both the offline plot script
(``plot_atr_trail_trades.py``) and the dashboard endpoint
(``/backtest/atr-trail/trades``) reuse one tested trade reconstruction.

The strategy is the TOS ``ATRTrailingStopLE/SE`` flip: enter on the trail flip,
exit on the opposite flip. P&L is net of the same commission + slippage the
backtest uses.
"""

from __future__ import annotations

import math

import pandas as pd

from backtest.indicators import atr_trailing_stop

MULTIPLIERS = {"MES": 5.0, "ES": 50.0, "MNQ": 2.0, "MCL": 100.0, "MGC": 10.0}
TICK = {"MES": 0.25, "ES": 0.25, "MNQ": 0.25, "MCL": 0.01, "MGC": 0.1}
COMMISSION = 0.62  # $/round-trip
SLIPPAGE_TICKS = 1.0  # per side


def _round_trip_cost(symbol: str) -> float:
    mult = MULTIPLIERS.get(symbol, 1.0)
    return COMMISSION + 2 * SLIPPAGE_TICKS * TICK.get(symbol, 0.25) * mult


def reconstruct_flip_trades(
    df: pd.DataFrame, symbol: str = "MES", period: int = 5, factor: float = 3.5
) -> list[dict]:
    """Flip-to-flip trades for the ATR trailing stop. Pure; needs a DatetimeIndex.

    Each trade dict carries entry/exit timestamps (pd.Timestamp), prices,
    direction (+1 long / -1 short), and pnl in points and dollars (net of cost).
    """
    trail, state = atr_trailing_stop(df["high"], df["low"], df["close"], period=period, factor=factor)
    mult = MULTIPLIERS.get(symbol, 1.0)
    cost = _round_trip_cost(symbol)
    close = df["close"]
    trades: list[dict] = []
    open_t: dict | None = None
    for i in range(len(df)):
        s = state.iloc[i]
        if pd.isna(s):
            continue
        prev = state.iloc[i - 1] if i > 0 else float("nan")
        if not pd.isna(prev) and s != prev:  # a flip
            px = float(close.iloc[i])
            if open_t is not None:
                d = open_t["dir"]
                pnl_pts = (px - open_t["entry_px"]) * d
                trades.append({
                    **open_t,
                    "exit_time": df.index[i],
                    "exit_px": px,
                    "pnl_pts": round(pnl_pts, 4),
                    "pnl_usd": round(pnl_pts * mult - cost, 2),
                })
            open_t = {"entry_time": df.index[i], "entry_px": px, "dir": 1 if s == 1.0 else -1}
    return trades


def _unix(ts: pd.Timestamp) -> int:
    return int(pd.Timestamp(ts).timestamp())


def compute_atr_trail_viz(
    df: pd.DataFrame,
    symbol: str = "MES",
    period: int = 5,
    factor: float = 3.5,
    max_points: int = 3000,
) -> dict:
    """JSON-ready payload for the dashboard: price, trail (+state), trades, equity.

    Downsamples the price/trail series to ``max_points`` for a light payload.
    Timestamps are UNIX seconds (lightweight-charts ``time``).
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("compute_atr_trail_viz requires a DatetimeIndex")

    trail, state = atr_trailing_stop(df["high"], df["low"], df["close"], period=period, factor=factor)
    n = len(df)
    stride = max(1, math.ceil(n / max_points))
    idx = range(0, n, stride)

    price = [{"t": _unix(df.index[i]), "c": float(df["close"].iloc[i])} for i in idx]
    trail_pts = [
        {"t": _unix(df.index[i]), "v": float(trail.iloc[i]), "s": int(state.iloc[i])}
        for i in idx
        if not pd.isna(trail.iloc[i])
    ]

    raw = reconstruct_flip_trades(df, symbol, period, factor)
    trades = [
        {
            "entry_t": _unix(t["entry_time"]), "entry_px": t["entry_px"],
            "exit_t": _unix(t["exit_time"]), "exit_px": t["exit_px"],
            "dir": t["dir"], "pnl_usd": t["pnl_usd"], "pnl_pts": t["pnl_pts"],
        }
        for t in raw
    ]
    equity, cum = [], 0.0
    for t in raw:
        cum += t["pnl_usd"]
        equity.append({"t": _unix(t["exit_time"]), "v": round(cum, 2)})

    net = round(cum, 2)
    wins = sum(1 for t in raw if t["pnl_usd"] > 0)
    return {
        "symbol": symbol, "period": period, "factor": factor,
        "n_trades": len(raw),
        "win_rate": round(wins / len(raw), 4) if raw else 0.0,
        "net_usd": net,
        "bars": n,
        "price": price,
        "trail": trail_pts,
        "trades": trades,
        "equity": equity,
    }
