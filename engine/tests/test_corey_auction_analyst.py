"""
Tests for CoreyAuctionAnalystAgent's Hidden Pivots cross-confirmation boost
(Track H / T17 wiring landed 2026-04-10).

Scope
-----
These tests verify the HP cross-confirmation branch at
engine/agents/corey_auction_analyst.py lines 198-207. The branch takes an
optional `hp_context` dict and boosts `alignment_score` by +0.15 when the HP
pattern direction agrees with the auction bias (bullish + alignment > 0.2,
or bearish + alignment < -0.2).

The tests mock the Corey commentary processor and bot signal helpers so the
analyzer can run in isolation — no Anthropic calls, no SQLite hits, no
Discord data required.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agents.corey_auction_analyst import CoreyAuctionAnalystAgent, CoreyAuctionReport


def _make_session_bias(directional: str = "bullish"):
    """Build a CoreySessionBias stand-in with the fields the analyzer reads."""
    return SimpleNamespace(
        session_type="trend_day",
        directional_bias=directional,
        conviction=0.8,
        key_levels=[],
        ib_bias="above_ib",
        corey_quote="test quote",
        data_quality="fresh",
        message_count=3,
    )


def _make_agent() -> CoreyAuctionAnalystAgent:
    """Construct an analyzer with the commentary processor stubbed out."""
    with patch(
        "agents.corey_auction_analyst.CoreyAuctionAnalystAgent.__init__",
        return_value=None,
    ):
        agent = CoreyAuctionAnalystAgent()
    # Minimal internal state the analyze() method expects
    agent._llm = None  # type: ignore[attr-defined]
    agent._db_path = ":memory:"  # type: ignore[attr-defined]
    agent._processor = SimpleNamespace(  # type: ignore[attr-defined]
        get_session_bias=AsyncMock(return_value=_make_session_bias("bullish"))
    )
    return agent


@pytest.mark.asyncio
async def test_corey_hp_confirmation_boosts_alignment():
    """Bullish HP context should boost an already-bullish Corey alignment by +0.15."""
    agent = _make_agent()

    # Force a known positive alignment_score so the HP boost threshold is crossed.
    # _compute_bot_boost returns (bot_boost, alignment_score); we pin alignment=0.3
    # (>0.2 threshold) so the bullish HP branch fires.
    with patch.object(
        agent, "_get_active_bot_signal", return_value={"side": "LONG", "price": 100.0}
    ), patch.object(
        agent, "_get_rolling_win_rate", return_value=0.6
    ), patch.object(
        agent, "_compute_bot_boost", return_value=(0.3, 0.3)
    ), patch.object(
        agent, "_build_summary", return_value="test summary"
    ), patch.object(
        agent, "_build_reasoning", return_value="test reasoning"
    ):
        report = await agent.analyze(
            symbol="MCL",
            current_price=84.0,
            atr=1.2,
            hp_context={"direction": "bullish"},
        )

    assert isinstance(report, CoreyAuctionReport)
    # +0.15 boost on the 0.3 baseline → 0.45 (rounded to 4dp)
    assert report.alignment_score == pytest.approx(0.45)


@pytest.mark.asyncio
async def test_corey_hp_conflict_no_boost():
    """Bearish HP context on a bullish Corey alignment should NOT boost."""
    agent = _make_agent()

    with patch.object(
        agent, "_get_active_bot_signal", return_value={"side": "LONG", "price": 100.0}
    ), patch.object(
        agent, "_get_rolling_win_rate", return_value=0.6
    ), patch.object(
        agent, "_compute_bot_boost", return_value=(0.3, 0.3)
    ), patch.object(
        agent, "_build_summary", return_value="test summary"
    ), patch.object(
        agent, "_build_reasoning", return_value="test reasoning"
    ):
        report = await agent.analyze(
            symbol="MCL",
            current_price=84.0,
            atr=1.2,
            hp_context={"direction": "bearish"},  # conflicts with bullish alignment
        )

    # alignment_score unchanged at 0.3 — bearish branch requires alignment < -0.2
    assert report.alignment_score == pytest.approx(0.3)


# --- Decision-time futures-sentiment staleness flag (Task 3) ----------------
# The /health helper already reports feed age; this surfaces the staleness IN
# the analyst output so a >7-day-dark feed (collapses to neutral "none", which
# the in-window data_quality=="stale" label misses) stays visible in the
# decision trace and caps confidence.


def _make_agent_with_stale_days(stale_days: int = 2):
    agent = _make_agent()
    agent._processor.STALE_DAYS = stale_days  # type: ignore[attr-defined]
    return agent


@pytest.mark.asyncio
async def test_stale_feed_flags_report_and_caps_confidence():
    agent = _make_agent_with_stale_days()
    with patch(
        "discord.commentary_processor.get_futures_sentiment_staleness",
        return_value={"quality": "stale", "age_days": 14},
    ), patch.object(
        agent, "_get_active_bot_signal", return_value={"side": "LONG", "price": 100.0}
    ), patch.object(
        agent, "_get_rolling_win_rate", return_value=0.9
    ), patch.object(
        agent, "_compute_bot_boost", return_value=(0.3, 0.3)
    ), patch.object(
        agent, "_build_summary", return_value="s"
    ), patch.object(
        agent, "_build_reasoning", return_value="r"
    ):
        report = await agent.analyze(symbol="MES", current_price=5000.0, atr=10.0)

    assert report.sentiment_stale is True
    assert report.sentiment_age_days == 14
    # Even with a strong session bias + 0.9 win-rate, a stale feed caps conf ≤ 0.4.
    assert report.confidence <= agent.STALE_CONFIDENCE_CAP
    assert report.to_dict()["sentiment_stale"] is True


@pytest.mark.asyncio
async def test_fresh_feed_no_stale_flag():
    agent = _make_agent_with_stale_days()
    with patch(
        "discord.commentary_processor.get_futures_sentiment_staleness",
        return_value={"quality": "fresh", "age_days": 0},
    ), patch.object(
        agent, "_get_active_bot_signal", return_value={"side": "LONG", "price": 100.0}
    ), patch.object(
        agent, "_get_rolling_win_rate", return_value=0.6
    ), patch.object(
        agent, "_compute_bot_boost", return_value=(0.3, 0.3)
    ), patch.object(
        agent, "_build_summary", return_value="s"
    ), patch.object(
        agent, "_build_reasoning", return_value="r"
    ):
        report = await agent.analyze(symbol="MES", current_price=5000.0, atr=10.0)

    assert report.sentiment_stale is False
    assert report.sentiment_age_days == 0
