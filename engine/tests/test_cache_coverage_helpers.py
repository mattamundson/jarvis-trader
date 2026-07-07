"""Unit tests for the cache_coverage_manifest low-level helpers.

The existing test_cache_coverage_manifest.py covers build_coverage_manifest() at the
integration level; this file pins the filename-contract parser and the bar counter in
ISOLATION, because _parse_cache_name encodes the cache filename CONTRACT -- if its regex
drifts, every runner can silently select the wrong cache. Pure FS/string logic; no
trading path, no network.
"""

from __future__ import annotations

from datetime import date

import pytest

from backtest import cache_coverage_manifest as ccm

# --- _parse_cache_name (the filename contract) -----------------------------


def test_parse_cache_name_canonical():
    assert ccm._parse_cache_name("MES_2021-06-20_2026-06-21_1h.csv") == {
        "symbol": "MES",
        "start": "2021-06-20",
        "end": "2026-06-21",
        "interval": "1h",
    }


def test_parse_cache_name_two_char_symbol_and_15m_interval():
    # symbol regex is [A-Z][A-Z0-9]{1,3} (2-4 chars); interval is \d{1,2}[mhd].
    out = ccm._parse_cache_name("M2K_2024-01-01_2026-06-21_15m.csv")
    assert out is not None
    assert out["symbol"] == "M2K"
    assert out["interval"] == "15m"


@pytest.mark.parametrize(
    "bad",
    [
        "mes_2021-06-20_2026-06-21_1h.csv",  # lowercase symbol
        "M_2021-06-20_2026-06-21_1h.csv",  # symbol too short (needs >=2 chars)
        "MES_2021-6-20_2026-06-21_1h.csv",  # single-digit month
        "MES_2021-06-20_2026-06-21_1x.csv",  # bad interval unit
        "MES_2021-06-20_2026-06-21_100h.csv",  # 3-digit interval magnitude
        "MES_2021-06-20_2026-06-21_1h.txt",  # not .csv
        "MES_2021-06-20_1h.csv",  # missing a date field
        "garbage.csv",  # not a cache name at all
    ],
)
def test_parse_cache_name_rejects_off_contract(bad):
    assert ccm._parse_cache_name(bad) is None


# --- _count_bars -----------------------------------------------------------


def test_count_bars_subtracts_header(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("timestamp,open\n1,2\n3,4\n5,6\n", encoding="utf-8")
    assert ccm._count_bars(p) == 3  # 4 lines - header


def test_count_bars_header_only_is_zero(tmp_path):
    p = tmp_path / "h.csv"
    p.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")
    assert ccm._count_bars(p) == 0


def test_count_bars_empty_file_is_zero_not_negative(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    assert ccm._count_bars(p) == 0  # max(0, 0 - 1)


def test_count_bars_missing_file_returns_none(tmp_path):
    assert ccm._count_bars(tmp_path / "does_not_exist.csv") is None


# --- _iso_to_date ----------------------------------------------------------


def test_iso_to_date_parses_isoformat():
    assert ccm._iso_to_date("2026-06-21") == date(2026, 6, 21)


def test_iso_to_date_rejects_malformed():
    with pytest.raises(ValueError):
        ccm._iso_to_date("2026/06/21")
