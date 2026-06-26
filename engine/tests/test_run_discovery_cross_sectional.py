"""R3/T14: cross-sectional discovery driver (grid, gate-eval, isolation, split)."""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

import pandas as pd  # noqa: E402

from scripts import run_discovery_cross_sectional as drv  # noqa: E402


def _panel(data: dict, n: int) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(data, index=idx)


def test_iter_grid_is_small_for_honest_dsr():
    combos = drv.iter_grid()
    assert len(combos) <= 6  # DSR n_trials must equal trials actually tried
    assert all("lookback" in c and "top_k" in c for c in combos)


def test_evaluate_combo_no_trade_when_too_few_trades():
    # Tiny panel -> well under the 30-trade floor -> NO_TRADE, never calls validate.
    res = drv.evaluate_combo(
        _panel({"A": [100.0, 110.0, 121.0], "B": [100.0, 90.0, 81.0]}, 3),
        {"lookback": 1, "top_k": 1},
        n_grid_trials=6,
    )
    assert res["gate_verdict"]["verdict"] == "NO_TRADE"
    assert res["promoted"] is False
    assert "metrics" in res and "temporal_split" in res


def test_evaluate_combo_has_full_verdict_shape():
    # >=30 trades so the gate path runs (small n_resamples to stay fast).
    a = [100.0 * (1.01**k) for k in range(80)]
    b = [100.0 * (0.99**k) for k in range(80)]
    res = drv.evaluate_combo(
        _panel({"A": a, "B": b}, 80),
        {"lookback": 1, "top_k": 1},
        n_grid_trials=6,
        n_resamples=200,
    )
    assert res["metrics"]["total_trades"] >= 30
    assert res["gate_verdict"]["verdict"] in ("PASS", "FAIL", "NO_TRADE")
    assert res["temporal_split"]["verdict"] in ("STRONG", "FAIL")
    # promoted requires BOTH gate PASS and split STRONG.
    assert res["promoted"] == (
        res["gate_verdict"]["verdict"] == "PASS" and res["temporal_split"]["verdict"] == "STRONG"
    )


def test_write_verdict_is_isolated(tmp_path):
    out = drv._write_verdict({"hello": "world"}, out_dir=str(tmp_path / "iso"))
    assert out.exists()
    assert "discovery_cross_sectional" not in str(out)  # we passed a custom dir
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded == {"hello": "world"}


def test_run_discovery_with_injected_loader(tmp_path):
    a = [100.0 * (1.01**k) for k in range(80)]
    b = [100.0 * (0.99**k) for k in range(80)]
    store = {"A": _panel({"close": a}, 80), "B": _panel({"close": b}, 80)}

    class _Loader:
        def load(self, symbol, start, end, interval="1d"):
            return store.get(symbol)

    # Monkeypatch validate to a cheap resample count via a tiny grid is not exposed;
    # run_discovery uses default n_resamples, so keep the basket to 2 symbols/1 panel
    # and accept the bootstrap cost once.
    verdict = drv.run_discovery(["A", "B"], "2026-01-01", "2026-03-21", loader=_Loader())
    assert verdict["strategy_class"] == "cross_sectional_momentum"
    assert verdict["panel_rows"] == 80
    assert verdict["n_combos"] == len(drv.iter_grid())
    assert "results" in verdict and len(verdict["results"]) == verdict["n_combos"]
    # Results sorted with promoted first.
    promoted_flags = [r["promoted"] for r in verdict["results"]]
    assert promoted_flags == sorted(promoted_flags, reverse=True)
