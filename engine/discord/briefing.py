"""
DiscordBriefing — unified read-through facade over the four Discord consumers.

Why this exists
---------------
Four separate Discord consumer modules exist (commentary_processor, ib_levels,
signal_context, sentiment_provider), each with its own DB path helper, its own
cache, and its own shape. Agents that want a "what does Discord say about MCL
right now?" view currently have to wire all four themselves.

This module offers one stable surface:

    from discord.briefing import get_discord_briefing
    briefing = await get_discord_briefing("MCL")

Returns a DiscordBriefing dataclass with Corey's structured session bias,
today's IB levels (if reported), the keyword sentiment score + regime
multiplier, and the most-recent bot signal within the lookback window.

Caching
-------
Module-level 5-minute TTL dict keyed by (symbol.upper(), for_date_iso,
lookback_hours). The underlying providers keep their own caches too; this
wrapper avoids the coordination cost when the same briefing is requested
repeatedly within a bar (e.g. debate + trader + fundamental_analyst).

Policy
------
Per owner directive 2026-04-19, Corey #market-updates is the ONLY trusted
futures sentiment source. `corey_bias.directional_bias` and `ib_levels` are
authoritative for futures agents; `keyword_sentiment` is a weaker auxiliary
signal (keyword-matched, lossy). Reddit/Twitter/news are NOT consulted here.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from discord.commentary_processor import CoreyCommentaryProcessor, CoreySessionBias
from discord.ib_levels import IBLevelProvider
from discord.sentiment_provider import SentimentProvider
from discord.signal_context import DiscordSignalContext

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300  # 5-minute TTL — matches DiscordSignalContext.STATS_TTL_SECONDS


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DiscordBriefing:
    """One-shot Discord intelligence summary for a symbol."""

    symbol: str  # normalized uppercase JARVIS symbol (e.g. "MCL")
    discord_symbol: str  # mapped Discord full symbol (e.g. "CL")
    as_of: datetime  # when this briefing was assembled (UTC)
    corey_bias: CoreySessionBias  # structured session bias from commentary_processor
    ib_levels: Optional[dict]  # ib_high/low/ibu50/ibu100/ibd50/ibd100/auction_context, or None
    keyword_sentiment: float  # -1.0..+1.0 from sentiment_provider
    regime_multiplier: float  # 0.7..1.3 from sentiment_provider
    recent_signal: Optional[dict]  # most recent discord_bot_signals row within lookback, or None
    lookback_hours: int  # window used for recent_signal
    warnings: list[str] = field(default_factory=list)
    knowledge_context: Optional[list[dict]] = (
        None  # curated gbrain hits (only when enriched); ADVISORY — prompt context only, never gate/sizing input
    )
    knowledge_context_tier: Optional[str] = (
        None  # rerank tier that produced knowledge_context: voyage|local|off — observability for silent Voyage->local degradation
    )

    @property
    def headline(self) -> str:
        """Short human-readable one-liner (e.g. 'MCL range_day, neutral, inside_ib, conv 0.30')."""
        return (
            f"{self.symbol} {self.corey_bias.session_type}, "
            f"{self.corey_bias.directional_bias}, "
            f"{self.corey_bias.ib_bias}, conv {self.corey_bias.conviction:.2f}"
        )

    @property
    def actionable(self) -> bool:
        """True iff Corey's commentary is fresh, directional, and high-conviction."""
        return (
            self.corey_bias.data_quality == "fresh"
            and self.corey_bias.directional_bias != "neutral"
            and self.corey_bias.conviction >= 0.5
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "symbol": self.symbol,
            "discord_symbol": self.discord_symbol,
            "as_of": self.as_of.isoformat(),
            "corey_bias": self.corey_bias.to_dict(),
            "ib_levels": self.ib_levels,
            "keyword_sentiment": self.keyword_sentiment,
            "regime_multiplier": self.regime_multiplier,
            "recent_signal": self.recent_signal,
            "lookback_hours": self.lookback_hours,
            "headline": self.headline,
            "actionable": self.actionable,
            "warnings": list(self.warnings),
        }
        # Only surface knowledge_context (+ its rerank tier) when enrichment
        # actually ran, so the default (non-enriched) payload stays byte-identical
        # to the pre-feature shape — no spurious null key for the
        # overwhelming-majority code path.
        if self.knowledge_context is not None:
            out["knowledge_context"] = self.knowledge_context
            out["knowledge_context_tier"] = self.knowledge_context_tier
        return out


# ---------------------------------------------------------------------------
# Singletons + cache
# ---------------------------------------------------------------------------

_processor: Optional[CoreyCommentaryProcessor] = None
_ib_provider: Optional[IBLevelProvider] = None
_sentiment: Optional[SentimentProvider] = None
_signal_ctx: Optional[DiscordSignalContext] = None

# (symbol_upper, for_date_iso, lookback_hours, enriched) -> (briefing, fetch_time_monotonic)
# `enriched` is part of the key so an enriched request never returns a plain
# cached briefing (or vice versa) — the two have different shapes.
_cache: dict[tuple[str, str, int, bool], tuple[DiscordBriefing, float]] = {}


def _get_processor() -> CoreyCommentaryProcessor:
    global _processor
    if _processor is None:
        _processor = CoreyCommentaryProcessor()
    return _processor


def _get_ib_provider() -> IBLevelProvider:
    global _ib_provider
    if _ib_provider is None:
        _ib_provider = IBLevelProvider()
    return _ib_provider


def _get_sentiment() -> SentimentProvider:
    global _sentiment
    if _sentiment is None:
        _sentiment = SentimentProvider()
    return _sentiment


def _get_signal_ctx() -> DiscordSignalContext:
    global _signal_ctx
    if _signal_ctx is None:
        _signal_ctx = DiscordSignalContext()
    return _signal_ctx


def clear_cache() -> None:
    """Drop the module-level briefing cache. Tests + force-refresh flows use this."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


async def get_discord_briefing(
    symbol: str,
    lookback_hours: int = 24,
    for_date: Optional[date] = None,
    *,
    enriched_with_knowledge: bool = False,
    knowledge_limit: int = 3,
    knowledge_min_score: float = 0.2,
) -> DiscordBriefing:
    """
    Return the unified Discord briefing for `symbol`.

    Args:
        symbol:          JARVIS micro or Discord full symbol (MCL/CL, MES/ES, etc.)
        lookback_hours:  window for `recent_signal` probe (default 24h)
        for_date:        trading date to brief on (default today, useful for backtests)
        enriched_with_knowledge:
                         when True, attach `knowledge_context` — the top curated
                         gbrain knowledge hits for a query derived from Corey's
                         session bias + symbol. ADVISORY context only: it is
                         fallback-safe (a daemon-down/error leaves it None, never
                         raises) and MUST NOT feed gate-v2 / sizing / execution.
                         Off by default so existing callers are byte-identical.
        knowledge_limit:     max curated hits to attach (default 3)
        knowledge_min_score: reranker relevance floor for those hits (default 0.2)

    Returns:
        DiscordBriefing. Never raises for missing data — falls back to neutral
        dataclasses with a string in `warnings` describing the degraded source.
    """
    symbol = symbol.upper()
    if for_date is None:
        for_date = date.today()

    cache_key = (symbol, for_date.isoformat(), lookback_hours, enriched_with_knowledge)
    cached = _cache.get(cache_key)
    if cached is not None:
        briefing, fetched_at = cached
        if time.monotonic() - fetched_at < CACHE_TTL_SECONDS:
            return briefing

    warnings: list[str] = []

    # Corey session bias (async — LLM extraction)
    try:
        corey_bias = await _get_processor().get_session_bias(for_date)
    except Exception as exc:
        logger.warning("[DiscordBriefing] Corey bias fetch failed for %s: %s", symbol, exc)
        from discord.commentary_processor import _neutral_bias

        corey_bias = _neutral_bias(for_date, message_count=0)
        warnings.append(f"corey_bias_failed:{type(exc).__name__}")

    # IB levels (sync, date-indexed, Discord-symbol keyed)
    ib_provider = _get_ib_provider()
    discord_symbol = ib_provider._map_symbol(symbol)
    try:
        ib_levels = ib_provider.get_levels(symbol, for_date)
    except Exception as exc:
        logger.warning("[DiscordBriefing] IB levels fetch failed for %s: %s", symbol, exc)
        ib_levels = None
        warnings.append(f"ib_levels_failed:{type(exc).__name__}")

    # Keyword sentiment + regime multiplier (sync, cached in discord_daily_sentiment)
    try:
        sentiment_provider = _get_sentiment()
        keyword_sentiment = sentiment_provider.get_sentiment(for_date)
        regime_multiplier = sentiment_provider.get_regime_multiplier(for_date)
    except Exception as exc:
        logger.warning("[DiscordBriefing] Keyword sentiment failed for %s: %s", symbol, exc)
        keyword_sentiment = 0.0
        regime_multiplier = 1.0
        warnings.append(f"keyword_sentiment_failed:{type(exc).__name__}")

    # Recent signal (sync) — use raw DB query instead of get_features (which needs ATR/price)
    recent_signal = _fetch_recent_signal(discord_symbol, lookback_hours, warnings)

    # Optional curated-knowledge enrichment (opt-in). ADVISORY ONLY — attached for
    # agent prompt context; never consulted by gate-v2 / sizing / execution. Fully
    # fallback-safe: any failure (daemon down, error dict, no hits) leaves
    # knowledge_context None and is logged as a non-fatal warning.
    knowledge_context: Optional[list[dict]] = None
    knowledge_context_tier: Optional[str] = None
    if enriched_with_knowledge:
        knowledge_context, knowledge_context_tier = await _fetch_knowledge_context(
            symbol, corey_bias, knowledge_limit, knowledge_min_score, warnings
        )

    briefing = DiscordBriefing(
        symbol=symbol,
        discord_symbol=discord_symbol,
        as_of=datetime.utcnow(),
        corey_bias=corey_bias,
        ib_levels=ib_levels,
        keyword_sentiment=keyword_sentiment,
        regime_multiplier=regime_multiplier,
        recent_signal=recent_signal,
        lookback_hours=lookback_hours,
        warnings=warnings,
        knowledge_context=knowledge_context,
        knowledge_context_tier=knowledge_context_tier,
    )
    _cache[cache_key] = (briefing, time.monotonic())
    return briefing


async def _fetch_knowledge_context(
    symbol: str,
    corey_bias: CoreySessionBias,
    limit: int,
    min_score: float,
    warnings: list[str],
) -> tuple[Optional[list[dict]], Optional[str]]:
    """Derive a knowledge query from the session bias and pull curated gbrain hits.

    Returns (hits_or_None, rerank_tier_or_None). Fallback-safe by contract:
    returns (None, None) (and appends a warning) on any error or when the daemon
    yields nothing. The hits are advisory prompt context — slug/title/type/
    similarity/content per hit — and MUST NOT be wired into gate-v2, sizing, or
    execution decisions. The tier (voyage|local|off) is surfaced for
    observability so a silent Voyage->local rerank degradation is visible.
    """
    # Intent-bearing query from Corey's structured read (session type + direction)
    # plus the symbol, so retrieval targets the relevant strategy/risk knowledge.
    query = (
        f"{symbol} {corey_bias.session_type} {corey_bias.directional_bias} "
        "trading setup levels risk management"
    ).strip()
    try:
        from discord.knowledge import search_knowledge_core

        res = await search_knowledge_core(query, limit=limit, min_score=min_score)
        if res.get("error"):
            warnings.append(f"knowledge_context_failed:{res['error'][:60]}")
            return None, None
        hits = res.get("results") or []
        return (hits or None), (res.get("rerank") if hits else None)
    except Exception as exc:
        logger.warning("[DiscordBriefing] knowledge enrichment failed for %s: %s", symbol, exc)
        warnings.append(f"knowledge_context_failed:{type(exc).__name__}")
        return None, None


def _fetch_recent_signal(
    discord_symbol: str,
    lookback_hours: int,
    warnings: list[str],
) -> Optional[dict]:
    """Fetch most-recent discord_bot_signals row within lookback_hours window."""
    signal_ctx = _get_signal_ctx()
    since = datetime.utcnow() - timedelta(hours=lookback_hours)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        with sqlite3.connect(signal_ctx.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT symbol, direction, signal_type, entry_price,
                       target1, target2, stop1, win_rate, timestamp
                FROM discord_bot_signals
                WHERE symbol = ?
                  AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (discord_symbol, since_str),
            ).fetchone()
        return dict(row) if row else None
    except Exception as exc:
        logger.warning(
            "[DiscordBriefing] Recent-signal fetch failed for %s: %s", discord_symbol, exc
        )
        warnings.append(f"recent_signal_failed:{type(exc).__name__}")
        return None
