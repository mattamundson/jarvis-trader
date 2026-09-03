from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_phase0_isg0.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_phase0_isg0_gate", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state(criteria):
    return {
        "plan": "JARVIS-MIP-1.0",
        "gate": "ISG-0",
        "gate_auto_close_allowed": False,
        "capital_authorized": False,
        "criteria": criteria,
        "authorization": {
            "isg0_closed": False,
            "phase1_adopted": False,
            "paper_authorized_by_this_file": False,
            "live_authorized_by_this_file": False,
        },
    }


def test_blockers_keep_gate_open_and_never_authorize():
    module = _load_script()
    result = module.evaluate_gate(
        _state(
            [
                {
                    "id": "O-01",
                    "state": "SATISFIED_TECHNICAL",
                    "requirement": "CI baseline",
                },
                {
                    "id": "A-01",
                    "state": "BLOCKED_EXTERNAL",
                    "requirement": "Runtime truth",
                    "blocker": "host evidence",
                },
            ]
        )
    )

    assert result["status"] == "OPEN"
    assert result["blockers"][0]["id"] == "A-01"
    assert result["authorization"] == {
        "auto_close_allowed": False,
        "phase1_authorized": False,
        "paper_authorized": False,
        "live_authorized": False,
    }


def test_draft_complete_is_still_unsatisfied():
    module = _load_script()
    result = module.evaluate_gate(
        _state(
            [
                {
                    "id": "A-02",
                    "state": "DRAFT_COMPLETE",
                    "requirement": "Source hierarchy adopted",
                }
            ]
        )
    )

    assert result["status"] == "OPEN"
    assert result["unsatisfied"] == [{"id": "A-02", "state": "DRAFT_COMPLETE"}]


def test_only_satisfied_criteria_are_ready_for_human_review_not_closed():
    module = _load_script()
    result = module.evaluate_gate(
        _state(
            [
                {
                    "id": "O-01",
                    "state": "SATISFIED_TECHNICAL",
                    "requirement": "CI baseline",
                }
            ]
        )
    )

    assert result["status"] == "READY_FOR_HUMAN_REVIEW"
    assert result["authorization"]["auto_close_allowed"] is False
    assert result["authorization"]["phase1_authorized"] is False


def test_authorization_true_makes_manifest_invalid():
    module = _load_script()
    state = _state(
        [
            {
                "id": "O-01",
                "state": "SATISFIED_TECHNICAL",
                "requirement": "CI baseline",
            }
        ]
    )
    state["authorization"]["live_authorized_by_this_file"] = True

    result = module.evaluate_gate(state)

    assert result["status"] == "INVALID"
    assert "authorization.live_authorized_by_this_file must be false" in result["errors"]


def test_duplicate_or_unknown_criteria_state_is_invalid():
    module = _load_script()
    result = module.evaluate_gate(
        _state(
            [
                {"id": "A-01", "state": "SATISFIED_TECHNICAL", "requirement": "x"},
                {"id": "A-01", "state": "MAGIC", "requirement": "y"},
            ]
        )
    )

    assert result["status"] == "INVALID"
    assert any("duplicate criterion id" in error for error in result["errors"])
    assert any("invalid state" in error for error in result["errors"])
