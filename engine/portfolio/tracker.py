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
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.portfolio")

# Default JSONL storage path — sits next to this file at engine/portfolio/trades.jsonl
_DEFAULT_STORE = Path(__file__).parent / "trades.jsonl"

# Contract multipliers — dollar value per point per contract
# MCL: micro crude oil (100 barrels × $0.01/barrel/tick → $1/tick, $100/point)
# MNQ: micro Nasdaq ($2/point)
# MES: micro E-mini S&P 500 ($5/point)
# MGC: micro gold (10 troy oz × $0.10/oz/tick → $1/tick, $10/point)
INSTRUMENT_MULTIPLIERS: dict = {
    "MCL": 100.0,
    "MNQ": 2.0,
    "MES": 5.0,
    "MGC": 10.0,
    "ES": 50.0,
    "NQ": 20.0,
    "CL": 1000.0,
    "GC": 100.0,
}
_DEFAULT_MULTIPLIER = 1.0


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class PaperTrade:
    """Represents a single simulated trade, open or closed."""

    trade_id: str
    symbol: str
    action: str  # "buy" | "sell" | "buy_to_open" | "sell_to_open" etc.
    quantity: float
    entry_price: float
    entry_time: str  # ISO-8601

    # Filled in on close
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    pnl: Optional[float] = None
    notes: str = ""

    # Derived convenience
    is_open: bool = True

    # Risk management fields
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    atr_value: Optional[float] = None  # ATR at entry — used for breakeven logic

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
        self._open: Dict[str, PaperTrade] = {}  # trade_id → PaperTrade
        self._closed: List[PaperTrade] = []
        # Symbol-keyed live positions (richer dict kept in sync with DB when available)
        self._positions: Dict[str, dict] = {}  # symbol → position dict

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
        atr_value: Optional[float] = None,
    ) -> str:
        """
        Log a new simulated entry.

        Returns the trade_id (UUID4) assigned to this trade.
        Persists immediately to trades.jsonl (and SQLite if db_manager set).

        Parameters
        ----------
        atr_value : float, optional
            ATR at entry time.  Stored on the trade for later use by
            check_and_move_breakeven().
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
            atr_value=atr_value,
        )

        # SQLite-first: write to DB before touching in-memory state.
        # If the DB write fails the exception propagates and in-memory is NOT updated,
        # preventing ghost positions on restart (Bug B9 / US-2004).
        if self._db is not None:
            self._db.insert_paper_trade(
                trade_id,
                symbol=trade.symbol,
                side=trade.action,
                quantity=trade.quantity,
                entry_price=trade.entry_price,
                entry_time=trade.entry_time,
                stop_loss=None,
                take_profit=None,
                strategy_params={"notes": notes},
            )

        # DB write succeeded (or no DB configured) — update in-memory and JSONL
        self._open[trade_id] = trade
        self._append_record(trade)

        logger.info(
            "[PAPER] OPEN  %s %s qty=%s @ %.4f  id=%s",
            symbol.upper(),
            action.upper(),
            quantity,
            price,
            trade_id[:8],
        )
        # Publish trade opened event
        try:
            from events.bus import publish as publish_event
            publish_event(
                'trade_opened',
                f'{symbol.upper()} {action.upper()} {quantity} @ {price}',
                symbol=symbol.upper(),
                severity='info'
            )
        except Exception:
            pass

        return trade_id

    def close_trade(self, trade_id: str, exit_price: float) -> PaperTrade:
        """
        Close an open trade and compute P&L.

        Raises KeyError if trade_id is not found in open positions.
        Persists the closed record to SQLite first (if db_manager set), then JSONL.
        If the SQLite write fails the exception propagates and in-memory state is
        left unchanged — preventing divergence on restart (Bug B9 / US-2004).
        """
        trade = self._open.get(trade_id)
        if trade is None:
            raise KeyError(f"No open trade with id={trade_id!r}")

        # Compute close fields on a local copy before any writes
        exit_time = datetime.now(timezone.utc).isoformat()
        action_lower = trade.action.lower()
        is_short = "sell" in action_lower or "short" in action_lower
        multiplier = INSTRUMENT_MULTIPLIERS.get(trade.symbol.upper(), _DEFAULT_MULTIPLIER)
        if is_short:
            computed_pnl = (trade.entry_price - exit_price) * trade.quantity * multiplier
        else:
            computed_pnl = (exit_price - trade.entry_price) * trade.quantity * multiplier

        # SQLite-first: write to DB before mutating in-memory state.
        # If this raises, _open is unchanged — no ghost position on restart.
        if self._db is not None:
            self._db.close_paper_trade(
                trade_id=trade_id,
                exit_price=float(exit_price),
                exit_time=exit_time,
                pnl=computed_pnl,
            )

        # DB write succeeded (or no DB) — now mutate in-memory and JSONL
        self._open.pop(trade_id)
        trade.exit_price = float(exit_price)
        trade.exit_time = exit_time
        trade.is_open = False
        trade.pnl = computed_pnl

        self._closed.append(trade)
        self._append_record(trade)

        logger.info(
            "[PAPER] CLOSE %s @ %.4f  pnl=%+.2f  mult=%.1f  id=%s",
            trade.symbol,
            exit_price,
            trade.pnl,
            multiplier,
            trade_id[:8],
        )

        # Trade quality classification (lazy, non-blocking)
        try:
            from learning._experimental.trade_classifier import TradeClassifier

            _cls = TradeClassifier().classify(
                {
                    "id": trade_id,
                    "pnl": trade.pnl or 0.0,
                    "risk": 0.0,
                    "entry_price": trade.entry_price or 0.0,
                    "exit_price": trade.exit_price or 0.0,
                    "time_in_trade": 0.0,
                    "target_atr": 0.0,
                    "regime": "UNKNOWN",
                }
            )
            logger.info(
                "[LEARNING] Trade %s classified: grade=%s setup=%.2f",
                str(trade_id)[:8],
                _cls.grade,
                _cls.setup_quality,
            )
        except Exception as _exc:
            logger.debug("[LEARNING] Trade classification skipped: %s", _exc)

        # Wire trade close event to learning feedback module (non-blocking, best-effort)
        try:
            import asyncio as _asyncio_fb
            import os as _os_fb

            from learning.feedback import process_trade_outcome as _process_feedback

            if not _os_fb.getenv("TESTING"):
                _loop_fb = _asyncio_fb.get_event_loop()
                if _loop_fb.is_running():
                    _loop_fb.create_task(
                        _process_feedback(
                            trade_id=trade_id,
                            symbol=trade.symbol,
                            pnl=trade.pnl or 0.0,
                            entry_price=trade.entry_price or 0.0,
                            exit_price=float(exit_price),
                            entry_time=trade.entry_time or "",
                            exit_time=exit_time,
                            action=trade.action or "",
                        )
                    )
                    logger.info("[LEARNING] Feedback queued for trade %s", str(trade_id)[:8])
        except Exception as _fb_exc:
            logger.debug("[LEARNING] Feedback generation skipped: %s", _fb_exc)

        # OpenClaw WhatsApp alert on trade close (non-blocking, best-effort)
        try:
            import asyncio as _asyncio
            import os as _os

            from notifications.openclaw_notifier import notify_trade_closed as _oc_close

            if not _os.getenv("TESTING"):
                _loop = _asyncio.get_event_loop()
                if _loop.is_running():
                    _loop.create_task(
                        _oc_close(
                            symbol=trade.symbol,
                            action=trade.action,
                            entry_price=trade.entry_price,
                            exit_price=float(exit_price),
                            pnl=trade.pnl or 0.0,
                            quantity=trade.quantity,
                        )
                    )
        except Exception as _oc_exc:
            logger.debug("[PAPER] OpenClaw trade-close notify skipped: %s", _oc_exc)

        # Publish trade closed event
        try:
            from events.bus import publish as publish_event
            severity = 'warn' if trade.pnl and trade.pnl < 0 else 'info'
            publish_event(
                'trade_closed',
                f'{trade.symbol} closed pnl={trade.pnl}',
                symbol=trade.symbol,
                severity=severity
            )
        except Exception:
            pass

        return trade

    def get_open_positions(self) -> List[dict]:
        """Return all currently open trades as dicts, newest first."""
        return [
            t.to_dict()
            for t in sorted(
                self._open.values(),
                key=lambda t: t.entry_time,
                reverse=True,
            )
        ]

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
        # B9 fix: prefer SQLite as single source of truth (Sprint 17 US-1703)
        # Fall back to in-memory _closed if db_manager not available
        if getattr(self, "db_manager", None) is not None:
            try:
                rows = self.db_manager.get_closed_trades(limit=10000)
                closed = []
                for row in rows:
                    t = PaperTrade.__new__(PaperTrade)
                    t.trade_id = row.get("trade_id", "")
                    t.pnl = row.get("pnl") or row.get("realized_pnl")
                    closed.append(t)
            except Exception as exc:
                logger.warning("[TRACKER] get_performance: SQLite read failed, using in-memory: %s", exc)
                closed = self._closed
        else:
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
            "starting_balance": round(self._get_starting_balance(), 4),
        }

    def _get_starting_balance(self) -> float:
        """
        Return yesterday's closing equity as today's starting balance.

        Computes INITIAL_CAPITAL + sum(pnl) for ALL closed paper trades whose
        pnl is not NULL.  This ensures the daily P&L percentage is always
        measured against the correct prior-day equity rather than the hardcoded
        INITIAL_CAPITAL every day (Bug B4).

        Result is cached on first call per calendar day so repeated calls
        within the same trading session are O(1).

        Falls back to INITIAL_CAPITAL when:
          - No closed trades exist yet
          - SQLite is unavailable
          - Any exception is raised
        """
        # --- per-day cache ---
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cached_date: str = getattr(self, "_starting_balance_date", "")
        if cached_date == today_str:
            return getattr(self, "_starting_balance_cache", 0.0)

        # --- load INITIAL_CAPITAL from config ---
        initial: float = 10_000.0
        try:
            from config import settings  # type: ignore[import]
            initial = float(getattr(settings, "INITIAL_CAPITAL", 10_000.0) or 10_000.0)
        except Exception:
            pass

        # --- sum closed P&L from db_manager (B9-safe path) or raw SQLite ---
        total_pnl: float = 0.0
        try:
            if self._db is not None:
                rows = self._db.get_closed_trades(limit=100_000)
                total_pnl = sum(
                    float(r.get("pnl") or 0.0)
                    for r in rows
                    if r.get("pnl") is not None
                )
            else:
                # Fallback: query the SQLite file directly using SQLITE_DB_PATH
                try:
                    from config import settings as _cfg  # type: ignore[import]
                    db_path = getattr(_cfg, "SQLITE_DB_PATH", None)
                except Exception:
                    db_path = None
                if db_path:
                    conn = sqlite3.connect(str(db_path), timeout=5)
                    cursor = conn.execute(
                        "SELECT COALESCE(SUM(pnl), 0) FROM paper_trades WHERE pnl IS NOT NULL"
                    )
                    total_pnl = float(cursor.fetchone()[0] or 0.0)
                    conn.close()
        except Exception as exc:
            logger.warning("[TRACKER] _get_starting_balance: pnl sum failed: %s", exc)
            total_pnl = 0.0

        balance = initial + total_pnl
        # Cache for the rest of the trading day
        self._starting_balance_date: str = today_str
        self._starting_balance_cache: float = balance
        logger.debug(
            "[TRACKER] starting_balance computed: initial=%.2f + pnl=%.2f = %.2f",
            initial, total_pnl, balance,
        )
        return balance

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

        # SQLite-first: persist before updating in-memory (Bug B9 / US-2004).
        if self._db is not None:
            self._db.insert_paper_trade(
                trade_id,
                symbol=trade.symbol,
                side=side,
                quantity=float(quantity),
                entry_price=float(entry_price),
                entry_time=trade.entry_time,
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy_params=strategy_params,
            )

        # DB write succeeded (or no DB configured) — update in-memory and JSONL
        self._open[trade_id] = trade
        self._append_record(trade)

        logger.info(
            "[PAPER] ADD   %s %s qty=%s @ %.4f  sl=%s tp=%s  id=%s",
            symbol.upper(),
            side.upper(),
            quantity,
            entry_price,
            stop_loss,
            take_profit,
            trade_id[:8],
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
        SQLite is written first; in-memory is only updated on success (Bug B9 / US-2004).

        Raises KeyError if trade_id is unknown.
        """
        trade = self._open.get(trade_id)
        if trade is None:
            raise KeyError(f"No open trade with id={trade_id!r}")

        # Compute all close fields before any writes
        resolved_exit_time = exit_time or datetime.now(timezone.utc).isoformat()
        if pnl is not None:
            computed_pnl = float(pnl)
        else:
            action_lower = trade.action.lower()
            is_short = "sell" in action_lower or "short" in action_lower
            multiplier = INSTRUMENT_MULTIPLIERS.get(trade.symbol.upper(), _DEFAULT_MULTIPLIER)
            if is_short:
                computed_pnl = (trade.entry_price - exit_price) * trade.quantity * multiplier
            else:
                computed_pnl = (exit_price - trade.entry_price) * trade.quantity * multiplier

        # SQLite-first: if this raises, _open remains unchanged (Bug B9 / US-2004).
        if self._db is not None:
            self._db.close_paper_trade(
                trade_id=trade_id,
                exit_price=float(exit_price),
                exit_time=resolved_exit_time,
                pnl=computed_pnl,
            )

        # DB write succeeded (or no DB) — mutate in-memory and JSONL
        self._open.pop(trade_id)
        trade.exit_price = float(exit_price)
        trade.exit_time = resolved_exit_time
        trade.is_open = False
        trade.pnl = computed_pnl

        self._closed.append(trade)
        self._append_record(trade)

        logger.info(
            "[PAPER] CLOSE %s @ %.4f  pnl=%+.2f  id=%s",
            trade.symbol,
            exit_price,
            trade.pnl,
            trade_id[:8],
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

    # ── Session management helpers ────────────────────────────────────────────

    def flatten_all_positions(self, exit_price: Optional[float] = None) -> List[dict]:
        """
        Close all open positions at session end.

        Parameters
        ----------
        exit_price : float, optional
            Price to use for all closes.  If None, uses each trade's entry_price
            as a fallback (zero P&L result) so the ledger stays balanced.

        Returns
        -------
        List of closed trade dicts (one per position that was open).
        """
        closed: List[dict] = []
        # Snapshot keys — avoid mutation-during-iteration
        open_ids = list(self._open.keys())
        for trade_id in open_ids:
            trade = self._open.get(trade_id)
            if trade is None:
                continue
            # Determine exit price
            price = exit_price if exit_price is not None else trade.entry_price
            if price is None:
                logger.warning(
                    "flatten_all_positions: no price for trade %s, skipping", trade_id[:8]
                )
                continue
            try:
                result = self.close_trade(trade_id, exit_price=float(price))
                closed.append(result.to_dict())
            except Exception as exc:
                logger.warning("flatten_all_positions: failed to close %s: %s", trade_id[:8], exc)
        logger.info("flatten_all_positions: closed %d positions", len(closed))
        return closed

    def check_and_move_breakeven(self, trade_id: str, current_price: float) -> bool:
        """
        Move stop-loss to breakeven once price has moved at least
        ``BREAKEVEN_STOP_ATR_MULT * atr_value`` in favour of the trade.

        Requires the trade to have been opened with an ``atr_value``.

        Parameters
        ----------
        trade_id : str
            ID of an open trade.
        current_price : float
            Latest market price for the instrument.

        Returns
        -------
        True if the stop was moved this call, False otherwise.
        """
        trade = self._open.get(trade_id)
        if trade is None:
            return False

        entry_price: Optional[float] = trade.entry_price
        atr_value: Optional[float] = trade.atr_value
        action: str = (trade.action or "").lower()
        stop_loss: Optional[float] = trade.stop_loss

        if entry_price is None or atr_value is None or atr_value <= 0:
            return False  # Cannot compute without ATR

        # Load multiplier from config; default to 0.50 ATR buffer
        try:
            from config import settings  # type: ignore[import]

            be_mult: float = float(getattr(settings, "BREAKEVEN_STOP_ATR_MULT", 0.50))
        except Exception:
            be_mult = 0.50

        threshold = be_mult * atr_value
        micro_buffer = 1.0  # $1 buffer inside entry price

        moved = False
        is_long = action in ("buy", "buy_to_open", "long")
        is_short = action in ("sell", "sell_to_open", "short", "sell_short")

        if is_long:
            # Long: move stop to entry + buffer when price >= entry + threshold
            if current_price >= entry_price + threshold:
                new_stop = entry_price + micro_buffer
                if stop_loss is None or new_stop > stop_loss:
                    trade.stop_loss = new_stop
                    logger.info(
                        "Breakeven stop moved for %s: %.2f -> %.2f (entry=%.2f, atr=%.2f)",
                        trade_id[:8],
                        stop_loss or 0.0,
                        new_stop,
                        entry_price,
                        atr_value,
                    )
                    moved = True
        elif is_short:
            # Short: move stop to entry - buffer when price <= entry - threshold
            if current_price <= entry_price - threshold:
                new_stop = entry_price - micro_buffer
                if stop_loss is None or new_stop < stop_loss:
                    trade.stop_loss = new_stop
                    logger.info(
                        "Breakeven stop moved for %s: %.2f -> %.2f (entry=%.2f, atr=%.2f)",
                        trade_id[:8],
                        stop_loss or 0.0,
                        new_stop,
                        entry_price,
                        atr_value,
                    )
                    moved = True

        return moved

    # ── Persistence — JSONL (always on) ───────────────────────────────────────

    def _append_record(self, trade: PaperTrade) -> None:
        """Append a single trade record to the JSONL store (append-only audit log).

        TODO Sprint 17 US-1703: Remove this JSON write path after migration completes.
        JSON write path marked for removal — SQLite will be canonical after migration.
        """
        logger.warning(
            "[DEPRECATED] Writing paper trade to JSON at %s — "
            "JSON storage is deprecated; SQLite is the source of truth. "
            "This path will be removed in a future release.",
            self._store,
        )
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
                        logger.warning(
                            "Skipping malformed line %d in trades.jsonl: %s", line_num, exc
                        )
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
                    record.get("trade_id", "?"),
                    exc,
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
                            stop_loss=row.get("stop_loss"),
                            take_profit=row.get("take_profit"),
                            atr_value=row.get("atr_value"),
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

    def reload_open_positions_from_db(self) -> None:
        """
        Rebuild self._open from SQLite paper_trades (status='open').

        Called from main.py lifespan after the tracker is initialised so that any
        JSONL/in-memory divergence introduced by a prior crash is resolved before
        trading resumes.  Errors are caught and logged — the tracker stays usable
        even if the DB is temporarily unavailable (Bug B9 / US-2004).
        """
        if self._db is None:
            logger.debug("[TRACKER] reload_open_positions_from_db: no db_manager, skipping")
            return

        try:
            rows = self._db.get_trade_history(limit=5000, status="open")
            if not rows:
                self._open = {}
                logger.info(
                    "[TRACKER] reload_open_positions_from_db: no trades in DB, cleared open"
                )
                return

            rebuilt: Dict[str, PaperTrade] = {}
            for row in rows:
                try:
                    # Accept both dict-like rows and sqlite3.Row objects
                    is_open_flag = row.get("is_open", row.get("exit_price") is None)
                    if not is_open_flag:
                        continue
                    rebuilt[str(row["trade_id"])] = PaperTrade(
                        trade_id=str(row.get("trade_id") or row.get("id", "")),
                        symbol=str(row.get("symbol", "")),
                        action=str(row.get("side") or row.get("action", "")),
                        quantity=float(row.get("quantity", 0)),
                        entry_price=float(row.get("entry_price", 0)),
                        entry_time=str(row.get("entry_time", "")),
                        is_open=True,
                        notes=str(row.get("notes") or ""),
                        stop_loss=row.get("stop_loss"),
                        take_profit=row.get("take_profit"),
                        atr_value=row.get("atr_value"),
                    )
                except (TypeError, ValueError, KeyError) as exc:
                    logger.warning("[TRACKER] reload: skipping bad row: %s", exc)

            self._open = rebuilt
            logger.info("[TRACKER] Rebuilt %d open positions from SQLite", len(rebuilt))

        except Exception as exc:
            logger.error("[TRACKER] reload_open_positions_from_db failed: %s", exc)

    def initialize_closed_trades_from_db(self) -> None:
        """
        Populate self._closed from SQLite on engine startup.

        This ensures that after a restart, the in-memory closed trade history
        matches the database (Bug B9 / US-2004). Called after load_from_db()
        and _load_history() to fill any gaps.

        Errors are caught and logged; the tracker remains usable even if the DB
        is temporarily unavailable.
        """
        if self._db is None:
            logger.debug("[TRACKER] initialize_closed_trades_from_db: no db_manager, skipping")
            return

        try:
            rows = self._db.get_trade_history(limit=5000)
            if not rows:
                logger.debug("[TRACKER] initialize_closed_trades_from_db: no rows in DB")
                return

            existing_ids = {t.trade_id for t in self._closed}
            added = 0
            for row in rows:
                try:
                    is_open_flag = row.get("is_open", row.get("exit_price") is None)
                    if is_open_flag:
                        continue
                    trade_id = str(row.get("trade_id") or row.get("id", ""))
                    if trade_id in existing_ids:
                        continue
                    trade = PaperTrade(
                        trade_id=trade_id,
                        symbol=str(row.get("symbol", "")),
                        action=str(row.get("side") or row.get("action", "")),
                        quantity=float(row.get("quantity", 0)),
                        entry_price=float(row.get("entry_price", 0)),
                        entry_time=str(row.get("entry_time", "")),
                        exit_price=row.get("exit_price"),
                        exit_time=row.get("exit_time"),
                        pnl=row.get("pnl"),
                        notes=str(row.get("notes") or ""),
                        is_open=False,
                    )
                    self._closed.append(trade)
                    existing_ids.add(trade_id)
                    added += 1
                except (TypeError, ValueError, KeyError) as exc:
                    logger.warning("[TRACKER] initialize_closed: skipping bad row: %s", exc)

            self._closed.sort(key=lambda t: t.entry_time)
            logger.info(
                "[TRACKER] initialize_closed_trades_from_db: added %d closed trades from SQLite",
                added,
            )
        except Exception as exc:
            logger.error("[TRACKER] initialize_closed_trades_from_db failed: %s", exc)
