"""Strategy portfolio scoreboard — auto-generated from gate_v2_verdicts/*.json.

Reads all verdict JSON files from ``engine/data/gate_v2_verdicts/``, formats
them into a ranked markdown table, and writes to ``engine/data/SCOREBOARD.md``.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/scoreboard.py
    .venv/Scripts/python backtest/scoreboard.py --no-write

Columns: Symbol | Family | Rank | Verdict | pf_ci_lower | p_edge | mc_dd% | dsr | fixed_min_pf | refresh_date
Grouping: by symbol, then by family, then by rank (ascending).
Verdict display: PASS (core) | PASS (alt) | FAIL | NO_TRADE (stale/missing)

Stale threshold: VERDICT_TTL_DAYS = 30 (matches live_readiness.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

engine_root = Path(__file__).parent.parent
VERDICTS_DIR = engine_root / "data" / "gate_v2_verdicts"
SCOREBOARD_PATH = engine_root / "data" / "SCOREBOARD.md"

VERDICT_TTL_DAYS = 30
NOW = datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _load_verdicts() -> list[dict]:
    """Load all verdict JSON files; skip archive subdirectory."""
    rows = []
    if not VERDICTS_DIR.exists():
        return rows
    for path in sorted(VERDICTS_DIR.glob("*.json")):
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                continue
            v = json.loads(text)
            v["__file"] = path.name
            v["__path"] = path
            rows.append(v)
        except (json.JSONDecodeError, OSError):
            continue
    return rows


def _verdict_display(v: dict) -> str:
    """Human-readable verdict cell, including stale marker."""
    created = _parse_iso(v.get("created_at"))
    if created and (NOW - created).days >= VERDICT_TTL_DAYS:
        return "NO_TRADE (stale)"

    verdict = v.get("verdict", "?")
    passed_via = v.get("passed_via")

    if verdict == "PASS" and passed_via == "core":
        return "PASS (core)"
    if verdict == "PASS" and passed_via == "alt":
        return "PASS (alt)"
    if verdict == "PASS":
        return "PASS"
    if verdict == "FAIL":
        return "FAIL"
    return verdict or "?"


def _days_since(ts: str | None) -> str:
    dt = _parse_iso(ts)
    if not dt:
        return "?"
    delta = (NOW - dt).days
    if delta == 0:
        return "today"
    return f"{delta}d ago"


def _metric(v: dict, key: str, fmt: str = ".4f") -> str:
    metrics = v.get("gate_v2_metrics", {})
    val = metrics.get(key)
    if val is None:
        return "—"
    try:
        return format(float(val), fmt)
    except (ValueError, TypeError):
        return str(val)


def _wfo(v: dict) -> str:
    metrics = v.get("gate_v2_metrics", {})
    return str(metrics.get("wfo_consistency", "—"))


# ---------------------------------------------------------------------------
# Scoreboard build
# ---------------------------------------------------------------------------


def build_scoreboard(verdicts: list[dict]) -> str:
    """Build the markdown scoreboard string."""
    lines: list[str] = []
    lines.append("# Strategy Portfolio Scoreboard")
    lines.append("")
    lines.append(
        f"*Auto-generated {NOW.strftime('%Y-%m-%d %H:%M')} UTC from "
        f"`engine/data/gate_v2_verdicts/` ({len(verdicts)} verdict files)*"
    )
    lines.append("")
    lines.append(
        f"Stale threshold: {VERDICT_TTL_DAYS} days. " f"Source: `engine/backtest/scoreboard.py`."
    )
    lines.append("")

    # Sort: symbol asc, family asc, rank asc
    # rank may be int or string (older verdict files use hypothesis names)
    def _sort_key(v: dict) -> tuple:
        rank_raw = v.get("rank", 99)
        try:
            rank_sort = int(rank_raw)
        except (ValueError, TypeError):
            rank_sort = 99
        return (
            str(v.get("symbol", "")),
            str(v.get("family", "")),
            rank_sort,
        )

    sorted_verdicts = sorted(verdicts, key=_sort_key)

    # Group by symbol for section headers
    by_symbol: dict[str, list[dict]] = {}
    for v in sorted_verdicts:
        sym = v.get("symbol", "?")
        by_symbol.setdefault(sym, []).append(v)

    # Table header
    header = (
        "| Symbol | Family | Rank | Verdict | pf_ci_lower | p_edge | mc_dd% | dsr | "
        "wfo | fixed_min_pf | refresh |"
    )
    divider = (
        "|--------|--------|------|---------|-------------|--------|--------|-----|"
        "-----|-------------|---------|"
    )

    lines.append(header)
    lines.append(divider)

    for sym, sym_verdicts in sorted(by_symbol.items()):
        for v in sym_verdicts:
            verdict_str = _verdict_display(v)
            family = v.get("family", "?")
            rank = str(v.get("rank", "?"))
            pf_ci = _metric(v, "pf_ci_lower")
            p_edge = _metric(v, "p_edge")
            mc_dd = _metric(v, "mc_95th_dd_pct", ".4f")
            dsr = _metric(v, "dsr", ".4f")
            wfo = _wfo(v)
            fixed_min = _metric(v, "fixed_params_min_pf", ".4f")
            refresh = _days_since(v.get("created_at"))

            lines.append(
                f"| {sym} | {family} | {rank} | {verdict_str} | {pf_ci} | "
                f"{p_edge} | {mc_dd} | {dsr} | {wfo} | {fixed_min} | {refresh} |"
            )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")

    # Summary counts
    pass_count = sum(1 for v in verdicts if v.get("verdict") == "PASS")
    fail_count = sum(1 for v in verdicts if v.get("verdict") == "FAIL")
    stale_count = sum(
        1
        for v in verdicts
        if v.get("verdict") == "PASS"
        and _parse_iso(v.get("created_at"))
        and (NOW - _parse_iso(v.get("created_at"))).days >= VERDICT_TTL_DAYS  # type: ignore[operator]
    )

    pass_active = pass_count - stale_count
    lines.append(f"- **PASS (active):** {pass_active}")
    lines.append(f"- **PASS (stale):** {stale_count}")
    lines.append(f"- **FAIL:** {fail_count}")
    lines.append(f"- **Total strategies evaluated:** {len(verdicts)}")
    lines.append("")

    # Next refresh due (soonest PASS verdict expiry)
    pass_verdicts = [
        v for v in verdicts if v.get("verdict") == "PASS" and _parse_iso(v.get("created_at"))
    ]
    if pass_verdicts:

        def _expiry(v: dict) -> datetime:
            created = _parse_iso(v.get("created_at"))
            return created + timedelta(days=VERDICT_TTL_DAYS)  # type: ignore[operator]

        soonest = min(pass_verdicts, key=_expiry)
        soonest_expiry = _expiry(soonest)
        days_remaining = (soonest_expiry - NOW).days
        lines.append(
            f"**Next refresh due:** `{soonest.get('__file', '?')}` "
            f"expires {soonest_expiry.strftime('%Y-%m-%d')} "
            f"({days_remaining}d remaining)"
        )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print to stdout without writing SCOREBOARD.md",
    )
    args = parser.parse_args()

    verdicts = _load_verdicts()
    if not verdicts:
        print(f"[scoreboard] No verdict JSON files found in {VERDICTS_DIR}", file=sys.stderr)
        print("[scoreboard] Run a WFO runner first (e.g. run_mes_trend_rank11.py)", file=sys.stderr)
        return 1

    scoreboard = build_scoreboard(verdicts)

    if args.no_write:
        print(scoreboard)
        return 0

    SCOREBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCOREBOARD_PATH.write_text(scoreboard, encoding="utf-8")
    print(f"[scoreboard] Written to {SCOREBOARD_PATH}")
    print(
        f"[scoreboard] {len(verdicts)} strategies | "
        f"{sum(1 for v in verdicts if v.get('verdict') == 'PASS')} PASS | "
        f"{sum(1 for v in verdicts if v.get('verdict') == 'FAIL')} FAIL"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
