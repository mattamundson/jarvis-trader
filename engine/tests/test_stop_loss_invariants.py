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
