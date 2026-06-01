"""
Tests for risk/futures_margin.py — margin_requirement, is_futures_symbol,
UnknownFuturesSymbolError.
"""

from __future__ import annotations

import pytest

from risk.futures_margin import (
    FUTURES_MARGIN_TABLE,
    FUTURES_SYMBOLS,
    UnknownFuturesSymbolError,
    is_futures_symbol,
    margin_requirement,
)


class TestIsFuturesSymbol:
    def test_mes_is_futures(self):
        assert is_futures_symbol("MES") is True

    def test_lowercase_mes_is_futures(self):
        """is_futures_symbol is case-insensitive."""
        assert is_futures_symbol("mes") is True

    def test_unknown_symbol_is_not_futures(self):
        assert is_futures_symbol("AAPL") is False

    def test_all_table_symbols_are_futures(self):
        for sym in FUTURES_SYMBOLS:
            assert is_futures_symbol(sym) is True


class TestMarginRequirement:
    def test_mes_margin_is_positive(self):
        margin = margin_requirement("MES")
        assert margin > 0

    def test_mes_margin_matches_table(self):
        assert margin_requirement("MES") == FUTURES_MARGIN_TABLE["MES"]

    def test_case_insensitive(self):
        assert margin_requirement("mes") == margin_requirement("MES")

    def test_unknown_symbol_raises(self):
        with pytest.raises(UnknownFuturesSymbolError):
            margin_requirement("UNKNOWN")

    def test_each_known_symbol_returns_float(self):
        for sym in FUTURES_SYMBOLS:
            result = margin_requirement(sym)
            assert isinstance(result, float)
            assert result > 0

    @pytest.mark.parametrize("symbol", ["MES", "MCL", "MNQ", "MGC", "ES", "NQ"])
    def test_specific_symbols_have_margin(self, symbol):
        margin = margin_requirement(symbol)
        assert margin > 0

    def test_raises_is_subclass_of_value_error(self):
        with pytest.raises(ValueError):
            margin_requirement("ZZZ")
