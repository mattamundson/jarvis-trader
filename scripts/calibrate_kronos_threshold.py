"""
calibrate_kronos_threshold.py
==============================
Empirically derive the ``BULL_BEAR_THRESHOLD_BPS`` for the Kronos classifier
from historical 1-hour bar data stored in ``engine/data/jarvis_trader.db``.

Usage (from repo root)::

    engine/.venv/Scripts/python scripts/calibrate_kronos_threshold.py

Output:
    - Markdown report printed to stdout
    - JSON written to ``scripts/data/kronos_threshold_calibration.json``

Method
------
For each instrument (MES, MCL, MNQ) the script:

1. Loads 1-hour OHLCV bars from ``market_data_bars`` (non-smoke-test sources,
   within the configured lookback window).
2. Computes N-bar-ahead log returns in basis points for every bar:
   ``ret_bps = log(close[t+N] / close[t]) * 10_000``
3. Reports the distribution (p10 .. p90) of both signed and absolute returns.
4. Recommends a threshold equal to the 75th percentile of the absolute-return
   distribution ("p75-of-absolute").  This sits above the median fluctuation
   without being so tight that every small drift triggers a bull/bear verdict.

Caveats encoded in output
-------------------------
- Return distributions are non-stationary across regimes (trending vs choppy).
  A single percentile from the full sample underweights quiet periods and
  overweights high-vol events.  The recommended value is a starting point, not
  a calibrated optimal; revisit after the first 30 days of live Kronos verdicts.
- MCL (crude oil) carries meaningfully different volatility than MES/MNQ
  (equity indices), so per-instrument thresholds are strongly preferred over
  a single global value.
- Log returns are used for symmetry; bps conversion matches ``_forecast_to_verdict``
  in ``engine/agents/kronos_classifier.py`` which uses simple returns.  At
  small magnitudes the difference is negligible (<1 bps), but the distinction
  is noted for completeness.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HORIZON_BARS: int = 5  # N-bar-ahead forecast horizon to match Kronos pred_len default
LOOKBACK_DAYS: int = 90  # Calendar days of history to include
RECOMMENDATION_METHOD: str = "p75-of-absolute"

# Instruments to calibrate; must match symbols in market_data_bars
INSTRUMENTS: list[str] = ["MES", "MCL", "MNQ"]

# Minimum bars required for a valid calibration (otherwise skip gracefully)
MIN_BARS_REQUIRED: int = 20

# Per-instrument sanity floor for close prices.  Rows below this level are
# clearly bad data (e.g. TV returning 100.5 for MES during a startup burst)
# and are excluded before computing returns.
PRICE_FLOORS: dict[str, float] = {
    "MES": 3000.0,  # MES trades ~5000-7500; anything below 3000 is corrupt
    "MCL": 20.0,  # MCL crude oil; below $20/bbl would be extraordinary
    "MNQ": 10000.0,  # MNQ trades ~17000-22000; anything below 10000 is corrupt
}
DEFAULT_PRICE_FLOOR: float = 1.0  # for unknown instruments

# DB path (relative to repo root)
DB_RELATIVE: str = "engine/data/jarvis_trader.db"

# Output JSON path (relative to repo root)
JSON_RELATIVE: str = "scripts/data/kronos_threshold_calibration.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Return the repository root (directory containing this script's parent)."""
    return Path(__file__).resolve().parent.parent


def _db_path() -> Path:
    return _repo_root() / DB_RELATIVE


def _json_path() -> Path:
    return _repo_root() / JSON_RELATIVE


def _cutoff_utc(lookback_days: int) -> str:
    """ISO-8601 cutoff timestamp for the lookback window."""
    dt = datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _confirm_instrument_presence(
    cur: sqlite3.Cursor, instruments: list[str]
) -> list[str]:
    """
    Return the subset of instruments that appear in paper_trades, logging a
    warning for any that are missing.  Falls back to confirming presence in
    market_data_bars if paper_trades has no rows (acceptable during early paper
    phase — paper_trades only has 16 rows total as of calibration date).
    """
    cur.execute("SELECT DISTINCT symbol FROM paper_trades")
    trade_syms = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT symbol FROM market_data_bars")
    bar_syms = {r[0] for r in cur.fetchall()}

    present: list[str] = []
    for sym in instruments:
        if sym in trade_syms or sym in bar_syms:
            present.append(sym)
        else:
            print(
                f"[WARN] {sym} not found in paper_trades or market_data_bars — skipping",
                file=sys.stderr,
            )
    return present


def _load_closes(cur: sqlite3.Cursor, symbol: str, cutoff: str) -> list[float]:
    """
    Load chronologically ordered close prices for a symbol from the lookback
    window.  Excludes:
    - smoke-test rows (source='smoke_test') which use synthetic stepped prices
    - rows whose close is below ``PRICE_FLOORS[symbol]`` (corrupt TV / startup
      rows that return placeholder values like 100.5 for MES)
    """
    price_floor = PRICE_FLOORS.get(symbol, DEFAULT_PRICE_FLOOR)
    cur.execute(
        """
        SELECT close
        FROM market_data_bars
        WHERE symbol = ?
          AND interval = '1h'
          AND source != 'smoke_test'
          AND ts_utc >= ?
          AND close >= ?
        ORDER BY ts_utc ASC
        """,
        (symbol, cutoff, price_floor),
    )
    return [r[0] for r in cur.fetchall()]


def _compute_returns_bps(closes: list[float], horizon: int) -> list[float]:
    """
    Compute N-bar-ahead log returns in basis points.

    ``ret_bps[i] = log(closes[i + horizon] / closes[i]) * 10_000``

    Returns an empty list if there are fewer than ``horizon + 1`` closes.
    """
    n = len(closes)
    if n <= horizon:
        return []
    returns: list[float] = []
    for i in range(n - horizon):
        if closes[i] <= 0:
            continue  # guard against bad data
        ret = math.log(closes[i + horizon] / closes[i]) * 10_000.0
        returns.append(ret)
    return returns


def _percentile(data: list[float], p: float) -> float:
    """
    Compute the p-th percentile (0–100) of a sorted list using linear
    interpolation (equivalent to numpy.percentile default).
    """
    if not data:
        raise ValueError("empty sequence")
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100.0
    lo = int(k)
    hi = lo + 1
    if hi >= len(sorted_data):
        return float(sorted_data[-1])
    frac = k - lo
    return sorted_data[lo] + frac * (sorted_data[hi] - sorted_data[lo])


def _mean(data: list[float]) -> float:
    return sum(data) / len(data) if data else 0.0


def _std(data: list[float]) -> float:
    if len(data) < 2:
        return 0.0
    m = _mean(data)
    variance = sum((x - m) ** 2 for x in data) / (len(data) - 1)
    return math.sqrt(variance)


def _calibrate_instrument(
    cur: sqlite3.Cursor,
    symbol: str,
    cutoff: str,
    horizon: int,
    recommendation_method: str,
) -> dict[str, Any]:
    """
    Return a per-instrument calibration dict, or an ``"insufficient_data"``
    entry if there are not enough bars.
    """
    closes = _load_closes(cur, symbol, cutoff)

    if len(closes) < MIN_BARS_REQUIRED + horizon:
        return {
            "status": "insufficient_data",
            "n_closes": len(closes),
            "reason": f"need >= {MIN_BARS_REQUIRED + horizon} closes, got {len(closes)}",
        }

    returns = _compute_returns_bps(closes, horizon)

    if len(returns) < MIN_BARS_REQUIRED:
        return {
            "status": "insufficient_data",
            "n_closes": len(closes),
            "n_bars": len(returns),
            "reason": f"need >= {MIN_BARS_REQUIRED} return observations, got {len(returns)}",
        }

    abs_returns = [abs(r) for r in returns]

    pcts_signed = {
        "p10": _percentile(returns, 10),
        "p25": _percentile(returns, 25),
        "p50": _percentile(returns, 50),
        "p75": _percentile(returns, 75),
        "p90": _percentile(returns, 90),
    }
    pcts_abs = {
        "p10": _percentile(abs_returns, 10),
        "p25": _percentile(abs_returns, 25),
        "p50": _percentile(abs_returns, 50),
        "p75": _percentile(abs_returns, 75),
        "p90": _percentile(abs_returns, 90),
    }

    if recommendation_method == "p75-of-absolute":
        recommended = pcts_abs["p75"]
    else:
        raise ValueError(f"Unknown recommendation_method: {recommendation_method}")

    return {
        "status": "ok",
        "n_closes": len(closes),
        "n_bars": len(returns),
        "mean_return_bps": round(_mean(returns), 3),
        "std_return_bps": round(_std(returns), 3),
        "percentiles_signed": {k: round(v, 3) for k, v in pcts_signed.items()},
        "percentiles": {k: round(v, 3) for k, v in pcts_abs.items()},
        "recommended_threshold_bps": round(recommended, 2),
        "recommendation_method": recommendation_method,
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _format_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Kronos Threshold Calibration Report")
    lines.append("")
    lines.append(f"**Calibrated at:** {result['calibrated_at']}")
    lines.append(f"**Horizon bars (N):** {result['horizon_bars']}")
    lines.append(f"**Lookback days:** {result['lookback_days']}")
    lines.append(f"**Method:** {RECOMMENDATION_METHOD}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for sym, data in result["per_instrument"].items():
        lines.append(f"## {sym}")
        if data.get("status") == "insufficient_data":
            lines.append(f"**SKIPPED — insufficient data:** {data.get('reason', '')}")
            lines.append("")
            continue

        lines.append(f"- Bars analysed: {data['n_bars']:,}")
        lines.append(
            f"- Mean {result['horizon_bars']}-bar return: {data['mean_return_bps']:+.1f} bps"
        )
        lines.append(f"- Std dev: {data['std_return_bps']:.1f} bps")
        lines.append("")
        lines.append("**Absolute-return percentiles (bps):**")
        lines.append("")
        pcts = data["percentiles"]
        lines.append(f"| p10 | p25 | p50 | p75 | p90 |")
        lines.append(f"|-----|-----|-----|-----|-----|")
        lines.append(
            f"| {pcts['p10']:.1f} | {pcts['p25']:.1f} | {pcts['p50']:.1f} "
            f"| {pcts['p75']:.1f} | {pcts['p90']:.1f} |"
        )
        lines.append("")
        lines.append(
            f"**Recommended threshold:** {data['recommended_threshold_bps']:.1f} bps"
            f"  *(current default: 20.0 bps)*"
        )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"**Global recommendation:** {result['global_recommendation_bps']:.1f} bps"
    )
    lines.append(
        "*(median of per-instrument recommendations — prefer per-instrument values)*"
    )
    lines.append("")
    lines.append("## Notes")
    for note in result["notes"]:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## Script")
    lines.append("`scripts/calibrate_kronos_threshold.py`")
    lines.append("")
    lines.append("JSON results: `scripts/data/kronos_threshold_calibration.json`")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_calibration(
    db_path: str | Path | None = None,
    horizon: int = HORIZON_BARS,
    lookback_days: int = LOOKBACK_DAYS,
    instruments: list[str] | None = None,
) -> dict[str, Any]:
    """
    Execute the calibration and return the result dict.

    Exposed as a function (not only a ``__main__`` block) so tests can call it
    directly with a custom ``db_path`` pointing at a temp database.
    """
    if db_path is None:
        db_path = _db_path()
    if instruments is None:
        instruments = INSTRUMENTS

    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    cutoff = _cutoff_utc(lookback_days)

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        confirmed = _confirm_instrument_presence(cur, instruments)

        per_instrument: dict[str, Any] = {}
        for sym in confirmed:
            per_instrument[sym] = _calibrate_instrument(
                cur, sym, cutoff, horizon, RECOMMENDATION_METHOD
            )

    finally:
        conn.close()

    # Global recommendation: median of per-instrument recommended thresholds
    ok_thresholds = [
        v["recommended_threshold_bps"]
        for v in per_instrument.values()
        if v.get("status") == "ok"
    ]
    if ok_thresholds:
        ok_thresholds_sorted = sorted(ok_thresholds)
        mid = len(ok_thresholds_sorted) // 2
        if len(ok_thresholds_sorted) % 2 == 0:
            global_rec = (
                ok_thresholds_sorted[mid - 1] + ok_thresholds_sorted[mid]
            ) / 2.0
        else:
            global_rec = ok_thresholds_sorted[mid]
    else:
        global_rec = 20.0  # fall back to the existing default

    notes = [
        "Per-instrument thresholds are strongly preferred; instrument volatility "
        "regimes (MES/MNQ = equity index; MCL = crude oil) differ substantially.",
        "Return distributions are non-stationary across regimes. This p75-of-absolute "
        "threshold is calibrated on the full lookback sample and will underweight "
        "quiet regimes while overweighting high-vol events. Revisit after 30 days "
        "of live Kronos verdicts.",
        f"Lookback window: last {lookback_days} calendar days of 1-hour bars "
        f"(smoke-test rows excluded). Horizon N={horizon} bars.",
        "Log returns used for distribution symmetry; kronos_classifier.py uses "
        "simple returns. At small magnitudes (<100 bps) the difference is < 1 bps.",
        "MNQ absent from paper_trades as of calibration date; bar data is present "
        "and sufficient for calibration.",
    ]

    result: dict[str, Any] = {
        "calibrated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizon_bars": horizon,
        "lookback_days": lookback_days,
        "per_instrument": per_instrument,
        "global_recommendation_bps": round(global_rec, 2),
        "notes": notes,
    }
    return result


def main() -> None:
    result = run_calibration()

    # Write JSON
    json_path = _json_path()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"[OK] JSON written to {json_path}", file=sys.stderr)

    # Print markdown to stdout
    print(_format_markdown(result))


if __name__ == "__main__":
    main()
