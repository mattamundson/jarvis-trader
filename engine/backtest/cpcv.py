"""
Combinatorial Purged Cross-Validation (CPCV) — Lopez de Prado AFML ch.7/12.

Generates C(n_groups, n_test_groups) OOS folds from a time-series index,
with purging (before test block) and embargoing (after test block) to prevent
feature look-ahead and holding-period leakage.

Pure numpy/pandas, no new dependencies. Designed as an opt-in supplement to
sequential WFO — it must not alter sequential verdicts.

Usage:
    from backtest.cpcv import generate_cpcv_folds, CPCVFold
    folds = generate_cpcv_folds(df.index, n_groups=6, n_test_groups=2)
    for fold in folds:
        df_train = df.iloc[fold.train_idx]
        df_test  = df.iloc[fold.test_idx]
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class CPCVFold:
    """One combinatorial fold (a specific choice of test groups)."""
    fold_id: int
    test_group_ids: tuple[int, ...]
    train_idx: np.ndarray   # positional indices into the source df
    test_idx: np.ndarray    # positional indices into the source df


def generate_groups(index: pd.DatetimeIndex, n_groups: int) -> list[np.ndarray]:
    """Split *index* into n_groups contiguous, time-ordered, equal-bar-count blocks.

    Returns a list of n_groups arrays of positional (integer) indices into index.
    Groups are as equal as possible; excess bars go to earlier groups.
    """
    if n_groups < 1:
        raise ValueError(f"n_groups must be >= 1, got {n_groups}")
    n_bars = len(index)
    if n_bars < n_groups:
        raise ValueError(
            f"n_bars={n_bars} < n_groups={n_groups}; not enough data to form groups"
        )
    all_pos = np.arange(n_bars)
    # np.array_split distributes remainder to FRONT groups — contiguous & covers all bars
    return list(np.array_split(all_pos, n_groups))


def _session_bars(index: pd.DatetimeIndex) -> int:
    """Estimate number of bars per RTH session from a DatetimeIndex.

    Uses the median count of bars per calendar date. Falls back to 78 (5m RTH)
    if the index is empty or too sparse to compute.
    """
    if len(index) == 0:
        return 78  # 5m RTH default: 6.5hr * 12 bars/hr
    # Localise to Eastern (or strip tz) for date grouping
    try:
        dates = index.tz_convert("America/New_York").date
    except Exception:
        dates = index.date
    counts = pd.Series(dates).value_counts()
    median_val = int(np.median(counts.values))
    return max(1, median_val)


def purge_embargo(
    index: pd.DatetimeIndex,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    embargo_bars: int,
    purge_bars: int,
) -> np.ndarray:
    """Remove contaminated training bars around test blocks.

    Drops from train_idx:
    - Any bar within `purge_bars` positions BEFORE the start of each contiguous
      test block (feature warm-up leak — label constructed partly from train period).
    - Any bar within `embargo_bars` positions AFTER the end of each contiguous
      test block (holding / label decay leak).

    Returns the cleaned train_idx (sorted, no duplicates).
    """
    if len(test_idx) == 0 or (purge_bars == 0 and embargo_bars == 0):
        return train_idx

    test_sorted = np.sort(test_idx)
    # Find contiguous test blocks by detecting gaps
    gaps = np.where(np.diff(test_sorted) > 1)[0]
    # block_starts[i] -> position of first bar in block i
    block_starts = np.concatenate([[test_sorted[0]], test_sorted[gaps + 1]])
    block_ends   = np.concatenate([test_sorted[gaps], [test_sorted[-1]]])

    forbidden = set()
    n = len(index)
    for start, end in zip(block_starts, block_ends, strict=False):
        if purge_bars > 0:
            for pos in range(max(0, start - purge_bars), start):
                forbidden.add(pos)
        if embargo_bars > 0:
            for pos in range(end + 1, min(n, end + 1 + embargo_bars)):
                forbidden.add(pos)

    mask = np.isin(train_idx, list(forbidden), invert=True)
    return train_idx[mask]


def generate_cpcv_folds(
    index: pd.DatetimeIndex,
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo_sessions: int = 1,
    purge_sessions: int = 14,
) -> list[CPCVFold]:
    """Generate C(n_groups, n_test_groups) CPCV folds.

    For each combination of n_test_groups chosen from n_groups:
      - test_idx  = union of bars in those groups
      - train_idx = all remaining bars, minus purge/embargo neighbourhood
                    (sessions converted to bars via _session_bars)

    With defaults (n_groups=6, n_test_groups=2) returns 15 folds.

    Parameters
    ----------
    index           : DatetimeIndex of the full dataset (df.index)
    n_groups        : number of contiguous time groups to partition data into
    n_test_groups   : size of each test-group combination
    embargo_sessions: sessions to drop from train AFTER each test block
    purge_sessions  : sessions to drop from train BEFORE each test block
    """
    if n_test_groups >= n_groups:
        raise ValueError(
            f"n_test_groups={n_test_groups} must be < n_groups={n_groups}"
        )

    bars_per_session = _session_bars(index)
    embargo_bars = max(0, embargo_sessions * bars_per_session)
    purge_bars   = max(0, purge_sessions   * bars_per_session)

    groups = generate_groups(index, n_groups)
    all_positions = np.arange(len(index))

    folds: list[CPCVFold] = []
    for fold_id, test_group_combo in enumerate(
        itertools.combinations(range(n_groups), n_test_groups)
    ):
        # test_idx: union of positions in the chosen groups
        test_idx = np.concatenate([groups[g] for g in test_group_combo])
        test_idx = np.sort(test_idx)

        # train_idx: everything NOT in test_idx
        test_set = set(test_idx.tolist())
        train_idx = np.array([p for p in all_positions if p not in test_set])

        # apply purge + embargo
        train_idx = purge_embargo(index, train_idx, test_idx, embargo_bars, purge_bars)

        folds.append(CPCVFold(
            fold_id=fold_id,
            test_group_ids=tuple(test_group_combo),
            train_idx=train_idx,
            test_idx=test_idx,
        ))

    return folds
