"""
JARVIS TRADER — Regime-Specific Performance Breakdown
Analyzes backtest results and OHLCV data to classify each trade's market regime
and compute performance metrics per regime.

Core insight: Not all edges come from the same regime. This tool identifies
which regimes are profitable, which should be avoided, and whether regime
transitions create false signals.

Regime Classification:
  - TRENDING_UP:    EMA ribbon bullish + positive phase/momentum
  - TRENDING_DOWN:  EMA ribbon bearish + negative phase/momentum
  - RANGE_BOUND:    Compressed EMAs + low ATR consumed %
  - HIGH_VOLATILITY: ATR consumed > 80% or extreme phase values
  - TRANSITION:     Regime just changed (within last 5 bars)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd


@dataclass
class RegimeMetrics:
    """Performance metrics for a single regime."""
    regime: str
    trade_count: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    total_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_loss: float = 0.0
    max_win: float = 0.0
    expectancy: float = 0.0

    def to_dict(self) -> dict:
        return {
            'regime': self.regime,
            'trade_count': self.trade_count,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': round(self.win_rate, 4) if self.trade_count > 0 else 0.0,
            'gross_profit': round(self.gross_profit, 2),
            'gross_loss': round(self.gross_loss, 2),
            'profit_factor': round(self.profit_factor, 3) if self.gross_loss != 0 else 0.0,
            'avg_win': round(self.avg_win, 2) if self.winning_trades > 0 else 0.0,
            'avg_loss': round(self.avg_loss, 2) if self.losing_trades > 0 else 0.0,
            'total_pnl': round(self.total_pnl, 2),
            'sharpe_ratio': round(self.sharpe_ratio, 2),
            'max_win': round(self.max_win, 2),
            'max_loss': round(self.max_loss, 2),
            'expectancy': round(self.expectancy, 2),
        }


class RegimeAnalyzer:
    """
    Analyzes backtest results across market regimes.

    Can work in two modes:
    1. With trade-embedded regime data (preferred): trades already have 'regime' field
    2. With OHLCV data: classifies each trade's entry regime from price/indicator data
    """

    def __init__(self, df: pd.DataFrame = None):
        """
        Initialize with optional OHLCV DataFrame that has been pre-computed with indicators.
        If df is None, regime analysis will use embedded regime data from trades.

        Expects columns (if provided): open, high, low, close, volume, atr, ema_8, ema_21, ema_34,
                        phase_val, phase_compression, atr_consumed_pct, etc.
        """
        self.df = df.copy() if df is not None else None
        self.regime_stats: Dict[str, RegimeMetrics] = {}
        if self.df is not None:
            self._ensure_datetime_index()

    def _ensure_datetime_index(self):
        """Ensure the DataFrame index is datetime for lookups."""
        if not isinstance(self.df.index, pd.DatetimeIndex):
            if isinstance(self.df.index, pd.RangeIndex):
                # Try to use a timestamp column
                if 'timestamp' in self.df.columns:
                    self.df.index = pd.to_datetime(self.df['timestamp'])
                else:
                    raise ValueError("DataFrame must have datetime index or 'timestamp' column")
            else:
                self.df.index = pd.to_datetime(self.df.index)

    def classify_regime_at_entry(self, entry_timestamp: datetime) -> str:
        """
        Determine the market regime at a specific entry timestamp.
        Uses the regime classification logic from signals.py.

        Regimes:
          - TRENDING_UP: EMA ribbon bullish + positive phase
          - TRENDING_DOWN: EMA ribbon bearish + negative phase
          - RANGE_BOUND: Compressed EMAs, low ATR consumed %
          - HIGH_VOLATILITY: ATR consumed > 80% or extreme phase
          - TRANSITION: Regime changed in last 5 bars
        """
        # Find the bar at or just after entry_timestamp
        try:
            bar = self.df.loc[self.df.index <= entry_timestamp].iloc[-1]
        except (KeyError, IndexError):
            return 'UNKNOWN'

        bar_idx = self.df.index.get_loc(bar.name)

        # Check for transition: did regime change in last 5 bars?
        if bar_idx >= 5:
            regimes_prior_5 = []
            for i in range(max(0, bar_idx - 5), bar_idx):
                regimes_prior_5.append(self._classify_single_bar(self.df.iloc[i]))

            # If regimes are not uniform, it's a transition
            if len(set(regimes_prior_5)) > 1:
                return 'TRANSITION'

        return self._classify_single_bar(bar)

    def _classify_single_bar(self, row: pd.Series) -> str:
        """Classify a single bar's regime."""
        atr_consumed = float(row.get('atr_consumed_pct', 0) or 0)
        phase = float(row.get('phase_val', 0) or 0)
        compression = bool(row.get('phase_compression', False))
        ema_8 = float(row.get('ema_8', 0) or 0)
        ema_21 = float(row.get('ema_21', 0) or 0)
        ema_34 = float(row.get('ema_34', 0) or 0)

        # High volatility: ATR consumed > 80% or extreme phase
        if atr_consumed > 80 or abs(phase) > 61.8:
            return 'HIGH_VOLATILITY'

        # Range bound: compressed EMAs + low ATR consumed
        if compression and atr_consumed < 50:
            return 'RANGE_BOUND'

        # Determine EMA trend
        if ema_8 > ema_21 > ema_34:
            ema_trend = 'bullish'
        elif ema_8 < ema_21 < ema_34:
            ema_trend = 'bearish'
        else:
            ema_trend = 'neutral'

        # Trending up: bullish ribbon + positive phase
        if ema_trend == 'bullish' and atr_consumed < 70 and phase > 0:
            return 'TRENDING_UP'

        # Trending down: bearish ribbon + negative phase
        if ema_trend == 'bearish' and atr_consumed < 70 and phase < 0:
            return 'TRENDING_DOWN'

        # Default: range bound
        return 'RANGE_BOUND'

    def analyze_trades(
        self,
        trades: List[Dict],
        pnl_column: str = 'pnl',
        entry_date_column: str = 'entry_date',
        regime_column: str = 'regime',
    ) -> Dict[str, RegimeMetrics]:
        """
        Analyze a list of trades (dicts with entry_date and pnl).
        Uses embedded regime data if available; otherwise classifies from OHLCV.

        Parameters
        ----------
        trades : List[Dict]
            List of trade dicts with keys: entry_date, pnl (at minimum)
        pnl_column : str
            Key in trade dict containing P&L value
        entry_date_column : str
            Key in trade dict containing entry timestamp
        regime_column : str
            Key in trade dict containing regime label (if available)

        Returns
        -------
        Dict[str, RegimeMetrics]
            Dict mapping regime name -> RegimeMetrics
        """
        regime_trades: Dict[str, List[float]] = {
            'TRENDING_UP': [],
            'TRENDING_DOWN': [],
            'TRENDING_BULL': [],
            'TRENDING_BEAR': [],
            'RANGE_BOUND': [],
            'HIGH_VOLATILITY': [],
            'COMPRESSION': [],
            'EXHAUSTED': [],
            'TRANSITION': [],
        }

        # Classify each trade and bucket by regime
        for trade in trades:
            if entry_date_column not in trade or pnl_column not in trade:
                continue

            entry_ts = trade[entry_date_column]
            pnl = float(trade[pnl_column])

            # Parse datetime if it's a string
            if isinstance(entry_ts, str):
                entry_ts = pd.to_datetime(entry_ts)

            # Prefer embedded regime data; fall back to classification
            if regime_column in trade and trade[regime_column]:
                regime = trade[regime_column]
            elif self.df is not None:
                regime = self.classify_regime_at_entry(entry_ts)
            else:
                regime = 'UNKNOWN'

            # Normalize regime names
            regime = regime.upper()
            if regime not in regime_trades:
                regime_trades[regime] = []

            regime_trades[regime].append(pnl)

        # Compute metrics for each regime
        self.regime_stats = {}
        for regime, pnls in regime_trades.items():
            if len(pnls) == 0 or regime == 'UNKNOWN':
                continue

            pnls = np.array(pnls)
            winning = pnls[pnls > 0]
            losing = pnls[pnls < 0]

            gross_profit = float(winning.sum()) if len(winning) > 0 else 0.0
            gross_loss = float(abs(losing.sum())) if len(losing) > 0 else 0.0
            total_pnl = float(pnls.sum())

            win_rate = len(winning) / len(pnls) if len(pnls) > 0 else 0.0
            avg_win = float(winning.mean()) if len(winning) > 0 else 0.0
            avg_loss = float(losing.mean()) if len(losing) > 0 else 0.0

            # Profit factor: gross_profit / gross_loss
            pf = gross_profit / gross_loss if gross_loss != 0 else (1.0 if gross_profit > 0 else 0.0)

            # Sharpe: std of returns
            sharpe = float(pnls.std() / abs(pnls.mean())) if pnls.mean() != 0 else 0.0

            # Expectancy: (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
            expectancy = (win_rate * avg_win) + ((1.0 - win_rate) * avg_loss)

            metrics = RegimeMetrics(
                regime=regime,
                trade_count=len(pnls),
                winning_trades=len(winning),
                losing_trades=len(losing),
                win_rate=win_rate,
                gross_profit=gross_profit,
                gross_loss=gross_loss,
                profit_factor=pf,
                avg_win=avg_win,
                avg_loss=avg_loss,
                total_pnl=total_pnl,
                sharpe_ratio=sharpe,
                max_win=float(pnls.max()),
                max_loss=float(pnls.min()),
                expectancy=expectancy,
            )
            self.regime_stats[regime] = metrics

        return self.regime_stats

    def summary(self) -> str:
        """Return human-readable summary of regime performance."""
        if not self.regime_stats:
            return "No regime analysis available."

        lines = ["=== REGIME-SPECIFIC PERFORMANCE ===", ""]

        for regime in ['TRENDING_UP', 'TRENDING_DOWN', 'RANGE_BOUND', 'HIGH_VOLATILITY', 'TRANSITION']:
            if regime not in self.regime_stats:
                continue

            m = self.regime_stats[regime]
            if m.trade_count == 0:
                continue

            lines.append(f"{regime}")
            lines.append(f"  Trades: {m.trade_count} | Win Rate: {m.win_rate:.1%} | Profit Factor: {m.profit_factor:.2f}")
            lines.append(f"  Total P&L: ${m.total_pnl:,.0f} | Avg Win: ${m.avg_win:,.0f} | Avg Loss: ${m.avg_loss:,.0f}")
            lines.append(f"  Sharpe: {m.sharpe_ratio:.2f} | Expectancy: ${m.expectancy:,.0f}")
            lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Return regime metrics as a dict for JSON serialization."""
        return {
            regime: metrics.to_dict()
            for regime, metrics in self.regime_stats.items()
        }

    def identify_edge_sources(self) -> Dict[str, any]:
        """
        Identify which regimes contribute to the overall edge.

        Returns:
          - profitable_regimes: List of regimes with PF > 1.0
          - unprofitable_regimes: List of regimes with PF < 1.0
          - best_regime: Regime with highest profit factor
          - worst_regime: Regime with lowest profit factor (or highest loss)
          - regime_distribution: % of trades coming from each regime
        """
        if not self.regime_stats:
            return {}

        profitable = [r for r, m in self.regime_stats.items() if m.profit_factor > 1.0]
        unprofitable = [r for r, m in self.regime_stats.items() if m.profit_factor < 1.0]

        best_regime = max(self.regime_stats.items(), key=lambda x: x[1].profit_factor)[0]
        worst_regime = min(self.regime_stats.items(), key=lambda x: x[1].profit_factor)[0]

        total_trades = sum(m.trade_count for m in self.regime_stats.values())
        regime_dist = {
            r: m.trade_count / total_trades if total_trades > 0 else 0
            for r, m in self.regime_stats.items()
        }

        return {
            'profitable_regimes': profitable,
            'unprofitable_regimes': unprofitable,
            'best_regime': best_regime,
            'best_pf': round(self.regime_stats[best_regime].profit_factor, 3),
            'worst_regime': worst_regime,
            'worst_pf': round(self.regime_stats[worst_regime].profit_factor, 3),
            'regime_distribution': {r: round(pct, 3) for r, pct in regime_dist.items()},
        }
