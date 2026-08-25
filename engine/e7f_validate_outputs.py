#!/usr/bin/env python
"""E7-FOLLOWUP post-run validation:
1. cards.jsonl is valid JSON per line.
2. Both options verdict JSONs parse via the engine's VerdictSnapshot schema.
3. Trade CSVs load and their PnL sum matches the verdict total_pnl_usd.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

engine_root = Path(__file__).resolve().parent
sys.path.insert(0, str(engine_root))

CARDS = (
    engine_root.parent
    / "docs"
    / "research"
    / "edge-roadmap-candidates-2026-08-18.cards.jsonl"
)
VERDICTS = engine_root / "data" / "gate_v2_verdicts"
OPT_OUT = engine_root / "data" / "options_backtests"

ok = True

# 1. cards.jsonl
try:
    lines = [
        l for l in CARDS.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    cards = [json.loads(l) for l in lines]
    print(f"cards.jsonl: {len(cards)} cards, all valid JSON")
    for c in cards:
        impl = c["implementation_status"]
        v = impl["gate_v2_verdict"][:60]
        print("  " + c["hypothesis_id"] + ": verdict=" + v)
except Exception as e:
    ok = False
    print(f"cards.jsonl FAIL: {e}")

# 2. Verdict schema
try:
    from backtest.gate_v2_policy import VerdictSnapshot

    for name in [
        "SPY_options_vertical_sma_10_40_2.0.json",
        "QQQ_options_vertical_sma_8_40_2.5.json",
    ]:
        p = VERDICTS / name
        snap = VerdictSnapshot.from_dict(json.loads(p.read_text(encoding="utf-8")))
        print(f"{name}: schema OK -> verdict={snap.verdict} family={snap.family}")
except Exception as e:
    ok = False
    print(f"verdict schema check FAIL: {e}")

# 3. Trades CSV <-> verdict total_pnl
for name, expected in [
    ("SPY_vertical_sma_10_40_2.0_trades.csv", 7.73),
    ("QQQ_vertical_sma_8_40_2.5_trades.csv", 8.05),
]:
    p = OPT_OUT / name
    if not p.exists():
        ok = False
        print(f"{name}: MISSING")
        continue
    df = pd.read_csv(p)
    total = round(float(df["pnl"].sum()), 2)
    match = abs(total - expected) < 0.01
    ok = ok and match
    print(
        f"{name}: {len(df)} trades, pnl sum={total} "
        f"(verdict {expected}) {'OK' if match else 'MISMATCH'}"
    )

print("\n=== VALIDATION:", "PASS" if ok else "FAIL", "===")
sys.exit(0 if ok else 1)
