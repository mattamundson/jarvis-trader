"""
JARVIS TRADER — VWAP Reversion Backtester
==========================================
Simulates VWAP Deviation Reversion trading on 1-hour bars.

Trade simulation rules:
  - Entry at close of signal bar (market-on-close approximation)
  - Stop: entry ± stop_mult × ATR
  - T1: VWAP (primary target) → exit full position
  - T2: opposite band (secondary target, if position still open past T1)
  - EOD exit: force-close at 15:59 bar (RTH close)
  - No partial exits — simple full exit at T1, T2, stop, or EOD
  - Slippage: 1 tick per leg
  - Commission: $0.62 per contract per leg

Simple full-exit model (no partial exits) because:
  - VWAP is the most likely mean-reversion target
  - Partial exits create "remainder" positions that typically stop at breakeven
  - Full exit at T1 with high win rate > partial exit with few T2 hits

Contract spec: same as orb_backtester.py (MES = $5/pt, 0.25 tick, $1.25/tick)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .vwap_signals import RTH_FINAL_HOUR, generate_vwap_signals

logger = logging.getLogger("vwap_backtester")

CONTRACT_SPECS: Dict[str, Dict[str, float]] = {
    "MES": {
        "multiplier": 5.0,
        "tick_size": 0.25,
        "tick_value": 1.25,
        "commission": 0.62,
        "slippage_ticks": 1,
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
}
DEFAULT_SPEC = CONTRACT_SPECS["MES"]


@dataclass
class VWAPTrade:
    symbol: str
    entry_date: str
    exit_date: str
    side: str
    entry_price: float
    exit_price: float
    contracts: int
    exit_reason: str  # "target_1" | "target_2" | "stop" | "eod"
    vwap_at_entry: float
    atr_at_entry: float
    pnl: float

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__.items())


@dataclass
class VWAPBacktestResult:
    symbol: str
    interval: str
    start_date: str
    end_date: str
    params: Dict[str, Any]
    trades: List[VWAPTrade] = field(default_factory=list)
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
            }

        pnls = [t.pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        net_pnl = sum(pnls)
        win_rate = len(wins) / len(pnls)
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0

        equity = np.cumsum(pnls)
        rolling_max = np.maximum.accumulate(equity)
        max_dd = float(abs(min(equity - rolling_max))) if len(pnls) > 0 else 0.0

        sharpe = 0.0
        if len(pnls) > 1:
            std = float(np.std(pnls, ddof=1))
            if std > 0:
                sharpe = round(float(np.mean(pnls)) / std * np.sqrt(252), 3)

        exit_counts: Dict[str, int] = {}
        for t in self.trades:
            exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1
        n = len(self.trades)

        self._summary = {
            "total_trades": n,
            "win_rate": round(win_rate, 4),
            "profit_factor": round(pf, 3) if pf != float("inf") else 99.0,
            "net_pnl": round(net_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "max_drawdown": round(max_dd, 2),
            "sharpe": sharpe,
            "long_trades": sum(1 for t in self.trades if t.side == "long"),
            "short_trades": sum(1 for t in self.trades if t.side == "short"),
            "t1_pct": round(exit_counts.get("target_1", 0) / n, 4),
            "t2_pct": round(exit_counts.get("target_2", 0) / n, 4),
            "stop_pct": round(exit_counts.get("stop", 0) / n, 4),
            "eod_pct": round(exit_counts.get("eod", 0) / n, 4),
        }
        return self._summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "params": self.params,
            "summary": self.summary(),
            "trades": [t.to_dict() for t in self.trades],
        }


def _slip(price: float, side: str, is_entry: bool, spec: Dict) -> float:
    tick = spec["tick_size"] * spec["slippage_ticks"]
    if side == "long":
        return price + tick if is_entry else price - tick
    return price - tick if is_entry else price + tick


def _pnl(entry: float, exit_p: float, side: str, contracts: int, spec: Dict) -> float:
    raw = (exit_p - entry) * spec["multiplier"] * contracts
    if side == "short":
        raw = -raw
    comm = spec["commission"] * contracts * 2  # 2 legs
    return raw - comm


def run_vwap_backtest(
    df: pd.DataFrame,
    symbol: str = "MES",
    contracts: int = 1,
    band_mult: float = 1.5,
    stop_mult: float = 0.5,
    atr_period: int = 14,
    require_reversal_bar: bool = True,
    regime_filter: bool = False,
    # SOTA execution-realism hardening (aligned with PR #592 shared Backtester)
    pessimistic_tie_breaker: bool = False,
    gap_stop_worst_fill: bool = False,
    volatility_scaled_slippage: bool = False,
    max_volume_pct: Optional[float] = None,
    initial_margin_per_contract: Optional[float] = None,
    initial_capital: float = 50_000.0,
) -> VWAPBacktestResult:
    """
    Run VWAP reversion backtest on a 1-hour OHLCV DataFrame.

    Full position exits: T1 (VWAP) → exit 100%, then stop/T2/EOD are irrelevant.
    Simple clean model — no partial exits.

    SOTA hardening (all optional, default False/None = unchanged behavior):
      pessimistic_tie_breaker: on a bar where BOTH the stop and a target are
        touched, assume the STOP was hit first (worst case) instead of the
        stop-first order below which is actually already conservative on
        order but optimistic on fill price. This overrides gap/direction
        inference.
      gap_stop_worst_fill: if the bar OPEN already violates the stop level
        (gap through the stop), fill at the worse of (bar_open, stop_price).
      volatility_scaled_slippage: scale slippage by current-bar ATR / trailing
        mean ATR (clamped 0.5x-4.0x) — wider fills during vol spikes.
      max_volume_pct: cap effective contracts at pct of bar volume and apply a
        quadratic POV impact surcharge on slippage.
      initial_margin_per_contract: cap contracts at floor(capital /
        margin_per_contract).
    """
    spec = CONTRACT_SPECS.get(symbol, DEFAULT_SPEC)
    params = {
        "band_mult": band_mult,
        "stop_mult": stop_mult,
        "atr_period": atr_period,
        "require_reversal_bar": require_reversal_bar,
        "regime_filter": regime_filter,
    }

    df = generate_vwap_signals(
        df,
        symbol=symbol,
        band_mult=band_mult,
        stop_mult=stop_mult,
        atr_period=atr_period,
        require_reversal_bar=require_reversal_bar,
        regime_filter=regime_filter,
    )

    trades: List[VWAPTrade] = []

    idx = df.index
    if hasattr(idx, "tz") and idx.tz is not None:
        eastern_hours = idx.tz_convert("America/New_York").hour
    else:
        eastern_hours = idx.hour

    highs = df["high"].to_numpy(dtype=float, copy=False)
    lows = df["low"].to_numpy(dtype=float, copy=False)
    closes = df["close"].to_numpy(dtype=float, copy=False)
    opens = df["open"].to_numpy(dtype=float, copy=False)
    volumes = (
        df["volume"].to_numpy(dtype=float, copy=False)
        if "volume" in df.columns
        else np.zeros(len(df), dtype=float)
    )
    atr_values = df["atr"].to_numpy(dtype=float, copy=False)
    signals = df["vwap_signal"].to_numpy(dtype=object, copy=False)
    stops = df["vwap_stop"].to_numpy(dtype=float, copy=False)
    targets_1 = df["vwap_target_1"].to_numpy(dtype=float, copy=False)
    targets_2 = df["vwap_target_2"].to_numpy(dtype=float, copy=False)
    vwaps = df["vwap"].to_numpy(dtype=float, copy=False)

    open_pos: Optional[Dict] = None

    for i in range(len(df)):
        bar_high = float(highs[i])
        bar_low = float(lows[i])
        bar_close = float(closes[i])
        bar_open = float(opens[i])
        bar_vol = float(volumes[i])
        bar_time = str(idx[i])
        bar_hour = int(eastern_hours[i])

        # SOTA: volatility-scaled slippage multiplier (ATR-relative)
        slip_mult = 1.0
        if volatility_scaled_slippage:
            atr_val = float(atr_values[i])
            lookback = max(0, i - 20)
            hist = atr_values[lookback:i]
            hist = hist[~np.isnan(hist)]
            if len(hist) >= 1 and atr_val > 0:
                mean_atr = float(hist.mean())
                if mean_atr > 0:
                    raw = atr_val / mean_atr
                    slip_mult = max(0.5, min(4.0, raw))

        # SOTA: POV impact surcharge on the slippage multiplier
        if max_volume_pct is not None and bar_vol > 0 and contracts > 0:
            pov = contracts / bar_vol
            if pov > max_volume_pct:
                excess = pov / max_volume_pct
                slip_mult *= 1.0 + (excess - 1.0) ** 2

        # SOTA: effective contracts capped by initial margin
        eff_contracts = contracts
        if initial_margin_per_contract is not None and initial_margin_per_contract > 0:
            cap = int(initial_capital // initial_margin_per_contract)
            eff_contracts = max(0, min(contracts, cap))
            if eff_contracts < 1:
                eff_contracts = 1

        # SOTA: effective slippage ticks = base * multiplier
        eff_spec = dict(spec)
        eff_spec["slippage_ticks"] = spec["slippage_ticks"] * slip_mult

        # EOD: force-close at 15:xx
        if open_pos is not None and bar_hour >= RTH_FINAL_HOUR:
            exit_p = _slip(bar_close, open_pos["side"], False, eff_spec)
            pnl = _pnl(open_pos["entry"], exit_p, open_pos["side"], eff_contracts, eff_spec)
            trades.append(
                VWAPTrade(
                    symbol=symbol,
                    entry_date=open_pos["entry_date"],
                    exit_date=bar_time,
                    side=open_pos["side"],
                    entry_price=open_pos["entry"],
                    exit_price=round(exit_p, 4),
                    contracts=eff_contracts,
                    exit_reason="eod",
                    vwap_at_entry=open_pos["vwap"],
                    atr_at_entry=open_pos["atr"],
                    pnl=round(pnl, 2),
                )
            )
            open_pos = None
            continue

        if open_pos is not None:
            side = open_pos["side"]
            entry = open_pos["entry"]
            stop = open_pos["stop"]
            t1 = open_pos["t1"]
            t2 = open_pos["t2"]

            # Check stop
            stop_hit = (side == "long" and bar_low <= stop) or (
                side == "short" and bar_high >= stop
            )
            if stop_hit:
                exit_p = _slip(stop, side, False, eff_spec)
                # SOTA: gap through the stop -> fill at worse of (bar_open, stop)
                if gap_stop_worst_fill:
                    if side == "long":
                        exit_p = min(_slip(bar_open, side, False, eff_spec), exit_p)
                    else:
                        exit_p = max(_slip(bar_open, side, False, eff_spec), exit_p)
                pnl = _pnl(entry, exit_p, side, eff_contracts, eff_spec)
                trades.append(
                    VWAPTrade(
                        symbol=symbol,
                        entry_date=open_pos["entry_date"],
                        exit_date=bar_time,
                        side=side,
                        entry_price=entry,
                        exit_price=round(exit_p, 4),
                        contracts=eff_contracts,
                        exit_reason="stop",
                        vwap_at_entry=open_pos["vwap"],
                        atr_at_entry=open_pos["atr"],
                        pnl=round(pnl, 2),
                    )
                )
                open_pos = None
                continue

            # Check T1 (VWAP)
            t1_hit = (side == "long" and bar_high >= t1) or (side == "short" and bar_low <= t1)
            if t1_hit:
                exit_p = _slip(t1, side, False, eff_spec)
                pnl = _pnl(entry, exit_p, side, eff_contracts, eff_spec)
                trades.append(
                    VWAPTrade(
                        symbol=symbol,
                        entry_date=open_pos["entry_date"],
                        exit_date=bar_time,
                        side=side,
                        entry_price=entry,
                        exit_price=round(exit_p, 4),
                        contracts=eff_contracts,
                        exit_reason="target_1",
                        vwap_at_entry=open_pos["vwap"],
                        atr_at_entry=open_pos["atr"],
                        pnl=round(pnl, 2),
                    )
                )
                open_pos = None
                continue

            # Check T2 (opposite band)
            t2_hit = (side == "long" and bar_high >= t2) or (side == "short" and bar_low <= t2)
            if t2_hit:
                exit_p = _slip(t2, side, False, eff_spec)
                pnl = _pnl(entry, exit_p, side, eff_contracts, eff_spec)
                trades.append(
                    VWAPTrade(
                        symbol=symbol,
                        entry_date=open_pos["entry_date"],
                        exit_date=bar_time,
                        side=side,
                        entry_price=entry,
                        exit_price=round(exit_p, 4),
                        contracts=eff_contracts,
                        exit_reason="target_2",
                        vwap_at_entry=open_pos["vwap"],
                        atr_at_entry=open_pos["atr"],
                        pnl=round(pnl, 2),
                    )
                )
                open_pos = None
                continue

        # New entry
        if open_pos is None:
            sig = str(signals[i])
            if sig in ("LONG_ENTRY", "SHORT_ENTRY"):
                side = "long" if sig == "LONG_ENTRY" else "short"
                entry_p = _slip(bar_close, side, True, eff_spec)
                stop_p = float(stops[i])
                t1_p = float(targets_1[i])
                t2_p = float(targets_2[i])
                vwap_p = float(vwaps[i])
                atr_p = float(atr_values[i])

                open_pos = {
                    "side": side,
                    "entry": entry_p,
                    "entry_date": bar_time,
                    "stop": stop_p,
                    "t1": t1_p,
                    "t2": t2_p,
                    "vwap": vwap_p,
                    "atr": atr_p,
                }

    # Force-close any remaining open position
    if open_pos is not None:
        last_close = float(closes[-1])
        exit_p = _slip(last_close, open_pos["side"], False, eff_spec)
        pnl = _pnl(open_pos["entry"], exit_p, open_pos["side"], eff_contracts, eff_spec)
        trades.append(
            VWAPTrade(
                symbol=symbol,
                entry_date=open_pos["entry_date"],
                exit_date=str(df.index[-1]),
                side=open_pos["side"],
                entry_price=open_pos["entry"],
                exit_price=round(exit_p, 4),
                contracts=eff_contracts,
                exit_reason="eod",
                vwap_at_entry=open_pos["vwap"],
                atr_at_entry=open_pos["atr"],
                pnl=round(pnl, 2),
            )
        )

    result = VWAPBacktestResult(
        symbol=symbol,
        interval="1h",
        start_date=str(df.index[0]),
        end_date=str(df.index[-1]),
        params=params,
        trades=trades,
    )
    s = result.summary()
    logger.info(
        f"VWAP Backtest {symbol} {str(df.index[0])[:10]}–{str(df.index[-1])[:10]}: "
        f"{s['total_trades']} trades | WR={s['win_rate']:.1%} | "
        f"PF={s['profit_factor']:.2f} | NetPnL=${s['net_pnl']:+.2f} | "
        f"MaxDD=${s['max_drawdown']:.2f} | Sharpe={s['sharpe']:.2f}"
    )
    return result
