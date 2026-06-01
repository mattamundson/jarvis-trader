"""
CFTC Commitment of Traders (CoT) data fetcher.

Fetches weekly futures positioning data from CFTC public API.
CoT data: released every Friday, covers prior Tuesday positions.

Symbol mapping:
  MES/ES  → "S&P 500 Stock Index - Chicago Mercantile Exchange"  (contract code 13874A)
  MNQ/NQ  → "NASDAQ-100 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE" (contract code 209742)
  MCL/CL  → "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE" (contract code 067651)

Usage:
    fetcher = CoTFetcher()
    result = fetcher.get_positioning("MES")
    # Returns: {symbol, report_date, commercial_net, large_spec_net, small_spec_net,
    #           commercial_trend, last_updated}
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# CFTC public API endpoint (CFTC Disaggregated Futures Only report)
CFTC_API = "https://publicreporting.cftc.gov/api/odata/v1/TriWeeklyReport_F_ALL"

# Contract codes for our instruments
CONTRACT_CODES = {
    "MES": "13874A",   # E-mini S&P 500
    "ES":  "13874A",
    "MNQ": "20974P",   # E-mini Nasdaq-100
    "NQ":  "20974P",
    "MCL": "067651",   # Crude Oil Light Sweet
    "CL":  "067651",
    "MGC": "088691",   # Gold
    "GC":  "088691",
}

# Market names for fallback text search
MARKET_NAMES = {
    "MES": "E-MINI S&P 500",
    "ES":  "E-MINI S&P 500",
    "MNQ": "NASDAQ-100",
    "NQ":  "NASDAQ-100",
    "MCL": "CRUDE OIL",
    "CL":  "CRUDE OIL",
}

DB_PATH = Path(__file__).parent.parent / "data" / "cot_cache.db"


class CoTFetcher:
    """CFTC Commitment of Traders data fetcher with SQLite caching."""

    def __init__(self):
        self._init_db()

    def _init_db(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cot_data (
                    symbol TEXT NOT NULL,
                    report_date TEXT NOT NULL,
                    commercial_long INTEGER,
                    commercial_short INTEGER,
                    commercial_net INTEGER,
                    large_spec_long INTEGER,
                    large_spec_short INTEGER,
                    large_spec_net INTEGER,
                    commercial_trend TEXT,
                    fetched_at TEXT,
                    PRIMARY KEY (symbol, report_date)
                )
            """)

    def get_positioning(self, symbol: str, max_age_days: int = 7) -> Optional[Dict[str, Any]]:
        """
        Get latest CoT positioning for a futures symbol.

        Returns cached data if < max_age_days old, otherwise fetches fresh.
        """
        symbol = symbol.upper()

        # Check cache first
        cached = self._get_cached(symbol, max_age_days)
        if cached:
            return cached

        # Fetch from CFTC API
        return self._fetch_and_cache(symbol)

    def _get_cached(self, symbol: str, max_age_days: int) -> Optional[Dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("""
                SELECT symbol, report_date, commercial_long, commercial_short,
                       commercial_net, large_spec_long, large_spec_short,
                       large_spec_net, commercial_trend, fetched_at
                FROM cot_data
                WHERE symbol = ? AND fetched_at > ?
                ORDER BY report_date DESC LIMIT 1
            """, (symbol, cutoff)).fetchone()

        if not row:
            return None

        return self._row_to_dict(row)

    def _fetch_and_cache(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch latest CoT data from CFTC public API."""
        market_name = MARKET_NAMES.get(symbol, "")
        if not market_name:
            logger.warning("No CFTC market name mapping for symbol: %s", symbol)
            return None

        try:
            # CFTC OData API — filter by market name, get last 2 reports
            params = {
                "$filter": f"contains(Market_and_Exchange_Names, '{market_name}')",
                "$orderby": "Report_Date_as_MM_DD_YYYY desc",
                "$top": "2",
                "$select": (
                    "Market_and_Exchange_Names,Report_Date_as_MM_DD_YYYY,"
                    "Comm_Positions_Long_All,Comm_Positions_Short_All,"
                    "NonComm_Positions_Long_All,NonComm_Positions_Short_All,"
                    "NonRept_Positions_Long_All,NonRept_Positions_Short_All"
                )
            }

            resp = requests.get(CFTC_API, params=params, timeout=15)
            resp.raise_for_status()

            data = resp.json()
            records = data.get("value", [])

            if not records:
                logger.warning("No CoT data found for %s (market: %s)", symbol, market_name)
                return None

            latest = records[0]

            comm_long = int(latest.get("Comm_Positions_Long_All", 0))
            comm_short = int(latest.get("Comm_Positions_Short_All", 0))
            comm_net = comm_long - comm_short

            lspec_long = int(latest.get("NonComm_Positions_Long_All", 0))
            lspec_short = int(latest.get("NonComm_Positions_Short_All", 0))
            lspec_net = lspec_long - lspec_short

            # Determine commercial trend (week-over-week if 2 records available)
            commercial_trend = "NEUTRAL"
            if len(records) >= 2:
                prev = records[1]
                prev_comm_net = int(prev.get("Comm_Positions_Long_All", 0)) - int(prev.get("Comm_Positions_Short_All", 0))
                if comm_net > prev_comm_net + 1000:
                    commercial_trend = "BULLISH"   # Commercials adding longs
                elif comm_net < prev_comm_net - 1000:
                    commercial_trend = "BEARISH"   # Commercials adding shorts

            report_date = latest.get("Report_Date_as_MM_DD_YYYY", "")

            # Cache result
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO cot_data
                    (symbol, report_date, commercial_long, commercial_short, commercial_net,
                     large_spec_long, large_spec_short, large_spec_net, commercial_trend, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol, report_date, comm_long, comm_short, comm_net,
                    lspec_long, lspec_short, lspec_net, commercial_trend,
                    datetime.now(timezone.utc).isoformat()
                ))

            return {
                "symbol": symbol,
                "report_date": report_date,
                "commercial_net": comm_net,
                "commercial_long": comm_long,
                "commercial_short": comm_short,
                "large_spec_net": lspec_net,
                "commercial_trend": commercial_trend,
                "source": "cftc",
            }

        except requests.RequestException as e:
            logger.warning("CFTC API request failed for %s: %s", symbol, e)
            return None
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            logger.warning("CFTC data parse error for %s: %s", symbol, e)
            return None

    def _row_to_dict(self, row) -> Dict[str, Any]:
        return {
            "symbol": row[0],
            "report_date": row[1],
            "commercial_long": row[2],
            "commercial_short": row[3],
            "commercial_net": row[4],
            "large_spec_long": row[5],
            "large_spec_short": row[6],
            "large_spec_net": row[7],
            "commercial_trend": row[8],
            "fetched_at": row[9],
            "source": "cftc_cache",
        }

    def get_bias_adjustment(self, symbol: str) -> float:
        """
        Returns a small signal bias adjustment based on commercial positioning.

        Returns:
            float: -0.1 (bearish) to +0.1 (bullish)
            0.0 if data unavailable
        """
        data = self.get_positioning(symbol)
        if not data:
            return 0.0

        trend = data.get("commercial_trend", "NEUTRAL")
        if trend == "BULLISH":
            return 0.1
        elif trend == "BEARISH":
            return -0.1
        return 0.0
