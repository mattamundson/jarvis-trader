from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research" / "reference_evidence" / "atlas_gic_autoresearch_evidence.json"
DOC = ROOT.parent / "docs" / "research" / "atlas-gic-autoresearch-risk-contract.md"


def test_atlas_gic_evidence_is_reference_only_not_alpha() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    assert evidence["source_repo"] == "mattamundson/atlas-gic"
    assert evidence["reference_commit"] == "fcfc40dcf628f6af091c28cb2c33827f42cef8fd"
    assert evidence["classification"] == "reference-only"
    assert evidence["jarvis_status"] == "research_control_not_alpha_evidence"
    assert len(evidence["selected_files"]) == 6
    assert all(item["sha256"] for item in evidence["selected_files"])


def test_atlas_gic_campaign_economics_block_prompt_metric_promotion() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    campaign = evidence["campaign_evidence"]

    assert campaign["trading_days"] == 378
    assert campaign["total_return_pct"] < 0
    assert campaign["ending_value"] < campaign["starting_value"]
    assert campaign["parsed_prepost_improved"] == 14
    assert campaign["parsed_post_sharpe_nonpositive"] == 15
    assert campaign["parsed_post_sharpe_nonpositive"] > campaign["parsed_prepost_rows"] / 2


def test_atlas_gic_contract_blocks_runtime_and_risk_side_effects() -> None:
    text = DOC.read_text(encoding="utf-8")

    for phrase in [
        "No live trading config",
        "campaign-level economic scoreboard",
        "Darwinian weights are research weights only",
        "Spawning a role is never permission to trade a role",
        "dedicated `[safety-review]` PR",
        "prompt_autoresearch_experiment",
    ]:
        assert phrase in text
