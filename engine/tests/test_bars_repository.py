"""Tests for engine.data.bars_repository — save/load/latest_bar round-trips."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

# Make engine root importable when pytest runs from the engine directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.bars_repository import latest_bar, load_bars, save_bars

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Path:
    """Create a minimal SQLite DB with the market_data_bars table."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_bars (
            symbol      TEXT NOT NULL,
            interval    TEXT NOT NULL,
            ts_utc      TEXT NOT NULL,
            open        REAL NOT NULL,
            high        REAL NOT NULL,
            low         REAL NOT NULL,
            close       REAL NOT NULL,
            volume      REAL,
            source      TEXT NOT NULL,
            fetched_at  TEXT NOT NULL,
            PRIMARY KEY (symbol, interval, ts_utc)
        )
        """
    )
    conn.commit()
    conn.close()
    return db


def _stored_bar(db: Path, symbol: str, interval: str, ts_utc: str) -> dict:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM market_data_bars "
            "WHERE symbol=? AND interval=? AND ts_utc=?",
            (symbol, interval, ts_utc),
        ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def _one_bar(
    timestamp: datetime,
    *,
    close: float = 4038.0,
    volume: float | None = 3231.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "timestamp": timestamp,
            "open": 4034.0,
            "high": 4042.0,
            "low": 4030.0,
            "close": close,
            "volume": float("nan") if volume is None else volume,
        }]
    )


def _make_bars(n: int = 5, symbol: str = "MES", start_hour: int = 9) -> pd.DataFrame:
    rows = []
    for i in range(n):
        dt = datetime(2026, 5, 7, start_hour + i, 0, 0, tzinfo=timezone.utc)
        rows.append(
            {
                "timestamp": dt,
                "open": 5300.0 + i,
                "high": 5310.0 + i,
                "low": 5290.0 + i,
                "close": 5305.0 + i,
                "volume": 1000.0 + i * 10,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# test_save_then_load
# ---------------------------------------------------------------------------


def test_save_then_load(tmp_path):
    db = _make_db(tmp_path)
    df = _make_bars(5)
    saved = save_bars(df, "MES", "1h", "tv", db_path=db)
    assert saved == 5

    loaded = load_bars("MES", "1h", db_path=db)
    assert len(loaded) == 5
    assert list(loaded.columns) >= ["timestamp", "open", "high", "low", "close", "volume"]
    # Values round-trip correctly
    assert abs(float(loaded["close"].iloc[0]) - 5305.0) < 1e-6


# ---------------------------------------------------------------------------
# test_save_idempotent
# ---------------------------------------------------------------------------


def test_save_idempotent(tmp_path):
    db = _make_db(tmp_path)
    df = _make_bars(3)

    first = save_bars(df, "MES", "1h", "tv", db_path=db)
    second = save_bars(df, "MES", "1h", "ibkr", db_path=db)  # same ts, different source

    assert first == 3
    # Finalized duplicate rows are immutable and remain a no-op.
    assert second == 0

    loaded = load_bars("MES", "1h", db_path=db)
    assert len(loaded) == 3  # no duplicates


def test_newer_snapshot_refreshes_provisional_mgc_hour(monkeypatch, tmp_path):
    """A newer fetch may refine one still-forming bar without duplicating it."""
    from data import bars_repository

    db = _make_db(tmp_path)
    timestamp = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:31:00")
    assert save_bars(_one_bar(timestamp), "MGC", "1h", "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:40:00")
    revised = _one_bar(timestamp, close=4037.8, volume=3545.0)
    assert save_bars(revised, "MGC", "1h", "ibkr", db_path=db) == 1

    loaded = load_bars("MGC", "1h", db_path=db)
    assert len(loaded) == 1
    assert float(loaded.iloc[0]["close"]) == pytest.approx(4037.8)
    assert float(loaded.iloc[0]["volume"]) == pytest.approx(3545.0)


def test_finalized_hour_is_immutable(monkeypatch, tmp_path):
    """A row first fetched at bar end is final and cannot be rewritten."""
    from data import bars_repository

    db = _make_db(tmp_path)
    timestamp = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T21:00:00")
    assert save_bars(_one_bar(timestamp), "MGC", "1h", "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T21:05:00")
    revised = _one_bar(timestamp, close=4040.0, volume=4000.0)
    assert save_bars(revised, "MGC", "1h", "tv", db_path=db) == 0

    stored = _stored_bar(db, "MGC", "1h", "2026-10-22T20:00:00")
    assert stored["close"] == pytest.approx(4038.0)
    assert stored["volume"] == pytest.approx(3231.0)
    assert stored["source"] == "ibkr"
    assert stored["fetched_at"] == "2026-10-22T21:00:00"


def test_post_close_refresh_finalizes_then_freezes_hour(monkeypatch, tmp_path):
    """The first post-close revision finalizes a provisional row exactly once."""
    from data import bars_repository

    db = _make_db(tmp_path)
    timestamp = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:31:00")
    assert save_bars(_one_bar(timestamp), "MGC", "1h", "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T21:05:00")
    finalized = _one_bar(timestamp, close=4037.8, volume=3545.0)
    assert save_bars(finalized, "MGC", "1h", "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T21:10:00")
    late_conflict = _one_bar(timestamp, close=4040.0, volume=4000.0)
    assert save_bars(late_conflict, "MGC", "1h", "tv", db_path=db) == 0

    stored = _stored_bar(db, "MGC", "1h", "2026-10-22T20:00:00")
    assert stored["close"] == pytest.approx(4037.8)
    assert stored["volume"] == pytest.approx(3545.0)
    assert stored["source"] == "ibkr"
    assert stored["fetched_at"] == "2026-10-22T21:05:00"


def test_identical_post_close_snapshot_finalizes_hour(monkeypatch, tmp_path):
    """A post-close confirmation freezes the row even when OHLCV is unchanged."""
    from data import bars_repository

    db = _make_db(tmp_path)
    timestamp = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:31:00")
    assert save_bars(_one_bar(timestamp), "MGC", "1h", "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T21:05:00")
    assert save_bars(_one_bar(timestamp), "MGC", "1h", "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T21:10:00")
    late_conflict = _one_bar(timestamp, close=4040.0, volume=4000.0)
    assert save_bars(late_conflict, "MGC", "1h", "tv", db_path=db) == 0

    stored = _stored_bar(db, "MGC", "1h", "2026-10-22T20:00:00")
    assert stored["close"] == pytest.approx(4038.0)
    assert stored["volume"] == pytest.approx(3231.0)
    assert stored["fetched_at"] == "2026-10-22T21:05:00"


def test_older_snapshot_cannot_replace_newer_provisional_snapshot(monkeypatch, tmp_path):
    from data import bars_repository

    db = _make_db(tmp_path)
    timestamp = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:45:00")
    newer = _one_bar(timestamp, close=4037.8, volume=3545.0)
    assert save_bars(newer, "MGC", "1h", "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:30:00")
    assert save_bars(_one_bar(timestamp), "MGC", "1h", "tv", db_path=db) == 0

    stored = _stored_bar(db, "MGC", "1h", "2026-10-22T20:00:00")
    assert stored["close"] == pytest.approx(4037.8)
    assert stored["volume"] == pytest.approx(3545.0)
    assert stored["fetched_at"] == "2026-10-22T20:45:00"


def test_identical_provisional_repeat_is_noop(monkeypatch, tmp_path):
    from data import bars_repository

    db = _make_db(tmp_path)
    timestamp = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:31:00")
    assert save_bars(_one_bar(timestamp), "MGC", "1h", "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:40:00")
    assert save_bars(_one_bar(timestamp), "MGC", "1h", "ibkr", db_path=db) == 0

    stored = _stored_bar(db, "MGC", "1h", "2026-10-22T20:00:00")
    assert stored["fetched_at"] == "2026-10-22T20:31:00"


def test_null_volume_refresh_preserves_known_volume(monkeypatch, tmp_path):
    from data import bars_repository

    db = _make_db(tmp_path)
    timestamp = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:31:00")
    assert save_bars(_one_bar(timestamp), "MGC", "1h", "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:40:00")
    no_volume = _one_bar(timestamp, close=4037.8, volume=None)
    assert save_bars(no_volume, "MGC", "1h", "ibkr", db_path=db) == 1

    stored = _stored_bar(db, "MGC", "1h", "2026-10-22T20:00:00")
    assert stored["close"] == pytest.approx(4037.8)
    assert stored["volume"] == pytest.approx(3231.0)


@pytest.mark.parametrize("interval", ["5m", "2h"])
def test_non_refreshable_interval_conflicts_remain_insert_ignore(
    interval, monkeypatch, tmp_path
):
    from data import bars_repository

    db = _make_db(tmp_path)
    timestamp = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:31:00")
    assert save_bars(_one_bar(timestamp), "MGC", interval, "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:40:00")
    revised = _one_bar(timestamp, close=4037.8, volume=3545.0)
    assert save_bars(revised, "MGC", interval, "ibkr", db_path=db) == 0

    stored = _stored_bar(db, "MGC", interval, "2026-10-22T20:00:00")
    assert stored["close"] == pytest.approx(4038.0)
    assert stored["volume"] == pytest.approx(3231.0)


def test_mixed_batch_refreshes_only_provisional_hour(monkeypatch, tmp_path):
    from data import bars_repository

    db = _make_db(tmp_path)
    finalized_ts = datetime(2026, 10, 22, 19, tzinfo=timezone.utc)
    provisional_ts = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:05:00")
    assert save_bars(_one_bar(finalized_ts), "MGC", "1h", "ibkr", db_path=db) == 1

    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:31:00")
    assert save_bars(_one_bar(provisional_ts), "MGC", "1h", "ibkr", db_path=db) == 1

    revised_batch = pd.concat(
        [
            _one_bar(finalized_ts, close=4040.0, volume=4000.0),
            _one_bar(provisional_ts, close=4037.8, volume=3545.0),
        ],
        ignore_index=True,
    )
    monkeypatch.setattr(bars_repository, "_utcnow_iso", lambda: "2026-10-22T20:40:00")
    assert save_bars(revised_batch, "MGC", "1h", "ibkr", db_path=db) == 1

    finalized = _stored_bar(db, "MGC", "1h", "2026-10-22T19:00:00")
    provisional = _stored_bar(db, "MGC", "1h", "2026-10-22T20:00:00")
    assert finalized["close"] == pytest.approx(4038.0)
    assert finalized["volume"] == pytest.approx(3231.0)
    assert provisional["close"] == pytest.approx(4037.8)
    assert provisional["volume"] == pytest.approx(3545.0)


# ---------------------------------------------------------------------------
# test_save_bars_converts_non_utc_tz_aware_timestamps
# ---------------------------------------------------------------------------


def test_save_bars_converts_non_utc_tz_aware_timestamps(tmp_path):
    """A tz-aware timestamp NOT already in UTC (e.g. IB's CME bars tagged
    US/Central) must be converted to true UTC before storage, not have its
    local wall-clock value printed verbatim into ts_utc.

    Regression for: every futures bar looked ~5-6h "stale" (fetched_at fresh,
    ts_utc chronically behind) because strftime() on a tz-aware-but-non-UTC
    timestamp silently keeps that zone's local time.
    """
    db = _make_db(tmp_path)
    central_ts = pd.Timestamp("2026-07-15 06:25:00", tz="US/Central")
    df = pd.DataFrame([{
        "timestamp": central_ts,
        "open": 7600.0,
        "high": 7603.0,
        "low": 7599.0,
        "close": 7601.0,
        "volume": 400.0,
    }])

    saved = save_bars(df, "MES", "5m", "ibkr", db_path=db)
    assert saved == 1

    bar = latest_bar("MES", "5m", db_path=db)
    assert bar is not None
    # US/Central is UTC-5 in July (CDT) -> 06:25 CDT == 11:25 UTC.
    # A bug that skips tz_convert would store "2026-07-15T06:25:00" instead.
    assert str(bar["timestamp"]).startswith("2026-07-15T11:25:00")


# ---------------------------------------------------------------------------
# test_latest_bar_returns_most_recent
# ---------------------------------------------------------------------------


def test_latest_bar_returns_most_recent(tmp_path):
    db = _make_db(tmp_path)
    df = _make_bars(4)
    save_bars(df, "MES", "1h", "ibkr", db_path=db)

    bar = latest_bar("MES", "1h", db_path=db)
    assert bar is not None
    # Most recent bar is the last one (start_hour=9, n=4 → ts = 12:00)
    assert "12:00:00" in bar["timestamp"]
    assert abs(float(bar["close"]) - 5308.0) < 1e-6


# ---------------------------------------------------------------------------
# test_save_bars_skips_empty_df
# ---------------------------------------------------------------------------


def test_save_bars_skips_empty_df(tmp_path):
    db = _make_db(tmp_path)
    result = save_bars(pd.DataFrame(), "MES", "1h", "tv", db_path=db)
    assert result == 0

    result_none = save_bars(None, "MES", "1h", "tv", db_path=db)  # type: ignore[arg-type]
    assert result_none == 0

    loaded = load_bars("MES", "1h", db_path=db)
    assert loaded.empty


# ---------------------------------------------------------------------------
# test_default_db_path_is_isolated_from_production
# ---------------------------------------------------------------------------


def test_default_db_path_is_isolated_from_production():
    """Regression guard for the 2026-06 bar-store contamination.

    The autouse _isolate_bars_db fixture must redirect the repository's
    default DB away from engine/data/jarvis_trader.db for every test, so a
    save_bars(db_path=None) call can never write fixture bars into the
    production table again.
    """
    import sqlite3

    from data import bars_repository

    default = Path(bars_repository._DEFAULT_DB_PATH)
    assert "jarvis_trader.db" not in default.name, (
        "tests must never default to the production bar store"
    )

    # A default-path write must land in the redirected location, not prod.
    conn = sqlite3.connect(str(default))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_bars (
            symbol TEXT, interval TEXT, ts_utc TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            source TEXT, fetched_at TEXT,
            UNIQUE(symbol, interval, ts_utc)
        )
        """
    )
    conn.commit()
    conn.close()

    df = pd.DataFrame(
        {
            "timestamp": [datetime(2026, 1, 1, 9, tzinfo=timezone.utc)],
            "open": [100.0],
            "high": [100.5],
            "low": [99.5],
            "close": [100.5],
            "volume": [1.0],
        }
    )
    inserted = save_bars(df, "MCL", "1h", "smoke_test")  # db_path=None on purpose
    assert inserted == 1

    loaded = load_bars("MCL", "1h")  # default path again
    assert len(loaded) == 1


# ---------------------------------------------------------------------------
# Write-time sanity gate (2026-06 contamination regression guards)
# ---------------------------------------------------------------------------


class TestSaveBarsSanityGate:
    """save_bars must refuse the exact row shapes that poisoned the bar store."""

    def test_rejects_ib_snapshot_sentinel_flat_bars(self, tmp_path):
        """O=H=L=C=100.5 flat bars (IB snapshot init) must never be written."""
        db = _make_db(tmp_path)
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2026, 6, 1, 9, tzinfo=timezone.utc)],
                "open": [100.5],
                "high": [100.5],
                "low": [100.5],
                "close": [100.5],
                "volume": [0.0],
            }
        )
        assert save_bars(df, "MCL", "1h", "ibkr", db_path=db) == 0
        assert load_bars("MCL", "1h", db_path=db).empty

    def test_rejects_out_of_band_price_for_symbol(self, tmp_path):
        """An MES bar at ~100 (placeholder scale) is outside the plausible band."""
        db = _make_db(tmp_path)
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2026, 6, 1, 9, tzinfo=timezone.utc)],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [10.0],
            }
        )
        assert save_bars(df, "MES", "1h", "tv", db_path=db) == 0
        assert load_bars("MES", "1h", db_path=db).empty

    def test_rejects_absurd_jump_vs_persisted_history(self, tmp_path):
        """A >50% close-to-close jump vs the latest persisted bar is a bad tick."""
        db = _make_db(tmp_path)
        save_bars(_make_bars(3), "MES", "1h", "tv", db_path=db)  # closes ~5305-5307

        df = pd.DataFrame(
            {
                "timestamp": [datetime(2026, 5, 7, 13, 0, tzinfo=timezone.utc)],
                "open": [900.0],
                "high": [905.0],
                "low": [895.0],
                "close": [900.0],  # -83% vs 5307 — absurd, but inside the MES band? No: band floor 500, 900 is inside — only the jump check catches it
                "volume": [10.0],
            }
        )
        assert save_bars(df, "MES", "1h", "ibkr", db_path=db) == 0
        assert len(load_bars("MES", "1h", db_path=db)) == 3

    def test_rejects_mid_batch_jump_but_keeps_sane_rows(self, tmp_path):
        """One poisoned row inside a batch is dropped; its neighbours are kept."""
        db = _make_db(tmp_path)
        rows = []
        for i, close in enumerate([5300.0, 5305.0, 900.0, 5310.0]):
            dt = datetime(2026, 5, 7, 9 + i, 0, tzinfo=timezone.utc)
            rows.append(
                {
                    "timestamp": dt,
                    "open": close,
                    "high": close + 5,
                    "low": close - 5,
                    "close": close,
                    "volume": 10.0,
                }
            )
        saved = save_bars(pd.DataFrame(rows), "MES", "1h", "tv", db_path=db)
        assert saved == 3
        loaded = load_bars("MES", "1h", db_path=db)
        assert len(loaded) == 3
        assert 900.0 not in set(loaded["close"].tolist())

    def test_rejects_incoherent_ohlc(self, tmp_path):
        """high < low or close outside [low, high] is structurally invalid."""
        db = _make_db(tmp_path)
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2026, 6, 1, 9, tzinfo=timezone.utc)],
                "open": [5300.0],
                "high": [5290.0],  # high < low
                "low": [5310.0],
                "close": [5305.0],
                "volume": [10.0],
            }
        )
        assert save_bars(df, "MES", "1h", "tv", db_path=db) == 0

    def test_rejects_nonpositive_prices(self, tmp_path):
        db = _make_db(tmp_path)
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2026, 6, 1, 9, tzinfo=timezone.utc)],
                "open": [0.0],
                "high": [0.0],
                "low": [0.0],
                "close": [0.0],
                "volume": [0.0],
            }
        )
        assert save_bars(df, "MGC", "1h", "ibkr", db_path=db) == 0

    def test_accepts_normal_consecutive_appends(self, tmp_path):
        """Sane bars keep flowing — the gate must not block real data."""
        db = _make_db(tmp_path)
        assert save_bars(_make_bars(5), "MES", "1h", "tv", db_path=db) == 5

        nxt = pd.DataFrame(
            {
                "timestamp": [datetime(2026, 5, 7, 14, 0, tzinfo=timezone.utc)],
                "open": [5310.0],
                "high": [5320.0],
                "low": [5300.0],
                "close": [5315.0],
                "volume": [900.0],
            }
        )
        assert save_bars(nxt, "MES", "1h", "ibkr", db_path=db) == 1
        assert len(load_bars("MES", "1h", db_path=db)) == 6

    def test_unknown_symbol_gets_generic_checks_only(self, tmp_path):
        """Symbols without a band still pass coherent rows and fail sentinels."""
        db = _make_db(tmp_path)
        ok = pd.DataFrame(
            {
                "timestamp": [datetime(2026, 6, 1, 9, tzinfo=timezone.utc)],
                "open": [42.0],
                "high": [43.0],
                "low": [41.0],
                "close": [42.5],
                "volume": [1.0],
            }
        )
        assert save_bars(ok, "ZW", "1h", "tv", db_path=db) == 1
