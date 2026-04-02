"""
JARVIS TRADER — Event-Driven Backtester
Walk-forward simulation of the 5-layer trading strategy.

Domain models (Trade, BacktestResult) live in trade_manager.py.
Metrics computation lives in metrics.py.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

# Re-export for backward compatibility — all existing imports continue to work
from backtest.trade_manager import BacktestResult, Trade
from backtest.metrics import calculate_metrics

__all__ = ["Backtester", "BacktestResult", "Trade"]


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
        initial_capital: float = 10_000.0,
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
        base = symbol.replace("=F", "").replace("-F", "").upper()
        if base in TICK_SIZES:
            return TICK_SIZES[base]
        if multiplier <= 1.0:
            return DEFAULT_TICK_SIZE_ETF
        return DEFAULT_TICK_SIZE_FUTURES

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
            low = row.get("low", close)
            high = row.get("high", close)
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

        return calculate_metrics(result)
