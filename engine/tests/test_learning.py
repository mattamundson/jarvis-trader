"""
Unit tests for Learning System (Phase 6).
Covers: PatternExtractor, TradeClassifier, StrategyTuner, SessionMemory
"""

from datetime import datetime

import pytest

from learning._experimental.pattern_extractor import Pattern, PatternExtractor
from learning._experimental.session_memory import Lesson, SessionMemory
from learning._experimental.strategy_tuner import StrategyTuner, Suggestion
from learning._experimental.trade_classifier import TradeClassification, TradeClassifier


class TestPatternExtractor:
    """Tests for PatternExtractor (US-011)."""

    @pytest.fixture
    def extractor(self):
        """Create a PatternExtractor instance."""
        return PatternExtractor()

    @pytest.fixture
    def sample_trades(self):
        """Sample trades for testing."""
        return [
            {
                "id": "t1",
                "symbol": "MNQ",
                "entry_time": "2026-04-01 09:30:00",
                "exit_time": "2026-04-01 10:15:00",
                "pnl": 150.0,
                "return_pct": 0.05,
                "regime": "TRENDING",
                "won": True,
            },
            {
                "id": "t2",
                "symbol": "MNQ",
                "entry_time": "2026-04-01 10:45:00",
                "exit_time": "2026-04-01 11:30:00",
                "pnl": -75.0,
                "return_pct": -0.025,
                "regime": "CHOPPY",
                "won": False,
            },
            {
                "id": "t3",
                "symbol": "MNQ",
                "entry_time": "2026-04-01 09:15:00",
                "exit_time": "2026-04-01 09:45:00",
                "pnl": 200.0,
                "return_pct": 0.067,
                "regime": "TRENDING",
                "won": True,
            },
            {
                "id": "t4",
                "symbol": "MNQ",
                "entry_time": "2026-04-01 09:50:00",
                "exit_time": "2026-04-01 10:30:00",
                "pnl": 120.0,
                "return_pct": 0.04,
                "regime": "TRENDING",
                "won": True,
            },
        ]

    def test_extract_returns_list(self, extractor, sample_trades):
        """Test that extract() returns a list."""
        result = extractor.extract(sample_trades)
        assert isinstance(result, list)

    def test_extract_empty_trades(self, extractor):
        """Test extract with empty trades list."""
        result = extractor.extract([])
        assert result == []

    def test_extract_time_patterns(self, extractor):
        """Test time-of-day pattern extraction."""
        trades = [
            {
                "id": f"t{i}",
                "entry_time": "2026-04-01 09:30:00",
                "won": True,
                "regime": "TRENDING",
                "return_pct": 0.01,
            }
            for i in range(5)
        ] + [
            {
                "id": f"t{i}",
                "entry_time": "2026-04-01 10:30:00",
                "won": False,
                "regime": "CHOPPY",
                "return_pct": -0.01,
            }
            for i in range(5, 8)
        ]
        result = extractor.extract(trades)
        time_patterns = [p for p in result if "hour" in p.name.lower()]
        assert len(time_patterns) > 0
        for pattern in time_patterns:
            assert 0.0 <= pattern.win_rate <= 1.0

    def test_extract_regime_patterns(self, extractor, sample_trades):
        """Test regime-based pattern extraction."""
        result = extractor.extract(sample_trades)
        regime_patterns = [p for p in result if "regime" in p.name.lower()]
        assert len(regime_patterns) > 0
        for pattern in regime_patterns:
            assert "regime" in pattern.conditions.keys()

    def test_pattern_structure(self, extractor, sample_trades):
        """Test that Pattern has correct structure."""
        result = extractor.extract(sample_trades)
        for pattern in result:
            assert isinstance(pattern, Pattern)
            assert pattern.name
            assert isinstance(pattern.frequency, int)
            assert 0.0 <= pattern.win_rate <= 1.0
            assert isinstance(pattern.conditions, dict)

    def test_min_frequency_threshold(self, extractor):
        """Test that patterns below MIN_PATTERN_FREQUENCY are not returned."""
        trades = [
            {
                "id": "t1",
                "entry_time": "2026-04-01 15:00:00",
                "won": True,
                "regime": "TRENDING",
                "return_pct": 0.01,
            },
        ]
        result = extractor.extract(trades)
        assert len(result) == 0

    def test_datetime_parsing(self, extractor):
        """Test various datetime formats are parsed correctly."""
        trades = [
            {
                "id": "t1",
                "entry_time": datetime(2026, 4, 1, 9, 30),
                "won": True,
                "regime": "TRENDING",
                "return_pct": 0.01,
            },
            {
                "id": "t2",
                "entry_time": "2026-04-01T09:45:00Z",
                "won": True,
                "regime": "TRENDING",
                "return_pct": 0.01,
            },
            {
                "id": "t3",
                "entry_time": "2026-04-01T10:00:00",
                "won": True,
                "regime": "TRENDING",
                "return_pct": 0.01,
            },
        ]
        result = extractor.extract(trades)
        assert len(result) > 0


class TestTradeClassifier:
    """Tests for TradeClassifier (US-012)."""

    @pytest.fixture
    def classifier(self):
        """Create a TradeClassifier instance."""
        return TradeClassifier()

    @pytest.fixture
    def winning_trade(self):
        """A winning trade."""
        return {
            "id": "win1",
            "pnl": 300.0,
            "risk": 100.0,
            "entry_price": 100.0,
            "exit_price": 103.0,
            "time_in_trade": 1.0,
            "target_atr": 50.0,
            "regime": "TRENDING",
            "regime_aligned": True,
            "slippage": 0.5,
            "entry_confidence": 0.9,
            "won": True,
        }

    @pytest.fixture
    def losing_trade(self):
        """A losing trade."""
        return {
            "id": "loss1",
            "pnl": -100.0,
            "risk": 100.0,
            "entry_price": 100.0,
            "exit_price": 99.0,
            "time_in_trade": 0.5,
            "target_atr": 50.0,
            "regime": "CHOPPY",
            "regime_aligned": False,
            "slippage": 2.0,
            "entry_confidence": 0.5,
            "won": False,
        }

    def test_classify_returns_classification(self, classifier, winning_trade):
        """Test that classify() returns TradeClassification."""
        result = classifier.classify(winning_trade)
        assert isinstance(result, TradeClassification)

    def test_classification_has_grade(self, classifier, winning_trade):
        """Test that classification includes a letter grade."""
        result = classifier.classify(winning_trade)
        assert result.grade in ["A", "B", "C", "D", "F"]

    def test_classification_has_qualities(self, classifier, winning_trade):
        """Test that classification includes quality scores."""
        result = classifier.classify(winning_trade)
        assert 0.0 <= result.setup_quality <= 1.0
        assert 0.0 <= result.execution_quality <= 1.0

    def test_winning_trade_grades_high(self, classifier, winning_trade):
        """Test that a good winning trade gets a high grade."""
        result = classifier.classify(winning_trade)
        assert result.grade in ["A", "B"]

    def test_losing_trade_grades_low(self, classifier, losing_trade):
        """Test that a losing trade gets a low grade."""
        result = classifier.classify(losing_trade)
        assert result.grade in ["D", "F"]

    def test_classification_has_factors(self, classifier, winning_trade):
        """Test that classification includes explanation factors."""
        result = classifier.classify(winning_trade)
        assert isinstance(result.factors, list)
        assert len(result.factors) > 0

    def test_r_multiple_calculation(self, classifier):
        """Test R-multiple calculation."""
        trade = {
            "id": "t1",
            "pnl": 300.0,
            "risk": 100.0,
            "entry_price": 100.0,
            "entry_confidence": 0.8,
            "regime_aligned": True,
            "time_in_trade": 2.0,
            "slippage": 0.1,
            "won": True,
        }
        result = classifier.classify(trade)
        assert "3" in str(result.factors) or result.grade == "A"

    def test_slippage_impacts_execution(self, classifier):
        """Test that high slippage lowers execution quality."""
        good_exec = {
            "id": "g1",
            "pnl": 100.0,
            "risk": 100.0,
            "entry_price": 100.0,
            "entry_confidence": 0.8,
            "regime_aligned": True,
            "time_in_trade": 2.0,
            "slippage": 0.1,
            "won": True,
        }
        bad_exec = {
            "id": "b1",
            "pnl": 100.0,
            "risk": 100.0,
            "entry_price": 100.0,
            "entry_confidence": 0.8,
            "regime_aligned": True,
            "time_in_trade": 2.0,
            "slippage": 5.0,
            "won": True,
        }
        good_result = classifier.classify(good_exec)
        bad_result = classifier.classify(bad_exec)
        assert good_result.execution_quality > bad_result.execution_quality


class TestStrategyTuner:
    """Tests for StrategyTuner (US-013)."""

    @pytest.fixture
    def tuner(self):
        """Create a StrategyTuner instance."""
        return StrategyTuner()

    @pytest.fixture
    def good_trades(self):
        """Trades with high win rate."""
        return [{"id": f"t{i}", "pnl": 200.0, "risk": 100.0, "won": True} for i in range(20)]

    @pytest.fixture
    def bad_trades(self):
        """Trades with low win rate."""
        return [{"id": f"t{i}", "pnl": -100.0, "risk": 100.0, "won": False} for i in range(20)]

    @pytest.fixture
    def current_params(self):
        """Current strategy parameters."""
        return {
            "STC_OS": 15,
            "STC_OB": 83,
            "STOP_ATR": 0.7,
            "T1_ATR": 1.0,
            "T2_ATR": 1.8,
        }

    def test_suggest_adjustments_returns_list(self, tuner, good_trades, current_params):
        """Test that suggest_adjustments() returns a list."""
        result = tuner.suggest_adjustments(good_trades, current_params)
        assert isinstance(result, list)

    def test_insufficient_trades_returns_empty(self, tuner, current_params):
        """Test that insufficient trades returns empty suggestions."""
        result = tuner.suggest_adjustments([{"pnl": 100, "risk": 100, "won": True}], current_params)
        assert result == []

    def test_no_params_returns_empty(self, tuner, good_trades):
        """Test that missing params returns empty."""
        result = tuner.suggest_adjustments(good_trades, {})
        assert result == []

    def test_low_win_rate_suggests_changes(self, tuner, bad_trades, current_params):
        """Test that low win rate triggers suggestions."""
        result = tuner.suggest_adjustments(bad_trades, current_params)
        assert len(result) > 0
        assert all(isinstance(s, Suggestion) for s in result)

    def test_suggestions_are_conservative(self, tuner, bad_trades, current_params):
        """Test that suggestions are bounded within reasonable limits."""
        result = tuner.suggest_adjustments(bad_trades, current_params)
        for suggestion in result:
            if suggestion.param_name in ["STC_OS", "STC_OB"]:
                current = suggestion.current_value
                suggested = suggestion.suggested_value
                change_pct = abs(suggested - current) / max(abs(current), 1)
                assert change_pct <= 0.15
            elif suggestion.param_name.startswith("T"):
                current = suggestion.current_value
                suggested = suggestion.suggested_value
                assert suggested >= 0.5

    def test_never_suggests_safety_params(self, tuner, bad_trades):
        """Test that safety parameters are never suggested for change."""
        safety_aware_params = {
            **{f"SAFETY_{i}": 1.0 for i in range(5)},
            "MAX_POSITION_SIZE_PCT": 0.05,
            "MAX_DAILY_LOSS_PCT": 0.02,
            "STC_OS": 15,
        }
        result = tuner.suggest_adjustments(bad_trades, safety_aware_params)
        for suggestion in result:
            assert not tuner.is_safety_param(suggestion.param_name)

    def test_tunable_params_recognized(self, tuner):
        """Test that tunable parameters are recognized."""
        assert tuner.is_tunable_param("STC_OS")
        assert tuner.is_tunable_param("STOP_ATR")
        assert not tuner.is_tunable_param("MAX_POSITION_SIZE_PCT")

    def test_clamp_suggestion_respects_bounds(self, tuner):
        """Test that clamp_suggestion respects min/max bounds."""
        clamped = tuner.clamp_suggestion("STC_OS", 5)
        assert clamped >= 10
        clamped = tuner.clamp_suggestion("STC_OS", 100)
        assert clamped <= 20

    def test_suggestion_structure(self, tuner, bad_trades, current_params):
        """Test that suggestions have correct structure."""
        result = tuner.suggest_adjustments(bad_trades, current_params)
        for suggestion in result:
            assert isinstance(suggestion, Suggestion)
            assert suggestion.param_name
            assert suggestion.confidence > 0
            assert suggestion.reason


class TestSessionMemory:
    """Tests for SessionMemory (US-014)."""

    @pytest.fixture
    def memory(self):
        """Create a SessionMemory instance."""
        mem = SessionMemory()
        mem.clear_lessons()
        return mem

    @pytest.fixture
    def sample_trades(self):
        """Sample trades for a session."""
        return [
            {"id": "t1", "pnl": 100.0, "won": True},
            {"id": "t2", "pnl": -50.0, "won": False},
            {"id": "t3", "pnl": 150.0, "won": True},
        ]

    def test_record_session_returns_bool(self, memory, sample_trades):
        """Test that record_session returns boolean."""
        result = memory.record_session(
            date="2026-04-01",
            trades=sample_trades,
            market_conditions={"regime": "TRENDING"},
            lessons=["Lesson 1", "Lesson 2"],
        )
        assert isinstance(result, bool)

    def test_record_session_stores_lessons(self, memory, sample_trades):
        """Test that record_session stores lessons."""
        memory.record_session(
            date="2026-04-01",
            trades=sample_trades,
            market_conditions={"regime": "TRENDING"},
            lessons=["Test lesson"],
        )
        assert len(memory.lessons) > 0

    def test_get_lessons_filters_by_condition(self, memory, sample_trades):
        """Test that get_lessons filters by market condition."""
        memory.record_session(
            date="2026-04-01",
            trades=sample_trades,
            market_conditions={"regime": "TRENDING"},
            lessons=["Trending lesson"],
        )
        memory.record_session(
            date="2026-04-02",
            trades=sample_trades,
            market_conditions={"regime": "CHOPPY"},
            lessons=["Choppy lesson"],
        )

        trending_lessons = memory.get_lessons("TRENDING")
        choppy_lessons = memory.get_lessons("CHOPPY")

        assert len(trending_lessons) > 0
        assert len(choppy_lessons) > 0
        assert all(lesson.condition == "TRENDING" for lesson in trending_lessons)
        assert all(lesson.condition == "CHOPPY" for lesson in choppy_lessons)

    def test_lesson_structure(self, memory, sample_trades):
        """Test that Lesson has correct structure."""
        memory.record_session(
            date="2026-04-01",
            trades=sample_trades,
            market_conditions={"regime": "TRENDING"},
            lessons=["Test"],
        )
        lesson = memory.lessons[0]
        assert isinstance(lesson, Lesson)
        assert lesson.date == "2026-04-01"
        assert lesson.condition == "TRENDING"
        assert lesson.lesson_text == "Test"
        assert isinstance(lesson.trades_affected, list)

    def test_outcome_classification(self, memory, sample_trades):
        """Test that outcome is correctly classified."""
        memory.record_session(
            date="2026-04-01",
            trades=sample_trades,
            market_conditions={"regime": "TRENDING"},
            lessons=["Test"],
        )
        lesson = memory.lessons[0]
        assert lesson.outcome in ["positive", "negative", "neutral"]

    def test_get_all_lessons(self, memory, sample_trades):
        """Test that get_all_lessons returns all lessons."""
        memory.record_session(
            date="2026-04-01",
            trades=sample_trades,
            market_conditions={"regime": "TRENDING"},
            lessons=["Lesson 1", "Lesson 2"],
        )
        all_lessons = memory.get_all_lessons()
        assert len(all_lessons) == 2

    def test_persistence_to_json(self, memory, sample_trades):
        """Test that lessons persist to JSON file."""
        memory.record_session(
            date="2026-04-01",
            trades=sample_trades,
            market_conditions={"regime": "TRENDING"},
            lessons=["Persisted lesson"],
        )

        new_memory = SessionMemory()
        assert len(new_memory.lessons) > 0
        assert any("Persisted lesson" in lesson.lesson_text for lesson in new_memory.lessons)

    def test_clear_lessons(self, memory, sample_trades):
        """Test that clear_lessons removes all lessons."""
        memory.record_session(
            date="2026-04-01",
            trades=sample_trades,
            market_conditions={"regime": "TRENDING"},
            lessons=["Will be cleared"],
        )
        assert len(memory.lessons) > 0
        memory.clear_lessons()
        assert len(memory.lessons) == 0

    def test_invalid_condition_returns_empty(self, memory, sample_trades):
        """Test that invalid condition returns empty list."""
        memory.record_session(
            date="2026-04-01",
            trades=sample_trades,
            market_conditions={"regime": "TRENDING"},
            lessons=["Test"],
        )
        result = memory.get_lessons("NONEXISTENT")
        assert result == []


class TestFeedback:
    """Tests for Feedback module (US-LEARN-002)."""

    @pytest.mark.asyncio
    async def test_process_winning_trade(self):
        """Test feedback generation for a winning trade."""
        from learning.feedback import process_trade_outcome

        feedback = await process_trade_outcome(
            trade_id="test_win_001",
            symbol="MCL",
            pnl=150.0,
            entry_price=85.50,
            exit_price=87.25,
            entry_time="2026-04-01T10:00:00Z",
            exit_time="2026-04-01T11:30:00Z",
            action="long",
        )

        assert feedback.trade_id == "test_win_001"
        assert feedback.symbol == "MCL"
        assert feedback.pnl == 150.0
        assert feedback.entry_price == 85.50
        assert feedback.exit_price == 87.25
        assert feedback.action == "long"
        assert hasattr(feedback, "lesson_type")
        assert feedback.lesson_type == "winning_trade"
        assert "Winning trade" in feedback.lesson_text

    @pytest.mark.asyncio
    async def test_process_losing_trade(self):
        """Test feedback generation for a losing trade."""
        from learning.feedback import process_trade_outcome

        feedback = await process_trade_outcome(
            trade_id="test_loss_001",
            symbol="MNQ",
            pnl=-75.0,
            entry_price=18500.00,
            exit_price=18492.00,
            entry_time="2026-04-01T14:00:00Z",
            exit_time="2026-04-01T14:45:00Z",
            action="short",
        )

        assert feedback.trade_id == "test_loss_001"
        assert feedback.pnl == -75.0
        assert feedback.lesson_type == "losing_trade"
        assert "Losing trade" in feedback.lesson_text

    @pytest.mark.asyncio
    async def test_process_breakeven_trade(self):
        """Test feedback generation for a breakeven trade."""
        from learning.feedback import process_trade_outcome

        feedback = await process_trade_outcome(
            trade_id="test_be_001",
            symbol="MES",
            pnl=0.0,
            entry_price=5400.00,
            exit_price=5400.00,
            entry_time="2026-04-01T09:00:00Z",
            exit_time="2026-04-01T10:00:00Z",
            action="long",
        )

        assert feedback.pnl == 0.0
        assert feedback.lesson_type == "breakeven_trade"
        assert "Breakeven trade" in feedback.lesson_text

    @pytest.mark.asyncio
    async def test_feedback_to_dict(self):
        """Test that feedback can be serialized to dict."""
        from learning.feedback import process_trade_outcome

        feedback = await process_trade_outcome(
            trade_id="test_dict_001",
            symbol="MCL",
            pnl=50.0,
            entry_price=85.00,
            exit_price=86.00,
            entry_time="2026-04-01T10:00:00Z",
            exit_time="2026-04-01T11:00:00Z",
            action="long",
        )

        d = feedback.to_dict()
        assert isinstance(d, dict)
        assert d["trade_id"] == "test_dict_001"
        assert d["symbol"] == "MCL"
        assert d["pnl"] == 50.0
        assert "generated_at" in d


class TestPatterns:
    """Tests for Patterns module (US-LEARN-003)."""

    def test_trade_pattern_creation(self):
        """Test that TradePattern objects are created correctly."""
        from learning.patterns import TradePattern

        pattern = TradePattern(
            symbol="MCL",
            pattern_type="symbol_winner",
            conditions={"symbol": "MCL", "outcome": "win"},
            win_count=5,
            loss_count=2,
        )

        assert pattern.symbol == "MCL"
        assert pattern.pattern_type == "symbol_winner"
        assert pattern.sample_count == 7
        assert pattern.win_rate == round(5 / 7, 3)

    def test_trade_pattern_to_dict(self):
        """Test that TradePattern can be serialized to dict."""
        from learning.patterns import TradePattern

        pattern = TradePattern(
            symbol="MNQ",
            pattern_type="time_window_10",
            conditions={"symbol": "MNQ", "entry_hour": 10},
            win_count=3,
            loss_count=1,
        )

        d = pattern.to_dict()
        assert isinstance(d, dict)
        assert d["symbol"] == "MNQ"
        assert d["pattern_type"] == "time_window_10"
        assert d["sample_count"] == 4
        assert d["win_rate"] == round(3 / 4, 3)

    @pytest.mark.asyncio
    async def test_update_patterns_from_feedback_winner(self):
        """Test pattern update from winning trade feedback."""
        from learning.patterns import update_patterns_from_feedback

        feedback = {
            "symbol": "MCL",
            "pnl": 150.0,
            "entry_time": "2026-04-01T10:30:00Z",
        }

        patterns = await update_patterns_from_feedback(feedback)
        assert patterns is not None
        assert len(patterns) >= 2  # At least symbol pattern + time pattern

        # Check first pattern (symbol winner)
        assert patterns[0].symbol == "MCL"
        assert "winner" in patterns[0].pattern_type
        assert patterns[0].win_count == 1
        assert patterns[0].loss_count == 0

    @pytest.mark.asyncio
    async def test_update_patterns_from_feedback_loser(self):
        """Test pattern update from losing trade feedback."""
        from learning.patterns import update_patterns_from_feedback

        feedback = {
            "symbol": "MNQ",
            "pnl": -75.0,
            "entry_time": "2026-04-01T14:45:00Z",
        }

        patterns = await update_patterns_from_feedback(feedback)
        assert patterns is not None

        # Check first pattern (symbol loser)
        assert patterns[0].symbol == "MNQ"
        assert "loser" in patterns[0].pattern_type
        assert patterns[0].win_count == 0
        assert patterns[0].loss_count == 1

    @pytest.mark.asyncio
    async def test_update_patterns_missing_symbol(self):
        """Test pattern update gracefully handles missing symbol."""
        from learning.patterns import update_patterns_from_feedback

        feedback = {
            "pnl": 100.0,
            "entry_time": "2026-04-01T10:00:00Z",
        }

        patterns = await update_patterns_from_feedback(feedback)
        assert patterns is None  # Should return None when symbol is missing
