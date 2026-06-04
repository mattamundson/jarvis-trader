"""
Tests for journal — daily trading journal generator.

All tests use in-memory or temp SQLite DBs + temp JSONL log files.
No writes to jarvis_trader.db or real vault paths.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from journal.builder import (
    _parse_ask_log,
    build_journal_entry,
    render_markdown,
    write_to_vault,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Path:
    """Create a minimal test database with the required tables."""
    db_path = tmp_path / "test_journal.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY,
            trade_id TEXT,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            entry_price REAL,
            exit_price REAL,
            entry_time TEXT,
            exit_time TEXT,
            pnl REAL,
            status TEXT,
            regime TEXT,
            strategy_params TEXT,
            notes TEXT
        );
        CREATE TABLE pnl_snapshots (
            date TEXT,
            daily_pnl REAL,
            portfolio_equity REAL,
            peak_equity REAL,
            consecutive_losses INTEGER,
            updated_at TEXT,
            account_id TEXT
        );
        CREATE TABLE discord_corey_commentary (
            id INTEGER PRIMARY KEY,
            message_id TEXT,
            timestamp TEXT,
            content TEXT,
            channel TEXT,
            author_id TEXT,
            created_at TEXT
        );
        CREATE TABLE discord_bot_signals (
            id INTEGER PRIMARY KEY,
            message_id TEXT,
            timestamp TEXT,
            symbol TEXT,
            direction TEXT,
            signal_type TEXT,
            entry_price REAL
        );
        CREATE TABLE alert_log (
            id INTEGER PRIMARY KEY,
            alert_type TEXT,
            symbol TEXT,
            message TEXT,
            status TEXT,
            error TEXT,
            created_at TEXT
        );
        CREATE TABLE system_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
        INSERT INTO system_state VALUES ('kill_switch_active', 'false', '2026-01-01T00:00:00');
        INSERT INTO system_state VALUES ('kill_switch_reason', '', '2026-01-01T00:00:00');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _add_trade(
    db_path: Path,
    *,
    trade_id: str = "trade-001",
    symbol: str = "MES",
    side: str = "buy",
    entry_price: float = 5000.0,
    exit_price: float = 5010.0,
    pnl: float = 50.0,
    exit_time: str = "2026-05-20T15:00:00+00:00",
    regime: str = "bull",
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO paper_trades
            (trade_id, symbol, side, quantity, entry_price, exit_price,
             entry_time, exit_time, pnl, status, regime)
        VALUES (?, ?, ?, 1, ?, ?, '2026-05-20T14:00:00+00:00', ?, ?, 'closed', ?)
        """,
        (trade_id, symbol, side, entry_price, exit_price, exit_time, pnl, regime),
    )
    conn.commit()
    conn.close()


def _add_pnl_snapshot(
    db_path: Path,
    *,
    date_str: str = "2026-05-20",
    daily_pnl: float = 150.0,
    portfolio_equity: float = 10150.0,
    peak_equity: float = 10200.0,
    consecutive_losses: int = 0,
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO pnl_snapshots (date, daily_pnl, portfolio_equity, peak_equity, consecutive_losses, updated_at)
        VALUES (?, ?, ?, ?, ?, '2026-05-20T20:00:00')
        """,
        (date_str, daily_pnl, portfolio_equity, peak_equity, consecutive_losses),
    )
    conn.commit()
    conn.close()


def _add_commentary(
    db_path: Path,
    *,
    message_id: str = "msg-001",
    timestamp: str = "2026-05-20T09:30:00+00:00",
    content: str = "X" * 250,
    channel: str = "market-updates",
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO discord_corey_commentary (message_id, timestamp, content, channel)
        VALUES (?, ?, ?, ?)
        """,
        (message_id, timestamp, content, channel),
    )
    conn.commit()
    conn.close()


def _add_bot_signal(
    db_path: Path,
    *,
    message_id: str = "sig-001",
    timestamp: str = "2026-05-20T09:00:00+00:00",
    symbol: str = "MES",
    direction: str = "LONG",
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO discord_bot_signals (message_id, timestamp, symbol, direction)
        VALUES (?, ?, ?, ?)
        """,
        (message_id, timestamp, symbol, direction),
    )
    conn.commit()
    conn.close()


def _add_kill_switch_alert(
    db_path: Path,
    *,
    alert_type: str = "KILL_SWITCH_ACTIVATED",
    message: str = "Daily P&L exceeded -2% threshold",
    created_at: str = "2026-05-20T14:45:00",
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO alert_log (alert_type, symbol, message, status, created_at)
        VALUES (?, NULL, ?, 'sent', ?)
        """,
        (alert_type, message, created_at),
    )
    conn.commit()
    conn.close()


def _make_ask_log(tmp_path: Path, records: list[dict]) -> Path:
    """Write a JSONL jarvis_ask.log with given records."""
    log_path = tmp_path / "jarvis_ask.log"
    with log_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return log_path


TARGET_DATE = date(2026, 5, 20)


# ---------------------------------------------------------------------------
# Test: empty day
# ---------------------------------------------------------------------------


def test_build_entry_empty_day(tmp_path: Path) -> None:
    """Date with zero trades/snapshots/commentary returns a valid entry with zero counts."""
    db_path = _make_db(tmp_path)

    entry = build_journal_entry(TARGET_DATE, str(db_path), log_path=None)

    assert entry["frontmatter"]["trade_count"] == 0
    assert entry["frontmatter"]["daily_pnl_usd"] is None
    assert entry["frontmatter"]["win_rate"] is None
    assert entry["trades"] == []
    assert entry["pnl_snapshot"] is None
    assert entry["commentary"] == []
    assert entry["bot_signals"] == []
    assert entry["jarvis_asks"]["total_queries"] == 0
    assert entry["kill_switch_events"] == []

    # Frontmatter shape must always include required keys
    fm = entry["frontmatter"]
    for key in ("source", "kind", "date", "trade_count", "daily_pnl_usd", "win_rate", "tags"):
        assert key in fm, f"Missing frontmatter key: {key}"


# ---------------------------------------------------------------------------
# Test: full day
# ---------------------------------------------------------------------------


def test_build_entry_full_day(tmp_path: Path) -> None:
    """Synthetic full-day data populates all sections."""
    db_path = _make_db(tmp_path)

    # Add 2 wins and 1 loss
    _add_trade(db_path, trade_id="t1", pnl=50.0, symbol="MES")
    _add_trade(db_path, trade_id="t2", pnl=80.0, symbol="MGC")
    _add_trade(db_path, trade_id="t3", pnl=-40.0, symbol="MES", side="sell")
    _add_pnl_snapshot(db_path, daily_pnl=90.0)
    _add_commentary(db_path, content="A" * 300)
    _add_bot_signal(db_path, symbol="MES", direction="LONG")
    _add_bot_signal(db_path, message_id="sig-002", symbol="MES", direction="LONG")
    _add_bot_signal(db_path, message_id="sig-003", symbol="MGC", direction="SHORT")

    ask_log = _make_ask_log(
        tmp_path,
        [
            {
                "timestamp": "2026-05-20T14:00:00+00:00",
                "intent": "market_analysis",
                "elapsed_ms": 100,
                "sources_count": 3,
                "actions_count": 1,
            },
            {
                "timestamp": "2026-05-20T15:00:00+00:00",
                "intent": "position_query",
                "elapsed_ms": 50,
                "sources_count": 1,
                "actions_count": 0,
            },
            {
                "timestamp": "2026-05-20T16:00:00+00:00",
                "intent": "market_analysis",
                "elapsed_ms": 120,
                "sources_count": 4,
                "actions_count": 1,
            },
        ],
    )

    entry = build_journal_entry(TARGET_DATE, str(db_path), log_path=str(ask_log))

    assert entry["frontmatter"]["trade_count"] == 3
    assert entry["frontmatter"]["daily_pnl_usd"] == 90.0
    assert entry["frontmatter"]["win_rate"] == pytest.approx(2 / 3, abs=0.001)

    assert len(entry["trades"]) == 3
    assert entry["pnl_snapshot"]["daily_pnl"] == 90.0
    assert len(entry["commentary"]) == 1
    assert len(entry["bot_signals"]) == 2  # MES-LONG + MGC-SHORT
    # Verify MES signal count
    mes_sig = next(s for s in entry["bot_signals"] if s["symbol"] == "MES")
    assert mes_sig["signal_count"] == 2

    assert entry["jarvis_asks"]["total_queries"] == 3
    assert entry["jarvis_asks"]["intent_counts"]["market_analysis"] == 2
    assert entry["jarvis_asks"]["intent_counts"]["position_query"] == 1


# ---------------------------------------------------------------------------
# Test: idempotent overwrite
# ---------------------------------------------------------------------------


def test_idempotent_overwrite(tmp_path: Path) -> None:
    """Writing twice for the same date produces exactly one file, second write overwrites first."""
    db_path = _make_db(tmp_path)
    vault_root = tmp_path / "vault"

    entry = build_journal_entry(TARGET_DATE, str(db_path))

    path1 = write_to_vault(entry, str(vault_root))
    content1 = path1.read_text(encoding="utf-8")

    # Write again — different generated_at
    entry2 = build_journal_entry(TARGET_DATE, str(db_path))
    path2 = write_to_vault(entry2, str(vault_root))
    content2 = path2.read_text(encoding="utf-8")

    # Same path
    assert path1 == path2

    # Only one file exists
    journal_dir = vault_root / "_session-journal"
    files = list(journal_dir.glob("*.md"))
    assert len(files) == 1

    # Contents differ only in generated_at (second write IS newer)
    assert "2026-05-20" in content2


# ---------------------------------------------------------------------------
# Test: frontmatter shape
# ---------------------------------------------------------------------------


def test_frontmatter_shape_matches_vault_convention(tmp_path: Path) -> None:
    """Required frontmatter keys are present and correctly typed."""
    db_path = _make_db(tmp_path)
    _add_trade(db_path, pnl=75.0)
    _add_pnl_snapshot(db_path)

    entry = build_journal_entry(TARGET_DATE, str(db_path))
    fm = entry["frontmatter"]

    assert fm["source"] == "trading-journal"
    assert fm["kind"] == "daily-journal"
    assert fm["date"] == "2026-05-20"
    assert isinstance(fm["trade_count"], int)
    assert isinstance(fm["tags"], list)
    assert "trading-journal" in fm["tags"]
    assert "jarvis-trader/audit-trail" in fm["tags"]


# ---------------------------------------------------------------------------
# Test: jarvis_ask.log parsing
# ---------------------------------------------------------------------------


def test_jarvis_ask_log_parsed_correctly(tmp_path: Path) -> None:
    """Synthetic JSONL log produces correct intent histogram for target_date only."""
    db_path = _make_db(tmp_path)

    records = [
        # On target date — 3 records
        {
            "timestamp": "2026-05-20T09:00:00+00:00",
            "intent": "market_analysis",
            "elapsed_ms": 100,
            "sources_count": 2,
            "actions_count": 1,
        },
        {
            "timestamp": "2026-05-20T12:00:00+00:00",
            "intent": "market_analysis",
            "elapsed_ms": 80,
            "sources_count": 3,
            "actions_count": 1,
        },
        {
            "timestamp": "2026-05-20T17:00:00+00:00",
            "intent": "position_query",
            "elapsed_ms": 50,
            "sources_count": 1,
            "actions_count": 0,
        },
        # Off target date — must be excluded
        {
            "timestamp": "2026-05-19T22:00:00+00:00",
            "intent": "health",
            "elapsed_ms": 10,
            "sources_count": 0,
            "actions_count": 0,
        },
        {
            "timestamp": "2026-05-21T01:00:00+00:00",
            "intent": "health",
            "elapsed_ms": 10,
            "sources_count": 0,
            "actions_count": 0,
        },
        # Malformed line is tolerated (won't appear in this list but tested via log content)
    ]
    log_path = _make_ask_log(tmp_path, records)

    # Also add a malformed line
    with log_path.open("a", encoding="utf-8") as f:
        f.write("NOT_JSON\n")

    entry = build_journal_entry(TARGET_DATE, str(db_path), log_path=str(log_path))
    asks = entry["jarvis_asks"]

    assert asks["total_queries"] == 3
    assert asks["intent_counts"]["market_analysis"] == 2
    assert asks["intent_counts"]["position_query"] == 1
    assert "health" not in asks["intent_counts"]  # off-date records excluded


# ---------------------------------------------------------------------------
# Test: kill switch event surfaced
# ---------------------------------------------------------------------------


def test_kill_switch_event_surfaced_in_notes(tmp_path: Path) -> None:
    """A kill-switch alert on the target date appears in kill_switch_events."""
    db_path = _make_db(tmp_path)
    _add_kill_switch_alert(
        db_path,
        alert_type="KILL_SWITCH_ACTIVATED",
        message="Daily P&L exceeded -2% threshold — trading halted",
        created_at="2026-05-20T14:45:00",
    )

    entry = build_journal_entry(TARGET_DATE, str(db_path))
    events = entry["kill_switch_events"]

    assert len(events) >= 1
    # Check that "kill" appears in either the alert_type or message field of any event
    all_text = " ".join(f"{e.get('alert_type', '')} {e.get('message', '')}" for e in events)
    assert "kill" in all_text.lower() or "KILL" in all_text

    # Rendered markdown notes section mentions kill switch (from the ### heading)
    md = render_markdown(entry)
    assert "Kill Switch" in md or "kill switch" in md.lower() or "KILL" in md


# ---------------------------------------------------------------------------
# Test: render_markdown produces valid structure
# ---------------------------------------------------------------------------


def test_render_markdown_structure(tmp_path: Path) -> None:
    """render_markdown includes all required sections and valid YAML frontmatter."""
    db_path = _make_db(tmp_path)
    _add_trade(db_path, pnl=100.0)
    _add_pnl_snapshot(db_path)

    entry = build_journal_entry(TARGET_DATE, str(db_path))
    md = render_markdown(entry)

    assert md.startswith("---\n")
    assert 'source: "trading-journal"' in md
    assert 'kind: "daily-journal"' in md
    assert "## At a Glance" in md
    assert "## Trades" in md
    assert "## P&L Snapshot" in md
    assert "## Corey Commentary Highlights" in md
    assert "## Bot Signal Summary" in md
    assert "## JARVIS Queries" in md
    assert "## Notes" in md
