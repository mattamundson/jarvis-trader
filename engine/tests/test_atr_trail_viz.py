"""Tests for the ATR-trail viz payload (dashboard endpoint data prep)."""
import numpy as np
import pandas as pd

from backtest.atr_trail_viz import compute_atr_trail_viz, reconstruct_flip_trades


def _df(n=600, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + 8 * np.sin(np.linspace(0, 40, n)) + np.cumsum(rng.normal(0, 0.4, n))
    high = close + np.abs(rng.normal(0, 1.0, n))
    low = close - np.abs(rng.normal(0, 1.0, n))
    idx = pd.date_range("2025-01-01 09:30", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def test_reconstruct_trades_have_consistent_pnl_sign():
    trades = reconstruct_flip_trades(_df(), "MES", 5, 3.5)
    assert trades
    for t in trades:
        move = (t["exit_px"] - t["entry_px"]) * t["dir"]
        # pnl_usd is the move in $ minus a positive round-trip cost
        assert t["pnl_usd"] <= round(move * 5.0, 2) + 1e-6


def test_viz_payload_shape_and_json_safe():
    import json
    viz = compute_atr_trail_viz(_df(800), "MES", 5, 3.5, max_points=200)
    assert set(viz) >= {"price", "trail", "trades", "equity", "n_trades", "net_usd", "win_rate"}
    assert len(viz["price"]) <= 210  # downsampled to ~max_points
    # equity is monotonic in time and cumulative
    if viz["equity"]:
        ts = [e["t"] for e in viz["equity"]]
        assert ts == sorted(ts)
        assert abs(viz["equity"][-1]["v"] - viz["net_usd"]) < 1.0
    json.dumps(viz)  # must not raise


def test_viz_downsamples_large_series():
    viz = compute_atr_trail_viz(_df(5000), "MES", 5, 3.5, max_points=1000)
    assert len(viz["price"]) <= 1010
    assert viz["bars"] == 5000
