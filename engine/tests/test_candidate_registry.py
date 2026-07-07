"""Tests for the pre-registered candidate registry (ROI #6).

Covers: the shipped registry loads + validates; verify_registry catches the
structural failure modes (duplicate id, bad status, empty params, missing
fields); active-candidate filtering; and the graduation rule -- including the
fail-closed defaults so a half-populated stat block can never graduate.
"""
from __future__ import annotations

import copy

import pytest

from backtest import candidate_registry as cr


def test_shipped_registry_loads_and_validates():
    reg = cr.load_registry()
    assert reg["schema_version"] == 1
    assert len(reg["candidates"]) >= 1
    # the MGC trend nucleus must be present and forward_testing
    active_ids = {c["id"] for c in cr.get_active_candidates(reg)}
    assert "MGC_trend_rv_filter_rank1" in active_ids


def test_shipped_registry_params_are_locked():
    c = cr.get_candidate("MGC_trend_rv_filter_rank1")
    assert c is not None
    # params frozen exactly as the gate-v2 champion
    assert c["params"] == {
        "fast": 50, "slow": 120, "atr_trail_mult": 2.0, "min_rv_annualized": 9.0,
    }
    assert c["lock_in_sample"]["pf_ci_lower"] == pytest.approx(3.1819)


def test_verify_catches_duplicate_id():
    reg = cr.load_registry()
    bad = copy.deepcopy(reg)
    bad["candidates"].append(copy.deepcopy(bad["candidates"][0]))
    problems = cr.verify_registry(bad)
    assert any("duplicate candidate id" in p for p in problems)


def test_verify_catches_bad_status():
    reg = cr.load_registry()
    bad = copy.deepcopy(reg)
    bad["candidates"][0]["status"] = "live_for_real"  # not in allowed_status
    problems = cr.verify_registry(bad)
    assert any("not in allowed_status" in p for p in problems)


def test_verify_catches_empty_params():
    reg = cr.load_registry()
    bad = copy.deepcopy(reg)
    bad["candidates"][0]["params"] = {}
    problems = cr.verify_registry(bad)
    assert any("params must be a non-empty object" in p for p in problems)


def test_verify_catches_missing_field():
    reg = cr.load_registry()
    bad = copy.deepcopy(reg)
    del bad["candidates"][0]["hypothesis"]
    problems = cr.verify_registry(bad)
    assert any("missing/empty 'hypothesis'" in p for p in problems)


def test_load_raises_on_invalid(tmp_path):
    import json
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema_version": 1, "candidates": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        cr.load_registry(str(p))


def test_graduation_requires_all_conditions():
    reg = cr.load_registry()
    passing = {
        "n_oos_windows": 8,
        "pf_ci_lower": 1.5,
        "p_edge": 0.97,
        "survives_family_fdr": True,
    }
    assert cr.meets_graduation(passing, reg) is True


def test_graduation_fails_closed_on_missing_keys():
    reg = cr.load_registry()
    # empty stats -> every threshold defaults to fail
    assert cr.meets_graduation({}, reg) is False


def test_graduation_fails_when_fdr_not_survived():
    reg = cr.load_registry()
    stats = {
        "n_oos_windows": 8,
        "pf_ci_lower": 1.5,
        "p_edge": 0.97,
        "survives_family_fdr": False,
    }
    assert cr.meets_graduation(stats, reg) is False


def test_graduation_fails_on_too_few_windows():
    reg = cr.load_registry()
    stats = {
        "n_oos_windows": 2,
        "pf_ci_lower": 5.0,
        "p_edge": 1.0,
        "survives_family_fdr": True,
    }
    assert cr.meets_graduation(stats, reg) is False
