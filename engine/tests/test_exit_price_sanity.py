"""Tests for the close-path phantom-price guard (2026-06-15).

Covers three layers:
  1. The pure predicate ``check_exit_price_sanity`` / ``assert_exit_price_sane``.
  2. The wired guard in ``PortfolioTracker.close_trade`` (rejects a corrupt
     exit before any P&L write; leaves the position open — fail-closed).
  3. The ``reconcile_daily_pnl`` detective control that re-derives realized P&L
     from closed paper_trades and flags drift from the stored daily_pnl row.
"""

import sqlite3

import pytest

from risk.exit_price_sanity import (
    ExitPriceSanityError,
    assert_exit_price_sane,
    check_exit_price_sanity,
)

# ----------------------------- predicate ----------------------------------

def test_sane_exit_passes():
    ok, _ = check_exit_price_sanity("MES", entry_price=5200.0, exit_price=5235.0)
    assert ok is True


def test_nonfinite_and_nonpositive_rejected():
    for bad in (float("nan"), float("inf"), 0.0, -5.0):
        ok, reason = check_exit_price_sanity("MES", 5200.0, bad)
        assert ok is False, f"{bad} should reject"
        assert "non-finite" in reason or "non-positive" in reason


def test_wrong_era_deviation_rejected():
    # entry-era ~7530, exit comes in at a 5299-era price (~30% off) — the
    # 2026-06-15 phantom signature. Default 25% threshold rejects it.
    ok, reason = check_exit_price_sanity("MES", entry_price=7530.0, exit_price=5299.0)
    assert ok is False
    assert "deviates" in reason


def test_missing_entry_reference_does_not_block():
    ok, _ = check_exit_price_sanity("MES", entry_price=0.0, exit_price=5235.0)
    assert ok is True  # entry guard owns that failure mode; never block on missing ref


def test_threshold_is_env_tunable(monkeypatch):
    # A 30% move is rejected at default 25% but allowed when threshold raised to 50%.
    assert check_exit_price_sanity("MES", 7530.0, 5299.0)[0] is False
    monkeypatch.setenv("EXIT_PRICE_SANITY_MAX_DEVIATION_PCT", "0.50")
    assert check_exit_price_sanity("MES", 7530.0, 5299.0)[0] is True


def test_assert_raises_and_can_be_disabled(monkeypatch):
    with pytest.raises(ExitPriceSanityError):
        assert_exit_price_sane("MES", 7530.0, 5299.0)
    monkeypatch.setenv("ENABLE_EXIT_PRICE_SANITY", "0")
    assert_exit_price_sane("MES", 7530.0, 5299.0)  # no-op when disabled


# --------------------------- close-path wiring ----------------------------

def _make_tracker(tmp_path):
    from portfolio.tracker import PortfolioTracker

    return PortfolioTracker(store_path=tmp_path / "paper_trades.jsonl", db_manager=None)


def test_close_trade_rejects_phantom_exit(tmp_path):
    tracker = _make_tracker(tmp_path)
    tid = tracker.open_trade("MES", "buy", 1, 7530.0)
    with pytest.raises(ExitPriceSanityError):
        tracker.close_trade(tid, exit_price=5299.0)
    # Fail-closed: the position must still be open, no phantom close recorded.
    assert tid in tracker._open
    assert len(tracker._closed) == 0


def test_close_trade_accepts_sane_exit(tmp_path):
    tracker = _make_tracker(tmp_path)
    tid = tracker.open_trade("MES", "buy", 1, 7530.0)
    closed = tracker.close_trade(tid, exit_price=7560.0)
    assert closed.exit_price == 7560.0
    assert tid not in tracker._open


# --------------------------- reconciliation -------------------------------

def _insert_closed_trade(db_path, *, trade_id, symbol, exit_time, pnl):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO paper_trades
               (trade_id, symbol, side, quantity, entry_price, exit_price,
                entry_time, exit_time, pnl, status, idempotency_key)
               VALUES (?,?,?,?,?,?,?,?,?, 'closed', ?)""",
            (trade_id, symbol, "buy", 1, 100.0, 101.0,
             exit_time, exit_time, pnl, f"idem-{trade_id}"),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_daily_pnl(db_path, *, date, realized, total_trades):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO daily_pnl (date, starting_balance, ending_balance,
                realized_pnl, total_trades)
               VALUES (?, 100000, 100000, ?, ?)""",
            (date, realized, total_trades),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path):
    from database.schema import DatabaseManager

    mgr = DatabaseManager(str(tmp_path / "recon.db"))
    mgr.initialize()  # run migrations → creates paper_trades + daily_pnl
    return mgr


def test_reconciliation_clean_when_stored_matches_trades(db, tmp_path):
    path = str(tmp_path / "recon.db")
    _insert_closed_trade(path, trade_id="t1", symbol="MES", exit_time="2026-06-14T15:00:00", pnl=120.0)
    _insert_closed_trade(path, trade_id="t2", symbol="MES", exit_time="2026-06-14T16:00:00", pnl=-20.0)
    _insert_daily_pnl(path, date="2026-06-14", realized=100.0, total_trades=2)

    report = db.reconcile_daily_pnl()
    assert report["ok"] is True
    assert report["drift_count"] == 0
    assert report["total_recomputed_realized"] == 100.0


def test_reconciliation_flags_phantom_drift(db, tmp_path):
    path = str(tmp_path / "recon.db")
    # Trades really sum to +100, but the stored snapshot claims a phantom +40000.
    _insert_closed_trade(path, trade_id="t1", symbol="MES", exit_time="2026-06-14T15:00:00", pnl=100.0)
    _insert_daily_pnl(path, date="2026-06-14", realized=40000.0, total_trades=1)

    report = db.reconcile_daily_pnl()
    assert report["ok"] is False
    assert report["drift_count"] == 1
    drift = report["drifts"][0]
    assert drift["date"] == "2026-06-14"
    assert drift["recomputed_realized"] == 100.0
    assert drift["stored_realized"] == 40000.0
    assert drift["delta"] == pytest.approx(39900.0)
