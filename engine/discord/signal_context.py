# engine/discord/signal_context.py
#
# DiscordSignalContext — provides 5 features for the RL agent state space
# features are appended at indices 18-22 after the existing 18 features
#
# Uses TTL caching (5 min) for rolling 30-day win rate stats
# Uses a simple recency check for "active signal within last 4 bars"
#
# NOTE: The discord_bot_signals table stores win_rate as a percentage (0–100),
# not a ratio (0.0–1.0). This module divides by 100 when returning win_rate.
# Real column names: entry_price, target1, target2, stop1 (not entry, t1, t2, stop)

import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional


class DiscordSignalContext:
    """
    Queries discord_bot_signals for RL feature injection.

    The 5 features (indices 18-22 in state vector):
      18: discord_signal_active     — 1 if same-symbol signal in last 4 bars
      19: discord_win_rate_context  — rolling 30-day win rate (0.0-1.0)
      20: discord_proximity_entry   — (price - entry_price) / ATR, clamped [-1, 1]
      21: discord_proximity_target  — abs(price - target1) / ATR, clamped [0, 2]
      22: discord_alignment         — -1/0/+1 alignment with JARVIS bias

    Maps JARVIS micro-contract symbols to Discord symbols.
    TTL cache (5 min) on rolling stats to avoid per-bar DB queries.

    win_rate in DB is stored as a percentage (e.g. 76.8 means 76.8%).
    It is divided by 100 before returning so the feature is in [0.0, 1.0].
    """

    BAR_MINUTES = 15  # default bar size for "4 bars" lookback
    WIN_RATE_LOOKBACK_DAYS = 30
    STATS_TTL_SECONDS = 300  # 5-minute TTL on rolling stats cache

    SYMBOL_MAP = {
        "MES": "ES",
        "MNQ": "NQ",
        "MGC": "GC",
        "MCL": "CL",
        "MYM": "YM",
        "M2K": "RTY",
    }

    def __init__(self, db_path: str = None, bar_minutes: int = 15):
        if db_path is None:
            # DB lives at engine/data/jarvis_trader.db.
            # engine/discord/signal_context.py → parent = engine/discord/ → parent = engine/
            # Then append /data/jarvis_trader.db. The previous 3-levels-up
            # walked to the workspace root and caused a split-brain DB on
            # 2026-04-10 (fix: anchor at engine/ root, not workspace root).
            engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(engine_root, "data", "jarvis_trader.db")
        self.db_path = db_path
        self.bar_minutes = bar_minutes
        # Rolling stats cache: key = (discord_symbol, date_str) → (stats_dict, fetch_time)
        self._stats_cache: dict = {}

    def _map_symbol(self, symbol: str) -> str:
        """Map JARVIS micro-contract symbol to Discord full-contract symbol."""
        return self.SYMBOL_MAP.get(symbol.upper(), symbol.upper())

    def get_features(
        self,
        symbol: str,
        timestamp: datetime,
        price: float,
        atr: float,
        jarvis_bias: str = "NEUTRAL",  # 'LONG', 'SHORT', or 'NEUTRAL'
    ) -> dict:
        """
        Return dict with 5 discord feature values.

        Args:
            symbol:       JARVIS or Discord symbol (MES, ES, NQ, etc.)
            timestamp:    current bar timestamp
            price:        current price (close of bar)
            atr:          ATR value for normalization
            jarvis_bias:  JARVIS's current directional bias

        Returns:
            {
                'discord_signal_active': float (0.0 or 1.0),
                'discord_win_rate_context': float (0.0-1.0),
                'discord_proximity_entry': float (-1.0 to 1.0),
                'discord_proximity_target': float (0.0-2.0),
                'discord_alignment': float (-1.0, 0.0, or 1.0),
            }
        """
        discord_symbol = self._map_symbol(symbol)

        # Safe ATR default
        if atr is None or atr <= 0:
            atr = 1.0

        # Look for recent signal (last 4 bars)
        lookback_minutes = self.bar_minutes * 4
        since = timestamp - timedelta(minutes=lookback_minutes)
        recent_signal = self._get_recent_signal(discord_symbol, since, timestamp)

        # Effective price for proximity: live quote, else signal entry (dashboard/API with no IBKR)
        price_eff: float
        if price is not None and float(price) > 0:
            price_eff = float(price)
        elif recent_signal and recent_signal.get("entry_price") and float(recent_signal["entry_price"]) > 0:
            price_eff = float(recent_signal["entry_price"])
        else:
            price_eff = 0.0

        # Feature 18: signal active
        signal_active = 1.0 if recent_signal is not None else 0.0

        # Feature 19: 30-day rolling win rate (cached, normalized to 0.0-1.0)
        win_rate = self._get_rolling_win_rate(discord_symbol, timestamp)

        # Feature 20: proximity to entry_price
        if recent_signal and recent_signal.get("entry_price") and recent_signal["entry_price"] > 0 and price_eff > 0:
            proximity_entry = (price_eff - recent_signal["entry_price"]) / atr
            proximity_entry = max(-1.0, min(1.0, proximity_entry))
        else:
            proximity_entry = 0.0

        # Feature 21: proximity to target1
        if recent_signal and recent_signal.get("target1") and recent_signal["target1"] > 0 and price_eff > 0:
            proximity_target = abs(price_eff - recent_signal["target1"]) / atr
            proximity_target = max(0.0, min(2.0, proximity_target))
        else:
            proximity_target = 0.0

        # Feature 22: alignment with JARVIS bias
        if recent_signal is None:
            alignment = 0.0
        else:
            # direction may be None in DB even when a row exists — guard with `or ''`
            sig_dir = (recent_signal.get("direction") or "").upper()
            jarvis_upper = jarvis_bias.upper()
            if sig_dir == jarvis_upper:
                alignment = 1.0
            elif (sig_dir == "LONG" and jarvis_upper == "SHORT") or (
                sig_dir == "SHORT" and jarvis_upper == "LONG"
            ):
                alignment = -1.0
            else:
                alignment = 0.0

        return {
            "discord_signal_active": signal_active,
            "discord_win_rate_context": win_rate,
            "discord_proximity_entry": proximity_entry,
            "discord_proximity_target": proximity_target,
            "discord_alignment": alignment,
        }

    def get_feature_list(self, *args, **kwargs) -> list:
        """Return features as ordered list [f18, f19, f20, f21, f22]."""
        d = self.get_features(*args, **kwargs)
        return [
            d["discord_signal_active"],
            d["discord_win_rate_context"],
            d["discord_proximity_entry"],
            d["discord_proximity_target"],
            d["discord_alignment"],
        ]

    def _get_recent_signal(
        self,
        discord_symbol: str,
        since: datetime,
        until: datetime,
    ) -> Optional[dict]:
        """Get most recent signal for symbol in [since, until] window.

        DB timestamps have timezone offsets (e.g. '2023-07-27T12:12:01.704-05:00').
        Naive isoformat() strings sort incorrectly against offset-aware strings when
        fractional seconds or tz suffixes differ. To handle this:
          - since: use bare YYYY-MM-DDTHH:MM:SS (no subseconds) — safe as lower bound
          - until: add 1 second so that '2024-01-15T10:00:01' >= any .NNN-05:00 at :00
        """
        since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
        # Extend upper bound by 1 second to include DB timestamps with millisecond
        # or tz-offset suffixes that sort after the bare timestamp string
        until_extended = until + timedelta(seconds=1)
        until_str = until_extended.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """
                SELECT direction, entry_price, target1, target2, stop1, win_rate
                FROM discord_bot_signals
                WHERE symbol = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (discord_symbol, since_str, until_str),
            )
            row = cur.fetchone()
            conn.close()
            if row is None:
                return None
            return dict(row)
        except Exception:
            return None

    def _get_rolling_win_rate(self, discord_symbol: str, timestamp: datetime) -> float:
        """
        Get rolling 30-day win rate for symbol using cached stats.
        TTL: 5 minutes.
        Falls back to 0.5 (neutral) if no data.

        The win_rate column in the DB is stored as a percentage (e.g. 76.8),
        so the average is divided by 100 to return a value in [0.0, 1.0].
        """
        # Use date-level key for cache (win rate doesn't change minute-by-minute)
        cache_key = (discord_symbol, timestamp.date().isoformat())
        cached = self._stats_cache.get(cache_key)
        if cached is not None:
            stats, fetch_time = cached
            if time.time() - fetch_time < self.STATS_TTL_SECONDS:
                return stats.get("win_rate", 0.5)

        # Query DB for average win_rate over last 30 days
        # Use strftime('%Y-%m-%dT%H:%M:%S') to avoid tz-offset string comparison issues
        since = timestamp - timedelta(days=self.WIN_RATE_LOOKBACK_DAYS)
        since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
        until_extended = timestamp + timedelta(seconds=1)
        until_str = until_extended.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT AVG(win_rate) AS avg_win_rate, COUNT(*) AS count
                FROM discord_bot_signals
                WHERE symbol = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                  AND win_rate IS NOT NULL
                """,
                (discord_symbol, since_str, until_str),
            )
            row = cur.fetchone()
            conn.close()

            if row and row[0] is not None and row[1] > 0:
                # win_rate stored as percentage — normalize to 0.0-1.0
                win_rate = float(row[0]) / 100.0
                win_rate = max(0.0, min(1.0, win_rate))
            else:
                win_rate = 0.5  # neutral fallback — no data for this symbol/window
        except Exception:
            win_rate = 0.5

        self._stats_cache[cache_key] = ({"win_rate": win_rate}, time.time())
        return win_rate

    def clear_cache(self):
        """Clear the stats cache."""
        self._stats_cache.clear()
