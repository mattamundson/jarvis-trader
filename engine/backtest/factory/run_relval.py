"""Execute the relative-value (pairs) gauntlet across the cointegrated index crosses.

Relative value is a STRUCTURALLY different class than the directional factory
(mean reversion on a spread between two correlated instruments, not directional
momentum). It reuses the same rigor -- WFO windows, gate-v2, PBO, globally-deflated
Sharpe -- but with its own dollar-neutral two-leg backtester. Bar caches are read
READ-ONLY from the primary checkout (gitignored CSVs live only there).

    python -m backtest.factory.run_relval \
        --cache "C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache" \
        --timeframe 1h --out "<scratchpad>"
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from backtest.factory.relval import relval_pairs, render_relval_report, run_relval

DEFAULT_CACHE = "C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--out", default=".")
    ap.add_argument("--timeframe", default="1h")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "relval_results.sqlite"
    report_path = out / "relval_report.md"

    created_at = datetime.now(timezone.utc).isoformat()
    summary = run_relval(relval_pairs(), args.timeframe, args.cache, db_path, created_at)
    report = render_relval_report(summary)
    report_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\n[written] {report_path}")
    print(f"[written] {db_path}")


if __name__ == "__main__":
    main()
