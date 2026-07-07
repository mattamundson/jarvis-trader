"""
Tests for IB market scanner module and HTTP routes.

All tests are offline — no IB Gateway connection required.
Scanner uses ENABLE_IB_SCANNER env flag (read at call time, not import time).
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_scan_item(rank: int, symbol: str) -> MagicMock:
    """Build a minimal mock ScannerData item matching the ib_async shape."""
    contract = MagicMock()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = "NASDAQ"
    contract.conId = 100 + rank

    details = MagicMock()
    details.contract = contract

    item = MagicMock()
    item.rank = rank
    item.contractDetails = details
    item.lastPrice = 100.0 + rank
    item.volume = 1_000_000 + rank * 10_000
    item.pctChange = rank * 0.5
    return item


# ── test_disabled_returns_501_via_route ───────────────────────────────────────


def test_disabled_returns_501_via_route():
    """
    When ENABLE_IB_SCANNER is not set (default OFF), all /ib-scanner/* routes
    must return HTTP 501 Not Implemented.
    """
    env_patch = {"ENABLE_IB_SCANNER": "0"}
    with patch.dict(os.environ, env_patch, clear=False):
        from routers.ib_scanner_router import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        for path in ["/ib-scanner/top-movers", "/ib-scanner/futures-movers"]:
            resp = client.get(path)
            assert (
                resp.status_code == 501
            ), f"Expected 501 for {path} when scanner disabled, got {resp.status_code}"
            assert "ENABLE_IB_SCANNER" in resp.json().get("detail", "")

        # Raw passthrough also needs a scan_code param — still 501 before validation
        resp = client.get("/ib-scanner/raw?scan_code=TOP_PERC_GAIN")
        assert resp.status_code == 501


# ── test_scan_returns_empty_list_on_timeout ───────────────────────────────────


@pytest.mark.asyncio
async def test_scan_returns_empty_list_on_timeout():
    """
    When the IB Gateway connection times out, scan() must return [] without raising.
    """
    with patch.dict(os.environ, {"ENABLE_IB_SCANNER": "1"}):
        with patch("brokers.ib_scanner._IB_AVAILABLE", True):
            mock_ib_instance = MagicMock()
            mock_ib_instance.connectAsync = AsyncMock(
                side_effect=asyncio.TimeoutError("connection timed out")
            )
            mock_ib_instance.disconnect = MagicMock()

            mock_ib_class = MagicMock(return_value=mock_ib_instance)

            with patch("brokers.ib_scanner._IB_CLASS", mock_ib_class):
                from brokers.ib_scanner import scan

                result = await scan("TOP_PERC_GAIN")

        assert result == [], f"Expected empty list on timeout, got: {result}"


# ── test_scan_top_movers_runs_parallel ────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_top_movers_runs_parallel():
    """
    scan_top_movers() must attempt all three scan codes
    (TOP_PERC_GAIN, TOP_PERC_LOSE, HOT_BY_VOLUME) in a single call.
    We verify all three were attempted by checking the mock call args.
    """
    call_log: list[str] = []

    async def fake_scan(scan_code: str, **kwargs):  # noqa: ANN003
        call_log.append(scan_code)
        return [
            {
                "rank": 1,
                "symbol": "TEST",
                "sec_type": "STK",
                "exchange": "NYSE",
                "contract_id": 1,
                "last_price": 100.0,
                "volume": 1e6,
                "pct_change": 2.0,
            }
        ]

    with patch("brokers.ib_scanner.scan", side_effect=fake_scan):
        from brokers.ib_scanner import scan_top_movers

        result = await scan_top_movers()

    # All three scan codes must have been called
    assert "TOP_PERC_GAIN" in call_log, f"TOP_PERC_GAIN not called; got {call_log}"
    assert "TOP_PERC_LOSE" in call_log, f"TOP_PERC_LOSE not called; got {call_log}"
    assert "HOT_BY_VOLUME" in call_log, f"HOT_BY_VOLUME not called; got {call_log}"

    # Result dict has expected keys
    assert "gainers" in result
    assert "losers" in result
    assert "unusual_volume" in result


# ── test_raw_passthrough_validates_scan_code ──────────────────────────────────


def test_raw_passthrough_validates_scan_code():
    """
    GET /ib-scanner/raw with an unknown scan_code must return HTTP 400.
    Known codes pass the validation gate (may still 501 if scanner disabled,
    but the 400 check happens before the 501 guard in this path).

    We enable the scanner in env to force the 400 to surface.
    """
    with patch.dict(os.environ, {"ENABLE_IB_SCANNER": "1"}):
        # Patch scan() so no real IB call fires
        async def fake_scan(*args, **kwargs):  # noqa: ANN002, ANN003
            return []

        with patch("brokers.ib_scanner.scan", side_effect=fake_scan):
            from routers.ib_scanner_router import router

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app, raise_server_exceptions=False)

            # Unknown scan code — must be rejected 400
            resp = client.get("/ib-scanner/raw?scan_code=BOGUS_CODE_XYZ")
            assert (
                resp.status_code == 400
            ), f"Expected 400 for unknown scan_code, got {resp.status_code}: {resp.text}"
            assert "BOGUS_CODE_XYZ" in resp.json().get("detail", "")

            # Known scan code — passes validation (returns 200 with empty results)
            resp = client.get("/ib-scanner/raw?scan_code=TOP_PERC_GAIN")
            assert (
                resp.status_code == 200
            ), f"Expected 200 for valid scan_code, got {resp.status_code}: {resp.text}"
