"""
JARVIS TRADER — Trade Decision Logging Tests
=============================================
Comprehensive test suite for automated trade decision logging.

Tests:
  1. Entry logging with decision context extraction
  2. Exit logging with P&L and post-trade analysis
  3. End-to-end trade lifecycle (entry → exit)
  4. Tag generation (regime, bias, confidence)
  5. Journal note formatting
  6. Error handling and edge cases

SKIPPED (2026-05-07): These tests target an older API surface
(TradeEntryContext, TradeExitContext, auto_log_trade_entry,
auto_log_trade_exit, initialize_trade_logger) imported from
`logging.trade_logger`. The package was since renamed to
`engine/trade_logging/` — the literal name `engine/logging/` shadowed the
stdlib `logging` module — and the surface was reduced to `LogEntry` +
`TradeLogger`. The retired helpers are no longer used in production and no
replacement coverage exists in this file. Re-introducing the helpers (or
porting these tests to the slimmer `TradeLogger` API) is a separate task.
Until then, this file is module-level skipped so it does not block pytest
collection (the bare `from logging.trade_logger import …` statement
ImportErrors at collection time on the renamed package).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "Targets the retired logging.trade_logger surface — the package was "
        "renamed to engine/trade_logging/ and the helpers (TradeEntryContext, "
        "TradeExitContext, auto_log_trade_entry, auto_log_trade_exit, "
        "initialize_trade_logger) were dropped. Rewriting against the slimmer "
        "TradeLogger/LogEntry API is a separate task; skipping module-wide "
        "to keep collection green."
    )
)

import json  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, Optional  # noqa: E402
from unittest.mock import MagicMock, call, patch  # noqa: E402

# Add engine to path
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# NOTE: imports below intentionally reference the retired path. Module-level
# skip above prevents collection from hitting these imports at collect-time
# (pytest evaluates pytestmark before resolving the test bodies).
try:  # pragma: no cover - retired API surface
    from logging.trade_logger import (  # type: ignore[import-not-found]  # noqa: E402
        TradeEntryContext,
        TradeExitContext,
        TradeLogger,
        auto_log_trade_entry,
        auto_log_trade_exit,
        initialize_trade_logger,
    )
except ImportError:  # pragma: no cover - expected on current branch
    TradeEntryContext = TradeExitContext = TradeLogger = None  # type: ignore[assignment, misc]
    auto_log_trade_entry = auto_log_trade_exit = initialize_trade_logger = None  # type: ignore[assignment]


@pytest.fixture
def mock_db_manager() -> MagicMock:
    """Create a mock DatabaseManager."""
    db = MagicMock()
    db.get_decisions = MagicMock(return_value=[])
    db.add_journal_entry = MagicMock(return_value=1)
    db.close_paper_trade = MagicMock(return_value=True)
    return db


@pytest.fixture
def mock_db_with_decision() -> MagicMock:
    """Create a mock DatabaseManager with a pre-loaded decision."""
    db = MagicMock()
    db.get_decisions = MagicMock(
        return_value=[
            {
                "id": 1,
                "symbol": "MCL",
                "timestamp": "2026-04-22T15:30:00Z",
                "action": "buy",
                "confidence": 0.85,
                "regime": "TRENDING_BULL",
                "signal_data_json": {
                    "composite_score": 0.78,
                    "stc_score": 1,
                    "orb_score": 1,
                    "vwap_score": 0,
                    "bull_score": 0.85,
                    "bear_score": 0.15,
                    "debate_confidence": 0.83,
                    "deciding_stage": "debate",
                    "regime_tier": 2,
                    "bias": "bullish",
                },
                "reasoning": "STC + ORB aligned with bull agenda. Strong setup.",
            }
        ]
    )
    db.add_journal_entry = MagicMock(return_value=1)
    db.close_paper_trade = MagicMock(return_value=True)
    return db


@pytest.fixture
def trade_logger(mock_db_manager) -> TradeLogger:
    """Create a TradeLogger instance with a mock database."""
    return TradeLogger(mock_db_manager)


@pytest.fixture
def sample_entry_context() -> TradeEntryContext:
    """Create a sample entry context."""
    return TradeEntryContext(
        trade_id="trade-001-abc123",
        symbol="MCL",
        side="buy",
        quantity=1.0,
        entry_price=85.50,
        entry_time="2026-04-22T15:30:00Z",
        regime="TRENDING_BULL",
        bias="bullish",
        composite_score=0.78,
        stc_score=1,
        orb_score=1,
        vwap_score=0,
        bull_score=0.85,
        bear_score=0.15,
        debate_confidence=0.83,
        deciding_stage="debate",
        regime_tier=2,
    )


@pytest.fixture
def sample_exit_context() -> TradeExitContext:
    """Create a sample exit context."""
    return TradeExitContext(
        trade_id="trade-001-abc123",
        exit_price=87.25,
        exit_time="2026-04-22T16:45:00Z",
        pnl=175.0,  # 1 contract × (87.25 - 85.50) × 100
    )


class TestTradeLoggerBasics:
    """Basic TradeLogger instantiation and initialization."""

    def test_init(self, mock_db_manager):
        """TradeLogger initializes correctly."""
        logger = TradeLogger(mock_db_manager)
        assert logger._db is mock_db_manager
        assert logger._entry_cache == {}

    def test_initialize_trade_logger(self, mock_db_manager):
        """initialize_trade_logger sets module-level instance."""
        import logging.trade_logger as tl_module

        logger = initialize_trade_logger(mock_db_manager)
        assert tl_module._logger is logger
        assert isinstance(logger, TradeLogger)


class TestEntryLogging:
    """Test trade entry logging."""

    def test_on_trade_opened_minimal(self, trade_logger, mock_db_manager):
        """on_trade_opened logs entry with minimal context."""
        trade_logger.on_trade_opened(
            trade_id="trade-001",
            symbol="MCL",
            side="buy",
            quantity=1.0,
            entry_price=85.50,
            entry_time="2026-04-22T15:30:00Z",
        )

        # Verify cache entry created
        assert "trade-001" in trade_logger._entry_cache

        # Verify journal entry added
        mock_db_manager.add_journal_entry.assert_called_once()
        call_kwargs = mock_db_manager.add_journal_entry.call_args[1]
        assert call_kwargs["trade_id"] == "trade-001"
        assert "MCL" in call_kwargs["note"]
        assert "buy" in call_kwargs["note"].lower()
        assert "85.50" in call_kwargs["note"]

    def test_on_trade_opened_with_decision_context(
        self, trade_logger, mock_db_with_decision
    ):
        """on_trade_opened enriches entry with decision context from decisions table."""
        trade_logger._db = mock_db_with_decision

        trade_logger.on_trade_opened(
            trade_id="trade-001",
            symbol="MCL",
            side="buy",
            quantity=1.0,
            entry_price=85.50,
            entry_time="2026-04-22T15:30:00Z",
        )

        # Verify context enriched
        context = trade_logger._entry_cache["trade-001"]
        assert context.regime == "TRENDING_BULL"
        assert context.bias == "bullish"
        assert context.bull_score == 0.85
        assert context.debate_confidence == 0.83

        # Verify journal includes decision metadata
        mock_db_with_decision.add_journal_entry.assert_called_once()
        call_kwargs = mock_db_with_decision.add_journal_entry.call_args[1]
        assert call_kwargs["bull_score"] == 0.85
        assert call_kwargs["debate_confidence"] == 0.83
        assert "TRENDING_BULL" in call_kwargs["note"]

    def test_on_trade_opened_error_handling(self, trade_logger, mock_db_manager):
        """on_trade_opened handles database errors gracefully."""
        mock_db_manager.get_decisions.side_effect = Exception("Database error")

        # Should not raise
        trade_logger.on_trade_opened(
            trade_id="trade-001",
            symbol="MCL",
            side="buy",
            quantity=1.0,
            entry_price=85.50,
            entry_time="2026-04-22T15:30:00Z",
        )

        # Entry still cached even if decision fetch fails
        assert "trade-001" in trade_logger._entry_cache


class TestExitLogging:
    """Test trade exit logging."""

    def test_on_trade_closed_basic(
        self, trade_logger, mock_db_manager, sample_entry_context
    ):
        """on_trade_closed logs exit with P&L."""
        # Pre-populate cache
        trade_logger._entry_cache[sample_entry_context.trade_id] = sample_entry_context

        trade_logger.on_trade_closed(
            trade_id=sample_entry_context.trade_id,
            exit_price=87.25,
            exit_time="2026-04-22T16:45:00Z",
            pnl=175.0,
        )

        # Verify cache cleared
        assert sample_entry_context.trade_id not in trade_logger._entry_cache

        # Verify exit journal entry added
        assert mock_db_manager.add_journal_entry.call_count == 1
        call_kwargs = mock_db_manager.add_journal_entry.call_args[1]
        assert call_kwargs["trade_id"] == sample_entry_context.trade_id
        assert "87.25" in call_kwargs["note"]
        assert "175.00" in call_kwargs["note"]

    def test_on_trade_closed_mood_generation(self, trade_logger, sample_entry_context):
        """on_trade_closed generates appropriate mood based on P&L."""
        trade_logger._entry_cache[sample_entry_context.trade_id] = sample_entry_context

        # Winning trade
        trade_logger.on_trade_closed(
            trade_id=sample_entry_context.trade_id,
            exit_price=87.25,
            exit_time="2026-04-22T16:45:00Z",
            pnl=175.0,
        )

        call_kwargs = trade_logger._db.add_journal_entry.call_args[1]
        assert call_kwargs["mood"] == "confident"

    def test_on_trade_closed_losing_trade_mood(self, trade_logger, sample_entry_context):
        """on_trade_closed marks large losses as frustrated."""
        trade_logger._entry_cache[sample_entry_context.trade_id] = sample_entry_context

        trade_logger.on_trade_closed(
            trade_id=sample_entry_context.trade_id,
            exit_price=80.00,
            exit_time="2026-04-22T16:45:00Z",
            pnl=-550.0,  # Large loss
        )

        call_kwargs = trade_logger._db.add_journal_entry.call_args[1]
        assert call_kwargs["mood"] == "frustrated"


class TestNoteFormatting:
    """Test journal note formatting."""

    def test_format_entry_note(self, sample_entry_context):
        """Entry note includes symbol, side, price, regime, bias, scores."""
        logger = TradeLogger(MagicMock())
        note = logger._format_entry_note(sample_entry_context)

        assert "MCL" in note
        assert "buy" in note.lower()
        assert "85.50" in note
        assert "TRENDING_BULL" in note
        assert "bullish" in note.lower()
        assert "0.78" in note  # composite score
        assert "0.85" in note  # bull score

    def test_format_entry_tags(self, sample_entry_context):
        """Entry tags include regime, bias, confidence, stage."""
        logger = TradeLogger(MagicMock())
        tags = logger._format_entry_tags(sample_entry_context)

        assert "entry" in tags
        assert "regime_bull" in tags
        assert "bias_bull" in tags
        assert "high_confidence" in tags
        assert "debate_driven" in tags

    def test_format_exit_note_winning(self, sample_entry_context, sample_exit_context):
        """Exit note includes P&L, time in trade, and exit reason."""
        logger = TradeLogger(MagicMock())
        note = logger._format_exit_note(sample_entry_context, sample_exit_context)

        assert "87.25" in note
        assert "+175.00" in note  # Positive P&L
        assert "Exit Reason" in note

    def test_format_exit_tags_winning(self, sample_entry_context, sample_exit_context):
        """Exit tags include winning_trade."""
        logger = TradeLogger(MagicMock())
        tags = logger._format_exit_tags(sample_entry_context, sample_exit_context)

        assert "exit" in tags
        assert "winning_trade" in tags

    def test_format_exit_tags_losing(self, sample_entry_context):
        """Exit tags include losing_trade for negative P&L."""
        logger = TradeLogger(MagicMock())
        exit_ctx = TradeExitContext(
            trade_id="trade-001",
            exit_price=80.00,
            exit_time="2026-04-22T16:45:00Z",
            pnl=-250.0,
        )
        tags = logger._format_exit_tags(sample_entry_context, exit_ctx)

        assert "exit" in tags
        assert "losing_trade" in tags


class TestPostTradeAnalysis:
    """Test post-trade analysis computation."""

    def test_compute_exit_reason_profit_target(self, sample_entry_context, sample_exit_context):
        """compute_exit_reason returns "Profit Target Hit" for winning trades."""
        logger = TradeLogger(MagicMock())
        reason = logger._compute_exit_reason(sample_entry_context, sample_exit_context)
        assert reason == "Profit Target Hit"

    def test_compute_exit_reason_stop_loss(self, sample_entry_context):
        """compute_exit_reason returns "Stop Loss Hit" for large losses."""
        logger = TradeLogger(MagicMock())
        exit_ctx = TradeExitContext(
            trade_id="trade-001",
            exit_price=80.00,
            exit_time="2026-04-22T16:45:00Z",
            pnl=-500.0,
        )
        reason = logger._compute_exit_reason(sample_entry_context, exit_ctx)
        assert reason == "Stop Loss Hit"

    def test_compute_post_analysis(self, sample_entry_context, sample_exit_context):
        """compute_post_analysis generates multi-part commentary."""
        logger = TradeLogger(MagicMock())
        analysis = logger._compute_post_analysis(sample_entry_context, sample_exit_context)

        # Should have multiple signals
        assert "|" in analysis
        assert "✓" in analysis or "✗" in analysis

    def test_compute_time_in_trade(self, sample_entry_context, sample_exit_context):
        """compute_time_in_trade returns human-readable duration."""
        logger = TradeLogger(MagicMock())
        duration = logger._compute_time_in_trade(sample_entry_context, sample_exit_context)

        # Should be something like "1h 15m"
        assert "h" in duration or "m" in duration


class TestEndToEnd:
    """End-to-end test: entry → exit lifecycle."""

    def test_full_trade_lifecycle(self, mock_db_with_decision):
        """Full trade lifecycle: entry logged, then exit logged."""
        logger = TradeLogger(mock_db_with_decision)

        # Open trade
        logger.on_trade_opened(
            trade_id="trade-e2e-001",
            symbol="MCL",
            side="buy",
            quantity=1.0,
            entry_price=85.50,
            entry_time="2026-04-22T15:30:00Z",
        )

        # Verify entry cached and logged
        assert "trade-e2e-001" in logger._entry_cache
        assert mock_db_with_decision.add_journal_entry.call_count == 1

        # Close trade
        logger.on_trade_closed(
            trade_id="trade-e2e-001",
            exit_price=87.25,
            exit_time="2026-04-22T16:45:00Z",
            pnl=175.0,
        )

        # Verify exit logged and cache cleared
        assert "trade-e2e-001" not in logger._entry_cache
        assert mock_db_with_decision.add_journal_entry.call_count == 2

        # Inspect both journal calls
        calls = mock_db_with_decision.add_journal_entry.call_args_list

        # First call (entry)
        entry_call = calls[0][1]
        assert entry_call["trade_id"] == "trade-e2e-001"
        assert "ENTRY" in entry_call["note"]
        assert entry_call["tags"] and "entry" in entry_call["tags"]

        # Second call (exit)
        exit_call = calls[1][1]
        assert exit_call["trade_id"] == "trade-e2e-001"
        assert "EXIT" in exit_call["note"]
        assert exit_call["tags"] and "exit" in exit_call["tags"]

    def test_multiple_concurrent_trades(self, mock_db_with_decision):
        """TradeLogger can handle multiple concurrent open trades."""
        logger = TradeLogger(mock_db_with_decision)

        # Open 3 concurrent trades
        trades = [
            ("trade-001", "MCL", 85.50),
            ("trade-002", "MNQ", 16500.00),
            ("trade-003", "MES", 5200.00),
        ]

        for trade_id, symbol, price in trades:
            logger.on_trade_opened(
                trade_id=trade_id,
                symbol=symbol,
                side="buy",
                quantity=1.0,
                entry_price=price,
                entry_time="2026-04-22T15:30:00Z",
            )

        # All cached
        assert len(logger._entry_cache) == 3

        # Close middle trade
        logger.on_trade_closed(
            trade_id="trade-002",
            exit_price=16550.00,
            exit_time="2026-04-22T16:45:00Z",
            pnl=5000.0,
        )

        # Other two still cached
        assert len(logger._entry_cache) == 2
        assert "trade-001" in logger._entry_cache
        assert "trade-003" in logger._entry_cache


class TestModuleLevelConvenience:
    """Test module-level convenience functions."""

    def test_auto_log_trade_entry(self, mock_db_manager):
        """auto_log_trade_entry uses module-level logger."""
        import logging.trade_logger as tl_module

        # Clear module state
        tl_module._logger = None

        # Initialize
        initialize_trade_logger(mock_db_manager)

        # Call convenience function
        auto_log_trade_entry(
            trade_id="trade-001",
            symbol="MCL",
            side="buy",
            quantity=1.0,
            entry_price=85.50,
            entry_time="2026-04-22T15:30:00Z",
        )

        # Verify logged
        mock_db_manager.add_journal_entry.assert_called_once()

    def test_auto_log_trade_exit(self, mock_db_manager):
        """auto_log_trade_exit uses module-level logger."""
        import logging.trade_logger as tl_module

        # Clear and reinitialize
        tl_module._logger = None
        logger = initialize_trade_logger(mock_db_manager)

        # Pre-populate cache
        logger._entry_cache["trade-001"] = TradeEntryContext(
            trade_id="trade-001",
            symbol="MCL",
            side="buy",
            quantity=1.0,
            entry_price=85.50,
            entry_time="2026-04-22T15:30:00Z",
        )

        # Call convenience function
        auto_log_trade_exit(
            trade_id="trade-001",
            exit_price=87.25,
            exit_time="2026-04-22T16:45:00Z",
            pnl=175.0,
        )

        # Verify logged
        mock_db_manager.add_journal_entry.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
