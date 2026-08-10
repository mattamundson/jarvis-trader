"""
Tests for the default-OFF volatility-targeting sizing overlay.

Two concerns:
  1. SHIP-DARK: the feature is OFF by default (settings.VOL_TARGET_ENABLED is
     False), so wiring it into the live pipeline changes no behavior until an
     owner explicitly enables it.
  2. The pure overlay (apply_vol_target_scaling) is correct: passthrough on
     missing inputs, down-scales high vol, up-scales low vol, clips to
     max_leverage, clamps to [1, max_contracts], never zeroes an approved trade.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from utils.position_sizing import apply_vol_target_scaling  # noqa: E402

_TARGETS = {"MGC": 13.3}


# ---------------------------------------------------------------------------
# 1. Ship-dark: default OFF
# ---------------------------------------------------------------------------

def test_vol_target_disabled_by_default():
    """Field-level default, not the live settings singleton -- engine/.env
    currently sets VOL_TARGET_ENABLED=true (a real, deliberate opt-in; the
    only configured target is MGC, which is separately halted via
    DO_NOT_TRADE_SYMBOLS, so the overlay is inert in practice). This test's
    job is the ship-dark guarantee -- what a fresh checkout with no .env
    override defaults to -- so it must read the declared Field default
    directly rather than the env-loaded singleton.
    """
    from config import TradingConfig
    assert TradingConfig.model_fields["VOL_TARGET_ENABLED"].default is False, (
        "vol-targeting must default OFF"
    )


def test_default_config_values_present():
    from config import settings
    assert settings.VOL_TARGET_MAX_LEVERAGE == pytest.approx(3.0)
    assert settings.VOL_TARGET_PER_SYMBOL.get("MGC") == pytest.approx(13.3)


# ---------------------------------------------------------------------------
# 2. Passthrough paths (overlay does nothing)
# ---------------------------------------------------------------------------

def test_passthrough_when_symbol_has_no_target():
    out, reason = apply_vol_target_scaling(2, "MES", 20.0, _TARGETS, 3.0, 5)
    assert out == 2 and "passthrough" in reason


def test_passthrough_when_rv_missing():
    out, _ = apply_vol_target_scaling(2, "MGC", None, _TARGETS, 3.0, 5)
    assert out == 2


def test_passthrough_when_rv_nonpositive():
    out, _ = apply_vol_target_scaling(2, "MGC", 0.0, _TARGETS, 3.0, 5)
    assert out == 2


def test_passthrough_when_no_base_contracts():
    out, _ = apply_vol_target_scaling(0, "MGC", 13.3, _TARGETS, 3.0, 5)
    assert out == 0


def test_passthrough_when_target_map_none():
    out, _ = apply_vol_target_scaling(2, "MGC", 13.3, None, 3.0, 5)
    assert out == 2


# ---------------------------------------------------------------------------
# 3. Scaling behavior
# ---------------------------------------------------------------------------

def test_at_target_is_unity():
    # rv == target => w == 1.0 => unchanged
    out, _ = apply_vol_target_scaling(2, "MGC", 13.3, _TARGETS, 3.0, 5)
    assert out == 2


def test_high_vol_downsizes():
    # rv 26.6 = 2x target => w = 0.5 => 4 * 0.5 = 2
    out, _ = apply_vol_target_scaling(4, "MGC", 26.6, _TARGETS, 3.0, 5)
    assert out == 2


def test_low_vol_upsizes():
    # rv 6.65 = half target => w = 2.0 => 2 * 2 = 4
    out, _ = apply_vol_target_scaling(2, "MGC", 6.65, _TARGETS, 5.0, 8)
    assert out == 4


def test_upsizing_clips_at_max_leverage():
    # rv tiny => w would be huge but clipped to max_leverage=3 => 1 * 3 = 3
    out, reason = apply_vol_target_scaling(1, "MGC", 0.5, _TARGETS, 3.0, 8)
    assert out == 3
    assert "w=3.00" in reason


def test_result_clamped_to_max_contracts():
    # w=2 on 4 contracts = 8, but max_contracts=5 => clamp to 5
    out, _ = apply_vol_target_scaling(4, "MGC", 6.65, _TARGETS, 3.0, 5)
    assert out == 5


def test_never_zeroes_an_approved_trade():
    # extreme vol: w -> ~0, round(1 * ~0) = 0, but floor at 1
    out, _ = apply_vol_target_scaling(1, "MGC", 9999.0, _TARGETS, 3.0, 5)
    assert out == 1


def test_reasoning_is_descriptive_when_scaling():
    _, reason = apply_vol_target_scaling(4, "MGC", 26.6, _TARGETS, 3.0, 5)
    assert "target=13.30%" in reason and "rv=26.60%" in reason
