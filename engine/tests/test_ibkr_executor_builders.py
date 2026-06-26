"""IBKRExecutor — offline coverage for the pure/constructive helpers.

The executor's connection and order-submission paths need a live IB Gateway and
are out of scope here. But three helpers are pure logic / object construction and
were untested, despite each being a correctness hinge for live orders:

- ``_nearest_quarterly_expiry`` — picks the front-month futures expiry. A wrong
  month/year here trades the wrong contract.
- ``_make_futures_contract`` — symbol -> exchange/contract mapping (MES->CME,
  MCL->NYMEX, MGC/MHG->COMEX, default CME).
- ``_build_ib_order`` — order-type/action -> ib_async Order, with the
  required-price guards that return None rather than place a malformed order.

No network: the executor is constructed with a stub settings object and a mock
safety layer; ``IB()`` is created but never connected.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from execution.ibkr_executor import (
    IB_AVAILABLE,
    IBKRExecutor,
    _nearest_quarterly_expiry,
)

# ib_async ships in the engine venv; skip cleanly if a stripped env lacks it.
pytestmark = pytest.mark.skipif(not IB_AVAILABLE, reason="ib_async not installed")


def _executor() -> IBKRExecutor:
    settings = SimpleNamespace(IBKR_PORT=4002, IBKR_HOST="127.0.0.1", IBKR_CLIENT_ID=11)
    return IBKRExecutor(settings, MagicMock())


# ── _nearest_quarterly_expiry ─────────────────────────────────────────────


def test_expiry_before_march_returns_march_21():
    assert _nearest_quarterly_expiry(date(2026, 1, 15)) == "20260321"


def test_expiry_day_before_roll_keeps_current_month():
    assert _nearest_quarterly_expiry(date(2026, 3, 20)) == "20260321"


def test_expiry_on_roll_day_advances_to_next_quarter():
    # candidate uses strict ``>``, so on the 21st itself the contract rolls.
    # NB: the code uses day 21 (_EXPIRY_DAY_APPROX); the docstring's "20260620"
    # example is off by one — the actual value is the 21st.
    assert _nearest_quarterly_expiry(date(2026, 3, 21)) == "20260621"


def test_expiry_mid_year_picks_september():
    assert _nearest_quarterly_expiry(date(2026, 7, 1)) == "20260921"


def test_expiry_after_december_rolls_to_next_year_march():
    assert _nearest_quarterly_expiry(date(2026, 12, 25)) == "20270321"


def test_expiry_format_is_eight_digits_ending_21():
    out = _nearest_quarterly_expiry(date(2026, 5, 5))
    assert len(out) == 8 and out.isdigit() and out.endswith("21")


def test_expiry_default_reference_is_valid_format():
    # No arg -> uses date.today(); we can only assert the shape, not the value.
    out = _nearest_quarterly_expiry()
    assert len(out) == 8 and out.isdigit()
    assert int(out[4:6]) in (3, 6, 9, 12)


# ── _make_futures_contract ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("symbol", "exchange"),
    [
        ("MES", "CME"),
        ("MNQ", "CME"),
        ("M2K", "CME"),
        ("MSI", "CME"),
        ("MCL", "NYMEX"),
        ("MGC", "COMEX"),
        ("MHG", "COMEX"),
    ],
)
def test_make_futures_contract_maps_exchange(symbol, exchange):
    contract = _executor()._make_futures_contract(symbol)
    assert contract.symbol == symbol
    assert contract.exchange == exchange
    assert contract.currency == "USD"
    assert contract.secType == "FUT"
    assert len(contract.lastTradeDateOrContractMonth) == 8


def test_make_futures_contract_unknown_symbol_defaults_to_cme():
    assert _executor()._make_futures_contract("XYZ").exchange == "CME"


def test_make_futures_contract_uppercases_symbol():
    contract = _executor()._make_futures_contract("mes")
    assert contract.symbol == "MES"
    assert contract.exchange == "CME"


# ── _build_ib_order ───────────────────────────────────────────────────────


def _order(limit_price=None, stop_price=None):
    return SimpleNamespace(limit_price=limit_price, stop_price=stop_price)


def test_build_market_order():
    o = _executor()._build_ib_order("market", "BUY", 2, _order())
    assert o is not None
    assert o.orderType == "MKT"
    assert o.action == "BUY"
    assert o.totalQuantity == 2


def test_build_order_type_is_case_insensitive():
    assert _executor()._build_ib_order("MARKET", "SELL", 1, _order()).orderType == "MKT"


def test_build_limit_order_with_price():
    o = _executor()._build_ib_order("limit", "BUY", 1, _order(limit_price=5300.0))
    assert o.orderType == "LMT"
    assert o.lmtPrice == 5300.0


def test_build_limit_order_without_price_returns_none():
    assert _executor()._build_ib_order("limit", "BUY", 1, _order()) is None


def test_build_stop_order_with_price():
    o = _executor()._build_ib_order("stop", "SELL", 1, _order(stop_price=5280.0))
    assert o.orderType == "STP"
    assert o.auxPrice == 5280.0


def test_build_stop_order_without_price_returns_none():
    assert _executor()._build_ib_order("stop", "SELL", 1, _order()) is None


def test_build_stop_limit_order_with_both_prices():
    o = _executor()._build_ib_order(
        "stop_limit", "BUY", 1, _order(limit_price=5305.0, stop_price=5300.0)
    )
    assert o.orderType == "STP LMT"
    assert o.lmtPrice == 5305.0
    assert o.auxPrice == 5300.0


def test_build_stop_limit_missing_one_price_returns_none():
    ex = _executor()
    assert ex._build_ib_order("stop_limit", "BUY", 1, _order(limit_price=5305.0)) is None
    assert ex._build_ib_order("stop_limit", "BUY", 1, _order(stop_price=5300.0)) is None


def test_build_unknown_order_type_returns_none():
    assert _executor()._build_ib_order("trailing_voodoo", "BUY", 1, _order()) is None
