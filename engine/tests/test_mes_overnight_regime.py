"""
Tests for the regime-conditional MES overnight carry variant.

Focus on the NEW volatility-stress gate (max_rv_annualized) and the
regime runner's 2D grid:
  1. rv_20_ann_pct column present
  2. max_rv=0 is a strict no-op (backward compatible with rank1)
  3. vol gate suppresses entries in a high-vol market + emits VOL_GATED
  4. vol gate keeps entries in a calm market (rv below threshold)
  5. lower max_rv => fewer-or-equal entries (monotonic)
  6. regime RunConfig grid == 8 combos and includes the (0, 0.0) baseline
  7. _find_data_file resolves the MES cache
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.overnight_signals import generate_overnight_signals  # noqa: E402
from backtest.run_mes_overnight_regime_rank1 import (  # noqa: E402
    RunConfig,
    _make_config,
)


def _hourly_df(n_days: int, per_bar_std: float, seed: int = 7) -> pd.DataFrame:
    """Synthetic 1h bars spanning all UTC hours, with a tunable return vol."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-02 00:00:00", periods=n_days * 24, freq="h", tz="UTC")
    log_ret = rng.normal(0, per_bar_std, len(idx))
    close = 4800.0 * np.exp(np.cumsum(log_ret))
    high = close * (1 + rng.uniform(0.0001, 0.001, len(idx)))
    low = close * (1 - rng.uniform(0.0001, 0.001, len(idx)))
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close},
        index=idx,
    )


def _n_entries(out: pd.DataFrame) -> int:
    return int((out["entry_signal"] == "ENTRY_NOW").sum())


# ---------------------------------------------------------------------------
# 1. rv column present
# ---------------------------------------------------------------------------

def test_rv_column_present():
    out = generate_overnight_signals(_hourly_df(30, 0.001))
    assert "rv_20_ann_pct" in out.columns


# ---------------------------------------------------------------------------
# 2. max_rv=0 is a strict no-op vs the rank1 baseline
# ---------------------------------------------------------------------------

def test_max_rv_zero_is_noop():
    df = _hourly_df(30, 0.003)
    base = generate_overnight_signals(df, filter_len=0)
    gated_off = generate_overnight_signals(df, filter_len=0, max_rv_annualized=0.0)
    assert (base["entry_signal"].values == gated_off["entry_signal"].values).all()
    assert _n_entries(base) == _n_entries(gated_off)


# ---------------------------------------------------------------------------
# 3. vol gate suppresses entries in a high-vol market + emits VOL_GATED
# ---------------------------------------------------------------------------

def test_vol_gate_suppresses_high_vol_entries():
    # per_bar_std 0.005 -> rv ~ 0.005 * sqrt(252*24) * 100 ~ 39% (well above 15)
    df = _hourly_df(40, 0.005, seed=11)
    off = generate_overnight_signals(df, filter_len=0, max_rv_annualized=0.0)
    gated = generate_overnight_signals(df, filter_len=0, max_rv_annualized=15.0)
    assert _n_entries(gated) < _n_entries(off), "high-vol entries should be gated out"
    assert (gated["regime"] == "VOL_GATED").any(), "expected VOL_GATED regime label"


# ---------------------------------------------------------------------------
# 4. vol gate keeps entries in a calm market
# ---------------------------------------------------------------------------

def test_vol_gate_keeps_calm_entries():
    # per_bar_std 0.0005 -> rv ~ 3.9% (below a 20% threshold) -> entries kept
    df = _hourly_df(40, 0.0005, seed=5)
    off = generate_overnight_signals(df, filter_len=0, max_rv_annualized=0.0)
    gated = generate_overnight_signals(df, filter_len=0, max_rv_annualized=20.0)
    assert _n_entries(gated) == _n_entries(off), "calm-market entries should survive the gate"


# ---------------------------------------------------------------------------
# 5. lower max_rv => fewer-or-equal entries (monotonic)
# ---------------------------------------------------------------------------

def test_vol_gate_monotonic():
    df = _hourly_df(50, 0.004, seed=3)
    e_off = _n_entries(generate_overnight_signals(df, max_rv_annualized=0.0))   # gate off = most
    e_30 = _n_entries(generate_overnight_signals(df, max_rv_annualized=30.0))
    e_15 = _n_entries(generate_overnight_signals(df, max_rv_annualized=15.0))
    assert e_15 <= e_30 <= e_off


# ---------------------------------------------------------------------------
# 6. regime RunConfig grid == 8 combos incl the (0, 0.0) baseline
# ---------------------------------------------------------------------------

def test_regime_grid_size_and_baseline():
    cfg: RunConfig = _make_config()
    assert len(cfg.grid) == 8, f"Expected 8 grid combos, got {len(cfg.grid)}"
    assert (0, 0.0) in cfg.grid, "grid must include the raw-overnight (0, 0.0) baseline"
    # all combos are (int filter_len, float max_rv)
    for fl, rv in cfg.grid:
        assert isinstance(fl, int) and isinstance(rv, float)


# ---------------------------------------------------------------------------
# 7. _find_data_file resolves the MES cache
# ---------------------------------------------------------------------------

def test_regime_find_data_file_resolves():
    from backtest.run_mes_overnight_regime_rank1 import _find_data_file
    data_file = _find_data_file()
    if data_file is None:
        # MES 1h CSV cache is gitignored / local-only; CI has no cache, so
        # resolution returns None. Skip rather than fail there.
        pytest.skip("MES 1h cache not available (no local cache, e.g. CI)")
    assert data_file.exists() and data_file.suffix == ".csv"
