"""Tests for eval_run.py Run-12 gate completeness (US-007).

Verifies that ITERATION_GATES and PRODUCTION_GATES contain the full Run-12
gate set including the skew and exposure additions (US-007 upgrade).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Import eval_run from scripts/ (not on sys.path by default)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
_EVAL_RUN_PATH = _SCRIPTS_DIR / "eval_run.py"


def _load_eval_run():
    """Dynamically import scripts/eval_run.py."""
    spec = importlib.util.spec_from_file_location("eval_run", _EVAL_RUN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Gate completeness
# ---------------------------------------------------------------------------

RUN_12_ITERATION_REQUIRED = {
    "profit_factor": (">=", 1.5),
    "win_rate": (">=", 0.52),
    "max_dd": ("<=", 0.20),
    "sortino": (">=", 1.0),
    "calmar": (">=", 0.5),
    "tail_ratio": (">=", 1.0),
    "gain_to_pain": (">=", 0.5),
    "consecutive_losses": ("<=", 8),
    "skew": (">=", -1.5),
    "exposure": (">=", 0.15),
}

RUN_12_PRODUCTION_REQUIRED_KEYS = {
    "sortino", "calmar", "tail_ratio", "gain_to_pain",
    "consecutive_losses", "skew", "exposure",
    "profit_factor", "win_rate", "max_dd",
}


def test_iteration_gates_contain_all_run12_keys():
    """ITERATION_GATES must contain every Run-12 key at the specified threshold."""
    mod = _load_eval_run()
    for key, (op, threshold) in RUN_12_ITERATION_REQUIRED.items():
        assert key in mod.ITERATION_GATES, f"ITERATION_GATES missing Run-12 key: {key}"
        actual_op, actual_thresh = mod.ITERATION_GATES[key]
        assert actual_op == op, f"{key}: expected op {op!r}, got {actual_op!r}"
        assert actual_thresh == pytest.approx(threshold), (
            f"{key}: expected threshold {threshold}, got {actual_thresh}"
        )


def test_production_gates_contain_all_run12_keys():
    """PRODUCTION_GATES must contain every Run-12 key (thresholds may be tighter)."""
    mod = _load_eval_run()
    for key in RUN_12_PRODUCTION_REQUIRED_KEYS:
        assert key in mod.PRODUCTION_GATES, f"PRODUCTION_GATES missing Run-12 key: {key}"


def test_skew_gate_iteration_threshold():
    """skew >= -1.5 in ITERATION_GATES (distribution quality floor)."""
    mod = _load_eval_run()
    op, thresh = mod.ITERATION_GATES["skew"]
    assert op == ">="
    assert thresh == pytest.approx(-1.5)


def test_exposure_gate_iteration_threshold():
    """exposure >= 0.15 in ITERATION_GATES (non-trivial deployment floor)."""
    mod = _load_eval_run()
    op, thresh = mod.ITERATION_GATES["exposure"]
    assert op == ">="
    assert thresh == pytest.approx(0.15)


def test_exposure_gate_production_tighter():
    """PRODUCTION_GATES exposure threshold >= ITERATION_GATES threshold."""
    mod = _load_eval_run()
    iter_thresh = mod.ITERATION_GATES["exposure"][1]
    prod_thresh = mod.PRODUCTION_GATES["exposure"][1]
    assert prod_thresh >= iter_thresh, (
        f"Production exposure ({prod_thresh}) must be >= iteration ({iter_thresh})"
    )


# ---------------------------------------------------------------------------
# Gate logic: skew and exposure actually filter bad metrics
# ---------------------------------------------------------------------------


def _make_returns_with_skew(target_skew: float, n: int = 120) -> pd.Series:
    """Return a daily returns series with approximate target skew."""
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2026-01-02", periods=n)
    if target_skew < -1.0:
        # Negatively skewed: mostly small gains, occasional big losses
        vals = rng.exponential(0.008, n)
        vals[::10] *= -5.0
    else:
        vals = rng.normal(0.001, 0.008, n)
    return pd.Series(vals, index=idx)


def test_skew_gate_logic_passes_mild_skew():
    """A series with skew > -1.5 should pass the skew gate."""
    from reports.quantstats_metrics import compute_quantstats_metrics

    returns = _make_returns_with_skew(target_skew=0.0)
    m = compute_quantstats_metrics(returns, source="pnl_snapshots")
    assert m["skew"] is not None
    assert m["skew"] >= -1.5, f"Expected mild-skew series to pass, got skew={m['skew']}"


def test_exposure_gate_logic_non_zero():
    """A series with non-zero returns has positive exposure."""
    from reports.quantstats_metrics import compute_quantstats_metrics

    rng = np.random.default_rng(42)
    idx = pd.bdate_range("2026-01-02", periods=90)
    returns = pd.Series(rng.normal(0.001, 0.01, 90), index=idx)
    m = compute_quantstats_metrics(returns, source="pnl_snapshots")
    assert m["exposure"] is not None
    assert m["exposure"] > 0.0, f"Expected positive exposure, got {m['exposure']}"


def test_no_existing_threshold_lowered():
    """Verify no existing Run-12 gate threshold was loosened vs. spec."""
    mod = _load_eval_run()
    floor_checks = {
        "sortino": (">=", 1.0),
        "calmar": (">=", 0.5),
        "tail_ratio": (">=", 1.0),
        "gain_to_pain": (">=", 0.5),
        "consecutive_losses": ("<=", 8),
    }
    for key, (op, min_thresh) in floor_checks.items():
        assert key in mod.ITERATION_GATES, f"Key {key} missing from ITERATION_GATES"
        actual_op, actual_thresh = mod.ITERATION_GATES[key]
        assert actual_op == op, f"{key}: op mismatch"
        if op == ">=":
            assert actual_thresh >= min_thresh, (
                f"{key} threshold was loosened: {actual_thresh} < {min_thresh}"
            )
        else:  # "<="
            assert actual_thresh <= min_thresh, (
                f"{key} threshold was loosened: {actual_thresh} > {min_thresh}"
            )
