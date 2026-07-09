"""Architecture regression: upsert_daily_pnl() is the SOLE runtime writer of daily_pnl.

The 2026-06 phantom-P&L incident's root cause was *multiple writers with
mismatched balance bases* -- a $10k-anchored EOD writer alongside a ~$50k
monitor-state writer -- which manufactured phantom +/-$40k "realized" days. The
existing test_daily_pnl_integrity.py suite locks the VALUE side (each written row
must be plausible: balance identity, no basis flip). This test locks the
ORTHOGONAL invariant the value guard cannot enforce: that only the single
guarded writer path exists at all.

A second runtime writer can emit rows that each pass the per-row value guard yet
carry a different balance basis (internally consistent, externally wrong) -- the
precise failure mode that caused the incident. The per-row guard in
DailyPnLMixin._daily_pnl_rejection() is blind to it; writer-uniqueness is what
catches it. Any NEW file that writes INTO the daily_pnl table fails this test
until it routes through upsert_daily_pnl() (inheriting the value guard) or earns
a documented allowlist entry here.

Scope notes:
- Signature is the *write* form ``INTO daily_pnl`` (case-sensitive INSERT /
  INSERT OR REPLACE). Bare ``daily_pnl`` mentions -- SELECTs, the schema CREATE
  TABLE, column names, the ``daily_pnl_corrupt_archive`` table, ``pnl_snapshots``
  -- are not table writes and are intentionally not matched. The trailing word
  boundary keeps ``INTO daily_pnl_corrupt_archive`` (the recovery archive) from
  matching the live table.
- The tests tree is excluded: tests legitimately seed fixtures.
"""
import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent

# Match a write into the daily_pnl TABLE specifically -- "INTO daily_pnl" followed
# by a word boundary that is NOT "_", so "INTO daily_pnl_corrupt_archive" (the
# recovery archive table) does not count as a live-table write.
WRITE_RE = re.compile(r"INTO\s+daily_pnl(?![\w])")

# Sanctioned writers of the daily_pnl table. Paths are posix-relative to ENGINE_ROOT.
ALLOWLIST = {
    # THE runtime writer -- applies the value/plausibility guard before every write.
    "database/_mixins_pnl.py",
    # Offline manual recovery tool: archives corrupt rows then re-derives every row
    # from closed paper_trades round-trips. Not a runtime path; derives from the same
    # single source of truth, so it cannot introduce a mismatched-basis row.
    "scripts/rebuild_daily_pnl.py",
    # Offline manual reconciliation tool (dry-run by default; --apply is DB-backup
    # gated). Rebuilds daily_pnl from the closed paper_trades ledger using the same
    # absolute-anchoring formula as the live EOD writer, so it derives from the single
    # source of truth and cannot introduce a mismatched-basis row. Consumed by the
    # daily-pnl-reconcile drift detector.
    "scripts/repair_daily_pnl.py",
}

EXCLUDE_DIRS = ("tests", ".venv", "node_modules", ".git")


def _engine_py_files():
    for path in ENGINE_ROOT.rglob("*.py"):
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        if any(rel == d or rel.startswith(d + "/") for d in EXCLUDE_DIRS):
            continue
        yield path, rel


def test_upsert_daily_pnl_is_sole_writer():
    """No production file outside the allowlist may write to the daily_pnl table."""
    offenders = []
    for path, rel in _engine_py_files():
        if rel in ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if WRITE_RE.search(text):
            offenders.append(rel)
    assert not offenders, (
        "Direct write to the daily_pnl table outside upsert_daily_pnl(): "
        f"{sorted(offenders)}. Route daily_pnl writes through "
        "DatabaseManager.upsert_daily_pnl() so they inherit the value/plausibility "
        "guard -- or, if this is a deliberate sanctioned writer, add a documented "
        "ALLOWLIST entry in this test. (Root cause of the 2026-06 phantom-P&L "
        "incident: a second writer with a mismatched balance basis.)"
    )


def test_allowlist_is_current():
    """Guard against allowlist rot: every entry must exist and still write daily_pnl."""
    stale = []
    for rel in sorted(ALLOWLIST):
        path = ENGINE_ROOT / rel
        if not path.exists():
            stale.append(f"{rel} (file missing -- prune the entry)")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not WRITE_RE.search(text):
            stale.append(f"{rel} (no longer writes daily_pnl -- prune the entry)")
    assert not stale, f"Stale ALLOWLIST entries: {stale}"
