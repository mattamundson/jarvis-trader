"""Gate v2 policy — advisory read-side for persisted gate v2 verdicts.

Phase 3 LIGHT implementation (`project_gate_v2_proposal.md`). Read-only
helpers for dashboards, cron logs, and future hard-enforcement work. This
module DOES NOT block trading routing — it exposes eligibility signals that
the rest of the codebase can advisorily consult.

Contract:
  * `get_last_verdict(symbol) -> VerdictSnapshot | None` — newest non-stale
     verdict across all rank files for `symbol`.
  * `is_ungate_eligible(symbol) -> bool` — True iff the most recent non-stale
     verdict for `symbol` has `verdict == "PASS"`. Default-deny on missing.
  * `list_verdicts() -> list[VerdictSnapshot]` — all non-stale verdicts.

Staleness: any verdict older than `MAX_VERDICT_AGE_DAYS` is treated as
missing. This prevents a one-shot PASS from implicitly authorizing live
trading forever without a fresh re-score.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Weekly cron cadence is 7 days — 14 days tolerates one missed run before
# advisory eligibility flips to default-deny.
MAX_VERDICT_AGE_DAYS = 14


# Lazy-resolved to avoid circular imports and to let tests monkeypatch.
def _default_verdicts_dir() -> Path:
    """Default verdicts directory: `<engine>/data/gate_v2_verdicts/`."""
    return Path(__file__).resolve().parent.parent / "data" / "gate_v2_verdicts"


class VerdictSnapshot:
    """Read-side mirror of `scripts.gate_v2_orchestrator.VerdictSnapshot`.

    Intentionally *not* importing the orchestrator's dataclass to avoid
    coupling the read path to the write path — routing code that reads
    verdicts should never have to import heavy numpy/statistics deps.
    """
    __slots__ = (
        "symbol", "family", "rank", "verdict", "passed_via",
        "core_verdict", "alt_verdict", "n_core_passed", "n_alt_passed",
        "created_at", "aux_freshness",
    )

    def __init__(self, doc: dict):
        self.symbol = doc["symbol"]
        self.family = doc["family"]
        self.rank = doc["rank"]
        self.verdict = doc["verdict"]
        self.passed_via = doc.get("passed_via")
        self.core_verdict = doc.get("core_verdict", "FAIL")
        self.alt_verdict = doc.get("alt_verdict", "UNSCORED")
        self.n_core_passed = doc.get("n_core_passed", 0)
        self.n_alt_passed = doc.get("n_alt_passed", 0)
        self.created_at = doc["created_at"]
        self.aux_freshness = doc.get("aux_freshness", {})

    def age_days(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(tz=timezone.utc)
        created = datetime.fromisoformat(self.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (now - created).total_seconds() / 86400.0

    def is_stale(self, max_age_days: float = MAX_VERDICT_AGE_DAYS) -> bool:
        return self.age_days() > max_age_days


def _iter_verdict_files(verdicts_dir: Optional[Path] = None):
    d = verdicts_dir or _default_verdicts_dir()
    if not d.exists():
        return
    for p in d.glob("*.json"):
        try:
            doc = json.loads(p.read_text())
            yield VerdictSnapshot(doc)
        except Exception as exc:
            logger.warning("gate_v2_policy: unreadable verdict file %s: %s", p, exc)


def get_last_verdict(
    symbol: str, verdicts_dir: Optional[Path] = None
) -> Optional[VerdictSnapshot]:
    """Return the newest non-stale verdict for `symbol`, or None."""
    sym_upper = symbol.upper()
    candidates = [
        v for v in _iter_verdict_files(verdicts_dir)
        if v.symbol.upper() == sym_upper and not v.is_stale()
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda v: v.created_at, reverse=True)
    return candidates[0]


def is_ungate_eligible(
    symbol: str, verdicts_dir: Optional[Path] = None
) -> bool:
    """Default-deny advisory: `True` iff ANY non-stale PASS verdict exists
    for `symbol` across all families.

    A FAIL in one family (e.g. trend_rv_filter) does not negate a PASS in
    another (e.g. trend). The routing layer decides which family to trade;
    this function asks "is there a valid green light for this symbol at all."

    Advisory only — does NOT block any routing decision. Call sites may
    log a warning when this disagrees with the actual routing state.
    """
    sym_upper = symbol.upper()
    return any(
        v.verdict == "PASS"
        for v in _iter_verdict_files(verdicts_dir)
        if v.symbol.upper() == sym_upper and not v.is_stale()
    )


def list_verdicts(
    verdicts_dir: Optional[Path] = None,
) -> list[VerdictSnapshot]:
    """Return every non-stale verdict snapshot, newest first."""
    fresh = [v for v in _iter_verdict_files(verdicts_dir) if not v.is_stale()]
    fresh.sort(key=lambda v: v.created_at, reverse=True)
    return fresh
