"""
JARVIS TRADER — One-shot bar backfill from cached CSVs.

Loads 1h OHLCV bars from engine/backtest/cache/ CSV files into the
market_data_bars SQLite table.  Uses INSERT OR IGNORE so re-running is a
complete no-op — no row is written twice.

Usage:
    # Dry-run: show what would be loaded, no writes
    python -m engine.scripts.backfill_market_data_bars --dry-run

    # Load all 5 symbols
    python -m engine.scripts.backfill_market_data_bars

    # Load specific symbols only
    python -m engine.scripts.backfill_market_data_bars --symbols MES MGC

Exit codes:
    0 — success (or dry-run)
    1 — one or more symbols failed to load
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill_market_data_bars")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ENGINE_DIR = Path(__file__).resolve().parent.parent
_CACHE_DIR = _ENGINE_DIR / "backtest" / "cache"

# Add engine root to sys.path for bare-module imports (same as all other scripts)
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# ---------------------------------------------------------------------------
# Symbol → CSV candidate mapping
#
# Each entry is an ordered list of candidate filenames (most-preferred first).
# The loader picks the first file that exists.  MGC (micro gold) uses the
# continuous GC contract file because no MGC-specific cache exists; prices
# are identical.
# ---------------------------------------------------------------------------

_SYMBOL_CSV_CANDIDATES: dict[str, list[str]] = {
    # For each symbol, list candidates in preference order.
    # The loader picks the FIRST existing file — except MNQ (see _SYMBOL_MERGE).
    "MES": [
        "MES_2024-04-26_2026-05-07_1h.csv",
        "MES_2024-01-01_2026-03-27_1h.csv",
    ],
    "MGC": [
        # No MGC-specific cache; GC (standard gold futures) has identical prices.
        "GC_2024-06-01_2026-03-27_1h.csv",
    ],
    "MNQ": [
        "MNQ_2024-06-01_2026-03-27_1h.csv",   # full 2yr history (primary)
    ],
    "M2K": [
        "M2K_2024-06-02_2026-05-07_1h.csv",
        "M2K_2024-01-01_2026-03-28_1h.csv",
    ],
    "MCL": [
        "MCL_2024-04-26_2026-05-07_1h.csv",
        "MCL_2024-01-01_2026-03-28_1h.csv",
    ],
}

# Symbols that need MULTIPLE files merged to cover the full available history.
# Each entry lists files to load (in order); INSERT OR IGNORE deduplicates overlap.
# Use this when no single file covers both long history AND recent data.
_SYMBOL_MERGE: dict[str, list[str]] = {
    # MNQ long file ends 2026-03-27; short file adds 2026-01-04 → 2026-05-07.
    "MNQ": [
        "MNQ_2024-06-01_2026-03-27_1h.csv",
        "MNQ_2026-01-04_2026-05-07_1h.csv",
    ],
}

ALL_SYMBOLS = list(_SYMBOL_CSV_CANDIDATES.keys())


# ---------------------------------------------------------------------------
# CSV loading helpers
# ---------------------------------------------------------------------------


def _find_csv(symbol: str) -> Optional[Path]:
    """Return the first existing candidate CSV for *symbol*, or None."""
    candidates = _SYMBOL_CSV_CANDIDATES.get(symbol.upper(), [])
    for name in candidates:
        p = _CACHE_DIR / name
        if p.exists():
            return p
    return None


def _find_all_csvs(symbol: str) -> list[Path]:
    """
    Return the list of CSV files to load for *symbol*.

    For symbols in _SYMBOL_MERGE, return all merge candidates (each file
    is loaded separately; INSERT OR IGNORE handles deduplication of overlap).
    For all other symbols, return the single best-match file.
    """
    sym = symbol.upper()
    if sym in _SYMBOL_MERGE:
        return [
            _CACHE_DIR / name
            for name in _SYMBOL_MERGE[sym]
            if (_CACHE_DIR / name).exists()
        ]
    single = _find_csv(sym)
    return [single] if single else []


def _load_csv(path: Path) -> pd.DataFrame:
    """
    Load a cache CSV and normalise columns to:
        timestamp, open, high, low, close, volume

    The cache files come in two layouts:
      - "timestamp-first":  timestamp, open, high, low, close, volume
      - "OHLCV-first":      open, high, low, close, volume, timestamp

    Both are handled automatically by checking whether 'timestamp' is present
    and moving it to the front if needed.
    """
    df = pd.read_csv(str(path))

    # Normalise column names (strip whitespace, lower)
    df.columns = [c.strip().lower() for c in df.columns]

    if "timestamp" not in df.columns:
        raise ValueError(f"No 'timestamp' column in {path.name}; columns={list(df.columns)}")

    # Move timestamp to position 0 for clarity (not strictly required)
    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        # volume is optional in the repository
        if missing == ["volume"]:
            df["volume"] = float("nan")
        else:
            raise ValueError(f"Missing required columns {missing} in {path.name}")

    df = df[cols].copy()

    # Drop rows where all OHLC are NaN
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


# ---------------------------------------------------------------------------
# Backfill logic
# ---------------------------------------------------------------------------


def backfill_symbol(
    symbol: str,
    dry_run: bool = False,
    db_path: Optional[Path] = None,
) -> dict:
    """
    Load the best cached CSV for *symbol* and persist into market_data_bars.

    Returns a result dict:
        symbol, csv_path, total_rows, new_rows, skipped_rows, error
    """
    result: dict = {
        "symbol": symbol,
        "csv_path": None,
        "total_rows": 0,
        "new_rows": 0,
        "skipped_rows": 0,
        "error": None,
    }

    csv_paths = _find_all_csvs(symbol)
    if not csv_paths:
        result["error"] = f"No cache CSV found for {symbol} in {_CACHE_DIR}"
        return result

    result["csv_path"] = "|".join(p.name for p in csv_paths)

    # Load and concatenate all CSVs for this symbol
    frames: list[pd.DataFrame] = []
    for csv_path in csv_paths:
        try:
            frames.append(_load_csv(csv_path))
        except Exception as exc:
            result["error"] = f"CSV load failed ({csv_path.name}): {exc}"
            return result

    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    result["total_rows"] = len(df)

    if dry_run:
        # In dry-run mode, report counts without writing
        first_ts = str(df["timestamp"].iloc[0]) if not df.empty else "?"
        last_ts = str(df["timestamp"].iloc[-1]) if not df.empty else "?"
        files_label = "|".join(p.name for p in csv_paths)
        logger.info(
            "[DRY-RUN] %s: %d rows from %s — %s (files: %s)",
            symbol, len(df), first_ts, last_ts, files_label,
        )
        result["new_rows"] = len(df)  # treat all as "would insert" for dry-run reporting
        return result

    try:
        from data.bars_repository import save_bars  # noqa: E402

        if db_path is not None:
            inserted = save_bars(df, symbol, "1h", source="cache", db_path=db_path)
        else:
            inserted = save_bars(df, symbol, "1h", source="cache")
    except Exception as exc:
        result["error"] = f"save_bars failed: {exc}"
        return result

    result["new_rows"] = inserted
    result["skipped_rows"] = len(df) - inserted
    logger.info(
        "%s: %d rows offered → %d new, %d skipped (file: %s)",
        symbol, len(df), inserted, result["skipped_rows"], csv_path.name,
    )
    return result


def run_backfill(
    symbols: list[str],
    dry_run: bool = False,
    db_path: Optional[Path] = None,
) -> int:
    """
    Run backfill for all symbols.

    Returns 0 on full success, 1 if any symbol encountered an error.
    """
    any_error = False
    total_new = 0
    total_skipped = 0

    for sym in symbols:
        r = backfill_symbol(sym, dry_run=dry_run, db_path=db_path)
        if r["error"]:
            logger.error("%s FAILED: %s", sym, r["error"])
            any_error = True
        else:
            total_new += r["new_rows"]
            total_skipped += r["skipped_rows"]

    if dry_run:
        logger.info(
            "[DRY-RUN] Summary: %d symbols checked; ~%d rows would be inserted",
            len(symbols), total_new,
        )
    else:
        logger.info(
            "Backfill complete: %d new rows inserted, %d already-present rows skipped",
            total_new, total_skipped,
        )

    return 1 if any_error else 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill market_data_bars from cached 1h CSV files"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=ALL_SYMBOLS,
        metavar="SYM",
        help=f"Symbols to backfill (default: {' '.join(ALL_SYMBOLS)})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be loaded without writing to the DB",
    )
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols]
    unknown = [s for s in symbols if s not in _SYMBOL_CSV_CANDIDATES]
    if unknown:
        logger.error("Unknown symbols: %s. Valid: %s", unknown, ALL_SYMBOLS)
        sys.exit(1)

    exit_code = run_backfill(symbols, dry_run=args.dry_run)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
