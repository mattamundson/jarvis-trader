"""Integration tests for the ThinkScript registry YAML and loader."""
import pytest

from utils.thinkscript_registry_loader import load_registry


def test_registry_loads_and_has_21_scripts():
    r = load_registry()
    # 28 entries: 22 prior (19 per-script + 2 COHEN + 1 legacy_utilities) + 6
    # jarvis-suite scripts (stc_signals, regime_filter, vwap_bands, risk_sizer,
    # mission_control_lower, scan_stc_regime) mirroring canonical engine logic.
    assert len(r.scripts) == 28, f"expected 28, got {len(r.scripts)}"


def test_stc_entry_has_correct_python_counterpart():
    r = load_registry()
    stc = next((s for s in r.scripts if s.id == "stc_ob_style_cycle"), None)
    assert stc is not None, "stc_ob_style_cycle missing from registry"
    assert "indicators.py::stc" in (stc.python_counterpart or "")
    assert stc.status == "ported"


def test_registry_version_is_1():
    r = load_registry()
    assert r.version == 1


def test_all_entries_have_docs():
    r = load_registry()
    for entry in r.scripts:
        assert entry.docs, f"entry {entry.id!r} is missing a docs path"


def test_saty_atr_levels_tos_inputs():
    r = load_registry()
    entry = next((s for s in r.scripts if s.id == "saty_atr_levels"), None)
    assert entry is not None
    assert entry.tos_inputs.get("atr_length") == 14
    assert entry.tos_inputs.get("fast_ema") == 8
    assert entry.tos_inputs.get("pivot_ema") == 21
    assert entry.tos_inputs.get("slow_ema") == 34


def test_status_distribution():
    r = load_registry()
    statuses = {s.status for s in r.scripts}
    assert "ported" in statuses
    # "orphan" status was cleared by Phase 2 porting — all 7 orphans are now ported.
    # If new orphans are added in future phases, restore this assertion.
    assert "deprecated" in statuses
    assert "reference_only" in statuses


def test_duplicates_to_skip_not_empty():
    r = load_registry()
    assert len(r.duplicates_to_skip) >= 11


def test_legacy_utilities_has_list_files():
    r = load_registry()
    entry = next((s for s in r.scripts if s.id == "legacy_utilities"), None)
    assert entry is not None
    assert isinstance(entry.file, list)
    assert len(entry.file) == 3


def test_source_of_truth_keys():
    r = load_registry()
    assert "parameters" in r.source_of_truth
    assert "indicators" in r.source_of_truth
    assert "signals.py" in r.source_of_truth["parameters"]
    assert "indicators.py" in r.source_of_truth["indicators"]
