"""Tests for the default-OFF VIX/VIX3M term-structure sizing overlay.

Two concerns (mirror test_vol_target_sizing.py):
  1. SHIP-DARK: OFF by default (settings.TS_OVERLAY_ENABLED is False), so wiring it
     into the live sizer changes nothing until an owner enables it.
  2. The pure overlay (apply_term_structure_scaling) is correct: passthrough on
     missing inputs, keeps size in contango, down-sizes in backwardation, optional
     stand-aside, clamps to [1, max_contracts], never zeroes an approved trade unless
     stand-aside is explicitly configured.
"""
from __future__ import annotations

import sys
from pathlib import Path

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from analytics.term_structure import apply_term_structure_scaling  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Ship-dark: default OFF
# ---------------------------------------------------------------------------

def test_overlay_disabled_by_default():
    from config import settings
    assert settings.TS_OVERLAY_ENABLED is False, "term-structure overlay must default OFF"


def test_default_config_values_present():
    from config import settings
    assert settings.TS_FLAT_BAND == 0.5
    assert settings.TS_BACKWARDATION_MULT == 0.5
    assert settings.TS_FLAT_MULT == 1.0
    assert settings.TS_STANDASIDE_ON_BACKWARDATION is False


# ---------------------------------------------------------------------------
# 2. Passthrough paths (overlay does nothing)
# ---------------------------------------------------------------------------

def test_passthrough_when_vix_missing():
    out, reason = apply_term_structure_scaling(2, None, 20.0)
    assert out == 2 and "passthrough" in reason


def test_passthrough_when_vix3m_missing():
    out, _ = apply_term_structure_scaling(2, 18.0, None)
    assert out == 2


def test_passthrough_when_iv_nonpositive():
    out, _ = apply_term_structure_scaling(2, 18.0, 0.0)
    assert out == 2


def test_passthrough_when_no_base_contracts():
    out, _ = apply_term_structure_scaling(0, 18.0, 20.0)
    assert out == 0


# ---------------------------------------------------------------------------
# 3. Scaling behavior
# ---------------------------------------------------------------------------

def test_contango_keeps_size():
    # VIX3M > VIX => CONTANGO => x1.0 => unchanged
    out, reason = apply_term_structure_scaling(2, 18.0, 20.0, max_contracts=5)
    assert out == 2 and "CONTANGO" in reason


def test_flat_keeps_size():
    # inside dead-band => FLAT => flat_mult (1.0) => unchanged
    out, reason = apply_term_structure_scaling(2, 18.0, 18.3, max_contracts=5)
    assert out == 2 and "FLAT" in reason


def test_backwardation_downsizes():
    # VIX > VIX3M => BACKWARDATION => x0.5 => 4 -> 2
    out, reason = apply_term_structure_scaling(4, 25.0, 22.0, backwardation_mult=0.5, max_contracts=5)
    assert out == 2 and "BACKWARDATION" in reason


def test_backwardation_never_zeroes_when_not_standaside():
    # mult 0.0, but floor at 1 (approved trade never zeroed) unless stand-aside
    out, _ = apply_term_structure_scaling(2, 30.0, 20.0, backwardation_mult=0.0,
                                          standaside_on_backwardation=False)
    assert out == 1


def test_standaside_returns_zero_on_backwardation():
    out, reason = apply_term_structure_scaling(3, 30.0, 20.0,
                                               standaside_on_backwardation=True)
    assert out == 0 and "stand aside" in reason


def test_standaside_does_not_fire_in_contango():
    # stand-aside only triggers on backwardation; contango is full size
    out, _ = apply_term_structure_scaling(3, 18.0, 21.0, standaside_on_backwardation=True,
                                          max_contracts=5)
    assert out == 3


def test_result_clamped_to_max_contracts():
    # contango_mult 3.0 on 2 contracts = 6, but max_contracts=3 => clamp to 3
    out, _ = apply_term_structure_scaling(2, 18.0, 22.0, contango_mult=3.0, max_contracts=3)
    assert out == 3


def test_reasoning_is_descriptive():
    _, reason = apply_term_structure_scaling(4, 25.0, 22.0, backwardation_mult=0.5)
    assert "VIX 25.00" in reason and "VIX3M 22.00" in reason and "x0.50" in reason
