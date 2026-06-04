"""
Tests for TradingMemoryConsolidator — /dream nightly pattern consolidation.
"""

import os
import sys
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from learning.consolidator import TradingMemoryConsolidator


class TestConsolidator:
    def setup_method(self):
        self.consolidator = TradingMemoryConsolidator(db_manager=None, llm_client=None)

    def _make_trades(self, n_wins=3, n_losses=2):
        trades = []
        for i in range(n_wins):
            trades.append(
                {
                    "side": "long",
                    "pnl": 50.0,
                    "entry_time": f"2026-04-02T{9 + i:02d}:35:00",
                    "symbol": "MES",
                }
            )
        for i in range(n_losses):
            trades.append(
                {
                    "side": "long",
                    "pnl": -30.0,
                    "entry_time": f"2026-04-02T{14 + i:02d}:00:00",
                    "symbol": "MES",
                }
            )
        return trades

    # ── consolidate_daily ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_consolidate_no_trades_returns_no_trades(self):
        result = await self.consolidator.consolidate_daily("2026-01-01")
        assert result["status"] == "no_trades"
        assert result["date"] == "2026-01-01"
        assert result["patterns"] == []
        assert result["accuracy"] == {}

    @pytest.mark.asyncio
    async def test_consolidate_defaults_to_today(self):
        # consolidate_daily with no arg defaults to today — just check it
        # returns no_trades since db_manager is None (no real DB)
        result = await self.consolidator.consolidate_daily()
        assert "date" in result
        assert result["status"] == "no_trades"

    # ── _extract_patterns ──────────────────────────────────────────────────────

    def test_extract_patterns_from_trades(self):
        trades = self._make_trades(3, 2)
        patterns = self.consolidator._extract_patterns(trades)
        assert isinstance(patterns, list)

    def test_extract_patterns_time_of_day(self):
        """Trades at the same hour with >60% win rate should generate a time pattern."""
        trades = [
            {
                "side": "long",
                "pnl": 100.0,
                "entry_time": "2026-04-02T09:35:00",
                "symbol": "MES",
            },
            {
                "side": "long",
                "pnl": 80.0,
                "entry_time": "2026-04-02T09:40:00",
                "symbol": "MES",
            },
            {
                "side": "long",
                "pnl": -20.0,
                "entry_time": "2026-04-02T09:50:00",
                "symbol": "MES",
            },
        ]
        patterns = self.consolidator._extract_patterns(trades)
        time_patterns = [p for p in patterns if p["category"] == "time"]
        assert any("hour_09" in p["pattern_type"] for p in time_patterns)

    def test_extract_patterns_direction_bias(self):
        """Trades with same direction qualify for a direction bias pattern."""
        trades = self._make_trades(3, 2)  # 5 long trades
        patterns = self.consolidator._extract_patterns(trades)
        regime_patterns = [p for p in patterns if p["category"] == "regime"]
        assert any("direction_long" in p["pattern_type"] for p in regime_patterns)

    def test_extract_patterns_returns_list(self):
        assert self.consolidator._extract_patterns([]) == []

    def test_extract_patterns_short_direction(self):
        trades = [
            {
                "side": "short",
                "pnl": 50.0,
                "entry_time": "2026-04-02T10:00:00",
                "symbol": "MES",
            },
            {
                "side": "short",
                "pnl": 60.0,
                "entry_time": "2026-04-02T10:05:00",
                "symbol": "MES",
            },
        ]
        patterns = self.consolidator._extract_patterns(trades)
        names = [p["pattern_type"] for p in patterns]
        assert any("direction_short" in n for n in names)

    # ── _score_signal_accuracy ─────────────────────────────────────────────────

    def test_score_accuracy_correct(self):
        trades = self._make_trades(3, 2)  # 3 wins, 2 losses = 60%
        accuracy = self.consolidator._score_signal_accuracy(trades)
        assert accuracy["total"] == 5
        assert accuracy["wins"] == 3
        assert accuracy["losses"] == 2
        assert accuracy["accuracy_pct"] == 60.0

    def test_score_accuracy_empty(self):
        acc = self.consolidator._score_signal_accuracy([])
        assert acc["total"] == 0

    def test_score_accuracy_all_wins(self):
        trades = [{"pnl": 100.0} for _ in range(4)]
        acc = self.consolidator._score_signal_accuracy(trades)
        assert acc["wins"] == 4
        assert acc["accuracy_pct"] == 100.0

    def test_score_accuracy_all_losses(self):
        trades = [{"pnl": -50.0} for _ in range(3)]
        acc = self.consolidator._score_signal_accuracy(trades)
        assert acc["wins"] == 0
        assert acc["accuracy_pct"] == 0.0

    def test_score_accuracy_total_pnl(self):
        trades = [{"pnl": 100.0}, {"pnl": -40.0}]
        acc = self.consolidator._score_signal_accuracy(trades)
        assert acc["total_pnl"] == 60.0

    # ── get_active_patterns / get_signal_accuracy (no DB) ────────────────────

    @pytest.mark.asyncio
    async def test_get_active_patterns_no_db(self):
        result = await self.consolidator.get_active_patterns()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_signal_accuracy_no_db(self):
        result = await self.consolidator.get_signal_accuracy(30)
        assert result["total"] == 0
        assert result["days"] == 30

    @pytest.mark.asyncio
    async def test_get_signal_accuracy_custom_days(self):
        result = await self.consolidator.get_signal_accuracy(7)
        assert result["days"] == 7

    # ── _upsert_pattern / _prune_stale_patterns (no DB — graceful degradation) ─

    @pytest.mark.asyncio
    async def test_upsert_pattern_no_db_is_noop(self):
        """Should not raise when db_manager is None."""
        pattern = {
            "pattern_type": "test_pattern",
            "category": "time",
            "conditions": "{}",
            "win_count": 1,
            "loss_count": 0,
            "win_rate": 1.0,
            "avg_return": 50.0,
            "frequency": 5,
        }
        await self.consolidator._upsert_pattern(pattern, "2026-04-02")  # no raise

    @pytest.mark.asyncio
    async def test_prune_stale_no_db_is_noop(self):
        """Should not raise when db_manager is None."""
        await self.consolidator._prune_stale_patterns()  # no raise

    # ── pattern field validation ───────────────────────────────────────────────

    def test_pattern_has_required_fields(self):
        trades = self._make_trades(4, 1)  # strong win rate at hours 9-12
        patterns = self.consolidator._extract_patterns(trades)
        for p in patterns:
            assert "pattern_type" in p
            assert "category" in p
            assert "conditions" in p
            assert "win_rate" in p
            assert "avg_return" in p
            assert "frequency" in p

    def test_win_rate_clamped_to_valid_range(self):
        trades = self._make_trades(5, 0)  # all wins
        patterns = self.consolidator._extract_patterns(trades)
        for p in patterns:
            assert 0.0 <= p["win_rate"] <= 1.0
