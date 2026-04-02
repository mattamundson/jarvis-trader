"""
Paper Trading Validation Tracker — per-instrument metrics monitoring.

Tracks MCL 1h and MNQ 1h forward test metrics against PASS thresholds:
  Profit Factor >= 2.0
  Sharpe >= 1.5
  Win Rate >= 55%
  Total Trades >= 60
  Days >= 30
  Max Drawdown <= 15%

Stores results in data/paper_validation.json.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

PASS_THRESHOLDS = {
    "profit_factor": 2.0,
    "sharpe_ratio": 1.5,
    "win_rate_pct": 55.0,
    "min_trades": 60,
    "min_days": 30,
    "max_drawdown_pct": 15.0,
}


class TradeRecord(BaseModel):
    """Single trade record."""

    model_config = ConfigDict(from_attributes=True)

    timestamp: str
    instrument: str
    entry_price: float
    exit_price: float
    pnl: float
    setup_grade: str = "unknown"


class InstrumentMetrics(BaseModel):
    """Per-instrument validation metrics."""

    model_config = ConfigDict(from_attributes=True)

    instrument: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    daily_pnl_values: list[float] = Field(default_factory=list)
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    trades: list[TradeRecord] = Field(default_factory=list)
    first_trade_date: Optional[str] = None
    last_trade_date: Optional[str] = None

    @property
    def win_rate_pct(self) -> float:
        """Win rate as percentage."""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def profit_factor(self) -> float:
        """Gross profit / gross loss."""
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        if gross_loss <= 0:
            return gross_profit if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def sharpe_ratio(self) -> float:
        """Annualized Sharpe ratio from daily P&L."""
        if len(self.daily_pnl_values) < 2:
            return 0.0
        try:
            mean = statistics.mean(self.daily_pnl_values)
            std = statistics.stdev(self.daily_pnl_values)
            if std == 0:
                return 0.0
            return (mean / std) * (252**0.5)
        except Exception:
            return 0.0

    @property
    def max_drawdown_pct(self) -> float:
        """Maximum drawdown from cumulative P&L."""
        if not self.daily_pnl_values:
            return 0.0
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in self.daily_pnl_values:
            equity += pnl
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        return max_dd

    @property
    def days_active(self) -> int:
        """Days from first to last trade."""
        if not self.first_trade_date or not self.last_trade_date:
            return 0
        start = datetime.fromisoformat(self.first_trade_date)
        end = datetime.fromisoformat(self.last_trade_date)
        return max(1, (end - start).days + 1)

    @property
    def avg_r_multiple(self) -> float:
        """Average R-multiple (profit / risk)."""
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl / max(1, self.total_trades)


class ValidationTracker:
    """Tracks paper trading validation metrics per instrument."""

    def __init__(self, data_dir: Path | str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.validation_file = self.data_dir / "paper_validation.json"
        self.metrics: dict[str, InstrumentMetrics] = {}
        self._load()

    def _load(self) -> None:
        """Load validation data from JSON."""
        if self.validation_file.exists():
            try:
                data = json.loads(self.validation_file.read_text())
                for instrument, metrics_dict in data.items():
                    self.metrics[instrument] = InstrumentMetrics.model_validate(metrics_dict)
                logger.info(f"Loaded validation data for {len(self.metrics)} instruments")
            except Exception as e:
                logger.warning(f"Failed to load validation file: {e}")
                self.metrics = {}
        else:
            self.metrics = {
                "MCL": InstrumentMetrics(instrument="MCL"),
                "MNQ": InstrumentMetrics(instrument="MNQ"),
            }

    def _save(self) -> None:
        """Save validation data to JSON."""
        try:
            data = {inst: m.model_dump() for inst, m in self.metrics.items()}
            self.validation_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to save validation file: {e}")

    def record_trade(
        self,
        instrument: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        setup_grade: str = "unknown",
    ) -> None:
        """Record a trade and update metrics."""
        if instrument not in self.metrics:
            self.metrics[instrument] = InstrumentMetrics(instrument=instrument)

        metrics = self.metrics[instrument]
        timestamp = datetime.utcnow().isoformat()

        trade = TradeRecord(
            timestamp=timestamp,
            instrument=instrument,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            setup_grade=setup_grade,
        )
        metrics.trades.append(trade)
        metrics.total_pnl += pnl
        metrics.total_trades += 1

        if pnl > 0:
            metrics.winning_trades += 1
            metrics.consecutive_losses = 0
        else:
            metrics.losing_trades += 1
            metrics.consecutive_losses += 1
            if metrics.consecutive_losses > metrics.max_consecutive_losses:
                metrics.max_consecutive_losses = metrics.consecutive_losses

        if not metrics.first_trade_date:
            metrics.first_trade_date = timestamp
        metrics.last_trade_date = timestamp

        self._save()

    def record_daily_pnl(self, instrument: str, daily_pnl: float) -> None:
        """Record daily P&L for Sharpe/Drawdown calculations."""
        if instrument not in self.metrics:
            self.metrics[instrument] = InstrumentMetrics(instrument=instrument)

        self.metrics[instrument].daily_pnl_values.append(daily_pnl)
        self._save()

    def get_progress(self, instrument: str = "MCL") -> dict:
        """Get validation progress for an instrument."""
        if instrument not in self.metrics:
            return {
                "instrument": instrument,
                "status": "not_started",
                "thresholds": PASS_THRESHOLDS,
            }

        metrics = self.metrics[instrument]
        return {
            "instrument": instrument,
            "total_trades": metrics.total_trades,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "win_rate_pct": round(metrics.win_rate_pct, 2),
            "profit_factor": round(metrics.profit_factor, 3),
            "sharpe_ratio": round(metrics.sharpe_ratio, 3),
            "max_drawdown_pct": round(metrics.max_drawdown_pct, 2),
            "avg_r_multiple": round(metrics.avg_r_multiple, 3),
            "consecutive_losses": metrics.consecutive_losses,
            "max_consecutive_losses": metrics.max_consecutive_losses,
            "days_active": metrics.days_active,
            "total_pnl": round(metrics.total_pnl, 2),
            "thresholds": PASS_THRESHOLDS,
            "pass_fail": self._get_pass_fail(metrics),
            "is_validated": self.is_validated(instrument),
        }

    def get_dashboard_data(self) -> dict:
        """Get formatted data for API response."""
        instruments = {}
        for instrument in ["MCL", "MNQ"]:
            instruments[instrument] = self.get_progress(instrument)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "instruments": instruments,
            "overall_pass": all(self.is_validated(inst) for inst in ["MCL", "MNQ"]),
        }

    def get_all_trades(self, instrument: str = "MCL") -> list[dict]:
        """Get all trades for an instrument."""
        if instrument not in self.metrics:
            return []

        return [t.model_dump() for t in self.metrics[instrument].trades]

    def is_validated(self, instrument: str = "MCL") -> bool:
        """Check if validation passes all thresholds."""
        if instrument not in self.metrics:
            return False

        metrics = self.metrics[instrument]

        return (
            metrics.profit_factor >= PASS_THRESHOLDS["profit_factor"]
            and metrics.sharpe_ratio >= PASS_THRESHOLDS["sharpe_ratio"]
            and metrics.win_rate_pct >= PASS_THRESHOLDS["win_rate_pct"]
            and metrics.total_trades >= PASS_THRESHOLDS["min_trades"]
            and metrics.days_active >= PASS_THRESHOLDS["min_days"]
            and metrics.max_drawdown_pct <= PASS_THRESHOLDS["max_drawdown_pct"]
        )

    @staticmethod
    def _get_pass_fail(metrics: InstrumentMetrics) -> dict:
        """Get pass/fail status for each threshold."""
        return {
            "profit_factor": {
                "value": round(metrics.profit_factor, 3),
                "threshold": PASS_THRESHOLDS["profit_factor"],
                "passes": metrics.profit_factor >= PASS_THRESHOLDS["profit_factor"],
            },
            "sharpe_ratio": {
                "value": round(metrics.sharpe_ratio, 3),
                "threshold": PASS_THRESHOLDS["sharpe_ratio"],
                "passes": metrics.sharpe_ratio >= PASS_THRESHOLDS["sharpe_ratio"],
            },
            "win_rate_pct": {
                "value": round(metrics.win_rate_pct, 2),
                "threshold": PASS_THRESHOLDS["win_rate_pct"],
                "passes": metrics.win_rate_pct >= PASS_THRESHOLDS["win_rate_pct"],
            },
            "total_trades": {
                "value": metrics.total_trades,
                "threshold": PASS_THRESHOLDS["min_trades"],
                "passes": metrics.total_trades >= PASS_THRESHOLDS["min_trades"],
            },
            "days_active": {
                "value": metrics.days_active,
                "threshold": PASS_THRESHOLDS["min_days"],
                "passes": metrics.days_active >= PASS_THRESHOLDS["min_days"],
            },
            "max_drawdown_pct": {
                "value": round(metrics.max_drawdown_pct, 2),
                "threshold": PASS_THRESHOLDS["max_drawdown_pct"],
                "passes": metrics.max_drawdown_pct <= PASS_THRESHOLDS["max_drawdown_pct"],
            },
        }
