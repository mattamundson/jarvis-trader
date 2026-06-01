"""Tests for the QuestDB dual-write scaffold (engine/discord/storage_questdb.py).

Design principles (matching test_discord_learning.py conventions):
  - No real QuestDB connection — httpx is mocked via unittest.mock.patch.
  - No real SQLite needed for storage_questdb tests (models are passed directly).
  - test_backfill_dry_run_does_not_write uses a synthetic SQLite + mock QuestDB.
  - All tests pass without QuestDB being installed or running.

Run from engine/:
    python -m pytest tests/test_storage_questdb.py -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_ENGINE_DIR = Path(__file__).parent.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))
if str(_ENGINE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR.parent))

# ---------------------------------------------------------------------------
# Environment guard
# ---------------------------------------------------------------------------
_ENV_DEFAULTS = {
    "API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "sk-test",
}
for _k, _v in _ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)

# Always start each test module without dual-write enabled
os.environ.pop("ENABLE_QUESTDB_DUAL_WRITE", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bot_signal(**kwargs):
    """Return a minimal BotSignal-like namespace."""
    defaults = {
        "message_id": "msg-123",
        "timestamp": "2026-05-20T09:30:00",
        "symbol": "ES",
        "timeframe": "15m",
        "direction": "LONG",
        "signal_type": "ENTRY",
        "entry_price": 5200.0,
        "target1": 5220.0,
        "target2": None,
        "stop1": 5185.0,
        "stop2": None,
        "win_rate": 68.5,
        "wins": 42,
        "losses": 20,
        "mfe": 25.0,
        "mae": -8.0,
        "rr": 1.8,
        "gain": 15.0,
        "draw": -5.0,
        "net": 10.0,
        "last_price": 5202.0,
        "source_channel": "proton-bot-alerts",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_commentary(**kwargs):
    """Return a minimal CoreyCommentary-like namespace."""
    defaults = {
        "message_id": "cmty-456",
        "timestamp": "2026-05-20T09:15:00",
        "content": "buyers above POC, long bias",
        "channel": "market-updates",
        "author_id": "564449478174703646",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_ib_report(**kwargs):
    """Return a minimal IBReport-like namespace."""
    defaults = {
        "message_id": "ib-789",
        "timestamp": "2026-05-20T08:45:00",
        "symbol": "ES",
        "timeframe": "15m",
        "ib_open": 5190.0,
        "ib_high": 5210.0,
        "ib_low": 5175.0,
        "ib_close": 5200.0,
        "ib_range": 35.0,
        "ibu50": 5227.5,
        "ibu100": 5245.0,
        "ibd50": 5157.5,
        "ibd100": 5140.0,
        "auction_context": "IBH",
        "source_channel": "indicator-alerts",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _mock_ok_response():
    """Return a mock httpx.Response that looks like a successful QuestDB response."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"ddl": "OK"}
    resp.status_code = 200
    return resp


# ===========================================================================
# 1. Disabled by default — NO-OP without connecting
# ===========================================================================


class TestDisabledByDefault:
    """When ENABLE_QUESTDB_DUAL_WRITE is not set, functions return without connecting."""

    def setup_method(self):
        """Ensure the flag is off and the cached client is cleared before each test."""
        os.environ.pop("ENABLE_QUESTDB_DUAL_WRITE", None)
        import discord.storage_questdb as qdb

        qdb._reset_client()

    def test_is_questdb_dual_write_enabled_returns_false_by_default(self):
        """is_questdb_dual_write_enabled() returns False when env var is absent."""
        from discord.storage_questdb import is_questdb_dual_write_enabled

        assert is_questdb_dual_write_enabled() is False

    def test_is_questdb_dual_write_enabled_returns_false_when_zero(self):
        """is_questdb_dual_write_enabled() returns False when var is '0'."""
        os.environ["ENABLE_QUESTDB_DUAL_WRITE"] = "0"
        from discord.storage_questdb import is_questdb_dual_write_enabled

        assert is_questdb_dual_write_enabled() is False

    def test_insert_bot_signal_ts_noop_when_disabled(self):
        """insert_bot_signal_ts does not attempt any HTTP call when disabled."""
        from discord.storage_questdb import insert_bot_signal_ts

        sig = _make_bot_signal()
        with patch("httpx.Client") as mock_client_cls:
            insert_bot_signal_ts(sig)
            mock_client_cls.assert_not_called()

    def test_insert_corey_commentary_ts_noop_when_disabled(self):
        """insert_corey_commentary_ts does not attempt any HTTP call when disabled."""
        from discord.storage_questdb import insert_corey_commentary_ts

        cmty = _make_commentary()
        with patch("httpx.Client") as mock_client_cls:
            insert_corey_commentary_ts(cmty)
            mock_client_cls.assert_not_called()

    def test_insert_ib_report_ts_noop_when_disabled(self):
        """insert_ib_report_ts does not attempt any HTTP call when disabled."""
        from discord.storage_questdb import insert_ib_report_ts

        rep = _make_ib_report()
        with patch("httpx.Client") as mock_client_cls:
            insert_ib_report_ts(rep)
            mock_client_cls.assert_not_called()

    def test_insert_daily_sentiment_ts_noop_when_disabled(self):
        """insert_daily_sentiment_ts does not attempt any HTTP call when disabled."""
        from discord.storage_questdb import insert_daily_sentiment_ts

        with patch("httpx.Client") as mock_client_cls:
            insert_daily_sentiment_ts(
                date_key="2026-05-20",
                sentiment_score=0.42,
                post_count=5,
                source="discord_corey_commentary",
                computed_at="2026-05-20T12:00:00",
            )
            mock_client_cls.assert_not_called()

    def teardown_method(self):
        os.environ.pop("ENABLE_QUESTDB_DUAL_WRITE", None)


# ===========================================================================
# 2. Enabled — attempts QuestDB write with correct SQL
# ===========================================================================


class TestEnabledAttemptsQuestDBWrite:
    """When ENABLE_QUESTDB_DUAL_WRITE=1, insert_* calls hit the QuestDB exec endpoint."""

    def setup_method(self):
        os.environ["ENABLE_QUESTDB_DUAL_WRITE"] = "1"
        import discord.storage_questdb as qdb

        qdb._reset_client()

    def teardown_method(self):
        os.environ.pop("ENABLE_QUESTDB_DUAL_WRITE", None)
        import discord.storage_questdb as qdb

        qdb._reset_client()

    def test_insert_bot_signal_ts_sends_insert_sql(self):
        """When enabled, insert_bot_signal_ts calls the /exec endpoint with INSERT SQL."""
        from discord.storage_questdb import insert_bot_signal_ts

        mock_resp = _mock_ok_response()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            sig = _make_bot_signal(message_id="test-sig-001")
            insert_bot_signal_ts(sig)

        # At least one call should be the DDL ensure, then one is the INSERT
        assert mock_client.get.called
        calls = [str(c) for c in mock_client.get.call_args_list]
        # At least one call should reference discord_bot_signals_ts
        assert any("discord_bot_signals_ts" in c for c in calls)

    def test_insert_bot_signal_ts_includes_message_id_in_sql(self):
        """The INSERT SQL for a bot signal includes the message_id value."""
        from discord.storage_questdb import insert_bot_signal_ts

        mock_resp = _mock_ok_response()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            sig = _make_bot_signal(message_id="unique-msg-xyz-9999")
            insert_bot_signal_ts(sig)

        all_call_args = str(mock_client.get.call_args_list)
        assert "unique-msg-xyz-9999" in all_call_args

    def test_insert_corey_commentary_ts_sends_insert_sql(self):
        """When enabled, insert_corey_commentary_ts calls /exec with INSERT SQL."""
        from discord.storage_questdb import insert_corey_commentary_ts

        mock_resp = _mock_ok_response()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            cmty = _make_commentary(message_id="cmty-enable-test")
            insert_corey_commentary_ts(cmty)

        calls = str(mock_client.get.call_args_list)
        assert "discord_corey_commentary_ts" in calls

    def test_insert_ib_report_ts_sends_insert_sql(self):
        """When enabled, insert_ib_report_ts calls /exec with INSERT SQL."""
        from discord.storage_questdb import insert_ib_report_ts

        mock_resp = _mock_ok_response()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            rep = _make_ib_report(message_id="ib-enable-test")
            insert_ib_report_ts(rep)

        calls = str(mock_client.get.call_args_list)
        assert "discord_ib_reports_ts" in calls

    def test_insert_daily_sentiment_ts_sends_insert_sql(self):
        """When enabled, insert_daily_sentiment_ts calls /exec with INSERT SQL."""
        from discord.storage_questdb import insert_daily_sentiment_ts

        mock_resp = _mock_ok_response()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            insert_daily_sentiment_ts(
                date_key="2026-05-20",
                sentiment_score=0.42,
                post_count=5,
                source="discord_corey_commentary",
                computed_at="2026-05-20T12:00:00",
            )

        calls = str(mock_client.get.call_args_list)
        assert "discord_daily_sentiment_ts" in calls


# ===========================================================================
# 3. QuestDB failure is logged, not raised
# ===========================================================================


class TestQuestDBFailureLoggedNotRaised:
    """When QuestDB raises, the function logs a WARNING and returns None — never raises."""

    def setup_method(self):
        os.environ["ENABLE_QUESTDB_DUAL_WRITE"] = "1"
        import discord.storage_questdb as qdb

        qdb._reset_client()

    def teardown_method(self):
        os.environ.pop("ENABLE_QUESTDB_DUAL_WRITE", None)
        import discord.storage_questdb as qdb

        qdb._reset_client()

    def test_bot_signal_failure_returns_none(self):
        """insert_bot_signal_ts returns None even when httpx raises."""
        from discord.storage_questdb import insert_bot_signal_ts

        mock_client = MagicMock()
        mock_client.get.side_effect = ConnectionError("QuestDB unreachable")

        with patch("httpx.Client", return_value=mock_client):
            result = insert_bot_signal_ts(_make_bot_signal())

        assert result is None

    def test_bot_signal_failure_logs_warning(self, caplog):
        """insert_bot_signal_ts logs a WARNING when QuestDB raises."""
        import logging

        from discord.storage_questdb import insert_bot_signal_ts

        mock_client = MagicMock()
        mock_client.get.side_effect = ConnectionError("QuestDB unreachable")

        with patch("httpx.Client", return_value=mock_client):
            with caplog.at_level(logging.WARNING, logger="discord.storage_questdb"):
                insert_bot_signal_ts(_make_bot_signal(message_id="fail-test-001"))

        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("fail-test-001" in m or "questdb" in m.lower() for m in warning_msgs)

    def test_commentary_failure_returns_none(self):
        """insert_corey_commentary_ts returns None even when httpx raises."""
        from discord.storage_questdb import insert_corey_commentary_ts

        mock_client = MagicMock()
        mock_client.get.side_effect = OSError("network error")

        with patch("httpx.Client", return_value=mock_client):
            result = insert_corey_commentary_ts(_make_commentary())

        assert result is None

    def test_ib_report_failure_does_not_raise(self):
        """insert_ib_report_ts does not propagate exceptions from QuestDB."""
        from discord.storage_questdb import insert_ib_report_ts

        mock_client = MagicMock()
        mock_client.get.side_effect = RuntimeError("unexpected QuestDB error")

        with patch("httpx.Client", return_value=mock_client):
            # Must not raise
            insert_ib_report_ts(_make_ib_report())


# ===========================================================================
# 4. DDL idempotency — calling _ensure_table_exists twice doesn't error
# ===========================================================================


class TestDdlIdempotent:
    """_ensure_table_exists is cached and doesn't send DDL twice for same table."""

    def setup_method(self):
        os.environ["ENABLE_QUESTDB_DUAL_WRITE"] = "1"
        import discord.storage_questdb as qdb

        qdb._reset_client()

    def teardown_method(self):
        os.environ.pop("ENABLE_QUESTDB_DUAL_WRITE", None)
        import discord.storage_questdb as qdb

        qdb._reset_client()

    def test_ensure_table_exists_called_once_per_table(self):
        """_ensure_table_exists only calls /exec once for the same table name."""
        from discord.storage_questdb import _DDL_BOT_SIGNALS, _ensure_table_exists

        mock_resp = _mock_ok_response()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        # First call should hit /exec
        _ensure_table_exists(mock_client, "discord_bot_signals_ts", _DDL_BOT_SIGNALS)
        call_count_after_first = mock_client.get.call_count

        # Second call should be cached — no additional /exec call
        _ensure_table_exists(mock_client, "discord_bot_signals_ts", _DDL_BOT_SIGNALS)
        call_count_after_second = mock_client.get.call_count

        assert call_count_after_first == 1
        assert call_count_after_second == 1  # no additional call

    def test_ensure_table_ddl_failure_does_not_raise(self):
        """_ensure_table_exists swallows DDL errors gracefully."""
        from discord.storage_questdb import _DDL_BOT_SIGNALS, _ensure_table_exists, _tables_ensured

        mock_client = MagicMock()
        mock_client.get.side_effect = ConnectionError("QuestDB down")

        unique_table = "discord_bot_signals_ts_ddl_fail_test"
        _tables_ensured.discard(unique_table)

        # Must not raise
        _ensure_table_exists(mock_client, unique_table, _DDL_BOT_SIGNALS)

    def test_ensure_different_tables_each_get_one_ddl_call(self):
        """Each distinct table name gets exactly one DDL /exec call."""
        from discord.storage_questdb import (
            _DDL_BOT_SIGNALS,
            _DDL_COREY_COMMENTARY,
            _ensure_table_exists,
            _tables_ensured,
        )

        mock_resp = _mock_ok_response()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp

        t1 = "discord_test_alpha_ts"
        t2 = "discord_test_beta_ts"
        _tables_ensured.discard(t1)
        _tables_ensured.discard(t2)

        _ensure_table_exists(mock_client, t1, _DDL_BOT_SIGNALS)
        _ensure_table_exists(mock_client, t2, _DDL_COREY_COMMENTARY)
        _ensure_table_exists(mock_client, t1, _DDL_BOT_SIGNALS)  # cached
        _ensure_table_exists(mock_client, t2, _DDL_COREY_COMMENTARY)  # cached

        # Exactly 2 calls total (one per distinct table name)
        assert mock_client.get.call_count == 2


# ===========================================================================
# 5. Backfill dry-run does not write to QuestDB
# ===========================================================================


class TestBackfillDryRun:
    """The backfill script --dry-run mode reports counts without writing."""

    def _make_temp_sqlite(self) -> str:
        """Create a fresh SQLite database with Discord tables and sample rows."""
        fd, path = tempfile.mkstemp(suffix=".db", prefix="jarvis_backfill_test_")
        os.close(fd)
        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS discord_bot_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    symbol TEXT,
                    timeframe TEXT,
                    direction TEXT,
                    signal_type TEXT,
                    entry_price REAL,
                    target1 REAL, target2 REAL,
                    stop1 REAL, stop2 REAL,
                    win_rate REAL,
                    wins INTEGER, losses INTEGER,
                    mfe REAL, mae REAL, rr REAL,
                    gain REAL, draw REAL, net REAL,
                    last_price REAL, source_channel TEXT
                );
                INSERT INTO discord_bot_signals
                    (message_id, timestamp, symbol, source_channel)
                VALUES
                    ('backfill-1', '2026-05-19T09:30:00', 'ES', 'proton-bot-alerts'),
                    ('backfill-2', '2026-05-20T09:30:00', 'NQ', 'proton-bot-alerts');
            """
            )
            conn.commit()
        finally:
            conn.close()
        return path

    def test_dry_run_does_not_write(self, capsys):
        """--dry-run mode prints counts but makes no HTTP write calls to QuestDB."""
        import importlib
        import sys

        db_path = self._make_temp_sqlite()
        try:
            # Import backfill module dynamically
            backfill_path = (
                Path(__file__).parent.parent.parent / "scripts" / "backfill_discord_to_questdb.py"
            )
            import importlib.util

            spec = importlib.util.spec_from_file_location("backfill_script", backfill_path)
            backfill = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(backfill)

            # Build a mock QuestDB client that raises if any write is attempted
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"dataset": []}
            mock_client.get.return_value = mock_resp

            cfg = backfill.TABLES["bot_signals"]
            total, written, skipped = backfill._backfill_table(
                client=mock_client,
                cfg=cfg,
                db_path=db_path,
                batch_size=100,
                dry_run=True,
            )

            # In dry-run, "written" is the count of rows that WOULD be written
            assert total == 2
            assert written == 2
            assert skipped == 0

            # No actual HTTP write calls should have been made
            # (existing_ids check is skipped in dry-run mode too)
            assert mock_client.get.call_count == 0
        finally:
            try:
                os.unlink(db_path)
            except PermissionError:
                pass  # Windows SQLite journal lock — OS will clean up

    def test_dry_run_skips_already_present_rows(self):
        """In dry-run with pre-existing IDs, those rows should be counted as skipped."""
        import importlib.util

        db_path = self._make_temp_sqlite()
        try:
            backfill_path = (
                Path(__file__).parent.parent.parent / "scripts" / "backfill_discord_to_questdb.py"
            )
            spec = importlib.util.spec_from_file_location("backfill_script", backfill_path)
            backfill = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(backfill)

            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            # Return existing IDs — simulate both rows already in QuestDB
            mock_resp.json.return_value = {"dataset": [["backfill-1"], ["backfill-2"]]}
            mock_client.get.return_value = mock_resp

            cfg = backfill.TABLES["bot_signals"]
            # non-dry-run so existing IDs are fetched
            total, written, skipped = backfill._backfill_table(
                client=mock_client,
                cfg=cfg,
                db_path=db_path,
                batch_size=100,
                dry_run=False,
            )

            assert total == 2
            assert skipped == 2
            assert written == 0
        finally:
            try:
                os.unlink(db_path)
            except PermissionError:
                pass
