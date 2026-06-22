"""
Unit tests for engine/backtest/cpcv.py (Combinatorial Purged Cross-Validation).

Pure unit tests — no imports from main, no live data, no network.
Runs fast cross-worktree using the main checkout venv.

Test plan:
  1. generate_cpcv_folds returns C(n_groups, n_test_groups) folds.
  2. LEAKAGE GUARD: no train bar inside a test block or its purge/embargo zone.
  3. PATH COVERAGE: each group appears in the test set the expected number of times.
  4. generate_groups returns contiguous, time-ordered, near-equal-size blocks
     covering all bars exactly once.
  5. _session_bars returns a sane positive int on a synthetic 5m RTH index.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.cpcv import (
    CPCVFold,
    _session_bars,
    generate_cpcv_folds,
    generate_groups,
    purge_embargo,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_rth_5m_index(n_days: int = 40) -> pd.DatetimeIndex:
    """Synthetic 5m RTH index: 09:30-16:00 ET, weekdays only.

    Each day has 78 bars (6.5 hr * 12 bars/hr).
    """
    bars = []
    day = pd.Timestamp("2024-01-02", tz="America/New_York")
    added = 0
    while added < n_days:
        if day.weekday() < 5:  # Mon-Fri
            session = pd.date_range(
                start=day.replace(hour=9, minute=30),
                end=day.replace(hour=16, minute=0),
                freq="5min",
                tz="America/New_York",
            )
            bars.extend(session.tolist())
            added += 1
        day += pd.Timedelta(days=1)
    return pd.DatetimeIndex(bars)


def _make_simple_index(n_bars: int = 300) -> pd.DatetimeIndex:
    """Plain minute-frequency index for deterministic testing."""
    return pd.date_range("2024-01-01", periods=n_bars, freq="1min", tz="UTC")


# ---------------------------------------------------------------------------
# Test 1 — fold count equals C(n_groups, n_test_groups)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_groups,n_test", [
    (6, 2),   # C(6,2) = 15 — default
    (4, 2),   # C(4,2) = 6
    (5, 2),   # C(5,2) = 10
    (6, 3),   # C(6,3) = 20
])
def test_fold_count_equals_combination(n_groups, n_test):
    """generate_cpcv_folds must return exactly C(n_groups, n_test_groups) folds."""
    index = _make_simple_index(n_bars=n_groups * 50)
    folds = generate_cpcv_folds(index, n_groups=n_groups, n_test_groups=n_test,
                                 embargo_sessions=0, purge_sessions=0)
    expected = math.comb(n_groups, n_test)
    assert len(folds) == expected, (
        f"Expected {expected} folds for C({n_groups},{n_test}), got {len(folds)}"
    )


def test_default_params_yield_15_folds():
    """Default n_groups=6, n_test_groups=2 => C(6,2)=15."""
    index = _make_rth_5m_index(n_days=40)
    folds = generate_cpcv_folds(index)
    assert len(folds) == 15


# ---------------------------------------------------------------------------
# Test 2 — LEAKAGE GUARD: train indices must not contaminate test blocks
# ---------------------------------------------------------------------------

def test_no_leakage_in_any_fold():
    """For every fold: no train bar inside the test block or purge/embargo zone."""
    # Use a multi-session synthetic index so purge/embargo actually bite
    index = _make_rth_5m_index(n_days=40)  # 40 days * 78 bars = 3120 bars
    folds = generate_cpcv_folds(
        index,
        n_groups=6,
        n_test_groups=2,
        embargo_sessions=1,   # 1 session = ~78 bars after test
        purge_sessions=14,    # 14 sessions before test
    )

    bars_per_session = _session_bars(index)
    embargo_bars = 1 * bars_per_session
    purge_bars   = 14 * bars_per_session

    for fold in folds:
        train_set = set(fold.train_idx.tolist())
        test_sorted = np.sort(fold.test_idx)

        # Identify contiguous test block boundaries
        if len(test_sorted) == 0:
            continue
        gaps = np.where(np.diff(test_sorted) > 1)[0]
        block_starts = np.concatenate([[test_sorted[0]], test_sorted[gaps + 1]])
        block_ends   = np.concatenate([test_sorted[gaps], [test_sorted[-1]]])

        for start, end in zip(block_starts, block_ends, strict=False):
            # 1. No train bar INSIDE the test block
            for pos in range(start, end + 1):
                assert pos not in train_set, (
                    f"Fold {fold.fold_id}: test pos {pos} found in train_idx"
                )
            # 2. No train bar in purge zone (before start)
            for pos in range(max(0, start - purge_bars), start):
                assert pos not in train_set, (
                    f"Fold {fold.fold_id}: purge-zone pos {pos} found in train_idx "
                    f"(purge_bars={purge_bars}, block_start={start})"
                )
            # 3. No train bar in embargo zone (after end)
            n = len(index)
            for pos in range(end + 1, min(n, end + 1 + embargo_bars)):
                assert pos not in train_set, (
                    f"Fold {fold.fold_id}: embargo-zone pos {pos} found in train_idx "
                    f"(embargo_bars={embargo_bars}, block_end={end})"
                )


def test_no_leakage_zero_purge_embargo():
    """With purge=0/embargo=0, train and test must still be disjoint."""
    index = _make_simple_index(300)
    folds = generate_cpcv_folds(index, n_groups=4, n_test_groups=2,
                                 embargo_sessions=0, purge_sessions=0)
    for fold in folds:
        overlap = np.intersect1d(fold.train_idx, fold.test_idx)
        assert len(overlap) == 0, (
            f"Fold {fold.fold_id}: {len(overlap)} positions appear in both train and test"
        )


# ---------------------------------------------------------------------------
# Test 3 — PATH COVERAGE: each group appears in test set expected number of times
# ---------------------------------------------------------------------------

def test_each_group_appears_in_test_set_expected_times():
    """Each of the n_groups groups must appear in exactly C(n_groups-1, n_test-1) folds."""
    n_groups, n_test = 6, 2
    index = _make_simple_index(n_bars=n_groups * 50)
    folds = generate_cpcv_folds(index, n_groups=n_groups, n_test_groups=n_test,
                                 embargo_sessions=0, purge_sessions=0)
    # Each group appears in C(n_groups-1, n_test-1) = C(5,1) = 5 folds
    expected_per_group = math.comb(n_groups - 1, n_test - 1)
    counts = dict.fromkeys(range(n_groups), 0)
    for fold in folds:
        for g in fold.test_group_ids:
            counts[g] += 1
    for g, cnt in counts.items():
        assert cnt == expected_per_group, (
            f"Group {g} appeared in {cnt} test folds, expected {expected_per_group}"
        )


# ---------------------------------------------------------------------------
# Test 4 — generate_groups: contiguous, time-ordered, equal-ish, covers all
# ---------------------------------------------------------------------------

def test_generate_groups_covers_all_bars():
    """All positional indices must appear exactly once across all groups."""
    n_bars = 317  # intentionally non-divisible
    index = _make_simple_index(n_bars)
    n_groups = 6
    groups = generate_groups(index, n_groups)
    assert len(groups) == n_groups
    all_indices = np.concatenate(groups)
    assert len(all_indices) == n_bars, f"Expected {n_bars} total, got {len(all_indices)}"
    assert len(np.unique(all_indices)) == n_bars, "Duplicate indices in groups"
    assert set(all_indices.tolist()) == set(range(n_bars)), "Missing indices in groups"


def test_generate_groups_are_contiguous_and_ordered():
    """Each group must be a contiguous block, and groups must be time-ordered."""
    index = _make_simple_index(200)
    n_groups = 5
    groups = generate_groups(index, n_groups)
    prev_end = -1
    for i, grp in enumerate(groups):
        # Each group must be sorted
        assert np.all(np.diff(grp) == 1) or len(grp) == 1, (
            f"Group {i} is not contiguous"
        )
        # Each group must start right after the previous one
        assert grp[0] == prev_end + 1, (
            f"Group {i} starts at {grp[0]}, expected {prev_end + 1}"
        )
        prev_end = grp[-1]
    assert prev_end == len(index) - 1, "Last group does not end at final bar"


def test_generate_groups_near_equal_size():
    """Groups must be within 1 bar of each other in size (numpy array_split guarantee)."""
    n_bars, n_groups = 100, 6
    index = _make_simple_index(n_bars)
    groups = generate_groups(index, n_groups)
    sizes = [len(g) for g in groups]
    assert max(sizes) - min(sizes) <= 1, (
        f"Group sizes vary by more than 1: {sizes}"
    )


def test_generate_groups_raises_on_too_few_bars():
    """Must raise ValueError when n_bars < n_groups."""
    index = _make_simple_index(3)
    with pytest.raises(ValueError, match="n_bars"):
        generate_groups(index, n_groups=5)


# ---------------------------------------------------------------------------
# Test 5 — _session_bars returns sane positive int on a synthetic 5m RTH index
# ---------------------------------------------------------------------------

def test_session_bars_5m_rth():
    """_session_bars should return ~78 for a 5m RTH index."""
    index = _make_rth_5m_index(n_days=20)
    result = _session_bars(index)
    assert isinstance(result, int), f"Expected int, got {type(result)}"
    assert result > 0, "session_bars must be positive"
    # 5m RTH: 09:30 -> 16:00 = 78 bars; allow slight slack for start/end inclusive
    assert 70 <= result <= 90, f"Expected ~78 bars/session for 5m RTH, got {result}"


def test_session_bars_empty_returns_default():
    """Empty index returns the fallback default (78)."""
    empty = pd.DatetimeIndex([])
    result = _session_bars(empty)
    assert result == 78


# ---------------------------------------------------------------------------
# Additional: CPCVFold is a proper dataclass with expected fields
# ---------------------------------------------------------------------------

def test_cpcv_fold_fields():
    """CPCVFold must expose fold_id, test_group_ids, train_idx, test_idx."""
    fold = CPCVFold(
        fold_id=0,
        test_group_ids=(0, 1),
        train_idx=np.array([2, 3, 4]),
        test_idx=np.array([0, 1]),
    )
    assert fold.fold_id == 0
    assert fold.test_group_ids == (0, 1)
    assert len(fold.train_idx) == 3
    assert len(fold.test_idx) == 2


# ---------------------------------------------------------------------------
# Additional: purge_embargo with no test blocks is a no-op
# ---------------------------------------------------------------------------

def test_purge_embargo_empty_test():
    """purge_embargo with empty test_idx returns train_idx unchanged."""
    index = _make_simple_index(100)
    train_idx = np.arange(50)
    result = purge_embargo(index, train_idx, np.array([], dtype=int),
                           embargo_bars=10, purge_bars=5)
    np.testing.assert_array_equal(result, train_idx)
