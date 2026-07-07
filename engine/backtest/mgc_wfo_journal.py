"""
MGC WFO + gate v2 metric journal.

Reads all gate_v2_verdicts files for MGC (current + archive) and maintains
a CSV at data/mgc_wfo_journal.csv for regime-shift detection.

Usage (one-shot rebuild):
    cd engine
    .venv/Scripts/python backtest/mgc_wfo_journal.py

Usage (append after a fresh WFO run):
    from backtest.mgc_wfo_journal import append_verdict
    append_verdict(Path("data/gate_v2_verdicts/MGC_trend_rank4.json"))
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

_ENGINE_DIR = Path(__file__).resolve().parents[1]
_VERDICTS_DIR = _ENGINE_DIR / "data" / "gate_v2_verdicts"
_JOURNAL_PATH = _ENGINE_DIR / "data" / "mgc_wfo_journal.csv"

_CSV_FIELDNAMES = [
    "run_date",
    "source_file",
    "symbol",
    "family",
    "rank",
    "verdict",
    "passed_via",
    "p_edge",
    "wfo_consistency",
    "pf_ci_lower",
    "dsr",
    "mc_95th_dd_pct",
    "n_oos_windows",
    "total_oos_trades",
]


def _safe(value: Any, *, default: str = "") -> str:
    """Convert a value to a CSV-safe string, mapping NaN/None/inf to empty."""
    if value is None:
        return default
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return str(value)
    except (TypeError, ValueError):
        return str(value) if value != "" else default


def parse_verdict_file(path: Path) -> dict[str, str] | None:
    """Extract journal row from a gate_v2 verdict JSON file.

    Returns None if the file is not an MGC verdict or lacks required fields.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        # gate_v2_verdicts can contain bare Infinity — replace before json.loads
        raw = raw.replace(": Infinity", ": null").replace(":Infinity", ":null")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None

    symbol = data.get("symbol", "")
    if symbol != "MGC":
        return None

    metrics = data.get("gate_v2_metrics") or {}
    wfo_config = data.get("wfo_config") or {}
    gate_v2 = data.get("gate_v2") or {}

    passed_via = data.get("passed_via") or gate_v2.get("passed_via") or ""

    return {
        "run_date": data.get("created_at", ""),
        "source_file": path.name,
        "symbol": symbol,
        "family": data.get("family", ""),
        "rank": _safe(data.get("rank")),
        "verdict": data.get("verdict", ""),
        "passed_via": passed_via,
        "p_edge": _safe(metrics.get("p_edge")),
        "wfo_consistency": _safe(metrics.get("wfo_consistency")),
        "pf_ci_lower": _safe(metrics.get("pf_ci_lower")),
        "dsr": _safe(metrics.get("dsr")),
        "mc_95th_dd_pct": _safe(metrics.get("mc_95th_dd_pct")),
        "n_oos_windows": _safe(wfo_config.get("n_oos_windows")),
        "total_oos_trades": _safe(wfo_config.get("total_oos_trades")),
    }


def collect_all_mgc_rows(verdicts_dir: Path | None = None) -> list[dict[str, str]]:
    """Scan current + archive verdict dirs and return all MGC rows, sorted by run_date."""
    if verdicts_dir is None:
        verdicts_dir = _VERDICTS_DIR

    paths: list[Path] = []
    paths.extend(verdicts_dir.glob("MGC_*.json"))
    archive = verdicts_dir / "archive"
    if archive.is_dir():
        paths.extend(archive.glob("MGC_*.json"))

    rows: list[dict[str, str]] = []
    for p in paths:
        row = parse_verdict_file(p)
        if row is not None:
            rows.append(row)

    rows.sort(key=lambda r: r["run_date"])
    return rows


def rebuild_journal(
    journal_path: Path | None = None,
    verdicts_dir: Path | None = None,
) -> int:
    """Rebuild the journal CSV from scratch. Returns number of rows written."""
    if journal_path is None:
        journal_path = _JOURNAL_PATH

    rows = collect_all_mgc_rows(verdicts_dir)
    with journal_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def append_verdict(
    verdict_path: Path,
    journal_path: Path | None = None,
) -> bool:
    """Append a single verdict file to the journal. Returns True if appended.

    Safe to call even if the file is not MGC (returns False).
    Deduplicates by source_file name — existing rows with the same filename
    are not duplicated.
    """
    if journal_path is None:
        journal_path = _JOURNAL_PATH

    row = parse_verdict_file(verdict_path)
    if row is None:
        return False

    existing_files: set[str] = set()
    if journal_path.exists():
        with journal_path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for existing in reader:
                existing_files.add(existing.get("source_file", ""))

    if row["source_file"] in existing_files:
        return False

    write_header = not journal_path.exists()
    with journal_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    return True


def read_journal(journal_path: Path | None = None) -> list[dict[str, str]]:
    """Read all rows from the journal CSV. Returns [] if file does not exist."""
    if journal_path is None:
        journal_path = _JOURNAL_PATH

    if not journal_path.exists():
        return []

    with journal_path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


if __name__ == "__main__":
    n = rebuild_journal()
    rows = read_journal()
    print(f"Rebuilt MGC WFO journal: {n} rows -> {_JOURNAL_PATH}")
    print(f"{'run_date':<35} {'file':<50} {'verdict':<5} {'p_edge':<8} {'wfo':<10} {'pf_ci'}")
    for r in rows:
        print(
            f"{r['run_date']:<35} {r['source_file']:<50} "
            f"{r['verdict']:<5} {r['p_edge']:<8} {r['wfo_consistency']:<10} {r['pf_ci_lower']}"
        )
