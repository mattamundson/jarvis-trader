"""
Regression: backtest cache files must contain futures prices, not equity prices.

Background: 2026-04-16 incident. When Polygon.io was routing futures tickers
to same-named equities (``CL`` → Colgate-Palmolive, ``NQ`` → Nasdaq Inc., etc.),
any CSV generated via Polygon would contain stock prices labeled as futures.
The 2026-04-16 T1.5 audit scanned all 78 cached CSVs and found none matched an
equity-ticker price range, so prior backtest validation numbers stand.

This test re-runs that audit on every test invocation so a contaminated file
can't silently sneak back in (e.g. if someone re-enables Polygon partially
without updating the blocklist).

Location of the audit logic: ``scripts/audit_polygon_contamination.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = ENGINE_DIR / "backtest" / "cache"

# Make ``scripts`` importable when run from repo root
SCRIPTS_DIR = ENGINE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from audit_polygon_contamination import (  # noqa: E402
    FUTURES_PRICE_BAND,
    classify,
)


@pytest.mark.skipif(
    not CACHE_DIR.exists() or not any(CACHE_DIR.glob("*.csv")),
    reason="backtest/cache is empty or absent in this checkout",
)
def test_no_contaminated_cache_files():
    """Every cached CSV must have prices inside its futures/equity band."""
    csvs = sorted(CACHE_DIR.glob("*.csv"))
    results = [classify(p) for p in csvs]

    contaminated = [r for r in results if r["verdict"] == "CONTAMINATED"]
    suspect = [r for r in results if r["verdict"] == "SUSPECT"]
    unknown = [r for r in results if r["verdict"] == "UNKNOWN_SYMBOL"]

    # UNKNOWN_SYMBOL is a config gap (missing band), not data contamination.
    # Surface it as an informational failure so new cache symbols get a band.
    assert not unknown, (
        f"{len(unknown)} cache file(s) have no price band defined. "
        f"Add the symbol to FUTURES_PRICE_BAND in "
        f"scripts/audit_polygon_contamination.py. "
        f"First: {unknown[0]['path'].name} ({unknown[0]['reason']})"
    )

    assert not contaminated, (
        f"{len(contaminated)} cache file(s) have prices outside the futures "
        f"band — likely populated by the Polygon equity-ticker bug. "
        f"Move them out of backtest/cache/ and re-fetch via IBKR. "
        f"First few: {[r['path'].name for r in contaminated[:3]]}"
    )

    assert not suspect, (
        f"{len(suspect)} cache file(s) are SUSPECT (prices in band but "
        f"volatility implies equity, not futures). "
        f"First few: {[r['path'].name for r in suspect[:3]]}"
    )


def test_audit_covers_every_futures_symbol_in_code():
    """The audit's band map must cover every futures symbol the engine uses."""
    # Keep this in sync with POLYGON_FUTURES_BLOCKLIST in engine/data/market_data.py.
    expected_futures = {"MCL", "MNQ", "MES", "MGC", "M2K", "MYM",
                        "CL", "NQ", "ES", "GC", "RTY", "YM",
                        "SI", "ZB", "ZN"}
    missing = expected_futures - FUTURES_PRICE_BAND.keys()
    assert not missing, (
        f"FUTURES_PRICE_BAND missing bands for {sorted(missing)}. "
        f"Add them to scripts/audit_polygon_contamination.py."
    )
