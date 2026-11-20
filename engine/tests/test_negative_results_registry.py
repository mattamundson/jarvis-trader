from __future__ import annotations

import json

import pytest

from backtest.research.negative_results import (
    RetiredResearchError,
    assert_reopen_allowed,
    load_registry,
    retired_result,
)

EXPECTED_RETIRED_IDS = {
    "mes_ib_sequential_target_ladder",
    "mes_weekly_vwap_time_acceptance",
    "mes_weekly_vwap_volume_acceptance",
    "mes_weekly_vwap_developing_vpoc_acceptance",
    "mes_weekly_vwap_developing_tpo_poc_acceptance",
    "mes_weekly_vwap_ohlcv_clv_delta_acceptance",
}


def test_registry_has_exact_preregistered_retired_set() -> None:
    payload = load_registry()
    ids = {row["candidate_id"] for row in payload["retired_results"]}

    assert ids == EXPECTED_RETIRED_IDS
    assert payload["mode"] == "ANALYSIS_ONLY"
    assert payload["paper_only"] is True
    assert payload["orders_enabled"] is False
    assert payload["do_not_trade_symbols_excluded"] == ["MCL", "MNQ"]
    assert payload["data_provenance"]["sha256"] == (
        "516beb11568f3270e595035b1dada669654c6b337f87b81b35fc386dff092a12"
    )


@pytest.mark.parametrize("candidate_id", sorted(EXPECTED_RETIRED_IDS))
def test_every_retired_candidate_fails_closed_without_new_freeze(candidate_id: str) -> None:
    with pytest.raises(RetiredResearchError, match="missing reopening evidence"):
        assert_reopen_allowed(candidate_id)


def test_partial_reopening_evidence_remains_blocked() -> None:
    with pytest.raises(RetiredResearchError, match="locked_evaluation_window_id"):
        assert_reopen_allowed(
            "mes_ib_sequential_target_ladder",
            preregistration_id="PREREG-2026-10-02-001",
            material_change="true aggressor-side order-flow data",
        )


def test_rejected_oos_cannot_be_reused_for_optimization() -> None:
    with pytest.raises(RetiredResearchError, match="cannot be reused"):
        assert_reopen_allowed(
            "mes_weekly_vwap_volume_acceptance",
            preregistration_id="PREREG-2026-10-02-002",
            material_change="exchange volume-at-price instead of OHLCV allocation proxy",
            locked_evaluation_window_id="WINDOW-POST-2026-05-29",
            reuses_rejected_oos_for_optimization=True,
        )


def test_complete_new_freeze_authorizes_research_only_reopen() -> None:
    authorization = assert_reopen_allowed(
        "mes_weekly_vwap_volume_acceptance",
        preregistration_id="PREREG-2026-10-02-002",
        material_change="exchange volume-at-price instead of OHLCV allocation proxy",
        locked_evaluation_window_id="WINDOW-POST-2026-05-29",
    )

    assert authorization is not None
    assert authorization.candidate_id == "mes_weekly_vwap_volume_acceptance"
    assert authorization.preregistration_id == "PREREG-2026-10-02-002"


def test_unknown_candidate_is_not_silently_added_to_retired_set() -> None:
    assert assert_reopen_allowed("new_preregistered_candidate") is None
    assert retired_result("new_preregistered_candidate") is None


def test_registry_is_machine_readable_and_self_consistent() -> None:
    payload = load_registry()
    serialized = json.dumps(payload, sort_keys=True)

    assert "NaN" not in serialized
    assert all(row["evidence_report"] for row in payload["retired_results"])
    assert all(row["evidence_artifact"] for row in payload["retired_results"])
    assert all(row["principal_failure"] for row in payload["retired_results"])
