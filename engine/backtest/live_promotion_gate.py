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

import os
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


#: Strategies cleared for live capital. INTENTIONALLY EMPTY (default-deny): a
#: strategy enters this set only when a human/verified process confirms it passed
#: ``evaluate_promotion`` — promotion is never an automatic data-driven act. As of
#: 2026-06-24 NO strategy qualifies (the one real candidate, singlefinder, is
#: BLOCKED — see ``singlefinder_current_evidence``). Populating this is the final
#: Amo-gated step of live promotion, paired with flipping PROMOTION_GATE_ENFORCE.
PROMOTED_STRATEGIES: frozenset[str] = frozenset()


def is_strategy_promoted(strategy_id: str | None) -> bool:
    """True only if ``strategy_id`` is an explicitly promoted strategy.

    Looks up ``PROMOTED_STRATEGIES`` at call time (so it honors monkeypatching /
    runtime population). A falsy/None id is never promoted.
    """
    return bool(strategy_id) and strategy_id in PROMOTED_STRATEGIES


def promotion_gate_enforced() -> bool:
    """Whether the pre-trade promotion block is ENFORCED (vs shadow-recorded).

    Shadow-default OFF (env unset → ``False``): the live order path records that an
    un-promoted strategy *would* be blocked but does not block. Setting
    ``PROMOTION_GATE_ENFORCE`` to a truthy value turns the block hard. House
    convention, mirrors ``GATE_V2_ENFORCE_*``. This flip is Amo Tier-3.
    """
    return os.getenv("PROMOTION_GATE_ENFORCE", "0").strip().lower() in {"1", "true", "yes", "on"}


def oos_cap_enforced() -> bool:
    """Whether the OOS-contamination cap BLOCKS promotion (vs shadow-recorded).

    Shadow-default OFF (env unset → ``False``), mirroring ``promotion_gate_enforced``.
    When off, the ``oos_budget_ok`` pillar is always satisfied (dormant): the per-quarter
    OOS-access cap stays a tracked ledger only (``analytics.oos_access_ledger``). Setting
    ``OOS_CAP_ENFORCE`` truthy makes an exhausted quarterly OOS budget a hard promotion
    block. House convention, mirrors ``PROMOTION_GATE_ENFORCE``; this flip is Amo Tier-3
    and should wait until the per-quarter access budget is calibrated.
    """
    return os.getenv("OOS_CAP_ENFORCE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _oos_budget_ok() -> bool:
    """Read-only OOS-budget pillar for :func:`evaluate_promotion`.

    Dormant (always True) when :func:`oos_cap_enforced` is off. When enforced, returns
    ``True`` only if this quarter's OOS-access budget is not exhausted. Never records —
    reads the ledger only. Fail-closed when enforced but the ledger is unreadable
    (default-deny, matching the module's fail-safe philosophy).
    """
    if not oos_cap_enforced():
        return True
    try:
        from analytics.oos_access_ledger import budget_status  # noqa: PLC0415

        return not budget_status().exceeded
    except Exception:
        return False  # enforced but unverifiable → block (fail-safe)


#: Strategy-class tag whose gate verdict may route through the beta-harvest variant.
BETA_HARVEST_TAG = "beta_harvest"


def beta_harvest_gate_enforced() -> bool:
    """Whether the APPROVED beta-harvest gate variant is active for tagged strategies.

    Shadow-default OFF (env unset → ``False``), mirroring ``promotion_gate_enforced``.
    The variant was APPROVED by Amo on 2026-06-25 (T10 — see
    ``engine/docs/BETA_HARVEST_GATE_PROPOSAL.md``); flipping ``BETA_HARVEST_GATE_ENFORCE``
    truthy is the pre-authorized runtime activation. Even when active it only changes
    the gate VERDICT for a strategy tagged ``beta_harvest`` — it promotes nothing
    (``evaluate_promotion`` still requires robust_edge + paper_shadow + live_system_stable,
    which turn-of-month does not yet satisfy).
    """
    return os.getenv("BETA_HARVEST_GATE_ENFORCE", "0").strip().lower() in {"1", "true", "yes", "on"}


def resolve_gate_verdict(r: Any, *, strategy_class: str = "", **kwargs: Any) -> dict[str, Any]:
    """Single activation point (Tier-3, T9): route a strategy's gate-v2 verdict.

    A strategy tagged ``strategy_class="beta_harvest"`` gets the approved beta-harvest
    variant (``gate_v2_beta_harvest_verdict``: the p_edge core floor 0.95 → 0.60 plus a
    chronological H1/H2 stationarity test) when ``beta_harvest_gate_enforced()``. Every
    other strategy — and the tagged strategy while the flag is off — gets the canonical
    ``gate_v2_verdict`` UNCHANGED. This routes the VERDICT only; it never promotes (see
    ``beta_harvest_gate_enforced``). The variant can only ever de-authorize less, never
    more: it rescues a canonical FAIL solely when the lone failing core criterion is
    p_edge (the mechanism enforces that).
    """
    from backtest.session_anomaly_backtest import (
        gate_v2_beta_harvest_verdict,
        gate_v2_verdict,
    )

    if strategy_class == BETA_HARVEST_TAG and beta_harvest_gate_enforced():
        return gate_v2_beta_harvest_verdict(r, **kwargs)
    return gate_v2_verdict(r, **kwargs)


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

    # Ensemble pillar — depends on decision_mode (Tier-3 systematic-strategy path):
    #   "ensemble" (default): an LLM-ensemble-driven strategy must beat the neutral
    #       Brier ceiling (unchanged behavior).
    #   "systematic": a deterministic rule (e.g. turn-of-month) has no agent ensemble,
    #       so the pillar is N/A. It is replaced by the out-of-sample backtest power
    #       (robust_edge + per_window_adequate), which are already required pillars
    #       above — so this can only ever de-authorize less, never more.
    decision_mode = evidence.get("decision_mode", "ensemble")
    if decision_mode == "systematic":
        criteria["ensemble_not_subneutral"] = True  # N/A for a non-LLM systematic rule
    else:
        brier = evidence.get("ensemble_brier")
        criteria["ensemble_not_subneutral"] = (
            isinstance(brier, (int, float)) and brier < ENSEMBLE_BRIER_CEILING
        )

    # OOS-contamination cap (research integrity). Dormant unless OOS_CAP_ENFORCE is on
    # — default True so promotion behavior is unchanged until the cap is calibrated.
    criteria["oos_budget_ok"] = _oos_budget_ok()

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


def turn_of_month_current_evidence() -> dict[str, Any]:
    """Turn-of-month candidate evidence as of 2026-06-24 (SPY 33yr + MES transfer).

    The first stationary, cost-surviving, multi-regime anomaly found this arc. On
    SPY 1993-2026 it is positive in every 5yr era (incl. 2008/2020) and stationary
    (H1 PF 1.23 / H2 PF 1.20). Beta-sized to a 5% DD budget it clears pf_ci_lower
    (1.17), DSR (1.0), and mc_95th_dd (4.57% <= 5%) — it fails the CORE gate ONLY on
    p_edge (0.62 < 0.95), which over annual windows is structurally unmeetable for a
    long-beta harvest (no long-only strategy is positive in 95% of years). See the
    beta-harvest gate proposal; robust_edge stays False pending that Tier-3 decision
    and the family BH-FDR.

    TOM is a SYSTEMATIC strategy — it does NOT route through the LLM agent ensemble,
    so it sets ``decision_mode="systematic"`` and the ``ensemble_not_subneutral``
    pillar is N/A (substituted by the OOS backtest-power pillars). TOM is STILL
    correctly BLOCKED — on ``robust_edge``, the forward paper-shadow, and live-system
    stability — so the systematic path does not promote it; it only removes a pillar
    that never applied.

    NOTE on ``robust_edge`` (pre-registered-hypothesis caveat, 2026-06-24): the family
    BH-FDR behind ``robust_edge`` exists to penalize the discovery factory's ~38 SWEPT
    candidates for multiple testing (family_fdr.py). TOM is a single PRE-REGISTERED
    hypothesis — it was never a member of that family, so crossing the family FDR is the
    wrong bar for it (it would be penalized for OTHER candidates' data-mining). TOM's
    honest validity rests instead on (a) the forward paper-shadow holding out-of-sample
    and (b) cross-index robustness. The cross-index check ran (TOM_CROSS_INDEX_RESULTS.md)
    and came back PARTIAL — corroborated in SPY/QQQ/MDY (large/tech/mid) but NOT across the
    full complex (3/6; small-cap + intl lose stationarity). So ``robust_edge`` stays False
    as the conservative state, and the forward shadow is the decisive arbiter — NOT a
    family-FDR pass it was never eligible for.
    """
    return {
        "strategy_id": "MES_turn_of_month",
        "decision_mode": "systematic",  # deterministic calendar rule, no LLM ensemble
        "robust_edge": False,  # gate-v2 fails on the mis-calibrated p_edge; BH-FDR not run
        "per_window_adequate": True,  # ~48 trades/yr over decades of windows
        "sensitivity_verdict": "ROBUST",  # parameter-free; stationary across 33yr/all regimes
        "leakage_clean": True,  # close-to-close, TOM dates known ex-ante, no look-ahead
        "cost_robust": True,  # net@2bps Sharpe 0.79; low turnover ~48 trades/yr
        "live_system_stable": False,  # engine on Gemini fallback / unverified
        # ensemble_brier omitted: systematic decision_mode makes the pillar N/A
        "paper_shadow_passed": False,  # forward dry-run not yet run
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
