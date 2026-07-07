#!/usr/bin/env python
"""
Verdict-history dashboard — portfolio-wide gate v2 summary

Scans engine/data/gate_v2_verdicts/ (active + archive) and produces a
human-readable summary of every WFO campaign verdict ever run, sorted
by status (PASS first), then by symbol, then by family, then by rank.

Usage (from engine/ directory):
    .venv/Scripts/python -m backtest.show_verdict_history
    .venv/Scripts/python -m backtest.show_verdict_history --include-archive
    .venv/Scripts/python -m backtest.show_verdict_history --json
    .venv/Scripts/python -m backtest.show_verdict_history --symbol MES

Filters and modes:
    --include-archive   Include verdicts in gate_v2_verdicts/archive/
    --json              Emit JSON instead of formatted table (for tooling)
    --symbol SYM        Filter to a specific symbol (e.g. MES, MGC, MNQ)
    --status STATUS     Filter to PASS or FAIL
    --expiring-soon     Only show PASS verdicts within 7 days of expiry
                        (verdict.created_at + 30 days)

Why this exists:
    Manually inspecting 25+ verdict JSONs across active+archive is error-prone.
    This is the single source of truth for "what's currently validated, what's
    parked, what's about to expire." Used by:
      - Pre-live-trading authorization checks
      - Verdict-expiry reminders (paired with cron)
      - Public README data (validation-results table)
      - Strategic-direction decisions (which families exhausted vs untested)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

engine_root = Path(__file__).parent.parent
VERDICTS_DIR = engine_root / "data" / "gate_v2_verdicts"

# 30-day verdict validity window (gate v2 ALT path policy)
VERDICT_TTL_DAYS = 30


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _load_verdict(path: Path) -> dict[str, Any] | None:
    """Load a verdict JSON, returning None on parse error or empty file."""
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return None
        # Some verdicts have raw Infinity/NaN tokens — Python json doesn't accept
        # them by default but the loader is lenient enough for our metric values.
        # If parse fails, fall through to None (caller will skip).
        return json.loads(text)
    except (json.JSONDecodeError, OSError):
        return None


def _summarize(verdict: dict[str, Any], path: Path, archived: bool) -> dict[str, Any]:
    """Extract one-row summary from a verdict JSON."""
    metrics = verdict.get("gate_v2_metrics", {})
    wfo_cfg = verdict.get("wfo_config", {})

    created = _parse_iso(verdict.get("created_at"))
    expires = (created + timedelta(days=VERDICT_TTL_DAYS)) if created else None
    now = datetime.now(tz=timezone.utc)
    days_until_expiry = (expires - now).days if expires else None

    return {
        "file": path.name,
        "archived": archived,
        "symbol": verdict.get("symbol", "?"),
        "family": verdict.get("family", "?"),
        "rank": verdict.get("rank") or verdict.get("hypothesis", "?"),
        "verdict": verdict.get("verdict", "?"),
        "passed_via": verdict.get("passed_via"),
        "core": verdict.get("core_verdict", "?"),
        "alt": verdict.get("alt_verdict", "?"),
        "pf_ci_lower": metrics.get("pf_ci_lower"),
        "p_edge": metrics.get("p_edge"),
        "mc_dd_pct": metrics.get("mc_95th_dd_pct"),
        "dsr": metrics.get("dsr"),
        "wfo": metrics.get("wfo_consistency"),
        "fixed_min": metrics.get("fixed_params_min_pf"),
        "cost": metrics.get("cost_survives_through"),
        "n_oos_trades": wfo_cfg.get("total_oos_trades"),
        "n_oos_windows": wfo_cfg.get("n_oos_windows_with_trades"),
        "created_at": created.isoformat() if created else None,
        "expires_at": expires.isoformat() if expires else None,
        "days_until_expiry": days_until_expiry,
    }


def _collect(include_archive: bool) -> list[dict[str, Any]]:
    rows = []
    if not VERDICTS_DIR.exists():
        return rows
    for path in sorted(VERDICTS_DIR.glob("*.json")):
        v = _load_verdict(path)
        if v is None:
            continue
        rows.append(_summarize(v, path, archived=False))
    if include_archive:
        archive_dir = VERDICTS_DIR / "archive"
        if archive_dir.exists():
            for path in sorted(archive_dir.glob("*.json")):
                v = _load_verdict(path)
                if v is None:
                    continue
                rows.append(_summarize(v, path, archived=True))
    return rows


def _sort_key(row: dict[str, Any]) -> tuple:
    """Sort: PASS first, then by symbol, family, rank."""
    status_priority = 0 if row["verdict"] == "PASS" else 1
    return (status_priority, row["symbol"], row["family"], str(row["rank"]))


def _format_metric(val: Any, places: int = 4) -> str:
    if val is None:
        return "  -  "
    if isinstance(val, str):
        return val
    try:
        if val != val:  # NaN check
            return "NaN"
        return f"{val:.{places}f}"
    except (TypeError, ValueError):
        return str(val)


def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No verdicts found.")
        return

    # Header
    print()
    print("=" * 120)
    print(
        f"{'Symbol':<7}{'Family':<12}{'Rank':<8}{'Verdict':<10}{'p_edge':<9}"
        f"{'pf_ci':<8}{'dsr':<7}{'mc_dd%':<8}{'wfo':<10}{'fixed_min':<10}"
        f"{'cost':<14}{'OOS':<7}{'days_left':<10}"
    )
    print("=" * 120)

    last_status = None
    for row in rows:
        # Group separator between PASS and FAIL
        if last_status is not None and last_status != row["verdict"]:
            print("-" * 120)
        last_status = row["verdict"]

        verdict_str = row["verdict"]
        if row["passed_via"]:
            verdict_str = f"{row['verdict']}-{row['passed_via']}"

        # Days-until-expiry color hint via prefix
        days_left = row["days_until_expiry"]
        if days_left is None:
            days_str = "  -  "
        elif days_left < 0:
            days_str = "EXPIRED"
        elif days_left <= 7:
            days_str = f"{days_left}d!"
        else:
            days_str = f"{days_left}d"

        archive_marker = "[A]" if row["archived"] else "   "
        symbol_str = f"{row['symbol']}{archive_marker}"

        print(
            f"{symbol_str:<7}{str(row['family']):<12}{str(row['rank']):<8}"
            f"{verdict_str:<10}{_format_metric(row['p_edge'], 3):<9}"
            f"{_format_metric(row['pf_ci_lower'], 3):<8}"
            f"{_format_metric(row['dsr'], 3):<7}"
            f"{_format_metric(row['mc_dd_pct'], 2):<8}"
            f"{str(row['wfo'] or '-'):<10}"
            f"{_format_metric(row['fixed_min'], 3):<10}"
            f"{str(row['cost'] or '-'):<14}"
            f"{str(row['n_oos_trades'] or '-'):<7}"
            f"{days_str:<10}"
        )
    print("=" * 120)

    # Summary line
    n_pass = sum(1 for r in rows if r["verdict"] == "PASS")
    n_fail = sum(1 for r in rows if r["verdict"] == "FAIL")
    n_expiring = sum(
        1
        for r in rows
        if r["verdict"] == "PASS"
        and r["days_until_expiry"] is not None
        and 0 <= r["days_until_expiry"] <= 7
    )
    n_expired = sum(
        1
        for r in rows
        if r["verdict"] == "PASS"
        and r["days_until_expiry"] is not None
        and r["days_until_expiry"] < 0
    )

    print(f"\nTotal: {len(rows)} verdicts | PASS: {n_pass} | FAIL: {n_fail}", end="")
    if n_expiring > 0:
        print(f" | EXPIRING-SOON (<=7d): {n_expiring}", end="")
    if n_expired > 0:
        print(f" | EXPIRED: {n_expired}", end="")
    print()
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--include-archive",
        action="store_true",
        help="Include verdicts in gate_v2_verdicts/archive/",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of formatted table")
    parser.add_argument("--symbol", help="Filter by symbol (e.g. MES)")
    parser.add_argument("--status", choices=["PASS", "FAIL"], help="Filter by verdict status")
    parser.add_argument(
        "--expiring-soon",
        action="store_true",
        help="Only show PASS verdicts within 7 days of expiry",
    )
    args = parser.parse_args()

    rows = _collect(include_archive=args.include_archive)

    if args.symbol:
        rows = [r for r in rows if r["symbol"] == args.symbol.upper()]
    if args.status:
        rows = [r for r in rows if r["verdict"] == args.status]
    if args.expiring_soon:
        rows = [
            r
            for r in rows
            if r["verdict"] == "PASS"
            and r["days_until_expiry"] is not None
            and 0 <= r["days_until_expiry"] <= 7
        ]

    rows.sort(key=_sort_key)

    if args.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        _print_table(rows)

    # Exit code: 0 normally, 1 if any PASS verdict expired or expiring soon
    has_warning = any(
        r["verdict"] == "PASS"
        and r["days_until_expiry"] is not None
        and r["days_until_expiry"] <= 7
        for r in rows
    )
    return 1 if has_warning else 0


if __name__ == "__main__":
    sys.exit(main())
