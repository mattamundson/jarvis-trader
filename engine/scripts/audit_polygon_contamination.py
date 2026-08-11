"""
Polygon Futures Contamination Audit — T1.5 follow-up to 2026-04-16 incident.

Scans engine/backtest/cache/*.csv for files whose price range cannot plausibly
be the futures instrument named in the filename. When the engine's Polygon
fallback was routing futures tickers to equity tickers of the same name
(``CL`` → Colgate-Palmolive, ``NQ`` → Nasdaq Inc., ``GC`` → an equity,
``ES`` → ESSA Pharma, etc.), the resulting CSV cache could contain stock
prices labeled as futures. This script flags those files by checking the
last-bar close against each future's plausible price band.

Usage:
    .venv/Scripts/python scripts/audit_polygon_contamination.py

Exit 0 on clean cache, 1 if any file is flagged.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

# (low, high) inclusive bands for the FUTURES price. Anything outside these
# ranges strongly suggests the cache was populated by the wrong Polygon
# ticker. Values are calibrated to 2024-2026 ranges with generous margin.
FUTURES_PRICE_BAND: dict[str, tuple[float, float]] = {
    # Crude oil futures ($/barrel). Note: overlaps Colgate-Palmolive
    # stock price (~$80-$90), so band alone cannot rule out contamination
    # for MCL/CL — use daily volatility as secondary signal below.
    "MCL": (25.0, 150.0),
    "CL": (25.0, 150.0),
    # Nasdaq-100 futures. Equity "NQ" = Nasdaq Inc. (~$50-$75) — clearly
    # distinguishable by band.
    "MNQ": (8_000.0, 32_000.0),
    "NQ": (8_000.0, 32_000.0),
    "NQ_F": (8_000.0, 32_000.0),
    # S&P 500 futures. Equity "ES" = ESSA Pharma (~$1-$15 penny stock).
    # Band ceiling set above 2026 all-time highs (~$7036).
    "MES": (3_000.0, 8_500.0),
    "ES": (3_000.0, 8_500.0),
    "ES_F": (3_000.0, 8_500.0),
    # Gold futures. Equity "GC" is various small caps (<$100).
    # Band ceiling set above 2026 all-time highs (~$5591).
    "MGC": (1_400.0, 6_500.0),
    "GC": (1_400.0, 6_500.0),
    # Russell 2000 micro futures.
    "M2K": (1_000.0, 3_500.0),
    "RTY": (1_000.0, 3_500.0),
    # Dow micro futures.
    "MYM": (25_000.0, 55_000.0),
    "YM": (25_000.0, 55_000.0),
    # Silver futures ($/oz).
    "SI": (12.0, 80.0),
    # 10-year / 30-year treasuries (price points — different order).
    "ZB": (90.0, 185.0),
    "ZN": (90.0, 155.0),
    # Benchmark equity ETFs (and FX micro futures) also live in the backtest
    # cache. For an ETF the symbol *is* the equity, so there is no futures/equity
    # ticker collision to detect (unlike ES=ESSA Pharma or GC=small caps) -- these
    # are generous "legit full-history range" guards, sized from each series'
    # observed dividend/price-adjusted range in this cache with margin, so a real
    # equity-price leak (wrong scale) still lands far outside. Ceilings look high
    # because this cache runs to 2026 levels well above nominal (GC ~5591, ES
    # ~7630, silver ~105), and floors look low because adjusted close reaches far
    # back (SPY ~23.8 in 1993, XLU ~3.3 in 2002).
    #
    # SPY floor widened from 250 to cover full adjusted history back to 1993 --
    # the old floor false-flagged legitimate pre-2016 SPY as CONTAMINATED.
    "SPY": (15.0, 900.0),
    "DIA": (25.0, 650.0),   # Dow SPDR;    observed ~41.7-520
    "QQQ": (10.0, 950.0),   # Nasdaq-100;  observed ~16.9-745
    "IWM": (15.0, 420.0),   # Russell 2k;  observed ~23.8-298
    "MDY": (15.0, 950.0),   # MidCap SPDR; observed ~24.7-695
    "EEM": (4.0, 110.0),    # EM equity;   observed ~7.2-71
    "EFA": (8.0, 160.0),    # EAFE;        observed ~15.0-105
    "XLU": (2.0, 90.0),     # Utilities;   observed ~3.3-47 (heavy dividend adj.)
    "GLD": (25.0, 650.0),   # Gold ETF;    observed ~41.3-496
    "SLV": (5.0, 160.0),    # Silver ETF;  observed ~8.9-106 (2026 silver run)
    "TLT": (22.0, 210.0),   # 20y+ treasuries; observed ~36.0-143
    "LQD": (22.0, 170.0),   # IG credit;   observed ~36.8-113
    "HYG": (12.0, 130.0),   # HY credit;   observed ~21.8-80 (heavy dividend adj.)
    # FX micro futures quote the exchange rate itself (~0.8-1.8), so any equity
    # leak ($10-500+) lands far outside. Values match master #270, so trunk->master
    # convergence (#279) is conflict-free for this dict.
    "M6B": (0.90, 1.80),    # Micro GBP/USD
    "M6E": (0.80, 1.70),    # Micro EUR/USD
    # HiddenPivots scanner cache (config.py SCAN_SYMBOLS) -- single-name equities,
    # broader universe than the 4-name options watchlist above. No futures/equity
    # ticker collision risk for these (the symbol IS the equity), so bands are
    # generous "legit full-history range" guards like the ETF entries above:
    # floor = 0.5x observed adjusted-history low (split-adjusted closes run near
    # zero for decades-old names), ceiling = 1.5x observed high rounded up, so a
    # real scale-error leak still lands far outside.
    "AAPL": (113.39, 515.0),   # observed ~226.79-340.08
    "TSLA": (149.16, 735.0),   # observed ~298.32-489.88
    "AMD": (0.81, 875.0),      # observed ~1.62-580.91
    "AMZN": (0.03, 415.0),     # observed ~0.07-274.99
    "AVGO": (0.51, 725.0),     # observed ~1.02-480.81
    "BAC": (0.13, 95.0),       # observed ~0.27-62.62
    "COIN": (16.26, 630.0),    # observed ~32.53-419.78
    "COST": (2.01, 1640.0),    # observed ~4.01-1092.58
    "CRM": (1.18, 545.0),      # observed ~2.36-363.22
    "GOOGL": (1.24, 605.0),    # observed ~2.48-402.38
    "JPM": (0.51, 540.0),      # observed ~1.02-357.31
    "LLY": (0.25, 1855.0),     # observed ~0.50-1235.56
    "META": (8.79, 1185.0),    # observed ~17.58-787.42
    "MSFT": (0.03, 810.0),     # observed ~0.05-538.66
    "MSTR": (0.22, 715.0),     # observed ~0.45-473.83
    "MU": (0.17, 1825.0),      # observed ~0.33-1213.37
    "NFLX": (0.02, 205.0),     # observed ~0.04-133.91
    "NVDA": (0.02, 355.0),     # observed ~0.03-235.47
    "PLTR": (3.0, 315.0),      # observed ~6.00-207.18
    "SMH": (3.12, 1005.0),     # observed ~6.24-668.91
    "UBER": (7.41, 155.0),     # observed ~14.82-100.10
    "XLE": (2.57, 95.0),       # observed ~5.14-62.11
    "XOM": (0.04, 260.0),      # observed ~0.08-170.31
}


# For MCL specifically, Colgate-Palmolive's daily close stays within ~1-2%
# day-to-day. Crude oil's daily close commonly moves 2-4%. If the cache's
# mean absolute daily return is below this threshold AND the price band is
# in the overlap zone ($70-$95), we flag the file as SUSPECT rather than
# CONTAMINATED.
CRUDE_DAILY_VOL_FLOOR = 0.012  # 1.2% daily stdev is the ceiling for Colgate,
# the floor for crude


def symbol_from_filename(name: str) -> str:
    # Filenames look like ``MES_2024-01-01_2026-03-27_1h.csv`` or
    # ``MNQ_1h_730d.csv``. Symbol is the leading token before the first
    # underscore (with special-case for ``ES_F``). Dry-run backtests prefix
    # the name with ``_dryrun_`` (e.g. ``_dryrun_MES_2026-06-05_..._cont.csv``),
    # which yields an empty leading token — drop empty tokens and skip the
    # ``dryrun`` marker so the real symbol is still validated.
    stem = Path(name).stem
    parts = [p for p in stem.split("_") if p]
    while parts and parts[0] == "dryrun":
        parts.pop(0)
    if len(parts) >= 2 and parts[0] == "ES" and parts[1] == "F":
        return "ES_F"
    return parts[0] if parts else ""


def read_closes(csv_path: Path) -> tuple[list[float], list[str]]:
    closes: list[float] = []
    dates: list[str] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # The backtest data loader writes columns Date,Open,High,Low,Close,Volume.
            # Be permissive about casing.
            close_key = next((k for k in row if k and k.lower() == "close"), None)
            date_key = next(
                (k for k in row if k and k.lower() in {"date", "datetime", "timestamp"}), None
            )
            if close_key is None:
                continue
            try:
                c = float(row[close_key])
            except (TypeError, ValueError):
                continue
            closes.append(c)
            if date_key is not None:
                dates.append(row[date_key])
    return closes, dates


def daily_volatility_from_closes(closes: list[float]) -> float:
    if len(closes) < 3:
        return 0.0
    rets = []
    for a, b in zip(closes[:-1], closes[1:], strict=False):
        if a > 0:
            rets.append((b - a) / a)
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return var**0.5


def classify(path: Path) -> dict:
    symbol = symbol_from_filename(path.name)
    closes, dates = read_closes(path)
    if not closes:
        return {
            "path": path,
            "symbol": symbol,
            "verdict": "EMPTY",
            "reason": "no close column or no rows",
        }
    band = FUTURES_PRICE_BAND.get(symbol)
    if band is None:
        return {
            "path": path,
            "symbol": symbol,
            "verdict": "UNKNOWN_SYMBOL",
            "reason": f"no band for {symbol}",
        }
    low, high = band
    first, last = closes[0], closes[-1]
    mn, mx = min(closes), max(closes)
    in_band = low <= mn and mx <= high
    if not in_band:
        return {
            "path": path,
            "symbol": symbol,
            "verdict": "CONTAMINATED",
            "reason": f"prices {mn:.2f}-{mx:.2f} outside futures band {low:.0f}-{high:.0f}",
            "first": first,
            "last": last,
            "bars": len(closes),
        }
    # For crude oil in the overlap zone, sanity-check volatility.
    if symbol in {"MCL", "CL"} and 70 <= mn and mx <= 95:
        vol = daily_volatility_from_closes(closes)
        if vol < CRUDE_DAILY_VOL_FLOOR:
            return {
                "path": path,
                "symbol": symbol,
                "verdict": "SUSPECT",
                "reason": f"vol {vol:.4f} below crude floor {CRUDE_DAILY_VOL_FLOOR}; could be Colgate-Palmolive",
                "first": first,
                "last": last,
                "bars": len(closes),
            }
    return {
        "path": path,
        "symbol": symbol,
        "verdict": "CLEAN",
        "reason": f"range {mn:.2f}-{mx:.2f} within {low:.0f}-{high:.0f}",
        "first": first,
        "last": last,
        "bars": len(closes),
    }


def main() -> int:
    here = Path(__file__).resolve().parent.parent
    cache = here / "backtest" / "cache"
    if not cache.exists():
        print(f"[ERROR] cache dir missing: {cache}", file=sys.stderr)
        return 2

    csvs = sorted(cache.glob("*.csv"))
    results = [classify(p) for p in csvs]

    by_verdict: dict[str, list[dict]] = {}
    for r in results:
        by_verdict.setdefault(r["verdict"], []).append(r)

    print(f"\n{'='*80}")
    print(f"Polygon Futures Contamination Audit — {len(csvs)} cache files")
    print("=" * 80)

    for verdict in ["CONTAMINATED", "SUSPECT", "UNKNOWN_SYMBOL", "EMPTY", "CLEAN"]:
        rows = by_verdict.get(verdict, [])
        if not rows:
            continue
        print(f"\n[{verdict}] {len(rows)} file(s)")
        for r in rows:
            rel = r["path"].relative_to(here)
            extra = ""
            if "bars" in r:
                extra = f" | last={r.get('last')} bars={r['bars']}"
            print(f"  {rel}\n      reason: {r['reason']}{extra}")

    contaminated = by_verdict.get("CONTAMINATED", [])
    suspect = by_verdict.get("SUSPECT", [])
    print(f"\n{'='*80}")
    if contaminated or suspect:
        print(f"RESULT: {len(contaminated)} CONTAMINATED, {len(suspect)} SUSPECT.")
        print("Recommended action: move flagged CSVs out of cache/ before next backtest.")
        print("=" * 80)
        return 1
    print("RESULT: cache is CLEAN. No futures files match equity-ticker price ranges.")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
