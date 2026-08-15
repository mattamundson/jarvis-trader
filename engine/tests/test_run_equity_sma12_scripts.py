"""Smoke tests for the QQQ/AAPL/TSLA sma12_monthly_momentum backtest+gate-v2 runners.

These three scripts (`backtest/run_qqq_sma12_rank1.py`, `run_aapl_sma12_rank1.py`,
`run_tsla_sma12_rank1.py`) are adapted from the pre-existing `run_spy_sma12_rank1.py`
template to fill the QQQ/AAPL/TSLA validation gap documented in `engine/CLAUDE.md`
"Active Instruments > Equities". No prior test covered any of the four `run_spy_*`
scripts, so this establishes the first coverage for the pattern -- not just for the
three new files.

No network access, no dependency on the real `backtest/cache/` CSVs: each test builds a
small synthetic daily OHLCV series with enough oscillation to produce multiple 12-month
SMA regime flips (so the gate-v2 battery sees a non-empty, non-degenerate PnL list) and
points the script at it via `--data`/`--out`, exactly like a real invocation would via
CLI flags.
"""

from __future__ import annotations

import importlib
import json

import numpy as np
import pandas as pd
import pytest

# module_name -> (script filename stem, expected `symbol` field in the output JSON)
_SCRIPTS = {
    "run_qqq_sma12_rank1": "QQQ",
    "run_aapl_sma12_rank1": "AAPL",
    "run_tsla_sma12_rank1": "TSLA",
}


def _synthetic_daily_csv(tmp_path, seed: int) -> str:
    """Build ~6 years of business-day OHLCV with several trend reversals, so the
    12-month SMA filter produces multiple long/cash regime flips (non-empty,
    non-degenerate in-market PnL series) instead of a single flat regime."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-02", periods=1500, freq="B")
    n = len(dates)
    t = np.arange(n)
    # Three multi-year trend segments (up / down / up) plus small daily noise --
    # guarantees at least two SMA-12mo crossings once the 12-month warmup passes.
    seg = n // 3
    trend = np.concatenate(
        [
            np.linspace(100, 180, seg),
            np.linspace(180, 90, seg),
            np.linspace(90, 220, n - 2 * seg),
        ]
    )
    noise = rng.normal(0, 1.5, n).cumsum() * 0.05
    close = np.clip(trend + noise, 5, None)
    df = pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 1_000_000,
        }
    )
    path = tmp_path / "SYNTH_1d.csv"
    df.to_csv(path, index=False)
    return str(path)


@pytest.mark.parametrize("module_name,expected_symbol", sorted(_SCRIPTS.items()))
def test_runner_end_to_end_smoke(tmp_path, monkeypatch, module_name, expected_symbol):
    """Each runner's main() should execute end-to-end against synthetic data, exit 0,
    and write a gate_v2-shaped report JSON to --out (the exact symbol/strategy tag is
    the one hardcoded for that script -- these scripts are per-symbol by design, not
    parameterized, matching the run_spy_*.py precedent)."""
    mod = importlib.import_module(f"backtest.{module_name}")

    data_csv = _synthetic_daily_csv(tmp_path, seed=hash(expected_symbol) % (2**31))
    out_json = tmp_path / f"{expected_symbol}_smoke_out.json"

    monkeypatch.setattr(
        "sys.argv",
        [module_name, "--data", data_csv, "--out", str(out_json)],
    )

    rc = mod.main()
    assert rc == 0

    assert out_json.exists()
    payload = json.loads(out_json.read_text())
    assert payload["symbol"] == expected_symbol
    assert payload["strategy"] == "sma12_monthly_momentum"
    assert "gate_v2" in payload
    assert payload["gate_v2"]["verdict"] in {"PASS", "FAIL"}
    assert payload["gate_v2"]["core_verdict"] in {"PASS", "FAIL"}
    # alt path is never scored by these runners (no aux evidence supplied) --
    # matches the SPY templates' behavior exactly.
    assert payload["gate_v2"]["alt_verdict"] == "UNSCORED"
    assert payload["n_in_market_trades"] >= 1


def test_runners_default_data_path_is_engine_relative():
    """Regression guard: unlike the SPY templates (hardcoded absolute path into the
    main checkout), these three must resolve their default --data path relative to the
    engine root (derived from the module's own file location) so the script works
    unmodified from any checkout/worktree."""
    import os

    for module_name in _SCRIPTS:
        mod = importlib.import_module(f"backtest.{module_name}")
        engine_root = os.path.dirname(os.path.dirname(os.path.abspath(mod.__file__)))
        assert mod._DEFAULT_DATA.startswith(engine_root), (
            f"{module_name}._DEFAULT_DATA must live under the engine root "
            f"({engine_root!r}), got {mod._DEFAULT_DATA!r}"
        )
