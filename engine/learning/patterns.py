"""
Trading Patterns Module — Aggregates lessons into recurring patterns.

When feedback is generated from a closed trade, this module:
1. Analyzes the trade outcome (win/loss, symbol, regime, direction, session, etc.)
2. Updates pattern library with win rates and frequencies
3. Identifies recurring conditions for pattern recommendations

Integrates with consolidator.py for persistent storage.

Pattern types (10 total):
  1. symbol_win_loss       — win/loss rate by symbol
  2. time_window           — entry hour performance (0–23)
  3. regime_pattern        — TRENDING vs RANGING regime performance
  4. direction_pattern     — LONG vs SHORT win rate per symbol
  5. session_pattern       — PRE_MARKET / RTH_EARLY / RTH_MID / RTH_LATE / OVERNIGHT
  6. signal_strength_pattern — High (>7) / Medium (5–7) / Low (<5) conviction
  7. vol_regime_pattern    — ATR expanding vs contracting
  8. day_of_week_pattern   — Monday–Friday performance
  9. drawdown_context_pattern — positive vs negative session P&L context
  10. consecutive_outcome_pattern — after win streaks vs loss streaks
"""

import inspect
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


async def _maybe_await(value):
    """Await ``value`` if it is awaitable, else return it as-is.

    The pattern-persistence path (roadmap 1.7) has to work against two
    db-manager shapes: the live ``database/manager.py`` manager exposes SYNC
    ``fetch_one``/``execute`` (used by main.py's init_db), while the async
    ``database/connection.py`` layer exposes coroutine equivalents. This helper
    lets ``_upsert_pattern_to_db`` call either without a hard-coded assumption —
    the prior unconditional ``await db_manager.fetch_one(...)`` raised TypeError
    on the sync manager, which is why this module never actually persisted a
    pattern in production despite the extractor being complete.
    """
    if inspect.isawaitable(value):
        return await value
    return value

# Session boundary definitions (UTC hours — adjust per market if needed)
_SESSION_BOUNDARIES: dict[str, tuple[int, int]] = {
    "PRE_MARKET": (9, 13),    # 09:00–13:59 UTC ≈ 05:00–09:59 ET
    "RTH_EARLY": (14, 16),   # 14:00–16:59 UTC ≈ 10:00–12:59 ET
    "RTH_MID": (17, 19),     # 17:00–19:59 UTC ≈ 13:00–15:59 ET
    "RTH_LATE": (20, 21),    # 20:00–21:59 UTC ≈ 16:00–17:59 ET
    "OVERNIGHT": (22, 8),    # 22:00–08:59 UTC (wraps midnight)
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _classify_session(hour: int) -> str:
    """Map a UTC hour (0–23) to a named session bucket."""
    for name, (start, end) in _SESSION_BOUNDARIES.items():
        if start <= end:
            if start <= hour <= end:
                return name
        else:
            # Wraps midnight
            if hour >= start or hour <= end:
                return name
    return "OVERNIGHT"


def _classify_conviction(score: float) -> str:
    """Map a numeric conviction/signal-strength score to a tier label."""
    if score > 7:
        return "HIGH"
    if score >= 5:
        return "MEDIUM"
    return "LOW"


class TradePattern:
    """Represents a recurring trading pattern discovered from closed trades."""

    def __init__(
        self,
        symbol: str,
        pattern_type: str,
        conditions: dict,
        win_count: int = 0,
        loss_count: int = 0,
        last_seen: Optional[str] = None,
    ):
        self.symbol = symbol
        self.pattern_type = pattern_type
        self.conditions = conditions
        self.win_count = win_count
        self.loss_count = loss_count
        self.last_seen = last_seen or datetime.now().isoformat()
        self.sample_count = win_count + loss_count
        self.win_rate = round(win_count / self.sample_count, 3) if self.sample_count > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "pattern_type": self.pattern_type,
            "conditions": self.conditions,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "sample_count": self.sample_count,
            "win_rate": self.win_rate,
            "last_seen": self.last_seen,
        }


def _make_pattern(
    symbol: str,
    pattern_type: str,
    conditions: dict,
    is_winner: bool,
) -> TradePattern:
    """Convenience factory — returns a single-trade TradePattern."""
    return TradePattern(
        symbol=symbol,
        pattern_type=pattern_type,
        conditions=conditions,
        win_count=1 if is_winner else 0,
        loss_count=0 if is_winner else 1,
    )


def _parse_entry_dt(entry_time_str: str) -> Optional[datetime]:
    """Parse ISO entry_time string; returns None on any failure."""
    if not entry_time_str:
        return None
    try:
        return datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


async def update_patterns_from_feedback(
    feedback_outcome: dict,
    db_manager=None,
) -> Optional[list]:
    """
    Update pattern library based on a single trade outcome from feedback.

    Args:
        feedback_outcome: Dict with fields:
            Required: symbol, pnl
            Optional: entry_time, exit_time, action, entry_price, exit_price,
                      regime, conviction_score, atr, atr_avg,
                      session_pnl, consecutive_wins, consecutive_losses
        db_manager: Optional database manager for persistence

    Returns:
        List of TradePattern objects created/updated, or None on error
    """
    try:
        symbol = feedback_outcome.get("symbol", "").upper()
        pnl = feedback_outcome.get("pnl", 0.0)
        entry_time_str = feedback_outcome.get("entry_time", "")
        is_winner = pnl > 0

        if not symbol:
            logger.warning("[LEARNING] Pattern update skipped: no symbol in feedback")
            return None

        patterns: list[TradePattern] = []
        entry_dt = _parse_entry_dt(entry_time_str)

        # ------------------------------------------------------------------
        # Pattern 1: Simple win/loss by symbol
        # ------------------------------------------------------------------
        pattern_type = f"{symbol}_winner" if is_winner else f"{symbol}_loser"
        patterns.append(
            _make_pattern(
                symbol,
                pattern_type,
                {"symbol": symbol, "outcome": "win" if is_winner else "loss"},
                is_winner,
            )
        )

        # ------------------------------------------------------------------
        # Pattern 2: Time-of-day performance (entry hour 0–23)
        # ------------------------------------------------------------------
        if entry_dt is not None:
            try:
                hour = entry_dt.hour
                patterns.append(
                    _make_pattern(
                        symbol,
                        f"time_window_{hour:02d}",
                        {"symbol": symbol, "entry_hour": hour},
                        is_winner,
                    )
                )
            except Exception as exc:
                logger.debug(f"[LEARNING] time_window pattern skipped: {exc}")

        # ------------------------------------------------------------------
        # Pattern 3: Regime pattern — TRENDING vs RANGING
        # ------------------------------------------------------------------
        regime = feedback_outcome.get("regime", "")
        if regime:
            try:
                regime_key = str(regime).upper().replace(" ", "_")
                patterns.append(
                    _make_pattern(
                        symbol,
                        f"regime_pattern_{regime_key}",
                        {"symbol": symbol, "regime": regime_key},
                        is_winner,
                    )
                )
            except Exception as exc:
                logger.debug(f"[LEARNING] regime_pattern skipped: {exc}")

        # ------------------------------------------------------------------
        # Pattern 4: Direction pattern — LONG vs SHORT per symbol
        # ------------------------------------------------------------------
        action = feedback_outcome.get("action", "")
        if action:
            try:
                direction = "LONG" if action.lower() in ("long", "buy") else "SHORT"
                patterns.append(
                    _make_pattern(
                        symbol,
                        f"direction_pattern_{direction}",
                        {"symbol": symbol, "direction": direction},
                        is_winner,
                    )
                )
            except Exception as exc:
                logger.debug(f"[LEARNING] direction_pattern skipped: {exc}")

        # ------------------------------------------------------------------
        # Pattern 5: Session pattern — named market session
        # ------------------------------------------------------------------
        if entry_dt is not None:
            try:
                session = _classify_session(entry_dt.hour)
                patterns.append(
                    _make_pattern(
                        symbol,
                        f"session_pattern_{session}",
                        {"symbol": symbol, "session": session},
                        is_winner,
                    )
                )
            except Exception as exc:
                logger.debug(f"[LEARNING] session_pattern skipped: {exc}")

        # ------------------------------------------------------------------
        # Pattern 6: Signal strength / conviction tier
        # ------------------------------------------------------------------
        conviction_score = feedback_outcome.get("conviction_score")
        if conviction_score is not None:
            try:
                tier = _classify_conviction(float(conviction_score))
                patterns.append(
                    _make_pattern(
                        symbol,
                        f"signal_strength_pattern_{tier}",
                        {"symbol": symbol, "conviction_tier": tier,
                         "conviction_score": float(conviction_score)},
                        is_winner,
                    )
                )
            except Exception as exc:
                logger.debug(f"[LEARNING] signal_strength_pattern skipped: {exc}")

        # ------------------------------------------------------------------
        # Pattern 7: Volatility regime — ATR expanding vs contracting
        # ------------------------------------------------------------------
        atr = feedback_outcome.get("atr")
        atr_avg = feedback_outcome.get("atr_avg")
        if atr is not None and atr_avg is not None:
            try:
                atr_f = float(atr)
                atr_avg_f = float(atr_avg)
                if atr_avg_f > 0:
                    vol_label = "EXPANDING" if atr_f > atr_avg_f else "CONTRACTING"
                    patterns.append(
                        _make_pattern(
                            symbol,
                            f"vol_regime_pattern_{vol_label}",
                            {"symbol": symbol, "vol_regime": vol_label,
                             "atr": round(atr_f, 4), "atr_avg": round(atr_avg_f, 4)},
                            is_winner,
                        )
                    )
            except Exception as exc:
                logger.debug(f"[LEARNING] vol_regime_pattern skipped: {exc}")

        # ------------------------------------------------------------------
        # Pattern 8: Day of week (Monday–Friday)
        # ------------------------------------------------------------------
        if entry_dt is not None:
            try:
                dow_idx = entry_dt.weekday()  # 0=Monday … 6=Sunday
                dow_name = DAY_NAMES[dow_idx]
                patterns.append(
                    _make_pattern(
                        symbol,
                        f"day_of_week_pattern_{dow_name.upper()}",
                        {"symbol": symbol, "day_of_week": dow_name},
                        is_winner,
                    )
                )
            except Exception as exc:
                logger.debug(f"[LEARNING] day_of_week_pattern skipped: {exc}")

        # ------------------------------------------------------------------
        # Pattern 9: Drawdown context — positive vs negative session P&L
        # ------------------------------------------------------------------
        session_pnl = feedback_outcome.get("session_pnl")
        if session_pnl is not None:
            try:
                context = "POSITIVE_SESSION" if float(session_pnl) >= 0 else "NEGATIVE_SESSION"
                patterns.append(
                    _make_pattern(
                        symbol,
                        f"drawdown_context_pattern_{context}",
                        {"symbol": symbol, "session_context": context,
                         "session_pnl": float(session_pnl)},
                        is_winner,
                    )
                )
            except Exception as exc:
                logger.debug(f"[LEARNING] drawdown_context_pattern skipped: {exc}")

        # ------------------------------------------------------------------
        # Pattern 10: Consecutive outcome — after win/loss streaks
        # ------------------------------------------------------------------
        consecutive_wins = feedback_outcome.get("consecutive_wins")
        consecutive_losses = feedback_outcome.get("consecutive_losses")
        if consecutive_wins is not None or consecutive_losses is not None:
            try:
                wins = int(consecutive_wins or 0)
                losses = int(consecutive_losses or 0)
                if wins >= 2:
                    streak_label = f"AFTER_WIN_STREAK_{wins}"
                elif losses >= 2:
                    streak_label = f"AFTER_LOSS_STREAK_{losses}"
                elif wins == 1:
                    streak_label = "AFTER_ONE_WIN"
                elif losses == 1:
                    streak_label = "AFTER_ONE_LOSS"
                else:
                    streak_label = "AFTER_BREAKEVEN"

                patterns.append(
                    _make_pattern(
                        symbol,
                        f"consecutive_outcome_pattern_{streak_label}",
                        {"symbol": symbol, "streak": streak_label,
                         "consecutive_wins": wins, "consecutive_losses": losses},
                        is_winner,
                    )
                )
            except Exception as exc:
                logger.debug(f"[LEARNING] consecutive_outcome_pattern skipped: {exc}")

        # ------------------------------------------------------------------
        # Persist to DB if available
        # ------------------------------------------------------------------
        if db_manager:
            try:
                for pattern in patterns:
                    await _upsert_pattern_to_db(db_manager, pattern)
            except Exception as db_err:
                logger.warning(f"[LEARNING] Failed to persist patterns to DB: {db_err}")

        logger.info(
            f"[LEARNING] Patterns updated for {symbol}: "
            f"{len(patterns)} patterns extracted, "
            f"pnl={pnl:+.2f}, outcome={'win' if is_winner else 'loss'}"
        )
        return patterns

    except Exception as e:
        logger.error(f"[LEARNING] Pattern update failed: {e}")
        return None


async def _upsert_pattern_to_db(db_manager, pattern: TradePattern) -> None:
    """Upsert a pattern into the trading_patterns table."""
    try:
        pattern_hash = _compute_pattern_hash(pattern.symbol, pattern.pattern_type)

        existing = await _maybe_await(
            db_manager.fetch_one(
                "SELECT id, win_count, loss_count FROM trading_patterns WHERE pattern_hash = ?",
                (pattern_hash,),
            )
        )

        if existing:
            new_win = existing["win_count"] + pattern.win_count
            new_loss = existing["loss_count"] + pattern.loss_count
            new_win_rate = (
                round(new_win / (new_win + new_loss), 3) if (new_win + new_loss) > 0 else 0.0
            )
            await _maybe_await(
                db_manager.execute(
                    "UPDATE trading_patterns SET win_count=?, loss_count=?, win_rate=?, "
                    "last_seen=?, is_active=1 WHERE pattern_hash=?",
                    (
                        new_win,
                        new_loss,
                        new_win_rate,
                        datetime.now().isoformat(),
                        pattern_hash,
                    ),
                )
            )
        else:
            await _maybe_await(
                db_manager.execute(
                    "INSERT INTO trading_patterns "
                    "(pattern_hash, symbol, pattern_type, conditions, win_count, loss_count, "
                    "win_rate, is_active, last_seen, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (
                        pattern_hash,
                        pattern.symbol,
                        pattern.pattern_type,
                        json.dumps(pattern.conditions),
                        pattern.win_count,
                        pattern.loss_count,
                        pattern.win_rate,
                        datetime.now().isoformat(),
                        datetime.now().isoformat(),
                    ),
                )
            )
    except Exception as e:
        logger.error(f"[LEARNING] DB upsert failed for pattern: {e}")
        raise


def _compute_pattern_hash(symbol: str, pattern_type: str) -> str:
    """Compute a deterministic hash for pattern deduplication."""
    import hashlib

    key = f"{symbol}:{pattern_type}"
    return hashlib.md5(key.encode()).hexdigest()[:16]
