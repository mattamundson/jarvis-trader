"""SPY weekly Supertrend — DARK observe-only forward paper-shadow.

Tier-B survivor of the 2026-07-02 X-bookmark edge scan (``supertrend_weekly_spx``,
@QuantifiedStrat): long/cash on a weekly Supertrend(ATR10, ×3). The backtest
established the prior (Sharpe 0.735 > buy&hold 0.685, maxDD −27% vs −55%); this
forward record tests whether the edge persists post-inception. Observe-only — no
orders, no DB, does NOT authorize paper routing.

Usage (from engine/):
    .venv/Scripts/python -m backtest.spy_supertrend_paper_track            # one observe-only tick
    .venv/Scripts/python -m backtest.spy_supertrend_paper_track --report   # forward record + grade
    .venv/Scripts/python -m backtest.spy_supertrend_paper_track --backfill-since 2020-01-01  # seed/test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import spy_paper_track_lib as lib  # noqa: E402
from generate_supertrend_signals import generate_supertrend_signals  # noqa: E402

NAME = "spy_supertrend"
CAPITAL = 10_000.0


def _sig(bars):
    return generate_supertrend_signals(bars, atr_period=10, multiplier=3.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="grade forward record vs backtest prior")
    ap.add_argument("--backfill-since", default=None, help="override inception (YYYY-MM-DD) to seed/test recording")
    args = ap.parse_args()

    if args.report:
        out = lib.report(name=NAME, resample_rule="W-FRI", signal_fn=_sig, capital=CAPITAL)
    else:
        out = lib.tick(name=NAME, resample_rule="W-FRI", signal_fn=_sig, capital=CAPITAL,
                       inception_override=args.backfill_since)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
