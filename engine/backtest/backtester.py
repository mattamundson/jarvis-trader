"""
JARVIS TRADER — Event-Driven Backtester
Walk-forward simulation of the 5-layer trading strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class Trade:
    """A single completed or open trade."""

    entry_date: datetime
    symbol: str
    direction: str  # "long"/"short"
    entry_price: float
    stop_price: float
    target_1: float
    target_2: float
    contracts: int
    multiplier: float
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # "target_1"/"target_2"/"target_3"/"stop"/"eod"
    holding_bars: int = 0
    regime: str = ""
    bias: str = ""

    def to_dict(self) -> dict:
        return {
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stop_price": self.stop_price,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "contracts": self.contracts,
            "multiplier": self.multiplier,
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 4),
            "exit_reason": self.exit_reason,
            "holding_bars": self.holding_bars,
            "regime": self.regime,
            "bias": self.bias,
        }


@dataclass
class BacktestResult:
    """Complete results of a backtest run."""

    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    trades: List[Trade] = field(default_factory=list)

    # Metrics (computed after simulation)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_dollars: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_win_loss_ratio: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    equity_curve: List[float] = field(default_factory=list)

    # Extended metrics (research-grade)
    calmar_ratio: float = 0.0  # total_return_pct / max_drawdown_pct
    expectancy: float = 0.0  # (win_rate * avg_win) + (loss_rate * avg_loss)
    recovery_factor: float = 0.0  # total_pnl / max_drawdown_dollars
    payoff_ratio: float = 0.0  # abs(avg_win) / abs(avg_loss)

    # Breakdown by direction
    long_trades: int = 0
    short_trades: int = 0
    long_win_rate: float = 0.0
    short_win_rate: float = 0.0
    long_profit_factor: float = 0.0
    short_profit_factor: float = 0.0

    # Breakdown by regime
    regime_stats: dict = field(default_factory=dict)  # {regime_name: {trades, win_rate, pf}}

    # Trailing stop tracking
    trailing_stop_exits: int = 0

    # Trade duration
    avg_holding_bars: float = 0.0
    median_holding_bars: float = 0.0
    max_holding_bars: int = 0

    # Drawdown duration
    max_drawdown_duration_bars: int = 0  # how many bars the max drawdown lasted

    def summary(self) -> str:
        """Human-readable one-screen summary."""
        lines = [
            f"=== BACKTEST RESULTS: {self.symbol} ===",
            f"Period: {self.start_date} -> {self.end_date}",
            f"Capital: ${self.initial_capital:,.0f} -> ${self.final_capital:,.0f}",
            f"Return: {self.total_return_pct:+.1f}%  |  Max DD: {self.max_drawdown_pct:.1f}%",
            "",
            f"Trades: {self.total_trades} total  |  Win Rate: {self.win_rate:.1%}",
            f"Avg Win: ${self.avg_win:,.0f}  |  Avg Loss: ${self.avg_loss:,.0f}",
            f"Profit Factor: {self.profit_factor:.2f}",
            f"Sharpe: {self.sharpe_ratio:.2f}  |  Sortino: {self.sortino_ratio:.2f}",
            f"Max Consec. Losses: {self.max_consecutive_losses}  |  Wins: {self.max_consecutive_wins}",
            "",
            f"Calmar: {self.calmar_ratio:.2f}  |  Expectancy: ${self.expectancy:,.0f}  |  Recovery Factor: {self.recovery_factor:.2f}",
            f"Long Trades: {self.long_trades} (WR {self.long_win_rate:.0%})  |  Short Trades: {self.short_trades} (WR {self.short_win_rate:.0%})",
            f"Avg Holding: {self.avg_holding_bars:.1f} bars  |  Max DD Duration: {self.max_drawdown_duration_bars} bars",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_capital": self.initial_capital,
            "final_capital": round(self.final_capital, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "gross_profit": round(self.gross_profit, 2),
            "gross_loss": round(self.gross_loss, 2),
            "profit_factor": round(self.profit_factor, 3),
            "total_pnl": round(self.total_pnl, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "max_drawdown_dollars": round(self.max_drawdown_dollars, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "avg_win_loss_ratio": round(self.avg_win_loss_ratio, 3),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "sortino_ratio": round(self.sortino_ratio, 3),
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_consecutive_wins": self.max_consecutive_wins,
            "calmar_ratio": round(self.calmar_ratio, 3),
            "expectancy": round(self.expectancy, 2),
            "recovery_factor": round(self.recovery_factor, 3),
            "payoff_ratio": round(self.payoff_ratio, 3),
            "long_trades": self.long_trades,
            "short_trades": self.short_trades,
            "long_win_rate": round(self.long_win_rate, 4),
            "short_win_rate": round(self.short_win_rate, 4),
            "long_profit_factor": round(self.long_profit_factor, 3)
            if self.long_profit_factor != float("inf")
            else "inf",
            "short_profit_factor": round(self.short_profit_factor, 3)
            if self.short_profit_factor != float("inf")
            else "inf",
            "regime_stats": self.regime_stats,
            "avg_holding_bars": round(self.avg_holding_bars, 2),
            "median_holding_bars": round(self.median_holding_bars, 2),
            "max_holding_bars": self.max_holding_bars,
            "trailing_stop_exits": self.trailing_stop_exits,
            "max_drawdown_duration_bars": self.max_drawdown_duration_bars,
            "equity_curve": [round(v, 2) for v in self.equity_curve],
            "trades": [t.to_dict() for t in self.trades],
        }


# Tick sizes by symbol type
TICK_SIZES: Dict[str, float] = {
    "ES": 0.25,
    "MES": 0.25,
    "NQ": 0.25,
    "MNQ": 0.25,
    "YM": 1.0,
    "MYM": 1.0,
    "RTY": 0.10,
    "M2K": 0.10,
    "CL": 0.01,
    "GC": 0.10,
    "MGC": 0.10,
    "MCL": 0.01,
}
DEFAULT_TICK_SIZE_FUTURES = 0.25
DEFAULT_TICK_SIZE_ETF = 0.01


class Backtester:
    """Event-driven walk-forward backtester."""

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        risk_per_trade: float = 0.01,
        max_daily_loss: float = 0.02,
        max_drawdown: float = 0.05,
        t1_exit_pct: float = 0.50,  # % to exit at target 1
        t2_exit_pct: float = 0.30,  # % to exit at target 2
        commission_per_contract: float = 2.50,
        slippage_ticks: int = 1,
        trailing_stop: bool = False,
        trailing_atr_mult: float = 0.70,
        trailing_post_t1: bool = False,
    ):
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_drawdown = max_drawdown
        self.t1_exit_pct = t1_exit_pct
        self.t2_exit_pct = t2_exit_pct
        self.commission_per_contract = commission_per_contract
        self.slippage_ticks = slippage_ticks
        self.trailing_stop = trailing_stop
        self.trailing_atr_mult = trailing_atr_mult
        self.trailing_post_t1 = trailing_post_t1

    def _transaction_cost(self, contracts: int, tick_size: float = 0.25) -> float:
        """Round-trip cost: commission + slippage per contract."""
        return contracts * (self.commission_per_contract + self.slippage_ticks * tick_size)

    def _get_tick_size(self, symbol: str, multiplier: float) -> float:
        """Determine tick size from symbol or multiplier heuristic."""
        # Strip common suffixes
        base = symbol.replace("=F", "").replace("-F", "").upper()
        if base in TICK_SIZES:
            return TICK_SIZES[base]
        # ETFs have multiplier 1.0
        if multiplier <= 1.0:
            return DEFAULT_TICK_SIZE_ETF
        return DEFAULT_TICK_SIZE_FUTURES

    def _process_pending_entry(
        self,
        pending_entry: dict,
        row: pd.Series,
        idx,
        df: pd.DataFrame,
        multiplier: float,
        tick_size: float,
    ) -> tuple[Optional[Trade], int, int, int, list, float]:
        """Process a pending entry signal (avoid look-ahead bias)."""
        entry_price = row["open"]
        atr_val = pending_entry["atr"]
        direction = pending_entry["direction"]

        # Recalculate stop and targets from actual entry price
        if direction == "long":
            stop_price = entry_price - pending_entry["stop_atr_mult"] * atr_val
            target_1 = entry_price + pending_entry["t1_atr_mult"] * atr_val
            target_2 = entry_price + pending_entry["t2_atr_mult"] * atr_val
        else:
            stop_price = entry_price + pending_entry["stop_atr_mult"] * atr_val
            target_1 = entry_price - pending_entry["t1_atr_mult"] * atr_val
            target_2 = entry_price - pending_entry["t2_atr_mult"] * atr_val

        stop_dist = abs(entry_price - stop_price)
        if stop_dist <= 0:
            return None, 0, 0, 0, [], 0.0

        rr = abs(target_1 - entry_price) / stop_dist
        if rr < 1.2:
            return None, 0, 0, 0, [], 0.0

        total_contracts = self._calculate_contracts(
            row.get("capital", self.initial_capital), entry_price, stop_price, multiplier
        )
        if total_contracts < 1:
            return None, 0, 0, 0, [], 0.0

        t1_contracts = max(1, int(total_contracts * self.t1_exit_pct))
        t2_contracts = max(0, int(total_contracts * self.t2_exit_pct))
        t3_contracts = max(0, total_contracts - t1_contracts - t2_contracts)

        open_trade = Trade(
            entry_date=idx,
            symbol=row.get("symbol", ""),
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            target_1=target_1,
            target_2=target_2,
            contracts=total_contracts,
            multiplier=multiplier,
            regime=pending_entry.get("regime", ""),
            bias=pending_entry["bias"],
        )
        capital_used = self._transaction_cost(total_contracts, tick_size)
        return open_trade, t1_contracts, t2_contracts, t3_contracts, [], capital_used

    def _check_targets_exit(
        self,
        open_trade: Trade,
        open_contracts_t1: int,
        open_contracts_t2: int,
        multiplier: float,
        tick_size: float,
        t1_touched: bool,
        t2_touched: bool,
    ) -> tuple[int, int, float, list]:
        """Check and process target exits."""
        targets_hit = []
        capital_change = 0.0

        if open_contracts_t1 > 0 and t1_touched:
            exit_price = open_trade.target_1
            if open_trade.direction == "long":
                pnl = open_contracts_t1 * (exit_price - open_trade.entry_price) * multiplier
            else:
                pnl = open_contracts_t1 * (open_trade.entry_price - exit_price) * multiplier
            capital_change += pnl - self._transaction_cost(open_contracts_t1, tick_size)
            open_trade.pnl += pnl
            open_contracts_t1 = 0
            open_trade.stop_price = open_trade.entry_price
            targets_hit.append("target_1")

        if open_contracts_t2 > 0 and t2_touched:
            exit_price = open_trade.target_2
            if open_trade.direction == "long":
                pnl = open_contracts_t2 * (exit_price - open_trade.entry_price) * multiplier
            else:
                pnl = open_contracts_t2 * (open_trade.entry_price - exit_price) * multiplier
            capital_change += pnl - self._transaction_cost(open_contracts_t2, tick_size)
            open_trade.pnl += pnl
            open_contracts_t2 = 0
            targets_hit.append("target_2")

        return open_contracts_t1, open_contracts_t2, capital_change, targets_hit

    def _check_stop_exit(
        self,
        open_trade: Trade,
        open_contracts_t1: int,
        open_contracts_t2: int,
        open_contracts_t3: int,
        multiplier: float,
        tick_size: float,
        stop_touched: bool,
        targets_hit: list,
    ) -> tuple[Optional[Trade], int, int, int, float, list]:
        """Check and process stop loss exit."""
        if not stop_touched or (open_contracts_t1 + open_contracts_t2 + open_contracts_t3) <= 0:
            return open_trade, open_contracts_t1, open_contracts_t2, open_contracts_t3, 0.0, targets_hit

        remaining = open_contracts_t1 + open_contracts_t2 + open_contracts_t3
        exit_price = open_trade.stop_price
        if open_trade.direction == "long":
            pnl = remaining * (exit_price - open_trade.entry_price) * multiplier
        else:
            pnl = remaining * (open_trade.entry_price - exit_price) * multiplier
        capital_change = pnl - self._transaction_cost(remaining, tick_size)
        open_trade.exit_price = exit_price
        open_trade.pnl += pnl
        open_trade.exit_reason = targets_hit[-1] if targets_hit else "stop"

        return None, 0, 0, 0, capital_change, targets_hit

    def _process_trailing_stop_long(
        self,
        open_trade: Trade,
        open_contracts: int,
        multiplier: float,
        tick_size: float,
        bar_atr: float,
        close: float,
        low: float,
    ) -> tuple[Optional[Trade], int, float, bool]:
        """Process trailing stop for long positions."""
        capital_change = 0.0
        exited = False

        favorable_excursion = close - open_trade.entry_price
        if favorable_excursion >= 0.5 * bar_atr:
            new_trail = close - self.trailing_atr_mult * bar_atr
            if new_trail > open_trade.stop_price:
                open_trade.stop_price = new_trail

            if low <= open_trade.stop_price:
                exit_price = open_trade.stop_price
                pnl = open_contracts * (exit_price - open_trade.entry_price) * multiplier
                capital_change = pnl - self._transaction_cost(open_contracts, tick_size)
                open_trade.exit_price = exit_price
                open_trade.pnl += pnl
                open_trade.exit_reason = "trailing_stop"
                exited = True
                open_trade = None

        return open_trade, open_contracts, capital_change, exited

    def _process_trailing_stop_short(
        self,
        open_trade: Trade,
        open_contracts: int,
        multiplier: float,
        tick_size: float,
        bar_atr: float,
        close: float,
        high: float,
    ) -> tuple[Optional[Trade], int, float, bool]:
        """Process trailing stop for short positions."""
        capital_change = 0.0
        exited = False

        favorable_excursion = open_trade.entry_price - close
        if favorable_excursion >= 0.5 * bar_atr:
            new_trail = close + self.trailing_atr_mult * bar_atr
            if new_trail < open_trade.stop_price:
                open_trade.stop_price = new_trail

            if high >= open_trade.stop_price:
                exit_price = open_trade.stop_price
                pnl = open_contracts * (open_trade.entry_price - exit_price) * multiplier
                capital_change = pnl - self._transaction_cost(open_contracts, tick_size)
                open_trade.exit_price = exit_price
                open_trade.pnl += pnl
                open_trade.exit_reason = "trailing_stop"
                exited = True
                open_trade = None

        return open_trade, open_contracts, capital_change, exited

    def _check_eod_close(
        self,
        open_trade: Trade,
        open_contracts_t1: int,
        open_contracts_t2: int,
        open_contracts_t3: int,
        multiplier: float,
        tick_size: float,
        is_eod: bool,
        close: float,
        idx,
        targets_hit: list,
    ) -> tuple[Optional[Trade], int, int, int, float, list]:
        """Check for end-of-day close."""
        if not is_eod:
            return open_trade, open_contracts_t1, open_contracts_t2, open_contracts_t3, 0.0, targets_hit

        remaining = open_contracts_t1 + open_contracts_t2 + open_contracts_t3
        if remaining <= 0:
            return open_trade, open_contracts_t1, open_contracts_t2, open_contracts_t3, 0.0, targets_hit

        if open_trade.direction == "long":
            pnl = remaining * (close - open_trade.entry_price) * multiplier
        else:
            pnl = remaining * (open_trade.entry_price - close) * multiplier
        capital_change = pnl - self._transaction_cost(remaining, tick_size)
        open_trade.pnl += pnl
        open_trade.exit_price = close
        open_trade.exit_date = idx
        open_trade.exit_reason = targets_hit[-1] if targets_hit else "eod"

        return None, 0, 0, 0, capital_change, targets_hit

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        multiplier: float = 1.0,
        commission_per_contract: Optional[float] = None,
        slippage_ticks: Optional[int] = None,
    ) -> BacktestResult:
        """
        Walk-forward simulation. df must have signals from generate_signals().
        Required columns: open, high, low, close, entry_signal, bias,
                         stop_level, target_1, target_2, target_3, regime
        """
        # Allow caller overrides
        if commission_per_contract is not None:
            self.commission_per_contract = commission_per_contract
        if slippage_ticks is not None:
            self.slippage_ticks = slippage_ticks

        tick_size = self._get_tick_size(symbol, multiplier)

        capital = self.initial_capital
        high_water_mark = capital
        completed_trades: List[Trade] = []
        equity_curve = [capital]

        open_trade: Optional[Trade] = None
        open_contracts_t1 = 0
        open_contracts_t2 = 0
        open_contracts_t3 = 0
        targets_hit: List[str] = []  # Track which targets were hit during trade

        daily_start_capital = capital
        current_date = None
        kill_switch = False

        # Bug 3 fix: pending entry to avoid look-ahead bias
        pending_entry: Optional[dict] = None

        for idx, row in df.iterrows():
            row_date = idx.date() if hasattr(idx, "date") else None

            # Reset daily tracking
            if row_date != current_date:
                current_date = row_date
                daily_start_capital = capital
                kill_switch = False

            # Check kill switch
            daily_pnl_pct = (capital - daily_start_capital) / daily_start_capital
            drawdown_pct = (capital - high_water_mark) / high_water_mark

            if daily_pnl_pct < -self.max_daily_loss or drawdown_pct < -self.max_drawdown:
                kill_switch = True

            # -- Execute pending entry from previous bar's signal (Bug 3 fix) --
            if pending_entry is not None and open_trade is None and not kill_switch:
                row_with_capital = row.copy()
                row_with_capital["capital"] = capital
                row_with_capital["symbol"] = symbol
                new_trade, t1c, t2c, t3c, targets_hit, capital_cost = self._process_pending_entry(
                    pending_entry, row_with_capital, idx, df, multiplier, tick_size
                )
                pending_entry = None
                if new_trade is not None:
                    open_trade = new_trade
                    open_contracts_t1 = t1c
                    open_contracts_t2 = t2c
                    open_contracts_t3 = t3c
                    targets_hit = []
                    capital -= capital_cost

            # -- Manage open trade (process exits on this bar) ---------
            close = row["close"]
            open_trade, open_contracts_t1, open_contracts_t2, open_contracts_t3, \
                capital_from_exits, targets_hit, closed_trades = self._process_trade_on_bar(
                    open_trade, open_contracts_t1, open_contracts_t2, open_contracts_t3,
                    targets_hit, row, idx, df, multiplier, tick_size, close
                )
            capital += capital_from_exits
            completed_trades.extend([t for t in closed_trades if t])

            # -- Trailing ATR stop logic ------------------------------------------
            if self.trailing_stop and open_trade is not None:
                remaining = open_contracts_t1 + open_contracts_t2 + open_contracts_t3
                t1_gate = (not self.trailing_post_t1) or ("target_1" in targets_hit)
                if remaining > 0 and t1_gate:
                    bar_atr = row.get("atr", 0)
                    if bar_atr > 0:
                        if open_trade.direction == "long":
                            open_trade, open_contracts_t1, capital_ts, ts_exited = \
                                self._process_trailing_stop_long(
                                    open_trade, remaining, multiplier, tick_size,
                                    bar_atr, close, low
                                )
                            if ts_exited:
                                open_contracts_t2 = 0
                                open_contracts_t3 = 0
                                targets_hit = []
                            capital += capital_ts
                        else:
                            open_trade, open_contracts_t1, capital_ts, ts_exited = \
                                self._process_trailing_stop_short(
                                    open_trade, remaining, multiplier, tick_size,
                                    bar_atr, close, high
                                )
                            if ts_exited:
                                open_contracts_t2 = 0
                                open_contracts_t3 = 0
                                targets_hit = []
                            capital += capital_ts
                        if ts_exited:
                            completed_trades.append(open_trade) if open_trade else None

            # End of day close
            remaining_contracts = open_contracts_t1 + open_contracts_t2 + open_contracts_t3
            if remaining_contracts > 0 and open_trade is not None:
                next_idx_pos = df.index.get_loc(idx)
                is_last_bar = next_idx_pos == len(df) - 1
                is_eod = is_last_bar
                if not is_last_bar and hasattr(idx, "hour"):
                    next_bar_date = df.index[next_idx_pos + 1].date()
                    is_eod = next_bar_date != row_date

                open_trade, open_contracts_t1, open_contracts_t2, open_contracts_t3, \
                    capital_eod, targets_hit = self._check_eod_close(
                        open_trade, open_contracts_t1, open_contracts_t2, open_contracts_t3,
                        multiplier, tick_size, is_eod, close, idx, targets_hit
                    )
                capital += capital_eod
                if open_trade is None:
                    # Trade was closed at EOD
                    pass

            # -- Check for new entry signal (Bug 3: store as pending, don't enter now) --
            if open_trade is None and pending_entry is None and not kill_switch:
                entry_sig = row.get("entry_signal", "NO_TRADE")
                bias = row.get("bias", "NEUTRAL")

                if entry_sig == "ENTRY_NOW" and bias not in ("NEUTRAL",):
                    direction = "long" if "BULL" in bias else "short"
                    signal_price = row["close"]
                    stop_price = row.get("stop_level", signal_price * 0.99)
                    target_1 = row.get("target_1", signal_price * 1.01)
                    target_2 = row.get("target_2", signal_price * 1.02)

                    # Compute ATR multiples for recalculation at actual entry
                    atr_val = row.get("atr", 1.0)
                    if atr_val <= 0:
                        atr_val = abs(signal_price - stop_price)
                    if atr_val <= 0:
                        continue

                    stop_dist = abs(signal_price - stop_price)
                    if stop_dist <= 0:
                        continue

                    # R:R pre-check on signal bar (Bug 6: lowered from 1.5 to 1.2)
                    rr = abs(target_1 - signal_price) / stop_dist
                    if rr < 1.2:
                        continue

                    pending_entry = {
                        "direction": direction,
                        "bias": bias,
                        "stop_atr_mult": stop_dist / atr_val,
                        "t1_atr_mult": abs(target_1 - signal_price) / atr_val,
                        "t2_atr_mult": abs(target_2 - signal_price) / atr_val,
                        "atr": atr_val,
                        "regime": row.get("regime", ""),
                    }

            # Update equity curve
            equity_curve.append(capital)
            if capital > high_water_mark:
                high_water_mark = capital

        result = BacktestResult(
            symbol=symbol,
            start_date=str(df.index[0].date()) if len(df) > 0 else "",
            end_date=str(df.index[-1].date()) if len(df) > 0 else "",
            initial_capital=self.initial_capital,
            final_capital=capital,
            trades=completed_trades,
            equity_curve=equity_curve,
        )

        return self._calculate_metrics(result)

    def _calculate_contracts(
        self, capital: float, entry: float, stop: float, multiplier: float
    ) -> int:
        """contracts = (capital x risk%) / (stop_distance x multiplier)"""
        stop_dist = abs(entry - stop)
        if stop_dist <= 0 or multiplier <= 0:
            return 0
        risk_dollars = capital * self.risk_per_trade
        contracts = risk_dollars / (stop_dist * multiplier)
        return max(0, min(int(contracts), 50))  # cap at 50

    def _compute_returns_and_drawdown(self, result: BacktestResult) -> None:
        """Compute basic return metrics and max drawdown."""
        equity = np.array(result.equity_curve)
        if len(equity) > 1:
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / peak
            result.max_drawdown_pct = float(abs(dd.min()))
            result.max_drawdown_dollars = float(abs((equity - peak).min()))

    def _compute_sharpe_sortino(self, result: BacktestResult) -> None:
        """Compute Sharpe and Sortino ratios from equity curve."""
        equity = np.array(result.equity_curve)
        if len(equity) <= 2:
            return
        daily_returns = np.diff(equity) / equity[:-1]
        daily_returns = daily_returns[~np.isnan(daily_returns)]
        if len(daily_returns) <= 1 or daily_returns.std() <= 0:
            return
        result.sharpe_ratio = float(
            (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
        )
        downside = daily_returns[daily_returns < 0]
        if len(downside) > 1:
            downside_std = downside.std()
            if downside_std > 0:
                result.sortino_ratio = float(
                    (daily_returns.mean() / downside_std) * np.sqrt(252)
                )

    def _compute_extended_metrics(self, result: BacktestResult) -> None:
        """Compute extended metrics (Calmar, Expectancy, Recovery, Payoff)."""
        if result.max_drawdown_pct > 0:
            result.calmar_ratio = result.total_return_pct / result.max_drawdown_pct
        if result.trades:
            loss_rate = 1 - result.win_rate
            result.expectancy = (result.win_rate * result.avg_win) + (loss_rate * result.avg_loss)
        if result.max_drawdown_dollars > 0:
            result.recovery_factor = result.total_pnl / result.max_drawdown_dollars
        if result.avg_loss != 0:
            result.payoff_ratio = abs(result.avg_win / result.avg_loss)

    def _compute_direction_breakdown(self, result: BacktestResult, trades: list) -> None:
        """Compute long vs short statistics."""
        long_trades = [t for t in trades if t.direction == "long"]
        short_trades = [t for t in trades if t.direction == "short"]
        result.long_trades = len(long_trades)
        result.short_trades = len(short_trades)

        if long_trades:
            long_wins = [t for t in long_trades if t.pnl > 0]
            result.long_win_rate = len(long_wins) / len(long_trades)
            long_gross_profit = sum(t.pnl for t in long_trades if t.pnl > 0)
            long_gross_loss = sum(t.pnl for t in long_trades if t.pnl <= 0)
            result.long_profit_factor = (
                long_gross_profit / abs(long_gross_loss) if long_gross_loss else float("inf")
            )

        if short_trades:
            short_wins = [t for t in short_trades if t.pnl > 0]
            result.short_win_rate = len(short_wins) / len(short_trades)
            short_gross_profit = sum(t.pnl for t in short_trades if t.pnl > 0)
            short_gross_loss = sum(t.pnl for t in short_trades if t.pnl <= 0)
            result.short_profit_factor = (
                short_gross_profit / abs(short_gross_loss) if short_gross_loss else float("inf")
            )

    def _compute_regime_breakdown(self, result: BacktestResult, trades: list) -> None:
        """Compute regime-based statistics."""
        regime_groups: Dict[str, list] = {}
        for t in trades:
            r = t.regime or "UNKNOWN"
            if r not in regime_groups:
                regime_groups[r] = []
            regime_groups[r].append(t)

        for regime, regime_trades in regime_groups.items():
            regime_wins = [t for t in regime_trades if t.pnl > 0]
            regime_gross_profit = sum(t.pnl for t in regime_trades if t.pnl > 0)
            regime_gross_loss = sum(t.pnl for t in regime_trades if t.pnl <= 0)
            result.regime_stats[regime] = {
                "trades": len(regime_trades),
                "win_rate": len(regime_wins) / len(regime_trades) if regime_trades else 0,
                "profit_factor": regime_gross_profit / abs(regime_gross_loss)
                if regime_gross_loss
                else float("inf"),
                "total_pnl": sum(t.pnl for t in regime_trades),
            }

    def _process_trade_on_bar(
        self,
        open_trade: Optional[Trade],
        open_contracts_t1: int,
        open_contracts_t2: int,
        open_contracts_t3: int,
        targets_hit: list,
        row: pd.Series,
        idx,
        df: pd.DataFrame,
        multiplier: float,
        tick_size: float,
        close: float,
    ) -> tuple[Optional[Trade], int, int, int, float, list, list]:
        """Process trade exits (targets, stops, trailing, EOD) on a single bar."""
        completed = []
        capital_change = 0.0

        if open_trade is None:
            return None, open_contracts_t1, open_contracts_t2, open_contracts_t3, capital_change, targets_hit, completed

        open_trade.holding_bars += 1
        bar_open = row["open"]
        high = row["high"]
        low = row["low"]

        # Determine which levels are touched
        if open_trade.direction == "long":
            stop_touched = low <= open_trade.stop_price
            t1_touched = high >= open_trade.target_1 if open_contracts_t1 > 0 else False
            t2_touched = high >= open_trade.target_2 if open_contracts_t2 > 0 else False
            target_first = bar_open >= open_trade.entry_price
        else:
            stop_touched = high >= open_trade.stop_price
            t1_touched = low <= open_trade.target_1 if open_contracts_t1 > 0 else False
            t2_touched = low <= open_trade.target_2 if open_contracts_t2 > 0 else False
            target_first = bar_open <= open_trade.entry_price

        # Process exits in priority order
        both_stop_and_target = stop_touched and (t1_touched or t2_touched)
        check_targets_first = both_stop_and_target and target_first

        if check_targets_first:
            open_contracts_t1, open_contracts_t2, capital_from_targets, new_targets = \
                self._check_targets_exit(
                    open_trade, open_contracts_t1, open_contracts_t2, multiplier,
                    tick_size, t1_touched, t2_touched
                )
            capital_change += capital_from_targets
            targets_hit.extend(new_targets)
            if open_trade is not None:
                open_trade, new_t1, new_t2, new_t3, capital_from_stop, targets_hit = \
                    self._check_stop_exit(
                        open_trade, open_contracts_t1, open_contracts_t2, open_contracts_t3,
                        multiplier, tick_size, stop_touched, targets_hit
                    )
                if open_trade is None:
                    completed.append(True)
                open_contracts_t1, open_contracts_t2, open_contracts_t3 = new_t1, new_t2, new_t3
                capital_change += capital_from_stop
        else:
            open_trade, new_t1, new_t2, new_t3, capital_from_stop, targets_hit = \
                self._check_stop_exit(
                    open_trade, open_contracts_t1, open_contracts_t2, open_contracts_t3,
                    multiplier, tick_size, stop_touched, targets_hit
                )
            if open_trade is None:
                completed.append(True)
            else:
                open_contracts_t1, open_contracts_t2, open_contracts_t3 = new_t1, new_t2, new_t3
                capital_change += capital_from_stop
                open_contracts_t1, open_contracts_t2, capital_from_targets, new_targets = \
                    self._check_targets_exit(
                        open_trade, open_contracts_t1, open_contracts_t2, multiplier,
                        tick_size, t1_touched, t2_touched
                    )
                capital_change += capital_from_targets
                targets_hit.extend(new_targets)

        # Check all contracts exited via targets
        if open_trade is not None and (open_contracts_t1 + open_contracts_t2 + open_contracts_t3) == 0:
            open_trade.exit_reason = targets_hit[-1] if targets_hit else "target_1"
            open_trade.exit_price = close
            open_trade.exit_date = idx
            completed.append(open_trade)
            open_trade = None
            targets_hit = []

        return open_trade, open_contracts_t1, open_contracts_t2, open_contracts_t3, capital_change, targets_hit, completed

    def _compute_duration_metrics(self, result: BacktestResult, trades: list) -> None:
        """Compute trade duration and drawdown duration."""
        if trades:
            holding_bars = [t.holding_bars for t in trades]
            result.avg_holding_bars = float(np.mean(holding_bars))
            result.median_holding_bars = float(np.median(holding_bars))
            result.max_holding_bars = max(holding_bars)

        equity = np.array(result.equity_curve)
        if len(equity) > 1:
            peak = np.maximum.accumulate(equity)
            in_dd = equity < peak
            max_dd_dur = 0
            cur_dd_dur = 0
            for is_dd in in_dd:
                if is_dd:
                    cur_dd_dur += 1
                else:
                    max_dd_dur = max(max_dd_dur, cur_dd_dur)
                    cur_dd_dur = 0
            result.max_drawdown_duration_bars = max(max_dd_dur, cur_dd_dur)

    def _calculate_metrics(self, result: BacktestResult) -> BacktestResult:
        """Fill in all metrics from the trades list."""
        trades = result.trades
        if not trades:
            return result

        result.total_trades = len(trades)
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.win_rate = len(wins) / len(trades) if trades else 0.0
        result.trailing_stop_exits = sum(1 for t in trades if t.exit_reason == "trailing_stop")
        result.gross_profit = sum(t.pnl for t in wins)
        result.gross_loss = sum(t.pnl for t in losses)
        result.profit_factor = (
            result.gross_profit / abs(result.gross_loss) if result.gross_loss != 0 else float("inf")
        )
        result.total_pnl = result.gross_profit + result.gross_loss
        result.total_return_pct = result.total_pnl / result.initial_capital

        result.avg_win = result.gross_profit / len(wins) if wins else 0.0
        result.avg_loss = result.gross_loss / len(losses) if losses else 0.0
        result.avg_win_loss_ratio = (
            abs(result.avg_win / result.avg_loss) if result.avg_loss != 0 else 0.0
        )

        # Max drawdown from equity curve
        equity = np.array(result.equity_curve)
        if len(equity) > 1:
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / peak
            result.max_drawdown_pct = float(abs(dd.min()))
            result.max_drawdown_dollars = float(abs((equity - peak).min()))

        # Bug 5 fix: Sharpe and Sortino from daily equity curve returns
        if len(equity) > 2:
            daily_returns = np.diff(equity) / equity[:-1]
            daily_returns = daily_returns[~np.isnan(daily_returns)]

            if len(daily_returns) > 1 and daily_returns.std() > 0:
                # Annualized Sharpe: mean_daily_return / std_daily_return * sqrt(252)
                result.sharpe_ratio = float(
                    (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
                )
                # Sortino: only penalize downside deviation
                downside = daily_returns[daily_returns < 0]
                if len(downside) > 1:
                    downside_std = downside.std()
                    if downside_std > 0:
                        result.sortino_ratio = float(
                            (daily_returns.mean() / downside_std) * np.sqrt(252)
                        )

        # Consecutive wins/losses
        max_consec_win = max_consec_loss = 0
        cur_win = cur_loss = 0
        for t in trades:
            if t.pnl > 0:
                cur_win += 1
                cur_loss = 0
                max_consec_win = max(max_consec_win, cur_win)
            else:
                cur_loss += 1
                cur_win = 0
                max_consec_loss = max(max_consec_loss, cur_loss)
        result.max_consecutive_wins = max_consec_win
        result.max_consecutive_losses = max_consec_loss

        # Delegate to helper methods
        self._compute_returns_and_drawdown(result)
        self._compute_sharpe_sortino(result)
        self._compute_extended_metrics(result)
        self._compute_direction_breakdown(result, trades)
        self._compute_regime_breakdown(result, trades)
        self._compute_duration_metrics(result, trades)

        return result
