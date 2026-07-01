#!/usr/bin/env python3
"""
Local-verdict snapshotter.

Run this on your local machine AFTER a batch of local backtests. It copies
your local gate_v2 verdicts into engine/data/local_pbo_snapshots/ with a
timestamped subdirectory. When you commit and push the snapshot files, the
weekly pbo-drift-monitor workflow will pick them up and diff against master.

Usage (from repo root):
    python scripts/ci/snapshot_local_pbo.py

Options:
    --source engine/data/gate_v2_verdicts   Where your local verdicts live
    --dest engine/data/local_pbo_snapshots  Where to write the snapshot copy
    --keep-history                          Keep prior snapshots (default: replace)

The workflow reads engine/data/local_pbo_snapshots/*.json (top-level, non-recursive).
Timestamped history under archived/ is ignored by the drift scan but preserved for
audit.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="engine/data/gate_v2_verdicts")
    parser.add_argument("--dest", default="engine/data/local_pbo_snapshots")
    parser.add_argument("--keep-history", action="store_true",
                        help="Move existing snapshots to archived/YYYY-MM-DD/ before writing new ones")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    src = Path(args.source)
    dst = Path(args.dest)

    if not src.exists():
        print(f"Source directory not found: {src}", file=sys.stderr)
        return 1

    # Collect source verdict files (top-level + live/)
    files = list(src.glob("*.json"))
    live_dir = src / "live"
    if live_dir.exists():
        files.extend(live_dir.glob("*.json"))

    if not files:
        print(f"No verdicts found under {src}", file=sys.stderr)
        return 1

    print(f"Snapshotting {len(files)} verdicts from {src} → {dst}")

    if args.dry_run:
        for f in files:
            print(f"  [DRY RUN] would copy: {f.name}")
        return 0

    # Archive prior snapshots if requested
    dst.mkdir(parents=True, exist_ok=True)
    if args.keep_history:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        archive = dst / "archived" / stamp
        archive.mkdir(parents=True, exist_ok=True)
        for old in dst.glob("*.json"):
            shutil.move(str(old), str(archive / old.name))
        print(f"  Archived prior snapshot to {archive}")
    else:
        # Blow away current top-level files
        for old in dst.glob("*.json"):
            old.unlink()

    # Copy new snapshot files
    for f in files:
        target = dst / f.name
        shutil.copy2(str(f), str(target))

    # Write a marker
    marker = dst / "SNAPSHOT_INFO.json"
    marker.write_text(json.dumps({
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(src),
        "n_files": len(files),
    }, indent=2))

    print(f"Wrote {len(files)} snapshot files. Commit them to trigger drift monitoring on next Monday.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
