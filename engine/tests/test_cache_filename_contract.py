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
    assert CACHE_FILENAME_CONTRACT.match(filename), f"Expected {filename!r} to match the contract"


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
    assert not CACHE_FILENAME_CONTRACT.match(
        filename
    ), f"{filename!r} should be rejected ({reason})"


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


# --------------------------------------------------------------------------- #
# Graceful degradation — contract regex edge cases                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "filename,reason",
    [
        # Invalid interval character — 'm' not in [hd]
        ("MES_2024-01-01_2026-05-07_1m.csv", "interval suffix 'm' not in [hd]"),
        # Symbol starts with lowercase
        ("mes_2024-01-01_2026-05-07_1h.csv", "non-uppercase first char"),
        # Symbol too long (5+ chars)
        ("MESXX_2024-01-01_2026-05-07_1h.csv", "symbol 5 chars exceeds max 4"),
        # Missing end-date (only one date segment)
        ("MES_2024-01-01__1h.csv", "empty end-date segment (double underscore)"),
        # End-date missing entirely but interval present
        ("MES_2024-01-01_1h.csv", "only one date — no end-date"),
        # Non-ISO date format in end position
        ("MES_2024-01-01_20260507_1h.csv", "non-ISO end-date (no hyphens)"),
        # Interval contains letters other than h/d
        ("MES_2024-01-01_2026-05-07_1x.csv", "unknown interval letter 'x'"),
        # Interval with three digits — \d{1,2} allows only 1 or 2 digits
        ("MES_2024-01-01_2026-05-07_100h.csv", "three-digit interval exceeds \\d{1,2} max"),
    ],
)
def test_contract_regex_rejects_degenerate_shapes(filename: str, reason: str) -> None:
    """Contract regex must reject edge-case malformed filenames without raising."""
    result = CACHE_FILENAME_CONTRACT.match(filename)
    assert result is None, f"{filename!r} should be rejected ({reason})"


@pytest.mark.parametrize(
    "filename,reason",
    [
        # Future-dated end-date — contract is purely structural, no date-range check
        ("MES_2024-01-01_2099-12-31_1h.csv", "future end-date is structurally valid"),
        # Multi-digit interval (e.g. 12h, 4h)
        ("MES_2024-01-01_2026-05-07_4h.csv", "4h is valid"),
        ("MES_2024-01-01_2026-05-07_12h.csv", "12h is valid (two-digit)"),
        # Symbol exactly 4 chars (upper bound)
        ("M2KX_2024-01-01_2026-05-07_1h.csv", "4-char symbol is at the boundary"),
        # Symbol exactly 2 chars (lower bound — A + one more)
        ("ES_2024-01-01_2026-05-07_1d.csv", "2-char symbol is at the lower boundary"),
    ],
)
def test_contract_regex_accepts_valid_edge_cases(filename: str, reason: str) -> None:
    """Contract regex must accept valid-but-unusual filenames."""
    assert CACHE_FILENAME_CONTRACT.match(filename), f"{filename!r} should be accepted ({reason})"


# --------------------------------------------------------------------------- #
# Graceful degradation — _find_latest_cache behaviour                         #
# --------------------------------------------------------------------------- #


def test_find_latest_cache_raises_not_crashes_on_empty_dir(tmp_path: Path) -> None:
    """Empty directory raises FileNotFoundError, not an uncaught exception."""
    with pytest.raises(FileNotFoundError):
        _find_latest_cache(tmp_path, "MES")


def test_find_latest_cache_malformed_filename_does_not_crash(tmp_path: Path) -> None:
    """A malformed filename (no valid end-date) mixed with a conforming one
    must not cause an exception — the conforming file should win."""
    conforming = tmp_path / "MES_2024-01-01_2026-05-07_1h.csv"
    malformed = tmp_path / "MES_invalid.csv"
    conforming.write_text("ts\n", encoding="utf-8")
    malformed.write_text("ts\n", encoding="utf-8")

    # Should not raise; conforming wins because malformed sorts to ""
    result = _find_latest_cache(tmp_path, "MES")
    assert result == conforming


def test_find_latest_cache_missing_date_component_does_not_crash(tmp_path: Path) -> None:
    """Filename with an empty end-date segment (like MES_2024-01-01__1h.csv)
    must not raise an unhandled exception — conforming sibling should win."""
    conforming = tmp_path / "MES_2024-01-01_2026-05-07_1h.csv"
    broken = tmp_path / "MES_2024-01-01__1h.csv"
    conforming.write_text("ts\n", encoding="utf-8")
    broken.write_text("ts\n", encoding="utf-8")

    result = _find_latest_cache(tmp_path, "MES")
    assert result == conforming


def test_find_latest_cache_invalid_interval_suffix_only_file_raises(tmp_path: Path) -> None:
    """A file with an invalid interval (e.g. _1m.csv) won't match the suffix
    filter for _1h.csv and will trigger FileNotFoundError."""
    invalid_interval = tmp_path / "MES_2024-01-01_2026-05-07_1m.csv"
    invalid_interval.write_text("ts\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        _find_latest_cache(tmp_path, "MES", suffix="_1h.csv")


def test_find_latest_cache_future_dated_file_selected(tmp_path: Path) -> None:
    """A future-dated end-date file is structurally valid and should be
    selected if it is the latest (lex max on end-date)."""
    past = tmp_path / "MES_2024-01-01_2026-05-07_1h.csv"
    future_dated = tmp_path / "MES_2024-01-01_2099-12-31_1h.csv"
    past.write_text("ts\n", encoding="utf-8")
    future_dated.write_text("ts\n", encoding="utf-8")

    result = _find_latest_cache(tmp_path, "MES")
    assert result == future_dated


def test_find_latest_cache_multiple_matches_picks_max_end_date_deterministically(
    tmp_path: Path,
) -> None:
    """With N conforming files, the one with the lexicographically greatest
    end-date segment is always selected, regardless of filesystem ordering."""
    files = [
        tmp_path / "MES_2024-01-01_2025-01-01_1h.csv",
        tmp_path / "MES_2024-01-01_2026-03-28_1h.csv",
        tmp_path / "MES_2024-01-01_2026-05-07_1h.csv",  # latest
        tmp_path / "MES_2024-01-01_2025-06-15_1h.csv",
    ]
    for f in files:
        f.write_text("ts\n", encoding="utf-8")

    expected = tmp_path / "MES_2024-01-01_2026-05-07_1h.csv"
    # Run multiple times to confirm determinism (max is stable)
    for _ in range(3):
        assert _find_latest_cache(tmp_path, "MES") == expected


def test_find_latest_cache_only_off_contract_files_returns_off_contract(tmp_path: Path) -> None:
    """When NO conforming file exists, the helper falls back to the lex-max
    of whatever is there (off-contract beats nothing). This tests the
    documented fallback behavior rather than asserting None."""
    only_file = tmp_path / "MES_legacy_1h.csv"
    only_file.write_text("ts\n", encoding="utf-8")

    # The helper does NOT return None — it returns the only candidate
    result = _find_latest_cache(tmp_path, "MES")
    assert result == only_file


def test_find_latest_cache_symbol_too_long_not_in_glob(tmp_path: Path) -> None:
    """A file with a 5-char symbol prefix won't match prefix='MES' glob,
    so it is correctly invisible to the selector for MES."""
    wrong_symbol = tmp_path / "MESXX_2024-01-01_2026-05-07_1h.csv"
    right_symbol = tmp_path / "MES_2024-01-01_2026-05-07_1h.csv"
    wrong_symbol.write_text("ts\n", encoding="utf-8")
    right_symbol.write_text("ts\n", encoding="utf-8")

    # Only the exact-prefix match should be returned
    result = _find_latest_cache(tmp_path, "MES")
    assert result == right_symbol
