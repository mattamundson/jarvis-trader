"""Known-answer tests for purged k-fold splits."""

from __future__ import annotations

import numpy as np
import pytest

from backtest.factory.purged_kfold import purged_kfold_splits


def test_plain_kfold_when_no_purge():
    """embargo=0, horizon=0 -> ordinary k-fold: train = complement of test."""
    splits = list(purged_kfold_splits(10, n_splits=5, embargo=0.0))
    assert len(splits) == 5
    all_test = []
    for train, test in splits:
        all_test.extend(test.tolist())
        # disjoint
        assert set(train).isdisjoint(set(test))
        # union covers everything (no purge)
        assert sorted(set(train) | set(test)) == list(range(10))
    # test folds tile the whole range, contiguous and in order
    assert all_test == list(range(10))


def test_test_folds_are_contiguous_and_ordered():
    splits = list(purged_kfold_splits(100, n_splits=5, embargo=0.0))
    starts = [int(test[0]) for _, test in splits]
    assert starts == sorted(starts)
    for _, test in splits:
        assert list(test) == list(range(int(test[0]), int(test[-1]) + 1))


def test_embargo_removes_band_after_test_fold():
    """embargo=0.1 on n=10 -> 1 bar purged immediately after each test fold."""
    splits = list(purged_kfold_splits(10, n_splits=5, embargo=0.1))
    # fold 1 = [2,3]; embargo should drop index 4 from train
    train, test = splits[1]
    assert list(test) == [2, 3]
    assert 4 not in train, "embargoed bar right after the test fold must be purged"
    assert 5 in train, "bar beyond the embargo band stays in train"


def test_purge_horizon_removes_both_sides():
    train, test = next(purged_kfold_splits(20, n_splits=4, embargo=0.0, label_horizon=1))
    # first fold = [0..4]; horizon=1 purges index 5 on the right (nothing on left)
    assert 5 not in train
    assert 6 in train


def test_validation_errors():
    with pytest.raises(ValueError):
        list(purged_kfold_splits(10, n_splits=1))
    with pytest.raises(ValueError):
        list(purged_kfold_splits(3, n_splits=5))
    with pytest.raises(ValueError):
        list(purged_kfold_splits(10, n_splits=5, embargo=1.5))
