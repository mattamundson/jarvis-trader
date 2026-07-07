#!/usr/bin/env python
"""Static architecture-invariant guard -- stdlib only, executes NO engine code.

A fast, deterministic pre-CI check that enforces the repo's architecture
invariants by scanning source *as text*. It imports and runs no engine runtime
code, so it is safe to run unattended against an untrusted PR head (unlike a
full ``pytest`` run, which executes the PR's imports and side effects). This is
the check the ``pr-local-ci`` loop runs on every draft PR -- the layer that
would have caught the 2026-07 ``repair_daily_pnl.py`` regression before it sat
latent behind CI's draft-skip.

Each invariant reuses the SINGLE SOURCE OF TRUTH already codified in the test
suite, so this guard can never drift from the authoritative pytest check:

  * ``daily_pnl_single_writer`` -- no engine file outside the allowlist may emit
    a raw write to the daily_pnl table. SSOT: ``tests/test_daily_pnl_single_writer.py``
    (root cause of the 2026-06 phantom-P&L incident: a second writer with a
    mismatched balance basis). NOTE: this guard's own source deliberately avoids
    the literal write signature so the scan does not flag itself.

Exit code: 0 if all invariants hold, 1 if any is violated. Offenders print one
per line as ``<invariant-id>: <engine-relative-path>`` (or as JSON with
``--json``). The guard reports the *whole-tree* state; the caller (pr-local-ci)
is responsible for diff-scoping -- a pre-existing violation should only fail a
PR that actually touches the offending file.

Usage (from the engine/ directory):
    python -m scripts.arch_invariant_guard
    python scripts/arch_invariant_guard.py --json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# engine/ -- this file lives at engine/scripts/arch_invariant_guard.py
ENGINE_ROOT = Path(__file__).resolve().parent.parent


def _load_module(rel_path: str):
    """Import a repo module by path WITHOUT importing the engine package.

    Used to pull an invariant's authoritative allowlist/regex from its test
    module (which is pure stdlib), keeping this guard drift-free.
    """
    target = ENGINE_ROOT / rel_path
    spec = importlib.util.spec_from_file_location("_arch_ssot_" + target.stem, target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_daily_pnl_offenders(engine_root: Path | None = None) -> list[str]:
    """Return engine-relative paths that write the daily_pnl table without an
    allowlist entry, reusing tests/test_daily_pnl_single_writer.py as the SSOT
    for the write regex, the allowlist, and the excluded dirs."""
    ssot = _load_module("tests/test_daily_pnl_single_writer.py")
    root = engine_root or ENGINE_ROOT
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if any(rel == d or rel.startswith(d + "/") for d in ssot.EXCLUDE_DIRS):
            continue
        if rel in ssot.ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if ssot.WRITE_RE.search(text):
            offenders.append(rel)
    return sorted(offenders)


# Registry of enforced invariants: (id, finder, remediation hint).
INVARIANTS = [
    (
        "daily_pnl_single_writer",
        find_daily_pnl_offenders,
        "un-allowlisted writer of the daily_pnl table -- route the write through "
        "DatabaseManager.upsert_daily_pnl() (inheriting the value guard) or add a "
        "documented ALLOWLIST entry in tests/test_daily_pnl_single_writer.py",
    ),
]


def scan() -> dict:
    """Run every invariant; return {invariant_id: {offenders, hint}} for violations."""
    findings: dict = {}
    for inv_id, finder, hint in INVARIANTS:
        offenders = finder()
        if offenders:
            findings[inv_id] = {"offenders": offenders, "hint": hint}
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Static architecture-invariant guard.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    findings = scan()

    if args.json:
        print(json.dumps(findings))
    else:
        if not findings:
            print("arch-invariant guard: all invariants hold.")
        for inv_id, detail in findings.items():
            for offender in detail["offenders"]:
                print(f"{inv_id}: {offender}")
            print(f"  -> {detail['hint']}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
