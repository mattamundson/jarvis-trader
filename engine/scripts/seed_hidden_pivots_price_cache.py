"""PRB-23 — seed a CSV price-cache floor for the extended Hidden Pivots watchlist.

PRB-21 (PR #530) found that 22 of the 33 symbols in hidden_pivots_router's
DEFAULT_WATCHLIST (the "momentum name" additions: NFLX, CRM, LLY, MSFT, SLV,
JPM, BAC, XOM, COST, SMH, GOOGL, META, AVGO, MU, UBER, XLE, NVDA, AMZN, PLTR,
COIN, MSTR, AMD) have zero live-price fallback floor once both IBKR and
Polygon (hard rate-limited to 4 calls/60s on the free tier) miss -- the only
remaining fallback, the CSV backtest cache (`_load_csv_cache` in
engine/data/market_data.py), only has files for the 11 symbols that have ever
been backtested. PR #530 shipped the interim fix (b1): cap the dashboard's
live-price poll to just those 11 via `get_price_covered_watchlist()` in
engine/routers/hidden_pivots_router.py.

This script is the structural follow-up (b2): a lightweight daily-close
snapshot job that writes a correctly-formatted ``{symbol}_{start}_{end}_1d.csv``
file into engine/backtest/cache/ for every DEFAULT_WATCHLIST symbol that
doesn't already have sufficiently fresh cache coverage. Once a symbol has a
fresh file, `get_price_covered_watchlist()` picks it up automatically on the
next call -- it already re-derives coverage from the cache directory glob, so
no further dashboard change is needed.

Data source: yfinance primary / Stooq fallback, reusing the already-tested
fetch -> normalize -> write pipeline from `backtest.free_daily_export`
(`normalize_daily`, `fetch_yfinance`, `fetch_stooq`). Both verified
network-reachable during PRB-23 investigation (a live yfinance pull for NVDA
returned real bars). Polygon's aggregates/snapshot endpoints were confirmed
403 NOT_AUTHORIZED on the configured plan during PRB-21/23 (free/Basic tier
not entitled), so Polygon is deliberately not used here.

One deliberate deviation from `free_daily_export.cache_filename()`: this
watchlist includes GOOGL, a 5-character symbol, which violates
`export_ibkr_history.CACHE_FILENAME_CONTRACT`'s 2-4 char assertion (that
contract exists for a *different* downstream reader, `_gate_v2_helpers.
_find_latest_cache`, which nothing here calls). `_has_csv_price_floor` /
`_load_csv_cache` -- the only readers that matter for this fix -- just glob
`{symbol}_*_1d.csv` and don't care about symbol length, so this script builds
its own filename directly instead of importing the stricter contract.

Futures symbols (MES, MNQ, MGC, MCL) are HARD-EXCLUDED from this job, always
-- confirmed live during PRB-23 that yfinance can't serve them safely:
MES/MNQ/MCL simply 404 ("possibly delisted"), which is a safe no-op, but
yfinance's ``MGC`` ticker silently resolves to the Vanguard Mega Cap ETF
(~$270/share) instead of COMEX Micro Gold futures (~$3000+/oz) -- a
wrong-instrument collision that would poison the price cache with the wrong
asset entirely if written. These 4 already have their own dedicated
futures-data pipelines (build_daily_cache_2025.py, refresh_ibkr_futures_data.py,
export_ibkr_history.py) and were never this job's target -- PRB-23's gap is
specifically the 22 "momentum name" equity/ETF additions.

NOT wired into a scheduled task or pm2 app by this change -- that's a
deploy-time decision left to Amo / a follow-up. To schedule it once
approved: a daily Windows scheduled task (same MINUTE-grammar registration
pattern used for down-alert-watchdog) running, once a day after the close,

    engine\\.venv\\Scripts\\python.exe -m scripts.seed_hidden_pivots_price_cache

would keep the floor fresh with zero manual effort.

Usage (run with cwd=engine/ so bare-module imports resolve, matching every
other script in this directory):

    .venv/Scripts/python -m scripts.seed_hidden_pivots_price_cache
    .venv/Scripts/python -m scripts.seed_hidden_pivots_price_cache --symbols NFLX CRM
    .venv/Scripts/python -m scripts.seed_hidden_pivots_price_cache --max-age-days 3
    .venv/Scripts/python -m scripts.seed_hidden_pivots_price_cache --force
    .venv/Scripts/python -m scripts.seed_hidden_pivots_price_cache --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_hidden_pivots_price_cache")

_ENGINE_DIR = Path(__file__).resolve().parent.parent

# Add engine root to sys.path for bare-module imports (same convention as
# every other script in engine/scripts/, e.g. backfill_market_data_bars.py).
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from backtest.free_daily_export import (  # noqa: E402
    Fetcher,
    _default_fetchers,
    normalize_daily,
)

# Canonical cache directory -- hardcoded to the MAIN checkout, same convention
# as backtest/free_daily_export.py ("writes to the MAIN-checkout cache ... so
# the data lands where the engine + factory read it and survives a worktree
# prune"). Override with --cache-dir for tests / one-off runs elsewhere.
CACHE_DIR = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache")

DEFAULT_MAX_AGE_DAYS = 4  # spans a 3-day weekend + one slack day
INTERVAL = "1d"

# Never fetch these via yfinance -- see module docstring. MES/MNQ/MCL 404;
# MGC silently resolves to the wrong instrument (Vanguard Mega Cap ETF).
# Hard exclusion, independent of --force / staleness.
FUTURES_SYMBOLS = frozenset({"MES", "MNQ", "MGC", "MCL"})

# Filename end-date regex -- mirrors MarketDataManager._load_csv_cache's
# `_end_date` helper in engine/data/market_data.py so freshness checks here
# agree with what the live price waterfall will actually pick as "freshest".
_END_DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_" + re.escape(INTERVAL) + r"\.csv$")


def _get_default_watchlist() -> list[str]:
    """DEFAULT_WATCHLIST from hidden_pivots_router, imported lazily so this
    script's pure logic (below) can be unit-tested without needing the full
    router module (and its FastAPI/data-manager dependency chain) importable.
    """
    from routers.hidden_pivots_router import DEFAULT_WATCHLIST

    return list(DEFAULT_WATCHLIST)


# ── pure core (no IO) ───────────────────────────────────────────────────────


def cache_filename(symbol: str, start_date: str, end_date: str) -> str:
    """Build the canonical cache filename for *symbol*.

    Deliberately does NOT assert export_ibkr_history.CACHE_FILENAME_CONTRACT
    (2-4 char symbols only) -- GOOGL is 5 characters and is a legitimate
    DEFAULT_WATCHLIST member. See module docstring for why that's safe here.
    """
    return f"{symbol.upper()}_{start_date}_{end_date}_{INTERVAL}.csv"


def latest_cache_end_date(symbol: str, cache_dir: Path) -> Optional[date]:
    """The end-date of the freshest existing 1d cache file for *symbol*, or
    None if no such file exists. Mirrors `_load_csv_cache`'s freshest-file
    selection convention (max by parsed end-date, not lexicographic filename)
    so this script's idea of "fresh" matches what the live waterfall serves.
    """
    try:
        matches = list(cache_dir.glob(f"{symbol.upper()}_*_{INTERVAL}.csv"))
    except OSError:
        return None
    if not matches:
        return None

    def _end(p: Path) -> str:
        m = _END_DATE_RE.search(p.name)
        if m:
            return m.group(1)
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", p.name)
        return dates[-1] if dates else ""

    chosen = max(matches, key=lambda p: (_end(p), p.name))
    end_str = _end(chosen)
    if not end_str:
        return None
    try:
        return date.fromisoformat(end_str)
    except ValueError:
        return None


def needs_refresh(
    symbol: str,
    cache_dir: Path,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    today: Optional[date] = None,
    force: bool = False,
) -> bool:
    """True if *symbol* has no cache file, or its freshest file is older
    than *max_age_days* relative to *today*. Futures symbols (see
    FUTURES_SYMBOLS) are never refreshed by this job regardless of --force."""
    if symbol.upper() in FUTURES_SYMBOLS:
        return False
    if force:
        return True
    end = latest_cache_end_date(symbol, cache_dir)
    if end is None:
        return True
    ref = today or date.today()
    return (ref - end).days > max_age_days


def symbols_to_seed(
    symbols: Sequence[str],
    cache_dir: Path,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    today: Optional[date] = None,
    force: bool = False,
) -> list[str]:
    """Filter *symbols* down to the ones that actually need a fetch, in
    stable input order. Excludes FUTURES_SYMBOLS unconditionally."""
    return [
        s
        for s in symbols
        if needs_refresh(s, cache_dir, max_age_days=max_age_days, today=today, force=force)
    ]


# ── pipeline (IO) ───────────────────────────────────────────────────────────


def seed_symbol(
    symbol: str,
    *,
    cache_dir: Path = CACHE_DIR,
    dry_run: bool = False,
    fetchers: Optional[Sequence[Fetcher]] = None,
) -> dict:
    """Fetch (primary then fallback) -> normalize -> write one symbol's daily
    price-cache snapshot. Never raises on a single source's failure -- returns
    a status dict instead, matching free_daily_export.export_symbol's shape."""
    raw: "pd.DataFrame | None" = None
    source: Optional[str] = None
    for name, fn in fetchers or _default_fetchers():
        try:
            r = fn(symbol)
        except Exception:  # noqa: BLE001 - source variance; fall through to next source
            continue
        if r is not None and len(r):
            raw, source = r, name
            break

    if raw is None or not len(raw):
        return {"symbol": symbol, "status": "NO_DATA"}

    norm = normalize_daily(raw)
    if norm.empty:
        return {"symbol": symbol, "status": "EMPTY_AFTER_NORM", "source": source}

    start, end = norm["timestamp"].iloc[0], norm["timestamp"].iloc[-1]
    fname = cache_filename(symbol, start, end)
    out = {
        "symbol": symbol,
        "status": "OK",
        "source": source,
        "rows": int(len(norm)),
        "start": start,
        "end": end,
        "file": fname,
    }
    if not dry_run:
        cache_dir.mkdir(parents=True, exist_ok=True)
        norm.to_csv(cache_dir / fname, index=False)
        out["path"] = str(cache_dir / fname)
    return out


def seed_watchlist(
    symbols: Optional[Sequence[str]] = None,
    *,
    cache_dir: Path = CACHE_DIR,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    today: Optional[date] = None,
    force: bool = False,
    dry_run: bool = False,
    fetchers: Optional[Sequence[Fetcher]] = None,
) -> list[dict]:
    """Seed/refresh CSV price cache for every stale-or-missing symbol in
    *symbols* (defaults to the full DEFAULT_WATCHLIST). Returns one result
    dict per symbol actually considered, including SKIPPED entries for
    symbols whose cache is already fresh."""
    all_symbols = list(symbols) if symbols is not None else _get_default_watchlist()
    to_fetch = set(
        symbols_to_seed(
            all_symbols, cache_dir, max_age_days=max_age_days, today=today, force=force
        )
    )

    results = []
    for sym in all_symbols:
        if sym.upper() in FUTURES_SYMBOLS:
            results.append({"symbol": sym, "status": "SKIPPED_FUTURES_NOT_YFINANCE_SAFE"})
            continue
        if sym not in to_fetch:
            results.append({"symbol": sym, "status": "SKIPPED_FRESH"})
            continue
        results.append(seed_symbol(sym, cache_dir=cache_dir, dry_run=dry_run, fetchers=fetchers))
    return results


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(description="seed Hidden Pivots CSV daily price-cache floor")
    ap.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="override target symbols (default: full DEFAULT_WATCHLIST)",
    )
    ap.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    ap.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help="skip symbols whose cache is fresher than this (default: %(default)s)",
    )
    ap.add_argument("--force", action="store_true", help="refetch even fresh symbols")
    ap.add_argument("--dry-run", action="store_true", help="report only, no writes")
    args = ap.parse_args()

    results = seed_watchlist(
        args.symbols,
        cache_dir=args.cache_dir,
        max_age_days=args.max_age_days,
        force=args.force,
        dry_run=args.dry_run,
    )
    for r in results:
        print(json.dumps(r))

    _SKIP_STATUSES = ("SKIPPED_FRESH", "SKIPPED_FUTURES_NOT_YFINANCE_SAFE")
    ok = sum(1 for r in results if r["status"] == "OK")
    skipped = sum(1 for r in results if r["status"] in _SKIP_STATUSES)
    failed = sum(1 for r in results if r["status"] not in ("OK", *_SKIP_STATUSES))
    logger.info("seeded=%d skipped=%d failed=%d total=%d", ok, skipped, failed, len(results))
    if failed:
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
