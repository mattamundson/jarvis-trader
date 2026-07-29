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
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("jarvis_trader.portfolio")

try:
    from database._helpers import compute_order_idempotency_key as _compute_idem_key
except ImportError:
    try:
        from engine.database._helpers import compute_order_idempotency_key as _compute_idem_key
    except ImportError:
        _compute_idem_key = None  # type: ignore[assignment]

try:
    from risk.exit_price_sanity import assert_exit_price_sane
except ImportError:
    try:
        from engine.risk.exit_price_sanity import assert_exit_price_sane
    except ImportError:  # pragma: no cover - guard is additive; never hard-fail import

        def assert_exit_price_sane(symbol, entry_price, exit_price):  # type: ignore[misc]
            return None


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


class UnknownInstrumentMultiplierError(ValueError):
    """Raised when a symbol has no configured contract multiplier.

    Fail-closed by design: a futures fill priced at a silent 1x multiplier
    mis-states P&L by 5x–1000x. Add the symbol to INSTRUMENT_MULTIPLIERS, or
    set ALLOW_DEFAULT_MULTIPLIER=1 to force the 1x fallback with a loud log.
    """


class TradeCloseNotPersistedError(RuntimeError):
    """Raised when the DB layer's close_paper_trade() reports 0 rows updated.

    DatabaseManager.close_paper_trade() returns True/False based on
    ``cur.rowcount == 1`` — it does NOT raise on a no-op UPDATE (stale
    trade_id, already closed elsewhere, or a race). Fail-closed by design
    (GT-48): if the DB write didn't actually land, the in-memory _open /
    _closed mutation must not proceed either, or the SQLite ledger and the
    in-memory/JSONL state silently diverge while the API still reports
    "closed".
    """


def _resolve_multiplier(symbol: str) -> float:
    """Return the contract multiplier for ``symbol``, fail-closed on unknowns.

    Previously ``INSTRUMENT_MULTIPLIERS.get(symbol, 1.0)`` silently applied a
    1x multiplier to any unlisted instrument, so an un-mapped futures symbol
    would post a P&L off by its true multiplier. This raises instead, unless
    ALLOW_DEFAULT_MULTIPLIER=1 is set (then it logs loudly and falls back).
    """
    mult = INSTRUMENT_MULTIPLIERS.get(symbol.upper())
    if mult is not None:
        return mult
    if os.getenv("ALLOW_DEFAULT_MULTIPLIER", "0") == "1":
        logger.error(
            "[PAPER] No contract multiplier configured for %s — falling back to "
            "%.1fx (ALLOW_DEFAULT_MULTIPLIER=1). P&L for this symbol may be wrong.",
            symbol,
            _DEFAULT_MULTIPLIER,
        )
        return _DEFAULT_MULTIPLIER
    raise UnknownInstrumentMultiplierError(
        f"No contract multiplier configured for {symbol!r}. Add it to "
        f"INSTRUMENT_MULTIPLIERS (engine/portfolio/tracker.py) or set "
        f"ALLOW_DEFAULT_MULTIPLIER=1 to force a 1x fallback."
    )


def _commission_per_contract() -> float:
    """Flat per-contract round-trip commission (dollars), subtracted at close.

    Configurable via COMMISSION_PER_CONTRACT (default $1.50, a realistic
    retail micro-futures round-trip). This is a flat proxy across instruments;
    historical rows closed before this term was introduced are pre-cost and
    are NOT retroactively adjusted. Broker-confirmed closes (an explicit pnl
    passed to close_paper_trade) are assumed to already include fees and are
    left untouched.
    """
    try:
        return float(os.getenv("COMMISSION_PER_CONTRACT", "1.50"))
    except (TypeError, ValueError):
        return 1.50


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
        rv_at_entry: Optional[float] = None,
        analyst_signals: Optional[Dict[str, float]] = None,
        candidate_id: Optional[str] = None,
        decision_identity: Optional[Dict[str, Any]] = None,
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
        candidate_id : str, optional
            Forward-test registry candidate that fired this entry. When supplied,
            the candidate id is stamped into ``strategy_params`` so the
            forward-test loop can attribute the trade at the precise
            candidate_id level and let it count toward graduation.
            Purely additive -- omit it and behaviour is unchanged.
        """
        # ── Idempotency key: compute before generating trade_id so that a
        # duplicate call within the same 5-second window can be collapsed to
        # the existing row without creating a ghost trade_id.
        idem_key: Optional[str] = None
        if _compute_idem_key is not None:
            try:
                idem_key = _compute_idem_key(symbol, action, float(quantity), float(price))
            except Exception as _ik_err:
                logger.debug("[TRACKER] idempotency key compute failed (non-fatal): %s", _ik_err)

        # If an idempotency key is available, check for an existing open trade
        # in the in-memory dict first (fast path, avoids DB round-trip).
        if idem_key is not None and self._db is not None:
            # The DB mixin will do the definitive check; we just need to return
            # the correct trade_id if the mixin deduplicates.
            pass  # resolved below after insert_paper_trade returns

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
        _sp: dict = {"notes": notes}
        if rv_at_entry is not None:
            _sp["rv_at_entry"] = round(float(rv_at_entry), 4)
        # Persist per-analyst signals so close-time _record_agent_feedback
        # writes a trade_outcomes row for calibration. No-op for callers that
        # carry no pipeline reports (manual / broker-reconcile opens).
        if analyst_signals:
            _sp["analyst_signals"] = {k: float(v) for k, v in analyst_signals.items()}
        # Forward-test attribution tag: stamp candidate_id + champion params so the
        # forward-test loop can attribute this trade at the precise level. Best-effort
        # and fail-open — a bad/unknown candidate_id must never block a real entry.
        if candidate_id:
            try:
                from backtest.forward_test import tag_strategy_params

                _sp = tag_strategy_params(_sp, candidate_id)
            except Exception as _tag_err:
                logger.debug("[TRACKER] candidate_id tag failed (non-fatal): %s", _tag_err)
                _sp["candidate_id"] = candidate_id
        # Decision-identity tag (P2): stamp WHICH live decision configuration
        # produced this trade so the forward-test loop can attribute it to a
        # decision lineage. Additive and fail-open.
        if decision_identity:
            _sp["decision_identity"] = decision_identity
        if self._db is not None:
            # INVARIANT: one open paper_trades row per (symbol, side). The engine
            # never pyramids, so any re-log of a still-open position collapses to
            # the existing row inside insert_paper_trade's open-state guard —
            # regardless of price drift or how far apart the re-emissions arrive.
            # (A future scale-in feature would need a bar/decision discriminator
            # added to that guard so genuine adds are not swallowed.)
            row_id = self._db.insert_paper_trade(
                trade_id,
                symbol=trade.symbol,
                side=trade.action,
                quantity=trade.quantity,
                entry_price=trade.entry_price,
                entry_time=trade.entry_time,
                stop_loss=None,
                take_profit=None,
                strategy_params=_sp,
                idempotency_key=idem_key,
            )
            # Dedup check: if the DB returned a row_id for an EXISTING row but
            # the trade_id we generated is NOT in _open, the mixin deduplicated
            # this submission.  Return the existing trade_id from the DB row.
            if idem_key is not None:
                try:
                    existing_row = self._db.get_trade_by_id(trade_id)
                    if existing_row is None:
                        # Our generated trade_id was not inserted — fetch the
                        # deduplicated row by row_id to get its trade_id.
                        with self._db._lock:
                            _conn = self._db._connect()
                            try:
                                _r = _conn.execute(
                                    "SELECT trade_id FROM paper_trades WHERE id = ?", (row_id,)
                                ).fetchone()
                            finally:
                                _conn.close()
                        if _r is not None:
                            existing_trade_id: str = _r[0]
                            logger.warning(
                                "[TRACKER] open_trade DEDUPLICATED — returning existing trade_id=%s "
                                "(idem_key=%s)",
                                existing_trade_id[:8],
                                idem_key,
                            )
                            return existing_trade_id
                except Exception as _dedup_err:
                    logger.debug(
                        "[TRACKER] dedup resolution failed (non-fatal, continuing): %s", _dedup_err
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
                "trade_opened",
                f"{symbol.upper()} {action.upper()} {quantity} @ {price}",
                symbol=symbol.upper(),
                severity="info",
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

        # Phantom-price guard (2026-06-15): reject a corrupt exit BEFORE any P&L
        # compute or DB write, so a wrong-era/non-finite price can never write a
        # phantom realized-P&L row. Fail-closed; raises ExitPriceSanityError.
        assert_exit_price_sane(trade.symbol, trade.entry_price, exit_price)

        # Compute close fields on a local copy before any writes
        exit_time = datetime.now(timezone.utc).isoformat()
        action_lower = trade.action.lower()
        is_short = "sell" in action_lower or "short" in action_lower
        multiplier = _resolve_multiplier(trade.symbol)
        if is_short:
            computed_pnl = (trade.entry_price - exit_price) * trade.quantity * multiplier
        else:
            computed_pnl = (exit_price - trade.entry_price) * trade.quantity * multiplier
        # Subtract a flat round-trip commission (see _commission_per_contract).
        computed_pnl -= _commission_per_contract() * abs(trade.quantity)

        # SQLite-first: write to DB before mutating in-memory state.
        # If this raises, _open is unchanged — no ghost position on restart.
        if self._db is not None:
            _db_updated = self._db.close_paper_trade(
                trade_id=trade_id,
                exit_price=float(exit_price),
                exit_time=exit_time,
                pnl=computed_pnl,
            )
            if not _db_updated:
                # GT-48: close_paper_trade() returns False (not an exception)
                # when the UPDATE affects 0 rows. Don't proceed with the
                # in-memory mutation below — that would report "closed" while
                # the SQLite ledger row was never actually updated.
                raise TradeCloseNotPersistedError(
                    f"close_trade: DB close_paper_trade affected 0 rows for "
                    f"trade_id={trade_id!r} (stale id, already closed, or a "
                    f"race) — refusing to mark closed in-memory."
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

        # Record outcome for Brier/IC calibration (Novel #2, Tracks F+H).
        # Reads analyst_signals persisted into strategy_params at open time and
        # writes a trade_outcomes row the debate loop can calibrate against.
        self._record_agent_feedback(trade_id, trade)

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

            severity = "warn" if trade.pnl and trade.pnl < 0 else "info"
            publish_event(
                "trade_closed",
                f"{trade.symbol} closed pnl={trade.pnl}",
                symbol=trade.symbol,
                severity=severity,
            )
        except Exception:
            pass

        # Queue post-trade LLM review (non-blocking, best-effort)
        try:
            import asyncio as _asyncio_rv
            import os as _os_rv

            from analytics.trade_review import queue_trade_review as _queue_review

            if not _os_rv.getenv("TESTING"):
                _loop_rv = _asyncio_rv.get_event_loop()
                if _loop_rv.is_running():
                    _loop_rv.create_task(_queue_review(trade))
        except Exception as _rv_exc:
            logger.debug("[REVIEW] Post-trade review skipped: %s", _rv_exc)

        return trade

    def get_open_positions(self) -> List[dict]:
        """Return all currently open trades as dicts, newest first.

        Applies defensive filters to prevent phantom positions from leaking into
        RiskManager/FundManager portfolio context (Apr 2026 fix):
          - exit_time must be None (closed trades should never be in _open, but
            a crash during close_trade can leave stale entries)
          - is_open must be True
          - entry_price must be a positive finite number (guards against
            0/NaN/None rows loaded from a corrupted DB)
        Any trade failing these checks is removed from _open in-place so the
        ledger self-heals without requiring a restart.
        """
        import math

        valid: List[PaperTrade] = []
        drop: List[str] = []
        for tid, t in self._open.items():
            exit_time = getattr(t, "exit_time", None)
            is_open = getattr(t, "is_open", True)
            entry_price = getattr(t, "entry_price", None)
            try:
                ep = float(entry_price) if entry_price is not None else 0.0
            except (TypeError, ValueError):
                ep = 0.0
            is_valid_price = ep > 0.0 and math.isfinite(ep)
            if exit_time is None and is_open and is_valid_price:
                valid.append(t)
            else:
                drop.append(tid)
                logger.warning(
                    "[TRACKER] Dropping phantom open position %s (exit_time=%s, is_open=%s, entry_price=%s)",
                    tid[:8] if tid else "?",
                    exit_time,
                    is_open,
                    entry_price,
                )

        for tid in drop:
            self._open.pop(tid, None)

        return [t.to_dict() for t in sorted(valid, key=lambda t: t.entry_time, reverse=True)]

    def get_open_positions_authoritative(self) -> Tuple[List[dict], dict]:
        """Return open positions anchored to the DB (source of truth) + a recon report.

        ``get_open_positions`` reads only the in-memory ``_open`` map, which can
        drift from ``paper_trades`` whenever a row is written by a path that
        bypasses the tracker (e.g. the stop-monitor's ``db_manager.close_trade``
        fallback, or a peer process). That drift is the root of the
        "dashboard shows no positions while one is open" trust bug.

        This method makes the DB authoritative: when a db_manager is present the
        returned list is the set of ``status='open'`` paper_trades, each rendered
        in the position-dict shape consumers expect (``action`` aliased from the
        DB ``side`` column). The in-memory dict is preferred when both agree so
        the richer runtime shape is kept. Divergence is surfaced (never silent)
        in the recon report and logged at WARNING.

        Returns ``(positions, recon)`` where recon is::

            {"source", "reconciled", "count", "in_memory_count", "db_count",
             "only_in_db": [trade_id...], "only_in_memory": [trade_id...]}
        """
        mem = self.get_open_positions()
        mem_by_id = {str(p.get("trade_id")): p for p in mem if p.get("trade_id")}

        if self._db is None:
            return mem, {
                "source": "memory",
                "reconciled": True,
                "count": len(mem),
                "in_memory_count": len(mem),
                "db_count": None,
                "only_in_db": [],
                "only_in_memory": [],
            }

        try:
            db_rows = self._db.get_open_trades()
        except Exception as exc:  # DB error must never break the read
            logger.error("[TRACKER] authoritative read: get_open_trades failed: %s", exc)
            return mem, {
                "source": "memory_db_error",
                "reconciled": False,
                "count": len(mem),
                "in_memory_count": len(mem),
                "db_count": None,
                "only_in_db": [],
                "only_in_memory": [],
            }

        db_by_id = {str(r.get("trade_id")): r for r in db_rows if r.get("trade_id")}

        positions: List[dict] = []
        for tid, row in db_by_id.items():
            if tid in mem_by_id:
                positions.append(mem_by_id[tid])
            else:
                norm = dict(row)
                # Consumers read `action`; the DB column is `side`.
                norm.setdefault("action", row.get("side"))
                positions.append(norm)

        only_in_db = sorted(set(db_by_id) - set(mem_by_id))
        only_in_memory = sorted(set(mem_by_id) - set(db_by_id))
        reconciled = not only_in_db and not only_in_memory
        if not reconciled:
            logger.warning(
                "[TRACKER] open-position drift: only_in_db=%s only_in_memory=%s "
                "(DB is authoritative; returning DB set)",
                only_in_db,
                only_in_memory,
            )

        return positions, {
            "source": "db_authoritative",
            "reconciled": reconciled,
            "count": len(positions),
            "in_memory_count": len(mem),
            "db_count": len(db_by_id),
            "only_in_db": only_in_db,
            "only_in_memory": only_in_memory,
        }

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
            equity_curve     : absolute account equity after each closed trade,
                               starting_balance-anchored (GT-05: downstream
                               consumers — e.g. risk/pnl_monitor.py's
                               PnLMonitor.get_drawdown_pct() — read this key to
                               find the peak equity used for the drawdown_pct
                               shown on /health and /mission-control; before
                               this fix the key was never populated, so the
                               drawdown calc always saw an empty series and
                               floored at 0.0 (or -0.0 once SafetyLayer negates
                               it) regardless of the true drawdown depth)
        """
        # B9 fix: prefer SQLite as single source of truth (Sprint 17 US-1703)
        # Fall back to in-memory _closed if the DB handle isn't available.
        # The handle is stored as self._db (set in __init__); the prior
        # getattr(self, "db_manager", ...) checked a non-existent attribute, so
        # this branch never ran and get_performance() always used the in-memory
        # _closed list (empty after every restart) — silently wrong metrics.
        if self._db is not None:
            try:
                rows = self._db.get_closed_trades(limit=10000)
                closed = []
                for row in rows:
                    t = PaperTrade.__new__(PaperTrade)
                    t.trade_id = row.get("trade_id", "")
                    t.pnl = row.get("pnl") or row.get("realized_pnl")
                    t.exit_time = row.get("exit_time")
                    closed.append(t)
            except Exception as exc:
                logger.warning(
                    "[TRACKER] get_performance: SQLite read failed, using in-memory: %s", exc
                )
                closed = self._closed
        else:
            closed = self._closed
        if not closed:
            starting_balance = self._get_starting_balance()
            return {
                "total_pnl": 0.0,
                "today_pnl": 0.0,
                "win_rate": 0.0,
                "profit_factor": None,
                "num_trades": 0,
                "num_open": len(self._open),
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "max_dd": 0.0,
                "best_trade": None,
                "worst_trade": None,
                "starting_balance": round(starting_balance, 4),
                "equity_curve": [round(starting_balance, 4)],
            }

        pnls = [t.pnl for t in closed if t.pnl is not None]

        # today_pnl: realized P&L from trades CLOSED today (UTC), as distinct from
        # total_pnl (the all-time closed sum). Callers that want "today" -- e.g.
        # FuturesModule.get_daily_pnl(), which feeds /portfolio/summary -- previously
        # fell back to total_pnl because this key did not exist, so a "daily" number
        # was silently reporting lifetime P&L. exit_time is stored as ISO-8601 UTC, so
        # the YYYY-MM-DD prefix is the UTC close date.
        _today = datetime.now(timezone.utc).date().isoformat()
        today_pnl = sum(
            t.pnl
            for t in closed
            if t.pnl is not None
            and getattr(t, "exit_time", None)
            and str(t.exit_time)[:10] == _today
        )

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0

        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

        # Equity curve for max drawdown. `equity`/`peak`/`max_dd` track the
        # relative (pnl-only) series used for the `max_dd` dollar figure below;
        # `equity_curve` tracks the ABSOLUTE account equity (starting_balance +
        # cumulative pnl) after each closed trade — this is the series consumers
        # like PnLMonitor.get_drawdown_pct() (risk/pnl_monitor.py) need, since
        # they compare it against an absolute `current_balance` (also
        # starting_balance + total_pnl). GT-05: this key was never populated
        # before, so that downstream peak lookup always saw `[]` and
        # drawdown_pct floored at 0.0 (or -0.0 once SafetyLayer negates it via
        # `-pnl_monitor.get_drawdown_pct()`) on /health and /mission-control,
        # regardless of the true drawdown depth.
        starting_balance = self._get_starting_balance()
        peak = 0.0
        equity = 0.0
        max_dd = 0.0
        equity_curve = [round(starting_balance, 4)]
        for p in pnls:
            equity += p
            if equity > peak:
                peak = equity
            dd = equity - peak
            if dd < max_dd:
                max_dd = dd
            equity_curve.append(round(starting_balance + equity, 4))

        return {
            "total_pnl": round(sum(pnls), 4),
            "today_pnl": round(today_pnl, 4),
            "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
            "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            "num_trades": len(pnls),
            "num_open": len(self._open),
            "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
            "max_dd": round(max_dd, 4),
            "best_trade": round(max(pnls), 4) if pnls else None,
            "worst_trade": round(min(pnls), 4) if pnls else None,
            "starting_balance": round(starting_balance, 4),
            "equity_curve": equity_curve,
        }

    def _get_starting_balance(self) -> float:
        """
        Return the pnl-FREE starting base (INITIAL_CAPITAL) for the account.

        This is a *starting* balance by contract: every consumer computes
        current equity as ``starting_balance + total_pnl`` (see
        ``risk/pnl_monitor._read_memory`` line ~513 and
        ``get_performance_summary`` line ~1381).  Baking cumulative closed P&L
        in here caused a DOUBLE-COUNT — consumers added ``total_pnl`` a second
        time, inflating portfolio_equity to ``initial + 2*total_pnl`` (e.g.
        $20,163.67 on 2026-07-02 when TRUE equity was $15,081.84 = $10k initial
        + $5,081.84 net closed P&L).  So this returns INITIAL_CAPITAL only, and
        equity is counted exactly once at the call sites.

        Tradeoff (formerly "Bug B4"): the daily_pnl_pct denominator reverts to
        the initial deposit rather than prior-day equity.  That is
        reporting-only — the live daily-loss GATE uses portfolio_equity (now
        correct), not this field.  If prior-day-equity daily% is wanted, derive
        it at the daily_pnl_pct site from portfolio_equity, NOT by re-inflating
        this base (which reintroduces the double-count).

        Result is cached per calendar day so repeated calls are O(1).
        """
        # --- per-day cache ---
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cached_date: str = getattr(self, "_starting_balance_date", "")
        if cached_date == today_str:
            return getattr(self, "_starting_balance_cache", 0.0)

        # --- load INITIAL_CAPITAL from config (the pnl-free base) ---
        initial: float = 10_000.0
        try:
            from config import settings  # type: ignore[import]

            initial = float(getattr(settings, "INITIAL_CAPITAL", 10_000.0) or 10_000.0)
        except Exception:
            pass

        # Counted-once contract: consumers add total_pnl themselves, so this
        # base MUST stay pnl-free (2026-07-02 double-count fix).
        balance = initial
        # Cache for the rest of the trading day
        self._starting_balance_date: str = today_str
        self._starting_balance_cache: float = balance
        logger.debug("[TRACKER] starting_balance (pnl-free base) = %.2f", balance)
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
        # ── Idempotency key ───────────────────────────────────────────────────
        idem_key: Optional[str] = None
        if _compute_idem_key is not None:
            try:
                idem_key = _compute_idem_key(symbol, side, float(quantity), float(entry_price))
            except Exception as _ik_err:
                logger.debug(
                    "[TRACKER] add_paper_trade: idempotency key compute failed (non-fatal): %s",
                    _ik_err,
                )

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
            row_id = self._db.insert_paper_trade(
                trade_id,
                symbol=trade.symbol,
                side=side,
                quantity=float(quantity),
                entry_price=float(entry_price),
                entry_time=trade.entry_time,
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy_params=strategy_params,
                idempotency_key=idem_key,
            )
            # Dedup check: if the DB mixin collapsed this to an existing row,
            # return its trade_id instead of the freshly-generated one.
            if idem_key is not None:
                try:
                    existing_row = self._db.get_trade_by_id(trade_id)
                    if existing_row is None:
                        with self._db._lock:
                            _conn = self._db._connect()
                            try:
                                _r = _conn.execute(
                                    "SELECT trade_id FROM paper_trades WHERE id = ?", (row_id,)
                                ).fetchone()
                            finally:
                                _conn.close()
                        if _r is not None:
                            existing_trade_id: str = _r[0]
                            logger.warning(
                                "[TRACKER] add_paper_trade DEDUPLICATED — returning existing "
                                "trade_id=%s (idem_key=%s)",
                                existing_trade_id[:8],
                                idem_key,
                            )
                            return existing_trade_id
                except Exception as _dedup_err:
                    logger.debug(
                        "[TRACKER] add_paper_trade dedup resolution failed (non-fatal): %s",
                        _dedup_err,
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

        # Phantom-price guard (2026-06-15): reject a corrupt exit before any
        # write — even when an explicit pnl is supplied, the bad exit_price is
        # still persisted and would poison reconciliation. Fail-closed.
        assert_exit_price_sane(trade.symbol, trade.entry_price, exit_price)

        # Compute all close fields before any writes
        resolved_exit_time = exit_time or datetime.now(timezone.utc).isoformat()
        if pnl is not None:
            # Broker-confirmed figure — already net of fees; do not re-deduct.
            computed_pnl = float(pnl)
        else:
            action_lower = trade.action.lower()
            is_short = "sell" in action_lower or "short" in action_lower
            multiplier = _resolve_multiplier(trade.symbol)
            if is_short:
                computed_pnl = (trade.entry_price - exit_price) * trade.quantity * multiplier
            else:
                computed_pnl = (exit_price - trade.entry_price) * trade.quantity * multiplier
            # Subtract a flat round-trip commission (see _commission_per_contract).
            computed_pnl -= _commission_per_contract() * abs(trade.quantity)

        # SQLite-first: if this raises, _open remains unchanged (Bug B9 / US-2004).
        if self._db is not None:
            _db_updated = self._db.close_paper_trade(
                trade_id=trade_id,
                exit_price=float(exit_price),
                exit_time=resolved_exit_time,
                pnl=computed_pnl,
            )
            if not _db_updated:
                # GT-48: close_paper_trade() returns False (not an exception)
                # when the UPDATE affects 0 rows. Don't proceed with the
                # in-memory mutation below — that would report "closed" while
                # the SQLite ledger row was never actually updated.
                raise TradeCloseNotPersistedError(
                    f"close_paper_trade: DB close_paper_trade affected 0 rows "
                    f"for trade_id={trade_id!r} (stale id, already closed, or "
                    f"a race) — refusing to mark closed in-memory."
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

        # OpenClaw/Discord alert on trade close (non-blocking, best-effort).
        # close_paper_trade is the broker-confirmed-pnl close path used by the
        # 5-min stop monitor (main.py:_monitor_open_stops); it previously closed
        # SILENTLY. Mirror close_trade so every close fans out an alert with P&L.
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

        # Record outcome for Brier/IC calibration (Novel #2, Tracks F+H).
        self._record_agent_feedback(trade_id, trade)

        return trade

    def _record_agent_feedback(self, trade_id: str, trade: PaperTrade) -> None:
        """Write a trade_outcomes row so BrierCalibrationTracker / ICWeightedEnsemble
        / AgentFeedbackTracker.compute_accuracy can calibrate off real closed trades.

        Reads the ``analyst_signals`` sub-dict that pipeline/main persisted into
        ``strategy_params`` at open time. Silent-skips when:
          * ``TESTING`` env var is set (match existing hook convention)
          * DB row doesn't exist or has no ``analyst_signals`` (legacy trades)
          * AgentFeedbackTracker import or write fails (best-effort, never blocks close)
        """
        import os as _os_af

        if _os_af.getenv("TESTING"):
            return

        # W4: surface an implausible per-trade P&L at the source. Covers the
        # paper_trades record (which feeds analytics beyond trade_outcomes).
        # Alert-only - never blocks the close. See analytics/outcome_hygiene.
        try:
            try:
                from engine.analytics.outcome_hygiene import (
                    MAX_PLAUSIBLE_ABS_PNL_USD,
                    is_plausible_pnl,
                )
            except ImportError:  # pragma: no cover
                from analytics.outcome_hygiene import (
                    MAX_PLAUSIBLE_ABS_PNL_USD,
                    is_plausible_pnl,
                )
            _pnl_outlier = float(trade.pnl or 0.0)
            if not is_plausible_pnl(_pnl_outlier):
                logger.warning(
                    "[PAPER] Implausible close P&L for %s %s: pnl=%+.2f (>$%d) - "
                    "possible upstream P&L corruption",
                    trade.symbol,
                    trade_id[:8],
                    _pnl_outlier,
                    int(MAX_PLAUSIBLE_ABS_PNL_USD),
                )
                try:
                    from events.bus import publish as _publish_outlier

                    _publish_outlier(
                        "trade_pnl_outlier",
                        f"{trade.symbol} close pnl={_pnl_outlier:+.2f} exceeds plausibility bound",
                        symbol=trade.symbol,
                        severity="warn",
                    )
                except Exception:
                    pass
        except Exception as _outlier_exc:
            logger.debug("[PAPER] P&L outlier check skipped: %s", _outlier_exc)

        try:
            from engine.analytics.agent_feedback import AgentFeedbackTracker

            analyst_signals: dict = {}
            regime: Optional[str] = None
            if self._db is not None:
                row = self._db.get_trade_by_id(trade_id) or {}
                sp = row.get("strategy_params")
                # strategy_params is stored as JSON TEXT; get_trade_by_id returns it raw
                if isinstance(sp, str) and sp:
                    try:
                        import json as _json_af

                        sp = _json_af.loads(sp)
                    except Exception:
                        sp = None
                if isinstance(sp, dict):
                    analyst_signals = sp.get("analyst_signals") or {}
                    regime = sp.get("regime")
            if not analyst_signals:
                return  # Legacy trades without signals — safe no-op
            action_lower = (trade.action or "").lower()
            direction = "SHORT" if ("sell" in action_lower or "short" in action_lower) else "LONG"
            AgentFeedbackTracker().record_outcome(
                trade_id=trade_id,
                symbol=trade.symbol,
                direction=direction,
                pnl_usd=float(trade.pnl or 0.0),
                analyst_signals={k: float(v) for k, v in analyst_signals.items()},
                regime=regime,
            )
            logger.info(
                "[FEEDBACK] Recorded outcome for %s pnl=%+.2f signals=%s",
                trade_id[:8],
                trade.pnl or 0.0,
                list(analyst_signals.keys()),
            )
        except Exception as _af_exc:
            logger.debug("[FEEDBACK] record_outcome skipped: %s", _af_exc)

    def set_broker_metadata(self, trade_id: str, metadata: dict) -> bool:
        """
        Attach broker order IDs (entry_order_id, stp_order_id, etc.) to an
        open trade record so the portfolio survives restarts without losing
        bracket linkage.

        Persists by updating the ``strategy_params`` JSON blob in SQLite (merged
        with any existing params) and mirroring the values onto the in-memory
        PaperTrade object's ``notes`` field for the JSONL audit trail.

        Parameters
        ----------
        trade_id : str
            UUID of the open trade returned by open_trade().
        metadata : dict
            Arbitrary key/value pairs to store (e.g.
            {"entry_order_id": "1234", "stp_order_id": "1235"}).

        Returns
        -------
        True if the update succeeded (in-memory + DB), False if trade_id is
        unknown or DB write failed (logged at WARNING level).
        """
        trade = self._open.get(trade_id)
        if trade is None:
            logger.warning("[TRACKER] set_broker_metadata: unknown trade_id %s", trade_id[:8])
            return False

        # Update in-memory notes (append JSON blob so JSONL log is readable)
        try:
            existing_notes = json.loads(trade.notes) if trade.notes else {}
        except (json.JSONDecodeError, TypeError):
            existing_notes = {"_notes": trade.notes} if trade.notes else {}
        existing_notes.update(metadata)
        trade.notes = json.dumps(existing_notes)

        # Persist to SQLite when db_manager is available
        if self._db is not None:
            try:
                # Merge with whatever strategy_params the row already holds
                row = self._db.get_trade_by_id(trade_id) or {}
                sp = row.get("strategy_params")
                if isinstance(sp, str) and sp:
                    try:
                        sp = json.loads(sp)
                    except Exception:
                        sp = {}
                if not isinstance(sp, dict):
                    sp = {}
                sp.update(metadata)
                self._db.update_paper_trade_strategy_params(trade_id, sp)
            except Exception as exc:
                logger.warning(
                    "[TRACKER] set_broker_metadata: DB update failed for %s: %s",
                    trade_id[:8],
                    exc,
                )
                return False

        logger.info(
            "[TRACKER] Broker metadata set for trade %s: %s",
            trade_id[:8],
            list(metadata.keys()),
        )
        return True

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

    def get_trades_by_date(self, date_str: str) -> List[dict]:
        """
        Return closed trades whose ``exit_time`` falls on the given calendar date.

        Parameters
        ----------
        date_str : str
            ISO calendar date in "YYYY-MM-DD" form.  Compared against the
            prefix of each trade's exit_time.  Empty / malformed input returns [].

        Returns
        -------
        List of closed-trade dicts.  Each dict includes both ``pnl`` (the
        canonical column) and ``realized_pnl`` (alias expected by the EOD
        summary task at main.py:1136).  Caller contract: EOD job sums
        ``t.get("realized_pnl", 0)`` across the returned list.
        """
        if not isinstance(date_str, str) or len(date_str) < 10:
            return []
        prefix = date_str[:10]

        rows: List[dict]
        if self._db is not None:
            try:
                rows = list(self._db.get_trade_history(limit=1000, status="closed") or [])
            except Exception as exc:
                logger.error("DB get_trade_history failed in get_trades_by_date: %s", exc)
                rows = [t.to_dict() for t in self._closed]
        else:
            rows = [t.to_dict() for t in self._closed]

        result: List[dict] = []
        for r in rows:
            exit_time = r.get("exit_time")
            if not isinstance(exit_time, str) or not exit_time.startswith(prefix):
                continue
            enriched = dict(r)
            if "realized_pnl" not in enriched:
                enriched["realized_pnl"] = float(enriched.get("pnl") or 0.0)
            result.append(enriched)
        return result

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

    def get_portfolio(self) -> dict:
        """
        Return portfolio state in the format expected by the pipeline's _get_portfolio().

        Used when this tracker is injected into pipeline._agents["portfolio"].
        Merges both open paper trades (_open) and live position records (_positions)
        so the risk manager sees all correlated positions.
        """
        # get_open_positions() reads from _open (add_paper_trade / open_trade path)
        # Defensive filters in get_open_positions() drop phantoms in-place.
        open_trades = self.get_open_positions()
        # get_positions() reads from _positions (update_position / DB path — live broker)
        live_positions = self.get_positions()

        # Apr 2026 fix — aggregate multiple same-symbol+direction paper trades
        # into one logical position per (symbol, action) pair. Previously the
        # Fund Manager saw e.g. 5 separate MCL LONGs and rejected new signals
        # as "overexposed" when they were really just repeated entries from
        # prior pipeline runs. Aggregation sums quantity and takes the
        # weighted-average entry price so downstream agents see a realistic
        # concentration figure.
        aggregated: Dict[Tuple[str, str], dict] = {}
        for t in open_trades:
            sym = str(t.get("symbol", "")).upper()
            act = str(t.get("action", "")).lower()
            key = (sym, act)
            ep = float(t.get("entry_price", 0.0) or 0.0)
            qty = float(t.get("quantity", 0.0) or 0.0)
            if key not in aggregated:
                aggregated[key] = dict(t)
                aggregated[key]["symbol"] = sym
                aggregated[key]["action"] = act
                aggregated[key]["position_count"] = 1
            else:
                cur = aggregated[key]
                cur_qty = float(cur.get("quantity", 0.0) or 0.0)
                cur_ep = float(cur.get("entry_price", 0.0) or 0.0)
                new_qty = cur_qty + qty
                if new_qty > 0:
                    cur["entry_price"] = (cur_ep * cur_qty + ep * qty) / new_qty
                cur["quantity"] = new_qty
                cur["position_count"] = int(cur.get("position_count", 1)) + 1
        open_trades_dedup = list(aggregated.values())

        open_symbols = {k[0] for k in aggregated.keys()}
        extra_live = [p for p in live_positions if p.get("symbol", "").upper() not in open_symbols]
        positions = open_trades_dedup + extra_live
        perf = self.get_performance()
        equity = getattr(self, "_equity", None)
        if equity is None:
            try:
                equity = self._get_starting_balance()
            except Exception:
                equity = 10_000.0
        total_pnl = perf.get("total_pnl", 0.0) or 0.0
        total_value = equity + total_pnl
        return {
            "total_value": total_value,
            "available_cash": total_value * 0.5,
            "margin_used_pct": 0.0,
            "daily_pnl": perf.get("total_pnl", 0.0),
            "open_position_count": len(positions),
            "positions": positions,
        }

    # ── Session management helpers ────────────────────────────────────────────

    def flatten_all_positions(
        self,
        exit_price: Optional[float] = None,
        market_price_fn: Optional[Callable[[str], Optional[float]]] = None,
    ) -> List[dict]:
        """
        Close all open positions at session end.

        Parameters
        ----------
        exit_price : float, optional
            Blanket price for every close.  Use only when you genuinely want
            every symbol closed at the same price (rare — most EOD flows
            should pass market_price_fn instead).
        market_price_fn : callable, optional
            Per-symbol price fetcher: ``symbol -> float | None``.  Preferred
            input when closing at market: allows each symbol to settle at its
            own last-known price.  If both args are provided, market_price_fn
            wins per-symbol and exit_price is used when the fetcher returns
            None.

        Resolution order for each position:
          1. ``market_price_fn(symbol)`` if provided and returns non-None
          2. ``exit_price`` if provided
          3. ``trade.entry_price`` **as a last-resort fallback that produces
             $0 P&L** — this is the source of the 2026-04-23 Phase-3 metrics
             bug and is now escalated to ERROR-level logging so the condition
             is visible.  Callers should strive to provide a real price.

        Returns
        -------
        List of closed trade dicts (one per position that was open).
        """
        closed: List[dict] = []
        breakeven_fallback_count = 0
        open_ids = list(self._open.keys())
        for trade_id in open_ids:
            trade = self._open.get(trade_id)
            if trade is None:
                continue

            price: Optional[float] = None
            if market_price_fn is not None:
                try:
                    fetched = market_price_fn(trade.symbol)
                    if fetched is not None:
                        price = float(fetched)
                except Exception as exc:
                    logger.warning(
                        "flatten_all_positions: market_price_fn raised for %s: %s",
                        trade.symbol,
                        exc,
                    )
            if price is None and exit_price is not None:
                price = float(exit_price)
            if price is None and trade.entry_price is not None:
                price = float(trade.entry_price)
                breakeven_fallback_count += 1
            if price is None:
                logger.warning(
                    "flatten_all_positions: no price for trade %s, skipping", trade_id[:8]
                )
                continue

            try:
                result = self.close_trade(trade_id, exit_price=price)
                closed.append(result.to_dict())
            except Exception as exc:
                logger.warning("flatten_all_positions: failed to close %s: %s", trade_id[:8], exc)

        if breakeven_fallback_count > 0:
            logger.error(
                "flatten_all_positions: %d position(s) closed at entry_price "
                "(breakeven fallback). P&L will be $0 for those trades; "
                "profit_factor and win_rate will be corrupted. Pass a "
                "market_price_fn to avoid this.",
                breakeven_fallback_count,
            )
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

    # ── Persistence — JSONL (fallback only; retired when SQLite is active) ─────

    def _append_record(self, trade: PaperTrade) -> None:
        """Append a single trade record to the JSONL store (fallback audit log).

        US-1703: When a SQLite db_manager is active, SQLite is the sole source of
        truth and this deprecated JSON write is skipped entirely — the DB insert
        upstream of every caller already persisted the trade, so the jsonl append
        only duplicated it (and, being append-only with no status field, never
        reflected later curation, accreting an unbounded contaminated superset).
        The jsonl path stays live ONLY in the no-DB fallback mode (e.g. tests /
        degraded startup). The existing jsonl file is left untouched on disk.
        """
        if self._db is not None:
            return
        try:
            with self._store.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(trade.to_dict()) + "\n")
        except OSError as exc:
            logger.error("Failed to persist trade %s to JSONL: %s", trade.trade_id[:8], exc)

    def _load_history(self) -> None:
        """
        Replay trades.jsonl on startup (no-DB fallback mode only).

        Strategy: for each trade_id, keep the LAST record written (which has
        the most complete data — the closed record supersedes the open record).
        After replay, separate into open vs closed buckets.

        US-1703: When a SQLite db_manager is active, SQLite is the authoritative
        store — open positions are rebuilt from the DB by
        reload_open_positions_from_db() and closed history by
        initialize_closed_trades_from_db(), both called from the main.py
        lifespan. Replaying the deprecated jsonl here only re-introduced its
        uncurated superset (phantom/cancelled/bootstrap rows the DB had already
        voided) into in-memory state, so it is skipped. The jsonl file is left
        untouched on disk; this path runs only in the no-DB fallback.
        """
        if self._db is not None:
            return
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
