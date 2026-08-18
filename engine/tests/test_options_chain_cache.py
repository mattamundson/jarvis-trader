"""
Unit tests for backtest.options_chain_cache (Strategy Novel #3 data layer).

Covers, without any network access (http_get is injected):
  * monthly expiry calendar (third Fridays) + next_monthly_expiry
  * option ticker formatting (Polygon O: convention)
  * IV solver sanity: recovered sigma ≈ input sigma, degenerate inputs -> 0
  * PolygonChainCache.get_chain end-to-end with a fake HTTP layer:
      - builds real contracts from fake daily bars
      - models bid/ask around the mid via relative_half_spread
      - computes IV + Greeks so select_vertical_spread can pick by delta
      - caches parquet (second get_chain does not re-hit the HTTP layer)
      - returns None when no underlying bars exist
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from backtest.options_backtester import select_vertical_spread
from backtest.options_chain_cache import (
    PolygonChainCache,
    good_friday,
    implied_volatility,
    monthly_expiries,
    next_monthly_expiry,
    option_ticker,
)

# ── Calendar + ticker helpers ────────────────────────────────────────────────

def test_monthly_expiries_third_fridays():
    exps = monthly_expiries(date(2024, 7, 1), date(2024, 9, 30))
    assert exps == [date(2024, 7, 19), date(2024, 8, 16), date(2024, 9, 20)]
    assert all(e.weekday() == 4 for e in exps)


def test_monthly_expiries_good_friday_shift():
    """April 2025: 3rd Friday (4/18) was Good Friday -> monthly expired 4/17."""
    exps = monthly_expiries(date(2025, 4, 1), date(2025, 4, 30))
    assert exps == [date(2025, 4, 17)]
    # March 2024: Good Friday 3/29 == 5th Friday, 3rd Friday (3/15) unaffected
    exps = monthly_expiries(date(2024, 3, 1), date(2024, 3, 31))
    assert exps == [date(2024, 3, 15)]


def test_good_friday_known_dates():
    assert good_friday(2025) == date(2025, 4, 18)
    assert good_friday(2024) == date(2024, 3, 29)
    assert good_friday(2026) == date(2026, 4, 3)


def test_next_monthly_expiry_dte():
    # 2024-11-01 -> 30 DTE skips Nov (only 14 days away) and lands on Dec monthly
    exp = next_monthly_expiry(date(2024, 11, 1), 30)
    assert exp == date(2024, 12, 20)
    # A 10-DTE ask from 2024-11-05 qualifies the Nov monthly (10 days away)
    exp = next_monthly_expiry(date(2024, 11, 5), 10)
    assert exp == date(2024, 11, 15)


def test_next_monthly_expiry_far_horizon_invariant():
    """For any min_dte the function returns a monthly with DTE >= min_dte
    (markets list monthlies years out, so None is unreachable)."""
    exp = next_monthly_expiry(date(2024, 1, 1), 1000)
    assert exp is not None
    assert exp.weekday() == 4
    assert (exp - date(2024, 1, 1)).days >= 1000


def test_option_ticker_format():
    assert option_ticker("SPY", date(2024, 12, 20), "call", 600.0) == "O:SPY241220C00600000"
    assert option_ticker("QQQ", date(2025, 6, 20), "put", 480.0) == "O:QQQ250620P00480000"
    with pytest.raises(ValueError, match="opt_type"):
        option_ticker("SPY", date(2024, 12, 20), "straddle", 600.0)


# ── IV solver ────────────────────────────────────────────────────────────────

def test_iv_solver_recovers_sigma():
    from options.premium_calculator import black_scholes_price

    spot, strike, T_years = 580.0, 600.0, 30 / 365.0
    sigma_in = 0.25
    px = black_scholes_price(spot, strike, T_years, 0.05, sigma_in, "call")
    expiry = date.today() + timedelta(days=30)
    iv = implied_volatility(px, spot, strike, expiry, date.today(), "call")
    assert iv == pytest.approx(sigma_in, abs=0.005)


def test_iv_solver_zero_for_degenerate():
    assert implied_volatility(0.0, 580.0, 600.0, date(2024, 12, 20), date(2024, 11, 1), "call") == 0.0
    # Price below intrinsic (stale/illiquid print) -> no IV
    assert implied_volatility(100.0, 580.0, 100.0, date(2024, 12, 20), date(2024, 11, 1), "call") == 0.0
    # Deep ITM price beyond solver range -> capped at hi
    assert implied_volatility(5000.0, 580.0, 100.0, date(2024, 12, 20), date(2024, 11, 1), "call") == pytest.approx(3.0)


# ── Fake HTTP layer + cache integration ──────────────────────────────────────

_TS = {  # UTC epoch ms so the module's UTC parsing yields these exact dates
    date(2024, 11, 1): int(datetime(2024, 11, 1, tzinfo=timezone.utc).timestamp() * 1000),
    date(2024, 11, 4): int(datetime(2024, 11, 4, tzinfo=timezone.utc).timestamp() * 1000),
}


class FakeHTTP:
    """Serves canned reference contracts + daily aggs. Counts calls."""

    def __init__(self):
        self.calls: list[str] = []
        self.expiry = date(2024, 11, 15)  # the monthly the provider should pick
        self.spot = 570.0
        self.spot_ts = _TS[date(2024, 11, 1)]

    def __call__(self, url: str, api_key: str) -> dict:
        self.calls.append(url)
        if "reference/options/contracts" in url:
            strikes = [560.0, 570.0, 580.0, 590.0, 600.0]
            results = []
            for s in strikes:
                for ct in ("call", "put"):
                    results.append({
                        "ticker": option_ticker("SPY", self.expiry, ct, s),
                        "strike_price": s,
                        "contract_type": ct,
                        "expiration_date": self.expiry.isoformat(),
                    })
            return {"results": results}
        if "/aggs/ticker/SPY/range" in url:
            # Serve a bar for every weekday in the requested range so the
            # underlying cache is complete and never refetched.
            rng = url.split("/range/1/day/")[1]
            start_s, end_s = rng.split("/")
            start_d, end_d = date.fromisoformat(start_s), date.fromisoformat(end_s)
            results = []
            d = start_d
            while d <= end_d:
                if d.weekday() < 5:
                    ts = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
                    results.append({"t": ts, "c": self.spot, "vw": self.spot, "v": 1000})
                d += timedelta(days=1)
            return {"results": results}
        if "/aggs/ticker/O:SPY" in url:
            # Derive a synthetic close per contract so IVs are well-posed.
            ticker = url.split("/aggs/ticker/")[1].split("/range")[0]
            body = ticker.split(":")[1]          # SPY241115C00570000
            leg = body[9]                        # 'C' or 'P'
            strike = float(body[10:]) / 1000.0
            opt_type = "call" if leg == "C" else "put"
            # Black-Scholes price at 25% IV for a clean synthetic market
            from options.premium_calculator import black_scholes_price

            T = (self.expiry - date(2024, 11, 1)).days / 365.0
            px = black_scholes_price(self.spot, strike, T, 0.05, 0.25, opt_type)
            return {"results": [{"t": self.spot_ts, "c": round(px, 4), "vw": round(px, 4), "v": 500}]}
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture
def fake_cache(tmp_path):
    return PolygonChainCache(
        cache_dir=tmp_path,
        api_key="test-key",
        requests_per_minute=1000,  # tests must not pace
        http_get=FakeHTTP(),
        relative_half_spread=0.02,
    )


def test_get_chain_builds_real_contracts(fake_cache):
    chain = fake_cache.get_chain("SPY", datetime(2024, 11, 1, 15, 0), target_dte=10)
    assert chain is not None
    assert chain.expiry == date(2024, 11, 15)
    assert chain.underlying_price == pytest.approx(570.0)
    assert len(chain.calls) == 5 and len(chain.puts) == 5
    # bid/ask modeled around mid
    c = chain.calls[1]  # ATM-ish call
    assert c.ask > c.mid > c.bid
    assert c.ask == pytest.approx(c.mid * 1.02, abs=1e-4)
    # IV solved (non-zero), delta signed positive for calls
    assert c.iv > 0.1
    assert c.delta > 0
    p = chain.puts[1]
    assert p.delta < 0


def test_get_chain_supports_scaffold_selection(fake_cache):
    """The built chain must let the scaffold pick a spread by target delta."""
    chain = fake_cache.get_chain("SPY", datetime(2024, 11, 1, 15, 0), target_dte=10)
    picks = select_vertical_spread(chain, direction="BULL", target_delta=0.30, width_strikes=1)
    assert picks is not None
    long_leg, short_leg = picks
    assert long_leg.option_type == "call"
    assert abs(abs(long_leg.delta) - 0.30) < 0.2  # nearest rung in a sparse ladder
    assert long_leg.strike < short_leg.strike


def test_get_chain_caches_and_does_not_rehit_http(fake_cache):
    _ = fake_cache.get_chain("SPY", datetime(2024, 11, 1, 15, 0), target_dte=10)
    n_calls_first = len(fake_cache.client._http_get.calls)
    _ = fake_cache.get_chain("SPY", datetime(2024, 11, 1, 15, 0), target_dte=10)
    assert len(fake_cache.client._http_get.calls) == n_calls_first
    # parquet files persisted
    files = list(fake_cache.cache_dir.glob("*.parquet"))
    assert len(files) >= 1


def test_get_chain_none_when_no_bars(tmp_path):
    class NoBarsHTTP(FakeHTTP):
        def __call__(self, url, api_key):
            if "/aggs/ticker/SPY/range" in url:
                return {"results": []}
            return super().__call__(url, api_key)

    cache = PolygonChainCache(
        cache_dir=tmp_path, api_key="k", requests_per_minute=1000, http_get=NoBarsHTTP()
    )
    assert cache.get_chain("SPY", datetime(2024, 11, 1), 10) is None


def test_get_chain_ignores_phantom_offgrid_strikes(tmp_path):
    """Polygon reference data carries phantom off-grid strikes (QQQ x.78
    artifacts alongside the real x.00 grid). The ladder must use ONLY clean
    integer/half-dollar strikes or chains silently come back empty."""

    class PhantomHTTP(FakeHTTP):
        def __call__(self, url, api_key):
            if "reference/options/contracts" in url:
                strikes = [560.0, 564.78, 570.0, 574.78, 580.0, 584.78, 590.0, 594.78, 600.0]
                results = []
                for s in strikes:
                    for ct in ("call", "put"):
                        results.append({
                            "ticker": option_ticker("SPY", self.expiry, ct, s),
                            "strike_price": s,
                            "contract_type": ct,
                            "expiration_date": self.expiry.isoformat(),
                        })
                return {"results": results}
            return super().__call__(url, api_key)

    cache = PolygonChainCache(
        cache_dir=tmp_path, api_key="k", requests_per_minute=1000,
        http_get=PhantomHTTP(), relative_half_spread=0.02,
    )
    chain = cache.get_chain("SPY", datetime(2024, 11, 1, 15, 0), target_dte=10)
    assert chain is not None
    # Only clean strikes in the ladder: 560, 570, 580, 590, 600
    assert sorted(c.strike for c in chain.calls) == [560.0, 570.0, 580.0, 590.0, 600.0]
    # And the scaffold can still pick a spread from it
    picks = select_vertical_spread(chain, direction="BULL", target_delta=0.30, width_strikes=1)
    assert picks is not None
