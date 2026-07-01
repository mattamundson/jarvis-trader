#!/usr/bin/env python3
"""
CI: PBO gate check for touched verdict files.

Called from .github/workflows/funnel-quality-gate.yml. Receives a list of
verdict json paths as CLI args, checks each against the funnel gate policy,
and exits non-zero if any strategy that claims a passing verdict has a PBO
(Probability of Backtest Overfit) above the block threshold.

Policy (matches tools/jarvis-funnel/references/thresholds.md):
    - Hard block if verdict.gate_v2_metrics.pbo >= 0.40
    - Warn (but do not block) if 0.30 <= pbo < 0.40
    - Also warn if pbo is null but verdict claims PASS (missing metric)

Writes pbo_report.md for the PR comment step to pick up.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Tuple

HARD_BLOCK_PBO = 0.40
WARN_PBO = 0.30

# Verdict fields worth surfacing in the report
REPORT_FIELDS = ["symbol", "family", "rank", "verdict", "passed_via", "core_verdict", "alt_verdict"]


def check_verdict(path: Path) -> Tuple[str, dict]:
    """Returns ('block' | 'warn' | 'ok', context_dict)."""
    try:
        d = json.loads(path.read_text())
    except Exception as e:
        return "block", {"error": f"cannot parse: {e}", "path": str(path)}

    m = d.get("gate_v2_metrics", {}) or {}
    pbo = m.get("pbo")
    verdict = d.get("verdict")

    ctx = {"path": str(path), "verdict": verdict, "pbo": pbo}
    for f in REPORT_FIELDS:
        if f in d:
            ctx[f] = d[f]

    if verdict == "PASS":
        if pbo is None:
            # Missing metric on a passing verdict — funnel policy requires it
            return "warn", {**ctx, "reason": "PBO metric missing on PASS verdict"}
        if pbo >= HARD_BLOCK_PBO:
            return "block", {**ctx, "reason": f"PBO {pbo:.2f} >= {HARD_BLOCK_PBO} block threshold"}
        if pbo >= WARN_PBO:
            return "warn", {**ctx, "reason": f"PBO {pbo:.2f} in warning band [{WARN_PBO}, {HARD_BLOCK_PBO})"}

    return "ok", ctx


def main(argv: List[str]) -> int:
    files = [Path(p) for p in argv[1:] if Path(p).exists()]
    if not files:
        print("No verdict files provided (or none exist). Nothing to check.")
        Path("pbo_report.md").write_text("No verdict files touched in this PR — PBO check skipped.\n")
        return 0

    blocks: List[dict] = []
    warns: List[dict] = []
    oks: List[dict] = []

    for p in files:
        status, ctx = check_verdict(p)
        if status == "block":
            blocks.append(ctx)
        elif status == "warn":
            warns.append(ctx)
        else:
            oks.append(ctx)

    # Build markdown report
    lines = [f"**{len(files)} verdict file(s) checked**\n"]
    if blocks:
        lines.append(f"### ❌ Blocking issues ({len(blocks)})")
        lines.append("| File | Symbol / Family / Rank | PBO | Reason |")
        lines.append("|---|---|---|---|")
        for b in blocks:
            sfr = f"{b.get('symbol','?')} / {b.get('family','?')} / {b.get('rank','?')}"
            lines.append(f"| `{b.get('path','?')}` | {sfr} | {b.get('pbo','?')} | {b.get('reason','?')} |")
        lines.append("")
    if warns:
        lines.append(f"### ⚠️ Warnings ({len(warns)})")
        lines.append("| File | Symbol / Family / Rank | PBO | Reason |")
        lines.append("|---|---|---|---|")
        for w in warns:
            sfr = f"{w.get('symbol','?')} / {w.get('family','?')} / {w.get('rank','?')}"
            lines.append(f"| `{w.get('path','?')}` | {sfr} | {w.get('pbo','?')} | {w.get('reason','?')} |")
        lines.append("")
    if oks:
        lines.append(f"### ✅ Clean ({len(oks)})")
        for o in oks:
            sfr = f"{o.get('symbol','?')} / {o.get('family','?')} / {o.get('rank','?')}"
            lines.append(f"- `{o.get('path','?')}` — {sfr}")
        lines.append("")

    lines.append("_Policy: block at PBO ≥ 0.40, warn at 0.30 ≤ PBO < 0.40. "
                 "See tools/jarvis-funnel/references/thresholds.md for calibration rationale._")

    Path("pbo_report.md").write_text("\n".join(lines))
    print("\n".join(lines))

    if blocks:
        return 1  # non-zero -> workflow fails -> PR blocked
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
