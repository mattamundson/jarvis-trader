"""
Tests for the DO_NOT_TRADE_SYMBOLS guard in the autonomous scheduler.

Configuring AUTONOMOUS_ACTIVE_SYMBOLS from the blocked set (the historical
default "MCL,MNQ" — both in DO_NOT_TRADE_SYMBOLS) makes the autonomous loop a
silent no-op. _warn_blocked_active_symbols() surfaces that explicitly.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from scheduler import pipeline_autonomous as pa

_FAKE_DNTS = frozenset({"MCL", "MNQ", "M2K"})


def test_warns_when_all_active_symbols_blocked(caplog):
    with patch.dict(
        "sys.modules",
        {"backtest.signals": MagicMock(DO_NOT_TRADE_SYMBOLS=_FAKE_DNTS)},
    ):
        with caplog.at_level(logging.WARNING, logger="jarvis_trader.scheduler.autonomous"):
            blocked = pa._warn_blocked_active_symbols(["MCL", "MNQ"])

    assert set(blocked) == {"MCL", "MNQ"}
    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert "DO_NOT_TRADE_SYMBOLS" in combined
    assert "silent no-op" in combined


def test_no_warning_for_tradeable_symbols(caplog):
    with patch.dict(
        "sys.modules",
        {"backtest.signals": MagicMock(DO_NOT_TRADE_SYMBOLS=_FAKE_DNTS)},
    ):
        with caplog.at_level(logging.WARNING, logger="jarvis_trader.scheduler.autonomous"):
            blocked = pa._warn_blocked_active_symbols(["MES", "MGC"])

    assert blocked == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_partial_block_reports_only_blocked(caplog):
    with patch.dict(
        "sys.modules",
        {"backtest.signals": MagicMock(DO_NOT_TRADE_SYMBOLS=_FAKE_DNTS)},
    ):
        blocked = pa._warn_blocked_active_symbols(["MES", "MCL"])

    assert blocked == ["MCL"]


def test_guard_never_raises_when_signals_unavailable():
    # If backtest.signals import fails, the guard must return [] and not block
    # the tick. Force an ImportError by mapping the module to None.
    with patch.dict("sys.modules", {"backtest.signals": None}):
        assert pa._warn_blocked_active_symbols(["MCL"]) == []
