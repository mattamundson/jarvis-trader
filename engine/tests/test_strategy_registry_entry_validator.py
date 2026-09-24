from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_strategy_registry_entry import main, validate_entry

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "research" / "examples" / "strategy_registry_entry.example.json"


def test_example_strategy_registry_entry_is_valid() -> None:
    entry = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert validate_entry(entry) == []


def test_validator_rejects_production_candidate_without_pass() -> None:
    entry = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    entry["status"] = "production_candidate"
    entry["promotion_gate"]["current_verdict"] = "fail"
    errors = validate_entry(entry)
    assert "production_candidate/approved strategies require pass or approved verdict" in "\n".join(errors)


def test_cli_reports_valid_example(capsys) -> None:
    assert main([str(EXAMPLE)]) == 0
    assert "valid strategy registry entry" in capsys.readouterr().out
