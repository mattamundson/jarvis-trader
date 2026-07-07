#!/usr/bin/env python
"""
IBKR Historical Bar Export — Cache Refresh Helper

Fetches historical OHLCV bars from IB Gateway paper account and extends
existing cache files in engine/backtest/cache/. Designed to be the one-command
prep step before re-running WFO verdicts that are about to expire.

Required: IB Gateway paper account running on 127.0.0.1:4002 with API enabled.
LIVE PORT 4001 IS PERMANENTLY BLOCKED — do not point this at it.

Usage (from engine/ directory):
    .venv/Scripts/python -m backtest.export_ibkr_history --symbol MES --interval 1h
    .venv/Scripts/python -m backtest.export_ibkr_history --symbol MES --interval 1h --duration "60 D"
    .venv/Scripts/python -m backtest.export_ibkr_history --refresh-all-pass-verdicts
    .venv/Scripts/python -m backtest.export_ibkr_history --dry-run --symbol MES --interval 1h

What it does:
    1. Connects to IB Gateway paper (127.0.0.1:4002)
    2. Identifies the active continuous-front-month contract for SYMBOL
    3. Fetches historical bars covering [last_cached_date - safety_buffer, now]
    4. Merges with existing cache, deduplicating on timestamp
    5. Writes back to engine/backtest/cache/SYMBOL_<start>_<end>_<interval>.csv
    6. Reports new bar count, range covered, gaps detected

Modes:
    --symbol SYM            One symbol at a time (MES, MGC, MNQ, MCL, M2K)
    --interval INT          1h or 1d
    --duration "60 D"       IB-style duration string; default extends from cache end
    --dry-run               Connect + identify contract but don't fetch bars
    --refresh-all-pass-verdicts
                            Iterate over every PASS verdict in gate_v2_verdicts/
                            and refresh that symbol's cache for the verdict's interval.
                            This is the canonical "verdict refresh prep" command.

Why the helper exists:
    Polygon futures data has been blocklisted since 2026-04-16. IBKR is the only
    valid source for fresh micro-futures bars. Building this once means future
    refreshes are a one-command operation timed against verdict expiry deadlines.

    MES rank11 expires ~2026-06-05; MGC rank4 expires ~2026-06-06. Plan ahead.

Implementation notes:
    - Uses ib_async (already a engine dependency).
    - Front-month detection: queries reqContractDetails for continuous month.
    - 1h bars: IB returns up to ~1 year per request; longer periods chunk.
    - 1d bars: fits 5-10 years per request; single call sufficient.
    - Cache filename convention: SYMBOL_YYYY-MM-DD_YYYY-MM-DD_INTERVAL.csv
      where the second date matches the latest bar inclusive.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Cache filename contract — single source of truth.
#
# Format: <SYMBOL>_<START_DATE>_<END_DATE>_<INTERVAL>.csv
#   - SYMBOL:   2-4 uppercase letters (e.g. MES, MGC, MNQ, MCL, M2K)
#   - START / END: ISO YYYY-MM-DD
#   - INTERVAL: digits + 'm', 'h', or 'd' (e.g. 5m, 15m, 1h, 4h, 1d)
#
# The downstream selector engine/backtest/_gate_v2_helpers.py::_find_latest_cache
# splits on "_" and uses parts[2] (the END_DATE) as the lex-sort key. If this
# pattern ever drifts (e.g. a contract-month suffix, or a non-ISO date), the
# selector silently picks the wrong file. The assertion in _save_merged below
# is the canary that catches drift at write-time, not weeks later at WFO time.
#
# 'm' added 2026-06-16 for intraday 5m/15m history: INTERVAL_TO_IB_BARSIZE has
# declared "5m"/"15m" but this regex only accepted [hd], so any 5m/15m save
# raised here -- the bars were fetchable but never persistable. Now persistable.
CACHE_FILENAME_CONTRACT = re.compile(
    r"^[A-Z][A-Z0-9]{1,3}_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_\d{1,2}[mhd]\.csv$"
)

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

CACHE_DIR = engine_root / "backtest" / "cache"
VERDICTS_DIR = engine_root / "data" / "gate_v2_verdicts"

IB_HOST = "127.0.0.1"
IB_PAPER_PORT = 4002
IB_LIVE_PORT = 4001  # PERMANENTLY BLOCKED — do not connect here
IB_CLIENT_ID_DATA = 71  # avoid conflicting with engine's executor client_id

# IB-side bar size strings
INTERVAL_TO_IB_BARSIZE = {
    "1h": "1 hour",
    "1d": "1 day",
    "5m": "5 mins",
    "15m": "15 mins",
}

# Per-interval IB request economics for deep-history pulls.
#   chunk_days  -- conservative max calendar days reqHistoricalData returns in a
#                  single request for this bar size. IB enforces tighter limits
#                  for smaller bars; these are deliberately safe (monthly for
#                  intraday) so a deep pull never silently truncates a chunk.
#   depth_days  -- default total history target when no --duration is given and
#                  there is no existing cache (the "fetch a long range" case).
# The actual per-request cap IB allows is larger for some bar sizes, but the
# binding constraint on new edge is *coverage*, not request count -- erring
# toward smaller, reliable chunks costs a few extra requests, never data.
INTERVAL_CHUNK_DAYS = {
    "5m": 30,     # ~1 month per request
    "15m": 30,    # ~1 month per request
    "1h": 365,    # ~1 year per request
    "1d": 3650,   # daily fits a single 10y request
}
INTERVAL_DEPTH_DAYS = {
    "5m": 1825,   # 5 years intraday
    "15m": 1825,  # 5 years intraday
    "1h": 1825,   # 5 years (was a single 2Y request; now chunked + deeper)
    "1d": 3650,   # 10 years daily (was capped at 5y)
}

# IB requires `whatToShow` for futures — TRADES is correct for OHLCV
WHAT_TO_SHOW = "TRADES"

# Per-symbol IB Future spec. Continuous-front-month routing handled at fetch time.
SYMBOL_TO_IB_SPEC = {
    "MES": {"symbol": "MES", "exchange": "CME", "currency": "USD"},
    "MNQ": {"symbol": "MNQ", "exchange": "CME", "currency": "USD"},
    "MGC": {"symbol": "MGC", "exchange": "COMEX", "currency": "USD"},
    "MCL": {"symbol": "MCL", "exchange": "NYMEX", "currency": "USD"},
    "M2K": {"symbol": "M2K", "exchange": "CME", "currency": "USD"},
    # B1 trend diversifiers (gold-uncorrelated). Rates on CBOT, FX micros on CME.
    # Required so export_ibkr_history can resolve a continuous-front-month contract
    # for these symbols; without them a pull fails on contract identification.
    "ZN": {"symbol": "ZN", "exchange": "CBOT", "currency": "USD"},
    "ZB": {"symbol": "ZB", "exchange": "CBOT", "currency": "USD"},
    "M6E": {"symbol": "M6E", "exchange": "CME", "currency": "USD"},
    "M6B": {"symbol": "M6B", "exchange": "CME", "currency": "USD"},
}


def _import_ib_async():
    """Import ib_async lazily so --help works without it installed."""
    try:
        from ib_async import IB, ContFuture, Future

        return IB, Future, ContFuture
    except ImportError as e:
        print(
            f"ERROR: ib_async not available ({e}).\n"
            f"Install: {sys.executable} -m pip install ib-async",
            file=sys.stderr,
        )
        sys.exit(2)


def _find_existing_cache(symbol: str, interval: str) -> Path | None:
    """Return the widest-span existing cache for symbol/interval, or None."""
    primary = CACHE_DIR / f"{symbol}_2024-01-01_2026-03-28_{interval}.csv"
    if primary.exists():
        return primary
    candidates = sorted(CACHE_DIR.glob(f"{symbol}_*_{interval}.csv"))
    if not candidates:
        return None
    # Pick the widest span by file size (rough proxy for date range)
    return max(candidates, key=lambda p: p.stat().st_size)


def _load_existing_bars(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
    return df.set_index(ts_col).sort_index()


def _last_bar_dt(df: pd.DataFrame) -> datetime | None:
    if df is None or df.empty:
        return None
    last = df.index.max()
    if last.tzinfo is None:
        last = last.tz_localize("UTC")
    return last.to_pydatetime()


def _ib_duration_from_gap(last_bar: datetime | None, interval: str) -> str:
    """Compute IB-style duration string covering the gap from last_bar to now."""
    now = datetime.now(tz=timezone.utc)
    if last_bar is None:
        # No existing cache — fetch a long range
        return "2 Y" if interval == "1h" else "5 Y"

    gap_days = max(1, (now - last_bar).days + 2)  # +2 day safety buffer
    if interval == "1h":
        # IB caps 1h to ~1 year per request — clamp to safe value
        return f"{min(gap_days, 365)} D"
    return f"{min(gap_days, 1825)} D"  # daily up to 5y


def _ib_enddate(dt: datetime) -> str:
    """Format a datetime as an IB endDateTime string in UTC.

    IB accepts 'yyyymmdd HH:mm:ss UTC'. An empty string means 'now', which is
    what the most-recent chunk uses.
    """
    return dt.astimezone(timezone.utc).strftime("%Y%m%d %H:%M:%S UTC")


def plan_history_chunks(
    interval: str,
    *,
    now: datetime,
    depth_days: int | None = None,
    last_bar: datetime | None = None,
) -> list[tuple[str, str]]:
    """Plan the (endDateTime, durationStr) IB requests, newest-first, that cover
    the desired history depth for ``interval`` in IB-safe chunks.

    - With ``last_bar`` set, only the gap last_bar -> now is fetched (incremental
      refresh), capped at ``depth_days``.
    - With ``last_bar`` None, the full ``depth_days`` (default per interval) is
      split into ceil(depth_days / chunk_days) chunks, walking endDateTime back.

    Pure: no IB, no IO, deterministic in ``now``. The newest chunk uses
    endDateTime="" (IB interprets "" as now). This is the real chunking the
    module's docstring always promised but never actually performed -- the old
    path issued a single capped request, silently truncating deep pulls.
    """
    if interval not in INTERVAL_CHUNK_DAYS:
        raise ValueError(
            f"Unknown interval {interval!r}; supported: {list(INTERVAL_CHUNK_DAYS)}"
        )

    target = depth_days if depth_days is not None else INTERVAL_DEPTH_DAYS[interval]
    if last_bar is not None:
        gap_days = max(1, (now - last_bar).days + 2)  # +2 day safety buffer
        target = min(target, gap_days)
    target = max(1, target)

    chunk_days = INTERVAL_CHUNK_DAYS[interval]
    n_chunks = max(1, math.ceil(target / chunk_days))

    plan: list[tuple[str, str]] = []
    for i in range(n_chunks):
        days_to_end = i * chunk_days  # this chunk ENDS at now - days_to_end
        remaining = target - days_to_end
        this_chunk = min(chunk_days, remaining)
        if this_chunk <= 0:
            break
        end_dt = "" if i == 0 else _ib_enddate(now - timedelta(days=days_to_end))
        plan.append((end_dt, f"{this_chunk} D"))
    return plan


def _save_merged(symbol: str, interval: str, merged: pd.DataFrame) -> Path:
    """Write merged DF to canonical filename convention.

    Filenames must match :data:`CACHE_FILENAME_CONTRACT`
    (``<SYMBOL>_<START_DATE>_<END_DATE>_<INTERVAL>.csv`` with ISO dates) so
    that ``_gate_v2_helpers._find_latest_cache`` can pick the freshest cache
    by lex-sorting on the end-date segment. A contract violation here would
    silently break verdict refresh, so we assert at write-time.
    """
    start_date = merged.index.min().date().isoformat()
    end_date = merged.index.max().date().isoformat()
    filename = f"{symbol}_{start_date}_{end_date}_{interval}.csv"
    if not CACHE_FILENAME_CONTRACT.match(filename):
        raise ValueError(
            f"Cache filename '{filename}' violates the contract "
            f"(expected '<SYMBOL>_<YYYY-MM-DD>_<YYYY-MM-DD>_<INTERVAL>.csv'). "
            f"Downstream _find_latest_cache parses parts[2] as the end-date "
            f"sort key — drift here breaks verdict refresh silently."
        )
    out = CACHE_DIR / filename
    out_df = merged.reset_index()
    # Canonical column name = "timestamp"
    if "datetime" in out_df.columns and "timestamp" not in out_df.columns:
        out_df = out_df.rename(columns={"datetime": "timestamp"})
    out_df.to_csv(out, index=False)
    return out


async def _fetch_bars_async(
    symbol: str,
    interval: str,
    duration: str,
    end_dt: str = "",
) -> pd.DataFrame:
    """Connect to IB Gateway paper and fetch historical bars."""
    IB, Future, ContFuture = _import_ib_async()

    if symbol not in SYMBOL_TO_IB_SPEC:
        raise ValueError(f"Unknown symbol {symbol}; supported: {list(SYMBOL_TO_IB_SPEC)}")
    if interval not in INTERVAL_TO_IB_BARSIZE:
        raise ValueError(f"Unknown interval {interval}; supported: {list(INTERVAL_TO_IB_BARSIZE)}")

    spec = SYMBOL_TO_IB_SPEC[symbol]
    bar_size = INTERVAL_TO_IB_BARSIZE[interval]

    ib = IB()
    print(f"[IBKR] Connecting to {IB_HOST}:{IB_PAPER_PORT} (clientId={IB_CLIENT_ID_DATA})...")
    await ib.connectAsync(IB_HOST, IB_PAPER_PORT, clientId=IB_CLIENT_ID_DATA, timeout=15)

    try:
        # Use ContFuture to get the continuous front-month contract directly.
        # Plain Future() without lastTradeDateOrContractMonth was returning
        # "Ambiguous contract" warnings and qualified=[None] from IBKR because
        # it matches every active expiry. ContFuture resolves to the front
        # month and lets us swap to its concrete localSymbol for historical
        # data requests.
        cont = ContFuture(
            symbol=spec["symbol"],
            exchange=spec["exchange"],
            currency=spec["currency"],
        )
        qualified = await ib.qualifyContractsAsync(cont)
        if not qualified or qualified[0] is None:
            raise RuntimeError(f"Could not qualify continuous contract for {symbol}")
        cont_active = qualified[0]

        # ContFuture provides the conId of the active front month. Build a
        # concrete Future contract from it for reqHistoricalDataAsync (which
        # works with ContFuture too, but specific contracts are more reliable
        # for historical data when you want bar-perfect coverage).
        active = Future(
            symbol=cont_active.symbol,
            lastTradeDateOrContractMonth=cont_active.lastTradeDateOrContractMonth,
            exchange=cont_active.exchange,
            currency=cont_active.currency,
            localSymbol=cont_active.localSymbol,
            multiplier=cont_active.multiplier,
        )
        active_qualified = await ib.qualifyContractsAsync(active)
        if not active_qualified or active_qualified[0] is None:
            raise RuntimeError(
                f"Could not qualify front-month {cont_active.localSymbol} for {symbol}"
            )
        active = active_qualified[0]
        print(
            f"[IBKR] Active contract: {active.localSymbol} ({active.lastTradeDateOrContractMonth})"
        )

        print(f"[IBKR] Requesting {bar_size} bars, duration={duration}, whatToShow={WHAT_TO_SHOW}")
        bars = await ib.reqHistoricalDataAsync(
            active,
            endDateTime=end_dt,
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=WHAT_TO_SHOW,
            useRTH=False,  # include extended hours for 1h bars
            formatDate=1,  # yyyyMMdd HH:mm:ss
        )

        if not bars:
            print(
                "[IBKR] WARNING: zero bars returned. Check IB Gateway has historical data permission."
            )
            return pd.DataFrame()

        # Convert to DataFrame
        rows = [
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
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()
        print(f"[IBKR] Fetched {len(df)} bars: {df.index.min()} -> {df.index.max()}")
        return df
    finally:
        ib.disconnect()
        print("[IBKR] Disconnected.")


def _refresh_one(
    symbol: str,
    interval: str,
    duration: str | None,
    dry_run: bool,
    depth_days: int | None = None,
) -> dict:
    """Refresh cache for one symbol/interval. Returns summary dict.

    Two fetch modes:
      * ``--duration`` given  -> a single IB request of that duration (back-compat).
      * otherwise             -> a chunked deep pull via :func:`plan_history_chunks`
        (covers the interval's default depth, or just the gap from the existing
        cache), walking endDateTime back in IB-safe chunks and merging+deduping.
    """
    summary = {
        "symbol": symbol,
        "interval": interval,
        "ok": False,
        "n_existing": 0,
        "n_fetched": 0,
        "n_merged": 0,
        "n_chunks": 0,
        "out_file": None,
        "error": None,
    }

    existing_path = _find_existing_cache(symbol, interval)
    existing_df = pd.DataFrame()
    last_bar = None
    if existing_path:
        try:
            existing_df = _load_existing_bars(existing_path)
            summary["n_existing"] = len(existing_df)
            last_bar = _last_bar_dt(existing_df)
            print(
                f"[{symbol}-{interval}] Existing cache: {existing_path.name} "
                f"({len(existing_df)} bars, last={last_bar})"
            )
        except Exception as e:
            print(f"[{symbol}-{interval}] WARN: cannot load existing cache: {e}")

    now = datetime.now(tz=timezone.utc)
    if duration:
        plan = [("", duration)]  # explicit single-request override
    else:
        plan = plan_history_chunks(
            interval, now=now, depth_days=depth_days, last_bar=last_bar
        )
    summary["n_chunks"] = len(plan)
    print(
        f"[{symbol}-{interval}] Plan: {len(plan)} request(s) -- "
        f"{[d for _, d in plan][:3]}{' ...' if len(plan) > 3 else ''}"
    )

    if dry_run:
        print(f"[{symbol}-{interval}] DRY RUN — skipping fetch.")
        summary["ok"] = True
        return summary

    try:
        chunk_frames = []
        for idx, (end_dt, dur) in enumerate(plan, 1):
            print(f"[{symbol}-{interval}] chunk {idx}/{len(plan)}: end='{end_dt or 'now'}' dur={dur}")
            cdf = asyncio.run(_fetch_bars_async(symbol, interval, dur, end_dt))
            if not cdf.empty:
                chunk_frames.append(cdf)
        new_df = (
            pd.concat(chunk_frames).sort_index() if chunk_frames else pd.DataFrame()
        )
        if not new_df.empty:
            new_df = new_df[~new_df.index.duplicated(keep="last")]
        summary["n_fetched"] = len(new_df)
    except Exception as e:
        summary["error"] = str(e)
        print(f"[{symbol}-{interval}] ERROR during fetch: {e}")
        return summary

    if new_df.empty:
        print(f"[{symbol}-{interval}] No new bars fetched; skipping merge.")
        return summary

    # Merge with deduplication on timestamp
    if not existing_df.empty:
        merged = pd.concat([existing_df, new_df]).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
    else:
        merged = new_df.sort_index()
    summary["n_merged"] = len(merged)

    out_path = _save_merged(symbol, interval, merged)
    summary["out_file"] = str(out_path.relative_to(engine_root.parent))
    summary["ok"] = True
    print(f"[{symbol}-{interval}] OK: wrote {len(merged)} bars to {out_path.name}")
    return summary


def _list_pass_verdict_targets() -> list[tuple[str, str]]:
    """Scan gate_v2_verdicts/ and return [(symbol, interval), ...] for PASS verdicts."""
    targets = []
    if not VERDICTS_DIR.exists():
        return targets
    seen = set()
    for path in sorted(VERDICTS_DIR.glob("*.json")):
        try:
            v = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if v.get("verdict") != "PASS":
            continue
        sym = v.get("symbol")
        if not sym:
            continue
        # Default interval inference: WFO runners all use 1h for current PASS strategies
        interval = "1h"
        key = (sym, interval)
        if key not in seen:
            targets.append(key)
            seen.add(key)
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--symbol", help="Symbol to refresh (MES/MGC/MNQ/MCL/M2K)")
    parser.add_argument(
        "--interval",
        default="1h",
        choices=list(INTERVAL_TO_IB_BARSIZE),
        help="Bar size (default: 1h)",
    )
    parser.add_argument(
        "--duration", help='IB-style duration (e.g. "60 D", "2 Y"). Single request; '
        "overrides chunked deep-pull. Default: auto-chunked from cache gap / depth.",
    )
    parser.add_argument(
        "--depth-days",
        type=int,
        default=None,
        help="Total history depth to pull when no --duration is given "
        "(default per interval: 5m/15m/1h=1825, 1d=3650). Chunked automatically.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Connect + identify contract but skip fetch"
    )
    parser.add_argument(
        "--refresh-all-pass-verdicts",
        action="store_true",
        help="Refresh cache for every symbol with a PASS verdict",
    )
    args = parser.parse_args()

    if args.refresh_all_pass_verdicts:
        targets = _list_pass_verdict_targets()
        if not targets:
            print("No PASS verdicts found.")
            return 0
        print(f"Refreshing {len(targets)} PASS-verdict targets: {targets}")
        results = []
        for sym, interval in targets:
            print(f"\n{'=' * 60}\n{sym} {interval}\n{'=' * 60}")
            results.append(
                _refresh_one(sym, interval, args.duration, args.dry_run, args.depth_days)
            )
        print("\nFINAL SUMMARY:")
        for r in results:
            status = "OK" if r["ok"] else f"FAIL ({r.get('error', 'unknown')})"
            print(
                f"  {r['symbol']} {r['interval']}: {status} "
                f"(existing={r['n_existing']}, fetched={r['n_fetched']}, merged={r['n_merged']})"
            )
        return 0 if all(r["ok"] for r in results) else 1

    if not args.symbol:
        parser.error("--symbol required (or use --refresh-all-pass-verdicts)")
    summary = _refresh_one(
        args.symbol, args.interval, args.duration, args.dry_run, args.depth_days
    )
    print(f"\nSUMMARY: {summary}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
