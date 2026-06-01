"""
Regression test for the 2026-04-16 Polygon-futures data contamination incident.

Background: Polygon's `CL` ticker is Colgate-Palmolive Company common stock,
not crude oil futures. Polygon's free plan does not include futures data at all.
Querying Polygon for any standard or micro futures symbol returns the wrong
asset (or empty). To prevent silent stock-vs-futures data substitution in the
trading pipeline, the futures-Polygon path is explicitly disabled.

These tests enforce that invariant. If they fail, the incident is regressing.
See `docs/data-source-audit-2026-04-16.md`.
"""

from __future__ import annotations

import pytest

from data.market_data import (
    POLYGON_FUTURES_BLOCKLIST,
    POLYGON_FUTURES_MAP,
)

# Symbols the trading pipeline actively uses (must always be blocked).
KNOWN_FUTURES = ["MCL", "MNQ", "MES", "MGC", "CL", "NQ", "ES", "GC"]


class TestPolygonFuturesBlocklist:
    """Invariant: Polygon must never be queried for futures symbols."""

    def test_blocklist_covers_all_known_micro_futures(self):
        for sym in ("MCL", "MNQ", "MES", "MGC", "M2K", "MYM"):
            assert sym in POLYGON_FUTURES_BLOCKLIST, (
                f"{sym} missing from POLYGON_FUTURES_BLOCKLIST. "
                "Polygon's free plan does not carry futures — must be blocked."
            )

    def test_blocklist_covers_all_known_standard_futures(self):
        for sym in ("CL", "NQ", "ES", "GC", "RTY", "YM", "SI", "ZB", "ZN"):
            assert sym in POLYGON_FUTURES_BLOCKLIST, (
                f"{sym} missing from POLYGON_FUTURES_BLOCKLIST. "
                "Bare standard-futures tickers on Polygon return the wrong asset "
                "(e.g. CL = Colgate-Palmolive stock)."
            )

    def test_polygon_futures_map_is_empty(self):
        # The map must stay empty until a paid Polygon plan is provisioned
        # AND the correct ticker format is verified (e.g. I:CL, C:CLF26).
        assert POLYGON_FUTURES_MAP == {}, (
            "POLYGON_FUTURES_MAP has entries — the 2026-04-16 incident may be "
            "regressing. Re-enabling requires verifying each symbol returns the "
            "correct underlying. See docs/data-source-audit-2026-04-16.md."
        )

    @pytest.mark.parametrize("symbol", KNOWN_FUTURES)
    def test_blocklist_membership_is_case_insensitive_via_caller(self, symbol):
        # Callers use `symbol.upper() in POLYGON_FUTURES_BLOCKLIST`, so the
        # blocklist itself only needs uppercase entries. Verify the convention.
        assert symbol.upper() in POLYGON_FUTURES_BLOCKLIST


class TestBacktestDataLoaderRespectsBlocklist:
    """The backtest path (separate FUTURES_MAP) must also honor the blocklist."""

    def test_backtest_loader_skips_futures(self, tmp_path, monkeypatch):
        from backtest.data_loader import BacktestDataLoader

        # Point cache to an empty temp dir so a stale on-disk cache can't
        # hide a real Polygon call (cache hit path returns cached data without
        # touching FUTURES_MAP). Forcing a miss exercises the blocklist guard.
        monkeypatch.setattr("backtest.data_loader.CACHE_DIR", tmp_path)

        loader = BacktestDataLoader()
        # Loading a known-futures symbol must return None (skipped), never a
        # DataFrame from the wrong asset. This catches the case where someone
        # adds a new futures symbol to FUTURES_MAP but forgets the blocklist.
        result = loader.load("MCL", "2026-01-01", "2026-01-15", "1d")
        assert result is None, (
            "BacktestDataLoader returned non-None for MCL — Polygon-futures "
            "path is active again. This is the 2026-04-16 incident regressing."
        )
