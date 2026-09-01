"""Tests for bounded MES VWAP rank1 runner controls."""

from __future__ import annotations

import pytest

from backtest.run_mes_vwap_rank1 import _normalize_run_bounds


def test_smoke_run_is_noncanonical_and_suffixed():
    bounds = _normalize_run_bounds(
        smoke=True,
        max_windows=None,
        max_grid_combos=None,
        skip_fixed_sweep=False,
        skip_cost_sweep=False,
        output_suffix=None,
    )

    assert bounds["canonical"] is False
    assert bounds["run_mode"] == "smoke"
    assert bounds["max_windows"] == 1
    assert bounds["max_grid_combos"] == 4
    assert bounds["skip_fixed_sweep"] is True
    assert bounds["skip_cost_sweep"] is True
    assert bounds["output_suffix"] == "smoke"


def test_bounded_run_gets_safe_default_suffix():
    bounds = _normalize_run_bounds(
        smoke=False,
        max_windows=2,
        max_grid_combos=None,
        skip_fixed_sweep=False,
        skip_cost_sweep=False,
        output_suffix=None,
    )

    assert bounds["canonical"] is False
    assert bounds["run_mode"] == "bounded"
    assert bounds["output_suffix"] == "bounded"


def test_canonical_run_keeps_unsuffixed_output():
    bounds = _normalize_run_bounds(
        smoke=False,
        max_windows=None,
        max_grid_combos=None,
        skip_fixed_sweep=False,
        skip_cost_sweep=False,
        output_suffix=None,
    )

    assert bounds["canonical"] is True
    assert bounds["run_mode"] == "canonical"
    assert bounds["output_suffix"] is None


def test_nonpositive_bounds_are_rejected():
    with pytest.raises(ValueError, match="max_windows"):
        _normalize_run_bounds(
            smoke=False,
            max_windows=0,
            max_grid_combos=None,
            skip_fixed_sweep=False,
            skip_cost_sweep=False,
            output_suffix=None,
        )
