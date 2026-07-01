"""Tests for the risk-of-ruin Monte Carlo (analytics/risk_of_ruin.py).

Deterministic via seeded RNG; small n_paths for speed. Asserts the qualitative
invariants the readout depends on rather than exact floats.
"""

from __future__ import annotations

import numpy as np

from analytics.risk_of_ruin import (
    DEFAULT_CAPITAL,
    DEFAULT_SCENARIOS,
    estimate_ruin,
    simulate_path,
    sweep,
)


def test_ruin_monotonic_in_risk_fraction():
    """Higher per-trade risk -> higher ruin probability, holding edge fixed."""
    wr, r = 0.42, 1.8  # trend-like positive edge
    r1 = estimate_ruin(wr, r, 0.01, n_paths=4000).ruin_prob
    r2 = estimate_ruin(wr, r, 0.02, n_paths=4000).ruin_prob
    r3 = estimate_ruin(wr, r, 0.03, n_paths=4000).ruin_prob
    assert r1 < r2 < r3


def test_positive_edge_still_ruins_at_high_fraction():
    """The core finding: a genuine edge is NOT safe at 3% sizing under a -20% halt."""
    res = estimate_ruin(0.40, 2.5, 0.03, n_paths=4000)  # strong trend edge
    assert res.ruin_prob > 0.5


def test_low_fraction_protects_real_edge():
    """At 1% sizing a real trend edge has modest ruin and a healthy median."""
    res = estimate_ruin(0.42, 1.8, 0.01, n_paths=4000)
    assert res.ruin_prob < 0.30
    assert res.median_equity > DEFAULT_CAPITAL


def test_ruined_path_never_exceeds_kill_threshold_at_end():
    """A path flagged ruined must have breached the drawdown kill from its peak."""
    rng = np.random.default_rng(1)
    # Negative edge, high risk -> almost certainly ruins quickly.
    ruined, term = simulate_path(0.30, 1.0, 0.05, rng)
    if ruined:
        # equity at ruin is at/below 80% of the initial peak (peak >= capital)
        assert term <= DEFAULT_CAPITAL * (1.0 - 0.20) + 1e-6


def test_sweep_shape():
    rows = sweep(risk_levels=(0.01, 0.03), n_paths=1000)
    assert len(rows) == len(DEFAULT_SCENARIOS) * 2
    labels = {label for label, _ in rows}
    assert "trend edge (WR42/R1.8)" in labels


def test_determinism():
    a = estimate_ruin(0.5, 1.2, 0.02, n_paths=2000, seed=7).ruin_prob
    b = estimate_ruin(0.5, 1.2, 0.02, n_paths=2000, seed=7).ruin_prob
    assert a == b
