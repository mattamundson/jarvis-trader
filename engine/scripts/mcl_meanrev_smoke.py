"""Quick-look smoke backtest for MCL Bollinger+RSI mean-reversion (P1.1 step 3).

NOT a gate-v2 validation run — just a fast sanity check: does the signal
produce a sensible number of trades with non-horrible expectancy? Gate-v2
battery (bootstrap PF CI, MC ruin, slippage stress, dsr) is step 4 and
requires explicit user approval per roadmap P1.1 ladder.

Reads cached 1h MCL data and runs a deterministic walk-through:
    - Entries at ENTRY_NOW bars (direction from bias column)
    - Exits at stop / target_3 (full reversion) / EXIT_NOW (midband cross)
    - Bar-by-bar simulation, no look-ahead

Usage (from jarvis-trader/):
    cd engine && .venv/Scripts/python scripts/mcl_meanrev_smoke.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd


# Ensure engine is importable
_ENGINE = Path(__file__).resolve().parents[1]
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.meanrev_signals import generate_bollinger_rsi_signals  # noqa: E402


CACHE = _ENGINE / "backtest" / "cache" / "MCL_2024-01-01_2026-03-28_1h.csv"


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Normalize column names
    df.columns = [c.strip().lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "date"
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=[ts_col]).set_index(ts_col).sort_index()
    # Keep only the essentials
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    return df[keep].astype(float)


def _simulate(sig: pd.DataFrame) -> list[dict]:
    """Simulate trades deterministically: one position at a time, flat-to-flat.

    Entry at the next bar's open after ENTRY_NOW fires (no look-ahead).
    Exit: first of { stop, target_3 (extreme reversion), EXIT_NOW (midband) }.
    """
    trades: list[dict] = []
    in_pos = False
    side = None
    entry_px = stop = tgt = None
    entry_ts = None

    bars = sig.reset_index()
    ts_col = bars.columns[0]

    for i in range(len(bars) - 1):
        row = bars.iloc[i]
        nxt = bars.iloc[i + 1]

        if not in_pos:
            if row["entry_signal"] == "ENTRY_NOW" and row["bias"] in ("STRONG_BULL", "STRONG_BEAR"):
                side = "long" if row["bias"] == "STRONG_BULL" else "short"
                # Execute at next bar's open (avoids look-ahead)
                entry_px = float(nxt["open"])
                stop = float(row["stop_level"])
                tgt = float(row["target_3"])  # use target_3 as "full reversion" target
                entry_ts = nxt[ts_col]
                in_pos = True
            continue

        # In position — check exits on this bar
        low = float(row["low"])
        high = float(row["high"])
        close = float(row["close"])

        if side == "long":
            # Pessimistic order: stop checked before target
            if low <= stop:
                exit_px = stop
                reason = "stop"
                pnl = exit_px - entry_px
            elif high >= tgt:
                exit_px = tgt
                reason = "target"
                pnl = exit_px - entry_px
            elif row["exit_signal"] == "EXIT_NOW":
                exit_px = close
                reason = "midband"
                pnl = exit_px - entry_px
            else:
                continue
        else:
            if high >= stop:
                exit_px = stop
                reason = "stop"
                pnl = entry_px - exit_px
            elif low <= tgt:
                exit_px = tgt
                reason = "target"
                pnl = entry_px - exit_px
            elif row["exit_signal"] == "EXIT_NOW":
                exit_px = close
                reason = "midband"
                pnl = entry_px - exit_px
            else:
                continue

        trades.append({
            "entry_ts": str(entry_ts),
            "exit_ts": str(row[ts_col]),
            "side": side,
            "entry": round(entry_px, 4),
            "exit": round(exit_px, 4),
            "pnl_pts": round(pnl, 4),
            "reason": reason,
        })
        in_pos = False

    return trades


def _stats(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    pnl = [t["pnl_pts"] for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else math.inf
    win_rate = len(wins) / n
    expectancy = sum(pnl) / n
    # Crude Sharpe: mean / std of per-trade pnl * sqrt(trades-per-year-guess)
    mu = expectancy
    sd = (sum((p - mu) ** 2 for p in pnl) / n) ** 0.5 if n > 1 else 0.0
    sharpe_trade = (mu / sd) if sd > 0 else 0.0
    # Reason breakdown
    by_reason: dict[str, int] = {}
    for t in trades:
        by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1
    return {
        "trades": n,
        "win_rate": round(win_rate, 3),
        "expectancy_pts": round(expectancy, 4),
        "pf": round(pf, 3) if pf != math.inf else "inf",
        "gross_win_pts": round(gross_win, 2),
        "gross_loss_pts": round(gross_loss, 2),
        "sharpe_per_trade": round(sharpe_trade, 3),
        "by_reason": by_reason,
        "first_trade": trades[0]["entry_ts"],
        "last_trade": trades[-1]["entry_ts"],
    }


def main() -> int:
    if not CACHE.exists():
        print(f"ERROR: missing cache {CACHE}")
        return 1
    print(f"Loading {CACHE.name}...")
    df = _load(CACHE)
    print(f"  {len(df)} bars: {df.index[0]} → {df.index[-1]}")

    print("\n=== Default MCL params (bb=20, std=2.0, rsi 30/70, stop=1.5×ATR) ===")
    sig = generate_bollinger_rsi_signals(df)
    trades = _simulate(sig)
    stats = _stats(trades)
    print(json.dumps(stats, indent=2, default=str))

    print("\n=== Loose thresholds (rsi 40/60, stop=2.0×ATR) — more trades ===")
    sig2 = generate_bollinger_rsi_signals(df, rsi_long=40.0, rsi_short=60.0, stop_atr_mult=2.0)
    trades2 = _simulate(sig2)
    stats2 = _stats(trades2)
    print(json.dumps(stats2, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
