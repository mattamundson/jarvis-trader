"""Build the diversified seasonal book from the calendar passers.

The gate-v2 PASSers + the strongest bond candidate, chosen to span 3 asset classes
x 3 disjoint day-sets so the correlation matrix shows what actually diversifies:

    pre_holiday:        SPY (equity), GLD (gold)      -- ~9 holidays/yr
    santa_claus:        SPY (equity), EEM (EM)        -- late-Dec/early-Jan
    last_day_of_month:  TLT (bonds)                   -- month-end

    .venv/Scripts/python -m backtest.run_calendar_combos --out "<scratchpad>"
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backtest.calendar_combos import (
    Sleeve,
    align,
    build_book,
    correlation_matrix,
    render_report,
    sleeve_returns,
)

# gate-PASS sleeves + the bond-specific candidate (max asset/day-set spread).
SLEEVES = [
    Sleeve("SPY", "pre_holiday"),
    Sleeve("GLD", "pre_holiday"),
    Sleeve("SPY", "santa_claus"),
    Sleeve("EEM", "santa_claus"),
    Sleeve("TLT", "last_day_of_month"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".")
    args = ap.parse_args()

    result = build_book(SLEEVES)
    corr = correlation_matrix(align([sleeve_returns(s) for s in SLEEVES]))
    report = render_report(result, corr)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "calendar_combos_report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"[written] {out / 'calendar_combos_report.md'}")


if __name__ == "__main__":
    main()
