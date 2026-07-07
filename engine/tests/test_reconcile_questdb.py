"""Tests for scripts/reconcile_questdb.py.

All tests are offline — no real QuestDB or SQLite I/O needed. QuestDB
responses are mocked via pytest monkeypatch + a lightweight fake httpx client.
SQLite calls are replaced with in-memory fixtures.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap so we can import from scripts/ without installing the pkg
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import reconcile_questdb as rq

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_db_with_data(tmp_path) -> str:
    """Create a minimal SQLite DB with a discord_bot_signals table."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """CREATE TABLE discord_bot_signals (
            message_id TEXT PRIMARY KEY,
            timestamp TEXT,
            symbol TEXT, timeframe TEXT, direction TEXT, signal_type TEXT,
            entry_price REAL, target1 REAL, target2 REAL,
            stop1 REAL, stop2 REAL, win_rate REAL, wins INT, losses INT,
            mfe REAL, mae REAL, rr REAL, gain REAL, draw REAL, net REAL,
            last_price REAL, source_channel TEXT
        )"""
    )
    for i in range(20):
        conn.execute(
            "INSERT INTO discord_bot_signals (message_id, timestamp, symbol) VALUES (?,?,?)",
            (str(i), "2026-01-01T00:00:00", "MES"),
        )
    conn.commit()
    conn.close()
    return str(db)


@pytest.fixture()
def sqlite_db_empty(tmp_path) -> str:
    """Empty discord_bot_signals table."""
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """CREATE TABLE discord_bot_signals (
            message_id TEXT PRIMARY KEY,
            timestamp TEXT, symbol TEXT, timeframe TEXT, direction TEXT,
            signal_type TEXT, entry_price REAL, target1 REAL, target2 REAL,
            stop1 REAL, stop2 REAL, win_rate REAL, wins INT, losses INT,
            mfe REAL, mae REAL, rr REAL, gain REAL, draw REAL, net REAL,
            last_price REAL, source_channel TEXT
        )"""
    )
    conn.commit()
    conn.close()
    return str(db)


# ---------------------------------------------------------------------------
# Fake httpx client helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    count_responses: dict[str, int], id_responses: dict[str, list[str]] | None = None
):
    """Build a mock httpx.Client.get that returns COUNT or ID results.

    count_responses: table_name -> row count
    id_responses: table_name -> list of ids present in QuestDB
    """
    if id_responses is None:
        id_responses = {}

    def _fake_get(path, *, params=None, timeout=30.0):
        sql = (params or {}).get("query", "")
        resp = MagicMock()
        resp.raise_for_status = MagicMock()

        # COUNT query
        if sql.strip().startswith("SELECT count()"):
            table = sql.split("FROM ")[1].strip().rstrip(";")
            count = count_responses.get(table, 0)
            resp.json.return_value = {
                "columns": [{"name": "count", "type": "LONG"}],
                "dataset": [[count]],
            }
            return resp

        # ID presence / fetch query
        if "SELECT message_id FROM" in sql or "SELECT date FROM" in sql:
            table = sql.split("FROM ")[1].split()[0].strip().rstrip(";")
            ids = id_responses.get(table, [])
            resp.json.return_value = {
                "columns": [{"name": "message_id", "type": "SYMBOL"}],
                "dataset": [[i] for i in ids],
            }
            return resp

        resp.json.return_value = {"dataset": []}
        return resp

    mock_client = MagicMock()
    mock_client.get.side_effect = _fake_get
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReconcileTableOkWhenCountsMatch:
    """Status 'ok' when SQLite count == QuestDB count and ids match."""

    def test_ok_status(self, sqlite_db_with_data, monkeypatch, tmp_path):
        # 20 rows in SQLite; QuestDB reports 20; all ids present
        sqlite_ids = [str(i) for i in range(20)]

        mock_client = _make_mock_client(
            count_responses={"discord_bot_signals_ts": 20},
            id_responses={"discord_bot_signals_ts": sqlite_ids},
        )

        import httpx

        class _FakeClientCtx:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return mock_client

            def __exit__(self, *a):
                pass

        monkeypatch.setattr(httpx, "Client", _FakeClientCtx)
        monkeypatch.setattr(rq, "SNAPSHOT_DIR", tmp_path / "snaps")
        monkeypatch.setattr(rq, "VAULT_RAW_DIR", tmp_path / "vault")

        result = rq.reconcile_table("bot_signals", sqlite_db_with_data, "http://mock:9000")

        assert result["status"] == "ok"
        assert result["sqlite_count"] == 20
        assert result["questdb_count"] == 20
        assert result["diff_pct"] == pytest.approx(0.0)
        assert result["missing_from_questdb_sample"] == []


class TestReconcileTableDivergentWhenDriftAboveThreshold:
    """Status 'divergent' when diff_pct is 0.1% < x <= 5%."""

    def test_divergent_status(self, sqlite_db_with_data, monkeypatch, tmp_path):
        # 20 rows in SQLite; QuestDB has only 19 ids — 1/20 = 5% — right at critical boundary
        # Use 19 of 20 ids in QuestDB → 1 missing → 1/20 = 5% → classified critical
        # To get "divergent", use 19/20 where total sqlite = 100 so 1% is missing
        # Rebuild: create 100 rows, QuestDB missing 1 → 1% → divergent
        conn = sqlite3.connect(sqlite_db_with_data)
        conn.execute("DELETE FROM discord_bot_signals")
        for i in range(100):
            conn.execute(
                "INSERT INTO discord_bot_signals (message_id, timestamp, symbol) VALUES (?,?,?)",
                (str(i), "2026-01-01T00:00:00", "MES"),
            )
        conn.commit()
        conn.close()

        questdb_ids = [str(i) for i in range(99)]  # missing id "99"

        mock_client = _make_mock_client(
            count_responses={"discord_bot_signals_ts": 99},
            id_responses={"discord_bot_signals_ts": questdb_ids},
        )

        import httpx

        class _FakeClientCtx:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return mock_client

            def __exit__(self, *a):
                pass

        monkeypatch.setattr(httpx, "Client", _FakeClientCtx)
        monkeypatch.setattr(rq, "SNAPSHOT_DIR", tmp_path / "snaps")
        monkeypatch.setattr(rq, "VAULT_RAW_DIR", tmp_path / "vault")

        result = rq.reconcile_table("bot_signals", sqlite_db_with_data, "http://mock:9000")

        assert result["status"] == "divergent"
        assert result["diff_pct"] == pytest.approx(0.01)
        assert "99" in result["missing_from_questdb_sample"]


class TestReconcileTableCriticalWhenDriftHigh:
    """Status 'critical' when diff_pct > 5%."""

    def test_critical_status(self, sqlite_db_with_data, monkeypatch, tmp_path):
        # 20 sqlite rows, QuestDB has only 18 ids → 2/20 = 10% → critical
        questdb_ids = [str(i) for i in range(18)]

        mock_client = _make_mock_client(
            count_responses={"discord_bot_signals_ts": 18},
            id_responses={"discord_bot_signals_ts": questdb_ids},
        )

        import httpx

        class _FakeClientCtx:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return mock_client

            def __exit__(self, *a):
                pass

        monkeypatch.setattr(httpx, "Client", _FakeClientCtx)
        monkeypatch.setattr(rq, "SNAPSHOT_DIR", tmp_path / "snaps")
        monkeypatch.setattr(rq, "VAULT_RAW_DIR", tmp_path / "vault")

        result = rq.reconcile_table("bot_signals", sqlite_db_with_data, "http://mock:9000")

        assert result["status"] == "critical"
        assert result["diff_pct"] > 0.05
        assert (
            "18" in result["missing_from_questdb_sample"]
            or "19" in result["missing_from_questdb_sample"]
        )


class TestReconcileHandlesQuestdbUnreachable:
    """Status 'unreachable' when QuestDB raises a connection error."""

    def test_unreachable_status(self, sqlite_db_with_data, monkeypatch, tmp_path):
        import httpx

        class _FailingClientCtx:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                mock = MagicMock()
                mock.get.side_effect = httpx.ConnectError("Connection refused")
                return mock

            def __exit__(self, *a):
                pass

        monkeypatch.setattr(httpx, "Client", _FailingClientCtx)
        monkeypatch.setattr(rq, "SNAPSHOT_DIR", tmp_path / "snaps")
        monkeypatch.setattr(rq, "VAULT_RAW_DIR", tmp_path / "vault")

        result = rq.reconcile_table("bot_signals", sqlite_db_with_data, "http://mock:9000")

        assert result["status"] == "unreachable"
        assert "unreachable" in result["note"].lower() or "connection" in result["note"].lower()
        # Reconcile must NOT raise — returns a dict
        assert isinstance(result, dict)


class TestHealRequiresExplicitFlag:
    """heal_table must exit non-zero when ENABLE_QUESTDB_RECONCILE_HEAL is not 1."""

    def test_exits_without_heal_flag(self, sqlite_db_with_data, monkeypatch):
        monkeypatch.setenv("ENABLE_QUESTDB_RECONCILE_HEAL", "0")

        with pytest.raises(SystemExit) as exc_info:
            rq.heal_table("bot_signals", sqlite_db_with_data, "http://mock:9000")

        assert exc_info.value.code != 0

    def test_exits_when_heal_flag_absent(self, sqlite_db_with_data, monkeypatch):
        monkeypatch.delenv("ENABLE_QUESTDB_RECONCILE_HEAL", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            rq.heal_table("bot_signals", sqlite_db_with_data, "http://mock:9000")

        assert exc_info.value.code != 0


class TestWritesVaultMarkdownWithFrontmatter:
    """reconcile_all must write a .md file with YAML frontmatter to the vault dir."""

    def test_vault_markdown_written(self, sqlite_db_with_data, monkeypatch, tmp_path):
        vault_dir = tmp_path / "vault"
        snap_dir = tmp_path / "snaps"
        monkeypatch.setattr(rq, "SNAPSHOT_DIR", snap_dir)
        monkeypatch.setattr(rq, "VAULT_RAW_DIR", vault_dir)

        # Mock all QuestDB calls so we run offline
        questdb_ids = [str(i) for i in range(20)]
        mock_client = _make_mock_client(
            count_responses={"discord_bot_signals_ts": 20},
            id_responses={"discord_bot_signals_ts": questdb_ids},
        )

        import httpx

        class _FakeClientCtx:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return mock_client

            def __exit__(self, *a):
                pass

        monkeypatch.setattr(httpx, "Client", _FakeClientCtx)

        # Only reconcile one table to keep the test fast
        monkeypatch.setattr(
            rq,
            "TABLES",
            {"bot_signals": rq.TABLES["bot_signals"]},
        )

        report = rq.reconcile_all(sqlite_db_with_data, "http://mock:9000")

        md_files = list(vault_dir.glob("reconcile-*.md"))
        assert len(md_files) == 1, "Exactly one vault markdown file should be written"

        content = md_files[0].read_text(encoding="utf-8")
        assert "---" in content, "YAML frontmatter delimiter missing"
        assert 'source: "questdb-reconcile"' in content
        assert 'kind: "daily-aggregate"' in content
        assert "overall_status:" in content
        assert "- questdb" in content
        assert "- reconciliation" in content
        assert "- daily-log" in content

    def test_snapshot_json_written(self, sqlite_db_with_data, monkeypatch, tmp_path):
        """JSON snapshot must be written alongside the markdown."""
        vault_dir = tmp_path / "vault"
        snap_dir = tmp_path / "snaps"
        monkeypatch.setattr(rq, "SNAPSHOT_DIR", snap_dir)
        monkeypatch.setattr(rq, "VAULT_RAW_DIR", vault_dir)

        questdb_ids = [str(i) for i in range(20)]
        mock_client = _make_mock_client(
            count_responses={"discord_bot_signals_ts": 20},
            id_responses={"discord_bot_signals_ts": questdb_ids},
        )

        import httpx

        class _FakeClientCtx:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return mock_client

            def __exit__(self, *a):
                pass

        monkeypatch.setattr(httpx, "Client", _FakeClientCtx)
        monkeypatch.setattr(
            rq,
            "TABLES",
            {"bot_signals": rq.TABLES["bot_signals"]},
        )

        rq.reconcile_all(sqlite_db_with_data, "http://mock:9000")

        snap_files = list(snap_dir.glob("*.json"))
        assert len(snap_files) == 1
        data = json.loads(snap_files[0].read_text())
        assert "overall_status" in data
        assert "tables" in data
        assert data["tables"][0]["table"] == "bot_signals"


class TestWilsonCI:
    """Unit tests for the Wilson score confidence interval helper."""

    def test_zero_missing(self):
        lo, hi = rq._wilson_ci(0, 1000)
        assert lo == pytest.approx(0.0, abs=1e-4)
        assert hi < 0.01

    def test_all_missing(self):
        lo, hi = rq._wilson_ci(1000, 1000)
        assert hi == pytest.approx(1.0, abs=1e-4)

    def test_zero_n(self):
        lo, hi = rq._wilson_ci(0, 0)
        assert lo == 0.0
        assert hi == 0.0

    def test_1pct_missing_1000_sample(self):
        # 1% missing from 1000-row sample: CI should bracket 1%
        lo, hi = rq._wilson_ci(10, 1000)
        assert lo < 0.01 < hi
