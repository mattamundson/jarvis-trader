"""Leakage-resistant time-series validation primitives for Judge V3.

This module implements combinatorial group splits with two protections:
1. PURGING: remove training samples whose label-information interval overlaps
   any test sample's label-information interval.
2. EMBARGO: remove a configurable number of samples immediately following each
   contiguous test block.

It intentionally does not score strategies or select parameters. It only emits
validated train/test index sets for downstream WFO/CPCV research.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb
from typing import Iterable

import numpy as np


class PurgedValidationError(ValueError):
    """Raised when validation geometry is malformed or cannot be made leakage-safe."""


@dataclass(frozen=True)
class PurgedSplit:
    split_id: int
    test_groups: tuple[int, ...]
    train_indices: np.ndarray
    test_indices: np.ndarray
    purged_indices: np.ndarray
    embargoed_indices: np.ndarray

    def assert_disjoint(self) -> None:
        if np.intersect1d(self.train_indices, self.test_indices).size:
            raise PurgedValidationError(f"split {self.split_id}: train/test overlap")


def _validate_label_ends(n_samples: int, label_end_positions: Iterable[int] | None) -> np.ndarray:
    if label_end_positions is None:
        return np.arange(n_samples, dtype=int)
    ends = np.asarray(list(label_end_positions), dtype=int)
    if len(ends) != n_samples:
        raise PurgedValidationError("label_end_positions length must equal n_samples")
    starts = np.arange(n_samples, dtype=int)
    if np.any(ends < starts):
        raise PurgedValidationError("label end cannot precede sample start")
    if np.any(ends >= n_samples):
        raise PurgedValidationError("label end must be within the supplied sample range")
    return ends


def _contiguous_blocks(indices: np.ndarray) -> list[tuple[int, int]]:
    if len(indices) == 0:
        return []
    ordered = np.sort(np.unique(indices))
    blocks: list[tuple[int, int]] = []
    start = previous = int(ordered[0])
    for value in ordered[1:]:
        current = int(value)
        if current != previous + 1:
            blocks.append((start, previous))
            start = current
        previous = current
    blocks.append((start, previous))
    return blocks


def _purge_mask(
    candidate_train: np.ndarray,
    test_indices: np.ndarray,
    label_ends: np.ndarray,
) -> np.ndarray:
    """Return mask for train samples whose [start,end] overlaps any test label interval."""
    keep = np.ones(len(candidate_train), dtype=bool)
    test_starts = test_indices
    test_ends = label_ends[test_indices]
    for position, train_start in enumerate(candidate_train):
        train_end = label_ends[train_start]
        overlaps = (train_start <= test_ends) & (train_end >= test_starts)
        if np.any(overlaps):
            keep[position] = False
    return keep


def combinatorial_purged_splits(
    n_samples: int,
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    label_end_positions: Iterable[int] | None = None,
    embargo_samples: int = 0,
    require_nonempty_train: bool = True,
) -> list[PurgedSplit]:
    """Generate group-combinatorial train/test splits with purging and embargo.

    Parameters
    ----------
    n_samples:
        Number of chronologically ordered samples. Sample start position is its
        integer position 0..n_samples-1.
    n_groups:
        Number of chronological groups used for combinations. Groups are formed
        with ``numpy.array_split`` so their sizes differ by at most one sample.
    n_test_groups:
        Number of groups selected as test data in each combination.
    label_end_positions:
        Inclusive integer end position of each sample's information/label window.
        If omitted, labels are instantaneous at their sample position.
    embargo_samples:
        Number of sample positions immediately after every contiguous test block
        excluded from training.

    Returns exactly C(n_groups, n_test_groups) splits unless a requested split
    cannot retain training data and ``require_nonempty_train`` is True, in which
    case the function fails closed.
    """
    if n_samples <= 1:
        raise PurgedValidationError("n_samples must be greater than 1")
    if n_groups < 2 or n_groups > n_samples:
        raise PurgedValidationError("n_groups must be between 2 and n_samples")
    if n_test_groups <= 0 or n_test_groups >= n_groups:
        raise PurgedValidationError("n_test_groups must be between 1 and n_groups-1")
    if embargo_samples < 0:
        raise PurgedValidationError("embargo_samples must be non-negative")

    label_ends = _validate_label_ends(n_samples, label_end_positions)
    all_indices = np.arange(n_samples, dtype=int)
    groups = [np.asarray(group, dtype=int) for group in np.array_split(all_indices, n_groups)]
    splits: list[PurgedSplit] = []

    for split_id, selected_groups in enumerate(combinations(range(n_groups), n_test_groups), start=1):
        test_indices = np.sort(np.concatenate([groups[group] for group in selected_groups]))
        candidate_train = np.setdiff1d(all_indices, test_indices, assume_unique=True)

        keep_after_purge = _purge_mask(candidate_train, test_indices, label_ends)
        purged_indices = candidate_train[~keep_after_purge]
        train_after_purge = candidate_train[keep_after_purge]

        embargoed: set[int] = set()
        if embargo_samples:
            for _, block_end in _contiguous_blocks(test_indices):
                embargo_start = block_end + 1
                embargo_end = min(n_samples, embargo_start + embargo_samples)
                embargoed.update(range(embargo_start, embargo_end))
        embargoed_indices = np.asarray(
            sorted(set(train_after_purge).intersection(embargoed)), dtype=int
        )
        train_indices = np.setdiff1d(
            train_after_purge, embargoed_indices, assume_unique=True
        )

        if require_nonempty_train and len(train_indices) == 0:
            raise PurgedValidationError(
                f"split {split_id} has no training observations after purge/embargo"
            )

        split = PurgedSplit(
            split_id=split_id,
            test_groups=tuple(selected_groups),
            train_indices=train_indices,
            test_indices=test_indices,
            purged_indices=purged_indices,
            embargoed_indices=embargoed_indices,
        )
        split.assert_disjoint()
        splits.append(split)

    expected = comb(n_groups, n_test_groups)
    if len(splits) != expected:
        raise PurgedValidationError(f"expected {expected} splits, generated {len(splits)}")
    return splits


def assert_no_label_overlap(split: PurgedSplit, label_end_positions: Iterable[int]) -> None:
    """Fail if any retained training label interval overlaps a test label interval."""
    ends = np.asarray(list(label_end_positions), dtype=int)
    for train_start in split.train_indices:
        train_end = ends[train_start]
        for test_start in split.test_indices:
            test_end = ends[test_start]
            if train_start <= test_end and train_end >= test_start:
                raise PurgedValidationError(
                    f"split {split.split_id}: train interval [{train_start},{train_end}] "
                    f"overlaps test interval [{test_start},{test_end}]"
                )
