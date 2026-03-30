"""
JARVIS Trader Options Engine — Position Manager
Persists options positions to SQLite and provides roll/expiry/P&L tracking.
"""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Generator, Literal, Optional

from .greeks_monitor import GreeksMonitor, PortfolioGreeks
from .strategy_executor import OptionsLeg, OptionsOrder, OptionsStrategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database path
# ---------------------------------------------------------------------------

_DB_DIR  = Path(__file__).resolve().parent.parent / "db"
_DB_PATH = _DB_DIR / "options_positions.db"


# ---------------------------------------------------------------------------
# OptionsPosition dataclass
# ---------------------------------------------------------------------------

@dataclass
class OptionsPosition:
    """Represents a live or closed options position."""

    id: str
    symbol: str
    strategy: str                   # OptionsStrategy.value
    legs: list[dict]                # serialised OptionsLeg dicts
    entry_premium: float            # net credit (+) or debit (-) per share at fill
    current_premium: float          # latest mark-to-market premium per share
    entry_date: datetime
    expiry: date
    status: Literal["OPEN", "CLOSED", "EXPIRED"]
    greeks: dict[str, float] = field(default_factory=dict)
    close_premium: Optional[float] = None
    close_date: Optional[datetime] = None
    notes: str = ""

    @property
    def unrealised_pnl(self) -> float:
        """Unrealised P&L per spread in dollars (positive = profit)."""
        return round((self.entry_premium - self.current_premium) * 100, 2)

    @property
    def realised_pnl(self) -> Optional[float]:
        """Realised P&L in dollars once the position is closed."""
        if self.close_premium is None:
            return None
        return round((self.entry_premium - self.close_premium) * 100, 2)

    @property
    def dte(self) -> int:
        """Remaining days to expiration from today."""
        today = datetime.utcnow().date()
        delta = self.expiry - today
        return max(0, delta.days)


# ---------------------------------------------------------------------------
# SQLite persistence helpers
# ---------------------------------------------------------------------------

def _init_db(db_path: Path) -> None:
    """Create the options_positions table if it does not exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS options_positions (
                id             TEXT PRIMARY KEY,
                symbol         TEXT NOT NULL,
                strategy       TEXT NOT NULL,
                legs_json      TEXT NOT NULL,
                entry_premium  REAL NOT NULL,
                current_premium REAL NOT NULL,
                entry_date     TEXT NOT NULL,
                expiry         TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'OPEN',
                greeks_json    TEXT NOT NULL DEFAULT '{}',
                close_premium  REAL,
                close_date     TEXT,
                notes          TEXT DEFAULT ''
            )
        """)
        conn.commit()
    logger.debug("[OptionsPositionManager] DB initialised at %s", db_path)


@contextmanager
def _get_conn(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Context manager yielding a WAL-mode SQLite connection."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_position(row: sqlite3.Row) -> OptionsPosition:
    """Convert a SQLite row to an :class:`OptionsPosition`."""
    return OptionsPosition(
        id=row["id"],
        symbol=row["symbol"],
        strategy=row["strategy"],
        legs=json.loads(row["legs_json"]),
        entry_premium=row["entry_premium"],
        current_premium=row["current_premium"],
        entry_date=datetime.fromisoformat(row["entry_date"]),
        expiry=date.fromisoformat(row["expiry"]),
        status=row["status"],
        greeks=json.loads(row["greeks_json"]) if row["greeks_json"] else {},
        close_premium=row["close_premium"],
        close_date=datetime.fromisoformat(row["close_date"]) if row["close_date"] else None,
        notes=row["notes"] or "",
    )


def _legs_to_json(legs: list[OptionsLeg]) -> str:
    return json.dumps([
        {
            "action": leg.action,
            "option_type": leg.option_type,
            "strike": leg.strike,
            "expiry": str(leg.expiry),
            "quantity": leg.quantity,
        }
        for leg in legs
    ])


# ---------------------------------------------------------------------------
# OptionsPositionManager
# ---------------------------------------------------------------------------

class OptionsPositionManager:
    """Manages open and closed options positions with SQLite persistence.

    All positions are stored in ``engine/db/options_positions.db``.

    Example usage::

        mgr = OptionsPositionManager()
        pos = mgr.add_position(order, fill_premium=1.45)
        positions = mgr.get_positions()
        rolls = mgr.check_roll_candidates()
        greeks = mgr.get_portfolio_greeks()
        pnl = mgr.close_position(pos.id, close_premium=0.30)
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        delta_alert_threshold: float = 0.30,
    ) -> None:
        self._db_path = db_path or _DB_PATH
        _init_db(self._db_path)
        self._greeks_monitor = GreeksMonitor(delta_alert_threshold=delta_alert_threshold)
        logger.info("[OptionsPositionManager] Ready | db=%s", self._db_path)

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------

    def add_position(
        self,
        order: OptionsOrder,
        fill_premium: float,
    ) -> OptionsPosition:
        """Record a new options position from a filled order.

        Args:
            order:        The :class:`OptionsOrder` that was executed.
            fill_premium: Actual fill premium per share (net credit or debit).

        Returns:
            The newly created :class:`OptionsPosition`.
        """
        pos_id = f"opt-{uuid.uuid4().hex[:8]}"

        # Determine the earliest expiry among legs as the position expiry
        expiry = min(leg.expiry for leg in order.legs)

        position = OptionsPosition(
            id=pos_id,
            symbol=order.symbol,
            strategy=order.strategy.value,
            legs=[
                {
                    "action": leg.action,
                    "option_type": leg.option_type,
                    "strike": leg.strike,
                    "expiry": str(leg.expiry),
                    "quantity": leg.quantity,
                }
                for leg in order.legs
            ],
            entry_premium=fill_premium,
            current_premium=fill_premium,
            entry_date=datetime.utcnow(),
            expiry=expiry,
            status="OPEN",
            greeks={},
            notes=order.notes,
        )

        with _get_conn(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO options_positions
                    (id, symbol, strategy, legs_json, entry_premium, current_premium,
                     entry_date, expiry, status, greeks_json, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position.id,
                    position.symbol,
                    position.strategy,
                    json.dumps(position.legs),
                    position.entry_premium,
                    position.current_premium,
                    position.entry_date.isoformat(),
                    str(position.expiry),
                    position.status,
                    json.dumps(position.greeks),
                    position.notes,
                ),
            )

        logger.info(
            "[OptionsPositionManager] ADD %s | %s %s fill=%.4f expiry=%s",
            pos_id, order.symbol, order.strategy.value, fill_premium, expiry,
        )
        return position

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_positions(self, status: Optional[str] = "OPEN") -> list[OptionsPosition]:
        """Return all positions, optionally filtered by status.

        Args:
            status: ``"OPEN"``, ``"CLOSED"``, ``"EXPIRED"``, or ``None`` for all.

        Returns:
            List of :class:`OptionsPosition` instances.
        """
        with _get_conn(self._db_path) as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM options_positions WHERE status = ? ORDER BY entry_date DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM options_positions ORDER BY entry_date DESC"
                ).fetchall()

        return [_row_to_position(r) for r in rows]

    def get_position(self, position_id: str) -> Optional[OptionsPosition]:
        """Fetch a single position by ID."""
        with _get_conn(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM options_positions WHERE id = ?", (position_id,)
            ).fetchone()
        return _row_to_position(row) if row else None

    def get_expiring_soon(self, days: int = 7) -> list[OptionsPosition]:
        """Return open positions expiring within ``days`` calendar days.

        Args:
            days: Look-ahead window (default 7).

        Returns:
            List of :class:`OptionsPosition` instances sorted by nearest expiry first.
        """
        all_open = self.get_positions(status="OPEN")
        expiring = [p for p in all_open if p.dte <= days]
        expiring.sort(key=lambda p: p.dte)
        logger.debug(
            "[OptionsPositionManager] get_expiring_soon(days=%d) → %d positions",
            days, len(expiring),
        )
        return expiring

    def check_roll_candidates(self) -> list[OptionsPosition]:
        """Return open positions where a short-leg delta has breached 0.30.

        Positions are flagged as roll candidates when the absolute value of
        the short-leg delta in the stored Greeks exceeds the monitor threshold.

        Returns:
            List of :class:`OptionsPosition` instances that should be rolled.
        """
        all_open = self.get_positions(status="OPEN")
        candidates = []
        threshold = self._greeks_monitor.delta_alert_threshold

        for pos in all_open:
            greeks = pos.greeks
            delta = greeks.get("delta", 0.0)

            # Heuristic: if the recorded delta is for a short leg, check breach
            is_short_leg_dominant = any(
                leg.get("action") == "SELL" for leg in pos.legs
            )
            if is_short_leg_dominant and abs(delta) >= threshold:
                candidates.append(pos)
                logger.warning(
                    "[OptionsPositionManager] ROLL CANDIDATE %s | %s | delta=%.4f threshold=%.2f",
                    pos.id, pos.symbol, delta, threshold,
                )

        return candidates

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_greeks(
        self,
        position_id: str,
        greeks: dict[str, float],
        current_premium: Optional[float] = None,
    ) -> bool:
        """Update the stored Greeks (and optionally mark) for a position.

        Args:
            position_id:     Position to update.
            greeks:          New Greeks dict.
            current_premium: Updated mark-to-market premium per share.

        Returns:
            True if the position was found and updated, False otherwise.
        """
        if current_premium is not None:
            with _get_conn(self._db_path) as conn:
                conn.execute(
                    """
                    UPDATE options_positions
                       SET greeks_json = ?, current_premium = ?
                     WHERE id = ?
                    """,
                    (json.dumps(greeks), current_premium, position_id),
                )
        else:
            with _get_conn(self._db_path) as conn:
                conn.execute(
                    "UPDATE options_positions SET greeks_json = ? WHERE id = ?",
                    (json.dumps(greeks), position_id),
                )

        # Sync monitor
        pos = self.get_position(position_id)
        if pos:
            self._greeks_monitor.update_position(
                position_id=position_id,
                symbol=pos.symbol,
                strategy=pos.strategy,
                greeks=greeks,
                leg_type="short" if any(l.get("action") == "SELL" for l in pos.legs) else "long",
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def close_position(
        self,
        position_id: str,
        close_premium: float,
    ) -> dict:
        """Close an open options position and calculate P&L.

        Args:
            position_id:   ID of the position to close.
            close_premium: Premium paid (debit) or received (credit) to close.
                           For a short position closed by buying it back, this is
                           the buy-back cost (positive value).

        Returns:
            Dictionary with keys:
            - position_id
            - symbol
            - strategy
            - entry_premium
            - close_premium
            - realised_pnl
            - status
            - close_date
        """
        pos = self.get_position(position_id)
        if pos is None:
            raise ValueError(f"Position {position_id!r} not found.")
        if pos.status != "OPEN":
            raise ValueError(f"Position {position_id!r} is already {pos.status}.")

        close_date = datetime.utcnow()

        # P&L: for credit positions, profit = entry_premium - close_premium
        # For debit positions, profit = close_premium - abs(entry_premium)
        if pos.entry_premium >= 0:
            # Credit spread or covered call: we collected premium, pay to close
            realised_pnl = round((pos.entry_premium - close_premium) * 100, 2)
        else:
            # Debit position (protective put, straddle, etc.)
            realised_pnl = round((close_premium - abs(pos.entry_premium)) * 100, 2)

        with _get_conn(self._db_path) as conn:
            conn.execute(
                """
                UPDATE options_positions
                   SET status = 'CLOSED', close_premium = ?, close_date = ?
                 WHERE id = ?
                """,
                (close_premium, close_date.isoformat(), position_id),
            )

        self._greeks_monitor.remove_position(position_id)

        logger.info(
            "[OptionsPositionManager] CLOSE %s | %s %s | pnl=$%.2f",
            position_id, pos.symbol, pos.strategy, realised_pnl,
        )

        return {
            "position_id": position_id,
            "symbol": pos.symbol,
            "strategy": pos.strategy,
            "entry_premium": pos.entry_premium,
            "close_premium": close_premium,
            "realised_pnl": realised_pnl,
            "status": "CLOSED",
            "close_date": close_date.isoformat(),
        }

    # ------------------------------------------------------------------
    # Portfolio Greeks
    # ------------------------------------------------------------------

    def get_portfolio_greeks(self) -> PortfolioGreeks:
        """Aggregate live Greeks across all open positions from the monitor.

        Returns:
            :class:`PortfolioGreeks` with total delta, gamma, theta, vega, rho.
        """
        return self._greeks_monitor.get_portfolio_greeks()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a one-line dashboard summary of the options book."""
        open_positions = self.get_positions("OPEN")
        expiring = self.get_expiring_soon(7)
        rolls = self.check_roll_candidates()
        pg = self.get_portfolio_greeks()

        return (
            f"Options book: {len(open_positions)} open | "
            f"{len(expiring)} expiring ≤7d | "
            f"{len(rolls)} roll candidate(s) | "
            f"Port Δ {pg.total_delta:+.4f} Θ {pg.total_theta:+.4f}/day"
        )
