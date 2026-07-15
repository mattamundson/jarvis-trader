"""Tests for engine/options/premium_calculator.py — Black-76 pricing.

Covered:
  - black76_price matches an independently-computed Black-76 reference value
    (via scipy.stats.norm.cdf, not the production _norm_cdf) for ATM call,
    ATM put, and an OTM ~25-delta call, across MES-like and MGC-like
    parameter sets.
  - Put-call parity holds for Black-76: call - put == disc * (F - K).
  - probability_of_profit returns a value in [0, 1] and moves in the
    expected direction as the strike moves ITM/OTM.
  - _d1_d2 raises ValueError for T <= 0 and sigma <= 0.

Design:
  - No network calls, no fixtures needed — pure math functions.
  - Reference prices are computed independently in this file (scipy.stats.norm)
    rather than reusing the production `_norm_cdf`/`_norm_pdf` helpers, so a
    bug shared between the implementation and a "test" that re-derives the
    same formula would still be caught.
"""

from __future__ import annotations

import math

import pytest
from scipy.stats import norm

from options.premium_calculator import _d1_d2, black76_price, probability_of_profit

TOL = 1e-4


# ---------------------------------------------------------------------------
# Independent reference implementation (scipy-backed, not production code)
# ---------------------------------------------------------------------------


def _reference_black76(F: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Hand-derived Black-76 price using scipy.stats.norm.cdf directly."""
    d1 = (math.log(F / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    disc = math.exp(-r * T)
    if option_type == "call":
        return disc * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return disc * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


# ---------------------------------------------------------------------------
# Parameter sets — MES-like and MGC-like (2 of the 4 traded instruments)
# ---------------------------------------------------------------------------

MES_LIKE = {"F": 6000.0, "K": 6000.0, "T": 30 / 365, "r": 0.05, "sigma": 0.14}
MGC_LIKE = {"F": 2000.0, "K": 2000.0, "T": 45 / 365, "r": 0.05, "sigma": 0.18}


@pytest.mark.parametrize("params", [MES_LIKE, MGC_LIKE], ids=["MES-like", "MGC-like"])
def test_atm_call_matches_reference(params):
    price = black76_price(params["F"], params["K"], params["T"], params["r"], params["sigma"], "call")
    ref = _reference_black76(params["F"], params["K"], params["T"], params["r"], params["sigma"], "call")
    assert price == pytest.approx(ref, abs=TOL)


@pytest.mark.parametrize("params", [MES_LIKE, MGC_LIKE], ids=["MES-like", "MGC-like"])
def test_atm_put_matches_reference(params):
    price = black76_price(params["F"], params["K"], params["T"], params["r"], params["sigma"], "put")
    ref = _reference_black76(params["F"], params["K"], params["T"], params["r"], params["sigma"], "put")
    assert price == pytest.approx(ref, abs=TOL)


@pytest.mark.parametrize("params", [MES_LIKE, MGC_LIKE], ids=["MES-like", "MGC-like"])
def test_otm_25_delta_call_matches_reference(params):
    """Strike chosen so the call delta lands near 0.25 (approx 25-delta OTM)."""
    F, T, r, sigma = params["F"], params["T"], params["r"], params["sigma"]
    # Solve K such that N(d1) * exp(-rT) ~= 0.25  -->  d1 ~= N^-1(0.25 / disc)
    disc = math.exp(-r * T)
    target_d1 = norm.ppf(0.25 / disc)
    log_fk = target_d1 * sigma * math.sqrt(T) - 0.5 * sigma**2 * T
    K = F / math.exp(log_fk)

    price = black76_price(F, K, T, r, sigma, "call")
    ref = _reference_black76(F, K, T, r, sigma, "call")
    assert price == pytest.approx(ref, abs=TOL)
    assert K > F  # genuinely OTM for a call

    delta_proxy = probability_of_profit(F, K, T, sigma, "call")
    assert 0.15 < delta_proxy < 0.35  # roughly 25-delta-ish


# ---------------------------------------------------------------------------
# Put-call parity: call - put == disc * (F - K)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "F,K,T,r,sigma",
    [
        (6000.0, 6000.0, 30 / 365, 0.05, 0.14),
        (6000.0, 6100.0, 30 / 365, 0.05, 0.14),
        (2000.0, 1950.0, 45 / 365, 0.05, 0.18),
    ],
    ids=["MES-ATM", "MES-OTM-call", "MGC-ITM-call"],
)
def test_put_call_parity(F, K, T, r, sigma):
    call = black76_price(F, K, T, r, sigma, "call")
    put = black76_price(F, K, T, r, sigma, "put")
    disc = math.exp(-r * T)
    assert (call - put) == pytest.approx(disc * (F - K), abs=TOL)


# ---------------------------------------------------------------------------
# probability_of_profit — range and directionality
# ---------------------------------------------------------------------------


def test_probability_of_profit_in_unit_interval():
    for option_type in ("call", "put"):
        p = probability_of_profit(6000.0, 6000.0, 30 / 365, 0.14, option_type)
        assert 0.0 <= p <= 1.0


def test_probability_of_profit_call_increases_as_strike_moves_itm():
    """A call is more likely to expire ITM the lower the strike (deeper ITM)."""
    F, T, sigma = 6000.0, 30 / 365, 0.14
    p_itm = probability_of_profit(F, 5800.0, T, sigma, "call")  # deep ITM
    p_atm = probability_of_profit(F, 6000.0, T, sigma, "call")  # ATM
    p_otm = probability_of_profit(F, 6200.0, T, sigma, "call")  # OTM
    assert p_itm > p_atm > p_otm


def test_probability_of_profit_put_increases_as_strike_moves_itm():
    """A put is more likely to expire ITM the higher the strike (deeper ITM)."""
    F, T, sigma = 6000.0, 30 / 365, 0.14
    p_itm = probability_of_profit(F, 6200.0, T, sigma, "put")  # deep ITM
    p_atm = probability_of_profit(F, 6000.0, T, sigma, "put")  # ATM
    p_otm = probability_of_profit(F, 5800.0, T, sigma, "put")  # OTM
    assert p_itm > p_atm > p_otm


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_d1_d2_raises_on_nonpositive_T():
    with pytest.raises(ValueError):
        _d1_d2(6000.0, 6000.0, 0.0, 0.14)
    with pytest.raises(ValueError):
        _d1_d2(6000.0, 6000.0, -1.0, 0.14)


def test_d1_d2_raises_on_nonpositive_sigma():
    with pytest.raises(ValueError):
        _d1_d2(6000.0, 6000.0, 30 / 365, 0.0)
    with pytest.raises(ValueError):
        _d1_d2(6000.0, 6000.0, 30 / 365, -0.1)


def test_black76_price_raises_on_nonpositive_sigma():
    """T <= 0 is a handled edge case (returns intrinsic value), but sigma <= 0
    is not — it propagates from _d1_d2."""
    with pytest.raises(ValueError):
        black76_price(6000.0, 6000.0, 30 / 365, 0.05, 0.0, "call")
