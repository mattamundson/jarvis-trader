"""DO_NOT_TRADE symbols must not generate production trade alerts.

Regression: on 2026-09-21 the running engine completed a full MNQ LLM pipeline
and broadcast ``MNQ SHORT`` even though ``MNQ`` is in ``DO_NOT_TRADE_SYMBOLS``.
The order layer held, but analysis/broadcast still burned budget and emitted a
misleading actionable alert. This test pins the lightweight pipeline gate that
prevents that class of alert leak.
"""

import sys
from types import SimpleNamespace

from agents.pipeline import _is_do_not_trade_symbol


def test_do_not_trade_symbols_are_classified_blocked(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "backtest.signals",
        SimpleNamespace(DO_NOT_TRADE_SYMBOLS=frozenset({"MCL", "MNQ", "MGC", "M2K"})),
    )

    assert _is_do_not_trade_symbol("MNQ") is True
    assert _is_do_not_trade_symbol("mnq") is True
    assert _is_do_not_trade_symbol("MCL") is True
    assert _is_do_not_trade_symbol("MES") is False


def test_blocked_symbol_check_fails_open_if_import_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "backtest.signals", None)

    # If the import path is broken, the broadcast helper must not suppress a
    # tradeable symbol. Execution/risk gates still enforce the hard blocklist.
    assert _is_do_not_trade_symbol("MES") is False
