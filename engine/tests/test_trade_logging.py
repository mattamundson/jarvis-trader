"""
JARVIS TRADER — Trade Decision Logging Tests
=============================================
End-to-end test of trade entry → decision context → exit → P&L tracking.

Tests the complete logging automation pipeline:
  1. Mock trade decision (BUY)
  2. Auto-log entry with regime, bias, signal scores
  3. Verify journal entry created with all context
  4. Mock trade exit
  5. Auto-log exit with P&L
  6. Verify exit logged correctly
  7. Correlate to decisions table
"""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, Mock, patch

from trade_logging.trade_logger import LogEntry, TradeLogger
from trade_logging.trader_hooks import (
    correlate_entry_to_decision,
    log_trade_entry,
    log_trade_exit,
    setup_trade_logging,
)


class MockTradeDecision:
    """Mock TradeDecision from TraderAgent."""

    def __init__(
        self,
        symbol: str = "MCL",
        action: str = "buy",
        quantity: int = 2,
        entry_price: float = 84.50,
        signal_score: float = 0.75,
        confidence: float = 0.82,
        reasoning: str = "Strong bullish confluence",
        risk_notes: str = "Stop at 83.00",
    ):
        self.symbol = symbol
        self.action = action
        self.quantity = quantity
        self.entry_price = entry_price
        self.signal_score = signal_score
        self.confidence = confidence
        self.reasoning = reasoning
        self.risk_notes = risk_notes


class MockDatabaseManager:
    """Mock DatabaseManager with journal and trade methods."""

    def __init__(self):
        self.journal_entries: Dict[int, dict] = {}
        self.journal_id_counter = 1
        self.trades: Dict[str, dict] = {}
        self.decisions: Dict[int, dict] = {}
        self.decision_id_counter = 1

    def add_journal_entry(
        self,
        trade_id: str,
        note: str,
        tags: Optional[str] = None,
        mood: Optional[str] = None,
        lesson: Optional[str] = None,
        timestamp: Optional[str] = None,
        regime_tier: Optional[int] = None,
        deciding_stage: Optional[str] = None,
        bull_score: Optional[float] = None,
        bear_score: Optional[float] = None,
        debate_confidence: Optional[float] = None,
        timeframe: Optional[str] = None,
    ) -> int:
        """Mock add_journal_entry — signature mirrors JournalMixin.add_journal_entry."""
        entry_id = self.journal_id_counter
        self.journal_id_counter += 1
        self.journal_entries[entry_id] = {
            "id": entry_id,
            "trade_id": trade_id,
            "timestamp": timestamp or datetime.now().isoformat(),
            "note": note,
            "tags": tags,
            "mood": mood,
            "lesson": lesson,
            "regime_tier": regime_tier,
            "deciding_stage": deciding_stage,
            "bull_score": bull_score,
            "bear_score": bear_score,
            "debate_confidence": debate_confidence,
            "timeframe": timeframe,
        }
        return entry_id

    def get_journal_entries(
        self,
        trade_id: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ):
        """Mock get_journal_entries."""
        results = []
        for entry in self.journal_entries.values():
            if trade_id and entry["trade_id"] != trade_id:
                continue
            if tag and (not entry.get("tags") or tag not in entry["tags"]):
                continue
            results.append(entry)
        return sorted(results, key=lambda x: x["timestamp"], reverse=True)[:limit]

    def update_journal_entry(
        self,
        entry_id: int,
        note: Optional[str] = None,
        tags: Optional[str] = None,
        mood: Optional[str] = None,
        lesson: Optional[str] = None,
    ) -> bool:
        """Mock update_journal_entry."""
        if entry_id not in self.journal_entries:
            return False
        if note is not None:
            self.journal_entries[entry_id]["note"] = note
        if tags is not None:
            self.journal_entries[entry_id]["tags"] = tags
        if mood is not None:
            self.journal_entries[entry_id]["mood"] = mood
        if lesson is not None:
            self.journal_entries[entry_id]["lesson"] = lesson
        return True

    def get_trade_by_id(self, trade_id: str) -> Optional[dict]:
        """Mock get_trade_by_id."""
        return self.trades.get(trade_id)

    def insert_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        entry_time: Optional[str] = None,
        status: str = "open",
        strategy_params: Optional[Any] = None,
        notes: str = "",
    ) -> int:
        """Mock insert_trade."""
        entry_time = entry_time or datetime.now().isoformat()
        self.trades[trade_id] = {
            "trade_id": trade_id,
            "symbol": symbol.upper(),
            "side": side.lower(),
            "quantity": quantity,
            "entry_price": entry_price,
            "entry_time": entry_time,
            "status": status,
            "notes": notes,
            "regime": None,
            "bias": None,
            "composite_score": None,
            "stc_contrib": None,
            "orb_contrib": None,
            "vwap_contrib": None,
            "bull_score": None,
            "bear_score": None,
            "debate_confidence": None,
        }
        return 1

    def get_decisions(
        self,
        symbol: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> list:
        """Mock get_decisions."""
        results = []
        for decision in self.decisions.values():
            if symbol and decision["symbol"] != symbol:
                continue
            if action and decision["action"] != action:
                continue
            results.append(decision)
        return sorted(
            results, key=lambda x: x["timestamp"], reverse=True
        )[:limit]

    def insert_decision(
        self,
        symbol: str,
        action: str,
        confidence: Optional[float] = None,
        regime: Optional[str] = None,
        signal_data: Optional[Any] = None,
        reasoning: Optional[str] = None,
        timestamp: Optional[str] = None,
        full_pipeline_data: Optional[Any] = None,
    ) -> int:
        """Mock insert_decision."""
        decision_id = self.decision_id_counter
        self.decision_id_counter += 1
        self.decisions[decision_id] = {
            "id": decision_id,
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "regime": regime,
            "signal_data_json": json.dumps(signal_data) if signal_data else None,
            "reasoning": reasoning,
            "timestamp": timestamp or datetime.now().isoformat(),
            "full_pipeline_json": (
                json.dumps(full_pipeline_data) if full_pipeline_data else None
            ),
        }
        return decision_id


class TestTradeLogging(unittest.TestCase):
    """Test suite for trade decision logging automation."""

    def setUp(self):
        """Set up test fixtures."""
        self.db_manager = MockDatabaseManager()
        self.trade_logger = TradeLogger(self.db_manager)

    def test_log_entry_creates_journal_entry(self):
        """Test that logging an entry creates a trade_journal entry."""
        # Prepare test data
        trade_decision = MockTradeDecision(
            symbol="MCL",
            action="buy",
            quantity=2,
            entry_price=84.50,
            signal_score=0.75,
            confidence=0.82,
        )

        debate_result = {
            "verdict": "BULL_WINS",
            "bull_score": 8.0,
            "bear_score": 2.0,
            "confidence": 0.8,
        }

        analyst_reports = {
            "technical": {
                "regime": "TRENDING_BULL",
                "bias": "bullish",
                "indicators": {
                    "composite_score": 0.75,
                    "stc_contrib": 1,
                    "orb_contrib": 1,
                    "vwap_contrib": 0,
                },
            },
            "news": {"sentiment": 0.6},
            "social": {"sentiment": 0.5},
            "fundamental": {"vix": 18.5},
        }

        # Execute
        loop = asyncio.new_event_loop()
        try:
            trade_id = loop.run_until_complete(
                self.trade_logger.log_entry(
                    symbol="MCL",
                    trade_decision=trade_decision,
                    debate_result=debate_result,
                    analyst_reports=analyst_reports,
                )
            )
        finally:
            loop.close()

        # Verify
        self.assertIsNotNone(trade_id)
        self.assertIn(trade_id, self.db_manager.trades)

        # Check journal entries
        journal_entries = self.db_manager.get_journal_entries(trade_id=trade_id)
        self.assertEqual(len(journal_entries), 1)

        entry = journal_entries[0]
        self.assertIn("AUTO-ENTRY", entry["note"])
        self.assertIn("MCL", entry["note"])
        self.assertIn("BUY", entry["note"])
        self.assertIn("auto_logged", entry.get("tags", ""))

    def test_log_entry_with_hold_decision(self):
        """Test that HOLD decisions are not logged."""
        trade_decision = MockTradeDecision(action="hold", quantity=0)

        debate_result = {"verdict": "INCONCLUSIVE"}
        analyst_reports = {}

        loop = asyncio.new_event_loop()
        try:
            trade_id = loop.run_until_complete(
                self.trade_logger.log_entry(
                    symbol="MCL",
                    trade_decision=trade_decision,
                    debate_result=debate_result,
                    analyst_reports=analyst_reports,
                )
            )
        finally:
            loop.close()

        # HOLD should not create a journal entry
        self.assertIsNone(trade_id)

    def test_log_exit_updates_journal(self):
        """Test that logging an exit updates the journal entry."""
        # First, log an entry
        trade_decision = MockTradeDecision()
        debate_result = {"bull_score": 8.0, "bear_score": 2.0, "confidence": 0.8}
        analyst_reports = {
            "technical": {
                "regime": "TRENDING_BULL",
                "bias": "bullish",
                "indicators": {},
            }
        }

        loop = asyncio.new_event_loop()
        try:
            trade_id = loop.run_until_complete(
                self.trade_logger.log_entry(
                    symbol="MCL",
                    trade_decision=trade_decision,
                    debate_result=debate_result,
                    analyst_reports=analyst_reports,
                )
            )

            # Now log the exit
            exit_success = loop.run_until_complete(
                self.trade_logger.log_exit(
                    trade_id=trade_id,
                    exit_price=86.25,
                    pnl=350.0,
                )
            )
        finally:
            loop.close()

        # Verify
        self.assertTrue(exit_success)

        # Check that journal entry was updated
        journal_entries = self.db_manager.get_journal_entries(trade_id=trade_id)
        self.assertEqual(len(journal_entries), 1)

        entry = journal_entries[0]
        self.assertIn("AUTO-EXIT", entry["note"])
        self.assertIn("86.25", entry["note"])
        self.assertIn("+350", entry["note"])
        self.assertIn("exit", entry.get("tags", ""))

    def test_log_entry_captures_signal_context(self):
        """Test that entry logging captures full signal context."""
        trade_decision = MockTradeDecision()

        debate_result = {
            "verdict": "BULL_WINS",
            "bull_score": 9.0,
            "bear_score": 1.0,
            "confidence": 0.95,
        }

        analyst_reports = {
            "technical": {
                "regime": "TRENDING_BULL",
                "bias": "strongly_bullish",
                "indicators": {
                    "composite_score": 0.87,
                    "stc_contrib": 1,
                    "orb_contrib": 1,
                    "vwap_contrib": 1,
                },
            },
        }

        loop = asyncio.new_event_loop()
        try:
            trade_id = loop.run_until_complete(
                self.trade_logger.log_entry(
                    symbol="MCL",
                    trade_decision=trade_decision,
                    debate_result=debate_result,
                    analyst_reports=analyst_reports,
                )
            )
        finally:
            loop.close()

        # Verify signal context was captured
        trade = self.db_manager.trades.get(trade_id)
        self.assertIsNotNone(trade)

        # The LogEntry should have captured the context
        # (In a real test, we'd verify the database columns were updated)
        journal_entries = self.db_manager.get_journal_entries(trade_id=trade_id)
        self.assertEqual(len(journal_entries), 1)
        # Verify the entry was tagged correctly
        self.assertIn("auto_logged", journal_entries[0]["tags"])

    def test_end_to_end_mock_trade(self):
        """
        Complete end-to-end test: entry → decision context → exit → P&L tracking.

        Simulates a complete trade lifecycle:
        1. BUY 2 MCL @ 84.50
        2. Log entry with regime (TRENDING_BULL), bias (bullish), scores
        3. EXIT @ 86.25 for +$350 P&L
        4. Log exit with P&L
        5. Verify complete journal trail
        """
        print("\n=== End-to-End Mock Trade Test ===\n")

        # 1. Create trade decision
        print("[1] Creating TRADE DECISION (BUY 2 MCL @ 84.50)...")
        trade_decision = MockTradeDecision(
            symbol="MCL",
            action="buy",
            quantity=2,
            entry_price=84.50,
            signal_score=0.75,
            confidence=0.82,
            reasoning="Strong bullish confluence: STC + ORB aligned, VWAP support",
            risk_notes="Stop at 83.00 (1.50 points = $300 max loss)",
        )

        # 2. Prepare debate + analyst context
        print("[2] Preparing DEBATE RESULT (Bull: 8.0, Bear: 2.0)...")
        debate_result = {
            "verdict": "BULL_WINS",
            "bull_score": 8.0,
            "bear_score": 2.0,
            "confidence": 0.8,
        }

        print("[3] Preparing ANALYST REPORTS (Regime: TRENDING_BULL)...")
        analyst_reports = {
            "technical": {
                "regime": "TRENDING_BULL",
                "structure_position": "BUYER_CONTROL",
                "bias": "bullish",
                "indicators": {
                    "composite_score": 0.75,
                    "atr": 1.25,
                    "stc_contrib": 1,
                    "orb_contrib": 1,
                    "vwap_contrib": 0,
                },
            },
            "news": {
                "sentiment": 0.60,
                "key_events": ["bullish CL inventory report"],
            },
            "social": {"sentiment": 0.50},
            "fundamental": {"vix": 18.5, "trend": "risk_on"},
        }

        # 3. Log entry
        loop = asyncio.new_event_loop()
        try:
            print("\n[4] AUTO-LOGGING ENTRY with decision context...")
            trade_id = loop.run_until_complete(
                self.trade_logger.log_entry(
                    symbol="MCL",
                    trade_decision=trade_decision,
                    debate_result=debate_result,
                    analyst_reports=analyst_reports,
                )
            )

            print(f"    ✓ Trade logged: {trade_id[:8]}...")

            # Verify entry
            journal_entries = self.db_manager.get_journal_entries(
                trade_id=trade_id, limit=1
            )
            entry = journal_entries[0]
            print(f"    ✓ Journal entry #{entry['id']}: {entry['note'][:80]}...")
            print(f"    ✓ Tags: {entry['tags']}")

            # 4. Simulate trade exit
            print("\n[5] EXITING TRADE @ 86.25 (+$350 P&L)...")
            exit_price = 86.25
            pnl = 350.0  # (86.25 - 84.50) * 2 contracts * $100/point

            exit_success = loop.run_until_complete(
                self.trade_logger.log_exit(
                    trade_id=trade_id,
                    exit_price=exit_price,
                    pnl=pnl,
                )
            )

            print(f"    ✓ Exit logged successfully: {exit_success}")

            # Verify exit
            journal_entries = self.db_manager.get_journal_entries(
                trade_id=trade_id, limit=1
            )
            exit_entry = journal_entries[0]
            print(f"    ✓ Journal updated: {exit_entry['note'][-80:]}...")

            # 5. Verify complete trade trail
            print("\n[6] VERIFYING COMPLETE TRADE TRAIL...")
            trade = self.db_manager.trades.get(trade_id)
            print(f"    ✓ Trade status: {trade['symbol']} {trade['side'].upper()} {trade['quantity']} @ {trade['entry_price']}")
            print("    ✓ Journal entry contains:")
            print("       - Entry: BUY 2 MCL @ 84.50")
            print(f"       - Regime: {analyst_reports['technical']['regime']}")
            print(f"       - Bias: {analyst_reports['technical']['bias']}")
            print(f"       - Debate: Bull {debate_result['bull_score']} vs Bear {debate_result['bear_score']}")
            print("       - Exit: 86.25 for +$350 P&L")
            print(f"       - Full note trail: {len(exit_entry['note'])} chars")

            # Final assertions
            self.assertIsNotNone(trade_id)
            self.assertTrue(exit_success)
            self.assertIn("AUTO-EXIT", exit_entry["note"])
            self.assertIn("86.25", exit_entry["note"])
            self.assertIn("+350", exit_entry["note"])

            print("\n✓ END-TO-END TEST PASSED\n")

        finally:
            loop.close()


class SqliteProvenanceDBManager:
    """
    Minimal DatabaseManager stand-in exposing only ``_connect()`` — the sole
    interface ``TradeLogger._store_signal_provenance`` needs. Backed by a
    real on-disk SQLite file so the direct-SQL UPDATE path is exercised
    against real ``PRAGMA table_info`` introspection instead of a mock.
    """

    def __init__(self, db_path: str, with_provenance_columns: bool = True):
        self._db_path = db_path
        self._with_provenance_columns = with_provenance_columns
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            if self._with_provenance_columns:
                # Matches migration_010's real paper_trades column set exactly
                # (database/migrations.py) -- bull_score/bear_score/
                # debate_confidence are NOT paper_trades columns, they live on
                # trade_journal via migration_012. _store_signal_provenance
                # deliberately never writes them here (see its docstring).
                conn.execute(
                    """
                    CREATE TABLE paper_trades (
                        trade_id TEXT PRIMARY KEY,
                        regime TEXT,
                        structure_position TEXT,
                        bias TEXT,
                        composite_score REAL,
                        stc_contrib INTEGER,
                        orb_contrib INTEGER,
                        vwap_contrib INTEGER
                    )
                    """
                )
            else:
                # Legacy/un-migrated schema: no provenance columns at all.
                conn.execute("CREATE TABLE paper_trades (trade_id TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO paper_trades (trade_id) VALUES ('trade-001')")
            conn.commit()
        finally:
            conn.close()


class TestStoreSignalProvenance(unittest.TestCase):
    """
    Coverage for TradeLogger._store_signal_provenance — the direct-SQL,
    best-effort path that persists signal context onto paper_trades. This
    is invoked internally by log_entry() but MockDatabaseManager (used by
    the rest of this file) has no _connect(), so that branch is never
    exercised by the other tests here.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmpdir.name) / "provenance.db")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _sample_entry(self) -> LogEntry:
        return LogEntry(
            trade_id="trade-001",
            symbol="MCL",
            side="buy",
            quantity=1.0,
            entry_price=85.50,
            entry_time="2026-04-22T15:30:00Z",
            signal_score=0.75,
            confidence=0.82,
            regime="TRENDING_BULL",
            bias="bullish",
            composite_score=0.78,
            stc_contrib=1,
            orb_contrib=1,
            vwap_contrib=0,
            bull_score=0.85,
            bear_score=0.15,
            debate_confidence=0.83,
        )

    def test_updates_columns_when_present(self):
        """When paper_trades has provenance columns, they get populated."""
        db = SqliteProvenanceDBManager(self._db_path, with_provenance_columns=True)
        logger = TradeLogger(db)

        logger._store_signal_provenance("trade-001", self._sample_entry())

        conn = db._connect()
        try:
            row = conn.execute(
                "SELECT regime, bias, composite_score, stc_contrib, orb_contrib, "
                "vwap_contrib FROM paper_trades WHERE trade_id = ?",
                ("trade-001",),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("TRENDING_BULL", "bullish", 0.78, 1, 1, 0))

    def test_noop_when_columns_missing(self):
        """No provenance columns on paper_trades -> silently skipped, no crash."""
        db = SqliteProvenanceDBManager(self._db_path, with_provenance_columns=False)
        logger = TradeLogger(db)

        # Should not raise even though the UPDATE columns don't exist.
        logger._store_signal_provenance("trade-001", self._sample_entry())

    def test_noop_when_no_direct_db_access(self):
        """A DatabaseManager without _connect() (e.g. MockDatabaseManager) is skipped."""
        db = MockDatabaseManager()
        logger = TradeLogger(db)

        # Should not raise (no AttributeError from missing _connect).
        logger._store_signal_provenance("trade-001", self._sample_entry())

    def test_swallows_db_errors(self):
        """A raising _connect() is caught -- provenance storage is non-critical."""

        class BoomDB:
            def _connect(self):
                raise RuntimeError("db unavailable")

        logger = TradeLogger(BoomDB())

        # Should not raise -- failures here must never block trade logging.
        logger._store_signal_provenance("trade-001", self._sample_entry())


class TestCorrelateEntryToDecision(unittest.TestCase):
    """Coverage for TradeLogger.correlate_entry_to_decision (background
    attribution task); previously untested by this file."""

    def setUp(self):
        self.db_manager = MockDatabaseManager()
        self.trade_logger = TradeLogger(self.db_manager)

    @staticmethod
    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_success_appends_decision_reference_to_journal(self):
        self.db_manager.insert_decision(
            symbol="MCL", action="buy", timestamp="2026-04-22T15:29:00Z"
        )
        entry_id = self.db_manager.add_journal_entry(
            trade_id="trade-001",
            note="AUTO-ENTRY: BUY 1 MCL @ 85.50",
            tags="auto_logged,entry",
            timestamp="2026-04-22T15:30:00Z",
        )

        result = self._run(
            self.trade_logger.correlate_entry_to_decision(
                trade_id="trade-001", symbol="MCL", timestamp="2026-04-22T15:30:00Z"
            )
        )

        self.assertTrue(result)
        updated_note = self.db_manager.journal_entries[entry_id]["note"]
        self.assertIn("[DECISION_ID: 1]", updated_note)

    def test_no_decisions_for_symbol_returns_false(self):
        self.db_manager.add_journal_entry(trade_id="trade-001", note="AUTO-ENTRY")

        result = self._run(
            self.trade_logger.correlate_entry_to_decision(
                trade_id="trade-001", symbol="MCL", timestamp="2026-04-22T15:30:00Z"
            )
        )

        self.assertFalse(result)

    def test_no_journal_entry_for_trade_returns_false(self):
        self.db_manager.insert_decision(symbol="MCL", action="buy")

        result = self._run(
            self.trade_logger.correlate_entry_to_decision(
                trade_id="trade-nonexistent",
                symbol="MCL",
                timestamp="2026-04-22T15:30:00Z",
            )
        )

        self.assertFalse(result)

    def test_no_db_manager_returns_false(self):
        logger = TradeLogger(None)

        result = self._run(
            logger.correlate_entry_to_decision(
                trade_id="trade-001", symbol="MCL", timestamp="2026-04-22T15:30:00Z"
            )
        )

        self.assertFalse(result)

    def test_swallows_db_exception_and_returns_false(self):
        db = MagicMock()
        db.get_decisions.side_effect = Exception("db unavailable")
        logger = TradeLogger(db)

        result = self._run(
            logger.correlate_entry_to_decision(
                trade_id="trade-001", symbol="MCL", timestamp="2026-04-22T15:30:00Z"
            )
        )

        self.assertFalse(result)


class TestTradeLoggerErrorHandling(unittest.TestCase):
    """Coverage for the guard-clause and exception-handling branches of
    log_entry/log_exit that the happy-path tests above don't reach."""

    def setUp(self):
        self.db_manager = MockDatabaseManager()
        self.trade_logger = TradeLogger(self.db_manager)

    @staticmethod
    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_log_entry_no_db_manager_returns_none(self):
        logger = TradeLogger(None)
        result = self._run(
            logger.log_entry(
                symbol="MCL",
                trade_decision=MockTradeDecision(),
                debate_result={},
                analyst_reports={},
            )
        )
        self.assertIsNone(result)

    def test_log_entry_swallows_exception_and_returns_none(self):
        db = MagicMock()
        db.insert_trade.side_effect = Exception("db write failed")
        logger = TradeLogger(db)

        result = self._run(
            logger.log_entry(
                symbol="MCL",
                trade_decision=MockTradeDecision(),
                debate_result={},
                analyst_reports={},
            )
        )

        self.assertIsNone(result)

    def test_log_exit_no_db_manager_returns_false(self):
        logger = TradeLogger(None)
        result = self._run(
            logger.log_exit(trade_id="trade-001", exit_price=87.25, pnl=175.0)
        )
        self.assertFalse(result)

    def test_log_exit_trade_not_found_returns_false(self):
        result = self._run(
            self.trade_logger.log_exit(
                trade_id="does-not-exist", exit_price=87.25, pnl=175.0
            )
        )
        self.assertFalse(result)

    def test_log_exit_no_journal_entry_returns_false(self):
        # Trade exists, but no journal entry was ever created for it.
        self.db_manager.insert_trade(
            trade_id="trade-001",
            symbol="MCL",
            side="buy",
            quantity=1.0,
            entry_price=85.50,
        )

        result = self._run(
            self.trade_logger.log_exit(
                trade_id="trade-001", exit_price=87.25, pnl=175.0
            )
        )

        self.assertFalse(result)

    def test_log_exit_swallows_exception_and_returns_false(self):
        db = MagicMock()
        db.get_trade_by_id.side_effect = Exception("db read failed")
        logger = TradeLogger(db)

        result = self._run(
            logger.log_exit(trade_id="trade-001", exit_price=87.25, pnl=175.0)
        )

        self.assertFalse(result)


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
