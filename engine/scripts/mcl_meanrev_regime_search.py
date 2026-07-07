"""
MCL Bollinger+RSI mean-reversion WITH regime filter — gate v2 battery harness.

Track 4 follow-up: the bbwidth<=40pct filter surfaced a real edge on MCL
(PF 1.695, n=54 per smoke test). This script wraps the filtered variant in
a `_run(df, params, spec) -> dict` harness so the 3 ALT validators can score it.

Separate from `mcl_meanrev_search.py` (V1 strategy, no RSI gate, no regime
filter) to avoid mutating V1 results. V1 stays the baseline reference;
this module is V2.

Usage (from engine/):
    # Emit a single-entry results JSON for the bbwidth variant:
    .venv/Scripts/python -u -m scripts.mcl_meanrev_regime_search --emit-only

    # The 3 ALT validators consume _run via --family meanrev_regime.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402
from backtest.data_loader import BacktestDataLoader  # noqa: E402
from backtest.meanrev_signals import generate_bollinger_rsi_signals  # noqa: E402

SYMBOL_SPECS = {
    sym: {
        "multiplier": spec.multiplier,
        "tick_size": spec.tick_size,
        "commission": spec.commission,
        "slippage_ticks": spec.slippage_ticks,
    }
    for sym, spec in CONTRACT_SPECS.items()
    if sym in ("MCL", "MES", "MNQ", "MGC")
}

CONTRACTS = 1
INITIAL_CAPITAL = 10_000.0


def _run(
    df: pd.DataFrame,
    bb_period: int,
    bb_std: float,
    rsi_long: float,
    rsi_short: float,
    stop_atr_mult: float,
    regime_filter_mode: str,
    regime_filter_bbwidth_pct: float,
    regime_filter_adx_threshold: float,
    spec: dict,
) -> dict:
    """Simulate MCL mean-rev WITH regime filter and return the standard metrics
    dict (matches mes_trend_search / mcl_meanrev_search schema).
    """
    sig = generate_bollinger_rsi_signals(
        df,
        bb_period=bb_period,
        bb_std=bb_std,
        rsi_long=rsi_long,
        rsi_short=rsi_short,
        stop_atr_mult=stop_atr_mult,
        regime_filter_mode=regime_filter_mode,
        regime_filter_bbwidth_pct=regime_filter_bbwidth_pct,
        regime_filter_adx_threshold=regime_filter_adx_threshold,
    )

    multiplier = spec["multiplier"]
    tick_size = spec["tick_size"]
    commission = spec["commission"]
    slippage_ticks = spec.get("slippage_ticks", 1)
    slip_usd = slippage_ticks * tick_size * multiplier * CONTRACTS
    commission_round = commission * 2 * CONTRACTS

    trades = _simulate_usd(sig, multiplier, slip_usd, commission_round)

    if not trades:
        return {"total_trades": 0, "pf": 0.0, "wr": 0.0, "net_pnl": 0.0, "ret_pct": 0.0,
                "trades": [], "avg_win": 0.0, "avg_loss": 0.0}

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    wr = len(wins) / len(pnls)
    net_pnl = sum(pnls)
    ret_pct = net_pnl / INITIAL_CAPITAL * 100
    import numpy as np
    return {
        "total_trades": len(trades),
        "pf": round(pf, 3) if pf != float("inf") else 999.0,
        "wr": round(wr * 100, 2),
        "net_pnl": round(net_pnl, 2),
        "ret_pct": round(ret_pct, 2),
        "trades": trades,
        "avg_win": round(float(np.mean(wins)), 2) if wins else 0.0,
        "avg_loss": round(float(np.mean(losses)), 2) if losses else 0.0,
    }


def _simulate_usd(
    sig: pd.DataFrame, multiplier: float, slip_usd: float, commission_round: float,
) -> list[dict]:
    """Simulate trades with USD pnl. Mirrors mcl_meanrev_smoke._simulate but
    emits USD (not points) and includes costs so validate_strategy's bootstrap
    works on the correct scale.
    """
    trades: list[dict] = []
    in_pos = False
    side = None
    entry_px = stop = tgt = None
    entry_ts = None

    # Be tolerant to the loader returning timestamp both as index AND column.
    if "timestamp" in sig.columns:
        bars = sig.reset_index(drop=True)
        ts_col = "timestamp"
    else:
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
                tgt = float(row["target_3"])
                entry_ts = nxt[ts_col]
                in_pos = True
            continue

        low_ = float(row["low"])
        high_ = float(row["high"])
        close_ = float(row["close"])

        if side == "long":
            if low_ <= stop:
                exit_px = stop
                reason = "stop"
            elif high_ >= tgt:
                exit_px = tgt
                reason = "target"
            elif row["exit_signal"] == "EXIT_NOW":
                exit_px = close_
                reason = "midband"
            else:
                continue
            pnl = (exit_px - entry_px) * multiplier * CONTRACTS - 2 * slip_usd - commission_round
        else:
            if high_ >= stop:
                exit_px = stop
                reason = "stop"
            elif low_ <= tgt:
                exit_px = tgt
                reason = "target"
            elif row["exit_signal"] == "EXIT_NOW":
                exit_px = close_
                reason = "midband"
            else:
                continue
            pnl = (entry_px - exit_px) * multiplier * CONTRACTS - 2 * slip_usd - commission_round

        trades.append({
            "entry_time": str(entry_ts),
            "exit_time": str(row[ts_col]),
            "side": side,
            "entry": round(entry_px, 4),
            "exit": round(exit_px, 4),
            "pnl": round(pnl, 2),
            "reason": reason,
        })
        in_pos = False

    return trades


def main() -> int:
    ap = argparse.ArgumentParser(description="MCL bbwidth-gated mean-rev _run + emit")
    ap.add_argument("--symbol", default="MCL", choices=sorted(SYMBOL_SPECS.keys()))
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--start", default="2024-04-01")
    ap.add_argument("--end", default="2026-03-27")
    ap.add_argument("--bb-period", type=int, default=20)
    ap.add_argument("--bb-std", type=float, default=2.0)
    ap.add_argument("--rsi-long", type=float, default=30.0)
    ap.add_argument("--rsi-short", type=float, default=70.0)
    ap.add_argument("--stop-atr-mult", type=float, default=1.5)
    ap.add_argument("--regime-filter-mode", default="bbwidth",
                    choices=["none", "adx", "bbwidth", "keltner"])
    ap.add_argument("--regime-filter-bbwidth-pct", type=float, default=40.0)
    ap.add_argument("--regime-filter-adx-threshold", type=float, default=20.0)
    args = ap.parse_args()

    symbol = args.symbol.upper()
    spec = SYMBOL_SPECS[symbol]

    loader = BacktestDataLoader()
    df = loader.load(symbol, args.start, args.end, args.interval)
    if df is None or df.empty:
        print(f"[ERROR] No data for {symbol}", flush=True)
        return 1

    params = {
        "bb_period": args.bb_period,
        "bb_std": args.bb_std,
        "rsi_long": args.rsi_long,
        "rsi_short": args.rsi_short,
        "stop_atr_mult": args.stop_atr_mult,
        "regime_filter_mode": args.regime_filter_mode,
        "regime_filter_bbwidth_pct": args.regime_filter_bbwidth_pct,
        "regime_filter_adx_threshold": args.regime_filter_adx_threshold,
    }

    print(f"Running {symbol} {args.interval} {args.start}->{args.end} "
          f"regime={args.regime_filter_mode}", flush=True)
    r = _run(df, **dict(params.items()), spec=spec)
    print(f"  PF={r['pf']} WR={r['wr']}% n={r['total_trades']} ret={r['ret_pct']:+.2f}%",
          flush=True)

    out = {
        "symbol": symbol, "interval": args.interval,
        "start": args.start, "end": args.end,
        "spec": spec, "n_combos": 1,
        "results": [{"params": params, **r}],
    }
    out_path = _HERE / f"{symbol.lower()}_meanrev_regime_search_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Saved {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
