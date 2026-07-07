"""Bar-cache completeness / gap detector.

WHY THIS MODULE EXISTS
----------------------
`_find_latest_cache` now selects the right cache *file* fleet-wide, but a
correctly-named file can still be HOLED. The MES 5m cache carried ~8 gaps
Aug-Dec 2025 while only ~Dec-2025 -> Jun-2026 was trustworthy -- and the filename
(`MES_<start>_<end>_5m_cont.csv`) advertises a complete range regardless. A
backtest that loads a holed slice silently computes a verdict on partial data.

This module inspects the actual bar timestamps and reports, for any cache:
- every gap above the per-interval cadence, tagged (duration, missing days,
  whether it spans a weekend, whether it is "suspicious"),
- the count of suspicious gaps, the subset that imply an unexplained full
  missing weekday (`n_suspicious_full_day_gaps`), and an overall `trustworthy`
  flag,
- the largest contiguous suspicious-gap-free window (the trustworthy slice).

WHAT IS *NOT* SUSPICIOUS (every futures series has these legitimately):
- the daily ~1h CME maintenance break (a short intra-session gap),
- weekends (Fri close -> Sun/Mon open: the missing calendar days are Sat/Sun),
- exchange holidays the caller whitelists via `holiday_dates` (pass
  `US_MARKET_HOLIDAYS | US_MARKET_EARLY_CLOSES` for both full closures and
  reduced-hours early closes -- see both frozensets below).

A gap IS suspicious when it implies missing *trading* data with no benign
explanation:
- one or more full WEEKDAY calendar days are absent and not whitelisted, OR
- a within-day gap longer than `max_intraday_gap_hours` (a midday hole, not the
  maintenance break).

Deliberately calendar-light: rather than hardcode the CME holiday schedule (which
drifts), an unexplained mid-week hole is flagged and the caller may whitelist
known holidays. Conservative by design -- for a data-TRUST gate, over-reporting a
hole is the safe error. That said, `find_trustworthy_cache`'s no-required-window
selection (see below) only treats an unexplained FULL missing weekday as
disqualifying, not every reported intraday-only suspicious gap -- a single
calendar-unexplained intraday anomaly in an otherwise-huge, current cache is a
much weaker signal than an actual missing trading day, and must not make that
cache lose to a tiny, coincidentally gap-free short window (2026-07-06 fix).

CALIBRATION SCOPE (important)
-----------------------------
``max_intraday_gap_hours`` defaults to 3h, tuned for the ~23h continuous-session
intraday caches (``*_cont.csv``) the strategy factory actually consumes. For
RTH-only instruments (ETFs like SPY/DIA) the LEGITIMATE nightly gap is ~17h and
every overnight is flagged -- so ``trustworthy`` is unreliable for those and
their results are advisory until a session-aware threshold lands. The plain 1h
futures caches (``MES_*_1h.csv`` etc.) are actually near-continuous (~23h
Globex sessions, not RTH-only as previously assumed here), so this guard DOES
apply to them once ``US_MARKET_EARLY_CLOSES`` is included -- see the
2026-07-06 vwap-sharpe incident, where the missing early-close whitelist (not
an RTH mismatch) was the actual cause of false "holed" verdicts.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional, Sequence

#: Default ceiling on a within-day (no full day missing) gap before it is
#: suspicious. The CME maintenance break is ~1h; a multi-hour midday hole is not.
_DEFAULT_MAX_INTRADAY_GAP_HOURS = 3.0
#: A consecutive spacing larger than this * cadence is recorded as a gap.
_DEFAULT_GAP_THRESHOLD_FACTOR = 1.5

_INTERVAL_RE = re.compile(r"^(\d+)([mhd])$")
_WEEKEND = (5, 6)  # Saturday, Sunday (datetime.weekday)

#: CME equity-index / NYSE full-closure dates 2024-2026 (the calendar the MES /
#: ES / MNQ caches follow). Pass as `holiday_dates` so genuine data holes aren't
#: drowned out by legitimate exchange closures. Includes the 2025-01-09 Carter
#: National Day of Mourning. Early-close half-days are intentionally OMITTED --
#: see `US_MARKET_EARLY_CLOSES` below for those. Extend as years roll.
#:
#: 2026-07-06 correction: this list previously started at 2024-11-28, silently
#: missing every full-closure holiday earlier in 2024 (New Year's, MLK,
#: Presidents, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor
#: Day). That gap caused `find_trustworthy_cache` to flag the real MES 1h
#: cache's 2024-05-27 / 2024-06-19 / 2024-09-02 overnight-closure gaps as
#: "suspicious" (see cache_completeness.CACHE_README or the vwap-sharpe
#: 2026-07-06 incident) purely because the corresponding 2024 date wasn't
#: whitelisted yet -- not because the data was actually holed.
US_MARKET_HOLIDAYS = frozenset(
    date(*ymd)
    for ymd in [
        (2024, 1, 1),
        (2024, 1, 15),
        (2024, 2, 19),
        (2024, 3, 29),
        (2024, 5, 27),
        (2024, 6, 19),
        (2024, 7, 4),
        (2024, 9, 2),
        (2024, 11, 28),
        (2024, 12, 25),
        (2025, 1, 1),
        (2025, 1, 9),
        (2025, 1, 20),
        (2025, 2, 17),
        (2025, 4, 18),
        (2025, 5, 26),
        (2025, 6, 19),
        (2025, 7, 4),
        (2025, 9, 1),
        (2025, 11, 27),
        (2025, 12, 25),
        (2026, 1, 1),
        (2026, 1, 19),
        (2026, 2, 16),
        (2026, 4, 3),
        (2026, 5, 25),
        (2026, 6, 19),
        (2026, 7, 3),
        (2026, 9, 7),
        (2026, 11, 26),
        (2026, 12, 25),
    ]
)

#: CME reduced-hours ("early close") session dates 2024-2026: quarterly
#: triple-witching Fridays (3rd Friday of Mar/Jun/Sep/Dec, when the equity-index
#: futures pit closes early), the day before Independence Day, and Christmas
#: Eve. These do NOT fully close the exchange, but empirically the plain (non-
#: `_cont`) 1h futures caches carry a genuine multi-hour bar gap on these dates
#: (7-12.5h observed on real MES_*_1h.csv data 2024-2025) -- the opposite of
#: the "still produce bars, so they need no whitelist" assumption this module
#: previously documented for early closes. Pass alongside `US_MARKET_HOLIDAYS`
#: (e.g. `US_MARKET_HOLIDAYS | US_MARKET_EARLY_CLOSES`) wherever a caller wants
#: both closure classes explained away. Extend as years roll.
US_MARKET_EARLY_CLOSES = frozenset(
    date(*ymd)
    for ymd in [
        (2024, 3, 15),
        (2024, 6, 21),
        (2024, 7, 3),
        (2024, 9, 20),
        (2024, 12, 20),
        (2024, 12, 24),
        (2025, 3, 21),
        (2025, 6, 20),
        (2025, 7, 3),
        (2025, 9, 19),
        (2025, 12, 19),
        (2025, 12, 24),
        (2026, 3, 20),
        (2026, 6, 19),
        (2026, 7, 2),
        (2026, 9, 18),
        (2026, 12, 18),
        (2026, 12, 24),
    ]
)


def cadence_minutes_for_interval(interval: str) -> int:
    """Bars-per-step in minutes. '5m'->5, '15m'->15, '1h'->60, '1d'->1440."""
    m = _INTERVAL_RE.match(interval.strip().lower())
    if not m:
        raise ValueError(f"Unrecognized interval {interval!r} (expected like 5m/15m/1h/1d)")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"m": 1, "h": 60, "d": 1440}[unit]


def interval_from_filename(name: str) -> str:
    """Extract the interval token from a cache filename.

    Contract: ``<SYM>_<START>_<END>_<INTERVAL>[_cont].csv`` -- the interval is
    the underscore token matching ``\\d+[mhd]`` (e.g. 5m, 15m, 1h, 1d).
    """
    stem = Path(name).stem
    for tok in stem.split("_"):
        if _INTERVAL_RE.match(tok):
            return tok
    raise ValueError(f"No interval token (\\d+[mhd]) found in filename {name!r}")


def _coerce_dt(ts) -> datetime:
    """Best-effort coercion to a datetime (accepts pandas Timestamp / datetime)."""
    if isinstance(ts, datetime):
        return ts
    to_pydatetime = getattr(ts, "to_pydatetime", None)
    if callable(to_pydatetime):
        return to_pydatetime()
    return datetime.fromisoformat(str(ts))


def _missing_full_days(prev: datetime, nxt: datetime) -> list[date]:
    """Calendar dates STRICTLY between two timestamps (full days with no data)."""
    out: list[date] = []
    d = prev.date() + timedelta(days=1)
    end = nxt.date()
    while d < end:
        out.append(d)
        d += timedelta(days=1)
    return out


def inspect_completeness(
    timestamps: Sequence,
    interval: str,
    *,
    holiday_dates: Optional[Iterable[date]] = None,
    max_intraday_gap_hours: float = _DEFAULT_MAX_INTRADAY_GAP_HOURS,
    gap_threshold_factor: float = _DEFAULT_GAP_THRESHOLD_FACTOR,
) -> dict:
    """Inspect a sequence of bar timestamps for completeness.

    Args:
        timestamps: bar timestamps (datetime / pandas Timestamp), any order.
        interval:   '5m' | '15m' | '1h' | '1d' (drives the expected cadence).
        holiday_dates: dates to treat as expected market closures.
        max_intraday_gap_hours: within-day gap ceiling before it is suspicious.
        gap_threshold_factor: a spacing > factor*cadence is recorded as a gap.

    Returns a dict: interval, cadence_minutes, n_bars, start, end, gaps[],
    n_suspicious_gaps, trustworthy, trustworthy_window{start,end,n_bars}.
    Degenerate input (<2 bars) default-denies trust.
    """
    holidays = set(holiday_dates or ())
    cadence = cadence_minutes_for_interval(interval)
    ts = sorted({_coerce_dt(t) for t in timestamps})
    n = len(ts)

    base = {
        "interval": interval,
        "cadence_minutes": cadence,
        "n_bars": n,
        "start": ts[0] if ts else None,
        "end": ts[-1] if ts else None,
    }

    if n < 2:
        base.update(
            gaps=[],
            n_suspicious_gaps=0,
            n_suspicious_full_day_gaps=0,
            trustworthy=False,  # cannot validate a 0/1-bar series
            trustworthy_window={
                "start": ts[0] if ts else None,
                "end": ts[0] if ts else None,
                "n_bars": n,
            },
        )
        return base

    threshold_min = gap_threshold_factor * cadence
    gaps: list[dict] = []
    # index boundaries (in `ts`) where a SUSPICIOUS gap splits the series.
    suspicious_breaks: list[int] = []
    # count of suspicious gaps with >=1 full calendar day missing (unexplained
    # weekday) -- a strictly worse signal than a long-but-same-day intraday
    # gap. See `n_suspicious_full_day_gaps` below.
    n_full_day_suspicious = 0

    for i in range(1, n):
        prev, cur = ts[i - 1], ts[i]
        delta = cur - prev
        delta_min = delta.total_seconds() / 60.0
        if delta_min <= threshold_min:
            continue  # normal cadence, no gap

        missing = _missing_full_days(prev, cur)
        spans_weekend = any(d.weekday() in _WEEKEND for d in missing) or (
            # endpoints can straddle a weekend with no full day between
            prev.weekday() in _WEEKEND
            or cur.weekday() in _WEEKEND
        )
        unexplained_days = [d for d in missing if d.weekday() < 5 and d not in holidays]
        # A holiday CLOSE shows as a long intra/overnight gap with no full day
        # strictly between (e.g. Dec 24 18:10 -> Dec 25 23:00), so it isn't
        # caught by the missing-weekday test -- key on either endpoint's date.
        holiday_adjacent = (prev.date() in holidays) or (cur.date() in holidays)

        if unexplained_days:
            suspicious = True  # full weekday(s) of trading data absent, unexplained
        elif missing:
            suspicious = False  # all missing days are weekend / whitelisted holiday
        else:
            # pure intra/overnight gap: suspicious only if long AND not a holiday close
            long_hole = (delta.total_seconds() / 3600.0) > max_intraday_gap_hours
            suspicious = bool(long_hole and not holiday_adjacent)

        gaps.append(
            {
                "start": prev,
                "end": cur,
                "duration_hours": round(delta.total_seconds() / 3600.0, 3),
                "missing_bars_est": int(round(delta_min / cadence)) - 1,
                "missing_days": [d.isoformat() for d in missing],
                "spans_weekend": bool(spans_weekend),
                "suspicious": bool(suspicious),
            }
        )
        if suspicious:
            suspicious_breaks.append(i)
            if missing:  # unexplained full weekday(s), not merely a long intraday gap
                n_full_day_suspicious += 1

    # Largest contiguous suspicious-gap-free window (by bar count).
    seg_starts = [0] + suspicious_breaks
    seg_ends = suspicious_breaks + [n]
    best = {"start": ts[0], "end": ts[-1], "n_bars": n}
    best_count = -1
    for s, e in zip(seg_starts, seg_ends, strict=True):  # equal length by construction
        count = e - s
        if count > best_count:
            best_count = count
            best = {"start": ts[s], "end": ts[e - 1], "n_bars": count}

    n_suspicious = len(suspicious_breaks)
    base.update(
        gaps=gaps,
        n_suspicious_gaps=n_suspicious,
        n_suspicious_full_day_gaps=n_full_day_suspicious,
        trustworthy=(n_suspicious == 0),
        trustworthy_window=best,
    )
    return base


def inspect_cache_file(
    path,
    *,
    interval: Optional[str] = None,
    holiday_dates: Optional[Iterable[date]] = None,
    timestamp_col: str = "timestamp",
    **kwargs,
) -> dict:
    """Load a cache CSV and report completeness.

    Interval is inferred from the filename unless given explicitly. The result
    dict additionally carries ``file`` (the path inspected).
    """
    import pandas as pd

    p = Path(path)
    iv = interval or interval_from_filename(p.name)
    df = pd.read_csv(p)
    df.columns = [c.lower() for c in df.columns]
    col = (
        timestamp_col
        if timestamp_col in df.columns
        else ("datetime" if "datetime" in df.columns else df.columns[0])
    )
    stamps = pd.to_datetime(df[col], utc=True)
    result = inspect_completeness(list(stamps), iv, holiday_dates=holiday_dates, **kwargs)
    result["file"] = str(p)
    return result


def scan_directory(
    cache_dir,
    *,
    pattern: str = "*.csv",
    holiday_dates: Optional[Iterable[date]] = US_MARKET_HOLIDAYS,
    intraday_only: bool = True,
    **kwargs,
) -> list[dict]:
    """Inspect every cache file in a directory; return summaries worst-first.

    Files whose name carries no interval token are skipped (e.g. ``DIA_daily.csv``).
    With ``intraday_only`` (default) only sub-daily caches (5m/15m/30m/1h) are
    scanned -- daily caches legitimately skip every weekend/holiday and aren't the
    hole-risk this guard targets. Each summary is the ``inspect_cache_file`` dict
    trimmed to the headline fields; the list sorts untrustworthy caches first.
    """
    d = Path(cache_dir)
    out: list[dict] = []
    for p in sorted(d.glob(pattern)):
        try:
            iv = interval_from_filename(p.name)
        except ValueError:
            continue  # no interval token -> not a contract-named bar cache
        if intraday_only and cadence_minutes_for_interval(iv) >= 1440:
            continue
        try:
            r = inspect_cache_file(p, holiday_dates=holiday_dates, **kwargs)
        except Exception as exc:  # unreadable / malformed -> surface, don't crash
            out.append({"file": str(p), "error": str(exc), "trustworthy": False})
            continue
        out.append(
            {
                "file": p.name,
                "interval": r["interval"],
                "n_bars": r["n_bars"],
                "start": r["start"],
                "end": r["end"],
                "n_suspicious_gaps": r["n_suspicious_gaps"],
                "trustworthy": r["trustworthy"],
                "trustworthy_window": r["trustworthy_window"],
            }
        )
    out.sort(key=lambda s: (s.get("trustworthy", False), -s.get("n_suspicious_gaps", 0)))
    return out


def find_trustworthy_cache(
    data_dir,
    prefix: str,
    suffix: str = "_5m_cont.csv",
    *,
    required_start: Optional[date] = None,
    required_end: Optional[date] = None,
    holiday_dates: Optional[Iterable[date]] = US_MARKET_HOLIDAYS | US_MARKET_EARLY_CLOSES,
    **kwargs,
) -> dict:
    """Completeness-aware companion to ``_find_latest_cache``.

    ``_find_latest_cache`` picks the latest END date -- which does NOT imply the
    file is complete: a holed late-end cache can beat a clean earlier one. This
    picker inspects completeness and chooses:

    * with a required [start, end] window: the latest-end cache whose
      ``trustworthy_window`` COVERS that window; if none covers, falls back to the
      latest-end file with ``fallback=True`` so the caller can warn/refuse;
    * with no window: the latest-end cache with zero suspicious gaps that imply an
      actual missing weekday (``n_suspicious_full_day_gaps == 0``); if none
      qualifies, the latest-end file with ``fallback=True``.

    2026-07-06 fix: the no-window branch previously required ``n_suspicious_gaps
    == 0`` (the WHOLE file perfectly gap-free). That let one isolated, calendar-
    unexplained intraday gap (a stray vendor hiccup with no full day missing) in
    an otherwise years-long, current cache lose to a tiny, coincidentally
    landmine-free short window -- exactly the 2026-07-06 vwap-sharpe incident
    (12,612-bar current MES cache rejected in favor of a 964-bar 2-month one).
    The new criterion only disqualifies a cache for an unexplained FULL missing
    weekday (a real hole); a lone intraday-only anomaly is reported but no
    longer disqualifying. See ``test_find_latest_cache_complete.py`` for both
    the repro and the guardrail that a genuine missing-weekday hole still loses.

    Returns a dict: ``path``, ``fallback`` (bool), ``reason``, ``trustworthy_window``,
    ``n_suspicious_gaps``, ``n_suspicious_full_day_gaps``, ``latest_end_path``
    (what ``_find_latest_cache`` would have returned). Purely advisory -- it does
    NOT mutate ``_find_latest_cache``; callers opt in. Raises FileNotFoundError if
    no file matches the glob.
    """
    d = Path(data_dir)
    candidates = sorted(d.glob(f"{prefix}_*{suffix}"))
    if not candidates:
        raise FileNotFoundError(
            f"No {prefix}{suffix} cache in {d} (looked for '{prefix}_*{suffix}')"
        )

    def _end_key(p: Path) -> str:
        parts = p.stem.split("_")
        return parts[2] if len(parts) >= 3 else ""

    candidates.sort(key=_end_key, reverse=True)  # latest end-date first
    latest = candidates[0]
    reports: list[tuple[Path, Optional[dict]]] = []
    for p in candidates:
        try:
            reports.append((p, inspect_cache_file(p, holiday_dates=holiday_dates, **kwargs)))
        except Exception:
            reports.append((p, None))
    latest_report = reports[0][1]

    def _result(path, fallback, reason, rep):
        return {
            "path": str(path),
            "fallback": bool(fallback),  # True only when NO trustworthy cache was found
            "chose_latest_end": str(path) == str(latest),
            "reason": reason,
            "trustworthy_window": rep["trustworthy_window"] if rep else None,
            "n_suspicious_gaps": rep["n_suspicious_gaps"] if rep else None,
            "n_suspicious_full_day_gaps": rep["n_suspicious_full_day_gaps"] if rep else None,
            "latest_end_path": str(latest),
        }

    if required_start or required_end:
        for p, rep in reports:  # latest-end first
            if rep is None:
                continue
            tw = rep["trustworthy_window"]
            if tw["start"] is None or tw["end"] is None:
                continue
            if required_start and tw["start"].date() > required_start:
                continue
            if required_end and tw["end"].date() < required_end:
                continue
            reason = (
                "latest end-date covers required window"
                if p == latest
                else "earlier end-date covers required window (latest end-date is holed over it)"
            )
            return _result(p, False, reason, rep)
        return _result(
            latest,
            True,
            "NO cache trustworthy over required window; fell back to latest end-date",
            latest_report,
        )

    # No window: the latest-end cache with no unexplained missing weekday. A
    # cache can still carry a reported (but non-disqualifying) intraday-only
    # suspicious gap -- see the module-level docstring's 2026-07-06 fix note.
    for p, rep in reports:
        if rep is not None and rep["n_suspicious_full_day_gaps"] == 0:
            if p == latest:
                reason = "latest end-date has no unexplained missing weekday"
            elif rep["n_suspicious_gaps"] == 0:
                reason = "earlier end-date is fully trustworthy (latest end-date is holed)"
            else:
                reason = (
                    "earlier end-date has no unexplained missing weekday "
                    "(latest end-date does)"
                )
            return _result(p, False, reason, rep)
    return _result(
        latest,
        True,
        "no fully-trustworthy cache; latest end-date has suspicious gaps",
        latest_report,
    )


def _main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Scan bar caches for completeness holes.")
    ap.add_argument("path", help="a cache .csv file OR a directory of caches")
    ap.add_argument(
        "--all-intervals",
        action="store_true",
        help="include daily caches when scanning a directory",
    )
    ap.add_argument(
        "--no-holidays",
        action="store_true",
        help="do not apply the built-in US_MARKET_HOLIDAYS whitelist",
    )
    args = ap.parse_args(argv)

    holidays = None if args.no_holidays else US_MARKET_HOLIDAYS
    p = Path(args.path)
    if p.is_dir():
        rows = scan_directory(p, holiday_dates=holidays, intraday_only=not args.all_intervals)
        holed = [r for r in rows if not r.get("trustworthy")]
        print(f"Scanned {len(rows)} caches in {p}  |  {len(holed)} not trustworthy\n")
        for r in rows:
            flag = "OK " if r.get("trustworthy") else "HOLE"
            if "error" in r:
                print(f"  [{flag}] {r['file']}: ERROR {r['error']}")
                continue
            tw = r["trustworthy_window"]
            print(
                f"  [{flag}] {r['file']:<46} {r['interval']:>3}  "
                f"sus={r['n_suspicious_gaps']:<3} "
                f"trust_window={str(tw['start'])[:10]}->{str(tw['end'])[:10]} "
                f"({tw['n_bars']} bars)"
            )
        return 1 if holed else 0

    r = inspect_cache_file(p, holiday_dates=holidays)
    print(f"{r['file']}")
    print(
        f"  interval={r['interval']} n_bars={r['n_bars']} "
        f"range={str(r['start'])[:16]}->{str(r['end'])[:16]}"
    )
    print(f"  suspicious_gaps={r['n_suspicious_gaps']} trustworthy={r['trustworthy']}")
    for g in sorted((g for g in r["gaps"] if g["suspicious"]), key=lambda g: -g["duration_hours"]):
        print(
            f"    HOLE {str(g['start'])[:16]} -> {str(g['end'])[:16]} "
            f"{g['duration_hours']:.1f}h missing={g['missing_days'][:8]}"
        )
    return 1 if not r["trustworthy"] else 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(_main())
