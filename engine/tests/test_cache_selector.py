"""Tests for engine/backtest/_gate_v2_helpers.py::_find_latest_cache.

Locks in the "glob <PREFIX>*<SUFFIX> and pick the file whose filename's
second date segment is the latest" contract that prevents the regression
fixed in 55739db (verdict-against-stale-data near-miss in MES rank11 +
MGC trend rank4 runners).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest._gate_v2_helpers import _find_latest_cache


def test_picks_latest_end_date(tmp_path):
    (tmp_path / "MES_2024-01-01_2026-03-28_1h.csv").write_text("a")
    (tmp_path / "MES_2024-01-01_2026-04-15_1h.csv").write_text("b")
    (tmp_path / "MES_2024-01-01_2026-05-07_1h.csv").write_text("c")
    chosen = _find_latest_cache(tmp_path, "MES")
    assert chosen.name == "MES_2024-01-01_2026-05-07_1h.csv"


def test_single_file(tmp_path):
    (tmp_path / "MGC_2024-01-01_2026-03-28_1h.csv").write_text("a")
    chosen = _find_latest_cache(tmp_path, "MGC")
    assert chosen.name == "MGC_2024-01-01_2026-03-28_1h.csv"


def test_no_files_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        _find_latest_cache(tmp_path, "MES")


def test_ignores_other_prefixes(tmp_path):
    (tmp_path / "MES_2024-01-01_2026-05-07_1h.csv").write_text("a")
    (tmp_path / "MGC_2024-01-01_2026-06-01_1h.csv").write_text("b")
    chosen = _find_latest_cache(tmp_path, "MES")
    assert chosen.name == "MES_2024-01-01_2026-05-07_1h.csv"
    # And the MGC call returns the MGC one — never sees the MES file.
    chosen_mgc = _find_latest_cache(tmp_path, "MGC")
    assert chosen_mgc.name == "MGC_2024-01-01_2026-06-01_1h.csv"


def test_ignores_other_suffixes(tmp_path):
    (tmp_path / "MES_2024-01-01_2026-05-07_1h.csv").write_text("a")
    (tmp_path / "MES_2024-01-01_2026-06-01_4h.csv").write_text("b")
    chosen = _find_latest_cache(tmp_path, "MES")
    # Default suffix _1h.csv must skip the _4h.csv even though it has a later end-date.
    assert chosen.name == "MES_2024-01-01_2026-05-07_1h.csv"


def test_handles_extra_underscores_in_name(tmp_path):
    # Filename still parses correctly when the full path has the canonical
    # PREFIX_START_END_INTERVAL.csv shape.
    (tmp_path / "MES_2024-01-01_2026-05-07_1h.csv").write_text("a")
    (tmp_path / "MES_2024-01-01_2026-04-15_1h.csv").write_text("b")
    chosen = _find_latest_cache(tmp_path, "MES")
    parts = chosen.stem.split("_")
    assert parts[2] == "2026-05-07"
    assert chosen.name == "MES_2024-01-01_2026-05-07_1h.csv"
