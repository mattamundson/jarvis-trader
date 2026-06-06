"""Tests for Task 2 — approval-bottleneck observability.

Covers:
- TelegramNotifier chat_id validation (a bot username like 'HermesAmoBot' must
  flip config_valid False so silent HTTP-400 drops become loud).
- PendingApprovalsMixin.get_pending_approval_stats (count + oldest_created_at)
  used by /health to surface a stuck approval queue.
"""
import sqlite3
import threading
from types import SimpleNamespace

import pytest

import notifications.telegram as telegram_mod
from database._mixins_pending_approvals import PendingApprovalsMixin
from database.migrations import run_migrations

# --- TelegramNotifier chat_id validation ----------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        ("8676240038", True),
        ("-1001234567890", True),  # group/channel id
        (8676240038, True),
        ("HermesAmoBot", False),  # the live misconfiguration
        ("@HermesAmoBot", False),
        ("", False),
        (None, False),
        ("123abc", False),
    ],
)
def test_is_valid_chat_id(value, expected):
    assert telegram_mod.TelegramNotifier._is_valid_chat_id(value) is expected


def _make_notifier(monkeypatch, token, chat_id):
    monkeypatch.setattr(
        telegram_mod,
        "settings",
        SimpleNamespace(TELEGRAM_BOT_TOKEN=token, TELEGRAM_CHAT_ID=chat_id),
    )
    return telegram_mod.TelegramNotifier()


def test_config_valid_false_for_username(monkeypatch):
    n = _make_notifier(monkeypatch, "tok:123", "HermesAmoBot")
    assert n.enabled is True          # token+chat present -> "enabled"
    assert n.config_valid is False    # but the chat_id is unusable


def test_config_valid_true_for_numeric(monkeypatch):
    n = _make_notifier(monkeypatch, "tok:123", "8676240038")
    assert n.enabled is True
    assert n.config_valid is True


def test_config_valid_false_when_unconfigured(monkeypatch):
    n = _make_notifier(monkeypatch, "", "")
    assert n.enabled is False
    assert n.config_valid is False


# --- pending-approval stats aggregate -------------------------------------

class _StubDB(PendingApprovalsMixin):
    """Minimal host for the mixin — real SQL, no full DatabaseManager."""

    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._path = path

    def _connect(self):
        return sqlite3.connect(self._path)


def _seed_pending(path: str, rows):
    conn = sqlite3.connect(path)
    for approval_id, created_at, status in rows:
        conn.execute(
            """INSERT INTO pending_trade_approvals
               (approval_id, symbol, action, quantity, status,
                pipeline_snapshot_json, created_at)
               VALUES (?, 'MES', 'buy', 1, ?, '{}', ?)""",
            (approval_id, status, created_at),
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def migrated_db(tmp_path):
    path = str(tmp_path / "j.db")
    conn = sqlite3.connect(path)
    run_migrations(conn)
    conn.close()
    return path


def test_stats_empty(migrated_db):
    stats = _StubDB(migrated_db).get_pending_approval_stats()
    assert stats == {"count": 0, "oldest_created_at": None}


def test_stats_counts_only_pending(migrated_db):
    _seed_pending(
        migrated_db,
        [
            ("a", "2026-06-04T15:00:00+00:00", "pending"),
            ("b", "2026-06-04T14:00:00+00:00", "pending"),
            ("c", "2026-06-04T13:00:00+00:00", "approved"),  # excluded
        ],
    )
    stats = _StubDB(migrated_db).get_pending_approval_stats()
    assert stats["count"] == 2
    assert stats["oldest_created_at"] == "2026-06-04T14:00:00+00:00"  # MIN of pending
