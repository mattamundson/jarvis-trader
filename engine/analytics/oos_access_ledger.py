"""OOS access ledger — mechanical data-snooping guard (ml-pitfalls-defense.md pitfall #4).

Nothing in the pipeline mechanically stops re-running an optimizer or backtest
against the held-out out-of-sample (OOS) set until it is contaminated — "data
snooping in slow motion". This ledger records each OOS *campaign* access per
symbol and answers a per-quarter budget question, so callers can WARN when a
symbol is being over-searched.

Report-only by design: this module never blocks and never raises into a caller's
hot path. Turning the budget into a hard gate that refuses a promotion is a
separate ``[safety-review]``/Tier-3 change — the rule asks for the diagnostic
first. Reuses nothing from the safety layer and touches no config/risk state.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_LEDGER = _DATA_DIR / "oos_access_log.jsonl"

# The rule's suggested ceiling: ~3 production promotions per quarter per symbol.
DEFAULT_QUARTERLY_CAP = 3


def quarter_key(dt: datetime) -> str:
    """Calendar-quarter label, e.g. ``2026Q3``."""
    return f"{dt.year}Q{(dt.month - 1) // 3 + 1}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_oos_access(
    symbol: str,
    context: str,
    *,
    kind: str = "campaign",
    now: Optional[datetime] = None,
    ledger_path: Path | str = DEFAULT_LEDGER,
) -> dict:
    """Append one OOS-access record and return the written entry.

    Args:
        symbol: instrument the OOS set was evaluated for (e.g. ``MES``).
        context: free-form provenance (e.g. ``optimizer:1h:50iter``).
        kind: access class — ``campaign`` (an optimization run) or ``promotion``
            (a prod promotion decision). Lets budgets be scoped per class.
        now: injectable timestamp for deterministic tests.
        ledger_path: JSONL ledger location.
    """
    ts = now or _utcnow()
    entry = {
        "timestamp": ts.isoformat(),
        "symbol": str(symbol),
        "context": str(context),
        "kind": str(kind),
        "quarter": quarter_key(ts),
    }
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def _iter_entries(ledger_path: Path | str) -> Iterator[dict]:
    path = Path(ledger_path)
    if not path.exists():
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # Tolerate a single corrupt line — accounting must never crash a caller.
                logger.debug("skipping unparseable oos-ledger line")
                continue


def oos_access_count(
    symbol: str,
    *,
    quarter: Optional[str] = None,
    kind: Optional[str] = None,
    now: Optional[datetime] = None,
    ledger_path: Path | str = DEFAULT_LEDGER,
) -> int:
    """Count OOS accesses for ``symbol`` in the given (default current) quarter."""
    q = quarter or quarter_key(now or _utcnow())
    n = 0
    for e in _iter_entries(ledger_path):
        if e.get("symbol") != str(symbol):
            continue
        if e.get("quarter") != q:
            continue
        if kind is not None and e.get("kind") != kind:
            continue
        n += 1
    return n


def check_oos_budget(
    symbol: str,
    *,
    cap: int = DEFAULT_QUARTERLY_CAP,
    quarter: Optional[str] = None,
    kind: Optional[str] = None,
    now: Optional[datetime] = None,
    ledger_path: Path | str = DEFAULT_LEDGER,
) -> dict:
    """Report-only budget check for a symbol's OOS accesses this quarter.

    Returns:
        {
            "symbol": str,
            "quarter": str,          # e.g. "2026Q3"
            "count": int,            # accesses so far this quarter
            "cap": int,
            "exceeded": bool,        # count > cap
            "remaining": int,        # max(0, cap - count)
        }
    """
    q = quarter or quarter_key(now or _utcnow())
    count = oos_access_count(symbol, quarter=q, kind=kind, now=now, ledger_path=ledger_path)
    cap_int = int(cap)
    return {
        "symbol": str(symbol),
        "quarter": q,
        "count": count,
        "cap": cap_int,
        "exceeded": count > cap_int,
        "remaining": max(0, cap_int - count),
    }
