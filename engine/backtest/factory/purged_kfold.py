"""Purged k-fold cross-validation with an embargo.

Per Lopez de Prado, "Advances in Financial Machine Learning" (2018), ch. 7.
Standard k-fold leaks information in time series because train observations
adjacent to the test fold share overlapping information (serial correlation,
multi-bar labels). PurgedKFold removes (purges) train observations whose
information window overlaps the test fold, and embargoes a band of observations
immediately AFTER each test fold.

Here each observation is one bar/return (label horizon defaults to 0), so
purging removes the `label_horizon` train bars on each side of the test fold and
the `embargo` fraction of bars following it.
"""

from __future__ import annotations

import numpy as np


def purged_kfold_splits(
    n_obs: int,
    n_splits: int = 5,
    embargo: float = 0.0,
    label_horizon: int = 0,
):
    """Yield (train_idx, test_idx) index arrays with purge + embargo.

    Args:
        n_obs: number of time-ordered observations.
        n_splits: number of contiguous test folds.
        embargo: fraction of n_obs to embargo immediately after each test fold.
        label_horizon: bars a label spans; that many train bars on each side of
            the test fold are purged (0 for single-bar returns).

    Yields:
        (train_idx, test_idx) numpy int arrays, test folds contiguous and in order.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    if n_splits > n_obs:
        raise ValueError(f"n_splits ({n_splits}) > n_obs ({n_obs})")
    if not (0.0 <= embargo < 1.0):
        raise ValueError("embargo must be in [0, 1)")

    indices = np.arange(n_obs)
    fold_bounds = np.array_split(indices, n_splits)
    embargo_size = int(round(embargo * n_obs))

    for fold in fold_bounds:
        test_start, test_end = int(fold[0]), int(fold[-1])
        test_idx = np.arange(test_start, test_end + 1)

        # Purge: drop train bars whose label window touches the test fold.
        purge_lo = test_start - label_horizon
        purge_hi = test_end + label_horizon
        # Embargo: drop a band immediately after the test fold.
        embargo_hi = purge_hi + embargo_size

        train_mask = np.ones(n_obs, dtype=bool)
        train_mask[max(0, purge_lo) : min(n_obs, embargo_hi + 1)] = False
        train_idx = indices[train_mask]
        yield train_idx, test_idx
