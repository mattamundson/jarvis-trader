"""
Unit tests for TVIndicatorBridge._parse_gamma_levels and the
_compute_gamma_regime_hints helper in technical_analyst.

Vendor script "MY FREE GAMMA LEVELS" is closed-source, so these tests use
synthetic label fixtures that mimic plausible label shapes. Each test locks
in ONE behavior so regressions surface the specific failure.
"""
import os
import sys

# Add engine to path (same pattern as test_tv_bridge.py)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# _parse_gamma_levels — label → dict
# ---------------------------------------------------------------------------

def test_parse_all_seven_levels_from_price_field():
    """Each label's `price` field is preferred over parsing text."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    labels = [
        {"text": "GEX Flip", "price": 5480.5},
        {"text": "Call Wall", "price": 5520.0},
        {"text": "Put Wall", "price": 5440.0},
        {"text": "HVL", "price": 5470.0},
        {"text": "Vol Trigger Up", "price": 5510.0},
        {"text": "Vol Trigger Down", "price": 5450.0},
        {"text": "Max Pain", "price": 5485.0},
    ]
    out = TVIndicatorBridge._parse_gamma_levels(labels)
    assert out["gex_flip"] == 5480.5
    assert out["call_wall"] == 5520.0
    assert out["put_wall"] == 5440.0
    assert out["hvl"] == 5470.0
    assert out["vol_trigger_up"] == 5510.0
    assert out["vol_trigger_down"] == 5450.0
    assert out["max_pain"] == 5485.0


def test_parse_falls_back_to_number_in_text_when_price_missing():
    """When a label lacks `price`, extract the first number from `text`."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    labels = [
        {"text": "Call Wall: 5555.25"},   # no price field
        {"text": "Put Wall 5420", "price": None},
    ]
    out = TVIndicatorBridge._parse_gamma_levels(labels)
    assert out["call_wall"] == 5555.25
    assert out["put_wall"] == 5420.0


def test_case_insensitive_matching():
    """Alias matching is case-insensitive — vendor labels may use any case."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    labels = [
        {"text": "GEX FLIP 5480", "price": 5480.0},
        {"text": "call wall", "price": 5500.0},
    ]
    out = TVIndicatorBridge._parse_gamma_levels(labels)
    assert out["gex_flip"] == 5480.0
    assert out["call_wall"] == 5500.0


def test_missing_labels_return_none():
    """Labels absent from input → corresponding keys are None, no exception."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    labels = [{"text": "Call Wall", "price": 5500.0}]
    out = TVIndicatorBridge._parse_gamma_levels(labels)
    assert out["call_wall"] == 5500.0
    # All other keys should be None, not missing
    for key in (
        "gex_flip",
        "put_wall",
        "hvl",
        "vol_trigger_up",
        "vol_trigger_down",
        "max_pain",
    ):
        assert out[key] is None


def test_empty_label_list_returns_all_none():
    """Empty input → dict of all Nones, never raises."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    out = TVIndicatorBridge._parse_gamma_levels([])
    assert set(out.keys()) == {
        "gex_flip",
        "call_wall",
        "put_wall",
        "hvl",
        "vol_trigger_up",
        "vol_trigger_down",
        "max_pain",
    }
    assert all(v is None for v in out.values())


def test_malformed_labels_are_skipped():
    """Non-dict labels, missing text, or bad price values → skipped silently."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    labels = [
        None,                                         # not a dict
        "just a string",                              # not a dict
        {"text": ""},                                 # empty text
        {"text": "call wall", "price": "not a num"},  # bad price, no fallback number
        {"text": "Call Wall", "price": 5500.0},       # valid — should win
    ]
    out = TVIndicatorBridge._parse_gamma_levels(labels)
    assert out["call_wall"] == 5500.0


def test_first_matching_label_wins():
    """Once a key is set, later labels do not overwrite it."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    labels = [
        {"text": "Call Wall", "price": 5500.0},
        {"text": "Call Wall", "price": 9999.0},  # should NOT overwrite
    ]
    out = TVIndicatorBridge._parse_gamma_levels(labels)
    assert out["call_wall"] == 5500.0


def test_vol_trigger_up_vs_down_disambiguation():
    """'Vol Trigger Up' and 'Vol Trigger Down' must land in distinct keys."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    labels = [
        {"text": "Vol Trigger Down", "price": 5400.0},
        {"text": "Vol Trigger Up", "price": 5550.0},
    ]
    out = TVIndicatorBridge._parse_gamma_levels(labels)
    assert out["vol_trigger_up"] == 5550.0
    assert out["vol_trigger_down"] == 5400.0


# ---------------------------------------------------------------------------
# _compute_gamma_regime_hints — regime derivation
# ---------------------------------------------------------------------------

def test_gamma_regime_positive_above_flip():
    """Price > gex_flip → positive regime → tight stop policy."""
    from agents.technical_analyst import _compute_gamma_regime_hints

    hints = _compute_gamma_regime_hints({
        "current_price": 5500.0,
        "tv_gex_flip": 5480.0,
        "tv_call_wall": 5520.0,
        "tv_put_wall": 5440.0,
        "tv_hvl": 5470.0,
    })
    assert hints["gex_regime"] == "positive"
    assert hints["suggested_stop_policy"] == "tight"
    assert hints["above_hvl"] is True


def test_gamma_regime_negative_below_flip():
    """Price < gex_flip → negative regime → wide stop policy."""
    from agents.technical_analyst import _compute_gamma_regime_hints

    hints = _compute_gamma_regime_hints({
        "current_price": 5460.0,
        "tv_gex_flip": 5480.0,
        "tv_hvl": 5470.0,
    })
    assert hints["gex_regime"] == "negative"
    assert hints["suggested_stop_policy"] == "wide"
    assert hints["above_hvl"] is False


def test_nearest_wall_selection():
    """Nearest wall is chosen by absolute distance, regardless of side."""
    from agents.technical_analyst import _compute_gamma_regime_hints

    # Price closer to put_wall than call_wall
    hints = _compute_gamma_regime_hints({
        "current_price": 5445.0,
        "tv_call_wall": 5520.0,
        "tv_put_wall": 5440.0,
    })
    assert hints["nearest_wall_side"] == "put_wall"
    assert hints["nearest_wall"] == 5440.0
    # Distance pct = |5440-5445| / 5445 ≈ 0.000918
    assert 0.0005 < hints["nearest_wall_distance_pct"] < 0.002


def test_hints_safe_when_price_missing():
    """No current_price → all hints are None, never raises."""
    from agents.technical_analyst import _compute_gamma_regime_hints

    hints = _compute_gamma_regime_hints({
        "tv_gex_flip": 5480.0,
        "tv_call_wall": 5520.0,
    })
    assert hints["gex_regime"] is None
    assert hints["nearest_wall"] is None
    assert hints["above_hvl"] is None


def test_hints_safe_when_gamma_fields_missing():
    """No gamma fields → all hints are None (graceful when overlay absent)."""
    from agents.technical_analyst import _compute_gamma_regime_hints

    hints = _compute_gamma_regime_hints({"current_price": 5500.0})
    for key in (
        "gex_regime",
        "nearest_wall",
        "nearest_wall_side",
        "nearest_wall_distance_pct",
        "above_hvl",
        "suggested_stop_policy",
    ):
        assert hints[key] is None


# ---------------------------------------------------------------------------
# Snapshot dataclass — gamma fields default to None
# ---------------------------------------------------------------------------

def test_snapshot_has_gamma_fields():
    """TVIndicatorSnapshot exposes all 7 gamma fields with None defaults."""
    from data.tv_indicator_bridge import TVIndicatorSnapshot

    snap = TVIndicatorSnapshot()
    for field in (
        "gex_flip",
        "call_wall",
        "put_wall",
        "hvl",
        "vol_trigger_up",
        "vol_trigger_down",
        "max_pain",
    ):
        assert hasattr(snap, field), f"Snapshot missing gamma field: {field}"
        assert getattr(snap, field) is None
