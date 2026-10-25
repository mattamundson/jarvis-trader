"""Tests for point-in-time feature snapshot manifests."""

from __future__ import annotations

from datetime import datetime, timezone

from data.feature_snapshot import (
    FeatureComponent,
    FeatureComponentType,
    FeatureFreshnessStatus,
    FeatureSnapshotManifest,
    component_from_data_provenance,
    data_provenance_from_decision,
    manifest_from_decision_provenance,
    required_feature_blocking_reasons,
)

NOW = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)


def test_feature_component_reports_fresh_when_inside_threshold() -> None:
    component = FeatureComponent(
        component_type=FeatureComponentType.MARKET_BARS,
        source="ibkr",
        as_of=datetime(2026, 9, 2, 14, 59, 30, tzinfo=timezone.utc),
        stale_after_s=60.0,
        quality="ok",
    )

    assert component.age_seconds(now=NOW) == 30.0
    assert component.freshness_status(now=NOW) is FeatureFreshnessStatus.FRESH


def test_feature_component_reports_stale_when_over_threshold() -> None:
    component = FeatureComponent(
        component_type=FeatureComponentType.MARKET_BARS,
        source="tradingview",
        as_of=datetime(2026, 9, 2, 14, 55, tzinfo=timezone.utc),
        stale_after_s=60.0,
        quality="ok",
    )

    assert component.freshness_status(now=NOW) is FeatureFreshnessStatus.STALE


def test_feature_component_reports_missing_for_unavailable_source() -> None:
    component = FeatureComponent(
        component_type=FeatureComponentType.FUTURES_SENTIMENT,
        source="unavailable",
        as_of=None,
        stale_after_s=300.0,
        quality="unavailable",
    )

    assert component.freshness_status(now=NOW) is FeatureFreshnessStatus.MISSING


def test_feature_component_reports_unknown_without_comparable_time() -> None:
    component = FeatureComponent(
        component_type=FeatureComponentType.GATE_VERDICT,
        source="gate_v2",
        as_of=None,
        stale_after_s=86_400.0,
        quality="pass",
    )

    assert component.freshness_status(now=NOW) is FeatureFreshnessStatus.UNKNOWN


def test_manifest_snapshot_id_is_deterministic_for_same_inputs() -> None:
    component = FeatureComponent(
        component_type=FeatureComponentType.MARKET_BARS,
        source="ibkr",
        as_of="2026-09-02T14:59:30Z",
        stale_after_s=60.0,
        quality="ok",
        metadata={"interval": "1m", "bars": 120},
    )
    manifest_a = FeatureSnapshotManifest(
        symbol="mes",
        decision_id="decision-1",
        created_at=NOW,
        components=[component],
    )
    manifest_b = FeatureSnapshotManifest(
        symbol="MES",
        decision_id="decision-1",
        created_at=NOW,
        components=[component],
    )

    assert manifest_a.snapshot_id(now=NOW) == manifest_b.snapshot_id(now=NOW)
    assert len(manifest_a.snapshot_id(now=NOW)) == 64


def test_manifest_blocking_reasons_include_missing_and_stale_components() -> None:
    manifest = FeatureSnapshotManifest(
        symbol="MES",
        decision_id="decision-1",
        created_at=NOW,
        components=[
            FeatureComponent(
                component_type=FeatureComponentType.MARKET_BARS,
                source="ibkr",
                as_of=datetime(2026, 9, 2, 14, 55, tzinfo=timezone.utc),
                stale_after_s=60.0,
                quality="ok",
            )
        ],
    )

    reasons = manifest.blocking_reasons(
        now=NOW,
        required_components={
            FeatureComponentType.MARKET_BARS,
            FeatureComponentType.GATE_VERDICT,
        },
    )

    assert reasons == ["missing_required_component:gate_verdict", "stale:market_bars"]


def test_component_from_existing_data_provenance_shape() -> None:
    component = component_from_data_provenance(
        {
            "last_bar_source": "ibkr",
            "serve_age_s": 45.0,
            "data_quality": "ok",
        },
        now=NOW,
        stale_after_s=60.0,
    )

    assert component.component_type is FeatureComponentType.MARKET_BARS
    assert component.source == "ibkr"
    assert component.age_seconds(now=NOW) == 45.0
    assert component.freshness_status(now=NOW) is FeatureFreshnessStatus.FRESH
    assert component.metadata["serve_age_s"] == 45.0


def test_component_from_data_provenance_fails_closed_when_source_missing() -> None:
    component = component_from_data_provenance(
        {"serve_age_s": 5.0},
        now=NOW,
        stale_after_s=60.0,
    )

    assert component.source == "unavailable"
    assert component.freshness_status(now=NOW) is FeatureFreshnessStatus.MISSING


def test_data_provenance_from_decision_reads_top_level() -> None:
    provenance = {"last_bar_source": "ibkr", "serve_age_s": 4.0}

    assert data_provenance_from_decision({"data_provenance": provenance}) == provenance


def test_data_provenance_from_decision_reads_signal_data() -> None:
    provenance = {"last_bar_source": "ibkr", "serve_age_s": 4.0}

    assert (
        data_provenance_from_decision({"signal_data": {"data_provenance": provenance}})
        == provenance
    )


def test_required_feature_blocking_reasons_blocks_missing_provenance() -> None:
    reasons = required_feature_blocking_reasons(
        {},
        symbol="MES",
        decision_id="decision-1",
        now=NOW,
    )

    assert "missing:market_bars" in reasons


def test_required_feature_blocking_reasons_blocks_unknown_age() -> None:
    reasons = required_feature_blocking_reasons(
        {"data_provenance": {"last_bar_source": "ibkr", "serve_age_s": None}},
        symbol="MES",
        decision_id="decision-1",
        now=NOW,
    )

    assert "unknown:market_bars" in reasons


def test_manifest_from_decision_provenance_uses_decision_id() -> None:
    manifest = manifest_from_decision_provenance(
        {"data_provenance": {"last_bar_source": "ibkr", "serve_age_s": 4.0}},
        symbol="mes",
        decision_id="decision-1",
        now=NOW,
    )

    record = manifest.to_record(now=NOW)
    assert record["symbol"] == "MES"
    assert record["decision_id"] == "decision-1"
    assert record["components"][0]["freshness_status"] == "fresh"
