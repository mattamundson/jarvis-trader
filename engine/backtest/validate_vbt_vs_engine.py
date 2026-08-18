"""validate_vbt_vs_engine.py — signal-level cross-validation.

Compares vbt_mes_sweep.generate_signals_vectorized entries/exits against the
JARVIS engine's canonical trend_signals.generate_sma_trend_signals for a set
of combos on the same MES 1h deep cache. Exact bar-by-bar match required.

Run from the engine/ dir with the vectorbt venv:
    ../.venv-vbt/Scripts/python backtest/validate_vbt_vs_engine.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE / "backtest"))

from vbt_mes_sweep import build_combos, generate_signals_vectorized  # noqa: E402

from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402

CSV = ENGINE / "backtest" / "cache" / "MES_2015-01-01_2026-08-16_1h.csv"
CHECK_COMBOS = [(50, 200, 2.0), (60, 200, 2.0), (40, 100, 1.5)]

df = pd.read_csv(CSV, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
combos = build_combos({"fast": [40, 50, 60], "slow": [100, 150, 200, 250, 300, 350], "atr_trail_mult": [1.5, 2.0, 2.5]})

close = df["close"].to_numpy(dtype=float)
high = df["high"].to_numpy(dtype=float)
low = df["low"].to_numpy(dtype=float)

entries, exits = generate_signals_vectorized(close, high, low, combos)

all_ok = True
for fast, slow, mult in CHECK_COMBOS:
    sig = generate_sma_trend_signals(df.copy(), fast=fast, slow=slow, atr_trail_mult=mult)
    eng_entry = (sig["entry_signal"] == "ENTRY_NOW").to_numpy()
    eng_exit = (sig["exit_signal"] == "EXIT_NOW").to_numpy()

    col = int(((combos["fast"] == fast) & (combos["slow"] == slow) & (combos["atr_trail_mult"] == mult)).idxmax())
    vbt_entry = entries[:, col]
    vbt_exit = exits[:, col]

    e_ok = np.array_equal(eng_entry, vbt_entry)
    x_ok = np.array_equal(eng_exit, vbt_exit)
    n_e, n_x = int(eng_entry.sum()), int(eng_exit.sum())
    mismatch_e = np.where(eng_entry != vbt_entry)[0][:5].tolist()
    mismatch_x = np.where(eng_exit != vbt_exit)[0][:5].tolist()
    print(f"combo fast={fast} slow={slow} mult={mult}: entries {n_e} match={e_ok} exits {n_x} match={x_ok}")
    if not e_ok:
        print(f"  entry mismatch bars (first 5): {mismatch_e}")
    if not x_ok:
        print(f"  exit mismatch bars (first 5): {mismatch_x}")
    all_ok = all_ok and e_ok and x_ok

print("VALIDATION:", "PASS" if all_ok else "FAIL")
sys.exit(0 if all_ok else 1)
