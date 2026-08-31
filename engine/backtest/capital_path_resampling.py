"""Dependence-preserving bootstrap index generators for Capital Path."""

from __future__ import annotations

from typing import Literal

import numpy as np


ResamplingMethod = Literal["iid", "moving_block", "stationary"]


class ResamplingError(ValueError):
    """Raised when bootstrap resampling geometry is invalid."""


def iid_indices(
    n_observations: int,
    output_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if n_observations < 1 or output_length < 1:
        raise ResamplingError("n_observations and output_length must be >= 1")
    return rng.integers(0, n_observations, size=output_length, dtype=int)


def moving_block_indices(
    n_observations: int,
    output_length: int,
    rng: np.random.Generator,
    *,
    block_size: int,
    circular: bool = True,
) -> np.ndarray:
    """Sample contiguous fixed-size blocks with replacement."""
    if n_observations < 1 or output_length < 1:
        raise ResamplingError("n_observations and output_length must be >= 1")
    if not 1 <= block_size <= n_observations:
        raise ResamplingError("block_size must be between 1 and n_observations")

    output: list[int] = []
    while len(output) < output_length:
        if circular:
            start = int(rng.integers(0, n_observations))
            block = [(start + offset) % n_observations for offset in range(block_size)]
        else:
            max_start = n_observations - block_size
            start = int(rng.integers(0, max_start + 1))
            block = list(range(start, start + block_size))
        output.extend(block)
    return np.asarray(output[:output_length], dtype=int)


def stationary_bootstrap_indices(
    n_observations: int,
    output_length: int,
    rng: np.random.Generator,
    *,
    expected_block_length: float,
) -> np.ndarray:
    """Politis-Romano-style stationary bootstrap with geometric block lengths.

    At each step the sequence restarts at a random observation with probability
    ``1/expected_block_length``; otherwise it advances one observation
    circularly. Expected contiguous run length therefore equals the configured
    block length while actual run lengths vary.
    """
    if n_observations < 1 or output_length < 1:
        raise ResamplingError("n_observations and output_length must be >= 1")
    if not 1.0 <= expected_block_length <= float(n_observations):
        raise ResamplingError(
            "expected_block_length must be between 1 and n_observations"
        )

    restart_probability = 1.0 / expected_block_length
    indices = np.empty(output_length, dtype=int)
    indices[0] = int(rng.integers(0, n_observations))
    for position in range(1, output_length):
        if rng.random() < restart_probability:
            indices[position] = int(rng.integers(0, n_observations))
        else:
            indices[position] = (indices[position - 1] + 1) % n_observations
    return indices


def resample_indices(
    method: ResamplingMethod,
    n_observations: int,
    output_length: int,
    rng: np.random.Generator,
    *,
    block_size: int | None = None,
    expected_block_length: float | None = None,
) -> np.ndarray:
    if method == "iid":
        return iid_indices(n_observations, output_length, rng)
    if method == "moving_block":
        if block_size is None:
            raise ResamplingError("moving_block requires block_size")
        return moving_block_indices(
            n_observations,
            output_length,
            rng,
            block_size=block_size,
        )
    if method == "stationary":
        if expected_block_length is None:
            raise ResamplingError("stationary requires expected_block_length")
        return stationary_bootstrap_indices(
            n_observations,
            output_length,
            rng,
            expected_block_length=expected_block_length,
        )
    raise ResamplingError(f"unknown resampling method: {method}")
