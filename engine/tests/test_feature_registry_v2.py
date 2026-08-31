"""Schema and governance invariants for FEATURE_REGISTRY_V2.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml


REGISTRY_PATH = Path(__file__).resolve().parents[2] / "thinkorswim-scripts" / "FEATURE_REGISTRY_V2.yaml"

REQUIRED_FEATURE_FIELDS = {
    "id",
    "source_files",
    "family",
    "role",
    "priority",
    "formula",
    "availability",
    "source_integrity",
    "causal_integrity",
    "parity",
    "statistical_evidence",
    "deployment",
}


def _load() -> dict:
    with REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_registry_v2_loads_and_has_unique_feature_ids() -> None:
    registry = _load()
    assert registry["version"] == 2
    features = registry["features"]
    ids = [feature["id"] for feature in features]
    assert len(features) >= 20
    assert len(ids) == len(set(ids))


def test_registry_features_satisfy_declared_status_enums() -> None:
    registry = _load()
    enums = registry["governance"]["status_dimensions"]

    for feature in registry["features"]:
        assert REQUIRED_FEATURE_FIELDS <= feature.keys(), feature["id"]
        for dimension in (
            "source_integrity",
            "causal_integrity",
            "parity",
            "statistical_evidence",
            "deployment",
        ):
            assert feature[dimension] in enums[dimension], (feature["id"], dimension)


def test_live_allowed_features_cannot_bypass_integrity_gates() -> None:
    registry = _load()
    for feature in registry["features"]:
        if feature["deployment"] != "live_allowed":
            continue
        assert feature["causal_integrity"] in {"safe", "safe_core", "safe_formula"}
        assert feature["parity"] == "passed"
        assert feature["statistical_evidence"] in {"paper_pass", "live_pass"}


def test_known_source_discrepancies_are_explicitly_versioned() -> None:
    features = {feature["id"]: feature for feature in _load()["features"]}

    kama = features["kama_next_signal_v2"]
    assert kama["parity"] == "failed"
    assert set(kama["required_variants"]) == {
        "kama_tos_legacy_v1",
        "kama_kaufman_standard_v1",
    }

    phase = features["phase_oscillator_v2"]
    assert phase["parity"] == "failed"
    assert set(phase["required_variants"]) == {
        "phase_tos_exact_v1",
        "phase_simplified_v1",
    }

    cohen = features["cohen_stc_custom_smoothing_v1"]
    assert cohen["parity"] == "failed"


def test_future_reference_sources_are_not_marked_live_allowed() -> None:
    features = {feature["id"]: feature for feature in _load()["features"]}
    for feature_id in (
        "calendar_preholiday_v2",
        "calendar_turn_of_month_v2",
        "singlefinder_confirmed_v2",
        "rangefinder_expansion_v2",
        "virgin_profile_levels_v1",
    ):
        assert features[feature_id]["deployment"] == "research_only"
