"""Visualize the ATR-trail (TOS ATRTrailingStopLE/SE) strategy's ACTUAL trades.

Answers "show me WHERE and WHY it failed." Plots, on your own bars:
  - price + the dotted ATR trailing-stop line (green=long state, red=short),
  - every flip entry (^ long / v short) and the trade segment to its exit,
    colored green (winner) / red (loser),
  - the cumulative equity curve (the honest aggregate — no cherry-picking),
  - text annotations on the worst losers.

Also writes a trades JSON so the result can be pushed and reviewed trade-by-trade.

Zoom to any window you watched live with --start/--end — the strategy is the
same everywhere, so you can point it straight at a "perfect bounce" you remember
and see what the systematic rule actually did there.

Run locally (needs your gitignored cache bars + matplotlib):
    .venv/Scripts/python -m backtest.plot_atr_trail_trades \
        --data-file backtest/cache/MES_..._5m_cont.csv \
        --out docs/reports/atr_trail_trades.png
    # zoom:
    ... --start 2026-06-18 --end 2026-06-25
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from backtest.indicators import atr_trailing_stop  # noqa: E402

MULTIPLIERS = {"MES": 5.0, "ES": 50.0, "MNQ": 2.0, "MCL": 100.0, "MGC": 10.0}
TICK = {"MES": 0.25, "ES": 0.25, "MNQ": 0.25, "MCL": 0.01, "MGC": 0.1}
COMMISSION = 0.62  # $/round-trip
SLIPPAGE_TICKS = 1.0  # per side


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    for tcol in ("timestamp", "datetime", "date", "time"):
        if tcol in df.columns:
            df[tcol] = pd.to_datetime(df[tcol], utc=True)
            return df.set_index(tcol).sort_index()
    raise SystemExit(f"No timestamp column in {path.name}; columns={list(df.columns)}")


def _reconstruct_trades(df: pd.DataFrame, symbol: str, period: int, factor: float) -> list[dict]:
    """Flip-to-flip trades: enter on the trail flip, exit on the opposite flip.

    This IS the TOS ATRTrailingStopLE/SE rule. P&L is net of the same commission
    + slippage the backtest uses, so the equity curve here matches the strategy.
    """
    trail, state = atr_trailing_stop(df["high"], df["low"], df["close"], period=period, factor=factor)
    mult = MULTIPLIERS.get(symbol, 1.0)
    cost = COMMISSION + 2 * SLIPPAGE_TICKS * TICK.get(symbol, 0.25) * mult  # round trip
    close = df["close"]
    trades: list[dict] = []
    open_t = None
    for i in range(len(df)):
        s = state.iloc[i]
        if pd.isna(s):
            continue
        prev = state.iloc[i - 1] if i > 0 else float("nan")
        if not pd.isna(prev) and s != prev:  # a flip
            px = float(close.iloc[i])
            if open_t is not None:
                d = open_t["dir"]
                pnl_pts = (px - open_t["entry_px"]) * d
                trades.append({
                    **open_t,
                    "exit_time": df.index[i], "exit_px": px,
                    "pnl_pts": round(pnl_pts, 4),
                    "pnl_usd": round(pnl_pts * mult - cost, 2),
                })
            open_t = {"entry_time": df.index[i], "entry_px": px, "dir": 1 if s == 1.0 else -1}
    return trades


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot ATR-trail flip trades on your bars")
    ap.add_argument("--symbol", default="MES")
    ap.add_argument("--data-file", required=True)
    ap.add_argument("--period", type=int, default=5)
    ap.add_argument("--factor", type=float, default=3.5)
    ap.add_argument("--start", default=None, help="zoom window start YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="zoom window end YYYY-MM-DD")
    ap.add_argument("--out", default="docs/reports/atr_trail_trades.png")
    ap.add_argument("--worst", type=int, default=8, help="annotate the N worst losers")
    args = ap.parse_args()

    df = _load(Path(args.data_file))
    trades = _reconstruct_trades(df, args.symbol, args.period, args.factor)
    # Equity over the FULL series (the honest aggregate), computed before zoom.
    for k, t in enumerate(trades):
        t["cum_usd"] = round(sum(x["pnl_usd"] for x in trades[: k + 1]), 2)

    # Optional zoom for the plot only.
    plot_df = df
    if args.start:
        plot_df = plot_df[plot_df.index >= pd.Timestamp(args.start, tz="UTC")]
    if args.end:
        plot_df = plot_df[plot_df.index <= pd.Timestamp(args.end, tz="UTC")]
    win = (plot_df.index.min(), plot_df.index.max())
    vis = [t for t in trades if win[0] <= t["entry_time"] <= win[1]]

    trail, state = atr_trailing_stop(
        df["high"], df["low"], df["close"], period=args.period, factor=args.factor
    )

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(16, 9), height_ratios=[3, 1], sharex=True,
        gridspec_kw={"hspace": 0.08},
    )
    ax1.plot(plot_df.index, plot_df["close"], color="0.5", lw=0.8, zorder=1)
    long_m = (state.reindex(plot_df.index) == 1.0)
    ax1.scatter(plot_df.index[long_m], trail.reindex(plot_df.index)[long_m], s=2, color="lime", zorder=2)
    ax1.scatter(plot_df.index[~long_m], trail.reindex(plot_df.index)[~long_m], s=2, color="red", zorder=2)

    wins = losses = 0
    for t in vis:
        c = "green" if t["pnl_usd"] > 0 else "red"
        wins += t["pnl_usd"] > 0
        losses += t["pnl_usd"] <= 0
        ax1.plot([t["entry_time"], t["exit_time"]], [t["entry_px"], t["exit_px"]],
                 color=c, lw=1.2, alpha=0.7, zorder=3)
        ax1.scatter([t["entry_time"]], [t["entry_px"]],
                    marker="^" if t["dir"] == 1 else "v", s=40,
                    color=c, edgecolor="k", lw=0.4, zorder=4)
    for t in sorted(vis, key=lambda x: x["pnl_usd"])[: args.worst]:
        ax1.annotate(f"${t['pnl_usd']:.0f}", (t["exit_time"], t["exit_px"]),
                     fontsize=7, color="darkred")

    ax1.set_title(
        f"{args.symbol} ATR-trail FLIP (period={args.period}, factor={args.factor}) — "
        f"{len(vis)} trades shown ({wins}W/{losses}L) | dotted line = the TOS stop"
    )
    ax1.set_ylabel("price")
    ax1.grid(alpha=0.2)

    if trades:
        ax2.plot([t["exit_time"] for t in trades], [t["cum_usd"] for t in trades],
                 color="steelblue", lw=1.2)
        ax2.axhline(0, color="k", lw=0.6)
        ax2.fill_between([t["exit_time"] for t in trades], [t["cum_usd"] for t in trades],
                         0, alpha=0.15, color="steelblue")
        ax2.set_xlim(*win)
    net = sum(t["pnl_usd"] for t in trades)
    wr = sum(t["pnl_usd"] > 0 for t in trades) / len(trades) if trades else 0
    ax2.set_title(
        f"Equity curve (FULL period, all {len(trades)} trades): "
        f"net ${net:,.0f}, win rate {wr:.0%} — this is the whole strategy, not a sample",
        fontsize=9,
    )
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax2.grid(alpha=0.2)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"[plot] wrote {out}")

    # Trades JSON for trade-by-trade review (push this; it's not gitignored).
    js = out.with_suffix(".trades.json")
    worst = sorted(trades, key=lambda x: x["pnl_usd"])[:15]
    js.write_text(json.dumps(
        {
            "symbol": args.symbol, "period": args.period, "factor": args.factor,
            "n_trades": len(trades), "net_usd": round(net, 2), "win_rate": round(wr, 4),
            "worst_15": [
                {**t, "entry_time": str(t["entry_time"]), "exit_time": str(t["exit_time"])}
                for t in worst
            ],
        },
        indent=2,
    ))
    print(f"[plot] wrote {js}")
    print(f"\nSUMMARY: {len(trades)} trades, net ${net:,.0f}, win rate {wr:.0%}")
    print("Worst 5 trades:")
    for t in worst[:5]:
        print(f"  {str(t['entry_time'])[:16]} {('LONG' if t['dir']==1 else 'SHORT')} "
              f"{t['entry_px']:.2f}->{t['exit_px']:.2f}  ${t['pnl_usd']:.0f}")


if __name__ == "__main__":
    main()
