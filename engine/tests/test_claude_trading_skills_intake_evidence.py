import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research" / "reference_evidence" / "claude_trading_skills_intake_evidence.json"
DOC = ROOT.parent / "docs" / "research" / "claude-trading-skills-intake-gate.md"


def test_claude_trading_skills_evidence_has_source_and_novelty():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["reference_repo"] == "mattamundson/claude-trading-skills"
    assert evidence["reference_commit"] == "9ef78d6"
    assert evidence["status"] == "research_control_not_validated_alpha"
    assert "authority_classification_for_agentic_trading_skills" in evidence["non_duplicative_value"]
    assert "advisory_output_cannot_override_strategy_registry" in evidence["non_duplicative_value"]


def test_skill_classes_have_allowed_and_blocked_influence():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    classes = {item["class"]: item for item in evidence["candidate_skill_classes"]}
    expected = {
        "research_context",
        "candidate_generator",
        "adversarial_reviewer",
        "risk_advisory",
        "operator_checklist",
        "provider_dependent",
    }
    assert set(classes) == expected
    for item in classes.values():
        assert item["allowed"]
        assert item["blocked"]
    assert "registry_approval" in classes["candidate_generator"]["blocked"]
    assert "change_risk_limits" in classes["risk_advisory"]["blocked"]
    assert "automated_order_approval" in classes["operator_checklist"]["blocked"]


def test_safety_boundary_blocks_runtime_and_trading_mutations():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert all(value is False for value in evidence["safety_boundary"].values())
    gates = set(evidence["acceptance_gates"])
    assert "missing_or_stale_provider_data_fails_closed" in gates
    assert "advisory_output_cannot_override_failed_registry_verdict" in gates


def test_document_preserves_advisory_only_boundary():
    text = DOC.read_text(encoding="utf-8")
    required = [
        "cannot override registry gates",
        "missing/stale provider data fails closed",
        "Blocked without a separate `[safety-review]` PR",
        "Letting any skill output place orders",
        "strategy-registry verdicts",
    ]
    for phrase in required:
        assert phrase in text
