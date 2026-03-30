"""
JARVIS TRADER — Paper Trading Portfolio Tracker
================================================
Tracks simulated trades and computes P&L without a broker connection.

Storage (dual-mode):
  - Without db_manager: engine/portfolio/trades.jsonl  — one JSON object per line,
    append-only (original behaviour, fully backward compatible).
  - With db_manager:    SQLite via DatabaseManager — all state persisted immediately;
    JSONL file is still written as a secondary audit log.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.portfolio")

# Default JSONL storage path — sits next to this file at engine/portfolio/trades.jsonl
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
    Lightweight paper-trade ledger with optional SQLite persistence.

    Parameters
    ----------
    store_path : Path
        Path to the JSONL audit log (always written).
    db_manager : optional DatabaseManager
        When provided, all trades and positions are also persisted to SQLite
        and loaded from SQLite on startup.  DB errors are caught and logged;
        they never crash the tracker (falls back to in-memory state).

    Thread-safety: not required — FastAPI runs in a single async event loop and
    all mutations are synchronous (file I/O) before returning to the caller.
    """

    def __init__(
        self,
        store_path: Path = _DEFAULT_STORE,
        db_manager: Any = None,
    ):
        self._store = store_path
        self._store.parent.mkdir(parents=True, exist_ok=True)

        self._db = db_manager  # may be None

        # In-memory state
        self._open: Dict[str, PaperTrade] = {}    # trade_id → PaperTrade
        self._closed: List[PaperTrade] = []
        # Symbol-keyed live positions (richer dict kept in sync with DB when available)
        self._positions: Dict[str, dict] = {}     # symbol → position dict

        # Load from DB first (if available), then overlay JSONL for audit integrity
        if self._db is not None:
            self._load_from_db()
        self._load_history()

        logger.info(
            "PortfolioTracker ready — %d closed trades, %d open positions%s",
            len(self._closed),
            len(self._open),
            " (SQLite)" if self._db is not None else " (JSONL only)",
        )

    # ── Public API — original methods (backward compatible) ───────────────────

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
        Persists immediately to trades.jsonl (and SQLite if db_manager set).
        """
        trade_id = str(uuid.uuid4())
        trade = PaperTrade(
            trade_id=trade_id,
            symbol=symbol.upper(),
            action=action.lower(),
            quantity=float(quantity),
            entry_price=float(price),
            entry_time=datetime.now(timezone.utc).isoformat(),
            notes=notes,
            is_open=True,
        )
        self._open[trade_id] = trade
        self._append_record(trade)

        # SQLite persistence
        if self._db is not None:
            try:
                self._db.insert_paper_trade(
                    symbol=trade.symbol,
                    side=trade.action,
                    quantity=trade.quantity,
                    entry_price=trade.entry_price,
                    entry_time=trade.entry_time,
                    stop_loss=None,
                    take_profit=None,
                    strategy_params={"notes": notes},
                )
            except Exception as exc:
                logger.error("DB insert_paper_trade failed for %s: %s", trade_id[:8], exc)

        logger.info(
            "[PAPER] OPEN  %s %s qty=%s @ %.4f  id=%s",
            symbol.upper(), action.upper(), quantity, price, trade_id[:8],
        )
        return trade_id

    def close_trade(self, trade_id: str, exit_price: float) -> PaperTrade:
        """
        Close an open trade and compute P&L.

        Raises KeyError if trade_id is not found in open positions.
        Persists the closed record to trades.jsonl (and SQLite if db_manager set).
        """
        trade = self._open.pop(trade_id, None)
        if trade is None:
            raise KeyError(f"No open trade with id={trade_id!r}")

        trade.exit_price = float(exit_price)
        trade.exit_time = datetime.now(timezone.utc).isoformat()
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

        # SQLite persistence
        if self._db is not None:
            try:
                self._db.close_paper_trade(
                    trade_id=trade_id,
                    exit_price=trade.exit_price,
                    exit_time=trade.exit_time,
                    pnl=trade.pnl,
                )
            except Exception as exc:
                logger.error("DB close_paper_trade failed for %s: %s", trade_id[:8], exc)

        logger.info(
            "[PAPER] CLOSE %s @ %.4f  pnl=%+.2f  id=%s",
            trade.symbol, exit_price, trade.pnl, trade_id[:8],
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

    # ── Public API — extended methods (used by db_manager callers) ────────────

    def add_paper_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        entry_time: Optional[str] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        strategy_params: Optional[dict] = None,
    ) -> str:
        """
        Extended entry point that accepts the full DB-style parameter set.

        Delegates to open_trade() for in-memory state and JSONL; writes the
        richer fields (stop_loss, take_profit, strategy_params) to SQLite.

        Returns the trade_id string.
        """
        notes = json.dumps(strategy_params) if strategy_params else ""
        trade_id = str(uuid.uuid4())
        trade = PaperTrade(
            trade_id=trade_id,
            symbol=symbol.upper(),
            action=side.lower(),
            quantity=float(quantity),
            entry_price=float(entry_price),
            entry_time=entry_time or datetime.now(timezone.utc).isoformat(),
            notes=notes,
            is_open=True,
        )
        self._open[trade_id] = trade
        self._append_record(trade)

        if self._db is not None:
            try:
                self._db.insert_paper_trade(
                    symbol=trade.symbol,
                    side=side,
                    quantity=float(quantity),
                    entry_price=float(entry_price),
                    entry_time=trade.entry_time,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    strategy_params=strategy_params,
                )
            except Exception as exc:
                logger.error("DB insert_paper_trade (add_paper_trade) failed for %s: %s", trade_id[:8], exc)

        logger.info(
            "[PAPER] ADD   %s %s qty=%s @ %.4f  sl=%s tp=%s  id=%s",
            symbol.upper(), side.upper(), quantity, entry_price,
            stop_loss, take_profit, trade_id[:8],
        )
        return trade_id

    def close_paper_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_time: Optional[str] = None,
        pnl: Optional[float] = None,
    ) -> PaperTrade:
        """
        Extended close entry point that accepts an explicit exit_time and pnl.

        When pnl is provided it is used directly (e.g., broker-confirmed figure).
        Falls back to close_trade() for in-memory state; writes to SQLite.

        Raises KeyError if trade_id is unknown.
        """
        trade = self._open.pop(trade_id, None)
        if trade is None:
            raise KeyError(f"No open trade with id={trade_id!r}")

        trade.exit_price = float(exit_price)
        trade.exit_time = exit_time or datetime.now(timezone.utc).isoformat()
        trade.is_open = False

        if pnl is not None:
            trade.pnl = float(pnl)
        else:
            action_lower = trade.action.lower()
            is_short = "sell" in action_lower or "short" in action_lower
            if is_short:
                trade.pnl = (trade.entry_price - exit_price) * trade.quantity
            else:
                trade.pnl = (exit_price - trade.entry_price) * trade.quantity

        self._closed.append(trade)
        self._append_record(trade)

        if self._db is not None:
            try:
                self._db.close_paper_trade(
                    trade_id=trade_id,
                    exit_price=trade.exit_price,
                    exit_time=trade.exit_time,
                    pnl=trade.pnl,
                )
            except Exception as exc:
                logger.error("DB close_paper_trade failed for %s: %s", trade_id[:8], exc)

        logger.info(
            "[PAPER] CLOSE %s @ %.4f  pnl=%+.2f  id=%s",
            trade.symbol, exit_price, trade.pnl, trade_id[:8],
        )
        return trade

    def update_position(
        self,
        symbol: str,
        current_price: float,
        unrealized_pnl: Optional[float] = None,
        quantity: Optional[float] = None,
        entry_price: Optional[float] = None,
        entry_time: Optional[str] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> dict:
        """
        Upsert a live position in the in-memory positions dict and SQLite.

        If the symbol is not yet tracked, a new position record is inserted.
        Returns the current position dict.
        """
        symbol = symbol.upper()
        now = datetime.now(timezone.utc).isoformat()

        if symbol not in self._positions:
            # Create position record
            pos: dict = {
                "symbol": symbol,
                "quantity": quantity or 0.0,
                "entry_price": entry_price or current_price,
                "entry_time": entry_time or now,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "current_price": current_price,
                "unrealized_pnl": unrealized_pnl or 0.0,
            }
            self._positions[symbol] = pos

            if self._db is not None:
                try:
                    self._db.insert_position(
                        symbol=symbol,
                        quantity=pos["quantity"],
                        entry_price=pos["entry_price"],
                        entry_time=pos["entry_time"],
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                    )
                except Exception as exc:
                    logger.error("DB insert_position failed for %s: %s", symbol, exc)
        else:
            pos = self._positions[symbol]
            if quantity is not None:
                pos["quantity"] = float(quantity)
            if entry_price is not None:
                pos["entry_price"] = float(entry_price)
            if stop_loss is not None:
                pos["stop_loss"] = float(stop_loss)
            if take_profit is not None:
                pos["take_profit"] = float(take_profit)
            pos["current_price"] = float(current_price)
            if unrealized_pnl is not None:
                pos["unrealized_pnl"] = float(unrealized_pnl)

        if self._db is not None:
            try:
                self._db.update_position(
                    symbol=symbol,
                    current_price=float(current_price),
                    unrealized_pnl=self._positions[symbol].get("unrealized_pnl", 0.0),
                )
            except Exception as exc:
                logger.error("DB update_position failed for %s: %s", symbol, exc)

        return self._positions[symbol]

    def remove_position(self, symbol: str) -> None:
        """Remove a position from tracking (e.g., after full exit)."""
        symbol = symbol.upper()
        self._positions.pop(symbol, None)

        if self._db is not None:
            try:
                self._db.remove_position(symbol)
            except Exception as exc:
                logger.error("DB remove_position failed for %s: %s", symbol, exc)

    def get_positions(self) -> List[dict]:
        """
        Return all live positions as a list of dicts.

        When db_manager is set, fetches directly from SQLite for freshness.
        Falls back to the in-memory positions dict on DB error.
        """
        if self._db is not None:
            try:
                rows = self._db.get_open_positions()
                if rows is not None:
                    # Sync back into in-memory cache
                    self._positions = {r["symbol"]: r for r in rows}
                    return list(rows)
            except Exception as exc:
                logger.error("DB get_open_positions failed, using in-memory: %s", exc)

        return list(self._positions.values())

    def get_trade_history(self, limit: int = 100) -> List[dict]:
        """
        Return closed trade records, most-recent first.

        When db_manager is set, queries SQLite which may contain more history
        than the current session's in-memory list.  Falls back to in-memory on error.
        """
        if self._db is not None:
            try:
                rows = self._db.get_trade_history(limit=limit)
                if rows is not None:
                    return list(rows)
            except Exception as exc:
                logger.error("DB get_trade_history failed, using in-memory: %s", exc)

        return [t.to_dict() for t in reversed(self._closed[-limit:])]

    def get_performance_summary(self) -> dict:
        """
        Extended performance summary.

        Merges the standard get_performance() metrics with daily P&L data
        from SQLite when available.  Always safe to call.
        """
        base = self.get_performance()

        if self._db is not None:
            try:
                daily = self._db.get_daily_pnl(days=30)
                base["daily_pnl"] = daily if daily is not None else []
            except Exception as exc:
                logger.error("DB get_daily_pnl failed: %s", exc)
                base["daily_pnl"] = []
        else:
            base["daily_pnl"] = []

        return base

    # ── Persistence — JSONL (always on) ───────────────────────────────────────

    def _append_record(self, trade: PaperTrade) -> None:
        """Append a single trade record to the JSONL store (append-only audit log)."""
        try:
            with self._store.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(trade.to_dict()) + "\n")
        except OSError as exc:
            logger.error("Failed to persist trade %s to JSONL: %s", trade.trade_id[:8], exc)

    def _load_history(self) -> None:
        """
        Replay trades.jsonl on startup.

        Strategy: for each trade_id, keep the LAST record written (which has
        the most complete data — the closed record supersedes the open record).
        After replay, separate into open vs closed buckets.

        If db_manager is active this is a secondary reconciliation pass; DB
        state loaded by _load_from_db() takes precedence for open trades.
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
                        logger.warning("Skipping malformed line %d in trades.jsonl: %s", line_num, exc)
        except OSError as exc:
            logger.error("Could not read trades.jsonl: %s", exc)
            return

        for record in by_id.values():
            try:
                trade = PaperTrade.from_dict(record)
                if trade.is_open:
                    # Only add if not already loaded from DB
                    if trade.trade_id not in self._open:
                        self._open[trade.trade_id] = trade
                else:
                    # Only add if not already loaded from DB (deduplicate by trade_id)
                    existing_ids = {t.trade_id for t in self._closed}
                    if trade.trade_id not in existing_ids:
                        self._closed.append(trade)
            except (TypeError, KeyError) as exc:
                logger.warning(
                    "Skipping bad trade record %s: %s",
                    record.get("trade_id", "?"), exc,
                )

        # Sort closed trades chronologically
        self._closed.sort(key=lambda t: t.entry_time)

    # ── Persistence — SQLite (optional) ───────────────────────────────────────

    def _load_from_db(self) -> None:
        """
        Populate in-memory state from SQLite on startup.

        Called before _load_history() so JSONL replay can fill any gaps.
        Errors are caught; a DB failure at startup falls back to JSONL-only mode.
        """
        if self._db is None:
            return

        # Load open positions
        try:
            rows = self._db.get_open_positions()
            if rows:
                for row in rows:
                    symbol = row.get("symbol", "")
                    self._positions[symbol] = row
                logger.info("Loaded %d open positions from SQLite", len(rows))
        except Exception as exc:
            logger.error("DB get_open_positions at startup failed: %s", exc)

        # Load trade history
        try:
            rows = self._db.get_trade_history(limit=1000)
            if rows:
                for row in rows:
                    try:
                        # Map DB row fields to PaperTrade fields
                        trade = PaperTrade(
                            trade_id=str(row.get("trade_id") or row.get("id", str(uuid.uuid4()))),
                            symbol=str(row.get("symbol", "")),
                            action=str(row.get("side") or row.get("action", "")),
                            quantity=float(row.get("quantity", 0)),
                            entry_price=float(row.get("entry_price", 0)),
                            entry_time=str(row.get("entry_time", "")),
                            exit_price=row.get("exit_price"),
                            exit_time=row.get("exit_time"),
                            pnl=row.get("pnl"),
                            notes=str(row.get("notes") or ""),
                            is_open=bool(row.get("is_open", row.get("exit_price") is None)),
                        )
                        if trade.is_open:
                            self._open[trade.trade_id] = trade
                        else:
                            self._closed.append(trade)
                    except (TypeError, KeyError, ValueError) as exc:
                        logger.warning("Skipping bad DB trade row: %s", exc)
                logger.info(
                    "Loaded %d trades from SQLite (%d open, %d closed)",
                    len(rows),
                    sum(1 for r in rows if r.get("is_open", r.get("exit_price") is None)),
                    sum(1 for r in rows if not r.get("is_open", r.get("exit_price") is None)),
                )
        except Exception as exc:
            logger.error("DB get_trade_history at startup failed: %s", exc)

        self._closed.sort(key=lambda t: t.entry_time)


# ── Singleton ─────────────────────────────────────────────────────────────────

_tracker: Optional[PortfolioTracker] = None


def get_tracker(db_manager: Any = None) -> PortfolioTracker:
    """
    Return the module-level singleton tracker, creating it on first call.

    Pass db_manager on the first call to enable SQLite persistence.
    Subsequent calls return the existing instance regardless of db_manager.
    """
    global _tracker
    if _tracker is None:
        _tracker = PortfolioTracker(db_manager=db_manager)
    return _tracker
