from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "audit_instrument_metadata.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_instrument_metadata_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_legacy_sources_are_parsed_without_runtime_imports():
    module = _load_script()
    report = module.build_audit(Path(__file__).resolve().parents[2])

    assert report["runtime_imports_used"] is False
    assert report["source_count"] == 3
    assert report["migration_authorized"] is False
    assert report["sources"]["position_sizing"]["MES"] == 5.0
    assert report["sources"]["portfolio_tracker"]["MES"] == 5.0
    assert report["sources"]["backtest_contract_specs"]["MES"] == 5.0


def test_provider_aliases_are_explicitly_quarantined():
    module = _load_script()
    report = module.build_audit(Path(__file__).resolve().parents[2])
    aliases = {row["alias"]: row for row in report["provider_aliases"]}

    assert set(aliases) == {"MES=F", "NQ=F", "CL=F", "GC=F"}
    assert all(row["requires_disposition"] is True for row in aliases.values())
    assert aliases["MES=F"]["multiplier_mismatch"] is False
    assert aliases["NQ=F"]["multiplier_mismatch"] is True
    assert aliases["CL=F"]["multiplier_mismatch"] is True
    assert aliases["GC=F"]["multiplier_mismatch"] is True


def test_current_alias_mismatches_capture_micro_vs_full_size_semantics():
    module = _load_script()
    report = module.build_audit(Path(__file__).resolve().parents[2])
    mismatches = {row["alias"]: row for row in report["alias_multiplier_mismatches"]}

    assert mismatches["NQ=F"]["alias_multiplier"] == 2.0
    assert mismatches["NQ=F"]["canonical_values"]["backtest_contract_specs"] == 20.0
    assert mismatches["CL=F"]["alias_multiplier"] == 100.0
    assert mismatches["CL=F"]["canonical_values"]["portfolio_tracker"] == 1000.0
    assert mismatches["GC=F"]["alias_multiplier"] == 10.0
    assert mismatches["GC=F"]["canonical_values"]["portfolio_tracker"] == 100.0


def test_cross_source_same_symbol_multipliers_have_no_hidden_disagreement():
    module = _load_script()
    report = module.build_audit(Path(__file__).resolve().parents[2])

    assert report["multiplier_mismatches"] == []


def test_coverage_debt_is_reported_not_silently_filled():
    module = _load_script()
    report = module.build_audit(Path(__file__).resolve().parents[2])
    incomplete = {row["symbol"]: row["present_in"] for row in report["incomplete_coverage"]}

    assert "MHG" in incomplete
    assert "MSI" in incomplete
    assert "MYM" in incomplete
    assert "RTY" in incomplete
