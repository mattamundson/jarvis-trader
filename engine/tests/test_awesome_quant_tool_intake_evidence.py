import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research" / "reference_evidence" / "awesome_quant_tool_intake_evidence.json"
DOC = ROOT.parent / "docs" / "research" / "awesome-quant-tool-intake-gate.md"


def test_awesome_quant_evidence_is_discovery_not_adoption():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["reference_repo"] == "mattamundson/awesome-quant"
    assert evidence["status"] == "tool_discovery_index_not_validated_dependency_or_alpha"
    assert evidence["parsed_entries"] >= 400
    assert evidence["relevant_trading_system_entries"] >= 200
    assert "catalog_inclusion_is_not_adoption_evidence" in evidence["non_duplicative_value"]


def test_required_intake_fields_cover_operational_risk():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    fields = set(evidence["required_intake_fields"])
    required = {
        "license_or_commercial_terms",
        "provider_or_key_requirements",
        "maintenance_signal",
        "overlap_check",
        "data_provenance_contract",
        "deterministic_fixture",
        "blocked_influence",
        "rollback_plan",
    }
    assert required <= fields


def test_blocked_influence_prevents_catalog_to_runtime_shortcut():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    blocked = set(evidence["blocked_influence"])
    assert "strategy_edge_claim" in blocked
    assert "runtime_dependency_without_approval" in blocked
    assert "live_or_paper_order_routing" in blocked
    assert all(value is False for value in evidence["safety_boundary"].values())


def test_document_requires_scorecard_not_star_count_adoption():
    text = DOC.read_text(encoding="utf-8")
    required = [
        "a vendor/tool catalog is not a strategy backlog",
        "Required intake scorecard before adoption",
        "Human approval if the proposal adds a runtime dependency or paid service",
        "Treating stars, catalog inclusion, or marketing claims as proof of strategy edge",
    ]
    for phrase in required:
        assert phrase in text
