"""Golden-vector tests for source-derived indicator parity.

These tests are intentionally version-aware. They lock source-reference behavior
and also lock known non-equivalence between legacy ThinkScript formulas and the
standard/simplified Python variants already used by JARVIS.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import kama, phase_oscillator, stc
from backtest.studies.source_parity import (
    cohen_stc_recursive_reference,
    kama_tos_legacy,
    phase_tos_source_reference,
    stc_tos_main_reference,
)


def _fixture() -> tuple[pd.Series, pd.Series, pd.Series]:
    x = np.arange(140, dtype=float)
    close = pd.Series(100 + 0.12 * x + 2.4 * np.sin(x / 5.0) + 0.8 * np.cos(x / 11.0))
    high = close + 1.0 + 0.15 * np.sin(x / 3.0)
    low = close - 0.9 - 0.1 * np.cos(x / 4.0)
    return close, high, low


def test_kama_tos_legacy_golden_vector() -> None:
    close, _, _ = _fixture()
    actual = kama_tos_legacy(close).dropna().tail(5).to_numpy()
    expected = np.array(
        [117.48941842, 117.75906357, 117.94838701, 118.05846987, 118.10496197]
    )
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-8)


def test_kama_tos_legacy_is_not_standard_kaufman_kama() -> None:
    close, _, _ = _fixture()
    legacy = kama_tos_legacy(close)
    standard = kama(close, period=10, fast_period=2, slow_period=30)
    mask = legacy.notna() & standard.notna()
    assert mask.sum() > 50
    assert float((legacy[mask] - standard[mask]).abs().max()) > 0.25


def test_main_stc_reference_matches_current_python_formula() -> None:
    close, _, _ = _fixture()
    reference = stc_tos_main_reference(close)
    current = stc(close, fast=23, slow=50, k_period=10, d_period=3)
    mask = reference.notna() & current.notna()
    assert mask.sum() > 50
    np.testing.assert_allclose(reference[mask], current[mask], rtol=0, atol=1e-10)


def test_main_stc_golden_vector() -> None:
    close, _, _ = _fixture()
    actual = stc_tos_main_reference(close).dropna().tail(5).to_numpy()
    expected = np.array([99.98867547, 99.99433774, 99.99716887, 99.99858443, 88.24814249])
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-8)


def test_cohen_stc_is_a_distinct_smoothing_variant() -> None:
    close, _, _ = _fixture()
    main = stc_tos_main_reference(close)
    cohen = cohen_stc_recursive_reference(close)
    mask = main.notna() & cohen.notna()
    assert mask.sum() > 50
    assert float((main[mask] - cohen[mask]).abs().max()) > 1.0


def test_phase_source_reference_golden_vector() -> None:
    close, high, low = _fixture()
    phase, _ = phase_tos_source_reference(close, high, low)
    actual = phase.dropna().tail(5).to_numpy()
    expected = np.array([59.10152851, 54.43765022, 48.71434519, 42.15840762, 35.01650609])
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-8)


def test_phase_source_reference_is_not_current_simplified_port() -> None:
    close, high, low = _fixture()
    reference_phase, reference_compression = phase_tos_source_reference(close, high, low)
    simplified_phase, simplified_compression = phase_oscillator(close, high, low)

    mask = reference_phase.notna() & simplified_phase.notna()
    assert mask.sum() > 50
    assert float((reference_phase[mask] - simplified_phase[mask]).abs().max()) > 0.5

    # Compression implementations are independently versioned too. The assertion
    # is intentionally weak: either state can coincide on a particular fixture,
    # but both outputs must be aligned and boolean-valued for future parity cases.
    assert reference_compression.index.equals(simplified_compression.index)
    assert reference_compression.dtype == bool
