"""
Tests for scripts/reconcile_paper_sources.py (MR-0.3).

Covers:
  - test_clean_when_all_jsonl_ids_present_in_sqlite
  - test_drift_reported_for_jsonl_only_trade_ids
  - test_jsonl_absent_is_trivially_clean
  - test_frozen_check_flags_mtime_after_cutover
  - test_frozen_check_passes_for_mtime_before_cutover
  - test_main_exit_code_matches_ok_flag
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import reconcile_paper_sources as rps  # noqa: E402


def _make_db(db_path: Path, trade_ids: list[str]) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE paper_trades (trade_id TEXT)")
    for tid in trade_ids:
        conn.execute("INSERT INTO paper_trades (trade_id) VALUES (?)", (tid,))
    conn.commit()
    conn.close()


def _make_jsonl(path: Path, trade_ids: list[str]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for tid in trade_ids:
            fh.write(json.dumps({"trade_id": tid}) + "\n")


def _set_mtime(path: Path, when: datetime) -> None:
    ts = when.timestamp()
    os.utime(str(path), (ts, ts))


@pytest.fixture
def patch_paths(tmp_path, monkeypatch):
    jsonl_path = tmp_path / "trades.jsonl"
    db_path = tmp_path / "jarvis_trader.db"
    monkeypatch.setattr(rps, "_JSONL_PATH", jsonl_path)
    monkeypatch.setattr(rps, "_DB_PATH", db_path)
    return jsonl_path, db_path


def test_clean_when_all_jsonl_ids_present_in_sqlite(patch_paths):
    jsonl_path, db_path = patch_paths
    _make_jsonl(jsonl_path, ["a", "b", "c"])
    _make_db(db_path, ["a", "b", "c", "d"])  # SQLite may have MORE (newer) rows
    _set_mtime(jsonl_path, rps._CUTOVER_UTC.replace(hour=0))

    result = rps.reconcile()

    assert result["ok"] is True
    assert result["divergent_count"] == 0
    assert result["jsonl_frozen"] is True


def test_drift_reported_for_jsonl_only_trade_ids(patch_paths):
    jsonl_path, db_path = patch_paths
    _make_jsonl(jsonl_path, ["a", "b", "orphan-1", "orphan-2"])
    _make_db(db_path, ["a", "b"])
    _set_mtime(jsonl_path, rps._CUTOVER_UTC.replace(hour=0))

    result = rps.reconcile()

    assert result["ok"] is False
    assert result["divergent_count"] == 2
    assert set(result["divergent_trade_ids"]) == {"orphan-1", "orphan-2"}


def test_jsonl_absent_is_trivially_clean(patch_paths):
    _jsonl_path, db_path = patch_paths
    _make_db(db_path, ["a"])
    # JSONL file never created.

    result = rps.reconcile()

    assert result["ok"] is True
    assert result["jsonl_trade_id_count"] == 0
    assert result["jsonl_frozen"] is True


def test_frozen_check_flags_mtime_after_cutover(patch_paths):
    jsonl_path, db_path = patch_paths
    _make_jsonl(jsonl_path, ["a"])
    _make_db(db_path, ["a"])
    _set_mtime(jsonl_path, rps._CUTOVER_UTC.replace(year=2027))  # written AFTER cutover

    result = rps.reconcile()

    assert result["ok"] is False
    assert result["jsonl_frozen"] is False
    assert "AFTER cutover" in result["jsonl_freeze_detail"]


def test_frozen_check_passes_for_mtime_before_cutover(patch_paths):
    jsonl_path, db_path = patch_paths
    _make_jsonl(jsonl_path, ["a"])
    _make_db(db_path, ["a"])
    _set_mtime(jsonl_path, rps._CUTOVER_UTC.replace(year=2025))

    is_frozen, detail = rps._check_jsonl_frozen(jsonl_path)

    assert is_frozen is True
    assert "predates cutover" in detail


def test_main_exit_code_matches_ok_flag(patch_paths, capsys):
    jsonl_path, db_path = patch_paths
    _make_jsonl(jsonl_path, ["a", "orphan"])
    _make_db(db_path, ["a"])
    _set_mtime(jsonl_path, rps._CUTOVER_UTC.replace(hour=0))

    exit_code = rps.main()

    assert exit_code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["divergent_count"] == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
