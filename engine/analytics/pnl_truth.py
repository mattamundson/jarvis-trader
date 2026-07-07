"""Honest paper-P&L truth surface — one number with an explicit trust verdict.

The system's recurring failure mode has been *confident fabrication*: a stale
mark or a corrupted ("phantom") trade reported as real P&L, so "how did paper do?"
could never be answered honestly. This module is the antidote: it composes a single
realized-P&L number from the closed-trade ledger and returns it ONLY when a small
set of honesty preconditions hold. When they don't, it returns ``DEGRADED`` with
``realized_pnl=None`` — it says "I don't know" rather than emit a fake ``0.0``.

It deliberately does NOT re-detect bad prices: the entry/exit guards already do that
(``engine/risk/entry_price_sanity.py``, ``engine/risk/exit_price_sanity.py``), and
rows already marked ``phantom``/``cancelled``/``void`` are simply excluded and counted.
This is the *reporting* honesty layer on top of those *submission* guards.

Trust verdict:
  TRUSTED  — ``realized_pnl`` is a real number you can stake a decision on.
  DEGRADED — ``realized_pnl is None``; one or more preconditions failed (listed in
             ``reasons``). Never present a fabricated value as if it were real.

A genuinely empty ledger is TRUSTED with ``realized_pnl == 0.0`` (zero trades really
is zero P&L); a *missing* source is DEGRADED (absence of data is not data).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Statuses whose rows are real but must NOT count toward realized P&L.
EXCLUDED_STATUSES = frozenset({"phantom", "cancelled", "void"})

# Default tolerance (account currency) for agreement between two P&L sources.
DEFAULT_TOLERANCE = 0.01


@dataclass(frozen=True)
class PnlTruth:
    """A realized-P&L reading with its provenance and a trust verdict."""

    status: str  # "TRUSTED" | "DEGRADED"
    realized_pnl: float | None
    closed_trades: int
    excluded_trades: int
    reasons: tuple[str, ...]
    sources_present: tuple[str, ...]

    @property
    def trusted(self) -> bool:
        return self.status == "TRUSTED"


def compute_pnl_truth(
    trades: Iterable[Mapping[str, object]] | None,
    *,
    cross_source_pnl: float | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> PnlTruth:
    """Compose one honest realized-P&L verdict from a closed-trade ledger.

    ``trades`` — rows shaped like ``paper_trades`` (need ``status`` and ``pnl``).
    ``None`` means the source could not be loaded → DEGRADED (not zero).
    ``cross_source_pnl`` — an independently computed realized total for the same
    window (e.g. ``PortfolioTracker.get_performance()['total_pnl']``); a divergence
    beyond ``tolerance`` degrades the verdict — two disagreeing sources cannot both
    be trusted.
    """
    if trades is None:
        return PnlTruth("DEGRADED", None, 0, 0, ("no_source",), ())

    rows = list(trades)
    excluded = sum(1 for t in rows if str(t.get("status")) in EXCLUDED_STATUSES)
    closed = [t for t in rows if str(t.get("status")) == "closed"]
    reasons: list[str] = []

    # A closed trade with no P&L is corrupt — we cannot honestly sum the ledger.
    missing_pnl = sum(1 for t in closed if t.get("pnl") is None)
    if missing_pnl:
        reasons.append(f"closed_trade_missing_pnl:{missing_pnl}")

    realized = sum(float(t["pnl"]) for t in closed if t.get("pnl") is not None)
    sources = ["ledger"]

    if cross_source_pnl is not None:
        sources.append("cross_source")
        if abs(realized - float(cross_source_pnl)) > tolerance:
            reasons.append(
                f"source_divergence:ledger={realized:.4f},cross={float(cross_source_pnl):.4f}"
            )

    if reasons:
        logger.warning("paper P&L DEGRADED: %s", "; ".join(reasons))
        return PnlTruth("DEGRADED", None, len(closed), excluded, tuple(reasons), tuple(sources))

    return PnlTruth("TRUSTED", realized, len(closed), excluded, (), tuple(sources))


def pnl_truth_from_sqlite(
    db_path: str | Path, *, cross_source_pnl: float | None = None
) -> PnlTruth:
    """Load ``paper_trades`` from SQLite and compute the verdict. Fail honest: a
    missing or unreadable DB returns DEGRADED, never a fabricated zero."""
    path = Path(db_path)
    if not path.is_file():
        return PnlTruth("DEGRADED", None, 0, 0, ("db_not_found",), ())
    try:
        con = sqlite3.connect(str(path))
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute("SELECT status, pnl FROM paper_trades")]
        con.close()
    except sqlite3.Error as exc:
        logger.warning("paper P&L DEGRADED: sqlite error %s", exc)
        return PnlTruth("DEGRADED", None, 0, 0, (f"db_error:{type(exc).__name__}",), ())
    return compute_pnl_truth(rows, cross_source_pnl=cross_source_pnl)
