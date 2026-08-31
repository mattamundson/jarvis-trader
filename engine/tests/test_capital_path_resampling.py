"""Tests for Capital Path bootstrap index generators."""

from __future__ import annotations

import numpy as np
import pytest

from backtest.capital_path_resampling import (
    ResamplingError,
    moving_block_indices,
    resample_indices,
    stationary_bootstrap_indices,
)


def test_moving_block_preserves_contiguous_runs() -> None:
    rng = np.random.default_rng(7)
    indices = moving_block_indices(10, 12, rng, block_size=3)
    assert len(indices) == 12
    for start in range(0, 12, 3):
        block = indices[start : start + 3]
        if len(block) < 2:
            continue
        for left, right in zip(block[:-1], block[1:]):
            assert right == (left + 1) % 10


def test_moving_block_is_reproducible_by_seed() -> None:
    first = moving_block_indices(20, 50, np.random.default_rng(123), block_size=5)
    second = moving_block_indices(20, 50, np.random.default_rng(123), block_size=5)
    np.testing.assert_array_equal(first, second)


def test_stationary_bootstrap_is_reproducible_and_bounded() -> None:
    first = stationary_bootstrap_indices(
        25, 100, np.random.default_rng(9), expected_block_length=5
    )
    second = stationary_bootstrap_indices(
        25, 100, np.random.default_rng(9), expected_block_length=5
    )
    np.testing.assert_array_equal(first, second)
    assert first.min() >= 0
    assert first.max() < 25


def test_stationary_expected_block_length_one_restarts_every_step() -> None:
    # With restart_probability=1 there is no forced contiguous carry-forward.
    indices = stationary_bootstrap_indices(
        10, 20, np.random.default_rng(4), expected_block_length=1
    )
    expected = np.random.default_rng(4)
    manual = np.empty(20, dtype=int)
    manual[0] = int(expected.integers(0, 10))
    for i in range(1, 20):
        expected.random()  # restart decision, always < 1
        manual[i] = int(expected.integers(0, 10))
    np.testing.assert_array_equal(indices, manual)


def test_dispatch_requires_method_specific_parameters() -> None:
    rng = np.random.default_rng(1)
    with pytest.raises(ResamplingError, match="block_size"):
        resample_indices("moving_block", 10, 10, rng)
    with pytest.raises(ResamplingError, match="expected_block_length"):
        resample_indices("stationary", 10, 10, rng)


def test_invalid_block_lengths_fail_closed() -> None:
    with pytest.raises(ResamplingError, match="block_size"):
        moving_block_indices(10, 10, np.random.default_rng(1), block_size=11)
    with pytest.raises(ResamplingError, match="expected_block_length"):
        stationary_bootstrap_indices(
            10, 10, np.random.default_rng(1), expected_block_length=11
        )
