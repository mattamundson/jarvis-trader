"""Bar-level OHLC permutation for Monte Carlo permutation testing (MCPT).

This is the *price-permutation* null, distinct from the trade-sequence shuffle in
``backtest/monte_carlo.py``:

* ``monte_carlo.run_monte_carlo`` shuffles a realized *trade P&L* sequence and asks
  "given these trades, is the equity curve just a lucky ordering?" (Aronson EBTA ch. 6).
* This module shuffles the *price bars themselves* so a strategy can be re-optimized on
  noise. Paired with ``analytics/permutation_test.py`` it answers the stronger question
  "would my optimization *process* have found this edge in pure noise?" — i.e. it is the
  test for data-mining / optimization bias, which the trade shuffle structurally cannot
  catch (by the time you have a trade list, the overfitting already happened).

Algorithm (Masters, *Permutation and Randomization Tests for Trading System
Development*, 2020; reference implementation: neurotrader888 ``mcpt``). Each bar is
decomposed in log space into four relative quantities:

    gap   = log(open)  - log(prev_close)
    high  = log(high)  - log(open)
    low   = log(low)   - log(open)
    close = log(close) - log(open)

The intra-bar trio (high, low, close) is shuffled together (within-bar geometry
preserved); the gap series is shuffled independently (any close->open relationship
destroyed). Reassembling from a fixed start bar yields a series with the *same* return
distribution, volatility, skew and kurtosis as the original but with trend, mean
reversion and any other order-dependent structure randomized away.

Futures applicability: unlike the bounded close-only Polymarket series in the source
write-up (where synthetic ``open == prev_close`` collapses the gap term to zero), real
CME futures bars carry genuine overnight / session gaps, so the gap permutation is
load-bearing here and is kept exactly as the canonical algorithm specifies.

What the shuffle destroys that is real: volatility clustering and long-memory
autocorrelation. A strategy that explicitly depends on regime persistence gets a small
optimistic bias *against* it (the permuted markets look slightly easier than reality).
``get_block_permutation`` mitigates this by shuffling short contiguous blocks.
"""

from __future__ import annotations

from typing import List, Optional, Union

import numpy as np
import pandas as pd

_OHLC_COLS = ["open", "high", "low", "close"]


def _as_list(ohlc: Union[pd.DataFrame, List[pd.DataFrame]]) -> tuple[List[pd.DataFrame], bool]:
    """Normalize input to a list of frames; return (frames, was_single)."""
    if isinstance(ohlc, list):
        if not ohlc:
            raise ValueError("ohlc list is empty")
        idx = ohlc[0].index
        for mkt in ohlc:
            if not np.array_equal(idx, mkt.index):
                raise ValueError("all market indexes must match for multi-market permutation")
        return ohlc, False
    return [ohlc], True


def get_permutation(
    ohlc: Union[pd.DataFrame, List[pd.DataFrame]],
    start_index: int = 0,
    seed: Optional[int] = None,
) -> Union[pd.DataFrame, List[pd.DataFrame]]:
    """Return a permutation of ``ohlc`` that preserves its return distribution.

    Bars ``[0, start_index]`` are copied verbatim (the in-sample anchor for a
    walk-forward permutation); bars after ``start_index`` are reconstructed from
    independently shuffled gap and intra-bar components.

    Args:
        ohlc: A single OHLC DataFrame, or a list of frames with identical indexes
            (multi-market). Columns ``open/high/low/close`` are required.
        start_index: Index up to and including which bars are left unpermuted. Use
            ``0`` for a full in-sample permutation, ``train_window`` for a
            walk-forward permutation that holds the training fold fixed.
        seed: RNG seed for reproducibility.

    Returns:
        A permuted DataFrame (or list of frames, matching the input shape) sharing
        the original index, first open, and last close.

    Note:
        For a multi-market list the same shuffle indices are applied to every market,
        which preserves *contemporaneous* cross-market correlation but destroys any
        lead-lag relationship. Strategies that exploit lead-lag need a dedicated
        permutation and will be unfairly rejected by this one.
    """
    if start_index < 0:
        raise ValueError("start_index must be >= 0")
    frames, was_single = _as_list(ohlc)
    rng = np.random.default_rng(seed)

    n_bars = len(frames[0])
    perm_index = start_index + 1
    perm_n = n_bars - perm_index
    if perm_n < 2:
        raise ValueError(
            f"need >=2 bars after start_index to permute (have {perm_n}); "
            "lower start_index or supply more data"
        )

    time_index = frames[0].index
    perm1 = rng.permutation(perm_n)  # intra-bar (high/low/close) shuffle
    perm2 = rng.permutation(perm_n)  # gap shuffle

    out: List[pd.DataFrame] = []
    for frame in frames:
        log_bars = np.log(frame[_OHLC_COLS].to_numpy())

        gap = log_bars[:, 0] - np.concatenate([[np.nan], log_bars[:-1, 3]])
        rel_high = log_bars[:, 1] - log_bars[:, 0]
        rel_low = log_bars[:, 2] - log_bars[:, 0]
        rel_close = log_bars[:, 3] - log_bars[:, 0]

        s_gap = gap[perm_index:][perm2]
        s_high = rel_high[perm_index:][perm1]
        s_low = rel_low[perm_index:][perm1]
        s_close = rel_close[perm_index:][perm1]

        perm_bars = np.empty_like(log_bars)
        perm_bars[:perm_index] = log_bars[:perm_index]  # anchor segment verbatim
        for i in range(perm_index, n_bars):
            k = i - perm_index
            perm_bars[i, 0] = perm_bars[i - 1, 3] + s_gap[k]
            perm_bars[i, 1] = perm_bars[i, 0] + s_high[k]
            perm_bars[i, 2] = perm_bars[i, 0] + s_low[k]
            perm_bars[i, 3] = perm_bars[i, 0] + s_close[k]

        df = pd.DataFrame(np.exp(perm_bars), index=time_index, columns=_OHLC_COLS)
        _carry_extra_columns(frame, df)
        out.append(df)

    return out[0] if was_single else out


def get_block_permutation(
    ohlc: Union[pd.DataFrame, List[pd.DataFrame]],
    start_index: int = 0,
    block_size: int = 5,
    seed: Optional[int] = None,
) -> Union[pd.DataFrame, List[pd.DataFrame]]:
    """Block variant of :func:`get_permutation` that preserves local autocorrelation.

    Instead of shuffling individual bars, contiguous blocks of ``block_size`` bars are
    shuffled as units, so volatility clustering and short-range memory inside a block
    survive while long-range structure is destroyed. Use for strategies that depend on
    regime persistence (GARCH-style), per the volatility-clustering caveat in the module
    docstring.
    """
    if block_size < 1:
        raise ValueError("block_size must be >= 1")
    if start_index < 0:
        raise ValueError("start_index must be >= 0")
    frames, was_single = _as_list(ohlc)
    rng = np.random.default_rng(seed)

    n_bars = len(frames[0])
    perm_index = start_index + 1
    perm_n = n_bars - perm_index
    if perm_n < 2 * block_size:
        raise ValueError(
            f"need >=2 blocks of {block_size} bars after start_index "
            f"(have {perm_n} bars); use get_permutation or a smaller block_size"
        )

    n_blocks = int(np.ceil(perm_n / block_size))
    block_order = rng.permutation(n_blocks)
    # Map shuffled block order back to a flat bar-index permutation, truncated to perm_n.
    flat = np.concatenate(
        [np.arange(b * block_size, min((b + 1) * block_size, perm_n)) for b in block_order]
    )

    time_index = frames[0].index
    out: List[pd.DataFrame] = []
    for frame in frames:
        log_bars = np.log(frame[_OHLC_COLS].to_numpy())
        gap = log_bars[:, 0] - np.concatenate([[np.nan], log_bars[:-1, 3]])
        rel_high = log_bars[:, 1] - log_bars[:, 0]
        rel_low = log_bars[:, 2] - log_bars[:, 0]
        rel_close = log_bars[:, 3] - log_bars[:, 0]

        s_gap = gap[perm_index:][flat]
        s_high = rel_high[perm_index:][flat]
        s_low = rel_low[perm_index:][flat]
        s_close = rel_close[perm_index:][flat]

        perm_bars = np.empty_like(log_bars)
        perm_bars[:perm_index] = log_bars[:perm_index]
        for i in range(perm_index, n_bars):
            k = i - perm_index
            perm_bars[i, 0] = perm_bars[i - 1, 3] + s_gap[k]
            perm_bars[i, 1] = perm_bars[i, 0] + s_high[k]
            perm_bars[i, 2] = perm_bars[i, 0] + s_low[k]
            perm_bars[i, 3] = perm_bars[i, 0] + s_close[k]

        df = pd.DataFrame(np.exp(perm_bars), index=time_index, columns=_OHLC_COLS)
        _carry_extra_columns(frame, df)
        out.append(df)

    return out[0] if was_single else out


def _carry_extra_columns(src: pd.DataFrame, dst: pd.DataFrame) -> None:
    """Copy non-OHLC columns (e.g. volume) through unchanged.

    Volume and similar series are not part of the price-geometry permutation; they are
    carried verbatim so downstream strategies that read them do not break. They are NOT
    shuffled, so a strategy that depends on volume timing will see a real-volume /
    permuted-price mismatch — acceptable for a price-pattern null, but worth knowing.
    """
    for col in src.columns:
        if col not in _OHLC_COLS:
            dst[col] = src[col].to_numpy()
