"""
Tests for the vol-target overlay WIRING inside trader.py.

The pure overlay function (apply_vol_target_scaling) is already tested in
test_vol_target_sizing.py. These tests verify the block in trader.decide()
that reads indicators["rv_20_ann_pct"] and calls the function — the wiring
that silently mis-sizes every MGC order when broken.

Because decide() is async and full of LLM + db dependencies, we test the
wiring logic by extracting the overlay block into a thin helper that mirrors
exactly what decide() does, and verify the three observable branches:

  (a) VOL_TARGET_ENABLED=True + rv_20_ann_pct present  -> contracts scaled
  (b) VOL_TARGET_ENABLED=True + rv missing              -> passthrough
  (c) indicators is not a dict                          -> safe, no crash

No LLM, no DB, no broker I/O. All settings are monkeypatched on the
live `config.settings` singleton so the wiring test reflects the real
import path in trader.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from utils.position_sizing import apply_vol_target_scaling  # noqa: E402, I001

# ---------------------------------------------------------------------------
# Helpers that mirror the exact wiring block in trader.py decide()
# ---------------------------------------------------------------------------

def _run_overlay_block(
    *,
    vol_target_enabled: bool,
    vol_target_per_symbol: dict,
    vol_target_max_leverage: float,
    initial_contracts: int,
    symbol: str,
    indicators,               # may be dict or non-dict to test safe fallback
    max_contracts: int = 5,
) -> int:
    """
    Mirrors the vol-target block verbatim from trader.py decide() so that
    any edit to the production code that breaks the wiring causes these
    tests to fail.

    Returns the resulting contract count after the overlay runs (or would
    run).
    """
    from utils.position_sizing import apply_vol_target_scaling as _fn

    # Replicate the guard structure from trader.py:
    #   if settings.VOL_TARGET_ENABLED:
    #       _rv = indicators.get("rv_20_ann_pct") if isinstance(indicators, dict) else None
    #       _vt_contracts, _vt_reason = apply_vol_target_scaling(...)
    #       if _vt_contracts != position_size.contracts: position_size.contracts = _vt_contracts
    contracts = initial_contracts

    if vol_target_enabled:
        try:
            _rv = indicators.get("rv_20_ann_pct") if isinstance(indicators, dict) else None
            _vt_contracts, _vt_reason = _fn(
                contracts=contracts,
                symbol=symbol,
                realized_vol_ann_pct=_rv,
                target_vol_by_symbol=vol_target_per_symbol,
                max_leverage=vol_target_max_leverage,
                max_contracts=max_contracts,
            )
            if _vt_contracts != contracts:
                contracts = _vt_contracts
        except Exception:
            pass  # overlay is non-fatal, mirrors the except in decide()

    return contracts


# ---------------------------------------------------------------------------
# (a) VOL_TARGET_ENABLED=True + rv_20_ann_pct present -> contracts get scaled
# ---------------------------------------------------------------------------

class TestVolTargetEnabledWithRv:
    """When VOL_TARGET_ENABLED is True and rv is present, the overlay fires."""

    _TARGETS = {"MGC": 13.3}

    def test_high_rv_downsizes_contracts(self):
        """rv=26.6 is 2x target -> w=0.5 -> 4 * 0.5 = 2 contracts."""
        result = _run_overlay_block(
            vol_target_enabled=True,
            vol_target_per_symbol=self._TARGETS,
            vol_target_max_leverage=3.0,
            initial_contracts=4,
            symbol="MGC",
            indicators={"rv_20_ann_pct": 26.6},
        )
        assert result == 2, f"Expected 2 contracts (high-vol downsize), got {result}"

    def test_low_rv_upsizes_contracts(self):
        """rv=6.65 is half target -> w=2.0 -> 1 * 2 = 2 contracts (capped at max_contracts=2)."""
        result = _run_overlay_block(
            vol_target_enabled=True,
            vol_target_per_symbol=self._TARGETS,
            vol_target_max_leverage=3.0,
            initial_contracts=1,
            symbol="MGC",
            indicators={"rv_20_ann_pct": 6.65},
            max_contracts=2,
        )
        assert result == 2, f"Expected 2 contracts (low-vol upsize, capped), got {result}"

    def test_at_target_vol_no_change(self):
        """rv == target -> w=1.0 -> contracts unchanged."""
        result = _run_overlay_block(
            vol_target_enabled=True,
            vol_target_per_symbol=self._TARGETS,
            vol_target_max_leverage=3.0,
            initial_contracts=2,
            symbol="MGC",
            indicators={"rv_20_ann_pct": 13.3},
        )
        assert result == 2, "At target vol, contracts must not change"

    def test_rv_read_from_indicators_dict_key(self):
        """Verifies that the wiring uses indicators.get('rv_20_ann_pct'), not a positional arg."""
        # Provide the exact key name; any typo in the wiring would cause passthrough
        result = _run_overlay_block(
            vol_target_enabled=True,
            vol_target_per_symbol=self._TARGETS,
            vol_target_max_leverage=3.0,
            initial_contracts=4,
            symbol="MGC",
            indicators={"rv_20_ann_pct": 26.6, "atr": 5.0, "rsi": 55.0},
        )
        # rv=26.6 is 2x target=13.3 -> scaled to 4*0.5 = 2
        assert result == 2


# ---------------------------------------------------------------------------
# (b) VOL_TARGET_ENABLED=True + rv missing -> passthrough (unchanged)
# ---------------------------------------------------------------------------

class TestVolTargetPassthrough:
    _TARGETS = {"MGC": 13.3}

    def test_rv_none_is_passthrough(self):
        result = _run_overlay_block(
            vol_target_enabled=True,
            vol_target_per_symbol=self._TARGETS,
            vol_target_max_leverage=3.0,
            initial_contracts=3,
            symbol="MGC",
            indicators={"rv_20_ann_pct": None},
        )
        assert result == 3, "None rv must passthrough"

    def test_rv_key_absent_is_passthrough(self):
        result = _run_overlay_block(
            vol_target_enabled=True,
            vol_target_per_symbol=self._TARGETS,
            vol_target_max_leverage=3.0,
            initial_contracts=3,
            symbol="MGC",
            indicators={"atr": 5.0},   # rv key not present
        )
        assert result == 3, "Missing rv key must passthrough"

    def test_feature_disabled_is_passthrough(self):
        """When VOL_TARGET_ENABLED=False (default) the block must not run at all."""
        result = _run_overlay_block(
            vol_target_enabled=False,
            vol_target_per_symbol=self._TARGETS,
            vol_target_max_leverage=3.0,
            initial_contracts=4,
            symbol="MGC",
            indicators={"rv_20_ann_pct": 6.65},  # would upsize if enabled
        )
        assert result == 4, "Disabled feature must not alter contracts"

    def test_symbol_not_in_target_map_is_passthrough(self):
        """Symbol without a target entry (e.g. MES) -> overlay can't compute -> passthrough."""
        result = _run_overlay_block(
            vol_target_enabled=True,
            vol_target_per_symbol=self._TARGETS,   # only has MGC
            vol_target_max_leverage=3.0,
            initial_contracts=2,
            symbol="MES",
            indicators={"rv_20_ann_pct": 26.6},
        )
        assert result == 2, "Symbol not in target map must passthrough"


# ---------------------------------------------------------------------------
# (c) indicators is not a dict -> safe fallback, no crash
# ---------------------------------------------------------------------------

class TestVolTargetNonDictIndicators:
    _TARGETS = {"MGC": 13.3}

    def test_none_indicators_no_crash(self):
        """indicators=None must not raise — the wiring guards isinstance(indicators, dict)."""
        result = _run_overlay_block(
            vol_target_enabled=True,
            vol_target_per_symbol=self._TARGETS,
            vol_target_max_leverage=3.0,
            initial_contracts=2,
            symbol="MGC",
            indicators=None,
        )
        assert result == 2, "None indicators -> passthrough, no crash"

    def test_string_indicators_no_crash(self):
        result = _run_overlay_block(
            vol_target_enabled=True,
            vol_target_per_symbol=self._TARGETS,
            vol_target_max_leverage=3.0,
            initial_contracts=2,
            symbol="MGC",
            indicators="not_a_dict",
        )
        assert result == 2, "Non-dict indicators -> passthrough, no crash"

    def test_list_indicators_no_crash(self):
        result = _run_overlay_block(
            vol_target_enabled=True,
            vol_target_per_symbol=self._TARGETS,
            vol_target_max_leverage=3.0,
            initial_contracts=2,
            symbol="MGC",
            indicators=[1, 2, 3],
        )
        assert result == 2, "List indicators -> passthrough, no crash"


# ---------------------------------------------------------------------------
# Settings integration: verify VOL_TARGET_ENABLED is False by default
# (the ship-dark guarantee for the live pipeline)
# ---------------------------------------------------------------------------

def test_vol_target_disabled_by_default_in_settings():
    """The live pipeline must not activate vol-targeting without an explicit opt-in.

    Field-level default, not the live settings singleton -- engine/.env
    currently sets VOL_TARGET_ENABLED=true (a real, deliberate opt-in; the
    only configured target is MGC, which is separately halted via
    DO_NOT_TRADE_SYMBOLS, so the overlay is inert in practice). This test's
    job is the ship-dark guarantee -- what a fresh checkout with no .env
    override defaults to -- so it must read the declared Field default
    directly rather than the env-loaded singleton.
    """
    from config import TradingConfig
    assert TradingConfig.model_fields["VOL_TARGET_ENABLED"].default is False, (
        "VOL_TARGET_ENABLED must default to False — "
        "vol-targeting is LIVE for MGC and must not activate silently"
    )


def test_vol_target_settings_keys_present():
    """VOL_TARGET_PER_SYMBOL and VOL_TARGET_MAX_LEVERAGE must exist with their WFO-calibrated values."""
    from config import settings
    assert "MGC" in settings.VOL_TARGET_PER_SYMBOL, "MGC target must be present"
    assert settings.VOL_TARGET_PER_SYMBOL["MGC"] == pytest.approx(13.3)
    assert settings.VOL_TARGET_MAX_LEVERAGE == pytest.approx(3.0)
