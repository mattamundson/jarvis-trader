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
    FACTORY_INSTRUMENTS,
    Universe,
    factory_cards,
    pilot_cards,
    render_report,
    run_funnel,
)

DEFAULT_CACHE = "C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--out", default=".")
    ap.add_argument("--cardset", choices=["pilot", "factory"], default="pilot")
    ap.add_argument("--instruments", default="")  # blank -> cardset default
    ap.add_argument("--timeframes", default="1h")
    args = ap.parse_args()

    cards = factory_cards() if args.cardset == "factory" else pilot_cards()
    default_inst = ",".join(FACTORY_INSTRUMENTS) if args.cardset == "factory" else "MES,SPY"
    instruments_arg = args.instruments or default_inst

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / f"{args.cardset}_results.sqlite"
    report_path = out / f"{args.cardset}_report.md"

    universe = Universe(
        instruments=[s.strip() for s in instruments_arg.split(",") if s.strip()],
        timeframes=[t.strip() for t in args.timeframes.split(",") if t.strip()],
    )
    created_at = datetime.now(timezone.utc).isoformat()

    summary = run_funnel(cards, universe, args.cache, db_path, created_at)
    report = render_report(summary)
    report_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\n[written] {report_path}")
    print(f"[written] {db_path}")


if __name__ == "__main__":
    main()
