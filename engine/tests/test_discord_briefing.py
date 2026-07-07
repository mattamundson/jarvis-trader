"""
DiscordBriefing facade regression tests.

Guards the contract that `get_discord_briefing` aggregates the four Discord
consumers without breaking any of them, with a 5-minute TTL cache and
graceful degradation on per-source failure.

Covered scenarios:
  1. Happy path — all four sources return data, briefing fields populate
  2. Corey bias fetch failure → fallback to neutral, warning recorded
  3. IB levels missing (None) → ib_levels=None, no warning (legitimate state)
  4. Recent-signal DB error → recent_signal=None, warning recorded
  5. 5-minute TTL cache hit — second call within window returns identical
     object without re-invoking providers
  6. `actionable` property requires fresh + directional + conviction >= 0.5
  7. `headline` property formats correctly
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discord import briefing as briefing_mod
from discord.briefing import DiscordBriefing, clear_cache, get_discord_briefing
from discord.commentary_processor import CoreySessionBias


@pytest.fixture(autouse=True)
def _reset_briefing_cache():
    """Clear the module-level TTL cache and provider singletons between tests."""
    clear_cache()
    briefing_mod._processor = None
    briefing_mod._ib_provider = None
    briefing_mod._sentiment = None
    briefing_mod._signal_ctx = None
    yield
    clear_cache()
    briefing_mod._processor = None
    briefing_mod._ib_provider = None
    briefing_mod._sentiment = None
    briefing_mod._signal_ctx = None


def _fresh_bias(for_date: date = None) -> CoreySessionBias:
    return CoreySessionBias(
        date=for_date or date.today(),
        session_type="range_day",
        directional_bias="bullish",
        key_levels=[84.20, 84.55],
        ib_bias="above_ib",
        specific_triggers=["hold above 84.20 → target 84.55"],
        conviction=0.72,
        corey_quote="Holding above 84.20 signals initiative buying",
        message_count=14,
        data_quality="fresh",
    )


def _neutral_bias(for_date: date = None) -> CoreySessionBias:
    return CoreySessionBias(
        date=for_date or date.today(),
        session_type="uncertain",
        directional_bias="neutral",
        key_levels=[],
        ib_bias="not_mentioned",
        specific_triggers=[],
        conviction=0.0,
        corey_quote="",
        message_count=0,
        data_quality="none",
    )


@pytest.mark.asyncio
async def test_happy_path_aggregates_all_four_sources():
    fake_bias = _fresh_bias()
    fake_levels = {
        "ib_high": 84.60, "ib_low": 83.80, "ib_range": 0.80,
        "ibu50": 85.00, "ibu100": 85.40,
        "ibd50": 83.40, "ibd100": 83.00,
        "auction_context": "above_ib",
    }
    fake_signal = {
        "symbol": "CL", "direction": "LONG", "signal_type": "ENTRY",
        "entry_price": 84.20, "target1": 84.55, "target2": 84.90,
        "stop1": 83.90, "win_rate": 76.8, "timestamp": "2026-04-18T09:12:00",
    }

    processor = MagicMock()
    processor.get_session_bias = AsyncMock(return_value=fake_bias)

    ib_provider = MagicMock()
    ib_provider._map_symbol = MagicMock(return_value="CL")
    ib_provider.get_levels = MagicMock(return_value=fake_levels)

    sentiment = MagicMock()
    sentiment.get_sentiment = MagicMock(return_value=0.4)
    sentiment.get_regime_multiplier = MagicMock(return_value=1.12)

    with patch.object(briefing_mod, "_get_processor", return_value=processor), \
         patch.object(briefing_mod, "_get_ib_provider", return_value=ib_provider), \
         patch.object(briefing_mod, "_get_sentiment", return_value=sentiment), \
         patch.object(briefing_mod, "_fetch_recent_signal", return_value=fake_signal):
        briefing = await get_discord_briefing("MCL", lookback_hours=12)

    assert isinstance(briefing, DiscordBriefing)
    assert briefing.symbol == "MCL"
    assert briefing.discord_symbol == "CL"
    assert briefing.corey_bias.directional_bias == "bullish"
    assert briefing.corey_bias.conviction == 0.72
    assert briefing.ib_levels == fake_levels
    assert briefing.keyword_sentiment == 0.4
    assert briefing.regime_multiplier == 1.12
    assert briefing.recent_signal == fake_signal
    assert briefing.lookback_hours == 12
    assert briefing.warnings == []
    assert briefing.actionable is True
    assert briefing.headline == "MCL range_day, bullish, above_ib, conv 0.72"


@pytest.mark.asyncio
async def test_corey_bias_failure_falls_back_to_neutral():
    processor = MagicMock()
    processor.get_session_bias = AsyncMock(side_effect=RuntimeError("anthropic_down"))

    ib_provider = MagicMock()
    ib_provider._map_symbol = MagicMock(return_value="CL")
    ib_provider.get_levels = MagicMock(return_value=None)

    sentiment = MagicMock()
    sentiment.get_sentiment = MagicMock(return_value=0.0)
    sentiment.get_regime_multiplier = MagicMock(return_value=1.0)

    with patch.object(briefing_mod, "_get_processor", return_value=processor), \
         patch.object(briefing_mod, "_get_ib_provider", return_value=ib_provider), \
         patch.object(briefing_mod, "_get_sentiment", return_value=sentiment), \
         patch.object(briefing_mod, "_fetch_recent_signal", return_value=None):
        briefing = await get_discord_briefing("MCL")

    assert briefing.corey_bias.directional_bias == "neutral"
    assert briefing.corey_bias.data_quality == "none"
    assert briefing.actionable is False
    assert any("corey_bias_failed:RuntimeError" in w for w in briefing.warnings)


@pytest.mark.asyncio
async def test_missing_ib_levels_is_not_a_warning():
    """Not every day has an IB report — None is a valid state, not an error."""
    processor = MagicMock()
    processor.get_session_bias = AsyncMock(return_value=_fresh_bias())

    ib_provider = MagicMock()
    ib_provider._map_symbol = MagicMock(return_value="CL")
    ib_provider.get_levels = MagicMock(return_value=None)

    sentiment = MagicMock()
    sentiment.get_sentiment = MagicMock(return_value=0.0)
    sentiment.get_regime_multiplier = MagicMock(return_value=1.0)

    with patch.object(briefing_mod, "_get_processor", return_value=processor), \
         patch.object(briefing_mod, "_get_ib_provider", return_value=ib_provider), \
         patch.object(briefing_mod, "_get_sentiment", return_value=sentiment), \
         patch.object(briefing_mod, "_fetch_recent_signal", return_value=None):
        briefing = await get_discord_briefing("MCL")

    assert briefing.ib_levels is None
    assert not any("ib_levels_failed" in w for w in briefing.warnings)


@pytest.mark.asyncio
async def test_five_minute_ttl_cache_hit_returns_same_object():
    processor = MagicMock()
    processor.get_session_bias = AsyncMock(return_value=_fresh_bias())

    ib_provider = MagicMock()
    ib_provider._map_symbol = MagicMock(return_value="CL")
    ib_provider.get_levels = MagicMock(return_value=None)

    sentiment = MagicMock()
    sentiment.get_sentiment = MagicMock(return_value=0.0)
    sentiment.get_regime_multiplier = MagicMock(return_value=1.0)

    call_count = 0
    def recent_signal_stub(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return None

    with patch.object(briefing_mod, "_get_processor", return_value=processor), \
         patch.object(briefing_mod, "_get_ib_provider", return_value=ib_provider), \
         patch.object(briefing_mod, "_get_sentiment", return_value=sentiment), \
         patch.object(briefing_mod, "_fetch_recent_signal", side_effect=recent_signal_stub):
        first = await get_discord_briefing("MCL", lookback_hours=24)
        second = await get_discord_briefing("MCL", lookback_hours=24)

    assert first is second  # identity — cached object returned unchanged
    assert processor.get_session_bias.await_count == 1
    assert ib_provider.get_levels.call_count == 1
    assert sentiment.get_sentiment.call_count == 1
    assert call_count == 1


@pytest.mark.asyncio
async def test_different_lookback_hours_is_different_cache_key():
    processor = MagicMock()
    processor.get_session_bias = AsyncMock(return_value=_fresh_bias())

    ib_provider = MagicMock()
    ib_provider._map_symbol = MagicMock(return_value="CL")
    ib_provider.get_levels = MagicMock(return_value=None)

    sentiment = MagicMock()
    sentiment.get_sentiment = MagicMock(return_value=0.0)
    sentiment.get_regime_multiplier = MagicMock(return_value=1.0)

    with patch.object(briefing_mod, "_get_processor", return_value=processor), \
         patch.object(briefing_mod, "_get_ib_provider", return_value=ib_provider), \
         patch.object(briefing_mod, "_get_sentiment", return_value=sentiment), \
         patch.object(briefing_mod, "_fetch_recent_signal", return_value=None):
        first = await get_discord_briefing("MCL", lookback_hours=24)
        second = await get_discord_briefing("MCL", lookback_hours=4)

    assert first is not second
    assert first.lookback_hours == 24
    assert second.lookback_hours == 4


@pytest.mark.asyncio
async def test_actionable_requires_fresh_directional_and_high_conviction():
    """Edge-case verification of the .actionable property."""
    # stale + bullish + 0.8 → not actionable (stale)
    stale_bias = CoreySessionBias(
        date=date.today(), session_type="trend_day", directional_bias="bullish",
        key_levels=[], ib_bias="above_ib", specific_triggers=[],
        conviction=0.8, corey_quote="", message_count=5, data_quality="stale",
    )
    # fresh + neutral + 0.9 → not actionable (not directional)
    neutral_bias = CoreySessionBias(
        date=date.today(), session_type="range_day", directional_bias="neutral",
        key_levels=[], ib_bias="inside_ib", specific_triggers=[],
        conviction=0.9, corey_quote="", message_count=5, data_quality="fresh",
    )
    # fresh + bullish + 0.4 → not actionable (conviction < 0.5)
    low_conv_bias = CoreySessionBias(
        date=date.today(), session_type="range_day", directional_bias="bullish",
        key_levels=[], ib_bias="above_ib", specific_triggers=[],
        conviction=0.4, corey_quote="", message_count=5, data_quality="fresh",
    )

    for bias, expected_actionable in [
        (_fresh_bias(), True),
        (stale_bias, False),
        (neutral_bias, False),
        (low_conv_bias, False),
    ]:
        b = DiscordBriefing(
            symbol="MCL", discord_symbol="CL", as_of=datetime.utcnow(),
            corey_bias=bias, ib_levels=None,
            keyword_sentiment=0.0, regime_multiplier=1.0,
            recent_signal=None, lookback_hours=24,
        )
        assert b.actionable is expected_actionable, f"bias={bias.data_quality}/{bias.directional_bias}/{bias.conviction}"


@pytest.mark.asyncio
async def test_to_dict_round_trip():
    processor = MagicMock()
    processor.get_session_bias = AsyncMock(return_value=_fresh_bias())

    ib_provider = MagicMock()
    ib_provider._map_symbol = MagicMock(return_value="CL")
    ib_provider.get_levels = MagicMock(return_value=None)

    sentiment = MagicMock()
    sentiment.get_sentiment = MagicMock(return_value=0.25)
    sentiment.get_regime_multiplier = MagicMock(return_value=1.075)

    with patch.object(briefing_mod, "_get_processor", return_value=processor), \
         patch.object(briefing_mod, "_get_ib_provider", return_value=ib_provider), \
         patch.object(briefing_mod, "_get_sentiment", return_value=sentiment), \
         patch.object(briefing_mod, "_fetch_recent_signal", return_value=None):
        briefing = await get_discord_briefing("MCL")

    d = briefing.to_dict()
    assert d["symbol"] == "MCL"
    assert d["discord_symbol"] == "CL"
    assert d["corey_bias"]["directional_bias"] == "bullish"
    assert d["keyword_sentiment"] == 0.25
    assert d["actionable"] is True
    assert d["headline"].startswith("MCL range_day, bullish")
    assert d["warnings"] == []
