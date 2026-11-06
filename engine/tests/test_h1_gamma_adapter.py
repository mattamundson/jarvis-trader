"""Unit test of the H1 gamma adapter. This file does not score H1."""

import math

from analytics.options_flow import compute_gex
from backtest.run_spy_options_baseline import bs_gamma


def test_a_bs_gamma_matches_hand_density():
    """Spot 100, strike 100, one year, volatility 0.20, rate 0.

    d1 = (ln(S/K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
       = (ln(1) + (0 + 0.5 * 0.04) * 1) / (0.20 * 1)
       = 0.02 / 0.20
       = 0.10

    The standard-normal density at that d1 is
    phi(0.10) = exp(-0.5 * 0.10**2) / sqrt(2 * pi)
              = exp(-0.005) / sqrt(2 * pi)

    gamma = phi(d1) / (S * sigma * sqrt(T))
          = phi(0.10) / (100 * 0.20 * 1)
          = phi(0.10) / 20
    """
    d1 = (math.log(100.0 / 100.0) + (0.0 + 0.5 * 0.20 ** 2) * 1.0) / (0.20 * math.sqrt(1.0))
    # 0.02 / 0.20 is 0.10. Binary division lands one ulp off 0.10.
    assert abs(d1 - 0.10) < 1e-15
    phi = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    hand = phi / (100.0 * 0.20 * math.sqrt(1.0))
    got = bs_gamma(100.0, 100.0, 1.0, 0.20, 0.0)
    assert abs(got - hand) < 1e-10


def test_b_one_call_net_gex_and_flip():
    gamma = bs_gamma(100.0, 100.0, 1.0, 0.20, 0.0)
    spot = 100.0
    open_interest = 1000.0
    sign = 1
    contract = {
        "details": {"contract_type": "call", "strike_price": 100.0},
        "greeks": {"gamma": gamma},
        "open_interest": open_interest,
    }
    flow = compute_gex([contract], spot)
    expected = sign * gamma * open_interest * 100 * (spot ** 2) * 0.01
    assert flow is not None
    # compute_gex rounds net_gex to cents. The unrounded formula is the claim.
    assert flow["net_gex"] == round(expected, 2)
    assert abs(flow["net_gex"] - expected) < 0.005
    assert flow["gex_flip_level"] == 100.0


def test_c_missing_open_interest_or_gamma_returns_none():
    gamma = bs_gamma(100.0, 100.0, 1.0, 0.20, 0.0)
    no_open_interest = {
        "details": {"contract_type": "call", "strike_price": 100.0},
        "greeks": {"gamma": gamma},
    }
    no_gamma = {
        "details": {"contract_type": "call", "strike_price": 100.0},
        "greeks": {},
        "open_interest": 1000,
    }
    assert compute_gex([no_open_interest], 100.0) is None
    assert compute_gex([no_gamma], 100.0) is None
