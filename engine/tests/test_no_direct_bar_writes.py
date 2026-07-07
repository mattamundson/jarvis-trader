"""Architecture regression: save_bars() is the SOLE production writer of market_data_bars.

Root cause of the 2026-03..06 data-poisoning incident: a code path wrote bars
straight into the ``market_data_bars`` table, bypassing ``save_bars()`` in
``engine/data/bars_repository.py`` and, with it, the write-time bar-quality /
sanity gate. 2,655 poisoned rows (O=H=L=C=100.5 IB snapshot sentinels,
impossible single-bar jumps) sat undetected for ~3 months -- found only by
refusing to believe a PF of 22 -- because *nothing enforced the single-writer
invariant*. The quarantine cleaned the past; this test stops it recurring.

The invariant: every write to ``market_data_bars`` flows through ``save_bars()``,
which applies the sanity gate. Any NEW file under ``engine/`` (outside the tests
tree) that writes ``INTO market_data_bars`` directly fails this test until it
either routes through ``save_bars()`` or earns a documented allowlist entry here.

Scope notes:
- The signature is the *write* form ``INTO market_data_bars`` (INSERT / INSERT OR
  IGNORE / REPLACE). A bare ``market_data_bars`` mention -- a SELECT, a
  ``CREATE TABLE``, an index, a docstring -- is reading/DDL, not a row write, and
  is intentionally NOT matched.
- The tests tree is excluded: tests legitimately seed fixtures/golden DBs and are
  not production writers.
"""
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent

# The write signature (case-sensitive on purpose -- the lowercase docstring
# "persist into market_data_bars" in backfill_market_data_bars.py is prose, not a
# SQL write, and must not match).
WRITE_LITERAL = "INTO market_data_bars"

# Only the sanctioned single writer may write bars directly. Everything else must
# call save_bars() (engine/data/bars_repository.py), which applies the write-time
# bar-quality / sanity gate. Paths are posix-relative to ENGINE_ROOT.
ALLOWLIST = {
    "data/bars_repository.py",  # save_bars() -- THE sanctioned writer + sanity gate
}

# Directories that are not production code (own fixtures / golden DBs).
EXCLUDE_DIRS = ("tests",)


def _engine_py_files():
    for path in ENGINE_ROOT.rglob("*.py"):
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        if any(rel == d or rel.startswith(d + "/") for d in EXCLUDE_DIRS):
            continue
        yield path, rel


def test_save_bars_is_sole_bar_writer():
    """No production file outside the allowlist may write directly to market_data_bars."""
    offenders = []
    for path, rel in _engine_py_files():
        if rel in ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if WRITE_LITERAL in text:
            offenders.append(rel)
    assert not offenders, (
        "Direct write to market_data_bars outside save_bars(): "
        f"{sorted(offenders)}. Route bar writes through save_bars() "
        "(engine/data/bars_repository.py) so they inherit the write-time "
        "bar-quality/sanity gate -- or, if this is a deliberate sanctioned "
        "writer, add a documented ALLOWLIST entry in this test. (Root cause of "
        "the 2,655-row poisoning incident: a writer that bypassed the gate.)"
    )


def test_allowlist_is_current():
    """Guard against allowlist rot: every entry must exist and still write bars."""
    stale = []
    for rel in sorted(ALLOWLIST):
        path = ENGINE_ROOT / rel
        if not path.exists():
            stale.append(f"{rel} (file missing -- prune the entry)")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if WRITE_LITERAL not in text:
            stale.append(f"{rel} (no longer writes market_data_bars -- prune the entry)")
    assert not stale, f"Stale ALLOWLIST entries: {stale}"
