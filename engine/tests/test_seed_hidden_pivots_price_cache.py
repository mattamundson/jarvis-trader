"""Tests for scripts.seed_hidden_pivots_price_cache (PRB-23).

Covers the script's pure logic: cache filename building (incl. the deliberate
GOOGL/5-char exception to CACHE_FILENAME_CONTRACT), freshness/staleness
detection against the `_end_date`-from-filename convention shared with
MarketDataManager._load_csv_cache, symbol selection (skip-fresh vs
needs-refresh vs force), and the fetch->normalize->write pipeline with an
injected fake fetcher (no network calls, matching test_free_daily_export.py's
pattern).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

# Make engine root importable when pytest runs from the engine directory
# (same convention as test_backfill_market_data_bars.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import seed_hidden_pivots_price_cache as seed


# ---------------------------------------------------------------- filenames
def test_cache_filename_shape():
    name = seed.cache_filename("NFLX", "2025-01-01", "2026-01-01")
    assert name == "NFLX_2025-01-01_2026-01-01_1d.csv"


def test_cache_filename_allows_5char_googl():
    # GOOGL is a real DEFAULT_WATCHLIST member and would be rejected by
    # export_ibkr_history.CACHE_FILENAME_CONTRACT's 2-4 char assertion --
    # this script deliberately doesn't use that contract. Must not raise.
    name = seed.cache_filename("googl", "2025-01-01", "2026-01-01")
    assert name == "GOOGL_2025-01-01_2026-01-01_1d.csv"


# ---------------------------------------------------------------- freshness
def test_latest_cache_end_date_none_when_no_files(tmp_path):
    assert seed.latest_cache_end_date("NFLX", tmp_path) is None


def test_latest_cache_end_date_parses_end_from_filename(tmp_path):
    (tmp_path / "NFLX_2025-01-01_2026-07-25_1d.csv").write_text("timestamp,close\n")
    assert seed.latest_cache_end_date("NFLX", tmp_path) == date(2026, 7, 25)


def test_latest_cache_end_date_picks_freshest_not_lexicographic_last(tmp_path):
    # An older-but-longer slice must not shadow a fresher, shorter one --
    # mirrors _load_csv_cache's own freshest-file-selection convention.
    (tmp_path / "NFLX_2020-01-01_2026-01-01_1d.csv").write_text("timestamp,close\n")
    (tmp_path / "NFLX_2026-07-20_2026-07-28_1d.csv").write_text("timestamp,close\n")
    assert seed.latest_cache_end_date("NFLX", tmp_path) == date(2026, 7, 28)


def test_latest_cache_end_date_ignores_other_symbols(tmp_path):
    (tmp_path / "SPY_2025-01-01_2026-07-25_1d.csv").write_text("timestamp,close\n")
    assert seed.latest_cache_end_date("NFLX", tmp_path) is None


def test_needs_refresh_true_when_no_cache(tmp_path):
    assert seed.needs_refresh("NFLX", tmp_path, today=date(2026, 7, 29)) is True


def test_needs_refresh_false_when_within_max_age(tmp_path):
    (tmp_path / "NFLX_2025-01-01_2026-07-27_1d.csv").write_text("timestamp,close\n")
    assert (
        seed.needs_refresh("NFLX", tmp_path, max_age_days=4, today=date(2026, 7, 29)) is False
    )


def test_needs_refresh_true_when_older_than_max_age(tmp_path):
    (tmp_path / "NFLX_2025-01-01_2026-07-01_1d.csv").write_text("timestamp,close\n")
    assert (
        seed.needs_refresh("NFLX", tmp_path, max_age_days=4, today=date(2026, 7, 29)) is True
    )


def test_needs_refresh_force_true_even_when_fresh(tmp_path):
    (tmp_path / "NFLX_2025-01-01_2026-07-29_1d.csv").write_text("timestamp,close\n")
    assert seed.needs_refresh("NFLX", tmp_path, today=date(2026, 7, 29), force=True) is True


def test_symbols_to_seed_filters_to_stale_and_missing_only(tmp_path):
    (tmp_path / "SPY_2025-01-01_2026-07-27_1d.csv").write_text("timestamp,close\n")  # fresh
    (tmp_path / "NFLX_2025-01-01_2026-01-01_1d.csv").write_text("timestamp,close\n")  # stale
    # AMD has no cache at all -> needs refresh
    out = seed.symbols_to_seed(
        ["SPY", "NFLX", "AMD"], tmp_path, max_age_days=4, today=date(2026, 7, 29)
    )
    assert out == ["NFLX", "AMD"]


def test_symbols_to_seed_preserves_input_order(tmp_path):
    out = seed.symbols_to_seed(
        ["AMD", "NFLX", "GOOGL"], tmp_path, max_age_days=4, today=date(2026, 7, 29)
    )
    assert out == ["AMD", "NFLX", "GOOGL"]


# --------------------------------------------------------- fetch/write pipeline
def _yf_frame():
    idx = pd.to_datetime(["2026-07-27", "2026-07-28", "2026-07-29"])
    df = pd.DataFrame(
        {
            ("Open", "NFLX"): [900.0, 905.0, 910.0],
            ("High", "NFLX"): [910.0, 915.0, 920.0],
            ("Low", "NFLX"): [895.0, 900.0, 905.0],
            ("Close", "NFLX"): [905.0, 910.0, 915.0],
            ("Volume", "NFLX"): [1_000_000, 1_100_000, 1_200_000],
        },
        index=idx,
    )
    df.index.name = "Date"
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def _fake_fetcher(df):
    return [("fake", lambda sym: df)]


def test_seed_symbol_writes_canonical_cache(tmp_path):
    res = seed.seed_symbol("NFLX", cache_dir=tmp_path, fetchers=_fake_fetcher(_yf_frame()))
    assert res["status"] == "OK"
    assert res["source"] == "fake"
    assert res["rows"] == 3
    assert res["file"] == "NFLX_2026-07-27_2026-07-29_1d.csv"
    written = tmp_path / res["file"]
    assert written.exists()
    back = pd.read_csv(written)
    assert list(back.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(back) == 3


def test_seed_symbol_dry_run_writes_nothing(tmp_path):
    res = seed.seed_symbol(
        "NFLX", cache_dir=tmp_path, dry_run=True, fetchers=_fake_fetcher(_yf_frame())
    )
    assert res["status"] == "OK"
    assert "path" not in res
    assert list(tmp_path.glob("*.csv")) == []


def test_seed_symbol_falls_back_to_second_source(tmp_path):
    def boom(sym):
        raise RuntimeError("primary down")

    fetchers = [("primary", boom), ("backup", lambda sym: _yf_frame())]
    res = seed.seed_symbol("NFLX", cache_dir=tmp_path, fetchers=fetchers)
    assert res["status"] == "OK"
    assert res["source"] == "backup"


def test_seed_symbol_no_data(tmp_path):
    fetchers = [("empty", lambda sym: pd.DataFrame())]
    res = seed.seed_symbol("XYZ", cache_dir=tmp_path, fetchers=fetchers)
    assert res["status"] == "NO_DATA"


def test_seed_symbol_googl_5char_writes_without_error(tmp_path):
    # Regression guard for the CACHE_FILENAME_CONTRACT deviation: a 5-char
    # symbol must not raise and must produce a glob-matchable file.
    res = seed.seed_symbol("GOOGL", cache_dir=tmp_path, fetchers=_fake_fetcher(_yf_frame()))
    assert res["status"] == "OK"
    assert res["file"].startswith("GOOGL_")
    assert (tmp_path / res["file"]).exists()


# --------------------------------------------------------- seed_watchlist (idempotency)
def test_seed_watchlist_skips_fresh_and_fetches_stale(tmp_path):
    (tmp_path / "SPY_2025-01-01_2026-07-27_1d.csv").write_text("timestamp,close\n")  # fresh

    results = seed.seed_watchlist(
        ["SPY", "NFLX"],
        cache_dir=tmp_path,
        max_age_days=4,
        today=date(2026, 7, 29),
        fetchers=_fake_fetcher(_yf_frame()),
    )
    by_symbol = {r["symbol"]: r for r in results}
    assert by_symbol["SPY"]["status"] == "SKIPPED_FRESH"
    assert by_symbol["NFLX"]["status"] == "OK"
    # SPY's fresh file must be untouched, not rewritten.
    assert list(tmp_path.glob("SPY_*_1d.csv")) == [tmp_path / "SPY_2025-01-01_2026-07-27_1d.csv"]


def test_seed_watchlist_idempotent_second_run_is_all_skips(tmp_path):
    fetchers = _fake_fetcher(_yf_frame())
    first = seed.seed_watchlist(
        ["NFLX"], cache_dir=tmp_path, today=date(2026, 7, 29), fetchers=fetchers
    )
    assert first[0]["status"] == "OK"

    # Re-running immediately after (same "today") must be a pure no-op --
    # the freshly-written file is within max_age_days, so no second write,
    # no duplicate file.
    second = seed.seed_watchlist(
        ["NFLX"], cache_dir=tmp_path, today=date(2026, 7, 29), fetchers=fetchers
    )
    assert second[0]["status"] == "SKIPPED_FRESH"
    assert len(list(tmp_path.glob("NFLX_*_1d.csv"))) == 1


def test_seed_watchlist_force_refetches_even_fresh(tmp_path):
    fetchers = _fake_fetcher(_yf_frame())
    seed.seed_watchlist(["NFLX"], cache_dir=tmp_path, today=date(2026, 7, 29), fetchers=fetchers)
    forced = seed.seed_watchlist(
        ["NFLX"], cache_dir=tmp_path, today=date(2026, 7, 29), force=True, fetchers=fetchers
    )
    assert forced[0]["status"] == "OK"


def test_seed_watchlist_dry_run_never_writes(tmp_path):
    results = seed.seed_watchlist(
        ["NFLX"],
        cache_dir=tmp_path,
        today=date(2026, 7, 29),
        dry_run=True,
        fetchers=_fake_fetcher(_yf_frame()),
    )
    assert results[0]["status"] == "OK"
    assert list(tmp_path.glob("*.csv")) == []


def test_needs_refresh_false_for_futures_symbol_even_with_no_cache_or_force(tmp_path):
    # MES/MNQ/MGC/MCL are hard-excluded: MES/MNQ/MCL 404 on yfinance and MGC
    # silently resolves to the WRONG instrument (Vanguard Mega Cap ETF, not
    # COMEX Micro Gold futures) -- confirmed live during PRB-23. Must stay
    # False regardless of missing cache or --force.
    assert seed.needs_refresh("MGC", tmp_path, today=date(2026, 7, 29)) is False
    assert seed.needs_refresh("MGC", tmp_path, today=date(2026, 7, 29), force=True) is False
    assert seed.needs_refresh("MES", tmp_path, today=date(2026, 7, 29), force=True) is False


def test_symbols_to_seed_excludes_futures(tmp_path):
    out = seed.symbols_to_seed(
        ["MES", "MNQ", "MGC", "MCL", "NFLX"], tmp_path, today=date(2026, 7, 29)
    )
    assert out == ["NFLX"]


def test_seed_watchlist_skips_futures_without_fetching(tmp_path):
    def boom(sym):
        raise AssertionError(f"must never fetch futures symbol {sym}")

    results = seed.seed_watchlist(
        ["MES", "MNQ", "MGC", "MCL"],
        cache_dir=tmp_path,
        today=date(2026, 7, 29),
        force=True,  # even --force must not touch futures symbols
        fetchers=[("boom", boom)],
    )
    assert {r["symbol"]: r["status"] for r in results} == {
        "MES": "SKIPPED_FUTURES_NOT_YFINANCE_SAFE",
        "MNQ": "SKIPPED_FUTURES_NOT_YFINANCE_SAFE",
        "MGC": "SKIPPED_FUTURES_NOT_YFINANCE_SAFE",
        "MCL": "SKIPPED_FUTURES_NOT_YFINANCE_SAFE",
    }
    assert list(tmp_path.glob("*.csv")) == []


def test_seed_watchlist_defaults_to_default_watchlist(tmp_path, monkeypatch):
    monkeypatch.setattr(seed, "_get_default_watchlist", lambda: ["MES", "NFLX"])
    results = seed.seed_watchlist(
        cache_dir=tmp_path,
        today=date(2026, 7, 29),
        fetchers=_fake_fetcher(_yf_frame()),
    )
    assert {r["symbol"] for r in results} == {"MES", "NFLX"}


# --------------------------------------------------------- get_price_covered_watchlist wiring
def test_seeded_symbol_is_recognized_by_router_coverage_check(tmp_path, monkeypatch):
    """End-to-end contract check: once this script writes a file, the PRB-21
    router helper that decides dashboard coverage must recognize it -- this
    is the whole point of PRB-23 (no further dashboard change needed)."""
    import routers.hidden_pivots_router as hp_router_module

    seed.seed_symbol("NFLX", cache_dir=tmp_path, fetchers=_fake_fetcher(_yf_frame()))

    monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path)
    monkeypatch.setattr(hp_router_module, "_get_watchlist", lambda: ["NFLX", "AMD"])
    assert hp_router_module.get_price_covered_watchlist() == ["NFLX"]
