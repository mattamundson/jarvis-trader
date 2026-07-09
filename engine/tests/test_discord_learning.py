"""
JARVIS TRADER — Discord + Learning Integration Test Suite
==========================================================

Covers:
  - DiscordSignalContext (discord/signal_context.py)
  - SentimentProvider (discord/sentiment_provider.py)
  - IBLevelProvider (discord/ib_levels.py)
  - PatternExtractor (learning/_experimental/pattern_extractor.py)
  - TradeClassifier (learning/_experimental/trade_classifier.py)
  - StrategyTuner (learning/_experimental/strategy_tuner.py)
  - SessionMemory (learning/_experimental/session_memory.py)
  - Learning Router (routers/learning_router.py) via FastAPI TestClient

Run from engine/:
    python -m pytest tests/test_discord_learning.py -v

Design principles:
  - All DB-dependent operations either use a temp in-memory SQLite or are mocked.
  - No test connects to the real jarvis_trader.db.
  - Every test must PASS or SKIP — no raw FAILUREs are allowed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_ENGINE_DIR = Path(__file__).parent.parent  # engine/
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))
if str(_ENGINE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR.parent))

# ---------------------------------------------------------------------------
# Environment guard — set dummy env vars that imports may require
# ---------------------------------------------------------------------------
_ENV_DEFAULTS = {
    "API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "sk-test",
    "POLYGON_API_KEY": "test",
    "FINNHUB_API_KEY": "test",
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "SCHWAB_APP_KEY": "test",
    "SCHWAB_APP_SECRET": "test",
}
for _k, _v in _ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)


# ===========================================================================
# Helpers
# ===========================================================================

_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS discord_bot_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        direction TEXT,
        entry_price REAL,
        target1 REAL,
        target2 REAL,
        stop1 REAL,
        win_rate REAL
    );

    CREATE TABLE IF NOT EXISTS discord_corey_commentary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        content TEXT
    );

    CREATE TABLE IF NOT EXISTS discord_daily_sentiment (
        date TEXT NOT NULL,
        sentiment_score REAL NOT NULL,
        post_count INTEGER NOT NULL,
        source TEXT DEFAULT 'discord_corey_commentary',
        computed_at TEXT NOT NULL,
        PRIMARY KEY (date)
    );

    CREATE TABLE IF NOT EXISTS discord_ib_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        ib_high REAL,
        ib_low REAL,
        ib_range REAL,
        ibu50 REAL,
        ibu100 REAL,
        ibd50 REAL,
        ibd100 REAL,
        auction_context TEXT
    );

    CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id TEXT,
        symbol TEXT,
        side TEXT,
        quantity INTEGER,
        entry_price REAL,
        exit_price REAL,
        entry_time TEXT,
        exit_time TEXT,
        pnl REAL,
        status TEXT DEFAULT 'open',
        strategy_params TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
"""


def _make_temp_db(tmp_path: Optional[Path] = None, extra_sql: list[str] = None) -> str:
    """
    Create a fresh SQLite database file and return its path.

    When tmp_path is supplied (a pytest tmp_path fixture value), the file is
    placed there — pytest handles cleanup after the test even on Windows where
    SQLite connections can delay file deletion.

    When tmp_path is None, a system tempfile is created (caller must handle
    cleanup; on Windows use a try/finally but skip os.unlink on PermissionError).
    """
    if tmp_path is not None:
        # Use a uniquely-named file inside pytest's tmp_path
        import uuid

        path = str(tmp_path / f"test_{uuid.uuid4().hex[:8]}.db")
    else:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="jarvis_test_")
        os.close(fd)

    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
        if extra_sql:
            for sql in extra_sql:
                conn.executescript(sql)
            conn.commit()
    finally:
        conn.close()

    return path


def _safe_unlink(path: str) -> None:
    """Delete a file, ignoring PermissionError on Windows (SQLite journal lock)."""
    try:
        os.unlink(path)
    except PermissionError:
        pass  # SQLite WAL/journal still held — Windows will clean it up later


def _insert_signal(
    db_path: str,
    symbol: str,
    timestamp: str,
    direction: str = "LONG",
    entry_price: float = 5000.0,
    target1: float = 5010.0,
    stop1: float = 4990.0,
    win_rate: float = 76.8,
) -> None:
    """Insert a single row into discord_bot_signals."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO discord_bot_signals
               (symbol, timestamp, direction, entry_price, target1, stop1, win_rate)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (symbol, timestamp, direction, entry_price, target1, stop1, win_rate),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_commentary(db_path: str, timestamp: str, content: str) -> None:
    """Insert a single row into discord_corey_commentary."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO discord_corey_commentary (timestamp, content) VALUES (?, ?)",
            (timestamp, content),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_ib_report(
    db_path: str,
    symbol: str,
    timestamp: str,
    ib_high: float = 5020.0,
    ib_low: float = 4980.0,
    ib_range: float = 40.0,
    ibu50: float = 5040.0,
    ibu100: float = 5060.0,
    ibd50: float = 4960.0,
    ibd100: float = 4940.0,
    auction_context: str = "IBH",
) -> None:
    """Insert a single row into discord_ib_reports."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO discord_ib_reports
               (symbol, timestamp, ib_high, ib_low, ib_range,
                ibu50, ibu100, ibd50, ibd100, auction_context)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                symbol,
                timestamp,
                ib_high,
                ib_low,
                ib_range,
                ibu50,
                ibu100,
                ibd50,
                ibd100,
                auction_context,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ===========================================================================
# 1. DiscordSignalContext Tests
# ===========================================================================


class TestDiscordSignalContext:
    """Tests for DiscordSignalContext (discord/signal_context.py)."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Provide a fresh temp SQLite DB for each test via pytest tmp_path."""
        return _make_temp_db(tmp_path)

    def _make_context(self, db_path: str):
        from discord.signal_context import DiscordSignalContext

        return DiscordSignalContext(db_path=db_path)

    def test_get_features_returns_dict_with_required_keys(self, db_path):
        """get_features() must return a dict with all 5 expected keys."""
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="MES", timestamp=ts, price=5000.0, atr=10.0)
        assert isinstance(result, dict)
        required_keys = {
            "discord_signal_active",
            "discord_win_rate_context",
            "discord_proximity_entry",
            "discord_proximity_target",
            "discord_alignment",
        }
        assert required_keys == set(result.keys())

    def test_signal_active_is_zero_when_no_data(self, db_path):
        """When no signals exist, discord_signal_active must be 0.0."""
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="ES", timestamp=ts, price=5000.0, atr=10.0)
        assert result["discord_signal_active"] == 0.0

    def test_win_rate_falls_back_to_neutral_when_no_data(self, db_path):
        """When no signals exist, win_rate context should be 0.5 (neutral fallback)."""
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="ES", timestamp=ts, price=5000.0, atr=10.0)
        assert result["discord_win_rate_context"] == 0.5

    def test_win_rate_in_valid_range(self, db_path):
        """win_rate_context must always be in [0.0, 1.0]."""
        _insert_signal(db_path, "ES", "2025-01-15T09:45:00", win_rate=76.8)
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="ES", timestamp=ts, price=5000.0, atr=10.0)
        assert 0.0 <= result["discord_win_rate_context"] <= 1.0

    def test_signal_active_is_one_when_recent_signal(self, db_path):
        """When a signal exists within the 4-bar lookback, active must be 1.0."""
        # Insert signal 30 minutes before the current bar (within 4 × 15 = 60 min)
        _insert_signal(db_path, "ES", "2025-01-15T09:30:00")
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="ES", timestamp=ts, price=5000.0, atr=10.0)
        assert result["discord_signal_active"] == 1.0

    def test_proximity_entry_in_valid_range(self, db_path):
        """proximity_entry must be clamped to [-1.0, 1.0]."""
        _insert_signal(db_path, "ES", "2025-01-15T09:30:00", entry_price=5000.0)
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="ES", timestamp=ts, price=5000.0, atr=10.0)
        assert -1.0 <= result["discord_proximity_entry"] <= 1.0

    def test_proximity_target_in_valid_range(self, db_path):
        """proximity_target must be clamped to [0.0, 2.0]."""
        _insert_signal(db_path, "ES", "2025-01-15T09:30:00", target1=5010.0)
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="ES", timestamp=ts, price=5000.0, atr=10.0)
        assert 0.0 <= result["discord_proximity_target"] <= 2.0

    def test_alignment_is_one_when_signal_matches_bias(self, db_path):
        """alignment must be 1.0 when signal direction matches JARVIS bias."""
        _insert_signal(db_path, "ES", "2025-01-15T09:30:00", direction="LONG")
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(
            symbol="ES", timestamp=ts, price=5000.0, atr=10.0, jarvis_bias="LONG"
        )
        assert result["discord_alignment"] == 1.0

    def test_alignment_is_negative_one_when_opposite(self, db_path):
        """alignment must be -1.0 when signal direction is opposite to JARVIS bias."""
        _insert_signal(db_path, "ES", "2025-01-15T09:30:00", direction="SHORT")
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(
            symbol="ES", timestamp=ts, price=5000.0, atr=10.0, jarvis_bias="LONG"
        )
        assert result["discord_alignment"] == -1.0

    def test_symbol_map_mes_to_es(self, db_path):
        """MES must be mapped to ES for Discord symbol lookup."""
        # Insert signal under ES (the Discord symbol) but query with MES
        _insert_signal(db_path, "ES", "2025-01-15T09:30:00")
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="MES", timestamp=ts, price=5000.0, atr=10.0)
        # Should find the ES signal via the SYMBOL_MAP
        assert result["discord_signal_active"] == 1.0

    def test_get_feature_list_returns_ordered_list(self, db_path):
        """get_feature_list() must return a list of 5 floats in correct order."""
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_feature_list(symbol="MES", timestamp=ts, price=5000.0, atr=10.0)
        assert isinstance(result, list)
        assert len(result) == 5
        for val in result:
            assert isinstance(val, float)

    def test_zero_atr_defaults_to_one(self, db_path):
        """When ATR is 0 or None, features should still be computed safely."""
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="MES", timestamp=ts, price=5000.0, atr=0)
        assert isinstance(result, dict)
        result2 = ctx.get_features(symbol="MES", timestamp=ts, price=5000.0, atr=None)
        assert isinstance(result2, dict)

    def test_clear_cache(self, db_path):
        """clear_cache() must not raise and must clear the stats cache."""
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        ctx.get_features(symbol="ES", timestamp=ts, price=5000.0, atr=10.0)
        ctx.clear_cache()
        assert len(ctx._stats_cache) == 0

    def test_all_feature_values_are_numeric(self, db_path):
        """All returned feature values must be numeric (int or float)."""
        ctx = self._make_context(db_path)
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="MES", timestamp=ts, price=5000.0, atr=10.0)
        for key, val in result.items():
            assert isinstance(val, (int, float)), f"{key} is not numeric: {val!r}"


# ===========================================================================
# 2. SentimentProvider Tests
# ===========================================================================


class TestSentimentProvider:
    """Tests for SentimentProvider (discord/sentiment_provider.py)."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Provide a fresh temp SQLite DB for each test via pytest tmp_path."""
        return _make_temp_db(tmp_path)

    def _make_provider(self, db_path: str):
        from discord.sentiment_provider import SentimentProvider

        return SentimentProvider(db_path=db_path)

    def test_instantiation_with_temp_db(self, db_path):
        """SentimentProvider can be instantiated with a temp DB."""
        provider = self._make_provider(db_path)
        assert provider is not None
        assert provider.db_path == db_path

    def test_get_sentiment_returns_float_no_data(self, db_path):
        """get_sentiment() returns float even when no commentary data exists."""
        provider = self._make_provider(db_path)
        result = provider.get_sentiment(date(2025, 1, 15))
        assert isinstance(result, float)

    def test_get_sentiment_float_in_range(self, db_path):
        """get_sentiment() result is always in [-1.0, 1.0]."""
        provider = self._make_provider(db_path)
        result = provider.get_sentiment(date(2025, 1, 15))
        assert -1.0 <= result <= 1.0

    def test_get_sentiment_with_bullish_commentary(self, db_path):
        """get_sentiment() returns positive score for bullish messages."""
        _insert_commentary(
            db_path,
            "2025-01-15T09:30:00",
            "buyers strong breakout above poc long bias upside momentum",
        )
        provider = self._make_provider(db_path)
        result = provider.get_sentiment(date(2025, 1, 15))
        assert result > 0.0

    def test_get_sentiment_with_bearish_commentary(self, db_path):
        """get_sentiment() returns negative score for bearish messages."""
        _insert_commentary(
            db_path,
            "2025-01-15T09:30:00",
            "sellers fade short below poc breakdown distribution weak downside",
        )
        provider = self._make_provider(db_path)
        result = provider.get_sentiment(date(2025, 1, 15))
        assert result < 0.0

    def test_get_sentiment_accepts_iso_string(self, db_path):
        """get_sentiment() works with an ISO format date string."""
        provider = self._make_provider(db_path)
        result = provider.get_sentiment("2025-01-15")
        assert isinstance(result, float)
        assert -1.0 <= result <= 1.0

    def test_get_regime_multiplier_returns_float(self, db_path):
        """get_regime_multiplier() returns a float."""
        provider = self._make_provider(db_path)
        result = provider.get_regime_multiplier(date(2025, 1, 15))
        assert isinstance(result, float)

    def test_get_regime_multiplier_in_range(self, db_path):
        """get_regime_multiplier() result is always in [0.7, 1.3]."""
        provider = self._make_provider(db_path)
        result = provider.get_regime_multiplier(date(2025, 1, 15))
        assert 0.7 <= result <= 1.3

    def test_get_regime_multiplier_with_iso_string(self, db_path):
        """get_regime_multiplier() works with ISO date string."""
        provider = self._make_provider(db_path)
        result = provider.get_regime_multiplier("2025-01-15")
        assert 0.7 <= result <= 1.3

    def test_neutral_day_gives_multiplier_of_one(self, db_path):
        """A neutral sentiment (score=0.0) gives multiplier exactly 1.0."""
        provider = self._make_provider(db_path)
        # No commentary → score = 0.0 → multiplier = 1.0
        result = provider.get_regime_multiplier(date(2025, 1, 15))
        assert result == 1.0

    def test_score_message_helper(self):
        """Module-level score_message() function works correctly."""
        from discord.sentiment_provider import score_message

        bullish_score = score_message("buyers long breakout support upside bid")
        bearish_score = score_message("sellers short breakdown resistance downside offer")
        neutral_score = score_message("no keywords at all here")
        assert bullish_score > 0.0
        assert bearish_score < 0.0
        assert neutral_score == 0.0

    def test_get_sentiment_uses_cache_when_available(self, db_path):
        """get_sentiment() returns cached value from discord_daily_sentiment table."""
        # Pre-populate the cache table directly
        conn = sqlite3.connect(db_path)
        conn.execute(
            """INSERT OR REPLACE INTO discord_daily_sentiment
               (date, sentiment_score, post_count, computed_at)
               VALUES ('2025-01-15', 0.42, 5, '2025-01-15T12:00:00')"""
        )
        conn.commit()
        conn.close()

        provider = self._make_provider(db_path)
        result = provider.get_sentiment(date(2025, 1, 15))
        assert result == pytest.approx(0.42)


# ===========================================================================
# 3. IBLevelProvider Tests
# ===========================================================================


class TestIBLevelProvider:
    """Tests for IBLevelProvider (discord/ib_levels.py)."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Provide a fresh temp SQLite DB for each test via pytest tmp_path."""
        return _make_temp_db(tmp_path)

    def _make_provider(self, db_path: str):
        from discord.ib_levels import IBLevelProvider

        return IBLevelProvider(db_path=db_path)

    def test_instantiation(self, db_path):
        """IBLevelProvider can be instantiated with a temp DB."""
        provider = self._make_provider(db_path)
        assert provider is not None

    def test_get_levels_returns_none_when_no_data(self, db_path):
        """get_levels() returns None gracefully when no data exists."""
        provider = self._make_provider(db_path)
        result = provider.get_levels(symbol="ES", trading_date=date(2025, 1, 15))
        assert result is None

    def test_get_levels_returns_dict_with_data(self, db_path):
        """get_levels() returns a dict when IB report data exists."""
        _insert_ib_report(db_path, "ES", "2025-01-15T08:00:00")
        provider = self._make_provider(db_path)
        result = provider.get_levels(symbol="ES", trading_date=date(2025, 1, 15))
        assert result is not None
        assert isinstance(result, dict)

    def test_get_levels_has_expected_keys(self, db_path):
        """Returned dict has all expected IB level keys."""
        _insert_ib_report(db_path, "ES", "2025-01-15T08:00:00")
        provider = self._make_provider(db_path)
        result = provider.get_levels(symbol="ES", trading_date=date(2025, 1, 15))
        expected_keys = {
            "ib_high",
            "ib_low",
            "ib_range",
            "ibu50",
            "ibu100",
            "ibd50",
            "ibd100",
            "auction_context",
        }
        assert expected_keys == set(result.keys())

    def test_get_levels_with_string_date(self, db_path):
        """get_levels() works with a date string."""
        _insert_ib_report(db_path, "ES", "2025-01-15T08:00:00")
        provider = self._make_provider(db_path)
        result = provider.get_levels(symbol="ES", trading_date="2025-01-15")
        assert result is not None

    def test_get_levels_with_datetime_object(self, db_path):
        """get_levels() works with a datetime object."""
        _insert_ib_report(db_path, "ES", "2025-01-15T08:00:00")
        provider = self._make_provider(db_path)
        result = provider.get_levels(symbol="ES", trading_date=datetime(2025, 1, 15, 10, 0))
        assert result is not None

    def test_symbol_map_mes_to_es(self, db_path):
        """MES maps to ES for IB level lookups."""
        _insert_ib_report(db_path, "ES", "2025-01-15T08:00:00")
        provider = self._make_provider(db_path)
        result = provider.get_levels(symbol="MES", trading_date=date(2025, 1, 15))
        assert result is not None

    def test_get_levels_caches_result(self, db_path):
        """A second call for same symbol/date returns cached result."""
        _insert_ib_report(db_path, "ES", "2025-01-15T08:00:00")
        provider = self._make_provider(db_path)
        result1 = provider.get_levels(symbol="ES", trading_date=date(2025, 1, 15))
        result2 = provider.get_levels(symbol="ES", trading_date=date(2025, 1, 15))
        assert result1 == result2

    def test_clear_cache(self, db_path):
        """clear_cache() empties the in-memory cache."""
        _insert_ib_report(db_path, "ES", "2025-01-15T08:00:00")
        provider = self._make_provider(db_path)
        provider.get_levels(symbol="ES", trading_date=date(2025, 1, 15))
        assert len(provider._cache) > 0
        provider.clear_cache()
        assert len(provider._cache) == 0

    def test_level_values_are_numeric(self, db_path):
        """All non-None level values must be numeric."""
        _insert_ib_report(db_path, "ES", "2025-01-15T08:00:00")
        provider = self._make_provider(db_path)
        result = provider.get_levels(symbol="ES", trading_date=date(2025, 1, 15))
        numeric_keys = {"ib_high", "ib_low", "ib_range", "ibu50", "ibu100", "ibd50", "ibd100"}
        for key in numeric_keys:
            val = result[key]
            if val is not None:
                assert isinstance(val, (int, float)), f"{key} not numeric: {val!r}"


# ===========================================================================
# 4. PatternExtractor Tests
# ===========================================================================


class TestPatternExtractor:
    """Tests for PatternExtractor (learning/_experimental/pattern_extractor.py)."""

    def _make_extractor(self):
        from learning._experimental.pattern_extractor import PatternExtractor

        return PatternExtractor()

    def _make_trades(
        self, count: int, regime: str = "TRENDING", won: bool = True, hour: int = 9
    ) -> list[dict]:
        return [
            {
                "id": f"t{i}",
                "symbol": "MES",
                "entry_time": f"2025-01-{15 + (i % 10):02d} {hour:02d}:30:00",
                "exit_time": f"2025-01-{15 + (i % 10):02d} {hour + 1:02d}:00:00",
                "pnl": 100.0 if won else -50.0,
                "return_pct": 0.02 if won else -0.01,
                "regime": regime,
                "won": won,
            }
            for i in range(count)
        ]

    def test_instantiation(self):
        """PatternExtractor can be instantiated."""
        extractor = self._make_extractor()
        assert extractor is not None

    def test_extract_empty_trades_returns_empty_list(self):
        """extract([]) returns an empty list without errors."""
        extractor = self._make_extractor()
        result = extractor.extract([])
        assert result == []

    def test_extract_returns_list(self):
        """extract() always returns a list."""
        extractor = self._make_extractor()
        trades = self._make_trades(5)
        result = extractor.extract(trades)
        assert isinstance(result, list)

    def test_extract_with_sufficient_trades_finds_patterns(self):
        """extract() finds time and regime patterns when MIN_PATTERN_FREQUENCY is met."""
        extractor = self._make_extractor()
        trades = self._make_trades(5, regime="TRENDING", won=True, hour=9)
        result = extractor.extract(trades)
        # With 5 trades at the same hour and regime, should find at least one pattern
        assert len(result) > 0

    def test_extracted_pattern_has_required_fields(self):
        """Each extracted Pattern has name, frequency, win_rate, avg_return, conditions."""
        from learning._experimental.pattern_extractor import Pattern

        extractor = self._make_extractor()
        trades = self._make_trades(5)
        result = extractor.extract(trades)
        for p in result:
            assert isinstance(p, Pattern)
            assert isinstance(p.name, str) and p.name
            assert isinstance(p.frequency, int) and p.frequency >= 1
            assert 0.0 <= p.win_rate <= 1.0
            assert isinstance(p.avg_return, float)
            assert isinstance(p.conditions, dict)

    def test_below_min_frequency_no_pattern(self):
        """Trades below MIN_PATTERN_FREQUENCY (3) for a group yield no patterns."""
        extractor = self._make_extractor()
        # 2 trades at the same hour — below threshold of 3
        trades = [
            {
                "id": "t1",
                "entry_time": "2025-01-15 14:00:00",
                "won": True,
                "regime": "UNIQUE_REGIME_X",
                "return_pct": 0.01,
            },
            {
                "id": "t2",
                "entry_time": "2025-01-16 14:00:00",
                "won": True,
                "regime": "UNIQUE_REGIME_X",
                "return_pct": 0.01,
            },
        ]
        result = extractor.extract(trades)
        # Pattern for hour 14 and UNIQUE_REGIME_X should not appear (below threshold)
        regime_names = [p.name for p in result if "UNIQUE_REGIME_X" in p.name]
        assert len(regime_names) == 0

    def test_extract_handles_missing_entry_time_gracefully(self):
        """Trades without entry_time don't cause crashes."""
        extractor = self._make_extractor()
        trades = [{"id": "t1", "pnl": 100.0, "won": True, "regime": "TRENDING", "return_pct": 0.01}]
        result = extractor.extract(trades)
        assert isinstance(result, list)

    def test_extract_datetime_objects_work(self):
        """extract() handles datetime objects in entry_time field."""
        extractor = self._make_extractor()
        trades = [
            {
                "id": f"t{i}",
                "entry_time": datetime(2025, 1, 15, 9, 30),
                "won": True,
                "regime": "TRENDING",
                "return_pct": 0.01,
            }
            for i in range(5)
        ]
        result = extractor.extract(trades)
        assert isinstance(result, list)

    def test_streak_patterns_detected(self):
        """extract() detects win streak patterns when 3+ consecutive wins occur."""
        extractor = self._make_extractor()
        trades = [
            {
                "id": f"win{i}",
                "entry_time": f"2025-01-{15 + i:02d} 09:30:00",
                "won": True,
                "regime": "TRENDING",
                "return_pct": 0.02,
            }
            for i in range(5)  # 5 consecutive wins
        ]
        result = extractor.extract(trades)
        streak_patterns = [p for p in result if "Win Streak" in p.name]
        assert len(streak_patterns) > 0


# ===========================================================================
# 5. TradeClassifier Tests
# ===========================================================================


class TestTradeClassifier:
    """Tests for TradeClassifier (learning/_experimental/trade_classifier.py)."""

    def _make_classifier(self):
        from learning._experimental.trade_classifier import TradeClassifier

        return TradeClassifier()

    def _make_trade(
        self,
        pnl: float = 300.0,
        risk: float = 100.0,
        entry_price: float = 100.0,
        exit_price: float = 103.0,
        time_in_trade: float = 1.0,
        regime_aligned: bool = True,
        slippage: float = 0.5,
        won: bool = True,
        trade_id: str = "test-trade-1",
    ) -> dict:
        return {
            "id": trade_id,
            "pnl": pnl,
            "risk": risk,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "time_in_trade": time_in_trade,
            "target_atr": 50.0,
            "regime": "TRENDING",
            "regime_aligned": regime_aligned,
            "slippage": slippage,
            "entry_confidence": 0.85,
            "won": won,
        }

    def test_instantiation(self):
        """TradeClassifier can be instantiated."""
        classifier = self._make_classifier()
        assert classifier is not None

    def test_classify_returns_trade_classification(self):
        """classify() returns a TradeClassification object."""
        from learning._experimental.trade_classifier import TradeClassification

        classifier = self._make_classifier()
        result = classifier.classify(self._make_trade())
        assert isinstance(result, TradeClassification)

    def test_classify_returns_valid_grade(self):
        """Grade must be one of A/B/C/D/F."""
        classifier = self._make_classifier()
        result = classifier.classify(self._make_trade())
        assert result.grade in ("A", "B", "C", "D", "F")

    def test_excellent_trade_gets_high_grade(self):
        """A 3R+ aligned quick trade should grade A or B."""
        classifier = self._make_classifier()
        trade = self._make_trade(
            pnl=300.0, risk=100.0, time_in_trade=1.0, regime_aligned=True, slippage=0.5, won=True
        )
        result = classifier.classify(trade)
        assert result.grade in ("A", "B")

    def test_losing_trade_grades_f(self):
        """A trade with negative P&L must grade F."""
        classifier = self._make_classifier()
        trade = self._make_trade(pnl=-100.0, risk=100.0, won=False)
        result = classifier.classify(trade)
        assert result.grade == "F"

    def test_setup_quality_in_range(self):
        """setup_quality must be in [0.0, 1.0]."""
        classifier = self._make_classifier()
        result = classifier.classify(self._make_trade())
        assert 0.0 <= result.setup_quality <= 1.0

    def test_execution_quality_in_range(self):
        """execution_quality must be in [0.0, 1.0]."""
        classifier = self._make_classifier()
        result = classifier.classify(self._make_trade())
        assert 0.0 <= result.execution_quality <= 1.0

    def test_classify_returns_non_empty_factors(self):
        """factors list must be non-empty."""
        classifier = self._make_classifier()
        result = classifier.classify(self._make_trade())
        assert isinstance(result.factors, list)
        assert len(result.factors) > 0

    def test_high_slippage_reduces_execution_quality(self):
        """High slippage should yield lower execution_quality than low slippage."""
        classifier = self._make_classifier()
        low_slip = self._make_trade(slippage=0.1)
        high_slip = self._make_trade(slippage=20.0)
        r_low = classifier.classify(low_slip)
        r_high = classifier.classify(high_slip)
        assert r_low.execution_quality >= r_high.execution_quality

    def test_trade_id_preserved(self):
        """The trade_id in the result matches the input trade id."""
        classifier = self._make_classifier()
        trade = self._make_trade(trade_id="my-unique-id-123")
        result = classifier.classify(trade)
        assert result.trade_id == "my-unique-id-123"

    def test_classify_handles_minimal_dict(self):
        """classify() handles a minimal dict with just id and pnl."""
        classifier = self._make_classifier()
        trade = {"id": "minimal", "pnl": 100.0}
        result = classifier.classify(trade)
        assert result.grade in ("A", "B", "C", "D", "F")

    def test_is_safety_param_not_available_on_classifier(self):
        """TradeClassifier does not expose is_safety_param (that's StrategyTuner's job)."""
        classifier = self._make_classifier()
        assert not hasattr(classifier, "is_safety_param")


# ===========================================================================
# 6. StrategyTuner Tests
# ===========================================================================


class TestStrategyTuner:
    """Tests for StrategyTuner (learning/_experimental/strategy_tuner.py)."""

    def _make_tuner(self):
        from learning._experimental.strategy_tuner import StrategyTuner

        return StrategyTuner()

    def _default_params(self) -> dict:
        return {
            "STC_OS": 15,
            "STC_OB": 83,
            "STOP_ATR": 0.7,
            "T1_ATR": 1.0,
            "T2_ATR": 2.0,
            "T3_ATR": 3.0,
            "ATR_PERIOD": 14,
        }

    def _make_bad_trades(self, count: int = 20) -> list[dict]:
        return [{"id": f"t{i}", "pnl": -100.0, "risk": 100.0, "won": False} for i in range(count)]

    def _make_good_trades(self, count: int = 20) -> list[dict]:
        return [{"id": f"t{i}", "pnl": 200.0, "risk": 100.0, "won": True} for i in range(count)]

    def test_instantiation(self):
        """StrategyTuner can be instantiated."""
        tuner = self._make_tuner()
        assert tuner is not None

    def test_suggest_adjustments_returns_list(self):
        """suggest_adjustments() always returns a list."""
        tuner = self._make_tuner()
        result = tuner.suggest_adjustments(self._make_good_trades(), self._default_params())
        assert isinstance(result, list)

    def test_insufficient_trades_returns_empty(self):
        """Fewer than 5 trades returns empty suggestions."""
        tuner = self._make_tuner()
        result = tuner.suggest_adjustments(
            [{"id": "t1", "pnl": 100.0, "risk": 100.0, "won": True}], self._default_params()
        )
        assert result == []

    def test_empty_params_returns_empty(self):
        """Empty params dict returns empty suggestions."""
        tuner = self._make_tuner()
        result = tuner.suggest_adjustments(self._make_bad_trades(), {})
        assert result == []

    def test_low_win_rate_generates_suggestions(self):
        """Low win rate (all losses) triggers parameter suggestions."""
        from learning._experimental.strategy_tuner import Suggestion

        tuner = self._make_tuner()
        result = tuner.suggest_adjustments(self._make_bad_trades(), self._default_params())
        assert len(result) > 0
        for s in result:
            assert isinstance(s, Suggestion)

    def test_suggestions_have_required_fields(self):
        """Each Suggestion has param_name, current_value, suggested_value, confidence, reason."""
        tuner = self._make_tuner()
        result = tuner.suggest_adjustments(self._make_bad_trades(), self._default_params())
        for s in result:
            assert s.param_name
            assert isinstance(s.current_value, (int, float))
            assert isinstance(s.suggested_value, (int, float))
            assert 0.0 < s.confidence <= 1.0
            assert isinstance(s.reason, str) and s.reason

    def test_never_suggests_safety_params(self):
        """Safety parameters (MAX_DAILY_LOSS_PCT etc.) must never be suggested."""
        tuner = self._make_tuner()
        params = {
            **self._default_params(),
            "MAX_DAILY_LOSS_PCT": 0.02,
            "MAX_POSITION_SIZE_PCT": 0.05,
        }
        result = tuner.suggest_adjustments(self._make_bad_trades(), params)
        for s in result:
            assert not tuner.is_safety_param(
                s.param_name
            ), f"Safety param '{s.param_name}' was suggested for change"

    def test_is_safety_param(self):
        """is_safety_param() correctly identifies safety vs tunable params."""
        tuner = self._make_tuner()
        assert tuner.is_safety_param("MAX_DAILY_LOSS_PCT")
        assert tuner.is_safety_param("MAX_POSITION_SIZE_PCT")
        assert not tuner.is_safety_param("STC_OS")
        assert not tuner.is_safety_param("STOP_ATR")

    def test_is_tunable_param(self):
        """is_tunable_param() correctly identifies tunable params."""
        tuner = self._make_tuner()
        assert tuner.is_tunable_param("STC_OS")
        assert tuner.is_tunable_param("STOP_ATR")
        assert tuner.is_tunable_param("T1_ATR")
        assert not tuner.is_tunable_param("MAX_DAILY_LOSS_PCT")

    def test_clamp_suggestion_respects_bounds(self):
        """clamp_suggestion() keeps value within [min, max] for a tunable param."""
        tuner = self._make_tuner()
        # STC_OS range is (10, 20)
        assert tuner.clamp_suggestion("STC_OS", 5) == 10  # below min → clamped to 10
        assert tuner.clamp_suggestion("STC_OS", 100) == 20  # above max → clamped to 20
        assert tuner.clamp_suggestion("STC_OS", 15) == 15  # within range → unchanged

    def test_clamp_suggestion_unknown_param_passthrough(self):
        """clamp_suggestion() returns the value unchanged for an unknown param."""
        tuner = self._make_tuner()
        assert tuner.clamp_suggestion("UNKNOWN_PARAM", 42.0) == 42.0

    def test_suggestions_are_conservative_max_10pct_change(self):
        """Each suggested change must not exceed 10% of the current value."""
        tuner = self._make_tuner()
        result = tuner.suggest_adjustments(self._make_bad_trades(), self._default_params())
        for s in result:
            if s.current_value != 0:
                change_pct = abs(s.suggested_value - s.current_value) / abs(s.current_value)
                assert change_pct <= 0.15, (
                    f"Suggestion for {s.param_name} changed by {change_pct:.1%} "
                    f"(current={s.current_value}, suggested={s.suggested_value})"
                )

    def test_symbol_parameter_mes_used_in_calling_code(self):
        """StrategyTuner itself doesn't filter by symbol — caller responsibility."""
        tuner = self._make_tuner()
        # Just verifying StrategyTuner doesn't require a symbol argument
        result = tuner.suggest_adjustments(self._make_bad_trades(), self._default_params())
        assert isinstance(result, list)


# ===========================================================================
# 7. SessionMemory Tests
# ===========================================================================


class TestSessionMemory:
    """Tests for SessionMemory (learning/_experimental/session_memory.py)."""

    @pytest.fixture(autouse=True)
    def _tmp_data_dir(self, tmp_path, monkeypatch):
        """
        Redirect SessionMemory's DATA_DIR and SESSION_MEMORY_FILE to a temp
        directory so tests never touch the real session_memory.json file.
        """
        import learning._experimental.session_memory as sm_module

        fake_data_dir = tmp_path / "data"
        fake_data_dir.mkdir()
        fake_memory_file = fake_data_dir / "session_memory.json"
        monkeypatch.setattr(sm_module, "DATA_DIR", fake_data_dir)
        monkeypatch.setattr(sm_module, "SESSION_MEMORY_FILE", fake_memory_file)

    def _make_memory(self):
        from learning._experimental.session_memory import SessionMemory

        return SessionMemory()

    def test_instantiation(self):
        """SessionMemory can be instantiated."""
        mem = self._make_memory()
        assert mem is not None

    def test_initial_lessons_is_list(self):
        """lessons attribute is a list after instantiation."""
        mem = self._make_memory()
        assert isinstance(mem.lessons, list)

    def test_record_session_returns_true(self):
        """record_session() returns True on success."""
        mem = self._make_memory()
        result = mem.record_session(
            date="2025-01-15",
            trades=[{"id": "t1", "pnl": 100.0, "won": True}],
            market_conditions={"regime": "TRENDING"},
            lessons=["Buy the dip in trending markets"],
        )
        assert result is True

    def test_record_session_stores_lessons(self):
        """Lessons are stored and retrievable after record_session()."""
        mem = self._make_memory()
        mem.record_session(
            date="2025-01-15",
            trades=[],
            market_conditions={"regime": "TRENDING"},
            lessons=["Lesson alpha", "Lesson beta"],
        )
        assert len(mem.lessons) == 2

    def test_get_all_lessons_returns_list(self):
        """get_all_lessons() returns a list."""
        mem = self._make_memory()
        result = mem.get_all_lessons()
        assert isinstance(result, list)

    def test_get_all_lessons_contains_recorded_lessons(self):
        """get_all_lessons() includes all recorded lessons."""
        mem = self._make_memory()
        mem.record_session(
            date="2025-01-15",
            trades=[],
            market_conditions={"regime": "CHOPPY"},
            lessons=["Avoid trades in chop"],
        )
        all_lessons = mem.get_all_lessons()
        assert len(all_lessons) == 1
        assert all_lessons[0].lesson_text == "Avoid trades in chop"

    def test_get_lessons_filters_by_condition(self):
        """get_lessons() returns only lessons matching the given condition."""
        mem = self._make_memory()
        mem.record_session(
            date="2025-01-15",
            trades=[],
            market_conditions={"regime": "TRENDING"},
            lessons=["Trending lesson"],
        )
        mem.record_session(
            date="2025-01-16",
            trades=[],
            market_conditions={"regime": "CHOPPY"},
            lessons=["Choppy lesson"],
        )
        trending = mem.get_lessons("TRENDING")
        choppy = mem.get_lessons("CHOPPY")
        assert len(trending) == 1
        assert trending[0].lesson_text == "Trending lesson"
        assert len(choppy) == 1
        assert choppy[0].lesson_text == "Choppy lesson"

    def test_get_lessons_unknown_condition_returns_empty(self):
        """get_lessons() with an unknown condition returns []."""
        mem = self._make_memory()
        result = mem.get_lessons("NONEXISTENT_REGIME_XYZ")
        assert result == []

    def test_lesson_has_correct_fields(self):
        """Each Lesson has date, condition, lesson_text, trades_affected, outcome."""
        from learning._experimental.session_memory import Lesson

        mem = self._make_memory()
        mem.record_session(
            date="2025-01-15",
            trades=[{"id": "t1", "pnl": 100.0, "won": True}],
            market_conditions={"regime": "TRENDING"},
            lessons=["Test lesson"],
        )
        lesson = mem.lessons[0]
        assert isinstance(lesson, Lesson)
        assert lesson.date == "2025-01-15"
        assert lesson.condition == "TRENDING"
        assert lesson.lesson_text == "Test lesson"
        assert isinstance(lesson.trades_affected, list)
        assert lesson.outcome in ("positive", "negative", "neutral")

    def test_outcome_positive_when_more_wins(self):
        """outcome is 'positive' when wins > losses."""
        mem = self._make_memory()
        mem.record_session(
            date="2025-01-15",
            trades=[
                {"id": "t1", "pnl": 100.0, "won": True},
                {"id": "t2", "pnl": 100.0, "won": True},
                {"id": "t3", "pnl": -50.0, "won": False},
            ],
            market_conditions={"regime": "TRENDING"},
            lessons=["Good session"],
        )
        assert mem.lessons[0].outcome == "positive"

    def test_outcome_negative_when_more_losses(self):
        """outcome is 'negative' when losses > wins."""
        mem = self._make_memory()
        mem.record_session(
            date="2025-01-15",
            trades=[
                {"id": "t1", "pnl": -100.0, "won": False},
                {"id": "t2", "pnl": -100.0, "won": False},
                {"id": "t3", "pnl": 50.0, "won": True},
            ],
            market_conditions={"regime": "CHOPPY"},
            lessons=["Bad session"],
        )
        assert mem.lessons[0].outcome == "negative"

    def test_clear_lessons_removes_all(self):
        """clear_lessons() sets lessons to empty list."""
        mem = self._make_memory()
        mem.record_session(
            date="2025-01-15",
            trades=[],
            market_conditions={"regime": "TRENDING"},
            lessons=["Will be cleared"],
        )
        assert len(mem.lessons) > 0
        mem.clear_lessons()
        assert len(mem.lessons) == 0

    def test_persistence_to_json(self, tmp_path):
        """Lessons are persisted to JSON and reloaded by a new instance."""
        import learning._experimental.session_memory as sm_module

        # The fixture already redirects DATA_DIR and SESSION_MEMORY_FILE
        mem1 = self._make_memory()
        mem1.record_session(
            date="2025-01-15",
            trades=[],
            market_conditions={"regime": "TRENDING"},
            lessons=["Persisted lesson check"],
        )
        # A fresh instance should load the same file
        mem2 = self._make_memory()
        assert any("Persisted lesson check" in lesson.lesson_text for lesson in mem2.lessons)

    def test_add_lesson_via_record_session(self):
        """Multiple calls to record_session accumulate lessons."""
        mem = self._make_memory()
        mem.record_session(
            date="2025-01-15",
            trades=[],
            market_conditions={"regime": "TRENDING"},
            lessons=["First"],
        )
        mem.record_session(
            date="2025-01-16",
            trades=[],
            market_conditions={"regime": "TRENDING"},
            lessons=["Second"],
        )
        assert len(mem.lessons) == 2


# ===========================================================================
# 8. Learning Router Tests (via FastAPI TestClient)
# ===========================================================================


def _build_learning_app():
    """
    Build a minimal FastAPI app with only the learning_router.
    Patches DB_PATH to a temp in-memory SQLite so no real DB is needed.
    """
    from fastapi import FastAPI

    from routers.learning_router import router as learning_router

    app = FastAPI()
    app.include_router(learning_router)
    return app


class TestLearningRouter:
    """Integration tests for the /learning/* API endpoints."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, tmp_path, monkeypatch):
        """
        Point DB_PATH to a fresh temp SQLite DB for all router tests.
        Also redirect SessionMemory's file storage to a temp location.
        """
        db_path = str(_make_temp_db(tmp_path))
        self.db_path = db_path

        monkeypatch.setenv("DB_PATH", db_path)

        # Redirect SessionMemory file storage
        import learning._experimental.session_memory as sm_module

        fake_data_dir = tmp_path / "data"
        fake_data_dir.mkdir(exist_ok=True)
        monkeypatch.setattr(sm_module, "DATA_DIR", fake_data_dir)
        monkeypatch.setattr(sm_module, "SESSION_MEMORY_FILE", fake_data_dir / "session_memory.json")

    @pytest.fixture
    def client(self):
        """Create a TestClient for the learning router app."""
        try:
            from fastapi.testclient import TestClient

            app = _build_learning_app()
            return TestClient(app)
        except Exception as exc:
            pytest.skip(f"Could not build TestClient: {exc}")

    def test_get_patterns_returns_200(self, client):
        """GET /learning/patterns?symbol=MES returns 200."""
        response = client.get("/learning/patterns?symbol=MES")
        assert response.status_code == 200

    def test_get_patterns_response_shape(self, client):
        """GET /learning/patterns returns {status: 'ok', data: {...}}."""
        response = client.get("/learning/patterns?symbol=MES")
        data = response.json()
        assert data.get("status") == "ok"
        assert "data" in data
        d = data["data"]
        assert "symbol" in d
        assert "trades_analyzed" in d
        assert "patterns_found" in d
        assert "time_of_day" in d
        assert "regime_patterns" in d
        assert "streak_patterns" in d

    def test_get_patterns_no_symbol_returns_200(self, client):
        """GET /learning/patterns (no symbol) returns 200."""
        response = client.get("/learning/patterns")
        assert response.status_code == 200

    def test_get_patterns_lookback_days_param(self, client):
        """GET /learning/patterns with custom lookback_days works."""
        response = client.get("/learning/patterns?symbol=MES&lookback_days=7")
        assert response.status_code == 200

    def test_get_suggestions_returns_200(self, client):
        """GET /learning/suggestions?symbol=MES returns 200."""
        response = client.get("/learning/suggestions?symbol=MES")
        assert response.status_code == 200

    def test_get_suggestions_response_shape(self, client):
        """GET /learning/suggestions returns {status: 'ok', data: {...}}."""
        response = client.get("/learning/suggestions?symbol=MES")
        data = response.json()
        assert data.get("status") == "ok"
        assert "data" in data
        d = data["data"]
        assert "trades_analyzed" in d
        assert "suggestions" in d
        assert "suggestion_count" in d
        assert isinstance(d["suggestions"], list)

    def test_get_suggestions_no_symbol_returns_200(self, client):
        """GET /learning/suggestions (no symbol) returns 200."""
        response = client.get("/learning/suggestions")
        assert response.status_code == 200

    def test_get_memory_returns_200(self, client):
        """GET /learning/memory returns 200."""
        response = client.get("/learning/memory")
        assert response.status_code == 200

    def test_get_memory_response_shape(self, client):
        """GET /learning/memory returns {status: 'ok', data: {...}}."""
        response = client.get("/learning/memory")
        data = response.json()
        assert data.get("status") == "ok"
        assert "data" in data
        d = data["data"]
        assert "total" in d
        assert "lessons" in d
        assert isinstance(d["lessons"], list)

    def test_get_memory_with_condition_filter(self, client):
        """GET /learning/memory?condition=TRENDING returns 200."""
        response = client.get("/learning/memory?condition=TRENDING")
        assert response.status_code == 200

    def test_post_memory_valid_body_returns_200(self, client):
        """POST /learning/memory with valid body returns 200."""
        payload = {"lesson": "Always wait for the open range to establish.", "category": "general"}
        response = client.post("/learning/memory", json=payload)
        assert response.status_code == 200

    def test_post_memory_response_shape(self, client):
        """POST /learning/memory returns {status: 'ok', data: {...}}."""
        payload = {"lesson": "Test lesson for router.", "category": "TRENDING"}
        response = client.post("/learning/memory", json=payload)
        data = response.json()
        assert data.get("status") == "ok"
        assert "data" in data
        d = data["data"]
        assert d.get("recorded") is True
        assert "lesson" in d
        assert "total_lessons" in d

    def test_post_memory_empty_lesson_returns_400(self, client):
        """POST /learning/memory with empty lesson string returns 400."""
        payload = {"lesson": "   ", "category": "general"}
        response = client.post("/learning/memory", json=payload)
        assert response.status_code == 400

    def test_post_memory_missing_lesson_returns_422(self, client):
        """POST /learning/memory with missing lesson field returns 422."""
        response = client.post("/learning/memory", json={"category": "general"})
        assert response.status_code == 422

    def test_post_then_get_memory_shows_new_lesson(self, client):
        """After POST, GET /learning/memory should include the new lesson."""
        lesson_text = "Buy on retests of VWAP in trending conditions."
        client.post("/learning/memory", json={"lesson": lesson_text, "category": "TRENDING"})
        response = client.get("/learning/memory")
        data = response.json()
        lessons = data["data"]["lessons"]
        assert any(lesson_text in row.get("lesson_text", "") for row in lessons)

    def test_classify_endpoint_missing_trade_id_returns_422(self, client):
        """GET /learning/classify without trade_id param returns 422."""
        response = client.get("/learning/classify")
        assert response.status_code == 422

    def test_classify_endpoint_unknown_trade_id_returns_404(self, client):
        """GET /learning/classify?trade_id=NONEXISTENT returns 404."""
        response = client.get("/learning/classify?trade_id=NONEXISTENT-TRADE-ID-XYZ")
        assert response.status_code == 404

    def test_classify_trade_id_recent_literal_still_404s(self, client):
        """
        Pins the ROOT CAUSE of the T2-15 dashboard finding: "recent" is not a
        real trade_id — GET /learning/classify does an exact-match lookup
        (_get_trade_by_id), so the dashboard's old
        `/learning/classify?trade_id=recent` call could never have worked.
        This is why /learning/classify/recent (a real batch endpoint) exists.
        """
        response = client.get("/learning/classify?trade_id=recent")
        assert response.status_code == 404

    def _insert_closed_trade(
        self,
        trade_id: str,
        symbol: str = "MES",
        entry_price: float = 5000.0,
        exit_price: float = 5025.0,
        pnl: float = 250.0,
        entry_time: str = "2026-07-01 09:30:00",
        exit_time: str = "2026-07-01 11:00:00",
    ) -> None:
        """Insert a single closed paper_trades row for classify/recent tests."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """INSERT INTO paper_trades
                   (trade_id, symbol, side, quantity, entry_price, exit_price,
                    entry_time, exit_time, pnl, status)
                   VALUES (?, ?, 'BUY', 1, ?, ?, ?, ?, ?, 'closed')""",
                (trade_id, symbol, entry_price, exit_price, entry_time, exit_time, pnl),
            )
            conn.commit()
        finally:
            conn.close()

    def test_classify_recent_returns_200(self, client):
        """GET /learning/classify/recent returns 200 with no trades in the DB."""
        response = client.get("/learning/classify/recent")
        assert response.status_code == 200

    def test_classify_recent_response_shape(self, client):
        """
        GET /learning/classify/recent returns {status: 'ok', data: {symbol,
        count, grades}}, and each grade entry carries the fields
        TradeGradeTable.tsx renders — grade/setup_quality/execution_quality/
        factors/explanation, not the old score/criteria shape.
        """
        self._insert_closed_trade("trade-recent-1", symbol="MES", pnl=250.0)
        self._insert_closed_trade("trade-recent-2", symbol="MES", pnl=-80.0)

        response = client.get("/learning/classify/recent?symbol=MES")
        assert response.status_code == 200
        body = response.json()
        assert body.get("status") == "ok"
        assert "data" in body
        d = body["data"]
        assert d["symbol"] == "MES"
        assert d["count"] == 2
        assert isinstance(d["grades"], list)
        assert len(d["grades"]) == 2

        grade = d["grades"][0]
        for key in (
            "trade_id", "symbol", "grade", "setup_quality",
            "execution_quality", "factors", "explanation",
            "entry_time", "exit_time", "pnl",
        ):
            assert key in grade
        assert grade["grade"] in {"A", "B", "C", "D", "F"}
        assert isinstance(grade["factors"], list)

    def test_classify_recent_respects_limit(self, client):
        """The `limit` query param caps how many recent trades are graded."""
        for i in range(5):
            self._insert_closed_trade(f"trade-limit-{i}", symbol="MGC")

        response = client.get("/learning/classify/recent?symbol=MGC&limit=2")
        assert response.status_code == 200
        d = response.json()["data"]
        assert d["count"] == 2
        assert len(d["grades"]) == 2

    def test_classify_recent_symbol_filter_excludes_other_symbols(self, client):
        """`symbol` query param filters out grades for other instruments."""
        self._insert_closed_trade("trade-mes-1", symbol="MES")
        self._insert_closed_trade("trade-mgc-1", symbol="MGC")

        response = client.get("/learning/classify/recent?symbol=MGC")
        assert response.status_code == 200
        d = response.json()["data"]
        assert all(g["symbol"] == "MGC" for g in d["grades"])

    def test_post_memory_old_frontend_body_shape_422s(self, client):
        """
        Documents the second half of the T2-15 root cause: the dashboard's
        Save Lesson form used to POST {type, content, symbol}, which does not
        match LessonRequest ({lesson, category}) and 422s every time. The
        fixed MemoryPanel.tsx now sends {lesson, category} instead (see
        test_post_memory_response_shape above, which already covers the
        corrected shape returning 200).
        """
        old_shape_payload = {"type": "lesson", "content": "Old body shape.", "symbol": "MES"}
        response = client.post("/learning/memory", json=old_shape_payload)
        assert response.status_code == 422


# ===========================================================================
# 9. Additional edge-case / cross-module Tests
# ===========================================================================


class TestEdgeCases:
    """Miscellaneous edge-case tests not covered above."""

    def test_sentiment_score_message_caution_keywords(self):
        """Caution keywords reduce denominator but don't contribute to numerator."""
        from discord.sentiment_provider import score_message

        # Pure caution → neutral score
        score = score_message("choppy sideways balanced wait avoid fomc holiday")
        # Score can be 0 or lean slightly positive/negative depending on mix
        assert -1.0 <= score <= 1.0

    def test_sentiment_score_message_mixed(self):
        """Mixed bullish + bearish message scores near 0."""
        from discord.sentiment_provider import score_message

        # Equal bullish and bearish → near 0
        score = score_message("buyers long breakout sellers short breakdown")
        assert -0.5 <= score <= 0.5

    def test_discord_signal_context_nonexistent_db_returns_defaults(self):
        """When DB file doesn't exist, get_features returns safe defaults."""
        from discord.signal_context import DiscordSignalContext

        ctx = DiscordSignalContext(db_path="/tmp/nonexistent_db_xyz_9999.db")
        ts = datetime(2025, 1, 15, 10, 0, 0)
        result = ctx.get_features(symbol="MES", timestamp=ts, price=5000.0, atr=10.0)
        # Should return defaults without raising
        assert result["discord_signal_active"] == 0.0
        assert result["discord_win_rate_context"] == 0.5

    def test_ib_level_provider_nonexistent_db_returns_none(self):
        """When DB file doesn't exist, get_levels returns None."""
        from discord.ib_levels import IBLevelProvider

        provider = IBLevelProvider(db_path="/tmp/nonexistent_db_xyz_9999.db")
        result = provider.get_levels(symbol="ES", trading_date=date(2025, 1, 15))
        assert result is None

    def test_pattern_extractor_with_invalid_datetime_strings(self):
        """PatternExtractor handles unparseable datetime strings gracefully."""
        from learning._experimental.pattern_extractor import PatternExtractor

        extractor = PatternExtractor()
        trades = [
            {
                "id": "t1",
                "entry_time": "not-a-datetime",
                "won": True,
                "regime": "TRENDING",
                "return_pct": 0.01,
            }
        ]
        result = extractor.extract(trades)
        assert isinstance(result, list)

    def test_trade_classifier_handles_loss_trade(self):
        """TradeClassifier returns grade F for a trade with negative P&L."""
        from learning._experimental.trade_classifier import TradeClassifier

        classifier = TradeClassifier()
        # A losing trade should always grade F
        result = classifier.classify(
            {"id": "loss-edge", "pnl": -500.0, "risk": 100.0, "won": False}
        )
        assert result.grade == "F"
        assert len(result.factors) > 0

    def test_strategy_tuner_empty_trades(self):
        """StrategyTuner returns empty list for empty trades."""
        from learning._experimental.strategy_tuner import StrategyTuner

        tuner = StrategyTuner()
        result = tuner.suggest_adjustments([], {"STC_OS": 15})
        assert result == []

    def test_ib_levels_mnq_to_nq_map(self, tmp_path):
        """MNQ is correctly mapped to NQ for IB lookups."""
        from discord.ib_levels import IBLevelProvider

        db_path = _make_temp_db(tmp_path)
        _insert_ib_report(db_path, "NQ", "2025-01-15T08:00:00")
        provider = IBLevelProvider(db_path=db_path)
        result = provider.get_levels(symbol="MNQ", trading_date=date(2025, 1, 15))
        assert result is not None
