from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_strategy_registry_entry import validate_entry

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "research" / "strategy_registry"


def test_all_strategy_registry_entries_are_valid() -> None:
    entries = sorted(REGISTRY.glob("*.json"))
    assert entries, "expected at least one seeded strategy registry entry"
    failures: dict[str, list[str]] = {}
    for path in entries:
        errors = validate_entry(json.loads(path.read_text(encoding="utf-8")))
        if errors:
            failures[path.name] = errors
    assert failures == {}


def test_registry_entries_do_not_promote_failed_or_halted_strategies() -> None:
    for path in sorted(REGISTRY.glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry["status"] in {"rejected", "halted"}:
            assert entry["promotion_gate"]["current_verdict"] == "fail"
            assert entry["risk_envelope"]["max_position_size"].startswith("0 live contracts")
            assert entry["promotion_gate"]["human_approval_required"] is True
