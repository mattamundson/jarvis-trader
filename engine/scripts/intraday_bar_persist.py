"""
JARVIS TRADER — Hourly intraday bar persistence script.
=========================================================
Fetches 1h OHLCV bars for MES + MGC (or any --symbols list) via the standard
MarketDataManager waterfall (TV → IBKR → CSV cache) and persists them into
market_data_bars through the existing save_bars hook.

Run once per cycle from a scheduled task — cron handles recurrence.
The script itself enforces a trading-hours gate so cron can be a simple
"every 60 min on weekdays" rule without day-of-week complexity in Task Scheduler.

Usage
-----
    # Normal mode: runs only during trading hours (Mon-Fri 09:25-16:05 ET)
    python -m engine.scripts.intraday_bar_persist

    # Override symbols
    python -m engine.scripts.intraday_bar_persist --symbols MES MGC MNQ

    # Bypass trading-hours gate (for manual runs or smoke tests)
    python -m engine.scripts.intraday_bar_persist --force

    # Dry-run: report what would be fetched without writing
    python -m engine.scripts.intraday_bar_persist --no-fetch

    # Combine
    python -m engine.scripts.intraday_bar_persist --force --no-fetch

Exit codes
----------
    0 — success (or skipped outside hours)
    1 — one or more fetches failed unexpectedly
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Path bootstrap — make bare engine-module imports work regardless of cwd
# ---------------------------------------------------------------------------

_ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# Module-level import so tests can patch scripts.intraday_bar_persist.MarketDataManager
# without needing to reach into data.market_data.  The try/except keeps startup
# safe when the engine package isn't fully installed.
try:
    from data.market_data import MarketDataManager
except Exception:  # pragma: no cover — only absent in bare-Python environments
    MarketDataManager = None  # type: ignore[assignment,misc]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [intraday_bar_persist] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("intraday_bar_persist")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS = ["MES", "MGC"]
BAR_LIMIT = 300          # 300 bars × 1h = ~12.5 trading days; covers SMA-200 + buffer
INTERVAL = "1h"
LOOKBACK_DAYS = 14       # 14 calendar days → enough 1h bars for SMA-200 on signal path

# Trading hours gate (Eastern Time): Mon-Fri, 09:25 → 16:05
# 09:25 gives cron triggered at 09:30 a ~5-min grace window on early bars.
# 16:05 captures the 16:00 bar before it's rolled off the exchange feed.
_ET = ZoneInfo("America/New_York")
_GATE_OPEN_H = 9
_GATE_OPEN_M = 25
_GATE_CLOSE_H = 16
_GATE_CLOSE_M = 5


# ---------------------------------------------------------------------------
# Trading hours check
# ---------------------------------------------------------------------------


def is_trading_hours(now: datetime | None = None) -> bool:
    """Return True when now falls inside Mon-Fri 09:25-16:05 Eastern.

    Parameters
    ----------
    now:
        Override the current time (used in tests). Must be tz-aware or will
        be treated as UTC and converted to ET.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Normalise to Eastern
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_et = now.astimezone(_ET)

    # Weekday gate: 0=Mon … 4=Fri
    if now_et.weekday() > 4:
        return False

    open_minutes = _GATE_OPEN_H * 60 + _GATE_OPEN_M
    close_minutes = _GATE_CLOSE_H * 60 + _GATE_CLOSE_M
    current_minutes = now_et.hour * 60 + now_et.minute

    return open_minutes <= current_minutes <= close_minutes


# ---------------------------------------------------------------------------
# Config shim — minimal stand-in so MarketDataManager can be constructed
# outside a full engine boot.  Reads actual values from the environment /
# .env when present.
# ---------------------------------------------------------------------------


def _load_config():
    """Return a config-like object sourced from the engine .env or environment."""
    import os

    # Load .env if dotenv is available (best-effort)
    env_path = _ENGINE_DIR / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path, override=False)
        except ImportError:
            pass  # dotenv not installed — fall back to raw os.environ

    class _Config:
        IBKR_HOST = os.environ.get("IBKR_HOST", "127.0.0.1")
        IBKR_PORT = int(os.environ.get("IBKR_PORT", "4002"))
        IBKR_CLIENT_ID = int(os.environ.get("IBKR_CLIENT_ID", "10"))  # non-conflicting client ID
        IBKR_CONNECT_TIMEOUT_SECONDS = float(os.environ.get("IBKR_CONNECT_TIMEOUT_SECONDS", "5.0"))
        POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
        FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
        FRED_API_KEY = os.environ.get("FRED_API_KEY", None)

    return _Config()


# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------


async def fetch_symbol(
    mgr,
    symbol: str,
    no_fetch: bool = False,
) -> dict:
    """Fetch 1h bars for one symbol and persist via MarketDataManager.get_bars().

    The persistence side-effect happens inside get_bars() itself (commit e31298e):
    both the TV-MCP tier and the IBKR tier call _save_bars after a successful fetch.

    Returns a result dict:
        symbol, rows_returned, source, persisted (bool), error
    """
    result: dict = {
        "symbol": symbol,
        "rows_returned": 0,
        "source": "none",
        "persisted": False,
        "error": None,
    }

    if no_fetch:
        logger.info("[DRY-RUN] Would fetch 1h bars for %s (limit=%d)", symbol, BAR_LIMIT)
        result["persisted"] = False
        result["source"] = "dry_run"
        return result

    try:
        df = await mgr.get_bars(
            symbol=symbol,
            lookback_days=LOOKBACK_DAYS,
            timeframe=INTERVAL,
            is_futures=True,
        )
        result["rows_returned"] = len(df)
        result["source"] = df.attrs.get("source", "unknown") if not df.empty else "empty"
        result["persisted"] = not df.empty

        if df.empty:
            logger.warning(
                "No 1h bars returned for %s — source reported as '%s'. "
                "IBKR Gateway may be offline; expected outside trading hours.",
                symbol,
                result["source"],
            )
        else:
            logger.info(
                "Fetched %d 1h bars for %s (source=%s) — persisted via save_bars hook",
                len(df),
                symbol,
                result["source"],
            )
    except Exception as exc:
        # Never crash — log warning and exit 0 (IBKR offline is expected outside hours)
        logger.warning(
            "get_bars raised for %s: %s — Gateway likely unreachable", symbol, exc
        )
        result["error"] = str(exc)

    return result


async def _run(symbols: list[str], force: bool, no_fetch: bool) -> int:
    """Async entrypoint — returns 0 on success, 1 on unexpected error."""
    now_utc = datetime.now(timezone.utc)

    if not force and not is_trading_hours(now_utc):
        now_et = now_utc.astimezone(_ET)
        logger.info(
            "Outside trading hours (%s ET weekday=%d) — skipping. Use --force to override.",
            now_et.strftime("%H:%M"),
            now_et.weekday(),
        )
        return 0

    config = _load_config()

    if MarketDataManager is None:
        logger.error("MarketDataManager could not be imported — engine package unavailable")
        return 1

    mgr = MarketDataManager(config)

    # Initialize data sources — IBKR may time out here (5s) if Gateway is down
    try:
        await mgr.initialize()
    except Exception as exc:
        logger.warning("MarketDataManager.initialize() raised: %s — continuing with offline sources", exc)

    any_error = False
    for symbol in symbols:
        result = await fetch_symbol(mgr, symbol, no_fetch=no_fetch)
        if result["error"] is not None:
            # A raised exception is unexpected — log but don't die
            logger.error("Unexpected error for %s: %s", symbol, result["error"])
            any_error = True

    # Best-effort disconnect (ignore errors — Gateway may already be gone)
    if mgr.ibkr:
        try:
            await mgr.ibkr.disconnect()
        except Exception:
            pass

    return 1 if any_error else 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hourly 1h bar persistence for market_data_bars"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_SYMBOLS,
        metavar="SYM",
        help=f"Symbols to fetch (default: {' '.join(DEFAULT_SYMBOLS)})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass trading-hours gate and fetch regardless of time/day",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        dest="no_fetch",
        help="Dry-run: report what would be fetched without hitting any data source",
    )
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols]
    exit_code = asyncio.run(_run(symbols, force=args.force, no_fetch=args.no_fetch))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
