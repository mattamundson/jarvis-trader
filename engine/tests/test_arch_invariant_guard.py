"""The static arch-invariant guard must reuse the daily_pnl single-writer SSOT
and flag an un-allowlisted writer while passing a clean tree.

These tests are hermetic (they scan a synthetic tmp tree via the guard's
``engine_root`` override), so they do not couple to the live engine tree's
current allowlist state.
"""
import importlib.util
from pathlib import Path

GUARD_PATH = Path(__file__).resolve().parent.parent / "scripts" / "arch_invariant_guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("_arch_guard_under_test", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_guard_module_loads():
    g = _load_guard()
    assert hasattr(g, "find_daily_pnl_offenders")
    assert hasattr(g, "scan")


def test_flags_unallowlisted_daily_pnl_writer(tmp_path):
    g = _load_guard()
    (tmp_path / "rogue_writer.py").write_text(
        'conn.execute("INSERT OR REPLACE INTO daily_pnl (date) VALUES (?)", (d,))',
        encoding="utf-8",
    )
    offenders = g.find_daily_pnl_offenders(engine_root=tmp_path)
    assert "rogue_writer.py" in offenders


def test_clean_tree_has_no_offenders(tmp_path):
    g = _load_guard()
    # A read (SELECT ... FROM) is not a write INTO the table and must not trip.
    (tmp_path / "reader.py").write_text(
        'rows = conn.execute("SELECT date FROM daily_pnl").fetchall()',
        encoding="utf-8",
    )
    offenders = g.find_daily_pnl_offenders(engine_root=tmp_path)
    assert offenders == []


def test_corrupt_archive_write_is_not_flagged(tmp_path):
    g = _load_guard()
    # Writing the recovery archive table (daily_pnl_corrupt_archive) must NOT
    # match the live-table write regex -- the SSOT's word-boundary guarantees it.
    (tmp_path / "archiver.py").write_text(
        'conn.execute("INSERT INTO daily_pnl_corrupt_archive SELECT * FROM daily_pnl")',
        encoding="utf-8",
    )
    offenders = g.find_daily_pnl_offenders(engine_root=tmp_path)
    assert offenders == []
