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
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# module_name -> (script filename stem, expected `symbol` field in the output JSON)
_SCRIPTS = {
    "run_qqq_sma12_rank1": "QQQ",
    "run_aapl_sma12_rank1": "AAPL",
    "run_tsla_sma12_rank1": "TSLA",
}


def _seed_for(symbol: str) -> int:
    """Deterministic per-symbol seed. NOT Python's builtin ``hash()`` -- string
    hashing is salted per-process (PYTHONHASHSEED) unless explicitly disabled,
    so ``hash(symbol)`` would silently vary run-to-run/CI-to-CI, making the
    synthetic fixture (and therefore this test's exercised code path) flaky
    -- ``zlib.crc32`` is stable across processes and Python versions."""
    return zlib.crc32(symbol.encode()) % (2**31)


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

    # CRITICAL: main() writes the research-report JSON to the CLI-controlled
    # --out path, but its write_research_verdict(...) call has NO equivalent
    # CLI override -- it always resolves to the real, tracked
    # engine/data/research_verdicts/{symbol}_..._rank1.json via
    # research_verdict.research_verdicts_dir()'s Path(__file__)-derived
    # default. Left unpatched, running this smoke test against synthetic
    # data silently overwrites that real committed verdict file with a
    # bogus, non-reproducible result on every test run (discovered the hard
    # way: a first version of this test corrupted the real QQQ/AAPL/TSLA
    # verdicts committed earlier in this same PR). Redirect it into tmp_path
    # so the smoke test is what it claims to be -- side-effect-free.
    orig_write_verdict = mod.write_research_verdict

    def _write_verdict_to_tmp(**kwargs):
        kwargs.setdefault("base", tmp_path)
        return orig_write_verdict(**kwargs)

    monkeypatch.setattr(mod, "write_research_verdict", _write_verdict_to_tmp)

    data_csv = _synthetic_daily_csv(tmp_path, seed=_seed_for(expected_symbol))
    out_json = tmp_path / f"{expected_symbol}_smoke_out.json"

    monkeypatch.setattr(
        "sys.argv",
        [module_name, "--data", data_csv, "--out", str(out_json)],
    )

    real_verdict_file = (
        Path(mod._ENGINE) / "data" / "research_verdicts" / f"{expected_symbol}_research_equity_trend_rank1.json"
    )
    before = real_verdict_file.read_bytes() if real_verdict_file.exists() else None

    rc = mod.main()
    assert rc == 0

    # The real tracked verdict file must be byte-identical to before this
    # test ran -- the regression guard for the corruption bug described above.
    after = real_verdict_file.read_bytes() if real_verdict_file.exists() else None
    assert after == before, (
        f"{module_name} smoke test wrote to the REAL tracked verdict file "
        f"{real_verdict_file} -- write_research_verdict's `base` redirect "
        f"isn't taking effect."
    )

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
