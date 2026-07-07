"""
Verdict metric journal tracker — P2-8.

Reads all gate_v2 verdict JSON files (live + archive) and appends new rows
to engine/data/gate_v2_verdicts/_journal.csv.  Designed to be called after
each WFO refresh to track metric drift over time.

Columns:
    date          — ISO date the verdict was created
    symbol        — MES / MGC / MCL / etc.
    family        — trend / orb / etc.
    rank          — 1, 4, 11, etc.
    verdict       — PASS / FAIL
    passed_via    — core / alt / None
    pf_ci_lower   — bootstrap 95% CI lower bound on PF
    p_edge        — fraction of bootstrap draws with PF > 1
    mc_dd_pct     — Monte Carlo 95th-pctile max drawdown %
    dsr           — deflated Sharpe ratio
    wfo           — STRONG / MODERATE / WEAK / OVERFIT / etc.
    fixed_min_pf  — minimum PF across all fixed-param combos
    source_file   — basename of the verdict JSON

Usage:
    cd engine
    .venv/Scripts/python -m backtest.track_verdict_journal

    # Add --include-archive to also journal archived verdicts:
    .venv/Scripts/python -m backtest.track_verdict_journal --include-archive

    # Preview without writing (dry-run):
    .venv/Scripts/python -m backtest.track_verdict_journal --dry-run

    # Print the journal table:
    .venv/Scripts/python -m backtest.track_verdict_journal --report
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

engine_root = Path(__file__).parent.parent
VERDICTS_DIR = engine_root / "data" / "gate_v2_verdicts"
JOURNAL_PATH = VERDICTS_DIR / "_journal.csv"

_COLUMNS = [
    "date",
    "symbol",
    "family",
    "rank",
    "verdict",
    "passed_via",
    "pf_ci_lower",
    "p_edge",
    "mc_dd_pct",
    "dsr",
    "wfo",
    "fixed_min_pf",
    "source_file",
]


def _extract_row(verdict: dict[str, Any], source_file: str) -> dict[str, Any] | None:
    """Return a CSV row dict from a verdict JSON, or None if not parseable."""
    symbol = verdict.get("symbol")
    family = verdict.get("family")
    rank = verdict.get("rank")
    v = verdict.get("verdict")
    if not all([symbol, family, v]):
        return None

    created_at = verdict.get("created_at", "")
    date = created_at[:10] if created_at else ""

    metrics = verdict.get("gate_v2_metrics", {})
    pf_ci = metrics.get("pf_ci_lower", "")
    p_edge = metrics.get("p_edge", "")
    mc_dd = metrics.get("mc_95th_dd_pct", "")
    dsr = metrics.get("dsr", "")
    wfo = metrics.get("wfo_consistency", verdict.get("wfo_consistency", ""))
    fixed_min = metrics.get("fixed_params_min_pf", "")

    return {
        "date": date,
        "symbol": symbol,
        "family": family,
        "rank": rank if rank is not None else "",
        "verdict": v,
        "passed_via": verdict.get("passed_via", ""),
        "pf_ci_lower": f"{pf_ci:.4f}" if isinstance(pf_ci, float) else pf_ci,
        "p_edge": f"{p_edge:.4f}" if isinstance(p_edge, float) else p_edge,
        "mc_dd_pct": f"{mc_dd:.4f}" if isinstance(mc_dd, float) else mc_dd,
        "dsr": f"{dsr:.4f}" if isinstance(dsr, float) else dsr,
        "wfo": wfo,
        "fixed_min_pf": f"{fixed_min:.4f}" if isinstance(fixed_min, float) else fixed_min,
        "source_file": source_file,
    }


def _load_journal() -> list[dict[str, Any]]:
    """Return existing journal rows, or empty list if file doesn't exist."""
    if not JOURNAL_PATH.exists():
        return []
    with JOURNAL_PATH.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _existing_source_files(rows: list[dict[str, Any]]) -> set[str]:
    return {r.get("source_file", "") for r in rows}


def _scan_verdicts(include_archive: bool) -> list[tuple[Path, str]]:
    """Yield (path, relative_name) for all verdict JSON files."""
    results = []
    for p in sorted(VERDICTS_DIR.glob("*.json")):
        if p.name.startswith("_"):
            continue
        results.append((p, p.name))
    if include_archive:
        archive_dir = VERDICTS_DIR / "archive"
        if archive_dir.exists():
            for p in sorted(archive_dir.glob("*.json")):
                results.append((p, f"archive/{p.name}"))
    return results


def _write_journal(rows: list[dict[str, Any]]) -> None:
    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def update_journal(
    include_archive: bool = False,
    dry_run: bool = False,
) -> int:
    """Scan verdict files and append any new ones to the journal.

    Returns the number of rows added.
    """
    existing_rows = _load_journal()
    already_seen = _existing_source_files(existing_rows)

    new_rows: list[dict[str, Any]] = []
    skipped = 0
    errors = 0

    for path, rel_name in _scan_verdicts(include_archive):
        if rel_name in already_seen:
            skipped += 1
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            # Replace JSON-invalid Infinity literals before parsing.
            raw = raw.replace(": Infinity", ": null").replace(":Infinity", ":null")
            verdict = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[WARN] Cannot parse {rel_name}: {exc}", file=sys.stderr)
            errors += 1
            continue

        row = _extract_row(verdict, rel_name)
        if row is None:
            print(f"[WARN] Skipping {rel_name}: missing required fields", file=sys.stderr)
            errors += 1
            continue

        new_rows.append(row)
        print(
            f"  + {rel_name}: {row['symbol']} {row['family']} rank{row['rank']} "
            f"({row['verdict']}) p_edge={row['p_edge']} wfo={row['wfo']}"
        )

    if not new_rows:
        print(f"Journal already up to date ({len(existing_rows)} rows, {skipped} skipped).")
        return 0

    print(f"\n{len(new_rows)} new rows to add (skipped {skipped} already-journaled).")
    if dry_run:
        print("[DRY-RUN] No changes written.")
        return len(new_rows)

    # Sort all rows by (symbol, family, rank, date) for stable output.
    all_rows = existing_rows + new_rows
    all_rows.sort(
        key=lambda r: (
            r.get("symbol", ""),
            r.get("family", ""),
            str(r.get("rank", "")),
            r.get("date", ""),
        )
    )
    _write_journal(all_rows)
    print(f"Written: {JOURNAL_PATH} ({len(all_rows)} total rows)")
    return len(new_rows)


def print_report() -> None:
    """Print a summary table of the journal, sorted by symbol+family+rank, most recent first."""
    rows = _load_journal()
    if not rows:
        print("Journal is empty. Run without --report to populate.")
        return

    # Group by (symbol, family, rank), show most recent entry.
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        key = (r.get("symbol", ""), r.get("family", ""), str(r.get("rank", "")))
        groups.setdefault(key, []).append(r)

    header = (
        f"  {'Symbol':<6} {'Family':<8} {'Rk':>2}  {'Verdict':<6} {'Via':<4}  "
        f"{'PF_CI':>6} {'p_edge':>6} {'DD%':>6} {'DSR':>5} {'WFO':<8}  Date"
    )
    print()
    print(header)
    print("  " + "-" * (len(header) - 2))
    for (sym, fam, rnk), group in sorted(groups.items()):
        latest = sorted(group, key=lambda r: r.get("date", ""))[-1]
        v = latest.get("verdict", "")
        via = latest.get("passed_via", "") or ""
        pf = latest.get("pf_ci_lower", "")
        pe = latest.get("p_edge", "")
        dd = latest.get("mc_dd_pct", "")
        dsr = latest.get("dsr", "")
        wfo = latest.get("wfo", "")
        date = latest.get("date", "")

        verdict_mark = "PASS" if v == "PASS" else "FAIL"
        line = (
            f"  {sym:<6} {fam:<8} {rnk:>2}  {verdict_mark:<6} {via[:4]:<4}  "
            f"{pf:>6} {pe:>6} {dd:>6} {dsr:>5} {wfo:<8}  {date}"
        )
        print(line)
    print(f"\nTotal: {len(rows)} rows across {len(groups)} strategies.")
    print(f"Journal: {JOURNAL_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verdict metric journal tracker")
    parser.add_argument(
        "--include-archive",
        action="store_true",
        help="Also journal verdicts in the archive/ subdirectory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be added without writing",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print the journal summary table instead of updating",
    )
    args = parser.parse_args()

    if args.report:
        print_report()
    else:
        n = update_journal(include_archive=args.include_archive, dry_run=args.dry_run)
        if n > 0 and not args.dry_run:
            print()
            print_report()


if __name__ == "__main__":
    main()
