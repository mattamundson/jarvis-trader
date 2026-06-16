"""Wiring: compute_all_indicators must add TPO-score observability columns
ONLY when the ENABLE_TPO_SCORE feature flag is set, and must NEVER change
entry/exit routing.

The TPO score (Corey TScore v2 port, engine/backtest/tpo_score.py) is unit-
tested in test_tpo_score.py. This file locks the *integration* into the live
signal path:
  - default OFF  → live path byte-for-byte unchanged (no new columns)
  - flag ON      → tpo_score / tpo_score_label / price_zone_label appear
  - observability ONLY → no entry_signal / exit_signal difference vs baseline

Routing on the score is intentionally NOT wired until it clears gate-v2.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.signals import (  # noqa: E402
    _is_tpo_score_enabled,
    compute_all_indicators,
    generate_instrument_signals,
)

_TPO_COLS = ("tpo_score", "tpo_score_label", "price_zone_label")


def _make_bars(n: int = 220, seed: int = 11) -> pd.DataFrame:
    """Synthetic OHLCV with a gentle uptrend; enough rows for rolling(20)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-02 09:30", periods=n, freq="1h", tz="UTC")
    close = np.cumsum(rng.normal(0.05, 1.0, n)) + 100
    high = close + np.abs(rng.normal(0.3, 0.2, n))
    low = close - np.abs(rng.normal(0.3, 0.2, n))
    open_ = close + rng.normal(0, 0.1, n)
    vol = rng.integers(1000, 5000, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


# ── flag parsing ──────────────────────────────────────────────────────────────

def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("ENABLE_TPO_SCORE", raising=False)
    assert _is_tpo_score_enabled() is False


def test_flag_truthy_values(monkeypatch):
    for val in ("1", "true", "TRUE", "yes", "On"):
        monkeypatch.setenv("ENABLE_TPO_SCORE", val)
        assert _is_tpo_score_enabled() is True


def test_flag_falsey_values(monkeypatch):
    for val in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("ENABLE_TPO_SCORE", val)
        assert _is_tpo_score_enabled() is False


# ── column presence gated by the flag ─────────────────────────────────────────

def test_columns_absent_when_flag_off(monkeypatch):
    monkeypatch.delenv("ENABLE_TPO_SCORE", raising=False)
    out = compute_all_indicators(_make_bars())
    for col in _TPO_COLS:
        assert col not in out.columns, f"{col} present despite flag OFF"


def test_columns_present_when_flag_on(monkeypatch):
    monkeypatch.setenv("ENABLE_TPO_SCORE", "1")
    out = compute_all_indicators(_make_bars())
    for col in _TPO_COLS:
        assert col in out.columns, f"{col} missing despite flag ON"


def test_score_in_range_when_flag_on(monkeypatch):
    monkeypatch.setenv("ENABLE_TPO_SCORE", "1")
    out = compute_all_indicators(_make_bars())
    valid = out["tpo_score"].dropna()
    assert len(valid) > 0
    assert valid.between(-1.0, 1.0).all()


def test_labels_are_valid_when_flag_on(monkeypatch):
    monkeypatch.setenv("ENABLE_TPO_SCORE", "1")
    out = compute_all_indicators(_make_bars())
    allowed_score = {
        "BUYERS_CONTROL", "BUYERS_LEAN", "NEUTRAL", "SELLERS_LEAN", "SELLERS_CONTROL",
    }
    allowed_zone = {
        "ABOVE_VALUE", "AT_UPPER_VA", "IN_VALUE", "AT_LOWER_VA", "BELOW_VALUE",
    }
    # warmup rows (rolling NaN) produce a label too; just assert membership
    assert set(out["tpo_score_label"].dropna().unique()) <= allowed_score
    assert set(out["price_zone_label"].dropna().unique()) <= allowed_zone


# ── observability ONLY: routing must not change ───────────────────────────────

def test_routing_unchanged_by_flag(monkeypatch):
    """Entry/exit signals must be identical with the flag ON vs OFF —
    the TPO score is observability-only until it clears gate-v2."""
    bars = _make_bars()

    monkeypatch.delenv("ENABLE_TPO_SCORE", raising=False)
    base = generate_instrument_signals(bars.copy(), symbol="MES")

    monkeypatch.setenv("ENABLE_TPO_SCORE", "1")
    withtpo = generate_instrument_signals(bars.copy(), symbol="MES")

    assert list(base["entry_signal"]) == list(withtpo["entry_signal"])
    if "exit_signal" in base.columns and "exit_signal" in withtpo.columns:
        assert list(base["exit_signal"]) == list(withtpo["exit_signal"])
