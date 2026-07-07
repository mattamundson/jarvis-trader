"""SPY monthly 12mo-SMA momentum — DARK observe-only forward paper-shadow.

Tier-A survivor of the 2026-07-02 X-bookmark edge scan (``sma12_monthly_momentum``,
@QuantifiedStrat): long SPY while monthly close > 12-month SMA, else cash. The
backtest established the prior (Sharpe 0.95, maxDD −16.6% vs buy&hold −50.8%); this
forward record tests whether the edge persists post-inception. Observe-only — no
orders, no DB, does NOT authorize paper routing.

Usage (from engine/):
    .venv/Scripts/python -m backtest.spy_momentum_paper_track            # one observe-only tick
    .venv/Scripts/python -m backtest.spy_momentum_paper_track --report   # forward record + grade
    .venv/Scripts/python -m backtest.spy_momentum_paper_track --backfill-since 2020-01-01  # seed/test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import spy_paper_track_lib as lib  # noqa: E402
from generate_sma12_momentum_signals import generate_sma12_momentum_signals  # noqa: E402

NAME = "spy_momentum"
CAPITAL = 10_000.0


def _sig(bars):
    return generate_sma12_momentum_signals(bars, sma_len=12)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="grade forward record vs backtest prior")
    ap.add_argument("--backfill-since", default=None, help="override inception (YYYY-MM-DD) to seed/test recording")
    args = ap.parse_args()

    if args.report:
        out = lib.report(name=NAME, resample_rule="ME", signal_fn=_sig, capital=CAPITAL)
    else:
        out = lib.tick(name=NAME, resample_rule="ME", signal_fn=_sig, capital=CAPITAL,
                       inception_override=args.backfill_since)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
