"""
Out-of-Sample Access Ledger
===========================
Mechanical guard against data-snooping the 2025 OOS holdout (ml-pitfalls-defense
pitfall #4). Every touch of the sealed OOS set should be RECORDED, and repeated
touches within a quarter flagged, because iterating a strategy against the
holdout until it passes contaminates the p-value itself — the most insidious
failure mode (Masters, target-fiddling).

This module provides the MECHANISM only: an append-only ledger in
``optimization_log.jsonl`` plus a per-quarter counter and a soft cap check. It is
deliberately NOT wired into a specific call site here — where the OOS boundary is
actually read is a design decision (optimizer entry vs data-loader vs promotion
gate), and wiring it wrong would either give false protection or block legitimate
work. Adopt ``record_oos_access`` / ``quarter_access_count`` at the chosen
chokepoint; default posture is warn-only (``enforce=False``) so it never blocks
until someone deliberately turns enforcement on.

Standalone (no config/pydantic import) so it runs in a lightweight venv and tests.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Default ledger location mirrors optimization/strategy_optimizer.py LOG_FILE.
DEFAULT_LEDGER = Path(__file__).resolve().parent.parent / "data" / "optimization_log.jsonl"

# Default soft cap: prod OOS promotions per quarter (ml-pitfalls-defense proposes ~3).
DEFAULT_QUARTER_CAP = 3

_RECORD_KIND = "oos_access"


@dataclass(frozen=True)
class OOSAccessCheck:
    """Result of recording/checking an OOS access."""

    symbol: str
    quarter: str          # e.g. "2026Q3"
    count_this_quarter: int
    cap: int
    over_cap: bool
    enforced: bool
    allowed: bool         # False only when over_cap AND enforced


def quarter_label(dt: datetime) -> str:
    """Calendar-quarter label like ``2026Q3`` for a timezone-aware datetime."""
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}Q{q}"


def _iter_records(ledger: Path):
    if not ledger.exists():
        return
    for line in ledger.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # tolerate non-ledger lines in a shared log file
        if rec.get("kind") == _RECORD_KIND:
            yield rec


def quarter_access_count(symbol: str, quarter: str, *, ledger: Path = DEFAULT_LEDGER) -> int:
    """Count prior OOS-access records for ``symbol`` in ``quarter``."""
    return sum(
        1
        for r in _iter_records(ledger)
        if r.get("symbol") == symbol and r.get("quarter") == quarter
    )


def record_oos_access(
    symbol: str,
    purpose: str,
    *,
    now: datetime | None = None,
    cap: int = DEFAULT_QUARTER_CAP,
    enforce: bool = False,
    ledger: Path = DEFAULT_LEDGER,
) -> OOSAccessCheck:
    """Append an OOS-access record and return the quarter's cap status.

    ``now`` must be supplied by the caller (tests pass a fixed instant; production
    passes ``datetime.now(timezone.utc)``) — this module never calls now() itself
    so it stays deterministic. When ``enforce`` is False (default) the access is
    always ``allowed``; the record and the ``over_cap`` flag still let a dashboard
    or reviewer see contamination pressure before it's turned into a hard gate.
    """
    if now is None:
        raise ValueError("record_oos_access requires an explicit `now` (utc datetime)")
    quarter = quarter_label(now)
    prior = quarter_access_count(symbol, quarter, ledger=ledger)
    count = prior + 1
    over_cap = count > cap
    allowed = not (over_cap and enforce)

    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a") as fh:
        fh.write(
            json.dumps(
                {
                    "kind": _RECORD_KIND,
                    "ts": now.astimezone(timezone.utc).isoformat(),
                    "symbol": symbol,
                    "quarter": quarter,
                    "purpose": purpose,
                    "count_this_quarter": count,
                    "cap": cap,
                    "over_cap": over_cap,
                    "enforced": enforce,
                    "allowed": allowed,
                }
            )
            + "\n"
        )

    if over_cap:
        level = logger.error if enforce else logger.warning
        level(
            "[OOS-LEDGER] %s OOS access #%d in %s exceeds cap %d (enforce=%s) — %s",
            symbol, count, quarter, cap, enforce,
            "BLOCKED" if not allowed else "allowed (warn-only)",
        )

    return OOSAccessCheck(
        symbol=symbol,
        quarter=quarter,
        count_this_quarter=count,
        cap=cap,
        over_cap=over_cap,
        enforced=enforce,
        allowed=allowed,
    )
