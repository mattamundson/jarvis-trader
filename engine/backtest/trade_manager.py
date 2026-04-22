"""
JARVIS TRADER — Trade Domain Models
Trade and BacktestResult dataclasses used throughout the backtest module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


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

    # Exposure time (% of bars with open position)
    exposure_time_pct: float = 0.0
    total_bars: int = 0

    # Bid-ask spread simulation cost (entry half-spread + exit half-spread, all trades)
    spread_cost_total: float = 0.0

    # Value-at-Risk (Historical, from equity curve daily returns)
    var_95: float = 0.0   # 95% VaR — 5th-percentile daily return (negative = loss)
    var_99: float = 0.0   # 99% VaR — 1st-percentile daily return
    cvar_95: float = 0.0  # Expected Shortfall beyond 95% VaR
    cvar_99: float = 0.0  # Expected Shortfall beyond 99% VaR

    # Kelly criterion (from avg_win / avg_loss)
    kelly_fraction: float = 0.0        # full Kelly f* (theoretical optimal bet fraction)
    half_kelly_fraction: float = 0.0   # f*/2 — practical sizing recommendation

    def summary(self) -> str:
        """Human-readable one-screen summary.

        Unit notes: total_return_pct, max_drawdown_pct, win_rate, long/short_win_rate are
        FRACTIONS (0.199 = 19.9%). Display with `{:.1%}` / `{:+.1%}`. The prior version
        mixed `{:+.1f}%` (appends % sign without converting) with a fraction — printing
        0.199 as '0.2%' while final_capital showed a large gain. Now all are `{:.1%}`
        style, and Capital->Return are kept in sync via metrics.calculate_metrics.
        """
        # Defensive sanity check: if final_capital and total_return_pct disagree, flag it.
        # calculate_metrics() derives return from final_capital, so this should never fire
        # unless a caller bypasses calculate_metrics() and mutates one field only.
        derived_final = self.initial_capital * (1.0 + self.total_return_pct)
        capital_note = ""
        tolerance = max(1.0, 0.01 * abs(self.initial_capital))
        if abs(derived_final - self.final_capital) > tolerance:
            capital_note = f"  [WARN: return-implied ${derived_final:,.0f} disagrees]"

        lines = [
            f"=== BACKTEST RESULTS: {self.symbol} ===",
            f"Period: {self.start_date} -> {self.end_date}",
            f"Capital: ${self.initial_capital:,.0f} -> ${self.final_capital:,.0f}{capital_note}",
            f"Return: {self.total_return_pct:+.1%}  |  Max DD: {self.max_drawdown_pct:.1%}",
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
            f"Spread Cost Total: ${self.spread_cost_total:,.2f}",
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
            "exposure_time_pct": round(self.exposure_time_pct, 2),
            "total_bars": self.total_bars,
            "var_95": round(self.var_95, 6),
            "var_99": round(self.var_99, 6),
            "cvar_95": round(self.cvar_95, 6),
            "cvar_99": round(self.cvar_99, 6),
            "spread_cost_total": round(self.spread_cost_total, 2),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "half_kelly_fraction": round(self.half_kelly_fraction, 4),
            "equity_curve": [round(v, 2) for v in self.equity_curve],
            "trades": [t.to_dict() for t in self.trades],
        }
