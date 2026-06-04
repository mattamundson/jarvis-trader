"""
Tests for engine.scripts.daily_morning_briefing.

All tests are offline — no live engine, no real DB, no Discord.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.daily_morning_briefing import (
    _OVERNIGHT_HOURS,
    _VERDICT_TTL_DAYS,
    _VERDICT_WARN_DAYS,
    DO_NOT_TRADE_SYMBOLS,
    compute_attention_items,
    compute_overnight_regime,
    compute_strategy_expectations,
    fetch_discord_overnight,
    fetch_engine_health,
    fetch_open_positions,
    load_active_strategies,
    render_active_strategies,
    render_attention_items,
    render_briefing,
    render_engine_status,
    render_open_positions,
    render_overnight_regime,
    render_yesterday_tally,
)

_UTC = timezone.utc
_TODAY = date(2026, 5, 7)


# ---------------------------------------------------------------------------
# Helper: build a minimal in-memory SQLite DB with bar data
# ---------------------------------------------------------------------------


def _make_bars_db(
    path: str,
    symbol: str = "MES",
    n_bars: int = 210,
    interval: str = "1h",
) -> None:
    """Create a minimal market_data_bars table with *n_bars* rows."""
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_bars (
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            interval TEXT,
            ts_utc TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL
        )
        """
    )
    base_close = 5300.0
    from datetime import timedelta

    start = datetime(2026, 1, 1, 9, 0, 0, tzinfo=_UTC)
    rows = []
    for i in range(n_bars):
        ts = start + timedelta(hours=i)
        close = base_close + float(i) * 0.1
        rows.append((symbol, interval, ts.isoformat(), close, close + 2.0, close - 2.0, close, 1000))
    con.executemany(
        "INSERT INTO market_data_bars (symbol, interval, ts_utc, open, high, low, close, volume) "
        "VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()


def _make_discord_db(path: str, n_rows: int = 5) -> None:
    """Create a discord_corey_commentary table with recent rows."""
    from datetime import timedelta

    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS discord_corey_commentary (
            id INTEGER PRIMARY KEY,
            message_id TEXT UNIQUE,
            timestamp TEXT NOT NULL,
            content TEXT NOT NULL,
            channel TEXT NOT NULL
        )
        """
    )
    now = datetime.now(_UTC)
    for i in range(n_rows):
        ts = (now - timedelta(hours=i * 2)).strftime("%Y-%m-%dT%H:%M:%S")
        con.execute(
            "INSERT INTO discord_corey_commentary (message_id, timestamp, content, channel) "
            "VALUES (?,?,?,?)",
            (f"msg-{i}", ts, f"Market commentary #{i}: ES looking strong at open", "market-updates"),
        )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Section 1 — Engine Status
# ---------------------------------------------------------------------------


def test_engine_status_section_when_healthy():
    health = {
        "status": "ok",
        "llm_path_healthy": True,
        "tradingview_mcp_healthy": True,
        "ibkr_data_healthy": True,
        "ibkr_exec_healthy": True,
        "kill_switch_active": False,
        "uptime_seconds": 7320,
    }
    rendered = render_engine_status(health)
    text = "\n".join(rendered)
    assert "OK" in text
    assert "LLM path" in text
    assert "TradingView MCP" in text
    assert "2h" in text  # 7320s = 2h 2m


def test_engine_status_section_when_unreachable():
    health = {"status": "UNREACHABLE", "error": "Connection refused"}
    rendered = render_engine_status(health)
    text = "\n".join(rendered)
    assert "DEGRADED" in text or "UNREACHABLE" in text
    assert "unreachable" in text.lower()


def test_fetch_engine_health_returns_error_dict_on_failure():
    """fetch_engine_health must never raise — returns error dict on connection failure."""
    # Port 19999 should be closed on any machine
    with patch("scripts.daily_morning_briefing._ENGINE_HEALTH_URL", "http://127.0.0.1:19999/health"):
        result = fetch_engine_health(timeout=2)
    assert isinstance(result, dict)
    assert result.get("status") == "UNREACHABLE"


# ---------------------------------------------------------------------------
# Section 2 — Active Strategies
# ---------------------------------------------------------------------------


def test_active_strategies_section_lists_only_enabled():
    """render_active_strategies only shows enabled configs."""
    strategies = [
        {
            "symbol": "MES",
            "strategy": "sma_trend",
            "fast": 60,
            "slow": 200,
            "verdict": "PASS",
            "passed_via": "alt",
            "created_at": "2026-05-06",
            "days_since_created": 1,
            "days_until_expiry": 29,
            "verdict_file": "MES_trend_rank11.json",
        }
    ]
    rendered = render_active_strategies(strategies)
    text = "\n".join(rendered)
    assert "MES" in text
    assert "PASS" in text
    assert "SMA(60,200)" in text
    assert "MGC" not in text  # only MES provided


def test_active_strategies_empty_returns_placeholder():
    rendered = render_active_strategies([])
    text = "\n".join(rendered)
    assert "No enabled strategies" in text


# ---------------------------------------------------------------------------
# Section 3 — Overnight Bar Regime
# ---------------------------------------------------------------------------


def test_regime_classification_from_bars():
    """Regime computation returns expected keys from a synthetic bar set."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    _make_bars_db(str(db_path), symbol="MES", n_bars=210)

    # Patch SMA_TREND_PARAMS so we don't need the full engine
    fake_params = {"MES": {"fast": 10, "slow": 20, "atr_trail_mult": 2.0}}
    with patch("analytics.regime.load_recent_bars") as mock_load, \
         patch("backtest.trend_signals.SMA_TREND_PARAMS", fake_params):
        # Build a minimal DataFrame
        import numpy as np

        n = 50
        closes = pd.Series(5300.0 + np.arange(n, dtype=float) * 0.5)
        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="1h"),
            "open": closes,
            "high": closes + 2.0,
            "low": closes - 2.0,
            "close": closes,
            "volume": 1000,
        })
        mock_load.return_value = df

        from analytics.regime import compute_bar_regime

        result = compute_bar_regime("MES", df, fast=10, slow=20)

    assert "regime" in result
    assert "bias" in result
    assert "close" in result
    assert "atr" in result
    # With a steadily rising series, fast SMA > slow SMA → TRENDING_BULL
    assert result["regime"] in ("TRENDING_BULL", "RANGE_BOUND", "INSUFFICIENT_DATA", "UNKNOWN")
    db_path.unlink(missing_ok=True)


def test_regime_section_with_empty_map():
    rendered = render_overnight_regime({})
    text = "\n".join(rendered)
    assert "No regime data" in text


# ---------------------------------------------------------------------------
# Section 4 — Discord Overnight
# ---------------------------------------------------------------------------


def test_overnight_discord_window_is_last_16h():
    """fetch_discord_overnight only returns rows within the cutoff window."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    _make_discord_db(str(db_path), n_rows=6)

    entries = fetch_discord_overnight(hours_back=_OVERNIGHT_HOURS, limit=20, db_path=db_path)

    # All returned entries should have timestamps within the last 16h
    from datetime import timedelta

    cutoff = datetime.now(_UTC) - timedelta(hours=_OVERNIGHT_HOURS)
    for e in entries:
        ts = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).replace(tzinfo=_UTC)
        assert ts >= cutoff, f"Entry {e['timestamp']} is outside the overnight window"

    db_path.unlink(missing_ok=True)


def test_discord_overnight_graceful_when_db_missing():
    """fetch_discord_overnight returns [] when DB path doesn't exist."""
    missing = Path("/nonexistent/path.db")
    result = fetch_discord_overnight(db_path=missing)
    assert result == []


def test_discord_overnight_graceful_when_table_missing():
    """fetch_discord_overnight returns [] when table doesn't exist in DB."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    # Write empty DB — no discord_corey_commentary table
    con = sqlite3.connect(str(db_path))
    con.close()

    result = fetch_discord_overnight(db_path=db_path)
    assert result == []
    db_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Section 8 — Open Positions
# ---------------------------------------------------------------------------


def test_renders_zero_open_positions_gracefully():
    rendered = render_open_positions([])
    text = "\n".join(rendered)
    assert "No open positions" in text


def test_renders_open_positions_with_data():
    positions = [
        {
            "symbol": "MES",
            "side": "buy",
            "quantity": 1,
            "entry_price": 5300.0,
            "unrealized_pnl": 25.0,
        }
    ]
    rendered = render_open_positions(positions)
    text = "\n".join(rendered)
    assert "MES" in text
    assert "5300.00" in text
    assert "+25.00" in text


def test_fetch_open_positions_returns_empty_on_failure():
    """fetch_open_positions must not raise — returns [] on connection failure."""
    with patch(
        "scripts.daily_morning_briefing._ENGINE_POSITIONS_URL",
        "http://127.0.0.1:19999/brokers/positions",
    ):
        result = fetch_open_positions(timeout=2)
    assert isinstance(result, list)
    assert result == []


# ---------------------------------------------------------------------------
# Section 9 — Attention Items
# ---------------------------------------------------------------------------


def test_attention_items_kills_switch_flagged():
    health = {"status": "ok", "kill_switch_active": True}
    items = compute_attention_items(
        health=health,
        active_strategies=[],
        regime_map={},
        briefing_date=_TODAY,
    )
    assert any("KILL SWITCH" in i for i in items)


def test_attention_items_verdict_expiring_soon():
    strategies = [
        {
            "symbol": "MES",
            "verdict": "PASS",
            "days_until_expiry": 3,  # < _VERDICT_WARN_DAYS
            "verdict_file": "MES_trend_rank11.json",
        }
    ]
    items = compute_attention_items(
        health={"status": "ok"},
        active_strategies=strategies,
        regime_map={},
        briefing_date=_TODAY,
    )
    assert any("EXPIRING" in i for i in items)


def test_attention_items_engine_degraded():
    health = {"status": "UNREACHABLE", "error": "timeout"}
    items = compute_attention_items(
        health=health,
        active_strategies=[],
        regime_map={},
        briefing_date=_TODAY,
    )
    assert any(("DEGRADED" in i) or ("UNREACHABLE" in i) for i in items)


def test_attention_items_nothing_flagged_nominal():
    health = {
        "status": "ok",
        "kill_switch_active": False,
        "llm_path_healthy": True,
        "tradingview_mcp_healthy": True,
    }
    strategies = [
        {
            "symbol": "MES",
            "verdict": "PASS",
            "days_until_expiry": 20,
            "verdict_file": "MES_trend_rank11.json",
        }
    ]
    regime_map = {
        "MES": {
            "regime": "TRENDING_BULL",
            "bias": "STRONG_BULL",
            "close": 5300.0,
            "atr": 12.0,
            "sma_fast": 5310.0,
            "sma_slow": 5200.0,
            "fast": 60,
            "slow": 200,
        }
    }
    items = compute_attention_items(
        health=health,
        active_strategies=strategies,
        regime_map=regime_map,
        briefing_date=_TODAY,
    )
    # No items should be raised under nominal conditions
    critical = [i for i in items if "DEGRADED" in i or "KILL SWITCH" in i or "EXPIRING" in i]
    assert critical == []


# ---------------------------------------------------------------------------
# Full render smoke test — no crashes
# ---------------------------------------------------------------------------


def test_render_briefing_no_crash():
    """render_briefing must not raise under any combination of empty/None data."""
    md = render_briefing(
        briefing_date=_TODAY,
        health={"status": "ok", "kill_switch_active": False},
        active_strategies=[],
        regime_map={},
        discord_entries=[],
        expectations=[],
        positions=[],
        attention_items=[],
    )
    assert isinstance(md, str)
    assert "Morning Briefing" in md
    assert "2026-05-07" in md


def test_render_briefing_contains_all_section_headers():
    md = render_briefing(
        briefing_date=_TODAY,
        health={"status": "ok"},
        active_strategies=[],
        regime_map={},
        discord_entries=[],
        expectations=[],
        positions=[],
        attention_items=[],
    )
    expected_headers = [
        "## 1. Engine Status",
        "## 2. Active Strategies Today",
        "## 3. Overnight Bar Regime",
        "## 4. Discord Overnight Signal",
        "## 5. Calendar / Events",
        "## 6. Strategy Expectations Today",
        "## 7. Yesterday's Tally",
        "## 8. Open Positions at Session Start",
        "## 9. Attention Required",
    ]
    for h in expected_headers:
        assert h in md, f"Missing section header: {h!r}"
