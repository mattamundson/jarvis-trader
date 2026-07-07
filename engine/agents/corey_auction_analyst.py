"""
CoreyAuctionAnalystAgent — Stage 1 analyst combining Corey's auction theory
commentary bias with active Discord bot signal alignment.

Produces a CoreyAuctionReport with:
  signal      (-1.0 to +1.0): commentary directional bias + bot signal proximity boost
  confidence  (0.0 to 1.0):   commentary conviction scaled by bot signal win rate

Signal computation:
  base_signal = {"bullish": +0.5, "bearish": -0.5, "neutral": 0.0}
  bot_boost   = 0 | ±0.3 (within 1.5x ATR) | ±0.5 (within 0.5x ATR)
  signal      = clamp(base_signal + bot_boost, -1.0, +1.0)

Confidence computation:
  win_rate_multiplier = 0.7 + 0.6 * ((win_rate - 0.5) / 0.5)   [0.7 at 50%, 1.3 at 100%]
  confidence          = min(1.0, commentary.conviction × multiplier)
  [capped at 0.4 when data_quality == "stale"]

Symbol mapping (JARVIS micro-contracts → Discord symbols):
  MES→ES, MNQ→NQ, MCL→CL, MGC→GC, MYM→YM, M2K→RTY
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["CoreyAuctionAnalystAgent", "CoreyAuctionReport"]

# ---------------------------------------------------------------------------
# Symbol map
# ---------------------------------------------------------------------------

SYMBOL_MAP = {
    "MES": "ES",
    "MNQ": "NQ",
    "MCL": "CL",
    "MGC": "GC",
    "MYM": "YM",
    "M2K": "RTY",
}


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class CoreyAuctionReport:
    """Output from the Corey Auction Analyst Stage 1 agent."""

    symbol: str
    timestamp: datetime
    signal: float              # -1.0 to +1.0
    confidence: float          # 0.0 to 1.0
    session_type: str          # from CoreySessionBias
    directional_bias: str      # "bullish" | "bearish" | "neutral"
    key_levels: list[float]
    active_bot_signal: dict    # most recent relevant bot signal, or {}
    bot_win_rate: float        # rolling 30-day win rate (0.0-1.0), 0.0 if none
    alignment_score: float     # commentary × bot signal alignment (-1.0 to +1.0)
    ib_bias: str               # "above_ib" | "below_ib" | "inside_ib" | "not_mentioned"
    corey_quote: str
    summary: str               # one-line description for debate researchers
    reasoning: str             # detailed reasoning
    data_quality: str          # "full" | "commentary_only" | "signals_only" | "stale" | "none"
    # Decision-time staleness flag for the SOLE sanctioned futures-sentiment
    # feed. data_quality only sees "stale" within the 7-day fetch window; a feed
    # dark >7 days collapses to "none" (neutral) and hides that the source has
    # gone silent. sentiment_stale uses the true MAX(timestamp) age so a long
    # outage stays visible in the decision trace even when the bias is neutral.
    sentiment_stale: bool = False
    sentiment_age_days: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "signal": self.signal,
            "confidence": self.confidence,
            "session_type": self.session_type,
            "directional_bias": self.directional_bias,
            "key_levels": self.key_levels,
            "active_bot_signal": self.active_bot_signal,
            "bot_win_rate": self.bot_win_rate,
            "alignment_score": self.alignment_score,
            "ib_bias": self.ib_bias,
            "corey_quote": self.corey_quote,
            "summary": self.summary,
            "reasoning": self.reasoning,
            "data_quality": self.data_quality,
            "sentiment_stale": self.sentiment_stale,
            "sentiment_age_days": self.sentiment_age_days,
        }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class CoreyAuctionAnalystAgent:
    """
    Stage 1 pipeline agent — Corey Auction Theory overlay.

    Reads today's commentary from CoreyCommentaryProcessor (LLM-extracted, cached),
    cross-references active Discord bot signals for the symbol, and emits a
    CoreyAuctionReport with signal/confidence values for the Bull/Bear debate.

    Gracefully degrades:
    - If commentary unavailable → signal = 0.0, confidence = 0.0
    - If bot signals unavailable → bot_boost = 0.0, uses commentary conviction only
    - If current_price = 0 → proximity boost skipped, alignment still computed
    - If data is stale (> 2 days old) → confidence capped at 0.4
    """

    BOT_SIGNAL_LOOKBACK_HOURS = 4
    WIN_RATE_LOOKBACK_DAYS = 30
    STALE_CONFIDENCE_CAP = 0.4

    def __init__(self, llm_client=None, db_path: Optional[str] = None):
        """
        Args:
            llm_client: Object with .api_key attribute (Anthropic key).
            db_path:    Override for the SQLite DB path (defaults to data/jarvis_trader.db).
        """
        self._llm = llm_client
        api_key = getattr(llm_client, "api_key", None) or os.getenv("ANTHROPIC_API_KEY", "")

        if db_path is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(base, "data", "jarvis_trader.db")
        self._db_path = db_path

        from discord.commentary_processor import CoreyCommentaryProcessor
        # Pass the engine LLM client through so bias extraction inherits the
        # provider-fallback chain (B4, 2026-06-11).
        self._processor = CoreyCommentaryProcessor(
            db_path=db_path, api_key=api_key, llm_client=llm_client
        )

    async def analyze(
        self,
        symbol: str,
        current_price: float = 0.0,
        atr: float = 0.0,
        hp_context: Optional[dict] = None,
        **kwargs,
    ) -> CoreyAuctionReport:
        """
        Run the Corey Auction Theory analysis for a symbol.

        Args:
            symbol:        JARVIS trading symbol (e.g. "MCL", "MNQ", "MES")
            current_price: Current market price (0.0 = skip proximity boost)
            atr:           Average True Range in price points (0.0 = skip proximity boost)
            hp_context:    Optional Hidden Pivots dict with "direction"/"bias" key (bullish/bearish/long/short)
                          When provided and direction matches Corey bias, alignment_score is boosted

        Returns:
            CoreyAuctionReport with signal, confidence, and full auction context
        """
        now = datetime.now()
        discord_symbol = SYMBOL_MAP.get(symbol.upper(), symbol.upper())

        # --- Step 1: Get session bias from commentary ----------------------
        try:
            session_bias = await self._processor.get_session_bias()
        except Exception as e:
            logger.error("[CoreyAuction] Commentary processor failed for %s: %s", symbol, e)
            return self._neutral_report(symbol, now, reason=f"commentary processor error: {e}")

        # --- Step 1b: True-age staleness of the sole futures-sentiment feed --
        # session_bias.data_quality only labels "stale" within the 7-day fetch
        # window; a feed dark >7 days collapses to "none" and the silence is
        # invisible at decision time. Query MAX(timestamp) age so a long outage
        # stays flagged in the decision trace even when the bias is neutral.
        sentiment_stale = False
        sentiment_age_days: Optional[int] = None
        try:
            from discord.commentary_processor import get_futures_sentiment_staleness

            _st = get_futures_sentiment_staleness()
            sentiment_age_days = _st.get("age_days")
            sentiment_stale = _st.get("quality") == "stale" or (
                sentiment_age_days is not None
                and sentiment_age_days > self._processor.STALE_DAYS
            )
            if sentiment_stale:
                logger.warning(
                    "[CoreyAuction] futures sentiment STALE for %s — Corey feed is "
                    "%s days old (sole sanctioned source); confidence capped, signal "
                    "down-weighted to neutral lean",
                    symbol,
                    sentiment_age_days,
                )
        except Exception:
            # Never let the staleness probe break scoring — annotate-first.
            pass

        # --- Step 2: Get active bot signals for symbol ---------------------
        bot_signal = self._get_active_bot_signal(discord_symbol)
        bot_win_rate = self._get_rolling_win_rate(discord_symbol)

        # ── TV Live Data (optional enrichment) ────────────────────────────
        tv_corey_score = None
        tv_ib_high = None
        tv_ib_low = None
        tv_poc = None
        try:
            from data.tradingview_feed import TradingViewFeed
            _tv = TradingViewFeed()
            _tv_snap = _tv.get_snapshot(symbol)
            if _tv_snap and _tv_snap.data_quality != "unavailable":
                tv_corey_score = _tv_snap.corey_score
                tv_ib_high = _tv_snap.ib_high
                tv_ib_low = _tv_snap.ib_low
                tv_poc = _tv_snap.vp_poc
        except Exception:
            pass

        # --- Step 3: Compute signal ----------------------------------------
        base_signal = {"bullish": 0.5, "bearish": -0.5, "neutral": 0.0}.get(
            session_bias.directional_bias, 0.0
        )

        bot_boost, alignment_score = self._compute_bot_boost(
            bot_signal=bot_signal,
            directional_bias=session_bias.directional_bias,
            current_price=current_price,
            atr=atr,
        )

        # Hidden Pivots cross-confirmation — boost alignment when HP pattern matches Corey bias
        if hp_context is not None and isinstance(hp_context, dict):
            try:
                hp_direction = hp_context.get("direction") or hp_context.get("bias")
                if hp_direction in ("bullish", "long") and alignment_score > 0.2:
                    alignment_score = min(1.0, alignment_score + 0.15)
                elif hp_direction in ("bearish", "short") and alignment_score < -0.2:
                    alignment_score = max(-1.0, alignment_score - 0.15)
            except Exception:
                pass  # graceful: never let HP wiring break Corey scoring

        signal = float(max(-1.0, min(1.0, base_signal + bot_boost)))

        # If TV Corey score available, blend it in as a strong anchor
        if tv_corey_score is not None:
            signal = signal * 0.70 + tv_corey_score * 0.30

        # --- Step 4: Compute confidence ------------------------------------
        win_rate_multiplier = 0.7 + 0.6 * max(0.0, (bot_win_rate - 0.5) / 0.5)
        confidence = float(min(1.0, session_bias.conviction * win_rate_multiplier))

        # Stale cap — fire on either the in-window "stale" label or the true-age
        # staleness (catches the >7-day silent-neutral case the label misses).
        if session_bias.data_quality == "stale" or sentiment_stale:
            confidence = min(confidence, self.STALE_CONFIDENCE_CAP)

        # --- Step 5: Determine data_quality label --------------------------
        has_commentary = session_bias.message_count > 0
        has_bot = bool(bot_signal)
        if has_commentary and has_bot and session_bias.data_quality == "fresh":
            data_quality = "full"
        elif has_commentary and session_bias.data_quality == "stale":
            data_quality = "stale"
        elif has_commentary:
            data_quality = "commentary_only"
        elif has_bot:
            data_quality = "signals_only"
        else:
            data_quality = "none"

        # --- Step 6: Build summary / reasoning ----------------------------
        summary = self._build_summary(symbol, session_bias, bot_signal, bot_win_rate, signal, confidence)
        reasoning = self._build_reasoning(
            session_bias, bot_signal, bot_win_rate, base_signal, bot_boost, alignment_score,
            current_price, atr,
            tv_corey_score=tv_corey_score,
            tv_ib_high=tv_ib_high,
            tv_ib_low=tv_ib_low,
            tv_poc=tv_poc,
        )

        logger.info(
            "[CoreyAuction] %s: bias=%s session=%s bot_wr=%.0f%% alignment=%.2f signal=%.2f conf=%.2f quality=%s",
            symbol, session_bias.directional_bias, session_bias.session_type,
            bot_win_rate * 100, alignment_score, signal, confidence, data_quality,
        )

        return CoreyAuctionReport(
            symbol=symbol,
            timestamp=now,
            signal=round(signal, 4),
            confidence=round(confidence, 4),
            session_type=session_bias.session_type,
            directional_bias=session_bias.directional_bias,
            key_levels=session_bias.key_levels,
            active_bot_signal=bot_signal or {},
            bot_win_rate=round(bot_win_rate, 4),
            alignment_score=round(alignment_score, 4),
            ib_bias=session_bias.ib_bias,
            corey_quote=session_bias.corey_quote,
            summary=summary,
            reasoning=reasoning,
            data_quality=data_quality,
            sentiment_stale=sentiment_stale,
            sentiment_age_days=sentiment_age_days,
        )

    # ── Bot Signal Queries ─────────────────────────────────────────────────

    def _get_active_bot_signal(self, discord_symbol: str) -> Optional[dict]:
        """
        Return the most recent LONG or SHORT signal for the symbol in the last 4 hours.
        Returns None if no signal found.
        """
        since = (datetime.now() - timedelta(hours=self.BOT_SIGNAL_LOOKBACK_HOURS)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """
                SELECT direction, entry_price, target1, target2, stop1,
                       win_rate, wins, losses, rr
                FROM discord_bot_signals
                WHERE symbol = ?
                  AND timestamp >= ?
                  AND direction IN ('LONG', 'SHORT')
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (discord_symbol, since),
            )
            row = cur.fetchone()
            conn.close()
            if row is None:
                return None
            d = dict(row)
            # win_rate stored as percentage in DB → normalize to 0.0-1.0
            if d.get("win_rate") is not None:
                d["win_rate"] = float(d["win_rate"]) / 100.0
            return d
        except Exception as e:
            logger.warning("[CoreyAuction] Bot signal query failed for %s: %s", discord_symbol, e)
            return None

    def _get_rolling_win_rate(self, discord_symbol: str) -> float:
        """Return rolling 30-day win rate for symbol (0.0-1.0). Returns 0.0 on error."""
        since = (datetime.now() - timedelta(days=self.WIN_RATE_LOOKBACK_DAYS)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        try:
            conn = sqlite3.connect(self._db_path)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT AVG(win_rate / 100.0)
                FROM discord_bot_signals
                WHERE symbol = ?
                  AND timestamp >= ?
                  AND win_rate IS NOT NULL
                  AND win_rate > 0
                """,
                (discord_symbol, since),
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0] is not None:
                return float(max(0.0, min(1.0, row[0])))
        except Exception as e:
            logger.warning("[CoreyAuction] Win rate query failed for %s: %s", discord_symbol, e)
        return 0.0

    # ── Signal Computation ─────────────────────────────────────────────────

    def _compute_bot_boost(
        self,
        bot_signal: Optional[dict],
        directional_bias: str,
        current_price: float,
        atr: float,
    ) -> tuple[float, float]:
        """
        Compute bot signal boost and alignment score.

        Returns:
            (bot_boost, alignment_score)
            bot_boost:       ±0.0 / ±0.3 / ±0.5 depending on proximity and alignment
            alignment_score: -1.0 (opposed), 0.0 (neutral/no signal), +1.0 (aligned)
        """
        if not bot_signal:
            return 0.0, 0.0

        sig_dir = str(bot_signal.get("direction") or "").upper()
        if sig_dir not in ("LONG", "SHORT"):
            return 0.0, 0.0

        # Alignment: commentary bias vs bot signal direction
        commentary_long = directional_bias == "bullish"
        commentary_short = directional_bias == "bearish"
        bot_long = sig_dir == "LONG"
        bot_short = sig_dir == "SHORT"

        if (commentary_long and bot_long) or (commentary_short and bot_short):
            alignment_score = 1.0
        elif (commentary_long and bot_short) or (commentary_short and bot_long):
            alignment_score = -1.0
        else:
            alignment_score = 0.0

        # Direction multiplier for boost (+1 for aligned, -1 for opposed)
        direction_mult = alignment_score  # already ±1 or 0

        # Proximity boost (only when price and ATR are available)
        if current_price > 0 and atr > 0:
            entry = bot_signal.get("entry_price")
            if entry and float(entry) > 0:
                distance = abs(current_price - float(entry))
                if distance <= atr * 0.5:
                    boost_magnitude = 0.5
                elif distance <= atr * 1.5:
                    boost_magnitude = 0.3
                else:
                    boost_magnitude = 0.0
            else:
                boost_magnitude = 0.3  # signal exists, no entry — moderate boost
        else:
            boost_magnitude = 0.3  # no price data — moderate boost if aligned

        bot_boost = direction_mult * boost_magnitude
        return float(bot_boost), float(alignment_score)

    # ── Formatting ─────────────────────────────────────────────────────────

    def _build_summary(
        self,
        symbol: str,
        bias,
        bot_signal: Optional[dict],
        bot_win_rate: float,
        signal: float,
        confidence: float,
    ) -> str:
        direction = bias.directional_bias.upper()
        session = bias.session_type.replace("_", " ")
        parts = [f"Corey: {session}, {direction} bias (conf={confidence:.0%})"]
        if bot_signal:
            sig_dir = bot_signal.get("direction", "?")
            wr_str = f"win_rate={bot_win_rate:.0%}" if bot_win_rate > 0 else "win_rate=n/a"
            parts.append(f"Bot signal: {symbol} {sig_dir} ({wr_str})")
        if bias.corey_quote:
            parts.append(f'"{bias.corey_quote[:100]}"')
        return " | ".join(parts)

    def _build_reasoning(
        self,
        bias,
        bot_signal: Optional[dict],
        bot_win_rate: float,
        base_signal: float,
        bot_boost: float,
        alignment_score: float,
        current_price: float,
        atr: float,
        tv_corey_score: Optional[float] = None,
        tv_ib_high: Optional[float] = None,
        tv_ib_low: Optional[float] = None,
        tv_poc: Optional[float] = None,
    ) -> str:
        lines = [
            f"Session type: {bias.session_type} | IB bias: {bias.ib_bias}",
            f"Directional bias: {bias.directional_bias} (conviction {bias.conviction:.0%}) → base signal {base_signal:+.2f}",
            f"Data quality: {bias.data_quality} | Messages used: {bias.message_count}",
        ]
        if bias.key_levels:
            levels_str = ", ".join(f"{l:.2f}" for l in bias.key_levels[:5])  # noqa: E741  # OHLC convention
            lines.append(f"Key levels: {levels_str}")
        if bias.specific_triggers:
            lines.append("Triggers:")
            for t in bias.specific_triggers[:3]:
                lines.append(f"  - {t}")
        if bot_signal:
            entry = bot_signal.get("entry_price", "?")
            target = bot_signal.get("target1", "?")
            stop = bot_signal.get("stop1", "?")
            rr = bot_signal.get("rr", "?")
            lines.append(
                f"Bot signal: {bot_signal.get('direction')} @ {entry} | T1={target} | Stop={stop} | R:R={rr}"
            )
            lines.append(
                f"Bot win rate (30d): {bot_win_rate:.0%} | Alignment: {alignment_score:+.1f} | Bot boost: {bot_boost:+.2f}"
            )
            if current_price > 0 and atr > 0:
                entry_f = float(entry) if entry != "?" else 0
                if entry_f > 0:
                    dist = abs(current_price - entry_f)
                    lines.append(
                        f"Price proximity: {dist:.2f} pts from entry ({dist/atr:.1f}x ATR)"
                    )
        else:
            lines.append("Bot signals: none active in last 4h")
        if tv_corey_score is not None:
            lines.append(
                "TRADINGVIEW COREY INDICATORS (live):"
            )
            lines.append(
                f"- Corey Score (TV): {tv_corey_score:.2f} (direct numerical anchor from TradingView)"
            )
            lines.append(
                f"- IB Levels (TV): High={tv_ib_high} Low={tv_ib_low}"
            )
            lines.append(f"- POC (TV): {tv_poc}")
        return "\n".join(lines)

    # ── Fallback ────────────────────────────────────────────────────────────

    def _neutral_report(self, symbol: str, now: datetime, reason: str = "") -> CoreyAuctionReport:
        return CoreyAuctionReport(
            symbol=symbol,
            timestamp=now,
            signal=0.0,
            confidence=0.0,
            session_type="uncertain",
            directional_bias="neutral",
            key_levels=[],
            active_bot_signal={},
            bot_win_rate=0.0,
            alignment_score=0.0,
            ib_bias="not_mentioned",
            corey_quote="",
            summary=f"Corey auction analysis unavailable ({reason})",
            reasoning=reason,
            data_quality="none",
        )
