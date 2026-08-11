#!/usr/bin/env python
"""
MES Deep History Puller — walks the real dated-contract chain backward.

Built 2026-08-11 for Item 2 of the jarvis-trader session plan (grow the MES
trend gate-v2 OOS sample past MIN_OOS_TRADES_TOTAL=30; rank11 had 17).

Why this exists and NOT `export_ibkr_history.py`: that script resolves
ContFuture to the CURRENT front-month contract, converts it to a concrete
dated Future, and requests historical data against THAT SAME contract for
every chunk in its deep-pull plan -- including chunks going back years. A
specific dated Future contract only has real trading data for its own
listing window (~9-12 months), so that approach silently returns
empty/near-zero bars for anything before the current contract's own life.
`ContFuture` itself can't be used for backward walks either: IB rejects a
custom endDateTime against it (error 10339, "Setting end date/time for
continuous future security type is not allowed") -- it only serves the
trailing window from now.

The only way to get real historical prices further back is to resolve each
PAST quarterly contract individually (Future(..., localSymbol='MESH4',
includeExpired=True)) and pull ITS OWN real trading window, then splice the
per-contract series together (raw, unadjusted -- no back-adjustment, so
there's a small real roll-gap at each boundary rather than a smoothed one;
this matches how the existing cache was itself built incrementally over
real time, so the methodology is consistent at the merge boundary).

Whether this even works depends on IB Gateway's account-level historical
data permission for expired contracts, which as of 2026-08-11 has a hard
wall on this account: MESU4 (Sep 2024 expiry) resolves via
reqContractDetailsAsync, MESM4 (Jun 2024) does not. Run
`check_mes_history_available.py` first (or pass --check-only here) to
confirm the wall has lifted before trusting this script's output.

Usage (from engine/ directory):
    .venv/Scripts/python scripts/pull_mes_deep_history.py
    .venv/Scripts/python scripts/pull_mes_deep_history.py --check-only
    .venv/Scripts/python scripts/pull_mes_deep_history.py --max-contracts 20
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd  # noqa: E402

CACHE_DIR = Path(__file__).parent.parent / "backtest" / "cache"
IB_HOST = "127.0.0.1"
IB_PORT = 4002  # paper only -- port 4001 is permanently blocked, never use it
IB_CLIENT_ID = 112

QUARTERLY_CODES = ["H", "M", "U", "Z"]  # Mar, Jun, Sep, Dec
QUARTERLY_MONTH = {"H": 3, "M": 6, "U": 9, "Z": 12}

# Per-contract chunk duration. Conservative: a quarter is ~3 months, this
# gives headroom without approaching the >=1Y duration boundary that hung
# (silently, past a 40s asyncio timeout) during this session's ContFuture
# probing -- unconfirmed whether that was a hard duration cap or a pacing
# violation, so specific-contract pulls stay well clear of it too.
CHUNK_DURATION = "4 M"
MIN_BARS_TO_CONTINUE = 20  # a contract with fewer real bars than this = no more usable history
PACING_DELAY_S = 4


def _prior_quarter_local_symbol(year: int, code: str) -> tuple[int, str]:
    idx = QUARTERLY_CODES.index(code)
    if idx == 0:
        return year - 1, QUARTERLY_CODES[-1]
    return year, QUARTERLY_CODES[idx - 1]


async def _resolve_contract(ib, local_symbol: str):
    from ib_async import Future

    fut = Future(symbol="MES", exchange="CME", currency="USD", localSymbol=local_symbol, includeExpired=True)
    details = await asyncio.wait_for(ib.reqContractDetailsAsync(fut), timeout=10)
    if not details:
        return None
    return details[0].contract


async def check_available(local_symbol: str = "MESM4") -> bool:
    """Cheap probe: does IB resolve a specific historically-expired contract?
    MESM4 (Jun 2024) is the known current wall (2026-08-11) -- MESU4 (Sep 2024)
    resolves, MESM4 does not. Pass a different localSymbol to probe elsewhere.
    """
    from ib_async import IB

    ib = IB()
    try:
        await asyncio.wait_for(ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, timeout=8), timeout=12)
    except Exception:
        return False
    try:
        contract = await _resolve_contract(ib, local_symbol)
        return contract is not None
    finally:
        ib.disconnect()


async def pull_deep_history(max_contracts: int = 20) -> pd.DataFrame | None:
    """Walk the MES quarterly contract chain backward from the existing
    cache's earliest bar, pulling each contract's own real trading window.
    Stops when a contract can't be resolved or returns near-zero bars.
    Returns the combined (existing cache + newly pulled) DataFrame, or None
    if nothing new was fetched.
    """
    from ib_async import IB

    existing_files = sorted(CACHE_DIR.glob("MES_*_1h.csv"))
    if not existing_files:
        print("[deep-history] No existing MES 1h cache found -- nothing to extend.")
        return None
    # Latest-end-date file, matching _find_latest_cache's own selection contract.
    existing_file = max(existing_files, key=lambda p: p.stem.split("_")[2] if len(p.stem.split("_")) >= 3 else "")
    existing_df = pd.read_csv(existing_file)
    existing_df["timestamp"] = pd.to_datetime(existing_df["timestamp"], utc=True)
    existing_df = existing_df.set_index("timestamp").sort_index()
    print(f"[deep-history] Existing cache: {existing_file.name} ({len(existing_df)} bars, "
          f"{existing_df.index.min()} -> {existing_df.index.max()})")

    earliest = existing_df.index.min().to_pydatetime()
    year, code = earliest.year, None
    for c in QUARTERLY_CODES:
        if QUARTERLY_MONTH[c] <= earliest.month:
            code = c
    if code is None:
        year -= 1
        code = "Z"

    ib = IB()

    def on_error(reqId, errorCode, errorString, contract):
        if errorCode not in (2104, 2106, 2158):
            print(f"[deep-history] IB_ERROR reqId={reqId} code={errorCode} msg={errorString}", flush=True)

    ib.errorEvent += on_error
    await asyncio.wait_for(ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, timeout=8), timeout=12)
    print("[deep-history] CONNECTED", flush=True)

    new_frames = []
    cursor_end = earliest - timedelta(seconds=1)

    try:
        for i in range(max_contracts):
            year, code = _prior_quarter_local_symbol(year, code)
            local_symbol = f"MES{code}{year % 10}"
            print(f"[deep-history] contract {i + 1}/{max_contracts}: {local_symbol} "
                  f"ending {cursor_end.strftime('%Y%m%d-%H:%M:%S')} UTC...", flush=True)

            contract = await _resolve_contract(ib, local_symbol)
            if contract is None:
                print(f"[deep-history] {local_symbol} not resolvable -- IB history wall reached, stopping.", flush=True)
                break

            try:
                bars = await asyncio.wait_for(
                    ib.reqHistoricalDataAsync(
                        contract,
                        endDateTime=cursor_end.strftime("%Y%m%d-%H:%M:%S"),
                        durationStr=CHUNK_DURATION,
                        barSizeSetting="1 hour",
                        whatToShow="TRADES",
                        useRTH=False,
                        formatDate=1,
                    ),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                print(f"[deep-history] {local_symbol} TIMEOUT -- stopping walk here.", flush=True)
                break

            if not bars or len(bars) < MIN_BARS_TO_CONTINUE:
                print(f"[deep-history] {local_symbol}: only {len(bars) if bars else 0} bars -- "
                      "no more usable history, stopping.", flush=True)
                break

            rows = [
                {"timestamp": b.date, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
                for b in bars
            ]
            df = pd.DataFrame(rows)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.set_index("timestamp").sort_index()
            print(f"[deep-history] {local_symbol}: {len(df)} bars, {df.index.min()} -> {df.index.max()}", flush=True)
            new_frames.append(df)

            cursor_end = df.index.min().to_pydatetime() - timedelta(seconds=1)
            await asyncio.sleep(PACING_DELAY_S)
    finally:
        ib.disconnect()
        print("[deep-history] disconnected", flush=True)

    if not new_frames:
        print("[deep-history] No new bars fetched.")
        return None

    new_df = pd.concat(new_frames).sort_index()
    new_df = new_df[~new_df.index.duplicated(keep="last")]
    combined = pd.concat([new_df, existing_df]).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    print(f"[deep-history] Combined: {len(combined)} bars "
          f"({len(combined) - len(existing_df)} new), {combined.index.min()} -> {combined.index.max()}")
    return combined


def save_combined_cache(combined: pd.DataFrame) -> Path:
    start = combined.index.min().strftime("%Y-%m-%d")
    end = combined.index.max().strftime("%Y-%m-%d")
    out_path = CACHE_DIR / f"MES_{start}_{end}_1h.csv"
    out_df = combined.reset_index()
    out_df = out_df.rename(columns={out_df.columns[0]: "timestamp"})
    out_df.to_csv(out_path, index=False)
    print(f"[deep-history] Wrote {out_path.name} ({len(out_df)} bars)")
    return out_path


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true", help="just probe MESM4 availability, no pull")
    parser.add_argument("--max-contracts", type=int, default=20)
    args = parser.parse_args()

    if args.check_only:
        available = await check_available()
        print(f"MESM4 resolvable: {available}")
        return 0 if available else 1

    combined = await pull_deep_history(max_contracts=args.max_contracts)
    if combined is None:
        print("[deep-history] Nothing new -- no cache written.")
        return 1

    save_combined_cache(combined)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
