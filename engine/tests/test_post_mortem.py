"""
JARVIS TRADER — Post-Trade Analysis Tests

Regression test for a bug where PostTradeAnalyzer called
self.db._get_connection() — a method that never existed on DatabaseManager
(only self.db._connect() does). Because nothing in the codebase instantiated
PostTradeAnalyzer, this went undetected: _ensure_table() would have raised
AttributeError the moment it was ever constructed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.post_mortem import PostTradeAnalyzer
from database.manager import DatabaseManager


def _fake_llm_client(response_json: dict) -> SimpleNamespace:
    """Build a minimal stand-in for JarvisLLMClient exposing .client.messages.create."""
    message = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(response_json))])
    messages = SimpleNamespace(create=AsyncMock(return_value=message))
    client = SimpleNamespace(messages=messages)
    return SimpleNamespace(client=client)


class TestEnsureTable:
    def test_construction_does_not_raise(self, tmp_path: Path) -> None:
        """PostTradeAnalyzer() must not crash on construction (regression: AttributeError)."""
        db = DatabaseManager(str(tmp_path / "test.db"))
        db.initialize()

        analyzer = PostTradeAnalyzer(db_manager=db, llm_client=_fake_llm_client({}))

        assert analyzer.db is db

    def test_table_actually_created(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        db = DatabaseManager(str(db_path))
        db.initialize()

        PostTradeAnalyzer(db_manager=db, llm_client=_fake_llm_client({}))

        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trade_post_mortem'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None


class TestAnalyzeTrade:
    @pytest.mark.asyncio
    async def test_analyze_trade_persists_row(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        db = DatabaseManager(str(db_path))
        db.initialize()

        llm = _fake_llm_client(
            {
                "analysis": "Entry aligned with trend, exit hit target cleanly.",
                "what_worked": "Trend filter",
                "what_failed": "None",
                "lesson": "Keep trailing stop at 2.0x ATR for trend trades.",
            }
        )
        analyzer = PostTradeAnalyzer(db_manager=db, llm_client=llm)

        result = await analyzer.analyze_trade(
            trade_id="T-1",
            trade_data={
                "symbol": "MES",
                "side": "LONG",
                "quantity": 1,
                "entry_price": 5800.0,
                "exit_price": 5850.0,
                "pnl": 250.0,
                "exit_reason": "target",
            },
            market_context={"regime": "TREND"},
        )

        assert "error" not in result
        assert result["lesson"] == "Keep trailing stop at 2.0x ATR for trend trades."

        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT trade_id, symbol, pnl, lesson FROM trade_post_mortem WHERE trade_id = ?",
                ("T-1",),
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        assert row[0] == "T-1"
        assert row[1] == "MES"
        assert row[2] == 250.0
        assert row[3] == "Keep trailing stop at 2.0x ATR for trend trades."
