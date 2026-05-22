"""verdict_lifecycle — atomic verdict refresh pipeline.

Encapsulates the four-step sequence every runner must perform when producing
a refreshed verdict:

    1. Archive the current (old) verdict JSON to gate_v2_verdicts/archive/
       with a datetime-stamped filename so the history is preserved.
    2. Write the new verdict JSON to the canonical path.
    3. Compare old vs. new via compare_verdicts.compare() and surface drift.
    4. Append the new row to _journal.csv via track_verdict_journal.

Runners call one function instead of manually handling each step:

    from backtest.verdict_lifecycle import commit_verdict

    summary = commit_verdict(
        verdict_doc=gate_output,
        symbol="MES",
        family="trend",
        rank=11,
        verdicts_dir=engine_root / "data" / "gate_v2_verdicts",
    )
    if summary["needs_review"]:
        print("[WARN] Drift detected — review before deploying to paper trading")

Returns a dict with keys:
    archived_path  — Path | None  (None if no previous verdict existed)
    verdict_path   — Path         (canonical path of the written verdict)
    diff           — dict | None  (compare_verdicts output; None if no prior verdict)
    needs_review   — bool         (True if diff signals a verdict transition or drift)
    journal_rows   — int          (number of rows appended to the journal; 0 or 1)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Internal imports — deferred to avoid circular deps at module load time
# ---------------------------------------------------------------------------


def _import_compare() -> Any:
    from backtest import compare_verdicts  # noqa: PLC0415

    return compare_verdicts


def _import_journal() -> Any:
    from backtest import track_verdict_journal  # noqa: PLC0415

    return track_verdict_journal


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def archive_existing(verdict_path: Path) -> Path | None:
    """Move the current verdict to the archive/ subdirectory.

    The archived filename gains an ISO-8601 timestamp suffix so multiple
    refreshes don't collide:
        MES_trend_rank11.json  ->  archive/MES_trend_rank11_2026-05-08T10:00:00Z.json

    Returns the Path of the archived file, or None if nothing was there to archive.
    """
    if not verdict_path.exists():
        return None

    archive_dir = verdict_path.parent / "archive"
    archive_dir.mkdir(exist_ok=True)

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    stem = verdict_path.stem  # e.g. "MES_trend_rank11"
    archived = archive_dir / f"{stem}_{ts}.json"

    verdict_path.rename(archived)
    return archived


def write_verdict(verdict_path: Path, verdict_doc: dict[str, Any]) -> Path:
    """Serialise verdict_doc to verdict_path as pretty-printed JSON.

    Handles JSON-incompatible float values (inf -> null) so the file is
    always valid JSON regardless of how the runner computed metrics.
    """
    verdict_path.parent.mkdir(parents=True, exist_ok=True)

    # Sanitise inf/-inf floats before serialising — json.dumps chokes on them
    raw = json.dumps(verdict_doc, indent=2, default=str)
    raw = raw.replace(": Infinity", ": null").replace(":Infinity", ":null")
    raw = raw.replace(": -Infinity", ": null").replace(":-Infinity", ":null")

    verdict_path.write_text(raw, encoding="utf-8")
    return verdict_path


def compare_verdicts(
    old_path: Path | None,
    new_path: Path,
    *,
    symbol: str | None = None,
) -> dict[str, Any] | None:
    """Diff old vs. new verdict and return the compare_verdicts result dict.

    Loads ThresholdConfig from data/compare_verdicts_config.yaml so that
    symbol-specific drift thresholds are applied automatically.

    Returns None if old_path is None or does not exist (no prior verdict to
    compare against).
    """
    if old_path is None or not old_path.exists():
        return None

    cv = _import_compare()
    try:
        old_doc = json.loads(old_path.read_text(encoding="utf-8"))
        new_doc = json.loads(new_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[verdict_lifecycle] WARNING: could not parse for diff: {exc}", file=sys.stderr)
        return None

    cfg = cv._load_config(symbol=symbol)
    return cv.compare(old_doc, new_doc, cfg)


def _refresh_journal_entry(verdicts_dir: Path, source_file: str) -> int:
    """Replace an existing journal row for source_file with fresh data.

    Used after a verdict refresh: the source_file name is unchanged but the
    content has changed, so normal append-dedup would skip it.  This function
    removes the old row and appends a new one from the current on-disk file.

    Returns 1 if the row was updated, 0 if no prior row existed (fall through
    to normal append).
    """
    import csv as _csv

    tj = _import_journal()
    journal_path = verdicts_dir / "_journal.csv"

    if not journal_path.exists():
        return 0

    rows = list(_csv.DictReader(journal_path.open(encoding="utf-8")))
    had_entry = any(r.get("source_file") == source_file for r in rows)
    if not had_entry:
        return 0

    # Remove old row for this source_file
    rows = [r for r in rows if r.get("source_file") != source_file]

    # Extract fresh row from the updated file
    verdict_path = verdicts_dir / source_file
    if verdict_path.exists():
        try:
            raw = verdict_path.read_text(encoding="utf-8")
            raw = raw.replace(": Infinity", ": null").replace(":Infinity", ":null")
            verdict_doc = json.loads(raw)
            new_row = tj._extract_row(verdict_doc, source_file)
            if new_row:
                rows.append(new_row)
        except (json.JSONDecodeError, OSError):
            pass

    # Re-sort and write
    rows.sort(
        key=lambda r: (
            r.get("symbol", ""),
            r.get("family", ""),
            str(r.get("rank", "")),
            r.get("date", ""),
        )
    )
    tj._write_journal.__func__(rows) if hasattr(tj._write_journal, "__func__") else None

    # Use tj._write_journal directly
    import csv as _csv2

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("w", newline="", encoding="utf-8") as fh:
        writer = _csv2.DictWriter(fh, fieldnames=tj._COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return 1


def append_to_journal(
    verdicts_dir: Path,
    source_file: str | None = None,
    include_archive: bool = False,
) -> int:
    """Append any unjourned verdict files to _journal.csv.

    If source_file is given (a refresh scenario), replaces the existing row
    for that file rather than deduplicating it away.

    Returns the number of rows appended/updated.
    """
    tj = _import_journal()

    # For refreshes: replace the existing row
    if source_file is not None:
        updated = _refresh_journal_entry(verdicts_dir, source_file)
        if updated:
            return updated

    # Normal append-only update for new files
    orig_vdir = tj.VERDICTS_DIR
    orig_jpath = tj.JOURNAL_PATH
    try:
        tj.VERDICTS_DIR = verdicts_dir
        tj.JOURNAL_PATH = verdicts_dir / "_journal.csv"
        return tj.update_journal(include_archive=include_archive)
    finally:
        tj.VERDICTS_DIR = orig_vdir
        tj.JOURNAL_PATH = orig_jpath


def commit_verdict(
    verdict_doc: dict[str, Any],
    *,
    symbol: str,
    family: str,
    rank: int,
    verdicts_dir: Path,
    update_journal: bool = True,
    print_summary: bool = True,
) -> dict[str, Any]:
    """Full lifecycle: archive -> write -> compare -> journal.

    Args:
        verdict_doc:    The gate v2 output dict from the runner.
        symbol:         e.g. "MES"
        family:         e.g. "trend"
        rank:           e.g. 11
        verdicts_dir:   Directory for verdict JSONs (default: engine/data/gate_v2_verdicts/)
        update_journal: If True, appends the new verdict to _journal.csv.
        print_summary:  If True, prints a one-line lifecycle summary to stdout.

    Returns a summary dict:
        archived_path   Path | None
        verdict_path    Path
        diff            dict | None
        needs_review    bool
        journal_rows    int
    """
    canonical_name = f"{symbol}_{family}_rank{rank}.json"
    verdict_path = verdicts_dir / canonical_name

    # 1. Archive the old verdict (if any)
    archived = archive_existing(verdict_path)

    # 2. Write the new verdict
    write_verdict(verdict_path, verdict_doc)

    # 3. Compare old vs. new — passes symbol so per-symbol YAML thresholds apply
    diff = compare_verdicts(archived, verdict_path, symbol=symbol)
    needs_review = bool(diff and diff.get("needs_review"))

    # 4. Append to journal (refresh-aware: replaces existing row if source_file already known)
    journal_rows = 0
    if update_journal:
        journal_rows = append_to_journal(verdicts_dir, source_file=canonical_name)

    if print_summary:
        status = "NEEDS REVIEW" if needs_review else "OK"
        archived_str = f" (archived: {archived.name})" if archived else " (first write)"
        print(
            f"[lifecycle] {canonical_name} -> written{archived_str} "
            f"| diff={status} | journal+{journal_rows}"
        )
        if needs_review and diff:
            trans = diff.get("verdict_transition", "")
            drift = diff.get("champion_drift", [])
            if trans and trans != "no transition":
                print(f"  verdict transition: {trans}")
            for d in drift[:3]:
                print(f"  param drift: {d}")

    return {
        "archived_path": archived,
        "verdict_path": verdict_path,
        "diff": diff,
        "needs_review": needs_review,
        "journal_rows": journal_rows,
    }
