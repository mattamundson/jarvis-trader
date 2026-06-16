#!/usr/bin/env python
"""
JARVIS TRADER — Paced IBKR Intraday Historical Fetcher (5m / 15m)
==================================================================

Builds roll-continuous intraday OHLCV history for the futures stack directly
from IB Gateway, replicating the EXISTING `*_cont.csv` generation method used in
`engine/backtest/export_ibkr_history.py`. Polygon is futures-BLIND (free plan
returns the wrong asset — `CL` = Colgate-Palmolive stock) so IBKR is the ONLY
valid source for micro-futures bars.

WHY THIS SCRIPT EXISTS
----------------------
The single-shot helpers (`export_ibkr_history.py`, `refresh_ibkr_futures_data.py`)
were built to top-up 1h caches near verdict-expiry. They don't do paced, chunked,
multi-symbol/multi-interval 5m+15m bulk backfill with a dedicated non-colliding
clientId. This script does, and is meant to be launched as a long-running
background job (full run ≈ 75-90 min — see PACING below).

ROLL-CONTINUITY METHOD (replicated, not invented)
-------------------------------------------------
The existing `MES_*_5m_cont.csv` / `MGC_*_5m_cont.csv` ground-truth files were
generated via IBKR's **ContFuture** front-month contract:

    1. `ContFuture(symbol, exchange, currency)` → qualify → get the active
       front-month's conId / localSymbol.
    2. Build a concrete `Future` from that conId and call
       `reqHistoricalDataAsync(..., whatToShow="TRADES", useRTH=False)`.

IBKR stitches the continuous series internally at the contract level. Empirical
verification on the existing `MES_2024-09-22_2026-05-29_5m_cont.csv` (119,096
bars): only 7 single-bar moves > 2% over ~20 months, and NONE of them fall on a
quarterly roll boundary (Mar/Jun/Sep/Dec 3rd-Friday) — they are the April-2025
tariff crash and one 2026-03 macro move, i.e. REAL price action. The series is
gap-free at rolls WITHOUT any manual back-adjustment.

Therefore: NO Panama/ratio back-adjustment is applied here. Doing so would
DIVERGE from ground truth — the existing `_cont` files were byte-identical to
their non-`_cont` twins (close diff = 0.0 across all 49,666 overlapping rows).
The `_cont` suffix denotes "continuous-front-month sourced", not "back-adjusted".
This is the documented roll rule for this repo. To switch to back-adjusted
continuous later, that is a SEPARATE, explicitly-flagged change.

CLIENT ID (hard requirement — PR#34 collision avoidance)
--------------------------------------------------------
The live engine executor connects with `IBKR_CLIENT_ID` (=1) and the data leg
with exec+1 (=2). Reusing either id makes IB Gateway reject the connection (it
refuses a duplicate clientId held by a live connection) — that was the PR#34
data-leg bug. This fetcher uses a DISTINCT id, `IBKR_BACKFILL_CLIENT_ID`
(default **77**), comfortably clear of 1/2/42/71 used elsewhere in the repo.

PACING (IBKR historical-data limits)
------------------------------------
IBKR enforces ~60 historical requests / 10 min (plus same-contract/size
sub-limits). We stay well under: a per-request sleep (default 12s ⇒ ≤50 req /
10 min) and conservative chunk sizes:
    - 5m : 14 calendar days / request (~4k bars; IB caps a 5m request well below
           a full year, and small chunks dodge the "duration too long for 5 min
           bars" pacing rejections).
    - 15m: 30 calendar days / request.
Bars are fetched walking BACKWARDS from `endDate` with explicit `endDateTime`,
then concatenated, de-duplicated on timestamp, and sorted ascending.

RTH
---
All requests use `useRTH=False` (full 24h session) so the continuous series is
stitch-complete; downstream studies filter to RTH themselves.

USAGE
-----
    cd engine
    # Dry-run a tiny sample (1 week MES 5m) to a SCRATCH csv — proves connection,
    # clientId, and bar shape WITHOUT touching the live DB or canonical caches:
    .venv/Scripts/python -m scripts.fetch_ib_intraday --dry-run

    # Full job (the parent's ~75-90 min background launch):
    .venv/Scripts/python -m scripts.fetch_ib_intraday --full

    # Targeted:
    .venv/Scripts/python -m scripts.fetch_ib_intraday --symbols MES MGC --intervals 5m --years 2

Exit codes:
    0 — success (or dry-run)
    1 — at least one (symbol, interval) failed
    2 — IB Gateway unreachable
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Make engine/ importable when run as `python -m scripts.fetch_ib_intraday`
# AND when run as a bare path.
_ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("fetch_ib_intraday")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

CACHE_DIR = _ENGINE_DIR / "backtest" / "cache"

IB_HOST = "127.0.0.1"
IB_PAPER_PORT = 4002
IB_LIVE_PORT = 4001  # PERMANENTLY BLOCKED — never connect here.

# DISTINCT backfill clientId (PR#34 collision avoidance). Executor=1, data-leg=2.
DEFAULT_BACKFILL_CLIENT_ID = 77


def _backfill_client_id() -> int:
    raw = os.environ.get("IBKR_BACKFILL_CLIENT_ID", str(DEFAULT_BACKFILL_CLIENT_ID))
    try:
        cid = int(raw)
    except (TypeError, ValueError):
        cid = DEFAULT_BACKFILL_CLIENT_ID
    # Guard against accidentally colliding with the live engine legs.
    if cid in (1, 2):
        logger.warning(
            "IBKR_BACKFILL_CLIENT_ID=%s collides with the live executor(1)/data-leg(2); "
            "forcing %d to avoid PR#34-style rejection.",
            cid,
            DEFAULT_BACKFILL_CLIENT_ID,
        )
        cid = DEFAULT_BACKFILL_CLIENT_ID
    return cid


# Per-symbol IB Future spec (matches export_ibkr_history.SYMBOL_TO_IB_SPEC).
SYMBOL_TO_IB_SPEC: dict[str, dict[str, str]] = {
    "ES": {"symbol": "ES", "exchange": "CME", "currency": "USD"},
    "MES": {"symbol": "MES", "exchange": "CME", "currency": "USD"},
    "MNQ": {"symbol": "MNQ", "exchange": "CME", "currency": "USD"},
    "MGC": {"symbol": "MGC", "exchange": "COMEX", "currency": "USD"},
    "MCL": {"symbol": "MCL", "exchange": "NYMEX", "currency": "USD"},
}

INTERVAL_TO_IB_BARSIZE = {
    "5m": "5 mins",
    "15m": "15 mins",
}

# Chunk size (calendar days) per interval. Conservative to dodge IB's
# "duration too long for <bar>" pacing rejections on small bars.
INTERVAL_CHUNK_DAYS = {
    "5m": 14,
    "15m": 30,
}

WHAT_TO_SHOW = "TRADES"
DEFAULT_INTER_REQUEST_SLEEP = 12.0  # seconds ⇒ ≤50 req / 10 min (limit is 60)

# ── Full-job target matrix (per task spec) ──
# ES, MNQ, MCL at 5m AND 15m, plus 2yr uniform MES & MGC at 5m AND 15m.
FULL_SYMBOLS = ["ES", "MNQ", "MCL", "MES", "MGC"]
FULL_INTERVALS = ["5m", "15m"]
FULL_YEARS = 2


# ─────────────────────────────────────────────────────────────────────────────
# IB plumbing
# ─────────────────────────────────────────────────────────────────────────────


def _import_ib_async():
    try:
        from ib_async import IB, ContFuture, Future

        return IB, Future, ContFuture
    except ImportError as e:  # pragma: no cover
        logger.error("ib_async not available (%s). Install: pip install ib-async", e)
        sys.exit(2)


async def _qualify_front_month(ib, symbol: str):
    """Resolve the continuous front-month concrete Future (the `_cont` method)."""
    _IB, Future, ContFuture = _import_ib_async()
    spec = SYMBOL_TO_IB_SPEC[symbol]

    cont = ContFuture(symbol=spec["symbol"], exchange=spec["exchange"], currency=spec["currency"])
    qualified = await ib.qualifyContractsAsync(cont)
    if not qualified or qualified[0] is None:
        raise RuntimeError(f"Could not qualify continuous contract for {symbol}")
    ca = qualified[0]

    active = Future(
        symbol=ca.symbol,
        lastTradeDateOrContractMonth=ca.lastTradeDateOrContractMonth,
        exchange=ca.exchange,
        currency=ca.currency,
        localSymbol=ca.localSymbol,
        multiplier=ca.multiplier,
    )
    aq = await ib.qualifyContractsAsync(active)
    if not aq or aq[0] is None:
        raise RuntimeError(f"Could not qualify front-month {ca.localSymbol} for {symbol}")
    logger.info(
        "[%s] active front-month: %s (%s)",
        symbol,
        aq[0].localSymbol,
        aq[0].lastTradeDateOrContractMonth,
    )
    return aq[0]


def _bars_to_df(bars) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(
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
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


async def _fetch_chunked(
    ib,
    contract,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    inter_request_sleep: float,
) -> pd.DataFrame:
    """Walk backwards from `end` to `start` in INTERVAL_CHUNK_DAYS slices.

    Each request uses an explicit endDateTime (UTC, IB format yyyymmdd-HH:MM:SS)
    and durationStr = "<chunk_days> D". Paced by `inter_request_sleep` between
    requests to honour the ~60 req / 10 min historical limit.
    """
    bar_size = INTERVAL_TO_IB_BARSIZE[interval]
    chunk_days = INTERVAL_CHUNK_DAYS[interval]

    frames: list[pd.DataFrame] = []
    cur_end = end
    req_count = 0
    while cur_end > start:
        end_str = cur_end.strftime("%Y%m%d-%H:%M:%S")
        req_count += 1
        logger.info(
            "[%s %s] req %d: %d D ending %s",
            symbol,
            interval,
            req_count,
            chunk_days,
            end_str,
        )
        try:
            bars = await ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end_str,
                durationStr=f"{chunk_days} D",
                barSizeSetting=bar_size,
                whatToShow=WHAT_TO_SHOW,
                useRTH=False,  # full 24h session for stitch-completeness
                formatDate=1,
            )
        except Exception as e:
            logger.warning("[%s %s] req %d failed: %s", symbol, interval, req_count, e)
            bars = None

        chunk = _bars_to_df(bars)
        if not chunk.empty:
            frames.append(chunk)
            earliest = chunk["timestamp"].min()
            logger.info(
                "[%s %s] req %d: +%d bars (earliest %s)",
                symbol,
                interval,
                req_count,
                len(chunk),
                earliest,
            )
            # Advance the window to just before the earliest bar we received.
            new_end = earliest.to_pydatetime() - timedelta(minutes=1)
            # Safety: if IB returned a tiny window, still step back a full chunk
            # so we don't spin forever on a sparse range.
            cur_end = min(new_end, cur_end - timedelta(days=chunk_days))
        else:
            logger.warning(
                "[%s %s] req %d: 0 bars — stepping back one chunk", symbol, interval, req_count
            )
            cur_end = cur_end - timedelta(days=chunk_days)

        if cur_end > start:
            await asyncio.sleep(inter_request_sleep)

    if not frames:
        return pd.DataFrame()

    out = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["timestamp"], keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    # Clip to the requested [start, end] window.
    start_utc = pd.Timestamp(start).tz_convert("UTC") if start.tzinfo else pd.Timestamp(
        start, tz="UTC"
    )
    out = out[out["timestamp"] >= start_utc].reset_index(drop=True)
    return out


def _write_cont_csv(symbol: str, interval: str, df: pd.DataFrame, scratch: bool) -> Path:
    """Write to the canonical `_cont` naming convention.

    Live: SYMBOL_<start>_<end>_<interval>_cont.csv  (matches existing ground truth)
    Scratch (dry-run): _dryrun_SYMBOL_<start>_<end>_<interval>_cont.csv
    """
    start_d = df["timestamp"].min().date().isoformat()
    end_d = df["timestamp"].max().date().isoformat()
    base = f"{symbol}_{start_d}_{end_d}_{interval}_cont.csv"
    name = f"_dryrun_{base}" if scratch else base
    out = CACHE_DIR / name
    df.to_csv(out, index=False)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────


async def fetch_one(
    ib,
    symbol: str,
    interval: str,
    years: float,
    inter_request_sleep: float,
    scratch: bool,
    sample_days: int | None = None,
) -> dict:
    result = {"symbol": symbol, "interval": interval, "status": "unknown", "bars": 0, "path": None}

    if symbol not in SYMBOL_TO_IB_SPEC:
        result["status"] = "bad_symbol"
        return result
    if interval not in INTERVAL_TO_IB_BARSIZE:
        result["status"] = "bad_interval"
        return result

    end = datetime.now(timezone.utc)
    if sample_days is not None:
        start = end - timedelta(days=sample_days)
    else:
        start = end - timedelta(days=int(years * 365))

    try:
        contract = await _qualify_front_month(ib, symbol)
    except Exception as e:
        result["status"] = "qualify_error"
        result["error"] = str(e)
        logger.error("[%s %s] qualify failed: %s", symbol, interval, e)
        return result

    df = await _fetch_chunked(ib, contract, symbol, interval, start, end, inter_request_sleep)
    if df.empty:
        result["status"] = "no_data"
        return result

    out = _write_cont_csv(symbol, interval, df, scratch)
    result["status"] = "ok"
    result["bars"] = len(df)
    result["path"] = str(out)
    logger.info(
        "[%s %s] %d bars %s -> %s | %s",
        symbol,
        interval,
        len(df),
        df["timestamp"].min(),
        df["timestamp"].max(),
        out.name,
    )
    return result


def estimate_full_job(inter_request_sleep: float) -> str:
    """Estimate total requests + wall time for the full target matrix."""
    lines = []
    total_reqs = 0
    for sym in FULL_SYMBOLS:
        for interval in FULL_INTERVALS:
            days = FULL_YEARS * 365
            reqs = -(-days // INTERVAL_CHUNK_DAYS[interval])  # ceil
            total_reqs += reqs
            lines.append(f"  {sym:<4} {interval:<3}: ~{reqs} reqs ({days}d / {INTERVAL_CHUNK_DAYS[interval]}d-chunk)")
    wall_min = total_reqs * inter_request_sleep / 60.0
    # Add a per-request fetch latency budget (~2-4s server-side) on top of sleep.
    wall_min_hi = total_reqs * (inter_request_sleep + 4) / 60.0
    header = (
        f"Full-job estimate ({len(FULL_SYMBOLS)} symbols x {len(FULL_INTERVALS)} intervals, "
        f"{FULL_YEARS}yr, {inter_request_sleep:.0f}s sleep):\n"
        f"  TOTAL ~{total_reqs} requests; "
        f"~{wall_min:.0f}-{wall_min_hi:.0f} min wall "
        f"(req-rate {600/(inter_request_sleep+0.001):.0f}/10min vs 60 limit)\n"
    )
    return header + "\n".join(lines)


async def run(args) -> int:
    if args.port == IB_LIVE_PORT:
        logger.error("Live port 4001 is permanently blocked. Use paper 4002.")
        return 2

    client_id = _backfill_client_id()
    logger.info(
        "Backfill clientId=%d (executor=1, data-leg=2 — distinct, PR#34-safe)", client_id
    )
    logger.info("\n%s", estimate_full_job(args.sleep))

    # Resolve target matrix.
    if args.dry_run:
        symbols, intervals = ["MES"], ["5m"]
        sample_days = 7
        scratch = True
    elif args.full:
        symbols, intervals = FULL_SYMBOLS, FULL_INTERVALS
        sample_days = None
        scratch = False
    else:
        symbols = [s.upper() for s in args.symbols]
        intervals = args.intervals
        sample_days = None
        scratch = args.scratch

    IB, _F, _CF = _import_ib_async()
    ib = IB()
    logger.info("Connecting IB Gateway %s:%d (clientId=%d)...", IB_HOST, args.port, client_id)
    try:
        await ib.connectAsync(IB_HOST, args.port, clientId=client_id, timeout=15)
    except Exception as e:
        logger.error(
            "IB Gateway unreachable at %s:%d (%s). Start Gateway (paper), log in, retry.",
            IB_HOST,
            args.port,
            e,
        )
        return 2

    results = []
    try:
        for sym in symbols:
            for interval in intervals:
                r = await fetch_one(
                    ib,
                    sym,
                    interval,
                    years=args.years,
                    inter_request_sleep=args.sleep,
                    scratch=scratch,
                    sample_days=sample_days,
                )
                results.append(r)
    finally:
        ib.disconnect()
        logger.info("IB disconnected.")

    # Summary + sanity for dry-run.
    print("\n" + "=" * 78)
    print("IBKR INTRADAY FETCH SUMMARY")
    print("=" * 78)
    for r in results:
        print(
            f"  {r['symbol']:<4} {r['interval']:<3}  {r['status']:<13} "
            f"bars={r['bars']:>7}  {Path(r['path']).name if r.get('path') else ''}"
        )

    if args.dry_run and results and results[0]["status"] == "ok":
        _sanity_check(results[0]["path"])

    n_fail = sum(1 for r in results if r["status"] not in ("ok",))
    return 1 if n_fail else 0


def _sanity_check(path: str) -> None:
    """Print basic sanity on a fetched sample (dry-run)."""
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp")
    print("\n" + "-" * 78)
    print(f"SANITY CHECK: {Path(path).name}")
    print("-" * 78)
    print(f"  rows         : {len(df)}")
    print(f"  span         : {df['timestamp'].min()} -> {df['timestamp'].max()}")
    print(f"  columns      : {list(df.columns)}")
    ohlc_ok = bool((df["high"] >= df["low"]).all() and (df["high"] >= df["close"]).all() and (df["low"] <= df["close"]).all())
    print(f"  OHLC valid   : {ohlc_ok}")
    print(f"  null OHLC     : {int(df[['open','high','low','close']].isna().sum().sum())}")
    r = df["close"].pct_change().abs()
    print(f"  max |bar ret|: {r.max() * 100:.2f}%  (>2% count: {int((r > 0.02).sum())})")
    dup = int(df["timestamp"].duplicated().sum())
    print(f"  dup timestmp : {dup}")
    print(f"  first 2 rows :\n{df.head(2).to_string(index=False)}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--dry-run", action="store_true", help="Fetch 1 week MES 5m to a SCRATCH csv")
    p.add_argument("--full", action="store_true", help="Full target matrix (ES,MNQ,MCL,MES,MGC x 5m,15m, 2yr)")
    p.add_argument("--symbols", nargs="+", default=["MES"], help="Symbols (default MES)")
    p.add_argument("--intervals", nargs="+", default=["5m"], choices=["5m", "15m"], help="Intervals")
    p.add_argument("--years", type=float, default=2.0, help="History depth in years (default 2)")
    p.add_argument("--sleep", type=float, default=DEFAULT_INTER_REQUEST_SLEEP, help="Inter-request sleep sec (>=12)")
    p.add_argument("--port", type=int, default=IB_PAPER_PORT, help="IB Gateway port (4002 paper)")
    p.add_argument("--scratch", action="store_true", help="Prefix outputs with _dryrun_ (no canonical write)")
    args = p.parse_args()

    if args.sleep < 12:
        logger.warning("--sleep %.0f < 12s risks pacing violations; clamping to 12s.", args.sleep)
        args.sleep = 12.0

    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
