"""
Regression: backtest cache files must contain futures prices, not equity prices.

Background: 2026-04-16 incident. When Polygon.io was routing futures tickers
to same-named equities (``CL`` → Colgate-Palmolive, ``NQ`` → Nasdaq Inc., etc.),
any CSV generated via Polygon would contain stock prices labeled as futures.
The 2026-04-16 T1.5 audit scanned all 78 cached CSVs and found none matched an
equity-ticker price range, so prior backtest validation numbers stand.

This test re-runs that audit on every test invocation so a contaminated file
can't silently sneak back in (e.g. if someone re-enables Polygon partially
without updating the blocklist).

Location of the audit logic: ``scripts/audit_polygon_contamination.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = ENGINE_DIR / "backtest" / "cache"

# Make ``scripts`` importable when run from repo root
SCRIPTS_DIR = ENGINE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from audit_polygon_contamination import (  # noqa: E402
    FUTURES_PRICE_BAND,
    classify,
    read_closes,
)


def _write_csv(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestReadCloses:
    """Header/row parsing contract for read_closes.

    The column keys are resolved once from the header rather than per row (the
    cache holds 5m series with 100k+ rows each), so these pin the behaviour that
    the per-row scan used to provide: case-insensitive header matching, tolerance
    of non-numeric rows, and empty output when no close column exists.
    """

    def test_parses_standard_loader_header(self, tmp_path):
        p = _write_csv(
            tmp_path,
            "MES_1h.csv",
            "Date,Open,High,Low,Close,Volume\n"
            "2026-01-02,100,101,99,100.5,10\n"
            "2026-01-03,100.5,102,100,101.5,12\n",
        )
        closes, dates = read_closes(p)
        assert closes == [100.5, 101.5]
        assert dates == ["2026-01-02", "2026-01-03"]

    def test_header_matching_is_case_insensitive(self, tmp_path):
        p = _write_csv(
            tmp_path,
            "MES_1h.csv",
            "TIMESTAMP,open,high,low,CLOSE,volume\n2026-01-02,1,1,1,42.0,1\n",
        )
        closes, dates = read_closes(p)
        assert closes == [42.0]
        assert dates == ["2026-01-02"]

    def test_no_close_column_yields_empty(self, tmp_path):
        p = _write_csv(tmp_path, "MES_1h.csv", "Date,Open,High,Low,Volume\n2026-01-02,1,1,1,1\n")
        assert read_closes(p) == ([], [])

    def test_non_numeric_closes_are_skipped(self, tmp_path):
        p = _write_csv(
            tmp_path,
            "MES_1h.csv",
            "Date,Close\n2026-01-02,100.0\n2026-01-03,n/a\n2026-01-04,\n2026-01-05,102.0\n",
        )
        closes, dates = read_closes(p)
        assert closes == [100.0, 102.0]
        # A skipped close must not desync the parallel dates list.
        assert dates == ["2026-01-02", "2026-01-05"]

    def test_close_column_without_date_column(self, tmp_path):
        p = _write_csv(tmp_path, "MES_1h.csv", "Close\n100.0\n101.0\n")
        closes, dates = read_closes(p)
        assert closes == [100.0, 101.0]
        assert dates == []

    def test_empty_file_yields_empty(self, tmp_path):
        p = _write_csv(tmp_path, "MES_1h.csv", "")
        assert read_closes(p) == ([], [])


@pytest.mark.skipif(
    not CACHE_DIR.exists() or not any(CACHE_DIR.glob("*.csv")),
    reason="backtest/cache is empty or absent in this checkout",
)
# This test reads every bar of every cached CSV, so it scales with the cache and
# does not fit the 30s per-test budget in pyproject.toml that unit tests assume.
# The budget matters more than usual here: pytest-timeout's thread method cannot
# cancel one test, so blowing it kills the whole suite run rather than failing
# this test. It regressed exactly that way once the cache grew past ~160 files.
@pytest.mark.timeout(180)
def test_no_contaminated_cache_files():
    """Every cached CSV must have prices inside its futures/equity band."""
    csvs = sorted(CACHE_DIR.glob("*.csv"))
    results = [classify(p) for p in csvs]

    contaminated = [r for r in results if r["verdict"] == "CONTAMINATED"]
    suspect = [r for r in results if r["verdict"] == "SUSPECT"]
    unknown = [r for r in results if r["verdict"] == "UNKNOWN_SYMBOL"]

    # UNKNOWN_SYMBOL is a config gap (missing band), not data contamination.
    # Surface it as an informational failure so new cache symbols get a band.
    assert not unknown, (
        f"{len(unknown)} cache file(s) have no price band defined. "
        f"Add the symbol to FUTURES_PRICE_BAND in "
        f"scripts/audit_polygon_contamination.py. "
        f"First: {unknown[0]['path'].name} ({unknown[0]['reason']})"
    )

    assert not contaminated, (
        f"{len(contaminated)} cache file(s) have prices outside the futures "
        f"band — likely populated by the Polygon equity-ticker bug. "
        f"Move them out of backtest/cache/ and re-fetch via IBKR. "
        f"First few: {[r['path'].name for r in contaminated[:3]]}"
    )

    assert not suspect, (
        f"{len(suspect)} cache file(s) are SUSPECT (prices in band but "
        f"volatility implies equity, not futures). "
        f"First few: {[r['path'].name for r in suspect[:3]]}"
    )


def test_audit_covers_every_futures_symbol_in_code():
    """The audit's band map must cover every futures symbol the engine uses."""
    # Keep this in sync with POLYGON_FUTURES_BLOCKLIST in engine/data/market_data.py.
    expected_futures = {"MCL", "MNQ", "MES", "MGC", "M2K", "MYM",
                        "CL", "NQ", "ES", "GC", "RTY", "YM",
                        "SI", "ZB", "ZN"}
    missing = expected_futures - FUTURES_PRICE_BAND.keys()
    assert not missing, (
        f"FUTURES_PRICE_BAND missing bands for {sorted(missing)}. "
        f"Add them to scripts/audit_polygon_contamination.py."
    )
