"""
Regression tests for the 2026-04-10 MAX_CONTRACTS_PER_INSTRUMENT hard cap.

Context: A runaway scanner created 3-contract MES shorts against stale price
data on 2026-04-10. Root cause was .env:95 MAX_CONTRACTS_PER_INSTRUMENT=3
silently overriding the config.py default of 2, with no validator to enforce
the project-level max-2 safety rule (CLAUDE.md §7).

Fix: Added @field_validator("MAX_CONTRACTS_PER_INSTRUMENT") in config.py that
clamps any value > 2 to exactly 2 and logs a warning.
"""

from __future__ import annotations

import pytest


def test_hard_cap_clamps_env_override_above_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if .env says 5, the config must expose 2."""
    monkeypatch.setenv("MAX_CONTRACTS_PER_INSTRUMENT", "5")
    # Need to force-reload config module since it's cached
    import importlib
    import config

    importlib.reload(config)
    tc = config.TradingConfig()
    assert tc.MAX_CONTRACTS_PER_INSTRUMENT == 2


def test_hard_cap_clamps_extreme_env_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even an absurd env override is clamped."""
    monkeypatch.setenv("MAX_CONTRACTS_PER_INSTRUMENT", "999")
    import importlib
    import config

    importlib.reload(config)
    tc = config.TradingConfig()
    assert tc.MAX_CONTRACTS_PER_INSTRUMENT == 2


def test_hard_cap_passes_through_valid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """A value of 2 should pass through unchanged."""
    monkeypatch.setenv("MAX_CONTRACTS_PER_INSTRUMENT", "2")
    import importlib
    import config

    importlib.reload(config)
    tc = config.TradingConfig()
    assert tc.MAX_CONTRACTS_PER_INSTRUMENT == 2


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


def test_hard_cap_validator_clamps_above_2() -> None:
    """Direct validator test: 3→2, 5→2, 999→2."""
    from config import TradingConfig

    assert TradingConfig._enforce_max_contracts_hard_cap(3) == 2
    assert TradingConfig._enforce_max_contracts_hard_cap(5) == 2
    assert TradingConfig._enforce_max_contracts_hard_cap(999) == 2


def test_hard_cap_validator_handles_non_int() -> None:
    """Malformed input should clamp to a safe default."""
    from config import TradingConfig

    # A string that isn't an int → default safe value
    assert TradingConfig._enforce_max_contracts_hard_cap("not-a-number") == 2
    # A None → default safe value
    assert TradingConfig._enforce_max_contracts_hard_cap(None) == 2
