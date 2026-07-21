"""Price-continuity / roll-splice detector for bar caches.

WHY THIS MODULE EXISTS
----------------------
`cache_completeness.py` inspects bar TIMESTAMPS and catches holed caches. It
cannot catch a roll splice, because a splice has no time gap at all: the bars
are perfectly consecutive and only the PRICE steps.

Measured on the live cache 2026-07-21 (`MES_2025-07-24_2026-07-16_15m_cont.csv`):
the `2026-03-23 11:00` bar opens 6560.50 -- continuous with the prior 6556.50
close -- and closes 6793.00. A +236.50 (+3.607%) step that then persists. At
$5/pt that is $1,182/contract of artifact, indistinguishable from real signal to
any strategy reading the series.

Critically, `cache_completeness.inspect_cache_file` reported that same file's
`trustworthy_window` as 2026-02-26 -> 2026-07-16 -- the splice sits INSIDE the
window it certifies. The two checks are orthogonal and both are required.

WHY A REFERENCE INSTRUMENT IS REQUIRED
--------------------------------------
A large single-bar move is not itself proof of a splice; real markets gap (the
April-2025 tariff crash is a genuine >2% bar in this very cache). Magnitude
alone cannot separate the two, and neither can volume -- the splice bar carried
375 contracts against an adjacent-bar norm of 30-170, which is elevated but not
conclusive.

What DOES separate them is a roll-free reference instrument. SPY tracks ES with
no contract mechanics, so on any date the two must move together:

    2026-03-23   MES (this cache): +3.6%      SPY: -0.34%      -> SPLICE

The levels corroborate it: SPY 653.18 x ~10 ~= 6532 matches the PRE-jump MES
(6556); the POST-jump 6793 implies a 3.6% futures premium to cash, impossible
when quarterly carry runs well under 1%.

Because cadence differs (15m futures vs 1d ETF), the comparison is made on
same-DATE daily returns rather than bar-to-bar.

FAIL-CLOSED BY DESIGN
---------------------
This repo's recurring defect is detectors that report GREEN when they could not
actually evaluate -- the engine watchdog (HTTP 200 only), the readiness loop
(stamps GREEN on preflight failure), and the four docs that still describe a
deleted cache file as verified. This module therefore reports `verified=False`
whenever a flagged discontinuity could NOT be adjudicated against a reference,
and callers MUST require `continuous and verified`. Absence of evidence is
never treated as evidence of continuity.

CALIBRATION
-----------
`DEFAULT_MAX_BAR_RETURN_PCT` = 1.5. Measured on the MES 15m cache (13,214
consecutive-bar pairs): median 0.021%, p99 0.387%, p99.9 0.747%, max 3.607%
(the splice). The splice is 1.9x the next-largest move, so 1.5% flags it plus a
small number of genuine macro bars, which the reference then adjudicates. Tune
per interval -- a 1d cache legitimately moves more per bar than a 15m one.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Sequence

#: Single-bar absolute return (percent) above which a bar is a splice CANDIDATE.
#: A candidate is not a finding until the reference cross-check adjudicates it.
DEFAULT_MAX_BAR_RETURN_PCT = 1.5

#: Max |instrument_daily_return - reference_daily_return| (percentage points)
#: still considered "moved together". Beyond this the move is unexplained by the
#: broad market and is treated as an artifact.
DEFAULT_DIVERGENCE_TOLERANCE_PCT = 1.0

#: A bar pair separated by more than cadence * this factor is NOT consecutive;
#: it spans a gap and belongs to cache_completeness, not here.
_GAP_FACTOR = 1.5

VERDICT_SPLICE = "SPLICE"
VERDICT_REAL = "REAL"
VERDICT_UNVERIFIED = "UNVERIFIED"


def _read_bars(path: str | Path) -> tuple[list[datetime], list[float]]:
    """Read (timestamps, closes) from a bar CSV.

    Column ORDER varies across caches in this repo -- MES files put `timestamp`
    first, SPY files put it last -- so access is strictly by name. Indexing
    `list(row.keys())[0]` reads the open price as a date and silently yields
    nothing, which is how a cross-check can appear to "find no data" while the
    file is perfectly valid.
    """
    timestamps: list[datetime] = []
    closes: list[float] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ts_raw = row.get("timestamp") or row.get("date") or row.get("Date")
            close_raw = row.get("close") or row.get("Close")
            if not ts_raw or close_raw in (None, ""):
                continue
            timestamps.append(datetime.fromisoformat(str(ts_raw)))
            closes.append(float(close_raw))
    return timestamps, closes


def _daily_returns(
    timestamps: Sequence[datetime], closes: Sequence[float]
) -> dict[date, float]:
    """Percent change per calendar date, for intraday OR daily series.

    Both shapes appear in this repo's cache and they need different math:

    - INTRADAY (many bars/day, e.g. MES 15m): first close -> last close within
      the day.
    - DAILY (exactly one bar/day, e.g. SPY 1d): prior day's close -> this day's
      close. Applying the intraday rule to a 1-bar day yields a constant 0.0%,
      which silently makes every reference comparison look like "the market did
      not move" and turns real moves into false SPLICE findings.
    """
    per_day: dict[date, list[float]] = {}
    for ts, close in zip(timestamps, closes):
        per_day.setdefault(ts.date(), []).append(close)

    days = sorted(per_day)
    multi_bar_days = sum(1 for d in days if len(per_day[d]) > 1)
    is_daily_series = multi_bar_days < len(days) / 2 if days else False

    out: dict[date, float] = {}
    if is_daily_series:
        prev_close: Optional[float] = None
        for day in days:
            close = per_day[day][-1]
            if prev_close:
                out[day] = (close / prev_close - 1.0) * 100.0
            prev_close = close
        return out

    for day in days:
        series = per_day[day]
        if len(series) >= 2 and series[0]:
            out[day] = (series[-1] / series[0] - 1.0) * 100.0
    return out


def find_candidates(
    timestamps: Sequence[datetime],
    closes: Sequence[float],
    cadence_minutes: float,
    max_bar_return_pct: float = DEFAULT_MAX_BAR_RETURN_PCT,
) -> list[dict]:
    """Consecutive-bar moves exceeding `max_bar_return_pct`.

    Only pairs with no intervening time gap are considered. A pair straddling a
    gap is a completeness problem, not a continuity one, and double-reporting it
    here would make every weekend look like a splice.
    """
    limit_minutes = cadence_minutes * _GAP_FACTOR
    candidates: list[dict] = []
    for i in range(1, len(closes)):
        elapsed = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60.0
        if elapsed > limit_minutes:
            continue
        prev = closes[i - 1]
        if not prev:
            continue
        pct = (closes[i] / prev - 1.0) * 100.0
        if abs(pct) >= max_bar_return_pct:
            candidates.append(
                {
                    "timestamp": timestamps[i],
                    "date": timestamps[i].date(),
                    "prev_close": prev,
                    "close": closes[i],
                    "bar_return_pct": pct,
                    "verdict": VERDICT_UNVERIFIED,
                    "reference_daily_pct": None,
                    "instrument_daily_pct": None,
                    "divergence_pct": None,
                }
            )
    return candidates


def adjudicate(
    candidates: list[dict],
    instrument_daily: dict[date, float],
    reference_daily: Optional[dict[date, float]],
    tolerance_pct: float = DEFAULT_DIVERGENCE_TOLERANCE_PCT,
) -> list[dict]:
    """Classify each candidate against a roll-free reference instrument.

    A candidate stays UNVERIFIED when the reference has no bar for that date --
    the honest answer, and the one that keeps `verified` False downstream.
    """
    for cand in candidates:
        day = cand["date"]
        inst = instrument_daily.get(day)
        cand["instrument_daily_pct"] = inst
        if reference_daily is None or day not in reference_daily or inst is None:
            cand["verdict"] = VERDICT_UNVERIFIED
            continue
        ref = reference_daily[day]
        divergence = abs(inst - ref)
        cand["reference_daily_pct"] = ref
        cand["divergence_pct"] = divergence
        cand["verdict"] = VERDICT_SPLICE if divergence > tolerance_pct else VERDICT_REAL
    return candidates


def inspect_price_continuity(
    path: str | Path,
    cadence_minutes: float,
    reference_path: Optional[str | Path] = None,
    max_bar_return_pct: float = DEFAULT_MAX_BAR_RETURN_PCT,
    tolerance_pct: float = DEFAULT_DIVERGENCE_TOLERANCE_PCT,
) -> dict:
    """Inspect a bar cache for unexplained price discontinuities.

    Returns a dict with:
      continuous -- no candidate was classified SPLICE
      verified   -- every candidate was adjudicated (none left UNVERIFIED)
      trustworthy -- continuous AND verified. Gate on THIS, not on `continuous`.
    """
    timestamps, closes = _read_bars(path)
    if len(closes) < 2:
        return {
            "file": str(path),
            "n_bars": len(closes),
            "continuous": False,
            "verified": False,
            "trustworthy": False,
            "reason": "insufficient bars to evaluate continuity",
            "candidates": [],
        }

    candidates = find_candidates(
        timestamps, closes, cadence_minutes, max_bar_return_pct
    )
    reference_daily = None
    if reference_path is not None:
        ref_ts, ref_close = _read_bars(reference_path)
        if len(ref_close) >= 2:
            reference_daily = _daily_returns(ref_ts, ref_close)

    candidates = adjudicate(
        candidates, _daily_returns(timestamps, closes), reference_daily, tolerance_pct
    )

    n_splice = sum(1 for c in candidates if c["verdict"] == VERDICT_SPLICE)
    n_unverified = sum(1 for c in candidates if c["verdict"] == VERDICT_UNVERIFIED)
    continuous = n_splice == 0
    verified = n_unverified == 0

    return {
        "file": str(path),
        "n_bars": len(closes),
        "start": timestamps[0],
        "end": timestamps[-1],
        "reference_file": str(reference_path) if reference_path else None,
        "max_bar_return_pct": max_bar_return_pct,
        "n_candidates": len(candidates),
        "n_splice": n_splice,
        "n_unverified": n_unverified,
        "continuous": continuous,
        "verified": verified,
        # Fail closed: an unadjudicated candidate is NOT a pass.
        "trustworthy": continuous and verified,
        "candidates": candidates,
    }
