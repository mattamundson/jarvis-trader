from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research" / "reference_evidence" / "sentinel_health_probe_contract.json"
DOC = ROOT.parent / "docs" / "research" / "sentinel-health-probe-contract.md"
INVENTORY = ROOT.parent / "docs" / "research" / "repo-strategy-candidate-inventory.md"


def load_evidence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_sentinel_contract_is_observability_not_strategy_promotion() -> None:
    evidence = load_evidence()
    assert evidence["classification"] == "observability_contract"
    boundary = evidence["authority_boundary"]
    assert boundary["may_block_readiness"] is True
    assert boundary["may_create_trade_permission"] is False
    assert boundary["may_route_orders"] is False
    assert boundary["may_promote_strategy"] is False
    assert boundary["may_reset_kill_switch"] is False


def test_required_probe_fields_cover_evidence_and_fail_closed_behavior() -> None:
    evidence = load_evidence()
    required = set(evidence["required_fields"])
    assert {"probe_id", "authority_class", "component", "evidence_source"}.issubset(required)
    assert {"cadence", "freshness_sla", "fail_closed_behavior", "explicit_non_actions"}.issubset(required)


def test_minimum_bundle_covers_jarvis_runtime_and_delivery_risks() -> None:
    evidence = load_evidence()
    bundle = set(evidence["minimum_bundle"])
    assert {"engine_health", "ib_gateway_state", "kill_switch_state", "feed_freshness"}.issubset(bundle)
    assert {"pm2_dump_secret_posture", "hermes_brain_health", "delivery_path", "deadman_heartbeat"}.issubset(bundle)


def test_loop_policy_preserves_six_hour_agentic_minimum() -> None:
    evidence = load_evidence()
    assert evidence["cadence_policy"]["agentic_loop_minimum_hours"] == 6
    assert "non-LLM" in evidence["cadence_policy"]["deterministic_probe_exception"]


def test_doc_and_inventory_record_covered_state() -> None:
    doc = DOC.read_text(encoding="utf-8")
    inventory = INVENTORY.read_text(encoding="utf-8")
    assert "observability may veto readiness; it may not create permission" in doc
    assert "Sentinel health/deadman probes" in inventory
    assert "`covered`" in inventory
    assert "Wave 32 adds a non-routing health-probe contract" in inventory
