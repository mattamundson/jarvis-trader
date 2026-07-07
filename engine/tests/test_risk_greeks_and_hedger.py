"""Risk guards — GreeksGuard + PortfolioHedger coverage (offline, pure logic).

Covers two previously zero-coverage risk modules:
- risk/greeks_guard.py: portfolio Greeks limit checks (delta/gamma/vega/theta).
- risk/hedger.py: cross-asset hedging recommendations + correlation scaling.

Both are pure functions (the hedger's db_manager is unused on these paths, so
it is passed as None). No network, no DB, no settings.
"""

from __future__ import annotations

from risk.greeks_guard import GreeksGuard, PortfolioGreeks
from risk.hedger import PortfolioHedger

# ── GreeksGuard.validate_trade ────────────────────────────────────────────


def test_greeks_within_limits_allowed():
    guard = GreeksGuard()  # defaults: delta 100, gamma 10, vega 50, theta -20
    cur = PortfolioGreeks(delta=10, gamma=1, vega=5, theta=-2)
    trade = PortfolioGreeks(delta=20, gamma=2, vega=10, theta=-3)
    out = guard.validate_trade(cur, trade)
    assert out["allowed"] is True
    assert out["reasons"] == []
    assert out["projected_greeks"] == {"delta": 30, "gamma": 3, "vega": 15, "theta": -5}


def test_greeks_delta_breach_blocks_positive_and_negative():
    guard = GreeksGuard(max_delta=100.0)
    # Positive breach
    out = guard.validate_trade(PortfolioGreeks(delta=90), PortfolioGreeks(delta=20))
    assert out["allowed"] is False
    assert any("Delta" in r for r in out["reasons"])
    # Negative breach (abs is used)
    out_neg = guard.validate_trade(PortfolioGreeks(delta=-90), PortfolioGreeks(delta=-20))
    assert out_neg["allowed"] is False
    assert any("Delta" in r for r in out_neg["reasons"])


def test_greeks_at_exact_limit_is_allowed():
    # validate_trade uses strict >, so exactly at the limit passes.
    guard = GreeksGuard(max_delta=100.0)
    out = guard.validate_trade(PortfolioGreeks(delta=60), PortfolioGreeks(delta=40))
    assert out["projected_greeks"]["delta"] == 100
    assert out["allowed"] is True


def test_greeks_gamma_and_vega_breaches():
    guard = GreeksGuard(max_gamma=10.0, max_vega=50.0)
    out = guard.validate_trade(
        PortfolioGreeks(gamma=8, vega=40), PortfolioGreeks(gamma=5, vega=20)
    )
    assert out["allowed"] is False
    assert any("Gamma" in r for r in out["reasons"])
    assert any("Vega" in r for r in out["reasons"])


def test_greeks_theta_breach_when_more_negative_than_min():
    guard = GreeksGuard(min_theta=-20.0)
    out = guard.validate_trade(PortfolioGreeks(theta=-15), PortfolioGreeks(theta=-10))
    assert out["projected_greeks"]["theta"] == -25
    assert out["allowed"] is False
    assert any("Theta" in r for r in out["reasons"])


def test_greeks_multiple_breaches_accumulate_reasons():
    guard = GreeksGuard(max_delta=100.0, max_gamma=10.0, max_vega=50.0, min_theta=-20.0)
    out = guard.validate_trade(
        PortfolioGreeks(delta=90, gamma=9, vega=45, theta=-18),
        PortfolioGreeks(delta=30, gamma=5, vega=20, theta=-10),
    )
    assert out["allowed"] is False
    assert len(out["reasons"]) == 4


# ── PortfolioHedger.evaluate_hedging ──────────────────────────────────────


def _news(summary="", event_type=""):
    return {"news": {"summary": summary, "event_type": event_type}}


def test_hedger_no_positions_returns_empty():
    hedger = PortfolioHedger(db_manager=None)
    assert hedger.evaluate_hedging({"positions": []}, {}) == []
    assert hedger.evaluate_hedging({}, {}) == []


def test_hedger_no_threat_returns_empty():
    hedger = PortfolioHedger(db_manager=None)
    portfolio = {"positions": [{"symbol": "MES", "unrealized_pnl": 500, "quantity": 2}]}
    # neither hawkish nor reversal
    assert hedger.evaluate_hedging(portfolio, _news(summary="calm markets")) == []


def test_hedger_equity_exposure_plus_hawkish_scales_down():
    hedger = PortfolioHedger(db_manager=None)
    portfolio = {"positions": [{"symbol": "MES", "unrealized_pnl": 500, "quantity": 4}]}
    actions = hedger.evaluate_hedging(portfolio, _news(summary="Fed sounds HAWKISH"))
    assert len(actions) == 1
    a = actions[0]
    assert a.action == "scale_down"
    assert a.symbol == "MES"
    assert a.quantity == 2  # int(4 * 0.5)
    assert a.urgency == "high"


def test_hedger_crypto_exposure_plus_visual_reversal_scales_down():
    hedger = PortfolioHedger(db_manager=None)
    portfolio = {"positions": [{"symbol": "BTCUSD", "unrealized_pnl": 300, "quantity": 2}]}
    reports = {"vision": {"visual_verdict": "REJECTED"}}
    actions = hedger.evaluate_hedging(portfolio, reports)
    assert len(actions) == 1
    assert actions[0].symbol == "BTCUSD"
    assert actions[0].quantity == 1  # max(1, int(2*0.5))


def test_hedger_threat_but_no_positive_exposure_no_action():
    hedger = PortfolioHedger(db_manager=None)
    # unrealized_pnl <= 0 so neither equity nor crypto exposure is > 0
    portfolio = {"positions": [{"symbol": "MES", "unrealized_pnl": -100, "quantity": 4}]}
    actions = hedger.evaluate_hedging(portfolio, _news(summary="HAWKISH tone"))
    assert actions == []


def test_hedger_picks_largest_correlated_long():
    hedger = PortfolioHedger(db_manager=None)
    portfolio = {
        "positions": [
            {"symbol": "MES", "unrealized_pnl": 100, "quantity": 2},
            {"symbol": "MNQ", "unrealized_pnl": 100, "quantity": 6},
        ]
    }
    actions = hedger.evaluate_hedging(portfolio, _news(event_type="FED decision"))
    assert len(actions) == 1
    assert actions[0].symbol == "MNQ"  # the larger quantity long
    assert actions[0].quantity == 3


def test_hedger_quantity_floor_is_one():
    hedger = PortfolioHedger(db_manager=None)
    portfolio = {"positions": [{"symbol": "SPY", "unrealized_pnl": 50, "quantity": 1}]}
    actions = hedger.evaluate_hedging(portfolio, _news(summary="HAWKISH"))
    assert actions[0].quantity == 1  # max(1, int(1*0.5)) == 1


# ── PortfolioHedger.get_correlation_scaling_factor ────────────────────────


def test_scaling_factor_no_positions_is_full():
    hedger = PortfolioHedger(db_manager=None)
    assert hedger.get_correlation_scaling_factor("MES", {"positions": []}) == 1.0


def test_scaling_factor_symbol_outside_groups_is_full():
    hedger = PortfolioHedger(db_manager=None)
    portfolio = {"positions": [{"symbol": "MES"}, {"symbol": "MNQ"}]}
    assert hedger.get_correlation_scaling_factor("TSLA", portfolio) == 1.0


def test_scaling_factor_single_in_group_is_full():
    hedger = PortfolioHedger(db_manager=None)
    portfolio = {"positions": [{"symbol": "MES"}]}
    assert hedger.get_correlation_scaling_factor("MNQ", portfolio) == 1.0


def test_scaling_factor_two_or_more_in_group_halves():
    hedger = PortfolioHedger(db_manager=None)
    portfolio = {"positions": [{"symbol": "MES"}, {"symbol": "MNQ"}]}
    # Both MES/MNQ are in EQUITY_GROUP -> group_count >= 2 -> 0.5
    assert hedger.get_correlation_scaling_factor("SPY", portfolio) == 0.5
