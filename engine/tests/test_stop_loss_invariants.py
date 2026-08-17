"""
Stop-loss directional invariants.

Long positions must have stop_loss < entry_price.
Short positions must have stop_loss > entry_price.

Background: 2026-04-09 incident report flagged an MCL paper position with
stop_loss above entry on a long trade — guaranteed loss on any normal tick.
2026-04-16 audit found zero inverted stops in current SQLite (10 trades) or
JSONL (45 trades) records, so no live data fix is needed. These tests act as
a regression net so the bug can't silently return.

The invariant itself now lives in ``engine/utils/trade_invariants.py`` so
production DB-write guards and these tests share one definition. See
``docs/incident-notes/2026-04-09-mcl-inverted-stop.md`` for the full audit.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ENGINE_DIR / "data" / "jarvis_trader.db"
JSONL_PATH = ENGINE_DIR / "portfolio" / "trades.jsonl"

# Make ``engine`` imports resolvable when tests are run with pytest from repo root
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from utils.trade_invariants import is_inverted_stop as _is_inverted  # noqa: E402


@pytest.mark.skipif(not DB_PATH.exists(), reason="paper_trades DB not present in CI env")
def test_no_inverted_stops_in_sqlite():
    """Every persisted paper trade must have a directionally-correct stop."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT trade_id, symbol, side, entry_price, stop_loss "
            "FROM paper_trades "
            "WHERE stop_loss IS NOT NULL AND entry_price IS NOT NULL"
        )
        violations: list[tuple] = [
            row for row in cur.fetchall() if _is_inverted(row[2], row[3], row[4])
        ]
    finally:
        conn.close()
    assert not violations, (
        f"{len(violations)} inverted stop(s) found in paper_trades. "
        f"First few: {violations[:5]}. "
        "This is the 2026-04-09 MCL incident regressing — investigate "
        "stop-calculation path in composite_signals.py / paper_runner.py."
    )


@pytest.mark.skipif(not JSONL_PATH.exists(), reason="trades.jsonl not present in CI env")
def test_no_inverted_stops_in_jsonl():
    """Same invariant for the JSONL append-only trade log."""
    violations: list[dict] = []
    with open(JSONL_PATH, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            side = rec.get("side") or rec.get("action")
            if _is_inverted(side, rec.get("entry_price"), rec.get("stop_loss")):
                violations.append({"line": lineno, **rec})
    assert not violations, (
        f"{len(violations)} inverted stop(s) in trades.jsonl. "
        f"First: {violations[0] if violations else None}"
    )


class TestStopLossInvariantHelper:
    """Unit tests for the helper itself — make sure it doesn't have its own bug."""

    @pytest.mark.parametrize(
        "side,entry,stop",
        [
            ("buy", 100.0, 95.0),  # long stop below — correct
            ("long", 50.0, 49.0),
            ("sell", 100.0, 105.0),  # short stop above — correct
            ("short", 50.0, 51.0),
            ("buy", 100.0, None),  # missing data — not inverted
            (None, 100.0, 95.0),
        ],
    )
    def test_helper_accepts_valid_or_missing(self, side, entry, stop):
        assert not _is_inverted(side, entry, stop)

    @pytest.mark.parametrize(
        "side,entry,stop",
        [
            ("buy", 100.0, 105.0),  # long stop ABOVE — wrong (the bug)
            ("long", 50.0, 51.0),
            ("buy_to_open", 84.20, 86.00),  # the original 2026-04-09 MCL case
            ("sell", 100.0, 95.0),  # short stop BELOW — wrong
            ("short", 50.0, 49.0),
        ],
    )
    def test_helper_flags_inverted(self, side, entry, stop):
        assert _is_inverted(side, entry, stop)


# ── Guard tests: production write paths must reject inverted stops ──────────


class TestInsertPaperTradeGuard:
    """DatabaseManager.insert_paper_trade must refuse inverted stops."""

    def _fresh_db(self, tmp_path):
        from database.manager import DatabaseManager

        db_file = tmp_path / "guard.db"
        return DatabaseManager(db_path=str(db_file))

    def test_insert_paper_trade_rejects_inverted_long_stop(self, tmp_path):
        db = self._fresh_db(tmp_path)
        with pytest.raises(ValueError, match="inverted stop"):
            db.insert_paper_trade(
                trade_id="test-long-inverted",
                symbol="MCL",
                side="buy",
                quantity=1,
                entry_price=84.20,
                stop_loss=86.00,  # ABOVE entry on a long — the 2026-04-09 shape
                idempotency_key="test-inverted-long-key-0000000000000000",
            )

    def test_insert_paper_trade_rejects_inverted_short_stop(self, tmp_path):
        db = self._fresh_db(tmp_path)
        with pytest.raises(ValueError, match="inverted stop"):
            db.insert_paper_trade(
                trade_id="test-short-inverted",
                symbol="MCL",
                side="sell",
                quantity=1,
                entry_price=84.20,
                stop_loss=82.00,  # BELOW entry on a short — same class of bug
                idempotency_key="test-inverted-short-key-000000000000000",
            )

    # Positive-control ("accepts correct stop") deliberately omitted:
    # test_no_inverted_stops_in_sqlite already scans the live DB's valid
    # stops on every run, so a synthetic happy-path case would be redundant
    # and require schema bootstrapping that the real DB provides for free.


class TestInsertPaperTradePersistsTakeProfit:
    """Regression net for the 2026-08-16 take_profit column drop.

    ``insert_paper_trade`` mirrored ``take_profit`` into ``strategy_params``
    JSON but omitted it from the INSERT column list, so the dedicated
    ``paper_trades.take_profit`` column was never written (0/119 populated).
    This test pins the dedicated-column write so the fix can't regress.
    """

    def _fresh_db(self, tmp_path):
        import sqlite3

        from database._mixins_trades import TradesMixin

        class _Lock:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        class _FakeDB(TradesMixin):
            def __init__(self, path):
                self._db_path = path
                self._lock = _Lock()
                conn = self._connect()
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_trades (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_id        TEXT    NOT NULL UNIQUE,
                        symbol          TEXT    NOT NULL,
                        side            TEXT    NOT NULL,
                        quantity        REAL    NOT NULL,
                        entry_price     REAL    NOT NULL,
                        exit_price      REAL,
                        entry_time      TEXT    NOT NULL,
                        exit_time       TEXT,
                        pnl             REAL,
                        status          TEXT    NOT NULL DEFAULT 'open',
                        stop_loss       REAL,
                        take_profit     REAL,
                        strategy_params TEXT,
                        notes           TEXT    DEFAULT '',
                        idempotency_key TEXT    NOT NULL,
                        strategy_id     TEXT
                    )
                    """
                )
                conn.commit()
                conn.close()

            def _connect(self):
                conn = sqlite3.connect(self._db_path)
                conn.row_factory = sqlite3.Row
                return conn

        return _FakeDB(str(tmp_path / "tp.db"))

    def test_take_profit_written_to_dedicated_column(self, tmp_path):
        import sqlite3

        db = self._fresh_db(tmp_path)
        trade_id = "test-tp-col-0000000000000000"
        db.insert_paper_trade(
            trade_id=trade_id,
            symbol="ES",
            side="buy",
            quantity=1,
            entry_price=5500.0,
            stop_loss=5490.0,
            take_profit=5530.0,
            strategy_params={"source": "test"},
            idempotency_key="test-tp-key-0000000000000000000000000000",
        )
        conn = sqlite3.connect(str(tmp_path / "tp.db"))
        try:
            row = conn.execute(
                "SELECT stop_loss, take_profit FROM paper_trades WHERE trade_id = ?",
                (trade_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "paper_trades row not written"
        assert row[0] == 5490.0, f"stop_loss not persisted: {row[0]}"
        assert row[1] == 5530.0, f"take_profit not persisted to dedicated column: {row[1]}"

    def test_take_profit_mirrored_into_strategy_params(self, tmp_path):
        import json
        import sqlite3

        db = self._fresh_db(tmp_path)
        trade_id = "test-tp-json-0000000000000000"
        db.insert_paper_trade(
            trade_id=trade_id,
            symbol="ES",
            side="buy",
            quantity=1,
            entry_price=5500.0,
            stop_loss=5490.0,
            take_profit=5530.0,
            strategy_params={"source": "test"},
            idempotency_key="test-tp-json-key-0000000000000000000000000",
        )
        conn = sqlite3.connect(str(tmp_path / "tp.db"))
        try:
            row = conn.execute(
                "SELECT strategy_params FROM paper_trades WHERE trade_id = ?",
                (trade_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        merged = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
        assert merged.get("take_profit") == 5530.0, "take_profit not mirrored into strategy_params"


class TestPatchPositionGuard:
    """update_position must raise HTTP 422 on an inverted stop update."""

    def test_patch_paper_position_rejects_inverted_stop(self):
        import asyncio

        from fastapi import HTTPException

        from routers import portfolio_router as pr
        from routers.portfolio_router import UpdatePositionRequest, update_position

        class _FakeTrade:
            side = "buy"
            entry_price = 84.20
            stop_loss = 82.40
            take_profit = None

        class _FakeTracker:
            _open = {"mcl-1": _FakeTrade()}

        prev_tracker = pr.paper_tracker
        pr.paper_tracker = _FakeTracker()
        try:
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    update_position(
                        "mcl-1",
                        UpdatePositionRequest(stop_loss=86.00),  # inverted for long
                    )
                )
        finally:
            pr.paper_tracker = prev_tracker

        assert exc_info.value.status_code == 422
        assert "Inverted stop_loss rejected" in exc_info.value.detail

    def test_patch_paper_position_rejects_inverted_stop_with_action_attr(self):
        """Regression: real Trade dataclass uses ``action`` not ``side``.

        Caught live 2026-04-16 after the initial guard shipped reading
        ``getattr(trade, "side")`` which returned None against the real
        PortfolioTracker Trade object (which stores the direction as
        ``action``). The guard silently skipped and the live PATCH returned
        HTTP 200 for an inverted stop. This test locks in the ``action``
        path explicitly.
        """
        import asyncio

        from fastapi import HTTPException

        from routers import portfolio_router as pr
        from routers.portfolio_router import UpdatePositionRequest, update_position

        class _ActionOnlyTrade:
            action = "buy"
            entry_price = 84.20
            stop_loss = 82.40
            take_profit = None

        class _FakeTracker:
            _open = {"mcl-action": _ActionOnlyTrade()}

        prev_tracker = pr.paper_tracker
        pr.paper_tracker = _FakeTracker()
        try:
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    update_position(
                        "mcl-action",
                        UpdatePositionRequest(stop_loss=86.00),
                    )
                )
        finally:
            pr.paper_tracker = prev_tracker

        assert exc_info.value.status_code == 422
        assert "Inverted stop_loss rejected" in exc_info.value.detail

    def test_patch_paper_position_accepts_correct_stop(self):
        """Control: a below-entry stop on a long must pass the guard."""
        import asyncio

        from routers import portfolio_router as pr
        from routers.portfolio_router import UpdatePositionRequest, update_position

        class _FakeTrade:
            side = "buy"
            entry_price = 84.20
            stop_loss = 82.40
            take_profit = None

        class _FakeTracker:
            _open = {"mcl-1": _FakeTrade()}

        prev_tracker = pr.paper_tracker
        prev_db = pr.db_manager
        pr.paper_tracker = _FakeTracker()
        pr.db_manager = None  # Skip SQLite persistence in this unit test
        try:
            result = asyncio.run(
                update_position(
                    "mcl-1",
                    UpdatePositionRequest(stop_loss=82.00),  # correct: below entry
                )
            )
        finally:
            pr.paper_tracker = prev_tracker
            pr.db_manager = prev_db

        assert result["stop_loss"] == 82.00
        assert result["status"] == "updated"
