"""
CFTC Commitment of Traders (CoT) data fetcher — v2 (corrected endpoint).

Uses the Socrata-based CFTC public API (resource 6dca-aqww), which replaced
the old OData TriWeeklyReport_F_ALL endpoint that returned 404 as of 2026.

Symbol mapping (CFTC contract market codes):
  MES/ES  → 13874A   (E-mini S&P 500 — CME)
  MNQ/NQ  → 209742   (Nasdaq Mini — CME)
  MCL/CL  → 067651   (WTI Crude — NYMEX)
  MGC/GC  → 088691   (Gold — COMEX)

CoT signal logic:
  Large Spec net > 0  → speculative longs outweigh shorts → bullish momentum
  Commercial net > 0  → hedger accumulation → often contrarian (but confirms trend)
  The strategy uses Large Spec net as the primary signal (trend-following)
  with a 4-week rate-of-change as momentum confirmation.

Usage:
    from data.cot_fetcher_v2 import CoTFetcherV2
    fetcher = CoTFetcherV2()
    result = fetcher.get_positioning("MES")
    # Returns: {symbol, report_date, large_spec_net, commercial_net,
    #           large_spec_trend, commercial_trend, cot_signal, last_updated}
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Correct CFTC Socrata endpoint (tested 2026-04-22)
CFTC_API = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# Contract market codes — single source of truth
CONTRACT_CODES: dict[str, str] = {
    "MES": "13874A",
    "ES":  "13874A",
    "MNQ": "209742",
    "NQ":  "209742",
    "MCL": "067651",
    "CL":  "067651",
    "MGC": "088691",
    "GC":  "088691",
}

DB_PATH = Path(__file__).parent.parent / "data" / "cot_cache_v2.db"


class CoTFetcherV2:
    """
    CFTC CoT data fetcher with SQLite caching.

    Fetches from the correct Socrata endpoint and caches results locally
    to avoid hammering the CFTC API (data only updates weekly on Fridays).
    """

    def __init__(self, cache_ttl_hours: int = 12):
        self._cache_ttl = timedelta(hours=cache_ttl_hours)
        self._init_db()

    def _init_db(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cot_data (
                    symbol          TEXT NOT NULL,
                    report_date     TEXT NOT NULL,
                    large_spec_long INTEGER,
                    large_spec_short INTEGER,
                    large_spec_net  INTEGER,
                    commercial_long INTEGER,
                    commercial_short INTEGER,
                    commercial_net  INTEGER,
                    open_interest   INTEGER,
                    large_spec_trend TEXT,
                    commercial_trend TEXT,
                    cot_signal      TEXT,
                    fetched_at      TEXT,
                    PRIMARY KEY (symbol, report_date)
                )
            """)
            conn.commit()

    def _fetch_from_api(self, symbol: str) -> Optional[dict]:
        """Fetch latest CoT record from CFTC Socrata API."""
        code = CONTRACT_CODES.get(symbol.upper())
        if not code:
            logger.warning("Unknown symbol %s — no contract code", symbol)
            return None

        try:
            resp = requests.get(
                CFTC_API,
                params={
                    "$where": f"cftc_contract_market_code='{code}'",
                    "$limit": 5,  # get last 5 weeks for trend calc
                    "$order": "report_date_as_yyyy_mm_dd DESC",
                },
                timeout=15,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                logger.warning("No CoT data returned for %s (code=%s)", symbol, code)
                return None
            return data  # list of records, newest first
        except Exception as exc:
            logger.warning("CFTC API error for %s: %s", symbol, exc)
            return None

    def _parse_record(self, symbol: str, records: list[dict]) -> dict:
        """Parse API response into standardised positioning dict."""
        latest = records[0]
        nc_long  = int(latest.get("noncomm_positions_long_all", 0) or 0)
        nc_short = int(latest.get("noncomm_positions_short_all", 0) or 0)
        cm_long  = int(latest.get("comm_positions_long_all", 0) or 0)
        cm_short = int(latest.get("comm_positions_short_all", 0) or 0)
        oi       = int(latest.get("open_interest_all", 0) or 0)

        nc_net = nc_long - nc_short
        cm_net = cm_long - cm_short

        # 4-week rate of change on large spec net
        nc_net_prev = None
        if len(records) >= 4:
            r4 = records[3]
            nc_net_prev = (
                int(r4.get("noncomm_positions_long_all", 0) or 0)
                - int(r4.get("noncomm_positions_short_all", 0) or 0)
            )

        # Trend classification
        if nc_net_prev is not None and oi > 0:
            chg_pct = (nc_net - nc_net_prev) / max(oi, 1) * 100
            if chg_pct > 2:
                large_spec_trend = "INCREASING_LONGS"
            elif chg_pct < -2:
                large_spec_trend = "INCREASING_SHORTS"
            else:
                large_spec_trend = "NEUTRAL"
        else:
            # Absolute net position
            if nc_net > 50_000:
                large_spec_trend = "NET_LONG"
            elif nc_net < -50_000:
                large_spec_trend = "NET_SHORT"
            else:
                large_spec_trend = "NEUTRAL"

        # Commercial trend (contrarian signal — commercials hedge against direction)
        if cm_net < -100_000:
            commercial_trend = "BEARISH_HEDGE"  # commercials heavily short → underlying bullish
        elif cm_net > 100_000:
            commercial_trend = "BULLISH_HEDGE"  # commercials heavily long → underlying bearish
        else:
            commercial_trend = "NEUTRAL"

        # Composite CoT signal
        # Large spec trend-following + commercial confirmation
        if large_spec_trend == "INCREASING_LONGS":
            cot_signal = "BULLISH"
        elif large_spec_trend == "INCREASING_SHORTS":
            cot_signal = "BEARISH"
        elif large_spec_trend == "NET_LONG" and commercial_trend == "BEARISH_HEDGE":
            cot_signal = "BULLISH"   # spec long + commercial hedge = healthy bull
        elif large_spec_trend == "NET_SHORT":
            cot_signal = "BEARISH"
        else:
            cot_signal = "NEUTRAL"

        report_date = latest.get("report_date_as_yyyy_mm_dd", "")[:10]

        return {
            "symbol": symbol,
            "report_date": report_date,
            "market_name": latest.get("market_and_exchange_names", ""),
            "large_spec_long": nc_long,
            "large_spec_short": nc_short,
            "large_spec_net": nc_net,
            "commercial_long": cm_long,
            "commercial_short": cm_short,
            "commercial_net": cm_net,
            "open_interest": oi,
            "large_spec_trend": large_spec_trend,
            "commercial_trend": commercial_trend,
            "cot_signal": cot_signal,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def _cache_get(self, symbol: str) -> Optional[dict]:
        """Return cached record if still fresh, else None."""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM cot_data WHERE symbol=? ORDER BY report_date DESC LIMIT 1",
                    (symbol.upper(),)
                ).fetchone()
                if row is None:
                    return None
                fetched_at = datetime.fromisoformat(row["fetched_at"]).replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - fetched_at
                if age > self._cache_ttl:
                    return None
                return dict(row)
        except Exception:
            return None

    def _cache_set(self, result: dict) -> None:
        """Write result to SQLite cache."""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO cot_data
                    (symbol, report_date, large_spec_long, large_spec_short, large_spec_net,
                     commercial_long, commercial_short, commercial_net, open_interest,
                     large_spec_trend, commercial_trend, cot_signal, fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    result["symbol"].upper(),
                    result["report_date"],
                    result["large_spec_long"],
                    result["large_spec_short"],
                    result["large_spec_net"],
                    result["commercial_long"],
                    result["commercial_short"],
                    result["commercial_net"],
                    result["open_interest"],
                    result["large_spec_trend"],
                    result["commercial_trend"],
                    result["cot_signal"],
                    result["last_updated"],
                ))
                conn.commit()
        except Exception as exc:
            logger.warning("CoT cache write failed: %s", exc)

    def get_positioning(self, symbol: str) -> Optional[dict]:
        """
        Get latest CoT positioning for a symbol.

        Returns cached result if fresh (< 12 hours old), otherwise fetches live.
        Returns None on failure (caller should fall back to neutral signal).
        """
        # Check cache first
        cached = self._cache_get(symbol)
        if cached:
            logger.debug("CoT cache hit for %s (report_date=%s)", symbol, cached.get("report_date"))
            return cached

        # Live fetch
        records = self._fetch_from_api(symbol)
        if not records:
            return None

        result = self._parse_record(symbol, records)
        self._cache_set(result)
        logger.info(
            "CoT %s: date=%s spec_net=%+d trend=%s signal=%s",
            symbol, result["report_date"], result["large_spec_net"],
            result["large_spec_trend"], result["cot_signal"]
        )
        return result

    def get_cot_multiplier(self, symbol: str) -> float:
        """
        Return a position sizing multiplier based on CoT signal.

        BULLISH  → 1.0  (no reduction)
        NEUTRAL  → 0.9  (slight reduction)
        BEARISH  → 0.7  (meaningful reduction — CoT is bearish headwind)
        None     → 1.0  (no data → don't penalise)
        """
        result = self.get_positioning(symbol)
        if result is None:
            return 1.0
        signal = result.get("cot_signal", "NEUTRAL")
        return {"BULLISH": 1.0, "NEUTRAL": 0.9, "BEARISH": 0.7}.get(signal, 1.0)


# ── Convenience alias so existing imports still work ─────────────────────────
CoTFetcher = CoTFetcherV2
