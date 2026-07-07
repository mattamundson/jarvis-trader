"""
Regression tests for the MAX_CONTRACTS_PER_INSTRUMENT hard cap.

Context: A runaway scanner created 3-contract MES shorts against stale price
data on 2026-04-10. Root cause was .env:95 MAX_CONTRACTS_PER_INSTRUMENT=3
silently overriding the config.py default of 2, with no validator to enforce
the project-level safety rule (CLAUDE.md §7). The original validator clamped
> 2 to exactly 2.

Update (Phase 3, commit 47f156b 2026-04-25): the hard cap was raised from 2
to 20 in `_enforce_max_contracts_hard_cap`. The default value in config.py
remains 2; `MAX_OVERNIGHT_CONTRACTS` defaults to 1. The validator now clamps
any value > 20 to exactly 20 and floors values < 1 to 1. These tests encode
the post-Phase-3 policy.
"""

from __future__ import annotations

import pytest


def test_hard_cap_clamps_env_override_above_20(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if .env says 25, the config must clamp to 20."""
    from unittest.mock import patch

    monkeypatch.setenv("MAX_CONTRACTS_PER_INSTRUMENT", "25")
    import importlib

    import config

    # Suppress load_dotenv so it doesn't override the monkeypatched env var.
    with patch("dotenv.load_dotenv"):
        importlib.reload(config)
        tc = config.TradingConfig()
    assert tc.MAX_CONTRACTS_PER_INSTRUMENT == 20


def test_hard_cap_clamps_extreme_env_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even an absurd env override is clamped to 20."""
    from unittest.mock import patch

    monkeypatch.setenv("MAX_CONTRACTS_PER_INSTRUMENT", "999")
    import importlib

    import config

    with patch("dotenv.load_dotenv"):
        importlib.reload(config)
        tc = config.TradingConfig()
    assert tc.MAX_CONTRACTS_PER_INSTRUMENT == 20


def test_hard_cap_passes_through_valid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """A value of 5 (within the 1..20 band) should pass through unchanged."""
    from unittest.mock import patch

    monkeypatch.setenv("MAX_CONTRACTS_PER_INSTRUMENT", "5")
    import importlib

    import config

    with patch("dotenv.load_dotenv"):
        importlib.reload(config)
        tc = config.TradingConfig()
    assert tc.MAX_CONTRACTS_PER_INSTRUMENT == 5


def test_hard_cap_validator_allows_below_default() -> None:
    """
    The validator classmethod itself should let 1 pass through.
    Tested directly rather than via instantiation because config.py calls
    load_dotenv(override=True) which wipes monkeypatch.setenv.
    """
    from config import TradingConfig

    assert TradingConfig._enforce_max_contracts_hard_cap(1) == 1


def test_hard_cap_validator_floor_is_1() -> None:
    """Zero or negative values should clamp UP to 1 (minimum 1 contract)."""
    from config import TradingConfig

    assert TradingConfig._enforce_max_contracts_hard_cap(0) == 1
    assert TradingConfig._enforce_max_contracts_hard_cap(-5) == 1


def test_hard_cap_validator_clamps_above_20() -> None:
    """Direct validator test: 21→20, 100→20, 999→20."""
    from config import TradingConfig

    assert TradingConfig._enforce_max_contracts_hard_cap(21) == 20
    assert TradingConfig._enforce_max_contracts_hard_cap(100) == 20
    assert TradingConfig._enforce_max_contracts_hard_cap(999) == 20


def test_hard_cap_validator_passes_through_in_band() -> None:
    """Values in [1, 20] should pass through unchanged."""
    from config import TradingConfig

    for v in (1, 2, 3, 5, 10, 20):
        assert TradingConfig._enforce_max_contracts_hard_cap(v) == v


def test_hard_cap_validator_handles_non_int() -> None:
    """Malformed input should clamp to the safe default of 2."""
    from config import TradingConfig

    # A string that isn't an int → default safe value
    assert TradingConfig._enforce_max_contracts_hard_cap("not-a-number") == 2
    # A None → default safe value
    assert TradingConfig._enforce_max_contracts_hard_cap(None) == 2
