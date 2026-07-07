"""Tests for US-2503 — Discord context injection into TechnicalAnalyst prompt."""
from unittest.mock import MagicMock, patch

import pytest


def _make_analyst():
    """Construct TechnicalAnalystAgent without calling __init__."""
    from agents.technical_analyst import TechnicalAnalystAgent
    ta = TechnicalAnalystAgent.__new__(TechnicalAnalystAgent)
    return ta


@pytest.mark.asyncio
async def test_discord_context_returns_empty_on_exception():
    """_get_discord_context() returns '' when DiscordSignalContext raises."""
    ta = _make_analyst()
    with patch("discord.signal_context.DiscordSignalContext", side_effect=RuntimeError("unavailable")):
        result = await ta._get_discord_context("MCL", 72.5, 0.5)
    assert result == ""


@pytest.mark.asyncio
async def test_discord_context_returns_empty_when_no_active_signal():
    """_get_discord_context() returns '' when discord_signal_active == 0."""
    ta = _make_analyst()
    mock_ctx = MagicMock()
    mock_ctx.get_features.return_value = {
        "discord_signal_active": 0.0,
        "discord_win_rate_context": 0.5,
        "discord_proximity_entry": 0.1,
        "discord_proximity_target": 0.5,
        "discord_alignment": 0.0,
    }
    with patch("discord.signal_context.DiscordSignalContext", return_value=mock_ctx):
        result = await ta._get_discord_context("MCL", 72.5, 0.5)
    assert result == ""


@pytest.mark.asyncio
async def test_discord_context_returns_block_when_signal_active():
    """_get_discord_context() returns non-empty string when discord_signal_active == 1."""
    ta = _make_analyst()
    mock_ctx = MagicMock()
    mock_ctx.get_features.return_value = {
        "discord_signal_active": 1.0,
        "discord_win_rate_context": 0.768,
        "discord_proximity_entry": -0.25,
        "discord_proximity_target": 0.80,
        "discord_alignment": 1.0,
    }
    with patch("discord.signal_context.DiscordSignalContext", return_value=mock_ctx):
        result = await ta._get_discord_context("MCL", 72.5, 0.5)
    assert "DISCORD INTELLIGENCE" in result
    assert "ALIGNED" in result


@pytest.mark.asyncio
async def test_alignment_labels():
    """_get_discord_context() returns correct alignment labels."""
    ta = _make_analyst()
    mock_ctx = MagicMock()
    for alignment_val, expected in [(1.0, "ALIGNED"), (-1.0, "OPPOSED"), (0.0, "NEUTRAL")]:
        mock_ctx.get_features.return_value = {
            "discord_signal_active": 1.0,
            "discord_win_rate_context": 0.6,
            "discord_proximity_entry": 0.0,
            "discord_proximity_target": 0.5,
            "discord_alignment": alignment_val,
        }
        with patch("discord.signal_context.DiscordSignalContext", return_value=mock_ctx):
            result = await ta._get_discord_context("MCL", 72.5, 0.5)
        assert expected in result, f"Expected {expected} for alignment={alignment_val}, got: {result!r}"


def test_get_discord_context_method_exists():
    """TechnicalAnalystAgent has _get_discord_context async method."""
    import inspect

    from agents.technical_analyst import TechnicalAnalystAgent
    assert hasattr(TechnicalAnalystAgent, "_get_discord_context")
    assert inspect.iscoroutinefunction(TechnicalAnalystAgent._get_discord_context)
