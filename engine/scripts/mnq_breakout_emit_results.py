"""Emit MNQ breakout SHORT-only don=20 results in the shape consumed by
`validate_strategy.py`. Step 4 of roadmap P1.2 — gate v2 battery input.

Per-trade PnL is converted to DOLLARS using the MNQ contract multiplier
($2 per point, $0.50 per 0.25-tick) so the Monte-Carlo drawdown stats in
`permute_max_dd` compare against a realistic equity base.

Output: `engine/scripts/mnq_breakout_search_results.json`

Usage (from engine/):
    .venv/Scripts/python scripts/mnq_breakout_emit_results.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

_ENGINE = Path(__file__).resolve().parents[1]
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.breakout_signals import generate_donchian_breakout_signals  # noqa: E402

CACHE = _ENGINE / "backtest" / "cache" / "MNQ_2024-04-01_2026-03-27_1h.csv"
OUTPUT = _ENGINE / "scripts" / "mnq_breakout_search_results.json"

# MNQ contract = $2 per point (0.25 tick = $0.50). ES/MES is $5/pt; NQ is
# $20/pt; micro-NQ (MNQ) is 1/10 of NQ = $2/pt.
MNQ_DOLLARS_PER_POINT = 2.0


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


def _simulate_short_only(sig: pd.DataFrame) -> list[dict]:
    """Short-only simulation: skip bars with bias=STRONG_BULL. Otherwise
    mirrors the logic in `mnq_breakout_smoke.py`."""
    trades: list[dict] = []
    in_pos = False
    entry_px = stop = tgt = None
    entry_ts = None

    bars = sig.reset_index()
    ts_col = bars.columns[0]

    for i in range(len(bars) - 1):
        row = bars.iloc[i]
        nxt = bars.iloc[i + 1]

        if not in_pos:
            if row["entry_signal"] == "ENTRY_NOW" and row["bias"] == "STRONG_BEAR":
                entry_px = float(nxt["open"])
                stop = float(row["stop_level"])
                tgt = float(row["target_2"])
                entry_ts = nxt[ts_col]
                in_pos = True
            continue

        low = float(row["low"])
        high = float(row["high"])
        close = float(row["close"])

        # Short-only exit priority: stop > target > re-entry
        if high >= stop:
            exit_px = stop
            reason = "stop"
        elif low <= tgt:
            exit_px = tgt
            reason = "target"
        elif row["exit_signal"] == "EXIT_NOW":
            exit_px = close
            reason = "re-entry"
        else:
            continue

        pnl_pts = entry_px - exit_px
        pnl_dollars = pnl_pts * MNQ_DOLLARS_PER_POINT

        trades.append({
            "entry_time": str(entry_ts),
            "exit_time": str(row[ts_col]),
            "entry": round(entry_px, 2),
            "exit": round(exit_px, 2),
            "pnl": round(pnl_dollars, 4),
            "pnl_pts": round(pnl_pts, 4),
            "reason": reason,
        })
        in_pos = False

    return trades


def _summarize(trades: list[dict], params: dict) -> dict:
    n = len(trades)
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else math.inf
    net_pnl = sum(pnls)
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (-gross_loss / len(losses)) if losses else 0.0
    return {
        "params": params,
        "total_trades": n,
        "pf": round(pf, 4) if pf != math.inf else "inf",
        "wr": round(len(wins) / n, 4) if n else 0.0,
        "net_pnl": round(net_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "trades": trades,
    }


def main() -> int:
    if not CACHE.exists():
        print(f"ERROR: missing cache {CACHE}", file=sys.stderr)
        return 1

    print(f"Loading {CACHE.name}...")
    df = _load(CACHE)
    print(f"  {len(df)} bars: {df.index[0]} -> {df.index[-1]}")

    # Only the single best config for now — can add more variants later.
    params = {
        "donchian_period": 20,
        "vol_ma_period": 20,
        "vol_mult": 1.0,
        "stop_atr_mult": 2.0,
        "short_only": True,
    }
    print(f"Generating signals with {params}")
    sig = generate_donchian_breakout_signals(
        df,
        donchian_period=params["donchian_period"],
        vol_ma_period=params["vol_ma_period"],
        vol_mult=params["vol_mult"],
        stop_atr_mult=params["stop_atr_mult"],
    )

    print("Simulating SHORT-only trades...")
    trades = _simulate_short_only(sig)
    result = _summarize(trades, params)
    print(
        f"  {result['total_trades']} trades | PF {result['pf']} | "
        f"WR {result['wr']} | net ${result['net_pnl']}"
    )

    doc = {
        "symbol": "MNQ",
        "interval": "1h",
        "start": str(df.index[0]),
        "end": str(df.index[-1]),
        "spec": "Donchian breakout SHORT-only (P1.2 gate v2 input)",
        "n_combos": 1,
        "elapsed_sec": 0.0,
        "results": [result],
        "contract_multiplier_usd_per_pt": MNQ_DOLLARS_PER_POINT,
    }
    OUTPUT.write_text(json.dumps(doc, indent=2))
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
