"""Execute the strategy-factory pilot on ES/MES + SPY, 1h + 1d.

Reads bar caches READ-ONLY from the primary checkout (gitignored CSVs live only
there). Writes the results DB + markdown report to --out. This is the harness
validation step: run it, then review the report with Amo before scaling.

    python -m backtest.factory.run_pilot \
        --cache "C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache" \
        --out   "<scratchpad>"
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from backtest.factory.orchestrator import (
    Universe,
    pilot_cards,
    render_report,
    run_funnel,
)

DEFAULT_CACHE = "C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--out", default=".")
    ap.add_argument("--instruments", default="MES,SPY")
    ap.add_argument("--timeframes", default="1h,1d")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "pilot_results.sqlite"
    report_path = out / "pilot_report.md"

    universe = Universe(
        instruments=[s.strip() for s in args.instruments.split(",") if s.strip()],
        timeframes=[t.strip() for t in args.timeframes.split(",") if t.strip()],
    )
    created_at = datetime.now(timezone.utc).isoformat()

    summary = run_funnel(pilot_cards(), universe, args.cache, db_path, created_at)
    report = render_report(summary)
    report_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\n[written] {report_path}")
    print(f"[written] {db_path}")


if __name__ == "__main__":
    main()
