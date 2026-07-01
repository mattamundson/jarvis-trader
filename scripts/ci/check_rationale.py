#!/usr/bin/env python3
"""
CI: Economic-rationale check for new strategy runner files.

For any newly-added engine/backtest/run_*.py file in this PR, require that
its module docstring contains AT LEAST ONE of the following markers:

    - The word "Hypothesis" or "hypothesis" as a heading or block
    - "Economic rationale" (case-insensitive)
    - A "Why" section header

This enforces the funnel skill's core rule: no strategy card without a
stated economic rationale. See:
    tools/jarvis-funnel/references/strategy_card_schema.md
    tools/jarvis-funnel/references/lopez_de_prado_vs_brute_force.md

Exit non-zero if any new runner lacks a rationale marker.
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

RATIONALE_PATTERNS = [
    r"\bhypothesis\b",
    r"\beconomic rationale\b",
    r"\bwhy this (should|might) work\b",
    r"\bthesis\b",
    r"^\s*##\s*why\b",
]

RUNNER_GLOB_RE = re.compile(r"^engine/backtest/run_.*\.py$")


def get_added_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", base, head],
        capture_output=True, text=True, check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def module_docstring(path: Path) -> str:
    try:
        src = path.read_text()
        tree = ast.parse(src)
        ds = ast.get_docstring(tree) or ""
        return ds
    except Exception:
        return ""


def has_rationale(docstring: str) -> bool:
    if not docstring:
        return False
    for pat in RATIONALE_PATTERNS:
        if re.search(pat, docstring, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()

    added = get_added_files(args.base, args.head)
    runners = [p for p in added if RUNNER_GLOB_RE.match(p)]

    if not runners:
        print("No new strategy runner files in this PR — rationale check not applicable.")
        return 0

    print(f"Checking {len(runners)} new runner file(s) for economic rationale:\n")
    missing = []
    for p in runners:
        path = Path(p)
        if not path.exists():
            continue
        ds = module_docstring(path)
        if has_rationale(ds):
            print(f"  ✅ {p} — rationale documented")
        else:
            print(f"  ❌ {p} — missing rationale block")
            missing.append(p)

    if missing:
        print()
        print("=" * 70)
        print("BLOCKED: The following new strategy runners lack an economic rationale.")
        print("=" * 70)
        print()
        print("Add a module docstring containing at least one of:")
        print("  - A 'Hypothesis' block explaining WHY the strategy should work")
        print("  - An 'Economic rationale' section")
        print("  - A 'Why' section header")
        print()
        print("Missing:")
        for p in missing:
            print(f"  - {p}")
        print()
        print("See tools/jarvis-funnel/references/strategy_card_schema.md")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
