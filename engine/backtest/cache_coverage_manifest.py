"""
JARVIS TRADER -- backtest cache coverage manifest.

Phase 2 of the self-improvement plan (end the WFO starvation) starts with
*measuring* the starvation precisely. The #1 structural limiter on validating
strategies is data depth: the gate-v2 walk-forward needs >= 30 OOS trades, and
shallow caches starve it regardless of edge. This module produces a per
(symbol, interval) coverage report -- how deep and how fresh the data the engine
would actually use is, versus the IBKR pull target -- so the gateway backfill
(which needs a live IB Gateway, Amo-gated) can be targeted at exactly the
symbols that are SHALLOW, and a scheduled refresh can alert when an active
symbol's cache goes STALE.

Pure filesystem + line-count: no IB Gateway, no pandas-heavy parse, no network.
Safe to run any time, and cheap enough for a scheduled staleness check.

Single source of truth: the cache filename contract, the per-interval depth
targets, the canonical cache directory, and the active-symbol set are all
imported from ``export_ibkr_history`` and ``_gate_v2_helpers`` so this report
can never silently diverge from how the engine reads and writes caches.

Usage:
    python -m backtest.cache_coverage_manifest                 # table + write JSON
    python -m backtest.cache_coverage_manifest --json-only     # JSON to stdout
    python -m backtest.cache_coverage_manifest --alert-only    # only SHALLOW/STALE/MISSING
    python -m backtest.cache_coverage_manifest --cache-dir <p> # report a specific cache dir
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Single source of truth -- the contract, depth targets, cache dir, symbol spec.
from backtest.export_ibkr_history import (
    CACHE_DIR,
    INTERVAL_DEPTH_DAYS,
    SYMBOL_TO_IB_SPEC,
)

# Capturing form of export_ibkr_history.CACHE_FILENAME_CONTRACT
# (^<SYMBOL>_<YYYY-MM-DD>_<YYYY-MM-DD>_<INTERVAL>.csv$).
_CACHE_PARSE_RE = re.compile(
    r"^(?P<symbol>[A-Z][A-Z0-9]{1,3})_"
    r"(?P<start>\d{4}-\d{2}-\d{2})_"
    r"(?P<end>\d{4}-\d{2}-\d{2})_"
    r"(?P<interval>\d{1,2}[mhd])\.csv$"
)

# A cache for an actively-pulled symbol is STALE if its end-date is older than
# this many calendar days (covers a normal weekend + a holiday).
DEFAULT_STALENESS_DAYS = 4
# A cache is SHALLOW if its span covers less than this fraction of the depth
# target -- i.e. it cannot reach the intended history depth for WFO.
DEFAULT_SHALLOW_FRACTION = 0.90

# Core intervals every active (export-target) symbol should have, so a fully
# missing one surfaces as MISSING rather than silently absent.
CORE_INTERVALS = ("1h", "1d")


def _parse_cache_name(name: str) -> dict | None:
    """Parse a contract-conforming cache filename into its fields, or None."""
    m = _CACHE_PARSE_RE.match(name)
    if not m:
        return None
    return {
        "symbol": m.group("symbol"),
        "start": m.group("start"),
        "end": m.group("end"),
        "interval": m.group("interval"),
    }


def _count_bars(path: Path) -> int | None:
    """Approximate bar count = data lines (lines minus a header), or None."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            total = sum(1 for _ in fh)
        return max(0, total - 1)  # subtract header row
    except OSError:
        return None


def _iso_to_date(s: str) -> date:
    return date.fromisoformat(s)


def build_coverage_manifest(
    cache_dir: Path | str = CACHE_DIR,
    *,
    now: datetime | None = None,
    staleness_days: int = DEFAULT_STALENESS_DAYS,
    shallow_fraction: float = DEFAULT_SHALLOW_FRACTION,
    count_bars: bool = True,
) -> dict:
    """Build the per (symbol, interval) cache coverage manifest.

    Args:
        cache_dir: directory of cache CSVs (defaults to the engine cache dir).
        now: reference instant for staleness (defaults to UTC now); inject for tests.
        staleness_days: end-date older than this (for active symbols) -> STALE.
        shallow_fraction: span < this fraction of the depth target -> SHALLOW.
        count_bars: read each selected file to count data rows (cheap line count).

    Returns:
        A JSON-serialisable dict: generated_at, cache_dir, thresholds, summary,
        alerts (active symbols only), and entries (one per symbol/interval pair).
    """
    cache_dir = Path(cache_dir)
    ref = now or datetime.now(tz=timezone.utc)
    ref_date = ref.date()
    active = set(SYMBOL_TO_IB_SPEC)

    # Discover every contract-conforming cache, grouped by (symbol, interval).
    by_key: dict[tuple[str, str], list[dict]] = {}
    if cache_dir.is_dir():
        for p in sorted(cache_dir.glob("*.csv")):
            parsed = _parse_cache_name(p.name)
            if parsed is None:
                continue  # off-contract / unrelated CSV -> ignored (not a bar cache)
            parsed["path"] = p
            by_key.setdefault((parsed["symbol"], parsed["interval"]), []).append(parsed)

    # The set of pairs to report: everything discovered, plus the core intervals
    # for every active symbol (so a missing core cache is flagged, not hidden).
    keys: set[tuple[str, str]] = set(by_key)
    for sym in active:
        for interval in CORE_INTERVALS:
            keys.add((sym, interval))

    entries: list[dict] = []
    for sym, interval in sorted(keys):
        is_active = sym in active
        target_days = INTERVAL_DEPTH_DAYS.get(interval)
        caches = by_key.get((sym, interval), [])

        if not caches:
            entries.append(
                {
                    "symbol": sym,
                    "interval": interval,
                    "status": "MISSING",
                    "flags": ["missing"],
                    "is_active": is_active,
                    "selected_file": None,
                    "start": None,
                    "end": None,
                    "span_days": None,
                    "span_months": None,
                    "n_bars": None,
                    "target_days": target_days,
                    "coverage_pct": 0.0 if target_days else None,
                    "stale_days": None,
                    "n_caches": 0,
                    "earliest_start_available": None,
                }
            )
            continue

        # The engine reads the freshest end-date cache (mirrors
        # _gate_v2_helpers._find_latest_cache: lex-max on the end-date segment).
        selected = max(caches, key=lambda c: c["end"])
        start_d = _iso_to_date(selected["start"])
        end_d = _iso_to_date(selected["end"])
        span_days = (end_d - start_d).days
        span_months = round(span_days / 30.44, 1)
        stale_days = (ref_date - end_d).days
        earliest_start = min(c["start"] for c in caches)
        n_bars = _count_bars(selected["path"]) if count_bars else None

        coverage_pct = (
            round(100.0 * span_days / target_days, 1) if target_days else None
        )

        flags: list[str] = []
        if target_days and span_days < shallow_fraction * target_days:
            flags.append("shallow")
        # Staleness is only an alert for actively-pulled symbols; legacy caches
        # (ES/GC/CL etc.) are not refreshed and "stale" is expected for them.
        if is_active and stale_days > staleness_days:
            flags.append("stale")

        if not flags:
            status = "OK"
        elif "stale" in flags and "shallow" in flags:
            status = "STALE+SHALLOW"
        elif "stale" in flags:
            status = "STALE"
        else:
            status = "SHALLOW"

        entries.append(
            {
                "symbol": sym,
                "interval": interval,
                "status": status,
                "flags": flags,
                "is_active": is_active,
                "selected_file": selected["path"].name,
                "start": selected["start"],
                "end": selected["end"],
                "span_days": span_days,
                "span_months": span_months,
                "n_bars": n_bars,
                "target_days": target_days,
                "coverage_pct": coverage_pct,
                "stale_days": stale_days,
                "n_caches": len(caches),
                "earliest_start_available": earliest_start,
            }
        )

    summary = {
        "total": len(entries),
        "ok": sum(1 for e in entries if e["status"] == "OK"),
        "shallow": sum(1 for e in entries if "shallow" in e["flags"]),
        "stale": sum(1 for e in entries if "stale" in e["flags"]),
        "missing": sum(1 for e in entries if e["status"] == "MISSING"),
    }

    # Alerts: only for active (export-target) symbols -- the ones we intend to
    # keep deep and fresh. Avoids noise from legacy/alt caches.
    alerts: list[str] = []
    for e in entries:
        if not e["is_active"] or e["status"] == "OK":
            continue
        if e["status"] == "MISSING":
            alerts.append(f"{e['symbol']} {e['interval']}: MISSING (no cache on disk)")
        else:
            alerts.append(
                f"{e['symbol']} {e['interval']}: {e['status']} -- "
                f"{e['span_months']}mo span ({e['coverage_pct']}% of target), "
                f"end {e['end']} ({e['stale_days']}d old)"
            )

    return {
        "generated_at": ref.isoformat(),
        "cache_dir": str(cache_dir),
        "thresholds": {
            "staleness_days": staleness_days,
            "shallow_fraction": shallow_fraction,
        },
        "summary": summary,
        "alerts": alerts,
        "entries": entries,
    }


def _format_table(manifest: dict, alert_only: bool = False) -> str:
    """Render a human-readable fixed-width table of the manifest entries."""
    rows = manifest["entries"]
    if alert_only:
        rows = [e for e in rows if e["status"] != "OK"]

    header = (
        f"{'SYMBOL':<7}{'INT':<5}{'STATUS':<14}{'SPAN':>8}{'COV%':>7}"
        f"{'BARS':>9}{'END':>13}{'STALE':>7}  FILE"
    )
    lines = [header, "-" * len(header)]
    for e in rows:
        span = f"{e['span_months']}mo" if e["span_months"] is not None else "-"
        cov = f"{e['coverage_pct']}" if e["coverage_pct"] is not None else "-"
        bars = f"{e['n_bars']}" if e["n_bars"] is not None else "-"
        end = e["end"] or "-"
        stale = f"{e['stale_days']}" if e["stale_days"] is not None else "-"
        f = e["selected_file"] or "(none)"
        lines.append(
            f"{e['symbol']:<7}{e['interval']:<5}{e['status']:<14}{span:>8}{cov:>7}"
            f"{bars:>9}{end:>13}{stale:>7}  {f}"
        )

    s = manifest["summary"]
    lines.append("")
    lines.append(
        f"Summary: {s['total']} pairs | OK {s['ok']} | "
        f"SHALLOW {s['shallow']} | STALE {s['stale']} | MISSING {s['missing']}"
    )
    if manifest["alerts"]:
        lines.append("")
        lines.append("ALERTS (active symbols needing a deeper/fresher pull):")
        lines.extend(f"  - {a}" for a in manifest["alerts"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest cache coverage manifest")
    parser.add_argument(
        "--cache-dir", default=str(CACHE_DIR), help="cache directory to scan"
    )
    parser.add_argument(
        "--json-only", action="store_true", help="emit JSON to stdout, no table"
    )
    parser.add_argument(
        "--alert-only",
        action="store_true",
        help="table: only rows that are not OK",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="write the JSON manifest to this path "
        "(default: <engine>/data/cache_coverage_manifest.json; '-' to skip)",
    )
    parser.add_argument(
        "--no-count", action="store_true", help="skip bar counting (faster)"
    )
    parser.add_argument(
        "--staleness-days", type=int, default=DEFAULT_STALENESS_DAYS
    )
    args = parser.parse_args(argv)

    manifest = build_coverage_manifest(
        args.cache_dir,
        staleness_days=args.staleness_days,
        count_bars=not args.no_count,
    )

    if args.json_only:
        print(json.dumps(manifest, indent=2))
        return 0

    # Resolve the JSON output path (data/ next to the cache dir's engine root).
    if args.out == "-":
        out_path = None
    elif args.out:
        out_path = Path(args.out)
    else:
        out_path = CACHE_DIR.parent.parent / "data" / "cache_coverage_manifest.json"

    if out_path is not None:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"WAR: could not write manifest JSON to {out_path}: {exc}",
                  file=sys.stderr)
            out_path = None

    print(_format_table(manifest, alert_only=args.alert_only))
    if out_path is not None:
        print(f"\nManifest JSON written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
