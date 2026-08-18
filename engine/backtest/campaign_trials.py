"""Campaign-level trial accounting for the gate-v2 DSR deflation.

WHY THIS EXISTS
---------------
`trade_level_dsr` deflates the observed Sharpe for selection bias using `n_trials`.
Every runner currently passes its OWN grid size (`n_grid_combos`) -- e.g.
`run_mes_trend_rank11.py` passes 3 (fast in [50,55,60]). That is the number of
parameter combinations tried IN THAT ONE RUN.

It is not the number of things that were actually tried before arriving at that
strategy. A single research campaign against one instrument/cache routinely burns
hundreds of trials: neighbourhood screens, composite-strategy grids, VIX-regime
variants, alternate families. Deflating for 3 when the true count is 100s
understates selection bias -- the exact failure mode that retroactively collapsed
MGC's Tier-3 approval on 2026-07-29 when DSR was recomputed at the honest count.

MEASURED SENSITIVITY (2026-08-17 audit, MES 55/200/2.0, n=128 trades, empirical DSR):
    n_trials=3  -> DSR 0.8000  CORE PASS / ALT PASS
    n_trials=9  -> DSR 0.5210  CORE PASS / ALT PASS
    n_trials=27 -> DSR 0.1430  CORE PASS / ALT FAIL
    n_trials=54 -> DSR 0.0165  CORE FAIL / ALT FAIL
    n_trials=82 -> DSR 0.0020  CORE FAIL / ALT FAIL

So the CORE gate breaks somewhere between 27 and 54 campaign trials, and the ALT
gate breaks by 27. This is a real, quantified exposure.

DELIBERATELY NON-BREAKING
-------------------------
This module does NOT change any gate verdict. Flipping a live PASS to FAIL is a
trading-authorization decision that requires explicit human sign-off, not a
library default. What it does instead:

  * counts trials actually recorded against a (symbol, family) in the verdict
    journal, and
  * lets a runner attach a `dsr_campaign_diagnostic` block to its verdict showing
    what DSR WOULD be at the honest trial count.

That makes the exposure impossible to miss on the next read of any verdict, while
leaving the promote/halt decision to a human.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

# Trial counts to report in the diagnostic sweep. Chosen to bracket the observed
# CORE/ALT breakpoints so the reader can see exactly where the verdict turns over.
DIAGNOSTIC_TRIAL_COUNTS: tuple[int, ...] = (3, 9, 27, 54, 82, 150)

_JOURNAL_REL = Path("data/gate_v2_verdicts/_journal.csv")


def count_journaled_trials(
    symbol: str,
    family_prefix: str | None = None,
    journal_path: str | Path | None = None,
) -> int:
    """Number of verdict rows already journaled for a symbol (optionally a family).

    This is a LOWER BOUND on campaign trials: it counts certifications that were
    written to the journal, not the far larger number of screening combinations
    evaluated on the way there. Reported as such -- never presented as exact.

    Returns 0 when the journal is absent or unreadable (never raises).
    """
    path = Path(journal_path) if journal_path else _JOURNAL_REL
    if not path.exists():
        return 0
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, csv.Error, UnicodeDecodeError):
        return 0

    sym = symbol.upper()
    n = 0
    for row in rows:
        row_sym = str(row.get("symbol", "")).upper()
        if row_sym != sym:
            continue
        if family_prefix:
            fam = str(row.get("family", "") or row.get("strategy", ""))
            if not fam.lower().startswith(family_prefix.lower()):
                continue
        n += 1
    return n


def dsr_campaign_diagnostic(
    pnls: Sequence[float],
    initial_capital: float,
    n_trials_used_by_gate: int,
    trial_counts: Iterable[int] = DIAGNOSTIC_TRIAL_COUNTS,
    n_permutations: int = 2_000,
    journaled_trials: int | None = None,
) -> dict:
    """DSR across a sweep of trial counts, for attachment to a gate-v2 verdict.

    Diagnostic only -- the caller must NOT use this to alter a verdict. It answers
    "how much of this PASS is an artifact of deflating for only the runner's own
    grid?" so the exposure is visible at read time.
    """
    from backtest.deflated_sharpe import deflated_sharpe_empirical

    pnl_list = [float(p) for p in pnls]
    if len(pnl_list) < 3:
        return {
            "note": "insufficient trades for DSR diagnostic (<3)",
            "n_trials_used_by_gate": int(n_trials_used_by_gate),
            "sweep": {},
        }

    sweep: dict[str, float] = {}
    for nt in sorted({int(n) for n in trial_counts if int(n) >= 1}):
        res = deflated_sharpe_empirical(
            pnls=pnl_list,
            n_trials=nt,
            initial_capital=initial_capital,
            n_permutations=n_permutations,
        )
        sweep[str(nt)] = round(float(res.get("dsr", 0.0)), 4)

    # Where does each gate threshold stop being met as trials increase?
    def _breakpoint(threshold: float) -> int | None:
        for nt in sorted(int(k) for k in sweep):
            if sweep[str(nt)] < threshold:
                return nt
        return None

    return {
        "note": (
            "DIAGNOSTIC ONLY -- does not affect the verdict. The gate deflates for "
            "this runner's own grid size; a research campaign against one cache "
            "typically spans far more trials. See campaign_trials.py."
        ),
        "n_trials_used_by_gate": int(n_trials_used_by_gate),
        "journaled_trials_lower_bound": journaled_trials,
        "n_permutations": int(n_permutations),
        "sweep": sweep,
        "core_fails_at_or_above_trials": _breakpoint(0.1),
        "alt_fails_at_or_above_trials": _breakpoint(0.3),
    }
