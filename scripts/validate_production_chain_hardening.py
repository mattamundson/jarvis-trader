#!/usr/bin/env python3
"""Validate JARVIS production-chain planning artifacts.

This is intentionally narrow: it validates captured governance metadata without
claiming runtime readiness or opening any capital authority.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_DIR = ROOT / "docs" / "plans"
JSON_PATH = PLAN_DIR / "production_chain_hardening_v1.json"
MD_PATH = PLAN_DIR / "JARVIS_PRODUCTION_CHAIN_HARDENING_v1.0.md"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def main() -> int:
    if not JSON_PATH.exists():
        fail(f"missing {JSON_PATH.relative_to(ROOT)}")
    if not MD_PATH.exists():
        fail(f"missing {MD_PATH.relative_to(ROOT)}")

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    md = MD_PATH.read_text(encoding="utf-8")

    if data.get("capital_authority") != "paper_only":
        fail("capital_authority must remain paper_only")
    if data.get("live_capital_authorized") is not False:
        fail("live_capital_authorized must be false")
    if data.get("canary_authorized") is not False:
        fail("canary_authorized must be false")

    phases = data.get("phases", [])
    queue = data.get("starting_queue", [])
    if len(phases) != data.get("captured_phase_rows"):
        fail("captured_phase_rows does not equal len(phases)")
    if len(queue) != data.get("captured_starting_queue_rows"):
        fail("captured_starting_queue_rows does not equal len(starting_queue)")

    if data.get("declared_program_phases") != len(phases) + data.get("missing_phase_rows", -1):
        fail("declared/missing phase row accounting mismatch")
    if data.get("declared_starting_queue") != len(queue) + data.get("missing_starting_queue_rows", -1):
        fail("declared/missing starting queue accounting mismatch")

    required_strings = [
        "PAPER ONLY",
        "Live/canary authority",
        "30–60 trading days",
        "Source completeness note",
        "Source excerpt unavailable",
        "does not authorize runtime trading changes",
    ]
    for needle in required_strings:
        if needle not in md:
            fail(f"missing required markdown phrase: {needle}")

    blocked = data.get("agent_boundaries", {})
    for key, value in blocked.items():
        if value is not True:
            fail(f"agent boundary {key} must be true")

    print("OK: production-chain artifacts are structurally consistent and preserve paper-only authority")
    return 0


if __name__ == "__main__":
    sys.exit(main())
