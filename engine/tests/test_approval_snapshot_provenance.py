"""Approval snapshots preserve point-in-time data provenance."""

from __future__ import annotations

from approval.snapshot import pipeline_result_for_approval_snapshot


def test_pipeline_result_for_approval_snapshot_preserves_data_provenance() -> None:
    snapshot = pipeline_result_for_approval_snapshot(
        {
            "trade_decision": {"entry_price": 5300.25},
            "final_action": "buy",
            "data_provenance": {
                "last_bar_source": "ibkr",
                "serve_age_s": 7.5,
                "data_quality": "ok",
            },
        }
    )

    assert snapshot["data_provenance"] == {
        "last_bar_source": "ibkr",
        "serve_age_s": 7.5,
        "data_quality": "ok",
    }

