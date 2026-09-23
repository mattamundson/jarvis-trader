import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "research" / "reference_evidence" / "mgc_trend_rv_filter_rank1_forward_contract.json"
DOC = ROOT.parent / "docs" / "research" / "mgc-trend-rv-filter-rank1-forward-contract.md"
QUEUE = ROOT / "research" / "strategy_validation_queue.json"
REGISTRY = ROOT / "backtest" / "candidate_registry.json"


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_mgc_rv_contract_preserves_halted_zero_exposure_boundary():
    evidence = _contract()
    assert evidence["candidate_id"] == "MGC_trend_rv_filter_rank1"
    assert evidence["symbol"] == "MGC"
    assert evidence["instrument_boundary"]["mgc_status"] == "halted_do_not_trade"
    assert evidence["instrument_boundary"]["may_route_orders"] is False
    assert evidence["instrument_boundary"]["zero_exposure_only"] is True
    assert all(value is False for value in evidence["safety_boundary"].values())


def test_contract_requires_candidate_specific_forward_evidence():
    evidence = _contract()
    contract = evidence["forward_evidence_contract"]
    assert contract["ledger_mode"] == "zero_exposure_research_only"
    assert "candidate_id" in contract["required_trade_fields"]
    assert "dsr_true_trial_count" in contract["required_summary_fields"]
    assert contract["minimum_review_sample"]["candidate_id_tagged_trades"] >= 60
    assert "symbol-only attribution used as graduation evidence" in contract["forbidden_sources"]


def test_historical_verdict_is_archived_context_not_fresh_permission():
    evidence = _contract()
    artifact = evidence["historical_artifacts"][0]
    assert "archive/MGC_trend_rv_filter_rank1_deep-2026-08-16.json" in artifact["path"]
    assert artifact["core_verdict"] == "FAIL"
    assert artifact["p_edge"] == 0.625
    assert "does not re-authorize MGC" in artifact["note"]
    blockers = set(evidence["fresh_evidence_blockers"])
    assert "No fresh non-archived gate-v2 artifact is linked for this candidate." in blockers


def test_registry_candidate_stays_not_deployed_live():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    candidate = next(c for c in registry["candidates"] if c["id"] == "MGC_trend_rv_filter_rank1")
    assert candidate["status"] == "forward_testing"
    assert candidate["deployed_live"] is False


def test_queue_marks_mgc_contract_step_blocked_not_actionable():
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    item = next(i for i in queue["items"] if i["id"] == "MGC_trend_rv_filter_rank1")
    assert item["state"] == "blocked"
    assert item["promotion_gates"]["data_contract"] is True
    assert item["may_route_orders"] is False
    assert item["evidence_contract"] == "engine/research/reference_evidence/mgc_trend_rv_filter_rank1_forward_contract.json"


def test_document_blocks_runtime_trading_surfaces():
    text = DOC.read_text(encoding="utf-8")
    required = [
        "research-only data contract",
        "MGC remains halted",
        "Symbol-only MGC context",
        "Blocked without a separate `[safety-review]` PR",
        "Treating archived historical verdicts as fresh promotion evidence",
    ]
    for phrase in required:
        assert phrase in text
