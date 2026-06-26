"""Execute the Phase-4 combination test across the current relval survivors.

The survivors (relval pairs that PASSED robustness) are the forward-shadow
candidates. This measures whether running them as a blended book is risk-superior
to running each alone -- a portfolio-construction question, in-sample, no tuning.

    python -m backtest.factory.run_combos \
        --cache "C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache" \
        --timeframe 1h --out "<scratchpad>"
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backtest.factory.combos import Survivor, render_combos_report, run_combos

DEFAULT_CACHE = "C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache"

# Current robustness-PASS survivors (see relval_report.md). Default params, the
# exact config each passed under. Add a Survivor here when a new pair passes.
SURVIVORS = [
    Survivor(name="ZB_ZN", leg_a="ZB", leg_b="ZN"),
    Survivor(name="M6E_M6B", leg_a="M6E", leg_b="M6B"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--out", default=".")
    ap.add_argument("--timeframe", default="1h")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = run_combos(SURVIVORS, args.timeframe, args.cache)
    report = render_combos_report(results, args.timeframe)
    (out / "combos_report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"[written] {out / 'combos_report.md'}")


if __name__ == "__main__":
    main()
