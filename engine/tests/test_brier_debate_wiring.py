"""
Unit tests for the Brier calibration wiring into debate.py (Novel #2).

Covers:
  * `_brier_blended_signal` blend math at the edges (alpha=1.0 → pure IC;
    zero-IC + neutral weights → identity; calibrated agent → boosted)
  * `_is_brier_enabled` env-var gate
  * `_get_brier_tracker` lazy-init + failure-sentinel caching

The debate-integration behaviors (picking the blend vs. pure IC at the
call site) are covered by the integration test in test_full_brier_loop.py.
"""

from __future__ import annotations

import importlib

import pytest

import agents.debate as debate

# ── Pure function: _brier_blended_signal ────────────────────────────────────


def test_brier_alpha_one_is_pure_ic():
    """alpha=1.0 must reproduce _ic_weighted_signal exactly — regression safety."""
    signal = 0.8
    ic_scores = {"technical": 0.2, "news": 0.0}
    brier_weights = {"technical": 0.9, "news": 0.1}  # extreme imbalance

    blended = debate._brier_blended_signal(signal, "technical", ic_scores, brier_weights, alpha=1.0)
    ic_only = debate._ic_weighted_signal(signal, "technical", ic_scores)

    assert blended == pytest.approx(ic_only)


def test_brier_zero_ic_uniform_weights_is_identity():
    """With IC=0 and uniform Brier (1/N), every agent gets the raw signal back."""
    signal = 0.5
    ic_scores = {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0, "e": 0.0}
    brier_weights = dict.fromkeys(ic_scores, 0.2)  # uniform → centered == 1.0
    out = debate._brier_blended_signal(signal, "a", ic_scores, brier_weights, alpha=0.5)
    assert out == pytest.approx(signal)


def test_brier_calibrated_agent_boosted_over_uncalibrated():
    """For two agents with identical raw signal and IC, the one with higher
    normalized Brier weight must get the larger post-blend signal."""
    signal = 1.0
    ic_scores = {"good": 0.0, "bad": 0.0}
    # good ≈ 0.8/(0.8+0.2) = 0.8 weight; bad = 0.2
    brier_weights = {"good": 0.8, "bad": 0.2}

    good_out = debate._brier_blended_signal(signal, "good", ic_scores, brier_weights, alpha=0.5)
    bad_out = debate._brier_blended_signal(signal, "bad", ic_scores, brier_weights, alpha=0.5)

    assert good_out > bad_out
    # With IC=0: blend collapses to 0.5*1.0 + 0.5*(w*N). w=0.8, N=2 → centered=1.6.
    # final_mult = 0.5 + 0.5*1.6 = 1.3
    assert good_out == pytest.approx(1.3)
    # bad: w=0.2, N=2 → centered=0.4. final_mult = 0.5 + 0.5*0.4 = 0.7
    assert bad_out == pytest.approx(0.7)


def test_brier_missing_agent_defaults_to_neutral():
    """An agent missing from brier_weights should be treated as neutral (1/N)."""
    signal = 1.0
    ic_scores = {"ghost": 0.0}
    brier_weights = {"a": 0.4, "b": 0.6}  # ghost absent

    out = debate._brier_blended_signal(signal, "ghost", ic_scores, brier_weights, alpha=0.5)
    # neutral = 1/2 = 0.5; centered = 0.5 * 2 = 1.0; final = 0.5*1.0 + 0.5*1.0 = 1.0
    assert out == pytest.approx(1.0)


# ── Env-var gate: _is_brier_enabled ─────────────────────────────────────────


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("no", False),
])
def test_is_brier_enabled_parses_truthy_values(monkeypatch, val, expected):
    monkeypatch.setenv("BRIER_CALIBRATION_ENABLED", val)
    assert debate._is_brier_enabled() is expected


def test_is_brier_enabled_defaults_false(monkeypatch):
    monkeypatch.delenv("BRIER_CALIBRATION_ENABLED", raising=False)
    assert debate._is_brier_enabled() is False


# ── Lazy init: _get_brier_tracker ───────────────────────────────────────────


def test_get_brier_tracker_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("BRIER_CALIBRATION_ENABLED", raising=False)
    # Clear any cached singleton from a prior test
    monkeypatch.setattr(debate, "_brier_tracker_instance", None)
    assert debate._get_brier_tracker(["technical"]) is None


def test_get_brier_tracker_caches_failure(monkeypatch):
    """A failed lazy-init must cache as False sentinel so retries don't stampede."""
    monkeypatch.setenv("BRIER_CALIBRATION_ENABLED", "true")
    monkeypatch.setattr(debate, "_brier_tracker_instance", None)

    # Patch the ic_ensemble import to raise on construction.
    # _get_brier_tracker imports via `engine.analytics.ic_ensemble` (absolute path
    # from project root); that's a distinct sys.modules entry from the
    # engine-sys-path shortcut `analytics.ic_ensemble`. Patch the one the
    # function actually resolves against.
    import engine.analytics.ic_ensemble as ic_mod

    def _boom(*a, **kw):
        raise RuntimeError("synthetic init failure")

    monkeypatch.setattr(ic_mod, "BrierCalibrationTracker", _boom)

    first = debate._get_brier_tracker(["technical"])
    assert first is None
    assert debate._brier_tracker_instance is False

    def _different_boom(*a, **kw):  # pragma: no cover — only fires if cache fails
        raise ValueError("should never be reached")

    monkeypatch.setattr(ic_mod, "BrierCalibrationTracker", _different_boom)
    second = debate._get_brier_tracker(["technical"])
    assert second is None


def test_get_brier_tracker_returns_instance_when_enabled(monkeypatch):
    monkeypatch.setenv("BRIER_CALIBRATION_ENABLED", "1")
    monkeypatch.setattr(debate, "_brier_tracker_instance", None)

    instance = debate._get_brier_tracker(["technical", "news"])
    assert instance is not None
    assert hasattr(instance, "get_calibration_weights")
    # Singleton: second call returns the same object
    assert debate._get_brier_tracker(["technical", "news"]) is instance
