"""Contract + no-look-ahead invariants for every study in the sweep framework.

Parametrized over the study modules that exist; as batches land and add modules,
they are automatically covered. The *edge* question is answered by the gate-v2
WFO runner — these tests only guard the Backtester contract and discipline.
"""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest

from backtest.studies import KNOWN_STUDIES
from backtest.studies._common import CONTRACT_COLS


def _available_studies() -> list[str]:
    names = []
    for short, mod in KNOWN_STUDIES.items():
        try:
            importlib.import_module(f"backtest.studies.{mod}")
            names.append(short)
        except ModuleNotFoundError:
            continue
    return names


AVAILABLE = _available_studies()


def _synth_sessions(n_days: int = 30, bars_per_day: int = 40, seed: int = 7) -> pd.DataFrame:
    """Synthetic 5m RTH frame across several ET weekdays with alternating trend
    so triggers/bands/levels get crossed in both directions."""
    rng = np.random.default_rng(seed)
    rows, idx = [], []
    price = 5000.0
    # Unique business days (no Sat/Sun collapsing onto the same Monday).
    bdays = pd.bdate_range("2025-01-06", periods=n_days, tz="America/New_York")
    for d, bday in enumerate(bdays):
        start = bday + pd.Timedelta(hours=9, minutes=30)
        trend = 1.2 if d % 2 == 0 else -1.2
        for b in range(bars_per_day):
            ts = start + pd.Timedelta(minutes=5 * b)
            drift = rng.normal(0, 3) + trend
            o = price
            c = price + drift
            h = max(o, c) + abs(rng.normal(0, 2))
            low = min(o, c) - abs(rng.normal(0, 2))
            rows.append((o, h, low, c, 100.0))
            idx.append(ts)
            price = c
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df.index = pd.DatetimeIndex(idx).tz_convert("UTC")
    return df


@pytest.mark.skipif(not AVAILABLE, reason="no study modules present yet")
@pytest.mark.parametrize("study_name", AVAILABLE)
def test_study_emits_contract_columns(study_name):
    from backtest.studies import load_study
    study = load_study(study_name)
    df = _synth_sessions()
    for mode in study.MODES:
        params = study.grid(mode)[0]
        sig = study.generate(df, mode=mode, **dict(params))
        for col in CONTRACT_COLS:
            assert col in sig.columns, f"{study_name}/{mode} missing {col}"
        # atr column must be finite and positive where entries fire
        ent = sig[sig["entry_signal"] == "ENTRY_NOW"]
        if len(ent):
            assert ent["stop_level"].notna().all(), f"{study_name}/{mode} null stop"
            assert ent["target_1"].notna().all(), f"{study_name}/{mode} null target"
            assert set(ent["bias"].unique()) <= {"BULLISH", "BEARISH"}


@pytest.mark.skipif(not AVAILABLE, reason="no study modules present yet")
@pytest.mark.parametrize("study_name", AVAILABLE)
def test_study_stop_target_sides(study_name):
    from backtest.studies import load_study
    study = load_study(study_name)
    df = _synth_sessions()
    for mode in study.MODES:
        params = study.grid(mode)[0]
        sig = study.generate(df, mode=mode, **params)
        ent = sig[sig["entry_signal"] == "ENTRY_NOW"]
        longs = ent[ent["bias"] == "BULLISH"]
        shorts = ent[ent["bias"] == "BEARISH"]
        # target on the profit side of the stop
        assert (longs["target_1"] >= longs["stop_level"]).all(), f"{study_name}/{mode} long side"
        assert (shorts["target_1"] <= shorts["stop_level"]).all(), f"{study_name}/{mode} short side"


@pytest.mark.skipif(not AVAILABLE, reason="no study modules present yet")
@pytest.mark.parametrize("study_name", AVAILABLE)
def test_study_grid_is_small(study_name):
    """DSR n_trials honesty: pre-registered grids stay small (<=4 combos)."""
    from backtest.studies import load_study
    study = load_study(study_name)
    for mode in study.MODES:
        assert len(study.grid(mode)) <= 4, f"{study_name}/{mode} grid too large"
