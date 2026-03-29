"""
JARVIS TRADER — Paper Trading Portfolio Tracker
================================================
Tracks simulated trades and computes P&L without a broker connection.

Storage: engine/portfolio/trades.jsonl — one JSON object per line, append-only.
All arithmetic uses plain Python floats. No external dependencies.

Trade lifecycle
---------------
1. Pipeline decides action != "hold"  →  open_trade()  →  returns trade_id
2. Pipeline decides to exit           →  close_trade()  →  returns completed PaperTrade

P&L calculation (long):   (exit_price - entry_price) * quantity
P&L calculation (short):  (entry_price - exit_price) * quantity
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("jarvis_trader.portfolio")

# Default storage path — sits next to this file at engine/portfolio/trades.jsonl
_DEFAULT_STORE = Path(__file__).parent / "trades.jsonl"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class PaperTrade:
    """Represents a single simulated trade, open or closed."""

    trade_id: str
    symbol: str
    action: str            # "buy" | "sell" | "buy_to_open" | "sell_to_open" etc.
    quantity: float
    entry_price: float
    entry_time: str        # ISO-8601

    # Filled in on close
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    pnl: Optional[float] = None
    notes: str = ""

    # Derived convenience
    is_open: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PaperTrade":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Tracker ───────────────────────────────────────────────────────────────────

class PortfolioTracker:
    """
    Lightweight paper-trade ledger.

    Thread-safety: not required — FastAPI runs in a single async event loop and
    all mutations are synchronous (file I/O) before returning to the caller.
    """

    def __init__(self, store_path: Path = _DEFAULT_STORE):
        self._store = store_path
        self._store.parent.mkdir(parents=True, exist_ok=True)

        # In-memory state
        self._open: Dict[str, PaperTrade] = {}    # trade_id → PaperTrade
        self._closed: List[PaperTrade] = []

        self._load_history()
        logger.info(
            f"PortfolioTracker ready — {len(self._closed)} closed trades, "
            f"{len(self._open)} open positions loaded from {self._store}"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def open_trade(
        self,
        symbol: str,
        action: str,
        quantity: float,
        price: float,
        notes: str = "",
    ) -> str:
        """
        Log a new simulated entry.

        Returns the trade_id (UUID4) assigned to this trade.
        Persists immediately to trades.jsonl.
        """
        trade_id = str(uuid.uuid4())
        trade = PaperTrade(
            trade_id=trade_id,
            symbol=symbol.upper(),
            action=action.lower(),
            quantity=float(quantity),
            entry_price=float(price),
            entry_time=datetime.utcnow().isoformat(),
            notes=notes,
            is_open=True,
        )
        self._open[trade_id] = trade
        self._append_record(trade)
        logger.info(
            f"[PAPER] OPEN  {symbol.upper()} {action.upper()} "
            f"qty={quantity} @ {price:.4f}  id={trade_id[:8]}"
        )
        return trade_id

    def close_trade(self, trade_id: str, exit_price: float) -> PaperTrade:
        """
        Close an open trade and compute P&L.

        Raises KeyError if trade_id is not found in open positions.
        Persists the closed record to trades.jsonl.
        """
        trade = self._open.pop(trade_id, None)
        if trade is None:
            raise KeyError(f"No open trade with id={trade_id!r}")

        trade.exit_price = float(exit_price)
        trade.exit_time = datetime.utcnow().isoformat()
        trade.is_open = False

        # Direction: actions containing "sell" or "short" are short; everything else long
        action_lower = trade.action.lower()
        is_short = "sell" in action_lower or "short" in action_lower
        if is_short:
            trade.pnl = (trade.entry_price - exit_price) * trade.quantity
        else:
            trade.pnl = (exit_price - trade.entry_price) * trade.quantity

        self._closed.append(trade)
        self._append_record(trade)

        logger.info(
            f"[PAPER] CLOSE {trade.symbol} @ {exit_price:.4f}  "
            f"pnl={trade.pnl:+.2f}  id={trade_id[:8]}"
        )
        return trade

    def get_open_positions(self) -> List[dict]:
        """Return all currently open trades as dicts, newest first."""
        return [t.to_dict() for t in sorted(
            self._open.values(),
            key=lambda t: t.entry_time,
            reverse=True,
        )]

    def get_performance(self) -> dict:
        """
        Compute summary performance metrics across all closed trades.

        Returns
        -------
        dict with keys:
            total_pnl        : sum of all closed P&L
            win_rate         : fraction of winning trades (0–1)
            profit_factor    : gross_profit / gross_loss  (None if no losses)
            num_trades       : count of closed trades
            num_open         : count of currently open positions
            avg_win          : average P&L of winning trades
            avg_loss         : average P&L of losing trades (negative value)
            max_dd           : maximum drawdown from peak equity (negative or 0)
            best_trade       : highest single-trade P&L
            worst_trade      : lowest single-trade P&L
        """
        closed = self._closed
        if not closed:
            return {
                "total_pnl": 0.0,
                "win_rate": 0.0,
                "profit_factor": None,
                "num_trades": 0,
                "num_open": len(self._open),
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "max_dd": 0.0,
                "best_trade": None,
                "worst_trade": None,
            }

        pnls = [t.pnl for t in closed if t.pnl is not None]

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0

        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

        # Equity curve for max drawdown
        peak = 0.0
        equity = 0.0
        max_dd = 0.0
        for p in pnls:
            equity += p
            if equity > peak:
                peak = equity
            dd = equity - peak
            if dd < max_dd:
                max_dd = dd

        return {
            "total_pnl": round(sum(pnls), 4),
            "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
            "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            "num_trades": len(pnls),
            "num_open": len(self._open),
            "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
            "max_dd": round(max_dd, 4),
            "best_trade": round(max(pnls), 4) if pnls else None,
            "worst_trade": round(min(pnls), 4) if pnls else None,
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _append_record(self, trade: PaperTrade) -> None:
        """Append a single trade record to the JSONL store (append-only)."""
        try:
            with self._store.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(trade.to_dict()) + "\n")
        except OSError as exc:
            logger.error(f"Failed to persist trade {trade.trade_id[:8]}: {exc}")

    def _load_history(self) -> None:
        """
        Replay trades.jsonl on startup.

        Strategy: for each trade_id, keep the LAST record written (which has
        the most complete data — the closed record supersedes the open record).
        After replay, separate into open vs closed buckets.
        """
        if not self._store.exists():
            return

        by_id: Dict[str, dict] = {}
        try:
            with self._store.open("r", encoding="utf-8") as fh:
                for line_num, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        trade_id = record.get("trade_id")
                        if trade_id:
                            by_id[trade_id] = record
                    except json.JSONDecodeError as exc:
                        logger.warning(f"Skipping malformed line {line_num} in trades.jsonl: {exc}")
        except OSError as exc:
            logger.error(f"Could not read trades.jsonl: {exc}")
            return

        for record in by_id.values():
            try:
                trade = PaperTrade.from_dict(record)
                if trade.is_open:
                    self._open[trade.trade_id] = trade
                else:
                    self._closed.append(trade)
            except (TypeError, KeyError) as exc:
                logger.warning(f"Skipping bad trade record {record.get('trade_id', '?')}: {exc}")

        # Sort closed trades chronologically
        self._closed.sort(key=lambda t: t.entry_time)


# ── Singleton ─────────────────────────────────────────────────────────────────

_tracker: Optional[PortfolioTracker] = None


def get_tracker() -> PortfolioTracker:
    """Return the module-level singleton tracker, creating it on first call."""
    global _tracker
    if _tracker is None:
        _tracker = PortfolioTracker()
    return _tracker
