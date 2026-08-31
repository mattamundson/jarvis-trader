"""Tests for leakage-resistant combinatorial validation splitting."""

from __future__ import annotations

from math import comb

import numpy as np
import pytest

from backtest.purged_validation import (
    PurgedValidationError,
    assert_no_label_overlap,
    combinatorial_purged_splits,
)


def test_split_count_matches_combinatorial_geometry() -> None:
    splits = combinatorial_purged_splits(60, n_groups=6, n_test_groups=2)
    assert len(splits) == comb(6, 2) == 15
    assert {split.test_groups for split in splits} == set(
        __import__("itertools").combinations(range(6), 2)
    )


def test_overlapping_label_horizons_are_purged_from_training() -> None:
    # Every label spans itself plus two future samples where possible.
    n = 24
    ends = np.minimum(np.arange(n) + 2, n - 1)
    splits = combinatorial_purged_splits(
        n,
        n_groups=4,
        n_test_groups=1,
        label_end_positions=ends,
    )

    for split in splits:
        assert_no_label_overlap(split, ends)
        assert not np.intersect1d(split.train_indices, split.test_indices).size

    # For the second chronological test group (positions 6..11), positions 4,5
    # must be purged because their labels reach into the test interval.
    split = next(item for item in splits if item.test_groups == (1,))
    assert {4, 5}.issubset(set(split.purged_indices))


def test_embargo_removes_samples_after_each_test_block() -> None:
    splits = combinatorial_purged_splits(
        30,
        n_groups=5,
        n_test_groups=1,
        embargo_samples=2,
    )
    first = next(item for item in splits if item.test_groups == (0,))
    # Group 0 is 0..5, so 6 and 7 are embargoed.
    assert first.embargoed_indices.tolist() == [6, 7]
    assert 6 not in first.train_indices
    assert 7 not in first.train_indices


def test_separated_test_groups_receive_separate_embargo_windows() -> None:
    splits = combinatorial_purged_splits(
        30,
        n_groups=5,
        n_test_groups=2,
        embargo_samples=1,
    )
    split = next(item for item in splits if item.test_groups == (0, 2))
    # groups: 0..5, 6..11, 12..17, 18..23, 24..29
    # embargo after group 0 -> 6; after group 2 -> 18.
    assert split.embargoed_indices.tolist() == [6, 18]


def test_adjacent_selected_groups_are_one_contiguous_test_block() -> None:
    splits = combinatorial_purged_splits(
        30,
        n_groups=5,
        n_test_groups=2,
        embargo_samples=1,
    )
    split = next(item for item in splits if item.test_groups == (0, 1))
    # Test interval is contiguous 0..11; only 12 is embargoed.
    assert split.embargoed_indices.tolist() == [12]


def test_invalid_label_end_geometry_fails_closed() -> None:
    with pytest.raises(PurgedValidationError, match="cannot precede"):
        combinatorial_purged_splits(
            5,
            n_groups=2,
            n_test_groups=1,
            label_end_positions=[0, 0, 2, 3, 4],
        )
    with pytest.raises(PurgedValidationError, match="within"):
        combinatorial_purged_splits(
            5,
            n_groups=2,
            n_test_groups=1,
            label_end_positions=[0, 1, 2, 3, 5],
        )


def test_aggressive_purge_can_fail_nonempty_train_gate() -> None:
    # Every training label stretches to the end of the dataset; selecting a
    # late test group purges all earlier training observations.
    ends = [7] * 8
    with pytest.raises(PurgedValidationError, match="no training observations"):
        combinatorial_purged_splits(
            8,
            n_groups=2,
            n_test_groups=1,
            label_end_positions=ends,
            require_nonempty_train=True,
        )
