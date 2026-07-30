"""Integration tests for GET/POST hidden-pivots endpoints.

Uses FastAPI TestClient with a mocked data_manager so no network calls are made.
Auth is handled by main.py middleware, not the router — standalone tests skip auth checks.
"""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.hidden_pivots_router import inject_dependencies
from routers.hidden_pivots_router import router as hp_router

# ─── Fake data helpers ───────────────────────────────────────────────────────


def _fake_bars(n: int = 150) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = 100.0 + np.cumsum(rng.normal(0.1, 0.5, n))
    close = np.clip(close, 1.0, None)
    spread = np.abs(rng.normal(0.4, 0.1, n))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": rng.integers(500, 5000, n).astype(float),
        },
        index=dates,
    )


# ─── App fixture with injected mocks ─────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    mock_data_manager = MagicMock()
    mock_data_manager.get_bars = AsyncMock(return_value=_fake_bars())

    mock_config = MagicMock()
    mock_config.SCAN_SYMBOLS = ["MCL", "MNQ"]

    inject_dependencies(mock_data_manager, mock_config)

    app = FastAPI()
    app.include_router(hp_router)
    return TestClient(app)


# ─── /hidden-pivots/analyze/{symbol} ─────────────────────────────────────────


class TestAnalyzeEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/hidden-pivots/analyze/MCL")
        assert resp.status_code == 200

    def test_response_has_bias(self, client):
        resp = client.get("/hidden-pivots/analyze/MCL")
        data = resp.json()
        assert "bias" in data
        assert data["bias"] in ("LONG", "SHORT", "WATCH", "SOH")

    def test_response_has_confidence(self, client):
        resp = client.get("/hidden-pivots/analyze/MCL")
        data = resp.json()
        assert "confidence" in data
        assert 0.0 <= data["confidence"] <= 1.0

    def test_response_has_ema_alignment(self, client):
        resp = client.get("/hidden-pivots/analyze/MCL")
        data = resp.json()
        assert data["ema_alignment"] in ("BULLISH_FAN", "BEARISH_FAN", "COMPRESSED", "MIXED")

    def test_response_has_oscillator_state(self, client):
        resp = client.get("/hidden-pivots/analyze/MCL")
        data = resp.json()
        assert data["oscillator_state"] in (
            "BULLISH_CROSS",
            "BEARISH_CROSS",
            "RISING",
            "FALLING",
            "FLAT",
        )


# ─── /hidden-pivots/levels/{symbol} ──────────────────────────────────────────


class TestLevelsEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/hidden-pivots/levels/MCL")
        assert resp.status_code == 200

    def test_response_has_symbol(self, client):
        resp = client.get("/hidden-pivots/levels/MCL")
        data = resp.json()
        assert data.get("symbol") == "MCL"

    def test_response_has_level_structure(self, client):
        resp = client.get("/hidden-pivots/levels/MCL")
        data = resp.json()
        # Should have hp_ou_level and level_ladder
        assert any(k in data for k in ("hp_ou_level", "level_ladder", "levels", "hp_levels"))


# ─── /hidden-pivots/scan ─────────────────────────────────────────────────────


class TestScanEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/hidden-pivots/scan")
        assert resp.status_code == 200

    def test_response_has_scan_time(self, client):
        resp = client.get("/hidden-pivots/scan")
        data = resp.json()
        assert "scan_time" in data

    def test_response_has_symbols_scanned(self, client):
        resp = client.get("/hidden-pivots/scan")
        data = resp.json()
        assert "symbols_scanned" in data
        assert isinstance(data["symbols_scanned"], int)

    def test_response_has_signals_list(self, client):
        resp = client.get("/hidden-pivots/scan")
        data = resp.json()
        assert "signals" in data
        assert isinstance(data["signals"], list)

    def test_response_has_details_for_every_scanned_symbol(self, client):
        # details carries the full per-symbol result (incl. WATCH/SOH) so UIs
        # can render ladders for non-armed setups.
        resp = client.get("/hidden-pivots/scan")
        data = resp.json()
        assert "details" in data
        assert isinstance(data["details"], list)
        # mock config scans MCL+MNQ; both resolve to a signal -> 2 details
        assert len(data["details"]) == data["symbols_scanned"]
        if data["details"]:
            assert "bias" in data["details"][0]
            assert "bars_since_cross" in data["details"][0]


# ─── /hidden-pivots/report ───────────────────────────────────────────────────


class TestReportEndpoint:
    def test_returns_200(self, client):
        # After /scan runs, cache is populated — report should return 200
        resp = client.get("/hidden-pivots/report")
        assert resp.status_code == 200

    def test_response_has_scan_time_if_populated(self, client):
        resp = client.get("/hidden-pivots/report")
        if resp.json() is not None:
            assert "scan_time" in resp.json()


# ─── /hidden-pivots/screen (POST) ────────────────────────────────────────────


class TestScreenEndpoint:
    def test_returns_200_with_valid_payload(self, client):
        payload = {"symbols": ["MCL", "MNQ"], "timeframe": "1d", "benchmark": "SPY"}
        resp = client.post("/hidden-pivots/screen", json=payload)
        assert resp.status_code == 200

    def test_response_has_signals_list(self, client):
        payload = {"symbols": ["MCL"], "timeframe": "1d", "benchmark": "SPY"}
        resp = client.post("/hidden-pivots/screen", json=payload)
        data = resp.json()
        assert "signals" in data

    def test_empty_symbols_returns_400_or_200_empty(self, client):
        payload = {"symbols": [], "timeframe": "1d", "benchmark": "SPY"}
        resp = client.post("/hidden-pivots/screen", json=payload)
        assert resp.status_code in (200, 400, 422)

    def test_symbols_scanned_matches_input(self, client):
        payload = {"symbols": ["MCL", "MNQ"], "timeframe": "1d", "benchmark": "SPY"}
        resp = client.post("/hidden-pivots/screen", json=payload)
        data = resp.json()
        assert data["symbols_scanned"] == 2


# ─── /hidden-pivots/confluence/{symbol} ──────────────────────────────────────


class TestConfluenceEndpoint:
    def test_returns_200_or_service_error(self, client):
        # May return 503 if internal pipeline endpoint unreachable
        resp = client.get("/hidden-pivots/confluence/MCL")
        assert resp.status_code in (200, 500, 503, 504)

    def test_verdict_is_valid_when_200(self, client):
        resp = client.get("/hidden-pivots/confluence/MCL")
        if resp.status_code == 200:
            data = resp.json()
            assert "verdict" in data
            assert data["verdict"] in (
                "HIGH_CONVICTION",
                "WEAK",
                "DIVERGENT",
                "HP_ONLY",
                "NO_SIGNAL",
            )


# ─── PRB-21: price-coverage floor ─────────────────────────────────────────────
# Hidden Pivots dashboard shows "--" with certainty for watchlist symbols with
# no CSV backtest-cache floor once IBKR is down and Polygon's 4-calls/60s rate
# limit is exhausted. _has_csv_price_floor / get_price_covered_watchlist /
# GET /price-coverage let the dashboard cap its live-price poll to the
# symbols that actually have a floor, without touching /scan (which must
# still cover the full watchlist regardless of price-cache state).

import routers.hidden_pivots_router as hp_router_module


class TestHasCsvPriceFloor:
    def test_true_when_matching_1d_cache_file_exists(self, tmp_path, monkeypatch):
        (tmp_path / "AAPL_2025-01-01_2026-01-01_1d.csv").write_text("timestamp,close\n")
        monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path)
        assert hp_router_module._has_csv_price_floor("AAPL") is True

    def test_false_when_symbol_only_has_a_non_1d_cache_file(self, tmp_path, monkeypatch):
        # e.g. MCL has 1h/5m backtest slices but the price floor specifically
        # needs a 1d file — see get_current_price's Tier 5 (_load_csv_cache
        # is called with timeframe="1d").
        (tmp_path / "AAPL_2025-01-01_2026-01-01_1h.csv").write_text("timestamp,close\n")
        monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path)
        assert hp_router_module._has_csv_price_floor("AAPL") is False

    def test_false_when_only_a_different_symbol_is_cached(self, tmp_path, monkeypatch):
        (tmp_path / "SPY_2025-01-01_2026-01-01_1d.csv").write_text("timestamp,close\n")
        monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path)
        assert hp_router_module._has_csv_price_floor("AAPL") is False

    def test_case_insensitive(self, tmp_path, monkeypatch):
        (tmp_path / "AAPL_2025-01-01_2026-01-01_1d.csv").write_text("timestamp,close\n")
        monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path)
        assert hp_router_module._has_csv_price_floor("aapl") is True

    def test_false_when_cache_dir_does_not_exist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path / "does-not-exist")
        assert hp_router_module._has_csv_price_floor("AAPL") is False


class TestGetPriceCoveredWatchlist:
    def test_filters_watchlist_to_symbols_with_a_cache_floor(self, tmp_path, monkeypatch):
        (tmp_path / "MCL_2025-01-01_2026-01-01_1d.csv").write_text("timestamp,close\n")
        monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path)
        monkeypatch.setattr(hp_router_module, "_get_watchlist", lambda: ["MCL", "NFLX"])
        assert hp_router_module.get_price_covered_watchlist() == ["MCL"]

    def test_empty_when_nothing_in_the_watchlist_is_cached(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path)
        monkeypatch.setattr(hp_router_module, "_get_watchlist", lambda: ["NFLX", "MSFT"])
        assert hp_router_module.get_price_covered_watchlist() == []

    def test_preserves_watchlist_order(self, tmp_path, monkeypatch):
        (tmp_path / "SPY_2025-01-01_2026-01-01_1d.csv").write_text("timestamp,close\n")
        (tmp_path / "MCL_2025-01-01_2026-01-01_1d.csv").write_text("timestamp,close\n")
        monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path)
        monkeypatch.setattr(hp_router_module, "_get_watchlist", lambda: ["MCL", "NFLX", "SPY"])
        assert hp_router_module.get_price_covered_watchlist() == ["MCL", "SPY"]


class TestPriceCoverageEndpoint:
    @pytest.fixture
    def coverage_client(self, tmp_path, monkeypatch):
        (tmp_path / "MCL_2025-01-01_2026-01-01_1d.csv").write_text("timestamp,close\n")
        (tmp_path / "SPY_2025-01-01_2026-01-01_1d.csv").write_text("timestamp,close\n")
        monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path)

        mock_config = MagicMock()
        mock_config.SCAN_SYMBOLS = ["MCL", "MNQ", "SPY", "NFLX"]
        inject_dependencies(MagicMock(), mock_config)

        app = FastAPI()
        app.include_router(hp_router)
        return TestClient(app)

    def test_returns_200(self, coverage_client):
        resp = coverage_client.get("/hidden-pivots/price-coverage")
        assert resp.status_code == 200

    def test_watchlist_size_matches_configured_watchlist(self, coverage_client):
        resp = coverage_client.get("/hidden-pivots/price-coverage")
        assert resp.json()["watchlist_size"] == 4

    def test_covered_symbols_are_exactly_the_ones_with_a_cache_file(self, coverage_client):
        resp = coverage_client.get("/hidden-pivots/price-coverage")
        data = resp.json()
        assert set(data["covered_symbols"]) == {"MCL", "SPY"}

    def test_uncovered_symbols_are_the_complement_of_covered(self, coverage_client):
        resp = coverage_client.get("/hidden-pivots/price-coverage")
        data = resp.json()
        assert set(data["uncovered_symbols"]) == {"MNQ", "NFLX"}
        assert set(data["covered_symbols"]) | set(data["uncovered_symbols"]) == {
            "MCL",
            "MNQ",
            "SPY",
            "NFLX",
        }
        assert not (set(data["covered_symbols"]) & set(data["uncovered_symbols"]))


class TestScanEndpointUnaffectedByPriceCoverage:
    """PRB-21: /scan must keep scanning the FULL watchlist regardless of
    which symbols have a CSV price-cache floor — only the dashboard's live-
    price poll is capped, never pattern/level scanning."""

    def test_scan_covers_full_watchlist_even_with_zero_price_coverage(self, tmp_path, monkeypatch):
        # Empty cache dir -> get_price_covered_watchlist() would report zero
        # covered symbols, but /scan is a completely separate code path and
        # must be untouched by that.
        monkeypatch.setattr(hp_router_module, "_CSV_CACHE_DIR", tmp_path)

        mock_data_manager = MagicMock()
        mock_data_manager.get_bars = AsyncMock(return_value=_fake_bars())
        mock_config = MagicMock()
        mock_config.SCAN_SYMBOLS = ["MCL", "MNQ", "NFLX"]
        inject_dependencies(mock_data_manager, mock_config)

        app = FastAPI()
        app.include_router(hp_router)
        local_client = TestClient(app)

        assert hp_router_module.get_price_covered_watchlist() == []

        resp = local_client.get("/hidden-pivots/scan")
        assert resp.status_code == 200
        assert resp.json()["symbols_scanned"] == 3
