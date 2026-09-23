"""Adoption guard for cache provenance in verdict-writing runners.

Context (2026-09-17 audit, `docs/research/verdict-artifact-audit-2026-09-17.md`): 74 modules write
verdict JSON files referencing `gate_v2_verdicts`, each with its own data loader, and **none**
recorded which cache produced the verdict — so no "validated on deep data" claim was independently
verifiable. Fixing that family-wide is a mechanical change across 74 heterogeneous files, so it is
rolled out incrementally instead of in one unreviewable diff.

This test makes the rollout **visible and enforced** rather than aspirational:

1. Every verdict-writing module must either record provenance (`cache_provenance` /
   `inject_cache_provenance`) or be listed in the dated allowlist below with a reason.
2. A **new** verdict writer that does neither fails the test — the count can only go up
   deliberately, never by accident.
3. A module that HAS adopted provenance must be REMOVED from the allowlist; leaving it there
   fails the test as a stale entry, so adoption progress cannot regress silently.

The allowlist is a debt ledger, not a permanent exemption. Its line count is the program's
adoption backlog.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("API_KEY", "local-research-sandbox-dummy-not-a-credential")

import pytest

BACKTEST_DIR = Path(__file__).resolve().parents[1] / "backtest"
ALLOWLIST = Path(__file__).resolve().parent / "cache_provenance_adoption_allowlist.txt"

#: Provenance is considered adopted when the module calls the shared helper or sets the field.
ADOPTION_MARKERS = ("cache_provenance", "inject_cache_provenance")


def _verdict_writers() -> list[Path]:
    """Modules that write a verdict artifact referencing the gate_v2 verdict store."""
    writers = []
    for f in sorted(BACKTEST_DIR.glob("*.py")):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover
            continue
        if "gate_v2_verdicts" not in src:
            continue
        if not re.search(r"json\.dump|write_text", src):
            continue
        writers.append(f)
    return writers


def _allowlisted() -> set[str]:
    if not ALLOWLIST.exists():
        return set()
    return {
        ln.strip()
        for ln in ALLOWLIST.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }


def test_adoption_baseline_is_non_trivial():
    """Sanity: the writer set should be substantial, or this guard is measuring nothing."""
    writers = _verdict_writers()
    assert len(writers) >= 20, f"expected many verdict writers, found {len(writers)}"
    adopted = [f for f in writers if any(m in f.read_text(encoding="utf-8", errors="replace")
                                        for m in ADOPTION_MARKERS)]
    assert adopted, "no module records provenance — the rollout has not started"


def test_every_verdict_writer_is_adopted_or_allowlisted():
    allow = _allowlisted()
    unaccounted = [
        f.name for f in _verdict_writers()
        if f.name not in allow
        and not any(m in f.read_text(encoding="utf-8", errors="replace") for m in ADOPTION_MARKERS)
    ]
    assert not unaccounted, (
        "these verdict writers record no cache provenance and are not allowlisted "
        f"(add `inject_cache_provenance(...)`, or allowlist with a dated reason): {unaccounted}"
    )


def test_allowlist_has_no_stale_entries():
    """An adopted module must be removed from the debt ledger."""
    allow = _allowlisted()
    by_name = {f.name: f for f in _verdict_writers()}
    stale = [
        name for name in sorted(allow)
        if name in by_name
        and any(m in by_name[name].read_text(encoding="utf-8", errors="replace")
                for m in ADOPTION_MARKERS)
    ]
    assert not stale, (
        f"these modules record provenance but are still allowlisted — remove them so the "
        f"backlog count stays honest: {stale}"
    )


def test_allowlist_entries_still_exist():
    """A guard against the ledger rotting: entries must name real files."""
    names = {f.name for f in _verdict_writers()}
    ghosts = [n for n in sorted(_allowlisted()) if n not in names]
    assert not ghosts, f"allowlist names modules that no longer write verdicts: {ghosts}"
