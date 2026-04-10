# engine/discord/ib_levels.py
#
# IBLevelProvider — queries discord_ib_reports for IB extension levels
# used in Layer 2 structure map in engine/backtest/signals.py
#
# Cache by (discord_symbol, date) — IB levels don't change intraday
# Returns None gracefully when no data for the date/symbol

import os
import sqlite3
from datetime import date, datetime
from typing import Optional


class IBLevelProvider:
    """
    Provides IB extension levels from discord_ib_reports.

    Maps JARVIS micro-contract symbols to Discord symbols.
    Caches by (symbol, date) since IB levels don't change intraday.

    The discord_ib_reports table stores timestamps as ISO 8601 strings
    (e.g. '2023-07-25T17:04:00.496-05:00'). Date filtering uses
    SQLite's DATE() function to extract the date portion.

    Returns None gracefully when no data available (not all dates have reports).
    """

    # Map JARVIS micro-contract symbols → Discord full-contract symbols
    SYMBOL_MAP = {
        "MES": "ES",
        "MNQ": "NQ",
        "MGC": "GC",
        "MCL": "CL",
        "MYM": "YM",
        "M2K": "RTY",
    }

    def __init__(self, db_path: str = None):
        if db_path is None:
            # DB lives at engine/data/jarvis_trader.db (not workspace root).
            # Previous 3-levels-up walked past engine/ to the workspace root,
            # causing a split-brain DB on 2026-04-10.
            engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(engine_root, "data", "jarvis_trader.db")
        self.db_path = db_path
        self._cache: dict = {}  # key: (discord_symbol, date_str) → dict | None

    def _map_symbol(self, symbol: str) -> str:
        """Map JARVIS symbol to Discord symbol. Pass-through if already a Discord symbol."""
        return self.SYMBOL_MAP.get(symbol.upper(), symbol.upper())

    def get_levels(self, symbol: str, trading_date) -> Optional[dict]:
        """
        Get IB extension levels for symbol on given date.

        Args:
            symbol: JARVIS or Discord symbol (MES, ES, MNQ, NQ, etc.)
            trading_date: date object, datetime object, or 'YYYY-MM-DD' string

        Returns:
            dict with keys: ib_high, ib_low, ib_range, ibu50, ibu100,
                            ibd50, ibd100, auction_context
            or None if no data is available for that date/symbol.
        """
        discord_symbol = self._map_symbol(symbol)

        # Normalize trading_date to a YYYY-MM-DD string
        if isinstance(trading_date, datetime):
            date_str = trading_date.date().isoformat()
        elif isinstance(trading_date, date):
            date_str = trading_date.isoformat()
        else:
            date_str = str(trading_date)[:10]  # Accept 'YYYY-MM-DD ...' or datetime str

        cache_key = (discord_symbol, date_str)
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = self._query(discord_symbol, date_str)
        self._cache[cache_key] = result
        return result

    def _query(self, discord_symbol: str, date_str: str) -> Optional[dict]:
        """
        Query DB for the most recent IB report for the given symbol on the given date.

        Uses DATE(timestamp) to handle ISO 8601 timestamps with timezone offsets.
        Filters to rows where ib_high is not NULL to skip incomplete reports.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """
                SELECT ib_high, ib_low, ib_range, ibu50, ibu100, ibd50, ibd100, auction_context
                FROM discord_ib_reports
                WHERE symbol = ?
                  AND DATE(timestamp) = ?
                  AND ib_high IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (discord_symbol, date_str),
            )
            row = cur.fetchone()
            conn.close()

            if row is None:
                return None

            return {
                "ib_high": row["ib_high"],
                "ib_low": row["ib_low"],
                "ib_range": row["ib_range"],
                "ibu50": row["ibu50"],
                "ibu100": row["ibu100"],
                "ibd50": row["ibd50"],
                "ibd100": row["ibd100"],
                "auction_context": row["auction_context"],
            }
        except Exception:
            return None

    def clear_cache(self):
        """Clear the in-memory cache (useful for testing or cross-day reuse)."""
        self._cache.clear()
