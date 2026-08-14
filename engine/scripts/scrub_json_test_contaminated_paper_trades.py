#!/usr/bin/env python
"""
Phase 0d (fix/engine-pythonhome-crashloop) -- scrub JSON-side test-contaminated
paper_trades.json rows (MCL / MNQ / MGC sentinel fills).

Background: before the Phase 0a isolation fix (commit 9e51e01), 21 test call
sites across 8 files constructed a real IBGatewayConnector and placed paper
orders directly, and PaperTradeLogger defaulted to writing the REAL
engine/data/paper_trades.json whenever a caller didn't override trades_file.
Every ordinary `pytest tests/` run silently appended synthetic fills for
MCL/MNQ/MGC (all DO_NOT_TRADE_SYMBOLS members) into the file the G5 live-
readiness gate reads. The isolation fix stopped new contamination; this
script cleans the historical rows.

Contamination predicate (unambiguous, verified against the live file with
zero middle-band rows):
    symbol in {"MCL", "MNQ"}                              -- ALL rows are
        synthetic: Phase 0b's full-history sweep found zero genuine pipeline
        trades for either symbol, and every row here is side=buy, pnl=None,
        filled_price clustered at 2-3 fixed mock-table values.
    OR (symbol == "MGC" AND side == "buy" AND pnl is None) -- the buy-side
        sentinel fills only. Deliberately EXCLUDES MGC's one real pipeline
        trade (2026-08-12, side=sell, filled_price=4396.75, pnl=+2091.48 --
        see the Phase 0b investigation in snazzy-swimming-waterfall.md,
        finding 2) which is honest historical record, not contamination.

Verified against the live file (2026-08-13): 54 contaminated rows (32 MCL +
18 MGC-buy-sentinel + 4 MNQ) out of 625 total; the `summary` block is keyed
off pnl-bearing trades only (19 rows: 18 MES + the 1 real MGC trade) and is
therefore byte-identical before/after -- this scrub only touches the raw
`trades` list.

Disposition: QUARANTINE, not DELETE (archive never delete). Removed rows are
appended to a sibling file, data/paper_trades_quarantine.json, each with a
quarantine_reason + quarantined_at timestamp, never discarded.

SAFETY: dry-run by default (read-only). --apply is DESTRUCTIVE and Amo-gated;
it takes a timestamped file backup first, does a single fast read-modify-
write (this file is the deprecated JSON audit log per PaperTradeLogger's own
DeprecationWarning -- SQLite paper_trades is the source of truth the live
engine's /health and /portfolio actually read -- so the small race window
against a concurrently-running engine process risks losing at most one
already-non-canonical audit-log row, never safety/portfolio state), and
verifies the result before exiting.

Usage (from engine/, against the target checkout's data file):
    .venv/Scripts/python scripts/scrub_json_test_contaminated_paper_trades.py --file <path>            # dry-run
    .venv/Scripts/python scripts/scrub_json_test_contaminated_paper_trades.py --file <path> --apply     # DESTRUCTIVE
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON = ENGINE_ROOT / "data" / "paper_trades.json"
DEFAULT_QUARANTINE = ENGINE_ROOT / "data" / "paper_trades_quarantine.json"

_SYNTHETIC_ONLY_SYMBOLS = {"MCL", "MNQ"}
QUARANTINE_REASON = (
    "Phase 0d (fix/engine-pythonhome-crashloop): JSON-side test contamination "
    "from pre-9e51e01 IBGatewayConnector test call sites writing real fills "
    "into production paper_trades.json. Quarantined not deleted."
)


def _is_contaminated(t: dict) -> bool:
    sym = t.get("symbol")
    if sym in _SYNTHETIC_ONLY_SYMBOLS:
        return True
    if sym == "MGC" and (t.get("side") or "").lower() == "buy" and t.get("pnl") is None:
        return True
    return False


def _load(json_path: Path) -> dict:
    return json.loads(json_path.read_text(encoding="utf-8"))


def dry_run(json_path: Path) -> None:
    data = _load(json_path)
    trades = data.get("trades", [])
    contaminated = [t for t in trades if _is_contaminated(t)]
    clean = [t for t in trades if not _is_contaminated(t)]

    print("=" * 72)
    print("DRY RUN -- Phase 0d JSON paper_trades scrub (no changes made)")
    print("=" * 72)
    print(f"File: {json_path}")
    print(f"Total trades: {len(trades)}")
    print(f"Contaminated (to quarantine): {len(contaminated)}")
    print(f"Clean (remain): {len(clean)}")
    print("\nsummary block (unaffected -- keyed off pnl-bearing trades only):")
    print(f"  {data.get('summary')}")

    from collections import Counter

    print(f"\nContaminated by symbol: {dict(Counter(t.get('symbol') for t in contaminated))}")
    print("\n  order_id                             | symbol | side | price    | pnl  | date")
    print("-" * 92)
    for t in contaminated:
        print(
            f"  {t.get('order_id', ''):<36} | {t.get('symbol', ''):<6} | "
            f"{t.get('side', ''):<4} | {t.get('filled_price'):<8} | "
            f"{t.get('pnl')} | {str(t.get('timestamp', ''))[:10]}"
        )

    print("\nNothing was modified. Re-run with --apply (DESTRUCTIVE, Amo-gated) to execute.")


def apply(json_path: Path, quarantine_path: Path) -> int:
    data = _load(json_path)
    trades = data.get("trades", [])
    contaminated = [t for t in trades if _is_contaminated(t)]
    clean = [t for t in trades if not _is_contaminated(t)]

    if not contaminated:
        print("No contaminated rows found -- nothing to do.")
        return 0

    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # 1. File backup before any mutation.
    backup = json_path.with_suffix(f".json.pre_phase0d_{stamp}.bak")
    shutil.copy2(json_path, backup)
    print(f"Backed up -> {backup}")

    # 2. Append quarantined rows (with reason + timestamp) to the quarantine file.
    if quarantine_path.exists():
        q_data = json.loads(quarantine_path.read_text(encoding="utf-8"))
    else:
        q_data = {"quarantined_trades": []}
    for t in contaminated:
        q_row = dict(t)
        q_row["quarantine_reason"] = QUARANTINE_REASON
        q_row["quarantined_at"] = stamp
        q_data["quarantined_trades"].append(q_row)

    q_tmp = quarantine_path.with_suffix(".tmp")
    q_tmp.write_text(json.dumps(q_data, indent=2), encoding="utf-8")
    q_tmp.replace(quarantine_path)
    print(f"Quarantined {len(contaminated)} row(s) -> {quarantine_path}")

    # 3. Fast read-modify-write of the live file: only the `trades` list
    #    changes, `summary` is left exactly as read (verified unaffected --
    #    it's keyed off pnl-bearing trades only, none of which are in the
    #    contaminated set).
    data["trades"] = clean
    tmp = json_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(json_path)
    print(f"Removed {len(contaminated)} contaminated row(s) from {json_path}")

    # 4. Verification: re-read from disk (not the in-memory copy).
    verify_data = _load(json_path)
    verify_trades = verify_data.get("trades", [])
    remaining_contam = sum(1 for t in verify_trades if _is_contaminated(t))
    print(
        f"\nVERIFY: total trades now={len(verify_trades)} (expect "
        f"{len(trades)} - {len(contaminated)} = {len(trades) - len(contaminated)}); "
        f"remaining contaminated={remaining_contam} (expect 0); "
        f"summary unchanged={verify_data.get('summary') == data.get('summary')}"
    )
    return 0 if remaining_contam == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scrub JSON test-contaminated paper_trades (Phase 0d)")
    p.add_argument(
        "--apply",
        action="store_true",
        help="DESTRUCTIVE: execute the quarantine (Amo-gated). Default is dry-run.",
    )
    p.add_argument("--file", default=str(DEFAULT_JSON), help="path to paper_trades.json")
    p.add_argument(
        "--quarantine-file",
        default=str(DEFAULT_QUARANTINE),
        help="path to the quarantine sidecar file",
    )
    args = p.parse_args(argv)

    json_path = Path(args.file)
    if not json_path.exists():
        print(f"File not found: {json_path}")
        return 2

    if args.apply:
        return apply(json_path, Path(args.quarantine_file))
    dry_run(json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
