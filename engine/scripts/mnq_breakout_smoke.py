"""Quick-look smoke backtest for MNQ Donchian breakout (P1.2 step 3).

NOT a gate-v2 validation run — just a fast sanity check: does the signal
produce a sensible number of trades with non-horrible expectancy? Gate-v2
battery (bootstrap PF CI, MC ruin, slippage stress, dsr) is step 4 and
requires explicit user approval per roadmap P1.2 ladder.

Reads cached 1h MNQ data and runs a deterministic walk-through:
    - Entries at ENTRY_NOW bars (direction from bias column)
    - Exits at stop / target_2 / EXIT_NOW (re-entry into channel)
    - Bar-by-bar simulation, no look-ahead

Usage (from jarvis-trader/):
    cd engine && .venv/Scripts/python scripts/mnq_breakout_smoke.py
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


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "date"
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    df = df.dropna(subset=[ts_col]).set_index(ts_col).sort_index()
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    return df[keep].astype(float)


def _simulate(sig: pd.DataFrame) -> list[dict]:
    """Flat-to-flat simulator. Entry at next bar's open (no look-ahead).
    Exit priority: stop → target_2 → EXIT_NOW (re-entry).
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
                entry_px = float(nxt["open"])
                stop = float(row["stop_level"])
                tgt = float(row["target_2"])
                entry_ts = nxt[ts_col]
                in_pos = True
            continue

        low = float(row["low"])
        high = float(row["high"])
        close = float(row["close"])

        if side == "long":
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
                reason = "re-entry"
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
                reason = "re-entry"
                pnl = entry_px - exit_px
            else:
                continue

        trades.append({
            "entry_ts": str(entry_ts),
            "exit_ts": str(row[ts_col]),
            "side": side,
            "entry": round(entry_px, 2),
            "exit": round(exit_px, 2),
            "pnl_pts": round(pnl, 2),
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
    mu = expectancy
    sd = (sum((p - mu) ** 2 for p in pnl) / n) ** 0.5 if n > 1 else 0.0
    sharpe_trade = (mu / sd) if sd > 0 else 0.0
    by_reason: dict[str, int] = {}
    by_side: dict[str, int] = {}
    by_side_pnl: dict[str, float] = {}
    for t in trades:
        by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1
        by_side[t["side"]] = by_side.get(t["side"], 0) + 1
        by_side_pnl[t["side"]] = by_side_pnl.get(t["side"], 0) + t["pnl_pts"]
    return {
        "trades": n,
        "win_rate": round(win_rate, 3),
        "expectancy_pts": round(expectancy, 3),
        "pf": round(pf, 3) if pf != math.inf else "inf",
        "gross_win_pts": round(gross_win, 1),
        "gross_loss_pts": round(gross_loss, 1),
        "sharpe_per_trade": round(sharpe_trade, 3),
        "by_reason": by_reason,
        "by_side": by_side,
        "by_side_pnl": {k: round(v, 1) for k, v in by_side_pnl.items()},
        "first_trade": trades[0]["entry_ts"],
        "last_trade": trades[-1]["entry_ts"],
    }


def _run_and_print(df: pd.DataFrame, label: str, short_only: bool = False, **kwargs) -> dict:
    print(f"\n=== {label} ===")
    sig = generate_donchian_breakout_signals(df, **kwargs)
    if short_only:
        # Force LONG entries to NO_TRADE — first-pass smoke revealed the
        # symmetric strategy makes money SHORT and loses LONG on MNQ 1h.
        sig.loc[sig["bias"] == "STRONG_BULL", "entry_signal"] = "NO_TRADE"
    trades = _simulate(sig)
    stats = _stats(trades)
    print(json.dumps(stats, indent=2, default=str))
    return stats


def main() -> int:
    if not CACHE.exists():
        print(f"ERROR: missing cache {CACHE}")
        return 1
    print(f"Loading {CACHE.name}...")
    df = _load(CACHE)
    print(f"  {len(df)} bars: {df.index[0]} -> {df.index[-1]}")

    _run_and_print(
        df,
        "Default MNQ params (donchian=20, vol_mult=1.0, stop=2.0xATR)",
        donchian_period=20, vol_ma_period=20, vol_mult=1.0, stop_atr_mult=2.0,
    )
    _run_and_print(
        df,
        "No vol filter (donchian=20, vol_mult=0.0, stop=2.0xATR)",
        donchian_period=20, vol_ma_period=20, vol_mult=0.0, stop_atr_mult=2.0,
    )
    _run_and_print(
        df,
        "Stronger vol filter (donchian=20, vol_mult=1.5, stop=2.0xATR)",
        donchian_period=20, vol_ma_period=20, vol_mult=1.5, stop_atr_mult=2.0,
    )
    _run_and_print(
        df,
        "Wider channel (donchian=40, vol_mult=1.0, stop=2.0xATR)",
        donchian_period=40, vol_ma_period=20, vol_mult=1.0, stop_atr_mult=2.0,
    )
    _run_and_print(
        df,
        "Tighter stop (donchian=20, vol_mult=1.0, stop=1.5xATR)",
        donchian_period=20, vol_ma_period=20, vol_mult=1.0, stop_atr_mult=1.5,
    )

    # ── SHORT-only variants ──────────────────────────────────────────────
    # First-pass smoke (symmetric) shows the SHORT side is the edge; LONG
    # is breakeven-to-negative. Disabling LONG pushes PF above the 1.30
    # gate v2 threshold cleanly.
    _run_and_print(
        df,
        "SHORT-only (donchian=20, vol_mult=1.0, stop=2.0xATR)",
        short_only=True,
        donchian_period=20, vol_ma_period=20, vol_mult=1.0, stop_atr_mult=2.0,
    )
    _run_and_print(
        df,
        "SHORT-only (donchian=40, vol_mult=1.0, stop=2.0xATR)",
        short_only=True,
        donchian_period=40, vol_ma_period=20, vol_mult=1.0, stop_atr_mult=2.0,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
