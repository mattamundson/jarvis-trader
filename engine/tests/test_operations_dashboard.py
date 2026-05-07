"""
Tests for engine.api.operations_dashboard.

All tests are offline — no running engine, no SQLite file required.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure engine root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TODAY = date(2026, 5, 7)

_SAMPLE_TRADES = [
    {
        "order_id": "aaa-001",
        "timestamp": "2026-05-07T14:00:00Z",
        "symbol": "MES",
        "side": "buy",
        "quantity": 1,
        "filled_price": 5300.0,
        "slippage_ticks": 0,
        "pnl": None,
    },
    {
        "order_id": "aaa-002",
        "timestamp": "2026-05-07T15:00:00Z",
        "symbol": "MES",
        "side": "sell",
        "quantity": 1,
        "filled_price": 5310.0,
        "slippage_ticks": 0,
        "pnl": 10.0,  # intentionally wrong (writer bug); pairing should recompute
    },
]


# ---------------------------------------------------------------------------
# test_dashboard_json_returns_all_panels
# ---------------------------------------------------------------------------

def test_dashboard_json_returns_all_panels():
    """build_dashboard_data returns a dict with all expected top-level keys."""
    from api.operations_dashboard import build_dashboard_data

    # Patch expensive calls so test is fast + offline
    with (
        patch("api.operations_dashboard._get_engine_health", return_value={"reachable": False, "status": "unreachable", "tradingview_mcp_healthy": False, "llm_path_healthy": False, "ibkr_exec": {}, "ibkr_data": {}, "kill_switch_active": False, "polled_at": "2026-05-07T00:00:00Z"}),
        patch("api.operations_dashboard._get_live_readiness", return_value={"status": "RED", "pass_count": 2, "consecutive_passing_days": 0, "days_to_live": 14, "gates": [], "source": "mock"}),
        patch("api.operations_dashboard._get_uptime_7d", return_value=[True, True, False, True, True, True, False]),
        patch("api.operations_dashboard._load_paper_trades_today", return_value=_SAMPLE_TRADES),
        patch("api.operations_dashboard._get_open_positions_count", return_value=1),
        patch("api.operations_dashboard._read_latest_report", return_value=None),
        patch("api.operations_dashboard._get_career_ops_recap", return_value=None),
    ):
        result = build_dashboard_data(target_date=_TODAY)

    assert "generated_at" in result, "Missing generated_at"
    assert "report_date" in result, "Missing report_date"
    assert "today" in result, "Missing today panel"
    assert "live_readiness" in result, "Missing live_readiness panel"
    assert "engine_health" in result, "Missing engine_health panel"
    assert "uptime_7d" in result, "Missing uptime_7d"
    assert "reports" in result, "Missing reports panel"

    today = result["today"]
    for key in ("pnl", "pnl_target", "total_trades", "wins", "losses", "open_positions"):
        assert key in today, f"today.{key} missing"

    reports = result["reports"]
    for key in ("morning_briefing", "post_trade", "career_recap"):
        assert key in reports, f"reports.{key} missing"


# ---------------------------------------------------------------------------
# test_dashboard_json_handles_missing_reports_gracefully
# ---------------------------------------------------------------------------

def test_dashboard_json_handles_missing_reports_gracefully():
    """When no report files exist, the reports panel returns None values — no crash."""
    from api.operations_dashboard import build_dashboard_data

    with (
        patch("api.operations_dashboard._get_engine_health", return_value={"reachable": False, "status": "unreachable", "tradingview_mcp_healthy": False, "llm_path_healthy": False, "ibkr_exec": {}, "ibkr_data": {}, "kill_switch_active": False, "polled_at": "2026-05-07T00:00:00Z"}),
        patch("api.operations_dashboard._get_live_readiness", return_value={"status": "UNKNOWN", "pass_count": 0, "consecutive_passing_days": 0, "days_to_live": 14, "gates": [], "source": "mock"}),
        patch("api.operations_dashboard._get_uptime_7d", return_value=[False] * 7),
        patch("api.operations_dashboard._load_paper_trades_today", return_value=[]),
        patch("api.operations_dashboard._get_open_positions_count", return_value=0),
        # Reports return None (no files found)
        patch("api.operations_dashboard._read_latest_report", return_value=None),
        patch("api.operations_dashboard._get_career_ops_recap", return_value=None),
    ):
        result = build_dashboard_data(target_date=_TODAY)

    reports = result["reports"]
    assert reports["morning_briefing"] is None, "morning_briefing should be None when absent"
    assert reports["post_trade"] is None, "post_trade should be None when absent"
    assert reports["career_recap"] is None, "career_recap should be None when absent"

    # today panel should still have zeros, not crash
    today = result["today"]
    assert today["total_trades"] == 0
    assert today["pnl"] == 0.0


# ---------------------------------------------------------------------------
# test_dashboard_html_serves_html_content_type
# ---------------------------------------------------------------------------

def test_dashboard_html_serves_html_content_type():
    """The /operations/dashboard.html endpoint returns an HTMLResponse."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from api.operations_dashboard import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    # Patch the HTML file path so it resolves to a temp file
    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False, encoding="utf-8") as f:
        f.write("<html><body>test</body></html>")
        tmp_path = Path(f.name)

    try:
        with patch("api.operations_dashboard._DASHBOARD_HTML", tmp_path):
            resp = client.get("/operations/dashboard.html")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert "text/html" in resp.headers.get("content-type", ""), \
            f"Expected HTML content-type, got: {resp.headers.get('content-type')}"
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# test_dashboard_json_pnl_uses_paired_trades_helper
# ---------------------------------------------------------------------------

def test_dashboard_json_pnl_uses_paired_trades_helper():
    """
    PnL computation uses pair_trades (FIFO FIFO) + contract multiplier.
    MES buy @ 5300 → sell @ 5310: 1 contract × 5 (MES multiplier) = $50, not $10.
    The stored ``pnl`` field on the sell is intentionally wrong (writer bug);
    the pairing helper must recompute from prices.
    """
    from api.operations_dashboard import build_dashboard_data

    with (
        patch("api.operations_dashboard._get_engine_health", return_value={"reachable": False, "status": "unreachable", "tradingview_mcp_healthy": False, "llm_path_healthy": False, "ibkr_exec": {}, "ibkr_data": {}, "kill_switch_active": False, "polled_at": "2026-05-07T00:00:00Z"}),
        patch("api.operations_dashboard._get_live_readiness", return_value={"status": "RED", "pass_count": 0, "consecutive_passing_days": 0, "days_to_live": 14, "gates": [], "source": "mock"}),
        patch("api.operations_dashboard._get_uptime_7d", return_value=[False] * 7),
        patch("api.operations_dashboard._load_paper_trades_today", return_value=_SAMPLE_TRADES),
        patch("api.operations_dashboard._get_open_positions_count", return_value=0),
        patch("api.operations_dashboard._read_latest_report", return_value=None),
        patch("api.operations_dashboard._get_career_ops_recap", return_value=None),
    ):
        result = build_dashboard_data(target_date=_TODAY)

    today = result["today"]
    # (5310 - 5300) * 1 qty * 5 multiplier = $50
    assert today["pnl"] == pytest.approx(50.0, abs=0.01), (
        f"Expected PnL=$50.0 (correct multiplier), got {today['pnl']}. "
        "Likely using stored pnl (writer-bug value) instead of pairing helper."
    )
    assert today["total_trades"] == 1
    assert today["wins"] == 1
    assert today["losses"] == 0
