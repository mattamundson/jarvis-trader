"""Tests for US-2502 — IBLevelProvider injection into signals.py Layer 2."""
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def _make_df(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2025-01-06", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "open": rng.uniform(70, 75, n),
            "high": rng.uniform(74, 76, n),
            "low": rng.uniform(69, 72, n),
            "close": rng.uniform(70, 75, n),
            "volume": rng.integers(1000, 5000, n),
        },
        index=idx,
    )


def test_inject_ib_levels_importable():
    """inject_ib_levels is importable from backtest.signals."""
    from backtest.signals import inject_ib_levels
    assert callable(inject_ib_levels)


def test_inject_ib_levels_adds_four_columns():
    """inject_ib_levels() adds discord_ columns when levels are available."""
    from backtest.signals import inject_ib_levels
    df = _make_df()
    mock_provider = MagicMock()
    mock_provider.SYMBOL_MAP = {"MCL": "CL", "MES": "ES", "MNQ": "NQ"}
    mock_provider.return_value.get_levels.return_value = {
        "ibu50": 72.5, "ibu100": 73.0, "ibd50": 70.5, "ibd100": 70.0
    }
    with patch("discord.ib_levels.IBLevelProvider", mock_provider):
        result = inject_ib_levels(df.copy(), "MCL")
    for col in ("discord_ibu50", "discord_ibu100", "discord_ibd50", "discord_ibd100"):
        assert col in result.columns, f"Missing column: {col}"


def test_inject_ib_levels_initializes_none_when_no_data():
    """inject_ib_levels() initializes discord_ columns to None when no levels found."""
    from backtest.signals import inject_ib_levels
    df = _make_df()
    mock_provider = MagicMock()
    mock_provider.SYMBOL_MAP = {"MCL": "CL"}
    mock_provider.return_value.get_levels.return_value = None
    with patch("discord.ib_levels.IBLevelProvider", mock_provider):
        result = inject_ib_levels(df.copy(), "MCL")
    assert "discord_ibu50" in result.columns
    assert result["discord_ibu50"].isna().all()


def test_inject_ib_levels_no_raise_on_import_error():
    """inject_ib_levels() returns df unchanged when discord module unavailable."""
    from backtest.signals import inject_ib_levels
    df = _make_df()
    with patch("backtest.signals._IB_AVAILABLE", False):
        with patch.dict("sys.modules", {"discord.ib_levels": None}):
            result = inject_ib_levels(df.copy(), "MCL")
    assert result is not None


def test_layer2_structure_no_discord_fields_returns_none():
    """layer2_structure() returns None for discord keys when columns absent."""
    from backtest.signals import layer2_structure
    row = pd.Series({
        "above_vah": False,
        "below_val": False,
        "above_ib_high": False,
        "below_ib_low": False,
        "vpoc": 72.0,
        "va_high": 73.0,
        "va_low": 71.0,
    })
    result = layer2_structure(row)
    assert "discord_ibu50" in result
    assert result["discord_ibu50"] is None
    assert result["discord_ibu100"] is None
    assert result["discord_ibd50"] is None
    assert result["discord_ibd100"] is None


def test_layer2_structure_with_discord_fields():
    """layer2_structure() includes discord values when discord columns populated."""
    from backtest.signals import layer2_structure
    row = pd.Series({
        "above_vah": True,
        "below_val": False,
        "above_ib_high": True,
        "below_ib_low": False,
        "vpoc": 72.0,
        "va_high": 73.0,
        "va_low": 71.0,
        "discord_ibu50": 72.5,
        "discord_ibu100": 73.0,
        "discord_ibd50": 70.5,
        "discord_ibd100": 70.0,
    })
    result = layer2_structure(row)
    assert result["discord_ibu50"] == pytest.approx(72.5)
    assert result["discord_ibu100"] == pytest.approx(73.0)
    assert result["discord_ibd50"] == pytest.approx(70.5)
    assert result["discord_ibd100"] == pytest.approx(70.0)
