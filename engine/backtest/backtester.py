"""
JARVIS TRADER — Event-Driven Backtester
Walk-forward simulation of the 5-layer trading strategy.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime, date


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

    def summary(self) -> str:
        """Human-readable one-screen summary."""
        lines = [
            f"=== BACKTEST RESULTS: {self.symbol} ===",
            f"Period: {self.start_date} -> {self.end_date}",
            f"Capital: ${self.initial_capital:,.0f} -> ${self.final_capital:,.0f}",
            f"Return: {self.total_return_pct:+.1f}%  |  Max DD: {self.max_drawdown_pct:.1f}%",
            f"",
            f"Trades: {self.total_trades} total  |  Win Rate: {self.win_rate:.1%}",
            f"Avg Win: ${self.avg_win:,.0f}  |  Avg Loss: ${self.avg_loss:,.0f}",
            f"Profit Factor: {self.profit_factor:.2f}",
            f"Sharpe: {self.sharpe_ratio:.2f}  |  Sortino: {self.sortino_ratio:.2f}",
            f"Max Consec. Losses: {self.max_consecutive_losses}  |  Wins: {self.max_consecutive_wins}",
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
            "equity_curve": [round(v, 2) for v in self.equity_curve],
            "trades": [t.to_dict() for t in self.trades],
        }


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
    ):
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_drawdown = max_drawdown
        self.t1_exit_pct = t1_exit_pct
        self.t2_exit_pct = t2_exit_pct

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        multiplier: float = 1.0
    ) -> BacktestResult:
        """
        Walk-forward simulation. df must have signals from generate_signals().
        Required columns: open, high, low, close, entry_signal, bias,
                         stop_level, target_1, target_2, target_3, regime
        """
        capital = self.initial_capital
        high_water_mark = capital
        completed_trades: List[Trade] = []
        equity_curve = [capital]

        open_trade: Optional[Trade] = None
        open_contracts_t1 = 0
        open_contracts_t2 = 0
        open_contracts_t3 = 0

        daily_start_capital = capital
        current_date = None
        kill_switch = False

        for idx, row in df.iterrows():
            row_date = idx.date() if hasattr(idx, 'date') else None

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

            # -- Manage open trade -------------------------------------------------
            if open_trade is not None:
                open_trade.holding_bars += 1
                high = row['high']
                low = row['low']
                close = row['close']

                # Check stop
                if open_trade.direction == 'long' and low <= open_trade.stop_price:
                    exit_price = open_trade.stop_price
                    remaining = open_contracts_t3
                    pnl = remaining * (exit_price - open_trade.entry_price) * multiplier
                    capital += pnl
                    open_trade.exit_price = exit_price
                    open_trade.exit_date = idx
                    open_trade.pnl += pnl
                    open_trade.exit_reason = "stop"
                    completed_trades.append(open_trade)
                    open_trade = None
                    open_contracts_t3 = 0

                elif open_trade.direction == 'short' and high >= open_trade.stop_price:
                    exit_price = open_trade.stop_price
                    remaining = open_contracts_t3
                    pnl = remaining * (open_trade.entry_price - exit_price) * multiplier
                    capital += pnl
                    open_trade.exit_price = exit_price
                    open_trade.exit_date = idx
                    open_trade.pnl += pnl
                    open_trade.exit_reason = "stop"
                    completed_trades.append(open_trade)
                    open_trade = None
                    open_contracts_t3 = 0

                elif open_trade is not None:
                    # Check target 1
                    if open_contracts_t1 > 0:
                        if (open_trade.direction == 'long' and high >= open_trade.target_1) or \
                           (open_trade.direction == 'short' and low <= open_trade.target_1):
                            exit_price = open_trade.target_1
                            if open_trade.direction == 'long':
                                pnl = open_contracts_t1 * (exit_price - open_trade.entry_price) * multiplier
                            else:
                                pnl = open_contracts_t1 * (open_trade.entry_price - exit_price) * multiplier
                            capital += pnl
                            open_trade.pnl += pnl
                            open_contracts_t1 = 0
                            # Move stop to breakeven
                            open_trade.stop_price = open_trade.entry_price

                    # Check target 2
                    if open_contracts_t2 > 0:
                        if (open_trade.direction == 'long' and high >= open_trade.target_2) or \
                           (open_trade.direction == 'short' and low <= open_trade.target_2):
                            exit_price = open_trade.target_2
                            if open_trade.direction == 'long':
                                pnl = open_contracts_t2 * (exit_price - open_trade.entry_price) * multiplier
                            else:
                                pnl = open_contracts_t2 * (open_trade.entry_price - exit_price) * multiplier
                            capital += pnl
                            open_trade.pnl += pnl
                            open_contracts_t2 = 0

                    # End of day: close any remaining open position
                    # (simplified: no overnight holding for intraday backtest)
                    if open_contracts_t3 > 0 and open_trade is not None:
                        next_idx = df.index.get_loc(idx)
                        is_last_bar = (next_idx == len(df) - 1)
                        if is_last_bar:
                            exit_price = close
                            if open_trade.direction == 'long':
                                pnl = open_contracts_t3 * (exit_price - open_trade.entry_price) * multiplier
                            else:
                                pnl = open_contracts_t3 * (open_trade.entry_price - exit_price) * multiplier
                            capital += pnl
                            open_trade.pnl += pnl
                            open_trade.exit_price = exit_price
                            open_trade.exit_date = idx
                            open_trade.exit_reason = "eod"
                            completed_trades.append(open_trade)
                            open_trade = None
                            open_contracts_t3 = 0

            # -- Check for new entry signal ----------------------------------------
            if open_trade is None and not kill_switch:
                entry_sig = row.get('entry_signal', 'NO_TRADE')
                bias = row.get('bias', 'NEUTRAL')

                if entry_sig == 'ENTRY_NOW' and bias not in ('NEUTRAL',):
                    direction = 'long' if 'BULL' in bias else 'short'
                    entry_price = row['close']  # next bar open would be more realistic
                    stop_price = row.get('stop_level', entry_price * 0.99)
                    target_1 = row.get('target_1', entry_price * 1.01)
                    target_2 = row.get('target_2', entry_price * 1.02)
                    target_3 = row.get('target_3', entry_price * 1.03)

                    stop_dist = abs(entry_price - stop_price)
                    if stop_dist <= 0:
                        continue

                    # R:R check
                    rr = abs(target_1 - entry_price) / stop_dist
                    if rr < 1.5:
                        continue

                    total_contracts = self._calculate_contracts(
                        capital, entry_price, stop_price, multiplier
                    )
                    if total_contracts < 1:
                        continue

                    t1_contracts = max(1, int(total_contracts * self.t1_exit_pct))
                    t2_contracts = max(0, int(total_contracts * self.t2_exit_pct))
                    t3_contracts = max(0, total_contracts - t1_contracts - t2_contracts)

                    open_contracts_t1 = t1_contracts
                    open_contracts_t2 = t2_contracts
                    open_contracts_t3 = t3_contracts

                    open_trade = Trade(
                        entry_date=idx,
                        symbol=symbol,
                        direction=direction,
                        entry_price=entry_price,
                        stop_price=stop_price,
                        target_1=target_1,
                        target_2=target_2,
                        contracts=total_contracts,
                        multiplier=multiplier,
                        regime=row.get('regime', ''),
                        bias=bias,
                    )

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
        self,
        capital: float,
        entry: float,
        stop: float,
        multiplier: float
    ) -> int:
        """contracts = (capital x risk%) / (stop_distance x multiplier)"""
        stop_dist = abs(entry - stop)
        if stop_dist <= 0 or multiplier <= 0:
            return 0
        risk_dollars = capital * self.risk_per_trade
        contracts = risk_dollars / (stop_dist * multiplier)
        return max(0, min(int(contracts), 50))  # cap at 50

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
        result.gross_profit = sum(t.pnl for t in wins)
        result.gross_loss = sum(t.pnl for t in losses)
        result.profit_factor = (
            result.gross_profit / abs(result.gross_loss)
            if result.gross_loss != 0 else float('inf')
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

        # Sharpe and Sortino (simplified, using trade P&L)
        pnls = np.array([t.pnl for t in trades])
        if len(pnls) > 1 and pnls.std() > 0:
            result.sharpe_ratio = float(
                (pnls.mean() / pnls.std()) * np.sqrt(252 / max(1, len(trades) / 252))
            )
            downside = pnls[pnls < 0]
            downside_std = downside.std() if len(downside) > 1 else 1.0
            if downside_std > 0:
                result.sortino_ratio = float(pnls.mean() / downside_std * np.sqrt(252))

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

        return result
