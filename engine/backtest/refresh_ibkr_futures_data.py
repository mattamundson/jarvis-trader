#!/usr/bin/env python
"""
IBKR Futures Data Refresh — extend cached CSVs to current date.

Background:
    Polygon futures BLOCKLISTED since 2026-04-16 (free plan doesn't include
    futures data). All cached CSVs in engine/backtest/cache/*_1h.csv end
    2026-03-27/28. WFO runners (MES rank11, MGC rank4) need fresh data
    before their gate v2 verdicts expire ~2026-06-05/06.

This script:
    1. Connects to IB Gateway (paper port 4002) via IBKRDataConnector.
    2. For each symbol (MES, MGC, MNQ, M2K, MCL), reads the most recent
       cached CSV to find the last bar timestamp.
    3. Fetches new 1h bars from last_bar to now via IBKR.
    4. Writes the extended CSV under the canonical name pattern:
       cache/{SYMBOL}_{old_start}_{new_end}_1h.csv
    5. Optionally archives the older CSV to cache/archive/ to keep cache/
       directory tidy.

Usage:
    cd engine
    .venv/Scripts/python -m backtest.refresh_ibkr_futures_data
    .venv/Scripts/python -m backtest.refresh_ibkr_futures_data --dry-run
    .venv/Scripts/python -m backtest.refresh_ibkr_futures_data --symbols MES MGC

Prerequisites:
    - IB Gateway running on port 4002 (paper account)
    - Logged in (Gateway prompts at startup)
    - Market data subscriptions active (CME real-time + EOD for futures)

Exit codes:
    0 — all symbols refreshed successfully
    1 — at least one symbol failed
    2 — IB Gateway unreachable (run gateway first)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

# Make engine/ importable when run as a module (-m backtest.refresh_...)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest._gate_v2_helpers import _find_latest_cache  # noqa: E402
from data.market_data import IBKRDataConnector  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# Default symbols + exchanges. Each entry maps the cache symbol (used in
# CSV filenames) to the IBKR contract symbol (used by IBKRDataConnector).
# All 5 are micro futures except where noted; all use 1h bars.
DEFAULT_SYMBOLS = ["MES", "MGC", "MNQ", "M2K", "MCL"]

CACHE_DIR = Path(__file__).resolve().parent / "cache"
ARCHIVE_DIR = CACHE_DIR / "archive"


def find_latest_csv(symbol: str, interval: str = "1h") -> Optional[Path]:
    """Thin wrapper around the canonical _find_latest_cache selector."""
    try:
        return _find_latest_cache(CACHE_DIR, symbol, f"_{interval}.csv")
    except FileNotFoundError:
        if symbol == "MES":
            try:
                return _find_latest_cache(CACHE_DIR, "ES_F", f"_{interval}.csv")
            except FileNotFoundError:
                pass
        return None


def parse_csv_date_range(path: Path) -> tuple[datetime, datetime]:
    """Read first and last timestamp from a cached CSV. Returns tz-naive UTC.

    Cache CSVs have inconsistent timestamp formats per symbol:
      MES + MGC store '+00:00' offsets (tz-aware after pd.to_datetime)
      MNQ + MCL store naive datetimes
    Downstream `now - last_dt` uses a naive UTC datetime, so any tz-aware
    parse causes 'can't subtract offset-naive and offset-aware' ValueError.
    Normalize to tz-naive UTC here once so callers don't have to.
    """
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    first = pd.to_datetime(df[ts_col].iloc[0])
    last = pd.to_datetime(df[ts_col].iloc[-1])
    if first.tzinfo is not None:
        first = first.tz_convert("UTC").tz_localize(None)
    if last.tzinfo is not None:
        last = last.tz_convert("UTC").tz_localize(None)
    return first.to_pydatetime(), last.to_pydatetime()


def parse_filename_dates(path: Path) -> tuple[Optional[str], Optional[str]]:
    """Extract start_date, end_date from a filename like SYMBOL_2024-06-01_2026-03-27_1h.csv."""
    stem = path.stem  # e.g. "MES_2024-06-01_2026-03-27_1h"
    parts = stem.split("_")
    # Find date-shaped tokens (YYYY-MM-DD)
    dates = [p for p in parts if len(p) == 10 and p.count("-") == 2]
    if len(dates) >= 2:
        return dates[0], dates[1]
    return None, None


async def refresh_symbol(
    connector: IBKRDataConnector,
    symbol: str,
    *,
    interval: str = "1h",
    dry_run: bool = False,
    chunk_days: int = 0,
    chunk_pause_sec: float = 2.0,
) -> dict:
    """Refresh a single symbol's cached CSV.

    Returns a result dict with keys: symbol, status, message, bars_added.
    """
    result: dict = {
        "symbol": symbol,
        "status": "unknown",
        "message": "",
        "bars_added": 0,
        "old_path": None,
        "new_path": None,
    }

    csv_path = find_latest_csv(symbol, interval)
    if csv_path is None:
        result["status"] = "missing_cache"
        result["message"] = f"No existing {symbol} {interval} CSV found in {CACHE_DIR}"
        return result
    result["old_path"] = str(csv_path)

    try:
        first_dt, last_dt = parse_csv_date_range(csv_path)
    except Exception as e:
        result["status"] = "parse_error"
        result["message"] = f"Cannot parse {csv_path.name}: {e}"
        return result

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    gap_hours = (now - last_dt).total_seconds() / 3600
    if gap_hours < 24:
        result["status"] = "fresh"
        result["message"] = f"Last bar {last_dt.isoformat()} is < 24h old; skipping"
        return result

    duration_days = max(1, int(gap_hours / 24) + 1)
    duration = f"{duration_days} D"
    logger.info(
        "[%s] last bar %s, gap %.1f hours, fetching duration=%s",
        symbol,
        last_dt.isoformat(),
        gap_hours,
        duration,
    )

    if dry_run:
        result["status"] = "dry_run"
        result["message"] = (
            f"Would fetch {duration} from IBKR ({last_dt.isoformat()} -> now), "
            f"then merge into {csv_path.name}"
        )
        return result

    try:
        if chunk_days <= 0 or duration_days <= chunk_days:
            new_bars = await connector.get_historical_bars(
                symbol,
                duration=duration,
                bar_size="1 hour",
                is_futures=True,
            )
        else:
            # Chunked path: split duration into chunk_days slices.
            # Used to avoid Gateway crashes on large historical requests.
            # Each chunk uses an explicit endDateTime walking backwards from now.
            chunks: list[pd.DataFrame] = []
            remaining = duration_days
            end_dt = datetime.now(timezone.utc).replace(tzinfo=None)
            chunk_idx = 0
            while remaining > 0:
                this_days = min(chunk_days, remaining)
                chunk_idx += 1
                logger.info(
                    "[%s] chunk %d: %d D ending %s",
                    symbol,
                    chunk_idx,
                    this_days,
                    end_dt.isoformat(),
                )
                # Use connector's underlying _ib + reqHistoricalDataAsync with explicit endDateTime
                contract = await connector._qualified_contract(symbol, True)  # type: ignore[attr-defined]
                if contract is None:
                    raise RuntimeError(f"contract qualification failed for {symbol}")
                # IBKR endDateTime format: yyyymmdd-HH:MM:SS (UTC)
                end_str = end_dt.strftime("%Y%m%d-%H:%M:%S")
                bars = await connector._ib.reqHistoricalDataAsync(  # type: ignore[attr-defined]
                    contract,
                    endDateTime=end_str,
                    durationStr=f"{this_days} D",
                    barSizeSetting="1 hour",
                    whatToShow="TRADES",
                    useRTH=False,
                )
                if bars:
                    chunk_df = pd.DataFrame(
                        [
                            {
                                "timestamp": b.date,
                                "open": b.open,
                                "high": b.high,
                                "low": b.low,
                                "close": b.close,
                                "volume": b.volume,
                            }
                            for b in bars
                        ]
                    )
                    chunks.append(chunk_df)
                    logger.info("[%s] chunk %d: +%d bars", symbol, chunk_idx, len(chunk_df))
                else:
                    logger.warning("[%s] chunk %d: 0 bars returned", symbol, chunk_idx)

                remaining -= this_days
                end_dt -= timedelta(days=this_days)
                if remaining > 0 and chunk_pause_sec > 0:
                    await asyncio.sleep(chunk_pause_sec)
            if chunks:
                new_bars = pd.concat(chunks, ignore_index=True)
            else:
                new_bars = pd.DataFrame()
    except Exception as e:
        result["status"] = "fetch_error"
        result["message"] = f"IBKR fetch failed: {e}"
        return result

    if new_bars.empty:
        result["status"] = "no_new_data"
        result["message"] = "IBKR returned 0 bars (market closed? wrong contract?)"
        return result

    # Merge old + new, dedupe by timestamp, sort
    old_df = pd.read_csv(csv_path)
    old_df.columns = [c.lower() for c in old_df.columns]
    if "datetime" in old_df.columns:
        old_df = old_df.rename(columns={"datetime": "timestamp"})

    new_bars = new_bars.copy()

    # IBKR bars come back tz-aware (UTC); cached CSVs are tz-naive. Strip tz
    # from both before concat to avoid "Cannot compare tz-naive and tz-aware".
    def _strip_tz(series: pd.Series) -> pd.Series:
        ts = pd.to_datetime(series, utc=True, errors="coerce")
        return ts.dt.tz_convert("UTC").dt.tz_localize(None)

    new_bars["timestamp"] = _strip_tz(new_bars["timestamp"])
    old_df["timestamp"] = _strip_tz(old_df["timestamp"])

    combined = (
        pd.concat([old_df, new_bars], ignore_index=True)
        .drop_duplicates(subset=["timestamp"], keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    bars_added = len(combined) - len(old_df)
    result["bars_added"] = bars_added

    if bars_added <= 0:
        result["status"] = "no_new_data"
        result["message"] = "All fetched bars were already in cache"
        return result

    new_first = combined["timestamp"].iloc[0].strftime("%Y-%m-%d")
    new_last = combined["timestamp"].iloc[-1].strftime("%Y-%m-%d")
    new_filename = f"{symbol}_{new_first}_{new_last}_{interval}.csv"
    new_path = CACHE_DIR / new_filename
    combined.to_csv(new_path, index=False)
    result["new_path"] = str(new_path)

    # Archive the old CSV unless it was already the canonical one we're rewriting.
    if csv_path != new_path:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = ARCHIVE_DIR / csv_path.name
        try:
            csv_path.rename(archive_path)
            logger.info("[%s] archived %s -> archive/", symbol, csv_path.name)
        except Exception as e:
            logger.warning("[%s] could not archive %s: %s", symbol, csv_path.name, e)

    result["status"] = "ok"
    result["message"] = f"+{bars_added} bars; {csv_path.name} -> {new_filename}"
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh IBKR futures CSV cache")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would happen, don't fetch"
    )
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to refresh")
    parser.add_argument(
        "--port", type=int, default=4002, help="IB Gateway port (4002 paper, 4001 live)"
    )
    parser.add_argument("--client-id", type=int, default=42, help="IBKR client ID (any unique int)")
    parser.add_argument("--interval", default="1h", help="Bar interval (1h or 1d)")
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=0,
        help="Split fetch into N-day chunks to avoid Gateway crashes on large requests (0 = single fetch)",
    )
    parser.add_argument(
        "--chunk-pause-sec",
        type=float,
        default=2.0,
        help="Seconds to pause between chunks (avoids pacing violations)",
    )
    args = parser.parse_args()

    if args.port == 4001:
        logger.error("Live port 4001 is permanently blocked per CLAUDE.md. Use paper port 4002.")
        return 2

    logger.info("Connecting to IBKR at 127.0.0.1:%d (client_id=%d)...", args.port, args.client_id)
    connector = IBKRDataConnector(port=args.port, client_id=args.client_id, connect_timeout=10.0)
    if not args.dry_run:
        connected = await connector.connect()
        if not connected:
            logger.error(
                "IB Gateway unreachable at 127.0.0.1:%d. Steps to fix:\n"
                "  1. Open IB Gateway from Start menu\n"
                "  2. Choose Paper Trading credentials\n"
                "  3. Wait for the connection indicator to turn green\n"
                "  4. Re-run this script",
                args.port,
            )
            return 2
    else:
        logger.info("[DRY RUN] Skipping IBKR connect")

    results = []
    for symbol in args.symbols:
        try:
            r = await refresh_symbol(
                connector,
                symbol,
                interval=args.interval,
                dry_run=args.dry_run,
                chunk_days=args.chunk_days,
                chunk_pause_sec=args.chunk_pause_sec,
            )
        except Exception as e:
            r = {"symbol": symbol, "status": "exception", "message": str(e), "bars_added": 0}
        results.append(r)
        logger.info("[%s] %s - %s", r["symbol"], r["status"].upper(), r["message"])

    if not args.dry_run:
        await connector.disconnect()

    # Summary
    print()
    print("=" * 80)
    print("IBKR FUTURES DATA REFRESH SUMMARY")
    print("=" * 80)
    print(f"{'Symbol':<8} {'Status':<14} {'Bars added':>12}  Message")
    print("-" * 80)
    for r in results:
        msg = r["message"][:50] + "..." if len(r["message"]) > 50 else r["message"]
        print(f"{r['symbol']:<8} {r['status']:<14} {r['bars_added']:>12}  {msg}")
    print("=" * 80)

    n_ok = sum(1 for r in results if r["status"] in ("ok", "fresh", "dry_run"))
    n_fail = len(results) - n_ok
    print(f"\n{n_ok}/{len(results)} OK  |  {n_fail} failed")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
