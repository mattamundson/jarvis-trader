import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research" / "reference_evidence" / "amo_arbitrage_forward_evidence_bridge.json"
DOC = ROOT.parent / "docs" / "research" / "amo-arbitrage-forward-evidence-bridge.md"


def test_amo_arbitrage_bridge_preserves_separate_product_boundary():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["reference_repo"] == "mattamundson/amo-arbitrage"
    assert evidence["status"] == "separate_product_bridge_only_not_validated_jarvis_alpha"
    assert evidence["product_boundary"] == "separate_product_bridge_only"
    assert "historical_screen_is_not_promotion" in evidence["non_duplicative_value"]


def test_pre_registration_and_forward_evidence_are_required():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["pre_registration"]["freeze_hash_required"] is True
    assert evidence["pre_registration"]["family_membership_immutable"] is True
    assert evidence["historical_screen"]["is_binding"] is False
    assert evidence["historical_screen"]["promotion_requires_forward_evidence"] is True
    assert evidence["forward_evidence"]["out_of_sample_required"] is True
    assert evidence["forward_evidence"]["exploratory_streams_zero_exposure_required"] is True


def test_feed_and_data_quality_controls_fail_closed():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["feed_ownership"]["single_writer_required"] is True
    assert evidence["feed_ownership"]["backfill_ledger_insert_only"] is True
    checks = set(evidence["data_quality"]["fail_closed_checks"])
    assert {"future_dated_rows", "missing_existence_rows", "stale_freshness", "date_parse_errors"} <= checks
    assert evidence["data_quality"]["business_day_sla_supported"] is True


def test_blocked_influence_covers_runtime_trading_surfaces():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    blocked = set(evidence["blocked_influence"])
    required = {
        "strategy_registry_promotion",
        "live_or_paper_order_routing",
        "risk_limit_changes",
        "kill_switch_changes",
        "env_or_secret_changes",
        "pm2_or_scheduler_changes",
        "broker_configuration",
    }
    assert required <= blocked
    assert all(value is False for value in evidence["safety_boundary"].values())


def test_document_states_screen_is_not_alpha_or_migration():
    text = DOC.read_text(encoding="utf-8")
    required = [
        "historical screens are not promotions",
        "separate product",
        "single-writer feed provenance",
        "Blocked without a separate `[safety-review]` PR",
        "Treating commodity/arbitrage screens as validated futures/options alpha",
    ]
    for phrase in required:
        assert phrase in text
