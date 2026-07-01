#!/usr/bin/env python3
"""
PBO drift scanner.

Compares PBO values between:
  - The verdicts committed in master under engine/data/gate_v2_verdicts/
  - A locally-produced snapshot under engine/data/local_pbo_snapshots/

For each strategy present in both, computes the absolute PBO delta. Flags
any strategy whose PBO has drifted by more than --threshold (default 0.10).

The snapshot directory is populated by scripts/ci/snapshot_local_pbo.py,
which you run on your local machine after a batch of backtests.

Exit code 0 always — this is a monitor, not a gate. Findings are surfaced
via the drift_report.md output and the calling workflow's issue-filer.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_verdicts(directory: Path) -> dict:
    """Returns { hypothesis_id: {pbo, verdict, path} }."""
    if not directory.exists():
        return {}
    out = {}
    # Include both live/ and archive/ subdirs
    for jf in list(directory.glob("*.json")) + list(directory.glob("**/*.json")):
        try:
            d = json.loads(jf.read_text())
        except json.JSONDecodeError:
            continue
        # Build a stable key: symbol/family/rank
        key = f"{d.get('symbol','?')}/{d.get('family','?')}/rank{d.get('rank','?')}"
        pbo = (d.get("gate_v2_metrics") or {}).get("pbo")
        if key in out:
            # Prefer non-null PBO
            if pbo is not None and out[key]["pbo"] is None:
                out[key] = {"pbo": pbo, "verdict": d.get("verdict"), "path": str(jf)}
        else:
            out[key] = {"pbo": pbo, "verdict": d.get("verdict"), "path": str(jf)}
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-dir", required=True, help="Path to master verdicts directory")
    parser.add_argument("--snapshot-dir", required=True, help="Path to local snapshot directory")
    parser.add_argument("--threshold", type=float, default=0.10)
    parser.add_argument("--report", required=True, help="Output markdown report path")
    args = parser.parse_args()

    master = load_verdicts(Path(args.master_dir))
    snapshot = load_verdicts(Path(args.snapshot_dir))

    if not snapshot:
        Path(args.report).write_text(
            "## PBO drift report\n\n"
            f"**NO_DRIFT_DETECTED** — no snapshot found at `{args.snapshot_dir}`.\n\n"
            "To populate the snapshot, run `scripts/ci/snapshot_local_pbo.py` on your local machine\n"
            "after a batch of backtests, then commit the resulting files.\n"
        )
        return 0

    common = sorted(set(master.keys()) & set(snapshot.keys()))
    drifted = []
    stable = 0
    only_master = sorted(set(master.keys()) - set(snapshot.keys()))
    only_snapshot = sorted(set(snapshot.keys()) - set(master.keys()))

    for key in common:
        m = master[key]["pbo"]
        s = snapshot[key]["pbo"]
        if m is None or s is None:
            continue  # can't compute drift on missing values
        delta = abs(m - s)
        if delta >= args.threshold:
            drifted.append({"key": key, "master_pbo": m, "snapshot_pbo": s, "delta": delta,
                            "master_path": master[key]["path"], "snapshot_path": snapshot[key]["path"]})
        else:
            stable += 1

    lines = ["## PBO drift report", ""]
    lines.append(f"**Threshold:** ±{args.threshold:.2f} absolute PBO delta")
    lines.append(f"**Compared:** {len(common)} strategies present in both master and snapshot")
    lines.append(f"**Stable:** {stable}")
    lines.append(f"**Drifted:** {len(drifted)}")
    lines.append(f"**In master only:** {len(only_master)}")
    lines.append(f"**In snapshot only:** {len(only_snapshot)}")
    lines.append("")

    if not drifted and not only_master and not only_snapshot:
        lines.append("**NO_DRIFT_DETECTED** — all strategies are stable and both stores are in sync.")
        Path(args.report).write_text("\n".join(lines))
        return 0

    if drifted:
        lines.append("### 🚨 Drifted strategies")
        lines.append("| Strategy | Master PBO | Snapshot PBO | Delta | Direction |")
        lines.append("|---|---:|---:|---:|---|")
        for d in sorted(drifted, key=lambda x: -x["delta"]):
            direction = "⬆ worse (higher PBO in snapshot)" if d["snapshot_pbo"] > d["master_pbo"] else "⬇ better"
            lines.append(f"| `{d['key']}` | {d['master_pbo']:.3f} | {d['snapshot_pbo']:.3f} | {d['delta']:.3f} | {direction} |")
        lines.append("")
        lines.append("**Investigation checklist for each drifted strategy:**")
        lines.append("1. Did the underlying bar data change since the master verdict was written? "
                     "(Check `engine/data/parquet_cache/` timestamps.)")
        lines.append("2. Did the parameter grid change in the runner file? (Wider grid → higher PBO.)")
        lines.append("3. Was the PBO computation itself updated in `engine/backtest/family_fdr.py`?")
        lines.append("4. If none of the above, the drift is estimator noise — re-run and compare.")
        lines.append("")

    if only_master or only_snapshot:
        lines.append("### Coverage gaps")
        if only_master:
            lines.append(f"- **In master but not snapshot** ({len(only_master)}): "
                         "these strategies have not been re-backtested locally recently.")
            for k in only_master[:10]:
                lines.append(f"  - `{k}` → `{master[k]['path']}`")
            if len(only_master) > 10:
                lines.append(f"  - _...and {len(only_master) - 10} more_")
        if only_snapshot:
            lines.append(f"- **In snapshot but not master** ({len(only_snapshot)}): "
                         "these are new strategies that haven't been committed yet.")
            for k in only_snapshot[:10]:
                lines.append(f"  - `{k}` → `{snapshot[k]['path']}`")
            if len(only_snapshot) > 10:
                lines.append(f"  - _...and {len(only_snapshot) - 10} more_")
        lines.append("")

    lines.append("---")
    lines.append("_Report generated by `scripts/ci/pbo_drift_scan.py`. "
                 "See `docs/pr_pbo_gate_design.md` for the overall PBO gate policy._")

    Path(args.report).write_text("\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
