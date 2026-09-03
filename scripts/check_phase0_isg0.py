#!/usr/bin/env python3
"""Summarize machine-readable ISG-0 gate state without closing the gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_STATE = Path(__file__).resolve().parents[1] / "docs" / "plans" / "phase0" / "ISG0_GATE_STATE.json"
ALLOWED_STATES = {
    "SATISFIED_TECHNICAL",
    "DRAFT_COMPLETE",
    "IMPLEMENTED_DRAFT",
    "BLOCKED_EXTERNAL",
    "BLOCKED_HUMAN_REVIEW",
    "BLOCKED_DEPENDENCY",
}
SATISFIED_STATES = {"SATISFIED_TECHNICAL"}


def evaluate_gate(state: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    criteria = state.get("criteria")
    if state.get("plan") != "JARVIS-MIP-1.0":
        errors.append("unexpected plan")
    if state.get("gate") != "ISG-0":
        errors.append("unexpected gate")
    if state.get("gate_auto_close_allowed") is not False:
        errors.append("gate_auto_close_allowed must be false")
    if state.get("capital_authorized") is not False:
        errors.append("capital_authorized must be false")
    if not isinstance(criteria, list) or not criteria:
        errors.append("criteria must be a non-empty list")
        criteria = []

    blockers: list[dict[str, str]] = []
    unsatisfied: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in criteria:
        if not isinstance(row, dict):
            errors.append("criterion must be an object")
            continue
        criterion_id = row.get("id")
        criterion_state = row.get("state")
        requirement = row.get("requirement")
        if not isinstance(criterion_id, str) or not criterion_id:
            errors.append("criterion id missing")
            continue
        if criterion_id in seen:
            errors.append(f"duplicate criterion id: {criterion_id}")
        seen.add(criterion_id)
        if criterion_state not in ALLOWED_STATES:
            errors.append(f"invalid state for {criterion_id}: {criterion_state}")
            continue
        if not isinstance(requirement, str) or not requirement:
            errors.append(f"requirement missing for {criterion_id}")
        if criterion_state not in SATISFIED_STATES:
            item = {"id": criterion_id, "state": str(criterion_state)}
            unsatisfied.append(item)
            if str(criterion_state).startswith("BLOCKED_"):
                item["blocker"] = str(row.get("blocker") or "unspecified")
                blockers.append(item)

    authorization = state.get("authorization")
    if not isinstance(authorization, dict):
        errors.append("authorization object missing")
        authorization = {}
    for key in (
        "isg0_closed",
        "phase1_adopted",
        "paper_authorized_by_this_file",
        "live_authorized_by_this_file",
    ):
        if authorization.get(key) is not False:
            errors.append(f"authorization.{key} must be false")

    if errors:
        status = "INVALID"
    elif blockers or unsatisfied:
        status = "OPEN"
    else:
        status = "READY_FOR_HUMAN_REVIEW"

    return {
        "gate": "ISG-0",
        "status": status,
        "errors": errors,
        "blockers": blockers,
        "unsatisfied": unsatisfied,
        "authorization": {
            "auto_close_allowed": False,
            "phase1_authorized": False,
            "paper_authorized": False,
            "live_authorized": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize JARVIS ISG-0 machine state.")
    parser.add_argument("state", type=Path, nargs="?", default=DEFAULT_STATE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read gate state: {exc}")
    if not isinstance(payload, dict):
        parser.error("gate state root must be a JSON object")

    result = evaluate_gate(payload)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"ISG-0: {result['status']}")
        print(f"Blockers: {len(result['blockers'])}; Unsatisfied: {len(result['unsatisfied'])}")
        for row in result["blockers"]:
            print(f"[BLOCKED] {row['id']}: {row.get('blocker', 'unspecified')}")
        if result["errors"]:
            for error in result["errors"]:
                print(f"[INVALID] {error}")
        print("This checker never closes ISG-0 or authorizes PAPER/LIVE execution.")
    return 0 if result["status"] == "READY_FOR_HUMAN_REVIEW" else 2


if __name__ == "__main__":
    sys.exit(main())
