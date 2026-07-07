"""
JARVIS TRADER — ORB Backtester
===============================
Simulates Opening Range Breakout trading on 1-hour bars.

Trade simulation rules:
  - Entry at close of signal bar (market-on-close approximation)
  - Stop: OR Low (long) / OR High (short)
  - T1: 1× OR range extension  → partial exit 50% of position
  - T2: 2× OR range extension  → exit remaining 50%
  - After T1 hit: move stop to breakeven
  - Max 1 open position per session (first valid signal only)
  - Session end (15:59 bar close): force exit any open position at close
  - Slippage: 1 tick ($1.25 per contract for MES) each way
  - Commission: $0.62 per contract per leg (IB Tiered for micro futures)

Contract specs (MES):
  - Tick size: 0.25 index points
  - Tick value: $1.25
  - Multiplier: $5 per point

Usage:
  result = run_orb_backtest(df, symbol="MES")
  print(result.summary())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .orb_signals import generate_orb_signals

logger = logging.getLogger("orb_backtester")

# ── MES Contract Specs ────────────────────────────────────────────────────────

CONTRACT_SPECS: Dict[str, Dict[str, float]] = {
    "MES": {
        "multiplier": 5.0,
        "tick_size": 0.25,
        "tick_value": 1.25,
        "commission": 0.62,  # per contract per leg (IB Tiered micro)
        "slippage_ticks": 1,  # 1 tick = 0.25 pts = $1.25 slippage per leg
    },
    "MCL": {
        "multiplier": 100.0,
        "tick_size": 0.01,
        "tick_value": 1.00,
        "commission": 0.85,
        "slippage_ticks": 1,
    },
    "MNQ": {
        "multiplier": 2.0,
        "tick_size": 0.25,
        "tick_value": 0.50,
        "commission": 0.62,
        "slippage_ticks": 2,
    },
    "M2K": {
        "multiplier": 5.0,
        "tick_size": 0.10,
        "tick_value": 0.50,
        "commission": 0.62,
        "slippage_ticks": 1,
    },
}

DEFAULT_SPEC = {
    "multiplier": 5.0,
    "tick_size": 0.25,
    "tick_value": 1.25,
    "commission": 0.62,
    "slippage_ticks": 1,
}


# ── Trade Record ─────────────────────────────────────────────────────────────


@dataclass
class ORBTrade:
    symbol: str
    entry_date: str
    exit_date: str
    side: str  # "long" | "short"
    entry_price: float
    exit_price: float
    contracts: int
    exit_reason: str  # "target_1" | "target_2" | "stop" | "eod" | "breakeven_stop"
    or_high: float
    or_low: float
    or_range: float
    pnl: float  # Net P&L after commissions and slippage
    mae: float = 0.0  # Maximum Adverse Excursion
    mfe: float = 0.0  # Maximum Favorable Excursion

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry_date": self.entry_date,
            "exit_date": self.exit_date,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "contracts": self.contracts,
            "exit_reason": self.exit_reason,
            "or_high": self.or_high,
            "or_low": self.or_low,
            "or_range": self.or_range,
            "pnl": self.pnl,
            "mae": self.mae,
            "mfe": self.mfe,
        }


# ── Backtest Result ───────────────────────────────────────────────────────────


@dataclass
class ORBBacktestResult:
    symbol: str
    interval: str
    start_date: str
    end_date: str
    trades: List[ORBTrade] = field(default_factory=list)

    # Computed on demand
    _summary: Optional[Dict[str, Any]] = field(default=None, repr=False, compare=False)

    def summary(self) -> Dict[str, Any]:
        if self._summary is not None:
            return self._summary

        if not self.trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "net_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "max_drawdown": 0.0,
                "sharpe": 0.0,
                "total_return_pct": 0.0,
                "avg_rr": 0.0,
                "long_trades": 0,
                "short_trades": 0,
                "stop_pct": 0.0,
                "t1_pct": 0.0,
                "t2_pct": 0.0,
                "eod_pct": 0.0,
            }

        pnls = [t.pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        net_pnl = sum(pnls)

        win_rate = len(wins) / len(pnls)
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = np.mean(losses) if losses else 0.0

        # Drawdown from equity curve
        equity = np.cumsum(pnls)
        rolling_max = np.maximum.accumulate(equity)
        drawdowns = equity - rolling_max
        max_drawdown = float(abs(min(drawdowns))) if len(drawdowns) > 0 else 0.0

        # Sharpe (annualised, assume 252 trading days × ~2 trades/day = 504)
        if len(pnls) > 1:
            pnl_std = float(np.std(pnls, ddof=1))
            pnl_mean = float(np.mean(pnls))
            sharpe = (pnl_mean / pnl_std * np.sqrt(252)) if pnl_std > 0 else 0.0
        else:
            sharpe = 0.0

        exit_counts = {}
        for t in self.trades:
            exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

        n = len(self.trades)
        self._summary = {
            "total_trades": n,
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 3),
            "net_pnl": round(net_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe": round(sharpe, 3),
            "long_trades": sum(1 for t in self.trades if t.side == "long"),
            "short_trades": sum(1 for t in self.trades if t.side == "short"),
            "stop_pct": round(exit_counts.get("stop", 0) / n, 4),
            "t1_pct": round(
                (exit_counts.get("target_1", 0) + exit_counts.get("partial_t1", 0)) / n, 4
            ),
            "t2_pct": round(exit_counts.get("target_2", 0) / n, 4),
            "eod_pct": round(exit_counts.get("eod", 0) / n, 4),
            "breakeven_pct": round(exit_counts.get("breakeven_stop", 0) / n, 4),
        }
        return self._summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "summary": self.summary(),
            "trades": [t.to_dict() for t in self.trades],
        }


# ── Core Simulation ───────────────────────────────────────────────────────────


def _slip(price: float, side: str, is_entry: bool, spec: Dict[str, float]) -> float:
    """Apply slippage to a fill price."""
    tick = spec["tick_size"]
    n = spec["slippage_ticks"]
    delta = tick * n
    if side == "long":
        return price + delta if is_entry else price - delta
    else:
        return price - delta if is_entry else price + delta


def _commission(contracts: int, legs: int, spec: Dict[str, float]) -> float:
    return spec["commission"] * contracts * legs


def _pnl(entry: float, exit_p: float, side: str, contracts: int, spec: Dict[str, float]) -> float:
    raw = (exit_p - entry) * spec["multiplier"] * contracts
    if side == "short":
        raw = -raw
    comm = _commission(contracts, 2, spec)
    return raw - comm


def run_orb_backtest(
    df: pd.DataFrame,
    symbol: str = "MES",
    contracts: int = 1,
    volume_filter: bool = True,
    regime_filter: bool = False,
    min_or_range_pct: float = 0.0008,
) -> ORBBacktestResult:
    """
    Run ORB backtest on a prepared 1-hour OHLCV DataFrame.

    Applies partial exits: 50% at T1, 50% at T2.
    After T1 hit, moves stop to breakeven.
    EOD exit at 15:59 bar if still open.

    Parameters
    ----------
    df : DataFrame with DatetimeIndex and open/high/low/close/volume columns.
    symbol : instrument symbol.
    contracts : number of contracts per trade.
    volume_filter : require volume confirmation on breakout bar.
    regime_filter : block EXHAUSTED/COMPRESSION entries (requires 'regime' col).
    min_or_range_pct : minimum OR range as pct of price.

    Returns
    -------
    ORBBacktestResult with trades list and summary stats.
    """
    spec = CONTRACT_SPECS.get(symbol, DEFAULT_SPEC)

    df = generate_orb_signals(
        df,
        symbol=symbol,
        volume_filter=volume_filter,
        regime_filter=regime_filter,
        min_or_range_pct=min_or_range_pct,
    )

    trades: List[ORBTrade] = []

    # Detect RTH hours for EOD exit
    idx = df.index
    if hasattr(idx, "tz") and idx.tz is not None:
        eastern_hours = pd.Series(idx.tz_convert("America/New_York").hour, index=df.index)
    else:
        eastern_hours = pd.Series(idx.hour, index=df.index)

    # Track open position state
    open_pos: Optional[Dict[str, Any]] = None

    for i in range(len(df)):
        bar_high = float(df["high"].iloc[i])
        bar_low = float(df["low"].iloc[i])
        bar_close = float(df["close"].iloc[i])
        bar_time = str(df.index[i])
        bar_hour = int(eastern_hours.iloc[i])

        # EOD: force-close any open position at 15:xx bar close
        if open_pos is not None and bar_hour >= 15:
            exit_p = _slip(bar_close, open_pos["side"], False, spec)
            remaining = open_pos.get("contracts_remaining", contracts)
            pnl = _pnl(open_pos["entry"], exit_p, open_pos["side"], remaining, spec)

            trades.append(
                ORBTrade(
                    symbol=symbol,
                    entry_date=open_pos["entry_date"],
                    exit_date=bar_time,
                    side=open_pos["side"],
                    entry_price=open_pos["entry"],
                    exit_price=round(exit_p, 4),
                    contracts=remaining,
                    exit_reason="eod",
                    or_high=open_pos["or_high"],
                    or_low=open_pos["or_low"],
                    or_range=open_pos["or_range"],
                    pnl=round(pnl + open_pos.get("partial_pnl", 0.0), 2),
                )
            )
            open_pos = None
            continue

        # Manage open position
        if open_pos is not None:
            side = open_pos["side"]
            entry = open_pos["entry"]
            stop = open_pos["stop"]
            t1 = open_pos["t1"]
            t2 = open_pos["t2"]
            remaining = open_pos.get("contracts_remaining", contracts)

            # Check stop first
            stop_hit = (side == "long" and bar_low <= stop) or (
                side == "short" and bar_high >= stop
            )
            if stop_hit:
                exit_p = _slip(stop, side, False, spec)
                pnl = _pnl(entry, exit_p, side, remaining, spec)
                reason = "breakeven_stop" if open_pos.get("at_breakeven") else "stop"

                trades.append(
                    ORBTrade(
                        symbol=symbol,
                        entry_date=open_pos["entry_date"],
                        exit_date=bar_time,
                        side=side,
                        entry_price=entry,
                        exit_price=round(exit_p, 4),
                        contracts=remaining,
                        exit_reason=reason,
                        or_high=open_pos["or_high"],
                        or_low=open_pos["or_low"],
                        or_range=open_pos["or_range"],
                        pnl=round(pnl + open_pos.get("partial_pnl", 0.0), 2),
                    )
                )
                open_pos = None
                continue

            # Check T1 (partial exit 50%)
            t1_contracts = max(1, remaining // 2)
            t1_hit = (side == "long" and bar_high >= t1) or (side == "short" and bar_low <= t1)
            if t1_hit and not open_pos.get("t1_done"):
                exit_p = _slip(t1, side, False, spec)
                partial_pnl = _pnl(entry, exit_p, side, t1_contracts, spec)

                open_pos["t1_done"] = True
                open_pos["contracts_remaining"] = remaining - t1_contracts
                open_pos["partial_pnl"] = open_pos.get("partial_pnl", 0.0) + partial_pnl
                open_pos["stop"] = entry  # Move stop to breakeven
                open_pos["at_breakeven"] = True

                # Log partial exit but don't close the position yet
                logger.debug(f"{symbol} T1 hit @ {exit_p:.2f} partial_pnl=${partial_pnl:.2f}")

                # If remaining contracts == 0 after T1, close
                if open_pos["contracts_remaining"] <= 0:
                    trades.append(
                        ORBTrade(
                            symbol=symbol,
                            entry_date=open_pos["entry_date"],
                            exit_date=bar_time,
                            side=side,
                            entry_price=entry,
                            exit_price=round(exit_p, 4),
                            contracts=t1_contracts,
                            exit_reason="target_1",
                            or_high=open_pos["or_high"],
                            or_low=open_pos["or_low"],
                            or_range=open_pos["or_range"],
                            pnl=round(open_pos["partial_pnl"], 2),
                        )
                    )
                    open_pos = None
                    continue

            # Check T2 (full remaining exit)
            if open_pos is not None:
                remaining2 = open_pos.get("contracts_remaining", contracts)
                t2_hit = (side == "long" and bar_high >= t2) or (side == "short" and bar_low <= t2)
                if t2_hit:
                    exit_p = _slip(t2, side, False, spec)
                    pnl = _pnl(entry, exit_p, side, remaining2, spec)

                    trades.append(
                        ORBTrade(
                            symbol=symbol,
                            entry_date=open_pos["entry_date"],
                            exit_date=bar_time,
                            side=side,
                            entry_price=entry,
                            exit_price=round(exit_p, 4),
                            contracts=remaining2,
                            exit_reason="target_2",
                            or_high=open_pos["or_high"],
                            or_low=open_pos["or_low"],
                            or_range=open_pos["or_range"],
                            pnl=round(pnl + open_pos.get("partial_pnl", 0.0), 2),
                        )
                    )
                    open_pos = None
                    continue

        # New entry — only if no open position
        if open_pos is None:
            sig = str(df["ORB_signal"].iloc[i])
            if sig in ("LONG_ENTRY", "SHORT_ENTRY"):
                side = "long" if sig == "LONG_ENTRY" else "short"
                entry_p = _slip(bar_close, side, True, spec)
                stop_p = float(df["orb_stop"].iloc[i])
                t1_p = float(df["orb_target_1"].iloc[i])
                t2_p = float(df["orb_target_2"].iloc[i])
                or_h = float(df["or_high"].iloc[i])
                or_l = float(df["or_low"].iloc[i])
                or_r = float(df["or_range"].iloc[i])

                open_pos = {
                    "side": side,
                    "entry": entry_p,
                    "entry_date": bar_time,
                    "stop": stop_p,
                    "t1": t1_p,
                    "t2": t2_p,
                    "or_high": or_h,
                    "or_low": or_l,
                    "or_range": or_r,
                    "contracts_remaining": contracts,
                    "t1_done": False,
                    "at_breakeven": False,
                    "partial_pnl": 0.0,
                }
                logger.debug(
                    f"{symbol} {side.upper()} entry @ {entry_p:.2f} | "
                    f"stop={stop_p:.2f} T1={t1_p:.2f} T2={t2_p:.2f} OR=[{or_l:.2f},{or_h:.2f}]"
                )

    # Force-close any position still open at end of data
    if open_pos is not None:
        last_close = float(df["close"].iloc[-1])
        exit_p = _slip(last_close, open_pos["side"], False, spec)
        remaining = open_pos.get("contracts_remaining", contracts)
        pnl = _pnl(open_pos["entry"], exit_p, open_pos["side"], remaining, spec)

        trades.append(
            ORBTrade(
                symbol=symbol,
                entry_date=open_pos["entry_date"],
                exit_date=str(df.index[-1]),
                side=open_pos["side"],
                entry_price=open_pos["entry"],
                exit_price=round(exit_p, 4),
                contracts=remaining,
                exit_reason="eod",
                or_high=open_pos["or_high"],
                or_low=open_pos["or_low"],
                or_range=open_pos["or_range"],
                pnl=round(pnl + open_pos.get("partial_pnl", 0.0), 2),
            )
        )

    start = str(df.index[0])
    end = str(df.index[-1])

    result = ORBBacktestResult(
        symbol=symbol,
        interval="1h",
        start_date=start,
        end_date=end,
        trades=trades,
    )

    s = result.summary()
    logger.info(
        f"ORB Backtest {symbol} {start[:10]}–{end[:10]}: "
        f"{s['total_trades']} trades | "
        f"WR={s['win_rate']:.1%} | "
        f"PF={s['profit_factor']:.2f} | "
        f"NetPnL=${s['net_pnl']:+.2f} | "
        f"MaxDD=${s['max_drawdown']:.2f}"
    )
    return result
