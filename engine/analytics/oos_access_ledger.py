"""
JARVIS TRADER — out-of-sample (OOS) access ledger + contamination cap
=====================================================================
Mechanical guard against slow-motion data snooping on the held-out 2025 OOS
set (``ml-pitfalls-defense.md`` pitfall #4: "nothing mechanically prevents
someone from iterating against the OOS set until it contaminates").

Every time the OOS set is consulted for a promotion decision, ``record_access``
appends a line to ``engine/data/oos_access_log.jsonl``. ``budget_status`` counts
the accesses in the current quarter and compares them to a hard cap (default 3
promotions/quarter); ``record_if_within_budget`` refuses to log a fresh access
once the cap is hit, so a caller that routes OOS access through it cannot
silently over-fit the held-out data.

Scope: this module only reads/writes its own JSONL ledger. It touches no trade
path, risk parameter, or config — it is a research-integrity ledger, not a
trading-safety control. Wiring the guard into ``strategy_optimizer`` (so
promotions actually route through it) is a deliberate follow-up, kept out of
this change so it stays additive.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LEDGER_PATH = os.path.normpath(os.path.join(_HERE, "..", "data", "oos_access_log.jsonl"))

# Hard cap on OOS-set consultations per calendar quarter (ml-pitfalls-defense.md).
DEFAULT_OOS_ACCESS_CAP = 3
DEFAULT_DATASET = "2025_oos"


class OOSBudgetExceeded(RuntimeError):
    """Raised when an OOS access would exceed the per-quarter contamination cap."""


def quarter_of(dt: datetime) -> str:
    """Calendar quarter label for ``dt``, e.g. ``2026Q3``."""
    return f"{dt.year}Q{(dt.month - 1) // 3 + 1}"


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _read_ledger(ledger_path: str) -> list[dict]:
    if not os.path.exists(ledger_path):
        return []
    out: list[dict] = []
    with open(ledger_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def count_accesses(
    quarter: str,
    *,
    dataset: str = DEFAULT_DATASET,
    ledger_path: str = DEFAULT_LEDGER_PATH,
) -> int:
    """Number of recorded accesses to ``dataset`` in ``quarter``."""
    return sum(
        1
        for r in _read_ledger(ledger_path)
        if r.get("quarter") == quarter and r.get("dataset") == dataset
    )


@dataclass
class BudgetStatus:
    """Snapshot of the OOS-access budget for one dataset in one quarter."""

    dataset: str
    quarter: str
    used: int
    cap: int
    remaining: int
    exceeded: bool

    def as_dict(self) -> dict:
        return asdict(self)


def budget_status(
    *,
    cap: int = DEFAULT_OOS_ACCESS_CAP,
    quarter: Optional[str] = None,
    dataset: str = DEFAULT_DATASET,
    ledger_path: str = DEFAULT_LEDGER_PATH,
    now: Optional[datetime] = None,
) -> BudgetStatus:
    """Current OOS-access budget for ``dataset`` (defaults to the current quarter)."""
    q = quarter or quarter_of(_now(now))
    used = count_accesses(q, dataset=dataset, ledger_path=ledger_path)
    remaining = max(0, cap - used)
    return BudgetStatus(
        dataset=dataset,
        quarter=q,
        used=used,
        cap=cap,
        remaining=remaining,
        exceeded=used >= cap,
    )


def record_access(
    purpose: str,
    *,
    dataset: str = DEFAULT_DATASET,
    ledger_path: str = DEFAULT_LEDGER_PATH,
    now: Optional[datetime] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Append one OOS-access record to the ledger and return it. Does not enforce."""
    ts = _now(now)
    record = {
        "timestamp": ts.isoformat(),
        "quarter": quarter_of(ts),
        "dataset": dataset,
        "purpose": purpose,
    }
    if extra:
        record.update(extra)
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def record_if_within_budget(
    purpose: str,
    *,
    cap: int = DEFAULT_OOS_ACCESS_CAP,
    dataset: str = DEFAULT_DATASET,
    ledger_path: str = DEFAULT_LEDGER_PATH,
    now: Optional[datetime] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Record an OOS access only if the quarter's cap is not already reached.

    Raises :class:`OOSBudgetExceeded` otherwise — the mechanical cap. Route a
    promotion's OOS consultation through this to make contamination impossible to
    do silently.
    """
    status = budget_status(
        cap=cap, dataset=dataset, ledger_path=ledger_path, now=now
    )
    if status.exceeded:
        logger.warning(
            "[OOSLedger] OOS access DENIED for %s: %s already used %d/%d in %s",
            purpose, dataset, status.used, status.cap, status.quarter,
        )
        raise OOSBudgetExceeded(
            f"OOS access cap reached for {dataset} in {status.quarter}: "
            f"{status.used}/{status.cap} used. Lock the spec and forward-test instead."
        )
    return record_access(
        purpose, dataset=dataset, ledger_path=ledger_path, now=now, extra=extra
    )
