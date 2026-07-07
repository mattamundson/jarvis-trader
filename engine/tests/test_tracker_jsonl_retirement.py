"""US-1703: retire the deprecated JSONL write+replay when SQLite is active.

When a db_manager is present, SQLite is the sole source of truth: the tracker
must NOT append new trades to portfolio/trades.jsonl, and must NOT replay that
(uncurated, phantom-accreting) jsonl on startup. The jsonl path stays live ONLY
in the no-DB fallback mode. These tests pin both branches.

Regression context: the raw jsonl carried no status field, so it never reflected
DB-layer curation (duplicate cancellation, contaminated-row voiding, phantom
voids) and accreted an unbounded superset that surfaced a phantom MES
"+$30,918 / 43 open" book on 2026-06-16.
"""

from __future__ import annotations

from pathlib import Path

from portfolio.tracker import PaperTrade, PortfolioTracker


def _trade(trade_id: str, *, symbol: str = "MES", entry_price: float = 5300.0, is_open: bool = True) -> PaperTrade:
    return PaperTrade(
        trade_id=trade_id,
        symbol=symbol,
        action="buy",
        quantity=1.0,
        entry_price=entry_price,
        entry_time="2026-06-17T00:00:00+00:00",
        is_open=is_open,
    )


# --------------------------------------------------------------------------- #
# Write path — _append_record                                                 #
# --------------------------------------------------------------------------- #


def test_append_record_skips_jsonl_when_db_active(tmp_path: Path):
    """With a db_manager present, _append_record writes nothing to the jsonl."""
    store = tmp_path / "trades.jsonl"
    tracker = PortfolioTracker(store_path=store, db_manager=None)
    tracker._db = object()  # simulate an active SQLite store

    tracker._append_record(_trade("t1"))

    assert (not store.exists()) or store.read_text(encoding="utf-8").strip() == ""


def test_append_record_writes_jsonl_when_no_db(tmp_path: Path):
    """Fallback mode (no db_manager) still writes the jsonl audit log."""
    store = tmp_path / "trades.jsonl"
    tracker = PortfolioTracker(store_path=store, db_manager=None)

    tracker._append_record(_trade("t1", symbol="MGC"))

    assert store.exists()
    body = store.read_text(encoding="utf-8")
    assert "MGC" in body and "t1" in body


# --------------------------------------------------------------------------- #
# Replay path — _load_history                                                 #
# --------------------------------------------------------------------------- #


def test_load_history_skipped_when_db_active(tmp_path: Path):
    """A contaminated jsonl on disk must NOT be replayed into memory when the
    DB is the authoritative store — proves the phantom-open resurrection path
    is closed."""
    store = tmp_path / "trades.jsonl"
    # A phantom open row of the exact class that contaminated the live store.
    store.write_text(
        '{"trade_id":"phantom1","symbol":"MES","action":"buy","quantity":1.0,'
        '"entry_price":70.57,"entry_time":"2026-04-10T00:00:00+00:00","is_open":true}\n',
        encoding="utf-8",
    )

    # No-db tracker WOULD replay it (sanity — confirms the fixture is live).
    nodb = PortfolioTracker(store_path=store, db_manager=None)
    assert "phantom1" in nodb._open

    # DB-active branch: re-running replay must skip the jsonl entirely.
    nodb._db = object()
    nodb._open.clear()
    nodb._closed.clear()
    nodb._load_history()
    assert nodb._open == {}
    assert nodb._closed == []


def test_load_history_replays_when_no_db(tmp_path: Path):
    """Fallback mode still replays the jsonl on startup."""
    store = tmp_path / "trades.jsonl"
    store.write_text(
        '{"trade_id":"open1","symbol":"MGC","action":"buy","quantity":2.0,'
        '"entry_price":4311.1,"entry_time":"2026-06-16T00:00:00+00:00","is_open":true}\n',
        encoding="utf-8",
    )
    tracker = PortfolioTracker(store_path=store, db_manager=None)
    assert "open1" in tracker._open
