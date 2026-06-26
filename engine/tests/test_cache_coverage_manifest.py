"""
Tests for backtest.cache_coverage_manifest -- the Phase-2 data-depth gauge.

Uses synthetic cache files in a tmp dir and an injected `now` so the
OK / SHALLOW / STALE / MISSING classification and the fragmentation surfacing
(a fresh-but-shallow cache shadowing a deeper older one) are deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backtest.cache_coverage_manifest import (
    DEFAULT_SHALLOW_FRACTION,
    build_coverage_manifest,
)
from backtest.export_ibkr_history import INTERVAL_DEPTH_DAYS

NOW = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
_HEADER = "timestamp,open,high,low,close,volume\n"


def _write_cache(d, name: str, n_rows: int = 3) -> None:
    body = "".join(
        f"2026-01-0{i % 9 + 1}T00:00:00Z,1,2,0,1,10\n" for i in range(n_rows)
    )
    (d / name).write_text(_HEADER + body, encoding="utf-8")


@pytest.fixture
def cache(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    # MES 1h: deep (~5y) + fresh (end 1d ago) -> OK
    _write_cache(d, "MES_2021-06-20_2026-06-21_1h.csv", n_rows=5)
    # MGC 1h: two caches -> engine selects the freshest end (the SHALLOW one),
    # while a deeper-start older cache also exists (fragmentation surfacing).
    _write_cache(d, "MGC_2025-12-04_2026-06-21_1h.csv", n_rows=4)   # span ~199d, fresh
    _write_cache(d, "MGC_2024-01-01_2026-06-20_1h.csv", n_rows=7)   # deeper, 1d older end
    # MES 1d: shallow (90d) + stale (end 10d ago) -> STALE+SHALLOW
    _write_cache(d, "MES_2026-03-14_2026-06-12_1d.csv", n_rows=2)
    # MNQ 1h present, MNQ 1d absent -> MNQ 1d MISSING (core interval forced)
    _write_cache(d, "MNQ_2024-01-01_2026-06-21_1h.csv", n_rows=3)
    # GC (legacy, NOT an export target) 1h: shallow + old, but no stale flag and
    # never in alerts because it is not an active symbol.
    _write_cache(d, "GC_2024-06-01_2026-03-27_1h.csv", n_rows=6)
    # Off-contract noise that must be ignored.
    _write_cache(d, "garbage.csv", n_rows=1)
    _write_cache(d, "MES_not_a_cache.csv", n_rows=1)
    return d


def _entry(manifest, symbol, interval):
    for e in manifest["entries"]:
        if e["symbol"] == symbol and e["interval"] == interval:
            return e
    raise AssertionError(f"no entry for {symbol} {interval}")


def test_deep_fresh_cache_is_ok(cache):
    m = build_coverage_manifest(cache, now=NOW)
    e = _entry(m, "MES", "1h")
    assert e["status"] == "OK", e
    assert e["flags"] == []
    assert e["target_days"] == INTERVAL_DEPTH_DAYS["1h"]
    assert e["coverage_pct"] >= 100.0 * DEFAULT_SHALLOW_FRACTION
    assert e["n_bars"] == 5  # 6 lines - header
    assert e["selected_file"] == "MES_2021-06-20_2026-06-21_1h.csv"


def test_shallow_fresh_cache_flagged_shallow(cache):
    m = build_coverage_manifest(cache, now=NOW)
    e = _entry(m, "MGC", "1h")
    assert e["status"] == "SHALLOW", e
    assert e["flags"] == ["shallow"]
    assert e["stale_days"] == 1  # end 2026-06-21 vs now 2026-06-22


def test_fragmentation_surfaced_via_earliest_start(cache):
    """Engine selects the freshest-end cache even when a deeper older one exists;
    the manifest surfaces the deeper start so the shadowing is visible."""
    m = build_coverage_manifest(cache, now=NOW)
    e = _entry(m, "MGC", "1h")
    assert e["n_caches"] == 2
    assert e["selected_file"] == "MGC_2025-12-04_2026-06-21_1h.csv"  # freshest end
    assert e["earliest_start_available"] == "2024-01-01"  # deeper start exists
    # selected span is far shallower than what the deeper cache could provide
    assert e["start"] == "2025-12-04"


def test_stale_and_shallow_daily(cache):
    m = build_coverage_manifest(cache, now=NOW)
    e = _entry(m, "MES", "1d")
    assert "stale" in e["flags"] and "shallow" in e["flags"]
    assert e["status"] == "STALE+SHALLOW"
    assert e["stale_days"] == 10


def test_missing_core_interval_for_active_symbol(cache):
    m = build_coverage_manifest(cache, now=NOW)
    e = _entry(m, "MNQ", "1d")
    assert e["status"] == "MISSING"
    assert e["n_caches"] == 0
    assert e["selected_file"] is None


def test_legacy_symbol_shallow_but_not_alerted(cache):
    m = build_coverage_manifest(cache, now=NOW)
    e = _entry(m, "GC", "1h")
    assert e["is_active"] is False
    assert "stale" not in e["flags"]  # staleness only flagged for active symbols
    # GC must never appear in alerts (alerts are active-symbol only).
    # Match the GC *symbol* via startswith -- "GC " is a substring of "MGC 1h".
    assert all(not a.startswith("GC ") for a in m["alerts"]), m["alerts"]


def test_alerts_cover_active_problems_only(cache):
    m = build_coverage_manifest(cache, now=NOW)
    joined = "\n".join(m["alerts"])
    assert "MGC 1h" in joined          # active + shallow
    assert "MNQ 1d" in joined          # active + missing
    assert "MES 1d" in joined          # active + stale+shallow
    assert "MES 1h" not in joined      # active + OK -> no alert
    # legacy GC never alerted -- match the symbol via per-alert startswith,
    # since "GC " is a substring of "MGC 1h".
    assert not any(a.startswith("GC ") for a in m["alerts"])


def test_off_contract_files_ignored(cache):
    m = build_coverage_manifest(cache, now=NOW)
    symbols = {e["symbol"] for e in m["entries"]}
    # 'garbage' / 'MES_not_a_cache' must not create phantom entries.
    assert "garbage" not in symbols
    # MES still only has real intervals (1h present, 1d present); no junk interval.
    mes_intervals = {e["interval"] for e in m["entries"] if e["symbol"] == "MES"}
    assert mes_intervals <= {"1h", "1d"}


def test_manifest_is_json_serialisable_and_summarised(cache):
    import json

    m = build_coverage_manifest(cache, now=NOW)
    json.dumps(m)  # must not raise
    assert m["summary"]["total"] == len(m["entries"])
    assert m["summary"]["missing"] >= 1
    assert m["generated_at"] == NOW.isoformat()


def test_missing_cache_dir_yields_all_missing(tmp_path):
    m = build_coverage_manifest(tmp_path / "does_not_exist", now=NOW)
    # All active symbols' core intervals appear as MISSING; nothing crashes.
    assert m["summary"]["total"] == m["summary"]["missing"] > 0
    assert all(e["status"] == "MISSING" for e in m["entries"])
