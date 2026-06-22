"""Boundary + identity tests for the ported term-structure classifier.

classify_term_structure() is pure (no I/O); these pin the contango/backwardation
boundaries around the flat dead-band and the str-Enum identity. Ported bit-for-bit
from ~/Code/options-vrp options_vrp.vrp_signal.classify_term_structure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from analytics.term_structure import Regime, classify_term_structure  # noqa: E402


def test_regime_enum_canonical_values():
    # str-Enum identity (matches options-vrp): values are the canonical strings.
    assert Regime.CONTANGO.value == "CONTANGO"
    assert Regime.FLAT.value == "FLAT"
    assert Regime.BACKWARDATION.value == "BACKWARDATION"


def test_contango_when_vix3m_above_vix():
    regime, slope = classify_term_structure(18.0, 20.0, flat_band=0.5)
    assert regime == Regime.CONTANGO
    assert slope == pytest.approx(2.0)


def test_backwardation_when_vix_above_vix3m():
    regime, slope = classify_term_structure(25.0, 22.0, flat_band=0.5)
    assert regime == Regime.BACKWARDATION
    assert slope == pytest.approx(-3.0)


def test_flat_inside_dead_band():
    regime, slope = classify_term_structure(18.0, 18.3, flat_band=0.5)
    assert regime == Regime.FLAT
    assert slope == pytest.approx(0.3)


def test_boundary_exactly_at_band_is_flat():
    # slope > flat_band is STRICT, so +0.5 with band 0.5 is FLAT, +0.51 is CONTANGO.
    assert classify_term_structure(18.0, 18.5, flat_band=0.5)[0] == Regime.FLAT
    assert classify_term_structure(18.0, 18.51, flat_band=0.5)[0] == Regime.CONTANGO
    assert classify_term_structure(18.5, 18.0, flat_band=0.5)[0] == Regime.FLAT
    assert classify_term_structure(18.51, 18.0, flat_band=0.5)[0] == Regime.BACKWARDATION


def test_zero_band_splits_on_sign():
    assert classify_term_structure(18.0, 18.01, flat_band=0.0)[0] == Regime.CONTANGO
    assert classify_term_structure(18.01, 18.0, flat_band=0.0)[0] == Regime.BACKWARDATION
    assert classify_term_structure(18.0, 18.0, flat_band=0.0)[0] == Regime.FLAT
