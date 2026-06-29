"""Cross-path paper-order submission dedup ledger (first-submission-wins).

Two autonomous paper paths submit through the SAME
``SafetyLayer.submit_paper_order`` with SEPARATE idempotency:
  * the auto-approve queue (``approval_queue_router.approve_candidate``), keyed by
    an approval-queue int row id;
  * the systematic bridge (``systematic.live_signal_executor``), keyed by a
    registry candidate id.

With BOTH live, the same market opportunity ``(symbol, action, trading_date)``
could be submitted by each path -> unintended 2x exposure / double fill. The
SafetyLayer caps *per-order* size but does not dedup across these two front-ends.
This module is the ONE shared ledger both paths consult so the first path to
submit a given ``(symbol, action, trading_date)`` claims it and the other skips.

``(symbol, action, trading_date)`` is also the only key BOTH paths can actually
compute (their native ids live in different namespaces). First-wins is the safe
default for the paper-validation phase; the ledger retains ``source`` +
``native_id`` so attribution survives the dedup. Widening the key with a strategy
tag (to allow intentional multi-strategy stacking on one symbol) is a deliberate
future change, not the default.

Usage (both paths):
    key = dedup.make_key(symbol, action, trading_date)
    if dedup.already_submitted(key):
        skip            # another path already submitted this opportunity
    result = await safety.submit_paper_order(...)
    if result["approved"]:
        dedup.record(key, source="queue", native_id=str(row_id))

Check-before-submit + record-after-success is correct for the single-process
paper scheduler (the autonomous tick and the bridge run sequentially, not truly
concurrent), and avoids falsely blocking the other path when a submit is rejected.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
# Shared runtime ledger under the gitignored engine/data/ tree.
_DEFAULT_LEDGER = _HERE.parent / "data" / "systematic_exec" / "submission_dedup.jsonl"


def _to_iso_date(value: Any) -> str:
    """Normalize a date/datetime/str to an ISO ``YYYY-MM-DD`` string."""
    if isinstance(value, _dt.datetime):
        return value.date().isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    s = str(value).strip()
    # An ISO datetime string ("2026-06-29T14:00:00Z") -> take the date prefix.
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


class SubmissionDedup:
    """Shared first-wins ledger keyed by (symbol, action, trading_date)."""

    def __init__(self, ledger_path: Optional[Path | str] = None) -> None:
        self._path = Path(ledger_path) if ledger_path else _DEFAULT_LEDGER

    @staticmethod
    def make_key(symbol: str, action: str, trading_date: Any) -> str:
        return f"{str(symbol).upper()}|{str(action).upper()}|{_to_iso_date(trading_date)}"

    def _keys(self) -> set[str]:
        if not self._path.exists():
            return set()
        keys: set[str] = set()
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = rec.get("key")
            if k:
                keys.add(k)
        return keys

    def already_submitted(self, key: str) -> bool:
        """True if any path has already recorded a submission for ``key``."""
        return key in self._keys()

    def record(
        self,
        key: str,
        *,
        source: str,
        native_id: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Claim ``key`` for ``source``. Returns True if newly recorded, False if
        it was already present (idempotent — never writes a duplicate line)."""
        if key in self._keys():
            return False
        record: dict[str, Any] = {"key": key, "source": source, "native_id": native_id}
        if extra:
            record.update(extra)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return True
