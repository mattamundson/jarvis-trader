"""Regression test for the /journal provenance write-back bug (dashboard audit
finding "Bug A", 2026-07-11).

Bug: TradeLogger._store_signal_provenance() UPDATEd paper_trades with
bull_score/bear_score/debate_confidence -- columns that only exist on
trade_journal (migration_012), not paper_trades (migration_010). The UPDATE
threw sqlite3.OperationalError on every call and was silently swallowed at
debug level, so NONE of the provenance fields (not even the valid
paper_trades ones -- regime/bias/composite_score/stc_contrib/orb_contrib/
vwap_contrib) ever persisted. Separately, TradeLogger.log_entry()'s
add_journal_entry() call never passed bull_score/bear_score/debate_confidence
even though trade_journal has columns for them, so those stayed NULL too.
And GET /trades/journal only ever SELECTed from paper_trades, which
structurally cannot carry regime_tier/deciding_stage/bull_score/bear_score/
debate_confidence -- those columns don't exist on that table.

This test uses the REAL DatabaseManager (real migrations, real schema) --
not a mock -- specifically because the original bug was invisible to
mock-based tests (test_trade_logging.py's MockDatabaseManager has no schema
to violate).
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.manager import DatabaseManager  # noqa: E402
from trade_logging.trade_logger import TradeLogger  # noqa: E402


class _TradeDecision:
    def __init__(self) -> None:
        self.action = "buy"
        self.quantity = 2
        self.entry_price = 84.50
        self.signal_score = 0.75
        self.confidence = 0.82
        self.reasoning = "Strong bullish confluence"
        self.risk_notes = "Stop at 83.00"


@pytest.fixture()
def real_db(tmp_path: Path) -> DatabaseManager:
    db_path = tmp_path / "test_provenance.db"
    db = DatabaseManager(db_path=str(db_path))
    db.initialize()
    return db


def test_provenance_writeback_against_real_schema(real_db: DatabaseManager) -> None:
    """log_entry() against a REAL migrated DB must not throw, and must
    actually persist provenance to both paper_trades and trade_journal."""
    logger_hook = TradeLogger(real_db)

    analyst_reports = {
        "technical": {
            "regime": "TRENDING_BULL",
            "bias": "STRONG_BULL",
            "indicators": {
                "composite_score": 0.68,
                "stc_contrib": 1,
                "orb_contrib": 1,
                "vwap_contrib": 0,
            },
        }
    }
    debate_result = {"bull_score": 8.0, "bear_score": 2.0, "confidence": 0.91}

    trade_id = asyncio.run(
        logger_hook.log_entry("MCL", _TradeDecision(), debate_result, analyst_reports)
    )

    assert trade_id is not None, "log_entry must not fail against the real schema"

    conn = real_db._connect()
    try:
        pt_row = conn.execute(
            "SELECT regime, bias, composite_score, stc_contrib, orb_contrib, vwap_contrib "
            "FROM paper_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
        assert pt_row is not None
        assert pt_row["regime"] == "TRENDING_BULL"
        assert pt_row["bias"] == "STRONG_BULL"
        assert pt_row["composite_score"] == pytest.approx(0.68)
        assert pt_row["stc_contrib"] == 1
        assert pt_row["orb_contrib"] == 1
        assert pt_row["vwap_contrib"] == 0

        tj_row = conn.execute(
            "SELECT bull_score, bear_score, debate_confidence FROM trade_journal "
            "WHERE trade_id = ? AND tags LIKE '%auto_logged%'",
            (trade_id,),
        ).fetchone()
        assert tj_row is not None
        assert tj_row["bull_score"] == pytest.approx(8.0)
        assert tj_row["bear_score"] == pytest.approx(2.0)
        assert tj_row["debate_confidence"] == pytest.approx(0.91)
    finally:
        conn.close()


def test_journal_endpoint_join_returns_trade_journal_fields(real_db: DatabaseManager) -> None:
    """The GET /trades/journal query (paper_trades LEFT JOIN trade_journal)
    must surface bull_score/bear_score/debate_confidence -- fields that
    structurally cannot live on paper_trades alone."""
    logger_hook = TradeLogger(real_db)

    analyst_reports = {
        "technical": {
            "regime": "RANGE",
            "bias": "NEUTRAL",
            "indicators": {"composite_score": 0.1, "stc_contrib": 0, "orb_contrib": 0, "vwap_contrib": 0},
        }
    }
    debate_result = {"bull_score": 5.5, "bear_score": 4.5, "confidence": 0.6}

    trade_id = asyncio.run(
        logger_hook.log_entry("MGC", _TradeDecision(), debate_result, analyst_reports)
    )
    assert trade_id is not None

    # Mirror the exact query from routers/trades_router.py::get_trades_journal
    query = """
        SELECT pt.*, tj.regime_tier, tj.deciding_stage, tj.bull_score,
               tj.bear_score, tj.debate_confidence, tj.timeframe
        FROM paper_trades pt
        LEFT JOIN (
            SELECT trade_id, regime_tier, deciding_stage, bull_score,
                   bear_score, debate_confidence, timeframe
            FROM trade_journal
            WHERE id IN (
                SELECT MAX(id) FROM trade_journal
                WHERE tags LIKE '%auto_logged%'
                GROUP BY trade_id
            )
        ) tj ON tj.trade_id = pt.trade_id
        WHERE pt.status IN ('open', 'closed') AND pt.trade_id = ?
    """
    conn = real_db._connect()
    try:
        cursor = conn.execute(query, (trade_id,))
        row = cursor.fetchone()
        col_names = [d[0] for d in cursor.description]
        result: dict[str, Any] = dict(zip(col_names, row, strict=False))
    finally:
        conn.close()

    assert result["bull_score"] == pytest.approx(5.5)
    assert result["bear_score"] == pytest.approx(4.5)
    assert result["debate_confidence"] == pytest.approx(0.6)
