"""Tests for the cross-index turn-of-month robustness check.

Synthetic daily OHLC + monkeypatched per-index validation — no network. Verifies the
registry, the per-index verdict shape, and the pre-registered >=4/6 corroboration logic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import tom_cross_index as tci


def _daily_bars(start: str, end: str, *, drift: float = 0.0004, seed: int = 0) -> pd.DataFrame:
    days = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(drift, 0.008, len(days)))
    return pd.DataFrame(
        {
            "date": [str(d.date()) for d in days],
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1_000_000,
        }
    )


def test_registry_has_spy_and_peers():
    assert "SPY" in tci.INDEX_REGISTRY
    # SPY + at least four independent peers (tech / small / blue-chip / mid / intl).
    assert len(tci.INDEX_REGISTRY) >= 5


def test_validate_index_returns_expected_shape():
    df = _daily_bars("2008-01-01", "2026-01-01")
    out = tci.validate_index("SPY", df=df)
    for k in (
        "symbol",
        "n",
        "sharpe_net",
        "beta_scale",
        "sized_dd_pct",
        "canonical_verdict",
        "p_edge",
        "pf_ci_lower",
        "beta_harvest_verdict",
        "stationary",
        "fails_only_on_p_edge",
        "corroborates",
    ):
        assert k in out, k
    assert out["symbol"] == "SPY"
    assert out["canonical_verdict"] in {"PASS", "FAIL"}
    assert isinstance(out["corroborates"], bool)


def test_validate_index_uses_provided_df_without_network(monkeypatch):
    # If a df is supplied, no fetch/load path should be touched.
    def _boom(*a, **k):
        raise AssertionError("network/cache fetch must not run when df is provided")

    monkeypatch.setattr(tci, "load_or_fetch", _boom)
    out = tci.validate_index("QQQ", df=_daily_bars("2010-01-01", "2024-01-01"))
    assert out["symbol"] == "QQQ"


def test_run_corroborated_at_four_of_six(monkeypatch):
    syms = ["SPY", "QQQ", "IWM", "DIA", "MDY", "EFA"]
    corr = {s: i < 4 for i, s in enumerate(syms)}  # exactly 4 corroborate

    def _fake(sym, **k):
        return {"symbol": sym, "corroborates": corr[sym], "canonical_verdict": "FAIL"}

    monkeypatch.setattr(tci, "validate_index", _fake)
    res = tci.run(symbols=syms)
    assert res["n_corroborating"] == 4
    assert res["verdict"] == "CORROBORATED"


def test_run_not_corroborated_below_threshold(monkeypatch):
    syms = ["SPY", "QQQ", "IWM", "DIA", "MDY", "EFA"]
    corr = {s: i < 3 for i, s in enumerate(syms)}  # only 3 corroborate

    def _fake(sym, **k):
        return {"symbol": sym, "corroborates": corr[sym], "canonical_verdict": "FAIL"}

    monkeypatch.setattr(tci, "validate_index", _fake)
    res = tci.run(symbols=syms)
    assert res["n_corroborating"] == 3
    assert res["verdict"] == "NOT-CORROBORATED"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
