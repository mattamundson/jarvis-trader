"""
Unit tests for the options backtester scaffold (Strategy Novel #3).

Covers:
  * Slippage model: BUY adds spread+bps, SELL subtracts, fill never < 0
  * select_vertical_spread: bull call, bear put, missing strikes, validation
  * OptionsLeg.realised_pnl signed by quantity
  * VerticalSpread.net_debit / max_profit / max_loss math
  * BacktestResult aggregates: n_trades, win_rate, profit_factor (incl. inf)
  * OptionsBacktester end-to-end with mocked chain provider + signal source
  * Skip-reason differentiation (no_chain vs no_strikes)
  * Edge cases: empty signals, missing underlying-price-at-expiry, validation
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from backtest.options_backtester import (
    BacktestResult,
    BacktestTrade,
    FlatSlippage,
    OptionsBacktester,
    OptionsLeg,
    Signal,
    VerticalSpread,
    select_vertical_spread,
)
from options.chain_fetcher import OptionsChain, OptionsContract

# ── Fixtures: synthetic chain ────────────────────────────────────────────────

def _mk_contract(strike, opt_type, delta, bid=1.00, ask=1.10, expiry=None):
    expiry = expiry or date(2026, 5, 16)
    mid = (bid + ask) / 2
    return OptionsContract(
        strike=strike, expiry=expiry, option_type=opt_type,
        bid=bid, ask=ask, mid=mid,
        delta=delta, gamma=0.01, theta=-0.02, vega=0.10,
        iv=0.30, volume=100, oi=500,
    )


@pytest.fixture
def bull_chain():
    """A 5-strike call chain centered at 5000 (think MES)."""
    calls = [
        _mk_contract(4980, "call", 0.65, bid=22.0, ask=22.5),
        _mk_contract(4990, "call", 0.55, bid=14.0, ask=14.5),
        _mk_contract(5000, "call", 0.45, bid=8.0, ask=8.5),    # ATM-ish
        _mk_contract(5010, "call", 0.30, bid=4.0, ask=4.5),    # 30-delta target
        _mk_contract(5020, "call", 0.15, bid=1.5, ask=2.0),
    ]
    return OptionsChain(
        symbol="MES",
        expiry=date(2026, 5, 16),
        underlying_price=5000.0,
        iv_rank=50.0,
        calls=calls,
        puts=[],
    )


@pytest.fixture
def bear_chain():
    """A 5-strike put chain centered at 5000."""
    puts = [
        _mk_contract(4980, "put", -0.15, bid=1.5, ask=2.0),
        _mk_contract(4990, "put", -0.30, bid=4.0, ask=4.5),    # 30-delta target
        _mk_contract(5000, "put", -0.45, bid=8.0, ask=8.5),
        _mk_contract(5010, "put", -0.55, bid=14.0, ask=14.5),
        _mk_contract(5020, "put", -0.65, bid=22.0, ask=22.5),
    ]
    return OptionsChain(
        symbol="MES",
        expiry=date(2026, 5, 16),
        underlying_price=5000.0,
        iv_rank=50.0,
        calls=[],
        puts=puts,
    )


# ── FlatSlippage ────────────────────────────────────────────────────────────

def test_slippage_buy_above_mid():
    c = _mk_contract(5000, "call", 0.45, bid=8.0, ask=8.5)
    px = FlatSlippage(bps=10.0).fill_price(c, "BUY")
    # mid=8.25, half_spread=0.25, bps_drag=8.25*0.001=0.00825 → ≈8.508
    assert px > 8.25
    assert px == pytest.approx(8.508, abs=0.01)


def test_slippage_sell_below_mid():
    c = _mk_contract(5000, "call", 0.45, bid=8.0, ask=8.5)
    px = FlatSlippage(bps=10.0).fill_price(c, "SELL")
    assert px < 8.25
    assert px == pytest.approx(7.992, abs=0.01)


def test_slippage_sell_floored_at_zero():
    """Even if bps drag would push below 0, fill price floors at 0."""
    c = _mk_contract(5000, "call", 0.05, bid=0.05, ask=0.10)
    px = FlatSlippage(bps=99999.0).fill_price(c, "SELL")
    assert px >= 0.0


def test_slippage_rejects_unknown_side():
    c = _mk_contract(5000, "call", 0.45)
    with pytest.raises(ValueError, match="Unknown side"):
        FlatSlippage().fill_price(c, "HOLD")


# ── select_vertical_spread ──────────────────────────────────────────────────

def test_select_bull_call_picks_target_delta(bull_chain):
    long_leg, short_leg = select_vertical_spread(
        bull_chain, direction="BULL", target_delta=0.30, width_strikes=1
    )
    # Long leg should be the 30-delta call (strike 5010)
    assert long_leg.strike == 5010
    assert long_leg.option_type == "call"
    # Short leg one strike higher (5020)
    assert short_leg.strike == 5020


def test_select_bear_put_picks_target_delta(bear_chain):
    long_leg, short_leg = select_vertical_spread(
        bear_chain, direction="BEAR", target_delta=0.30, width_strikes=1
    )
    # Long leg: 30-delta put (strike 4990)
    assert long_leg.strike == 4990
    assert long_leg.option_type == "put"
    # Short leg: one strike LOWER (further OTM for puts → 4980)
    assert short_leg.strike == 4980


def test_select_returns_none_when_no_strikes_available(bull_chain):
    """Width too wide for the chain → no short leg → None."""
    out = select_vertical_spread(
        bull_chain, direction="BULL", target_delta=0.30, width_strikes=10,
    )
    assert out is None


def test_select_returns_none_when_no_matching_option_type():
    """Bull spread on a put-only chain → None."""
    chain = OptionsChain(
        symbol="MES", expiry=date(2026, 5, 16), underlying_price=5000.0,
        iv_rank=50.0, calls=[], puts=[_mk_contract(5000, "put", -0.45)],
    )
    assert select_vertical_spread(chain, direction="BULL") is None


def test_select_rejects_invalid_direction(bull_chain):
    with pytest.raises(ValueError, match="direction"):
        select_vertical_spread(bull_chain, direction="FLAT")


def test_select_rejects_out_of_range_delta(bull_chain):
    with pytest.raises(ValueError, match="target_delta"):
        select_vertical_spread(bull_chain, direction="BULL", target_delta=1.5)


def test_select_rejects_zero_width(bull_chain):
    with pytest.raises(ValueError, match="width_strikes"):
        select_vertical_spread(bull_chain, direction="BULL", width_strikes=0)


# ── OptionsLeg P&L ──────────────────────────────────────────────────────────

def test_leg_open_realised_pnl_zero():
    leg = OptionsLeg(
        contract=_mk_contract(5000, "call", 0.45),
        quantity=1, entry_price=5.0,
        entry_timestamp=datetime(2026, 4, 16),
    )
    assert leg.is_open
    assert leg.realised_pnl == 0.0


def test_leg_long_winner():
    leg = OptionsLeg(
        contract=_mk_contract(5000, "call", 0.45),
        quantity=1, entry_price=5.0,
        entry_timestamp=datetime(2026, 4, 16),
        exit_price=8.0, exit_timestamp=datetime(2026, 5, 16),
    )
    assert not leg.is_open
    assert leg.realised_pnl == 3.0  # (8 - 5) * 1


def test_leg_short_winner():
    """Short leg P&L: exit < entry → positive when sold high, bought back low."""
    leg = OptionsLeg(
        contract=_mk_contract(5020, "call", 0.15),
        quantity=-1, entry_price=2.0,
        entry_timestamp=datetime(2026, 4, 16),
        exit_price=0.5, exit_timestamp=datetime(2026, 5, 16),
    )
    # (0.5 - 2.0) * (-1) = +1.5
    assert leg.realised_pnl == 1.5


# ── VerticalSpread math ─────────────────────────────────────────────────────

def test_spread_debit_math():
    """Bull call: long 5010 @ 4.5, short 5020 @ 1.75 → debit 2.75, max profit width-debit."""
    long_leg = OptionsLeg(
        contract=_mk_contract(5010, "call", 0.30),
        quantity=1, entry_price=4.5,
        entry_timestamp=datetime(2026, 4, 16),
    )
    short_leg = OptionsLeg(
        contract=_mk_contract(5020, "call", 0.15),
        quantity=-1, entry_price=1.75,
        entry_timestamp=datetime(2026, 4, 16),
    )
    spread = VerticalSpread(long_leg=long_leg, short_leg=short_leg)
    assert spread.net_debit == pytest.approx(2.75)
    # Width = 10, debit = 2.75 → max profit = 7.25
    assert spread.max_profit == pytest.approx(7.25)
    # Debit spread: max loss = debit
    assert spread.max_loss == pytest.approx(2.75)


def test_spread_credit_math():
    """Sell long for less than short → credit; max loss = width + net_debit (negative)."""
    long_leg = OptionsLeg(
        contract=_mk_contract(5020, "call", 0.15),
        quantity=1, entry_price=1.75,
        entry_timestamp=datetime(2026, 4, 16),
    )
    short_leg = OptionsLeg(
        contract=_mk_contract(5010, "call", 0.30),
        quantity=-1, entry_price=4.5,
        entry_timestamp=datetime(2026, 4, 16),
    )
    spread = VerticalSpread(long_leg=long_leg, short_leg=short_leg)
    # net_debit = 1.75 - 4.5 = -2.75 (a credit)
    assert spread.net_debit == pytest.approx(-2.75)
    # Width = 10, credit = 2.75 → max loss = 10 - 2.75 = 7.25
    assert spread.max_loss == pytest.approx(7.25)


def test_spread_realised_pnl_sums_legs():
    long_leg = OptionsLeg(
        contract=_mk_contract(5010, "call", 0.30),
        quantity=1, entry_price=4.5,
        entry_timestamp=datetime(2026, 4, 16),
        exit_price=10.0, exit_timestamp=datetime(2026, 5, 16),
    )
    short_leg = OptionsLeg(
        contract=_mk_contract(5020, "call", 0.15),
        quantity=-1, entry_price=1.75,
        entry_timestamp=datetime(2026, 4, 16),
        exit_price=0.0, exit_timestamp=datetime(2026, 5, 16),
    )
    spread = VerticalSpread(long_leg=long_leg, short_leg=short_leg)
    # Long: (10-4.5)*1 = 5.5; Short: (0-1.75)*-1 = 1.75 → total 7.25
    assert spread.realised_pnl == pytest.approx(7.25)


# ── BacktestResult aggregates ───────────────────────────────────────────────

def _winner_trade(pnl):
    """Helper to manufacture a BacktestTrade with a known P&L."""
    long_leg = OptionsLeg(
        contract=_mk_contract(5010, "call", 0.30),
        quantity=1, entry_price=0.0,
        entry_timestamp=datetime(2026, 4, 16),
        exit_price=pnl, exit_timestamp=datetime(2026, 5, 16),
    )
    short_leg = OptionsLeg(
        contract=_mk_contract(5020, "call", 0.15),
        quantity=-1, entry_price=0.0,
        entry_timestamp=datetime(2026, 4, 16),
        exit_price=0.0, exit_timestamp=datetime(2026, 5, 16),
    )
    spread = VerticalSpread(long_leg=long_leg, short_leg=short_leg)
    sig = Signal(timestamp=datetime(2026, 4, 16), symbol="MES", side="LONG")
    return BacktestTrade(signal=sig, spread=spread)


def test_result_empty_aggregates_safe():
    r = BacktestResult()
    assert r.n_trades == 0
    assert r.total_pnl == 0.0
    assert r.win_rate == 0.0
    assert r.profit_factor == 0.0


def test_result_all_winners_profit_factor_inf():
    r = BacktestResult(trades=[_winner_trade(5.0), _winner_trade(3.0)])
    assert r.profit_factor == float("inf")
    assert r.win_rate == 1.0


def test_result_mixed_winners_losers():
    r = BacktestResult(trades=[_winner_trade(10.0), _winner_trade(-5.0)])
    assert r.n_trades == 2
    assert r.total_pnl == pytest.approx(5.0)
    assert r.win_rate == 0.5
    assert r.profit_factor == 2.0  # 10 / 5


def test_result_to_dict_replaces_inf_with_string():
    r = BacktestResult(trades=[_winner_trade(5.0)])
    d = r.to_dict()
    assert d["profit_factor"] == "inf"


# ── End-to-end backtester ───────────────────────────────────────────────────

class _StaticChainProvider:
    """Returns the same chain for every (symbol, ts) request."""

    def __init__(self, chain):
        self.chain = chain

    def get_chain(self, symbol, as_of, target_dte):
        return self.chain


class _NoChainProvider:
    def get_chain(self, symbol, as_of, target_dte):
        return None


class _FixedSignalSource:
    def __init__(self, signals):
        self._signals = signals

    def signals(self):
        return list(self._signals)


def test_backtester_full_run_bull_winner(bull_chain):
    """LONG signal → bull call spread → underlying rallies past short strike → max profit."""
    sigs = [Signal(timestamp=datetime(2026, 4, 16), symbol="MES", side="LONG")]
    bt = OptionsBacktester(
        chain_provider=_StaticChainProvider(bull_chain),
        signal_source=_FixedSignalSource(sigs),
        target_dte=30, target_delta=0.30, width_strikes=1,
    )
    # Underlying closes at 5050 — both calls ITM, max profit on the spread
    result = bt.run({date(2026, 5, 16): 5050.0})
    assert result.n_trades == 1
    assert result.total_pnl > 0


def test_backtester_full_run_bull_loser(bull_chain):
    """LONG signal → bull call spread → underlying drops → both calls expire worthless."""
    sigs = [Signal(timestamp=datetime(2026, 4, 16), symbol="MES", side="LONG")]
    bt = OptionsBacktester(
        chain_provider=_StaticChainProvider(bull_chain),
        signal_source=_FixedSignalSource(sigs),
    )
    # Underlying closes at 4900 — both calls OTM, lose the entire debit
    result = bt.run({date(2026, 5, 16): 4900.0})
    assert result.n_trades == 1
    assert result.total_pnl < 0


def test_backtester_skips_signal_with_no_chain():
    sigs = [Signal(timestamp=datetime(2026, 4, 16), symbol="MES", side="LONG")]
    bt = OptionsBacktester(
        chain_provider=_NoChainProvider(),
        signal_source=_FixedSignalSource(sigs),
    )
    result = bt.run({date(2026, 5, 16): 5000.0})
    assert result.n_trades == 0
    assert result.n_signals_skipped_no_chain == 1
    assert result.n_signals_consumed == 1


def test_backtester_skips_signal_when_strikes_unavailable(bull_chain):
    """width_strikes > available strikes → no short leg → skip."""
    sigs = [Signal(timestamp=datetime(2026, 4, 16), symbol="MES", side="LONG")]
    bt = OptionsBacktester(
        chain_provider=_StaticChainProvider(bull_chain),
        signal_source=_FixedSignalSource(sigs),
        width_strikes=99,  # impossibly wide
    )
    result = bt.run({date(2026, 5, 16): 5000.0})
    assert result.n_trades == 0
    assert result.n_signals_skipped_no_strikes == 1


def test_backtester_handles_empty_signal_source(bull_chain):
    bt = OptionsBacktester(
        chain_provider=_StaticChainProvider(bull_chain),
        signal_source=_FixedSignalSource([]),
    )
    result = bt.run({})
    assert result.n_trades == 0
    assert result.n_signals_consumed == 0


def test_backtester_skips_when_no_underlying_price_at_expiry(bull_chain):
    """If underlying price for the expiry isn't supplied, skip the close."""
    sigs = [Signal(timestamp=datetime(2026, 4, 16), symbol="MES", side="LONG")]
    bt = OptionsBacktester(
        chain_provider=_StaticChainProvider(bull_chain),
        signal_source=_FixedSignalSource(sigs),
    )
    result = bt.run({})  # no expiry prices
    # Spread opened (consumed signal) but didn't close → not in trades
    assert result.n_signals_consumed == 1
    assert result.n_trades == 0


def test_backtester_validates_dte_and_contracts():
    with pytest.raises(ValueError, match="target_dte"):
        OptionsBacktester(_NoChainProvider(), _FixedSignalSource([]), target_dte=0)
    with pytest.raises(ValueError, match="contracts_per_signal"):
        OptionsBacktester(
            _NoChainProvider(), _FixedSignalSource([]), contracts_per_signal=0
        )


def test_backtester_intrinsic_value_helper():
    call = _mk_contract(5000, "call", 0.45)
    put = _mk_contract(5000, "put", -0.45)
    # Call ITM: underlying 5050 → intrinsic 50
    assert OptionsBacktester._intrinsic_value(call, 5050.0) == 50.0
    # Call OTM: underlying 4950 → intrinsic 0
    assert OptionsBacktester._intrinsic_value(call, 4950.0) == 0.0
    # Put ITM: underlying 4950 → intrinsic 50
    assert OptionsBacktester._intrinsic_value(put, 4950.0) == 50.0
    # Put OTM: underlying 5050 → intrinsic 0
    assert OptionsBacktester._intrinsic_value(put, 5050.0) == 0.0
