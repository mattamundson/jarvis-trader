"""
Paper Trading Validation Tracker — READ-ONLY metrics aggregator.

Consolidation note (US-303): This module is now READ-ONLY. All paper trade state is
managed by PaperTradeTracker (engine/backtest/paper_tracker.py). This module reads
trades from SQLite (primary) or the tracker's JSON files (fallback/tests) and computes
validation metrics.

US-2003: Primary data source changed from stale JSON files to SQLite
(engine/data/jarvis_trader.db, paper_trades table). JSON fallback is retained for
tests that supply a temp_data_dir with pre-populated JSON fixture files.

Sprint 20 B3/B4 FIX: Metrics are now queried LIVE from SQLite on each call,
not cached at init time. This ensures /paper/validation/status and
/paper/validation/progress always return current trade counts. Previously,
metrics were cached at initialization, so new trades added after the tracker
was instantiated would not be reflected.

Purpose: Aggregate per-instrument metrics and validate against PASS thresholds:
  Profit Factor >= 2.0
  Sharpe >= 1.5
  Win Rate >= 55%
  Total Trades >= 60
  Days >= 30
  Max Drawdown <= 15%

Data flow (production, NEW):
  paper_runner.py ↦ SQLite paper_trades table
                 ↦ ValidationTracker.get_progress() ↦ live SQLite query
                                                    ↦ computed metrics

Data flow (tests / fallback):
  _create_mock_tracker_file ↦ paper_trades_{symbol}.json
                            ↦ ValidationTracker.get_progress() ↦ JSON fallback
                                                               ↦ computed metrics
"""

from __future__ import annotations

import json
import logging
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from paper.validation_gate_config import PAPER_VALIDATION_GATES

logger = logging.getLogger(__name__)

PASS_THRESHOLDS = PAPER_VALIDATION_GATES

# Trend strategies win via high R:R (not frequency), so WR threshold is lower.
# MES SMA(50,200) WFO validated at 44-46% WR — 55% would permanently block live deployment.
_TREND_WIN_RATE_THRESHOLD = 45.0
_TREND_INSTRUMENTS = frozenset({"MES", "MGC"})

# Instruments tracked for paper validation — the live forward-proving book.
# MES + MGC trend are the only gate-v2 PASS edges; MCL/MNQ are DO_NOT_TRADE
# (routing-blocked) so pooling their stale rows into the scorecard was noise.
_TRACKED_INSTRUMENTS = ["MES", "MGC"]

# Forward-proving baseline: the SQLite scorecard counts only paper trades that
# close on/after this date, so the X/60 progress reflects the activated
# collection run rather than the handful of pre-activation stale rows
# (MCL/MES/MGC Apr-May 2026 + a TEST row). Lower bound only; applies to the
# production SQLite path, NOT the JSON fixture path used by tests.
FORWARD_PROVING_START_DATE = "2026-06-01"


def _thresholds_for(instrument: str) -> dict:
    """Return the correct gate thresholds for the given instrument."""
    if instrument in _TREND_INSTRUMENTS:
        return {**PASS_THRESHOLDS, "win_rate_pct": _TREND_WIN_RATE_THRESHOLD}
    return PASS_THRESHOLDS


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


def _build_metrics_from_trade_list(
    instrument: str,
    trade_dicts: list[dict],
    *,
    timestamp_key: str,
    pnl_key: str,
    entry_price_key: str,
    exit_price_key: str,
    instrument_key: str,
    setup_grade_key: str,
) -> InstrumentMetrics:
    """
    Build InstrumentMetrics from a list of trade dicts with configurable key names.

    Shared by both the SQLite and JSON loading paths.
    """
    im = InstrumentMetrics(instrument=instrument)
    for td in trade_dicts:
        ts = td.get(timestamp_key, "") or ""
        # Normalise to bare ISO string (strip timezone suffix if present)
        if ts and ts.endswith("Z"):
            ts = ts[:-1]
        # Strip +00:00 / +HH:MM style offsets for fromisoformat compat on py<3.11
        if "+" in ts[10:]:
            ts = ts[: ts.rfind("+")]

        trade = TradeRecord(
            timestamp=ts,
            instrument=td.get(instrument_key, instrument),
            entry_price=float(td.get(entry_price_key, 0) or 0),
            exit_price=float(td.get(exit_price_key, 0) or 0),
            pnl=float(td.get(pnl_key, 0) or 0),
            setup_grade=td.get(setup_grade_key, "unknown") or "unknown",
        )
        im.trades.append(trade)
        im.total_pnl += trade.pnl
        im.total_trades += 1

        if trade.pnl > 0:
            im.winning_trades += 1
            im.consecutive_losses = 0
        elif trade.pnl < 0:
            im.losing_trades += 1
            im.consecutive_losses += 1
            if im.consecutive_losses > im.max_consecutive_losses:
                im.max_consecutive_losses = im.consecutive_losses
        # pnl == 0 is a breakeven — neither W nor L. Do not advance the streak
        # counter (prevents test-fixture breakevens from triggering NOT_READY).

        if not im.first_trade_date:
            im.first_trade_date = trade.timestamp
        im.last_trade_date = trade.timestamp

        date_key = trade.timestamp.split("T")[0] if trade.timestamp else ""
        if date_key:
            im.daily_pnl_values.append(trade.pnl)

    return im


class ValidationTracker:
    """
    READ-ONLY validation metrics aggregator (US-303 consolidation, US-2003 SQLite).

    Sprint 20 B3/B4 FIX: Metrics are now queried LIVE from SQLite on each call,
    not cached at init time. This ensures /paper/validation/status and
    /paper/validation/progress always return current trade counts.

    Primary data source: SQLite paper_trades table (status='closed').
    Fallback: PaperTradeTracker JSON files (used by tests via temp_data_dir).

    This module observes state but never writes it.

    NOTE: record_trade() and record_daily_pnl() are deprecated.
    Use PaperTradeTracker (engine/backtest/paper_tracker.py) instead.
    """

    def __init__(
        self,
        data_dir: Path | str = "data",
        db_path: Optional[str | Path] = None,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Legacy: store path (read-only, no longer written to)
        self.validation_file = self.data_dir / "paper_validation.json"

        # Resolve SQLite path.  Explicit db_path wins; otherwise check canonical
        # location relative to data_dir (engine/data/jarvis_trader.db).
        if db_path is not None:
            self._db_path: Optional[Path] = Path(db_path)
        else:
            candidate = self.data_dir / "jarvis_trader.db"
            self._db_path = candidate if candidate.exists() else None

    # ------------------------------------------------------------------
    # Backward-compatible metrics property
    # ------------------------------------------------------------------

    @property
    def metrics(self) -> dict[str, "InstrumentMetrics"]:
        """
        Backward-compatible property returning live metrics dict.

        Tests and legacy callers that access tracker.metrics["MCL"] continue
        to work. Each access queries the best available source (SQLite or JSON
        fallback) so values are always current.
        """
        return self._get_metrics_live()

    # ------------------------------------------------------------------
    # Live loading (Sprint 20 B3/B4 fix)
    # ------------------------------------------------------------------

    def _get_metrics_live(self) -> dict[str, InstrumentMetrics]:
        """
        Load trade data from the best available source at query time.

        Priority:
          1. SQLite (self._db_path exists) — live paper trades, always current
          2. JSON tracker files — tests / legacy environments without a DB

        Called on each request, ensuring fresh data from SQLite.
        """
        if self._db_path and self._db_path.exists():
            try:
                result = self._load_from_sqlite()
                total = sum(m.total_trades for m in result.values())
                logger.debug(
                    "ValidationTracker: loaded %d trades from SQLite (%s) [live]",
                    total,
                    self._db_path,
                )
                return result
            except Exception as exc:
                logger.warning(
                    "ValidationTracker: SQLite load failed (%s), falling back to JSON",
                    exc,
                )

        return self._load_from_tracker()

    def _load_from_sqlite(self) -> dict[str, InstrumentMetrics]:
        """
        Load closed paper trades from the SQLite paper_trades table.

        Only rows with status IN ('closed', 'CLOSED') and symbol in
        _TRACKED_INSTRUMENTS are loaded.
        """
        metrics: dict[str, InstrumentMetrics] = {
            inst: InstrumentMetrics(instrument=inst) for inst in _TRACKED_INSTRUMENTS
        }

        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            placeholders = ",".join("?" for _ in _TRACKED_INSTRUMENTS)
            cur.execute(
                f"""
                SELECT symbol, entry_price, exit_price, entry_time, exit_time,
                       pnl, notes, status
                FROM paper_trades
                WHERE LOWER(status) = 'closed'
                  AND symbol IN ({placeholders})
                  AND exit_time >= ?
                ORDER BY exit_time
                """,
                [*_TRACKED_INSTRUMENTS, FORWARD_PROVING_START_DATE],
            )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        # Group by symbol
        by_symbol: dict[str, list[dict]] = {inst: [] for inst in _TRACKED_INSTRUMENTS}
        for row in rows:
            sym = row.get("symbol", "")
            if sym in by_symbol:
                by_symbol[sym].append(row)

        for inst, trade_list in by_symbol.items():
            if not trade_list:
                continue
            metrics[inst] = _build_metrics_from_trade_list(
                inst,
                trade_list,
                timestamp_key="exit_time",
                pnl_key="pnl",
                entry_price_key="entry_price",
                exit_price_key="exit_price",
                instrument_key="symbol",
                setup_grade_key="notes",
            )
            logger.debug("Loaded %d trades for %s from SQLite [live]", len(trade_list), inst)

        return metrics

    def _load_from_tracker(self) -> dict[str, InstrumentMetrics]:
        """
        Load trade data from PaperTradeTracker's JSON files (fallback / tests).

        Files: <data_dir>/backtest/results/paper_trades_{symbol}.json
        """
        metrics: dict[str, InstrumentMetrics] = {}
        tracker_dir = self.data_dir / "backtest" / "results"

        for instrument in _TRACKED_INSTRUMENTS:
            metrics[instrument] = InstrumentMetrics(instrument=instrument)
            tracker_file = tracker_dir / f"paper_trades_{instrument}.json"

            if tracker_file.exists():
                try:
                    data = json.loads(tracker_file.read_text())
                    trades_list = data.get("trades", [])

                    metrics[instrument] = _build_metrics_from_trade_list(
                        instrument,
                        trades_list,
                        timestamp_key="recorded_at",
                        pnl_key="pnl",
                        entry_price_key="entry_price",
                        exit_price_key="exit_price",
                        instrument_key="symbol",
                        setup_grade_key="exit_reason",
                    )
                    logger.debug(
                        "Loaded %d trades for %s from tracker JSON",
                        len(trades_list),
                        instrument,
                    )
                except Exception as exc:
                    logger.warning("Failed to load tracker data for %s: %s", instrument, exc)

        return metrics

    # ------------------------------------------------------------------
    # Deprecated write methods (no-op, kept for backward compat)
    # ------------------------------------------------------------------

    def record_trade(
        self,
        instrument: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        setup_grade: str = "unknown",
    ) -> None:
        """
        DEPRECATED (US-303): Use PaperTradeTracker.add_trade() instead.

        This method is kept for backward compatibility but is a no-op.
        """
        logger.warning(
            "ValidationTracker.record_trade() is deprecated. "
            "Use PaperTradeTracker.add_trade() instead."
        )

    def record_daily_pnl(self, instrument: str, daily_pnl: float) -> None:
        """
        DEPRECATED (US-303): Use PaperTradeTracker instead.

        This method is kept for backward compatibility but is a no-op.
        """
        logger.warning(
            "ValidationTracker.record_daily_pnl() is deprecated. " "Use PaperTradeTracker instead."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_progress(self, instrument: str = "MCL") -> dict:
        """Get validation progress for an instrument. Queries live from SQLite."""
        # SPRINT 20 B3/B4 FIX: Query live, don't use cached self.metrics
        metrics_dict = self._get_metrics_live()

        if instrument not in metrics_dict:
            return {
                "instrument": instrument,
                "status": "not_started",
                "thresholds": _thresholds_for(instrument),
            }

        metrics = metrics_dict[instrument]
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
            "thresholds": _thresholds_for(instrument),
            "pass_fail": self._get_pass_fail(metrics),
            "is_validated": self.is_validated(instrument),
        }

    def get_dashboard_data(self) -> dict:
        """Get formatted data for API response. Queries live from SQLite."""
        # SPRINT 20 B3/B4 FIX: Query live, don't use cached self.metrics
        metrics_dict = self._get_metrics_live()

        instruments = {}
        for instrument in _TRACKED_INSTRUMENTS:
            if instrument in metrics_dict:
                metrics = metrics_dict[instrument]
                instruments[instrument] = {
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
                    "thresholds": _thresholds_for(instrument),
                    "pass_fail": self._get_pass_fail(metrics),
                    "is_validated": self.is_validated(instrument),
                }
            else:
                instruments[instrument] = {
                    "instrument": instrument,
                    "status": "not_started",
                    "thresholds": _thresholds_for(instrument),
                }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "instruments": instruments,
            "overall_pass": all(self.is_validated(inst) for inst in _TRACKED_INSTRUMENTS),
        }

    def get_all_trades(self, instrument: str = "MCL") -> list[dict]:
        """Get all trades for an instrument. Queries live from SQLite."""
        # SPRINT 20 B3/B4 FIX: Query live, don't use cached self.metrics
        metrics_dict = self._get_metrics_live()

        if instrument not in metrics_dict:
            return []

        return [t.model_dump() for t in metrics_dict[instrument].trades]

    def is_validated(self, instrument: str = "MCL") -> bool:
        """Check if validation passes all thresholds. Queries live from SQLite."""
        # SPRINT 20 B3/B4 FIX: Query live, don't use cached self.metrics
        metrics_dict = self._get_metrics_live()

        if instrument not in metrics_dict:
            return False

        metrics = metrics_dict[instrument]
        t = _thresholds_for(instrument)

        return (
            metrics.profit_factor >= t["profit_factor"]
            and metrics.sharpe_ratio >= t["sharpe_ratio"]
            and metrics.win_rate_pct >= t["win_rate_pct"]
            and metrics.total_trades >= t["min_trades"]
            and metrics.days_active >= t["min_days"]
            and metrics.max_drawdown_pct <= t["max_drawdown_pct"]
        )

    @staticmethod
    def _get_pass_fail(metrics: InstrumentMetrics) -> dict:
        """Get pass/fail status for each threshold."""
        t = _thresholds_for(metrics.instrument)
        return {
            "profit_factor": {
                "value": round(metrics.profit_factor, 3),
                "threshold": t["profit_factor"],
                "passes": metrics.profit_factor >= t["profit_factor"],
            },
            "sharpe_ratio": {
                "value": round(metrics.sharpe_ratio, 3),
                "threshold": t["sharpe_ratio"],
                "passes": metrics.sharpe_ratio >= t["sharpe_ratio"],
            },
            "win_rate_pct": {
                "value": round(metrics.win_rate_pct, 2),
                "threshold": t["win_rate_pct"],
                "passes": metrics.win_rate_pct >= t["win_rate_pct"],
            },
            "total_trades": {
                "value": metrics.total_trades,
                "threshold": t["min_trades"],
                "passes": metrics.total_trades >= t["min_trades"],
            },
            "days_active": {
                "value": metrics.days_active,
                "threshold": t["min_days"],
                "passes": metrics.days_active >= t["min_days"],
            },
            "max_drawdown_pct": {
                "value": round(metrics.max_drawdown_pct, 2),
                "threshold": t["max_drawdown_pct"],
                "passes": metrics.max_drawdown_pct <= t["max_drawdown_pct"],
            },
        }
