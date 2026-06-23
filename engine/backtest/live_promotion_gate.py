"""Live-capital promotion gate — the enforced definition-of-done (Task 10).

This is the single hard check the live-wiring MUST call before any strategy is
allowed to risk real capital. It turns the prose DoD into code: a candidate can
be promoted only when EVERY pillar is satisfied. Default-deny — a missing or
unknown pillar blocks (fail-safe), and a sub-neutral agent ensemble
(Brier >= 0.25, i.e. no better than always predicting 0.5) is a hard block
regardless of how good the backtest looks.

This module is pure and read-only: it evaluates evidence, it does not authorize
trading itself. Wiring it into the actual order path (so promotion is *enforced*,
not advisory) is a separate, Amo-gated step. Until then it is the canonical
checklist + the place new pillars are added.

Pillars (all required):
  - robust_edge .............. gate-v2 PASS AND survives the family BH-FDR AND
                               sample-adequate (from family_fdr.run()).
  - per_window_adequate ...... median OOS window >= MIN_OOS_TRADES_PER_WINDOW.
  - sensitivity_robust ....... parameter sweep verdict is ROBUST or ACCEPTABLE
                               (FRAGILE blocks) -- from sweep_param_sensitivity.
  - leakage_clean ............ no look-ahead in signal/fill timing (Task 3).
  - cost_robust .............. edge survives realistic+ transaction costs (Task 3).
  - live_system_stable ....... engine healthy: port up, TV+LLM healthy (Task 4).
  - ensemble_not_subneutral .. live agent-ensemble Brier < 0.25 (hard block).
  - paper_shadow_passed ...... forward paper-vs-backtest dry-run agreed (see
                               run_paper_shadow_dryrun docstring).
"""

from __future__ import annotations

from typing import Any

# Neutral baseline Brier score = always predict p=0.5 on a binary outcome:
# 0.5^2 = 0.25. A live ensemble must BEAT this to authorize trades; >= 0.25 means
# it is no better than (or worse than) a coin and is a hard block.
ENSEMBLE_BRIER_CEILING = 0.25

#: Sensitivity verdicts that clear the robustness pillar (FRAGILE does not).
_SENSITIVITY_OK = {"ROBUST", "ACCEPTABLE"}

#: The boolean pillars that must each be True (default-deny on missing).
_BOOL_PILLARS = (
    "robust_edge",
    "per_window_adequate",
    "leakage_clean",
    "cost_robust",
    "live_system_stable",
    "paper_shadow_passed",
)


def evaluate_promotion(evidence: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a candidate's evidence against the enforced DoD.

    Returns ``{strategy_id, promote, blocks, criteria}`` where ``promote`` is True
    only if every pillar passes, ``blocks`` lists the failing pillar names, and
    ``criteria`` maps each pillar to its pass/fail bool. Default-deny: any pillar
    that is absent, None, or False blocks.
    """
    criteria: dict[str, bool] = {}

    for pillar in _BOOL_PILLARS:
        criteria[pillar] = evidence.get(pillar) is True

    # Sensitivity: ROBUST/ACCEPTABLE pass, FRAGILE/missing block.
    criteria["sensitivity_robust"] = evidence.get("sensitivity_verdict") in _SENSITIVITY_OK

    # Ensemble: must be a known Brier strictly below the neutral ceiling.
    brier = evidence.get("ensemble_brier")
    criteria["ensemble_not_subneutral"] = (
        isinstance(brier, (int, float)) and brier < ENSEMBLE_BRIER_CEILING
    )

    blocks = [name for name, ok in criteria.items() if not ok]
    return {
        "strategy_id": evidence.get("strategy_id", "<unknown>"),
        "promote": not blocks,
        "blocks": blocks,
        "criteria": criteria,
    }


def singlefinder_current_evidence() -> dict[str, Any]:
    """The real candidate's evidence as of 2026-06-23 (Tasks 1-3, live ensemble).

    Survives sensitivity (ROBUST), leakage (clean), and cost (robust), and is
    per-window adequate — but is NOT a robust_edge (family BH-FDR not crossed;
    needs more independent windows, Task 9), the forward paper-shadow dry-run has
    not run, and the live agent ensemble is sub-neutral (Brier ~0.39-0.45). So the
    gate correctly BLOCKS. This is a snapshot for reporting, not a live read.
    """
    return {
        "strategy_id": "MGC_singlefinder_fill_rank1",
        "robust_edge": False,  # p_binom 0.23 -- BH-FDR not crossed (Task 1/9)
        "per_window_adequate": True,  # median 60 trades/window (Task 5)
        "sensitivity_verdict": "ROBUST",  # min_single_ticks 97.6/100 (Task 2)
        "leakage_clean": True,  # prior-session zones + next-bar fill (Task 3)
        "cost_robust": True,  # PF>1.2 to 5 ticks slippage (Task 3)
        "live_system_stable": False,  # engine on Gemini fallback / unverified (Task 4)
        "ensemble_brier": 0.42,  # live ensemble worse-than-random
        "paper_shadow_passed": False,  # forward dry-run not yet run (Task 10c)
    }


def run_paper_shadow_dryrun(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Forward paper-vs-backtest dry-run — DARK until a candidate clears the gate.

    Intended contract (built when a robust candidate exists to monitor — folds in
    roadmap P2.2 live-vs-OOS divergence): run the cleared strategy against LIVE
    market data for a defined forward window, compare realized PF / win-rate /
    drawdown to the backtest OOS expectation, and return
    ``{passed: bool, observed: {...}, expected: {...}, divergence: {...}}``.
    `passed` requires the forward window to stay within tolerance of the backtest
    distribution (no regime-break, no silent decay). Today no candidate has
    cleared `robust_edge`, so this is intentionally not implemented.
    """
    raise NotImplementedError(
        "paper-shadow dry-run is built only once a candidate clears robust_edge; "
        "no candidate qualifies yet (see singlefinder_current_evidence)."
    )


# Walk-forward re-fit cadence + staleness policy (Task 10d) -- declared as data so
# the eventual scheduler/monitor can enforce it without re-deriving the rules.
REVALIDATION_POLICY = {
    "wfo_refit_cadence_days": 90,  # re-run the full WFO at least quarterly
    "max_verdict_age_days": 120,  # a verdict older than this is STALE -> NO_TRADE
    "min_new_oos_trades_before_refit": 60,  # or refit once this many new live trades accrue
    "halt_on_live_vs_oos_divergence": True,  # paper-shadow divergence beyond tolerance -> halt
    "kill_switch": {
        "max_drawdown_pct": 5.0,  # Backtester/live -5% account DD kill switch
        "daily_loss_limit_enforced": True,
        "deactivation": "AMO_ONLY",  # kill-switch deactivation is never JARVIS's call
    },
}


def format_promotion_report(result: dict[str, Any]) -> str:
    """Human-readable promotion verdict."""
    sid = result["strategy_id"]
    head = "PROMOTE" if result["promote"] else "BLOCKED"
    lines = [f"=== LIVE-CAPITAL PROMOTION GATE: {head} — {sid} ==="]
    for name, ok in result["criteria"].items():
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if result["blocks"]:
        lines.append(f"  -> blocked by: {', '.join(result['blocks'])}")
    return "\n".join(lines)


if __name__ == "__main__":
    res = evaluate_promotion(singlefinder_current_evidence())
    print(format_promotion_report(res))
