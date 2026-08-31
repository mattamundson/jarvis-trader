"""Judge V3 trial-count diagnostics backed by the immutable research ledger.

This module does not change Gate-v2 verdicts. It quantifies how much a runner's
stated ``n_trials`` understates the preregistered campaign search surface, so the
existing empirical DSR diagnostic can be recomputed with an honest count under
explicit human review.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtest.research_trial_ledger import TrialLedger


@dataclass(frozen=True)
class TrialAccountingDiagnostic:
    strategy_family: str
    gate_n_trials: int
    planned_trials: int
    completed_trials: int
    selection_events: int
    honest_n_trials: int
    undercount: int
    inflation_factor: float
    completion_fraction: float
    gate_understates_campaign: bool


def trial_accounting_diagnostic(
    ledger: TrialLedger,
    *,
    strategy_family: str,
    gate_n_trials: int,
) -> TrialAccountingDiagnostic:
    """Compare runner-local trial count with preregistered campaign evidence.

    ``honest_n_trials`` is the maximum of the runner-local count and the number
    of preregistered PLAN events in the requested family. This remains a lower
    bound when research happened before the ledger existed, but unlike verdict
    journal counts it includes every preregistered attempted configuration, not
    merely certifications that were eventually written.
    """
    if not strategy_family.strip():
        raise ValueError("strategy_family must be non-empty")
    if gate_n_trials < 1:
        raise ValueError("gate_n_trials must be >= 1")

    counts = ledger.trial_counts(strategy_family=strategy_family)
    planned = counts["planned"]
    completed = counts["completed"]
    selected = counts["selection_events"]
    honest = max(int(gate_n_trials), int(planned))
    undercount = max(0, honest - int(gate_n_trials))
    inflation = honest / float(gate_n_trials)
    completion_fraction = completed / planned if planned else 0.0

    return TrialAccountingDiagnostic(
        strategy_family=strategy_family,
        gate_n_trials=int(gate_n_trials),
        planned_trials=int(planned),
        completed_trials=int(completed),
        selection_events=int(selected),
        honest_n_trials=honest,
        undercount=undercount,
        inflation_factor=inflation,
        completion_fraction=completion_fraction,
        gate_understates_campaign=planned > gate_n_trials,
    )


def dsr_trial_count_for_review(
    ledger: TrialLedger,
    *,
    strategy_family: str,
    gate_n_trials: int,
) -> int:
    """Return the diagnostic trial count to feed into an explicit DSR re-check.

    This helper intentionally does not invoke DSR or modify any verdict. It only
    provides the count that an independent validation step should use.
    """
    return trial_accounting_diagnostic(
        ledger,
        strategy_family=strategy_family,
        gate_n_trials=gate_n_trials,
    ).honest_n_trials
