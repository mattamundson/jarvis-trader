from pathlib import Path

import pytest

from morning_alpha.research.campaign import (
    PRE_REGISTERED_COST_BPS,
    PRE_REGISTERED_STRATEGIES,
    PRE_REGISTERED_TRIGGERS,
    ResearchCampaignSpec,
    inspect_research_files,
    require_research_ready,
)


def test_campaign_order_is_frozen_and_matches_protocol():
    assert [key.canonical for key in PRE_REGISTERED_STRATEGIES] == [
        "relative_strength_breakout@1.0.0",
        "sector_rotation@1.0.0",
        "post_earnings_drift@1.0.0",
        "momentum_breakout@1.0.0",
        "pullback_continuation@1.0.0",
        "gap_continuation@1.0.0",
    ]
    assert PRE_REGISTERED_COST_BPS == (0, 2, 5, 10, 20)
    assert len(PRE_REGISTERED_TRIGGERS) == 8


def test_campaign_defaults_require_full_validation_stack():
    spec = ResearchCampaignSpec()
    assert spec.min_historical_trades == 200
    assert spec.require_oos is True
    assert spec.require_wfo is True
    assert spec.require_monte_carlo is True
    assert spec.require_regime_stability is True
    assert spec.require_gate_v2 is True


def test_missing_data_root_fails_closed(tmp_path: Path):
    report = inspect_research_files(tmp_path / "does-not-exist")
    assert report.ready is False
    assert "DATA_ROOT_MISSING" in report.reasons
    assert "NO_BAR_FILES" in report.reasons
    with pytest.raises(RuntimeError, match="research data not ready"):
        require_research_ready(report)


def test_empty_existing_data_root_fails_closed(tmp_path: Path):
    root = tmp_path / "data"
    root.mkdir()
    report = inspect_research_files(root)
    assert report.ready is False
    assert report.file_count == 0
    assert report.reasons == ("NO_BAR_FILES",)


def test_parquet_presence_marks_file_stage_ready_without_claiming_coverage(tmp_path: Path):
    root = tmp_path / "data"
    bars = root / "bars"
    bars.mkdir(parents=True)
    (bars / "SPY.parquet").write_bytes(b"fixture")
    (bars / "QQQ.parquet").write_bytes(b"fixture")
    report = inspect_research_files(root)
    assert report.ready is True
    assert report.file_count == 2
    assert report.symbols == ("QQQ", "SPY")
    assert report.earliest_timestamp is None
    assert report.latest_timestamp is None
