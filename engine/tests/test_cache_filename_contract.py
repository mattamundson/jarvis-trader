"""Lock in the cache filename contract used by export_ibkr_history + _find_latest_cache.

The selector ``engine/backtest/_gate_v2_helpers.py::_find_latest_cache``
splits filenames on ``_`` and uses ``parts[2]`` (the end-date) as a
lex-sort key. If the export step ever drifts from
``<SYMBOL>_<YYYY-MM-DD>_<YYYY-MM-DD>_<INTERVAL>.csv`` (e.g. by adding a
contract-month suffix or switching date format), the selector silently
picks the wrong file.

These tests exercise both ends of the contract:

* :data:`engine.backtest.export_ibkr_history.CACHE_FILENAME_CONTRACT`
  matches valid shapes and rejects invalid ones.
* :func:`engine.backtest._gate_v2_helpers._find_latest_cache` continues to
  prefer the latest-end-date conforming file even when off-contract files
  share the directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make engine/ importable when pytest is invoked from the repo root.
ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from backtest._gate_v2_helpers import _find_latest_cache  # noqa: E402
from backtest.export_ibkr_history import CACHE_FILENAME_CONTRACT  # noqa: E402


# --------------------------------------------------------------------------- #
# Contract regex tests                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "filename",
    [
        "MES_2024-01-01_2026-05-07_1h.csv",
        "MGC_2024-04-26_2026-05-07_1h.csv",
        "MNQ_2024-06-01_2026-03-27_4h.csv",
        "MCL_2023-12-31_2026-01-01_1d.csv",
        "M2K_2024-01-01_2026-05-07_1h.csv",  # symbol with embedded digit
    ],
)
def test_valid_filenames_match_contract(filename: str) -> None:
    assert CACHE_FILENAME_CONTRACT.match(filename), (
        f"Expected {filename!r} to match the contract"
    )


@pytest.mark.parametrize(
    "filename,reason",
    [
        ("MES_2024-01-01_1h.csv", "missing end-date segment"),
        ("MES_20240101_2026-05-07_1h.csv", "non-ISO date format"),
        ("MES_2024-01-01_2026-05-07_1h_dec.csv", "contract-month suffix drift"),
        ("mes_2024-01-01_2026-05-07_1h.csv", "lowercase symbol"),
        ("MES_2024-01-01_2026-05-07_60m.csv", "non-h/d interval suffix"),
        ("MES_2024-01-01_2026-05-07.csv", "missing interval"),
        ("MES-2024-01-01-2026-05-07-1h.csv", "wrong separator"),
        ("MES_2024-01-01_2026-05-07_1h.parquet", "wrong extension"),
        ("TOOLONGSYM_2024-01-01_2026-05-07_1h.csv", "symbol >4 chars"),
    ],
)
def test_invalid_filenames_rejected_by_contract(filename: str, reason: str) -> None:
    assert not CACHE_FILENAME_CONTRACT.match(filename), (
        f"{filename!r} should be rejected ({reason})"
    )


# --------------------------------------------------------------------------- #
# _find_latest_cache integration                                              #
# --------------------------------------------------------------------------- #


def test_find_latest_cache_picks_latest_end_date(tmp_path: Path) -> None:
    older = tmp_path / "MES_2024-01-01_2026-03-28_1h.csv"
    newer = tmp_path / "MES_2024-01-01_2026-05-07_1h.csv"
    older.write_text("ts,o,h,l,c,v\n", encoding="utf-8")
    newer.write_text("ts,o,h,l,c,v\n", encoding="utf-8")

    found = _find_latest_cache(tmp_path, "MES")
    assert found == newer


def test_find_latest_cache_off_contract_loses_to_conforming(tmp_path: Path) -> None:
    """Off-contract files sort to the bottom; conforming siblings always win."""
    conforming = tmp_path / "MES_2024-01-01_2026-03-28_1h.csv"
    off_contract = tmp_path / "MES_legacy_1h.csv"  # only 2 underscore parts
    conforming.write_text("ts\n", encoding="utf-8")
    off_contract.write_text("ts\n", encoding="utf-8")

    found = _find_latest_cache(tmp_path, "MES")
    assert found == conforming


def test_find_latest_cache_raises_when_no_match(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _find_latest_cache(tmp_path, "MES")


def test_find_latest_cache_respects_suffix_filter(tmp_path: Path) -> None:
    hourly = tmp_path / "MES_2024-01-01_2026-05-07_1h.csv"
    daily = tmp_path / "MES_2024-01-01_2026-05-07_1d.csv"
    hourly.write_text("ts\n", encoding="utf-8")
    daily.write_text("ts\n", encoding="utf-8")

    assert _find_latest_cache(tmp_path, "MES", suffix="_1h.csv") == hourly
    assert _find_latest_cache(tmp_path, "MES", suffix="_1d.csv") == daily
