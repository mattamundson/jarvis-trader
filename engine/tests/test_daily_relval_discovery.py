"""Tests for backtest.daily_relval_discovery -- standalone daily-ETF relative-value
(pairs z-reversion) screener, the deep-data complement to the futures relval track.

Pure logic only (synthetic series; no cache, no network): z-score construction,
look-ahead-safe position/return generation, cost-on-transition, and screen wiring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import daily_relval_discovery as drd


def _bdays(start, n):
    return pd.DatetimeIndex(pd.bdate_range(start, periods=n))


def test_zscore_spread_zero_mean_and_detects_divergence():
    idx = _bdays("2015-01-01", 300)
    rng = np.random.default_rng(3)
    # two cointegrated series: b tracks a with mean-zero noise in the log-spread
    a = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.005, len(idx))), index=idx)
    b = pd.Series(a.to_numpy() * np.exp(rng.normal(0, 0.01, len(idx))), index=idx)
    z = drd.zscore_spread(a, b, window=60).dropna()
    assert abs(float(z.mean())) < 0.5  # roughly mean-zero
    assert float(z.abs().max()) > 1.0  # some bar diverges past 1 sigma


def test_spread_returns_no_lookahead_and_indexed_by_following_day():
    idx = _bdays("2015-01-01", 120)
    a = pd.Series(np.full(len(idx), 100.0), index=idx)
    b = pd.Series(np.full(len(idx), 100.0), index=idx)
    # inject a single transient divergence then snap-back -> a profitable reversion
    b.iloc[80] = 95.0  # spread = log(a)-log(b) spikes up at bar 80, reverts at 81
    r = drd.spread_returns(a, b, window=20, entry_z=1.5, exit_z=0.5, stop_z=6.0)
    # all return dates are strictly after the first bar (returns are realized t->t+1)
    assert all(d > str(idx[0].date()) for d in r.index)
    # the reversion is captured as a positive book return on at least one day
    assert float(r.max()) > 0.0


def test_spread_returns_charges_cost_on_a_round_trip():
    idx = _bdays("2015-01-01", 120)
    a = pd.Series(np.full(len(idx), 100.0), index=idx)
    b = pd.Series(np.full(len(idx), 100.0), index=idx)
    b.iloc[80] = 95.0
    free = drd.spread_returns(
        a, b, window=20, entry_z=1.5, exit_z=0.5, stop_z=6.0, cost_bps_per_leg=0.0
    )
    costed = drd.spread_returns(
        a, b, window=20, entry_z=1.5, exit_z=0.5, stop_z=6.0, cost_bps_per_leg=5.0
    )
    # cost strictly reduces the net sum of the same round-trip
    assert float(costed.sum()) < float(free.sum())


def test_spread_returns_flat_when_never_diverges():
    idx = _bdays("2015-01-01", 200)
    # perfectly locked series -> spread constant -> z is 0/NaN, never enters
    a = pd.Series(np.full(len(idx), 100.0), index=idx)
    b = pd.Series(np.full(len(idx), 100.0), index=idx)
    r = drd.spread_returns(a, b, window=20, entry_z=1.5, exit_z=0.5, stop_z=6.0)
    assert len(r) == 0


def test_pairs_are_economically_labelled():
    assert len(drd.PAIRS) >= 6
    for _name, a, b, rationale in drd.PAIRS:
        assert a != b
        assert len(rationale) >= 20  # a real economic reason, not a placeholder


def test_screen_returns_graded_row(monkeypatch):
    idx = _bdays("2010-01-01", 1500)
    rng = np.random.default_rng(11)
    a = pd.DataFrame(
        {
            "timestamp": [str(d.date()) for d in idx],
            "close": 100 * np.cumprod(1 + rng.normal(0.0002, 0.01, len(idx))),
        }
    )
    base = pd.to_numeric(a["close"]).to_numpy()
    b = pd.DataFrame(
        {
            "timestamp": a["timestamp"],
            "close": base * np.exp(rng.normal(0, 0.02, len(idx))),  # cointegrated-ish
        }
    )
    row = drd.screen(("A_B", "A", "B", "synthetic cointegrated test pair"), a, b, n_trials=8)
    for k in ("pair", "n", "pf_ci_lower", "dsr", "sharpe", "max_dd_pct", "stationary", "gate"):
        assert k in row
    assert row["pair"] == "A_B"
    assert "verdict" in row["gate"]
