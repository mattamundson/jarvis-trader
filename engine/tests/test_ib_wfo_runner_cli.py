"""Tests for IB WFO runner dispatch controls."""

from __future__ import annotations

from argparse import Namespace

import pytest

from backtest.ib_wfo_runner import _resolve_targets


def _args(
    pos_symbol: str | None = None,
    pos_mode: str | None = None,
    opt_symbol: str | None = None,
    opt_mode: str | None = None,
) -> Namespace:
    return Namespace(
        pos_symbol=pos_symbol,
        pos_mode=pos_mode,
        opt_symbol=opt_symbol,
        opt_mode=opt_mode,
    )


def test_default_dispatch_runs_all_symbol_mode_pairs():
    assert _resolve_targets(_args()) == [
        ("MES", "go"),
        ("MES", "fade"),
        ("MGC", "go"),
        ("MGC", "fade"),
    ]


def test_positional_symbol_mode_dispatch_is_preserved():
    assert _resolve_targets(_args(pos_symbol="MES", pos_mode="go")) == [("MES", "go")]


def test_option_symbol_mode_dispatch_runs_one_pair():
    assert _resolve_targets(_args(opt_symbol="MGC", opt_mode="fade")) == [("MGC", "fade")]


def test_symbol_without_mode_runs_both_modes():
    assert _resolve_targets(_args(opt_symbol="MES")) == [("MES", "go"), ("MES", "fade")]


def test_mode_without_symbol_runs_both_symbols():
    assert _resolve_targets(_args(opt_mode="go")) == [("MES", "go"), ("MGC", "go")]


def test_conflicting_symbol_forms_raise():
    with pytest.raises(ValueError, match="symbol"):
        _resolve_targets(_args(pos_symbol="MES", opt_symbol="MGC"))
