# Proposal: a beta-harvest gate variant + a systematic-strategy promotion path

**Date:** 2026-06-24 · **Status:** MECHANISM BUILT (default-off) — Tier-3 ACTIVATION awaiting Amo.
JARVIS does not flip gate policy. Evidence: `SESSION_ANOMALY_FINDINGS.md` (SPY 33yr) +
`session_anomaly_backtest.validate_tom`.

## Implementation status (2026-06-24)

Both mechanisms are now CODE — additive, default-off, reversible, TDD'd (53 tests green, ruff
clean). Nothing trades and no existing verdict changes until Amo performs the single activation
flip described under each. Verified end-to-end on real SPY 33yr data:
`gate_v2_beta_harvest_verdict(beta_sized_TOM)` → **PASS (reclassified)**, because the canonical
`compute_gate_v2` core FAILs on EXACTLY one criterion (p_edge 0.618), TOM clears the lower floor
(0.618 ≥ 0.60) and is stationary (H1/H2 PF > 1).

- **Problem 1 (beta-harvest variant):** `session_anomaly_backtest.gate_v2_beta_harvest_verdict()`
  — a WRAPPER that never modifies `compute_gate_v2`; it reclassifies a canonical FAIL to PASS only
  when the sole failing core criterion is p_edge AND p_edge ≥ `BETA_HARVEST_P_EDGE_MIN` (0.60) AND
  the series is stationary. `grade_returns(..., beta_harvest=True)` lowers the module-gate p_edge
  floor identically. **Amo activation:** route a `beta_harvest`-tagged strategy's promotion read
  through `gate_v2_beta_harvest_verdict` (no flag exists yet — wiring it is the explicit Tier-3 step).
- **Problem 2 (systematic promotion path):** `live_promotion_gate.evaluate_promotion()` honors a
  new `decision_mode` field (default `"ensemble"`, unchanged). `"systematic"` makes the
  `ensemble_not_subneutral` pillar N/A (substituted by the already-required robust_edge +
  per_window_adequate). `turn_of_month_current_evidence()` now sets `decision_mode="systematic"`,
  so TOM no longer blocks on the ensemble pillar — but is STILL correctly BLOCKED on robust_edge,
  paper_shadow_passed, and live_system_stable. **Amo activation:** none needed for the mechanism;
  promotion still requires populating `PROMOTED_STRATEGIES` + `PROMOTION_GATE_ENFORCE` (Tier-3).

## The trigger

Turn-of-month is the first stationary, cost-surviving, multi-regime edge found this arc (SPY
1993-2026: Sharpe 1.07 gross / 0.79 net, positive in every 5yr era incl. 2008/2020, H1 PF 1.23 /
H2 PF 1.20). Beta-sized to a 5% DD budget and run through the **canonical `compute_gate_v2`**:

```
gate_net_sized: FAIL (via None)  pf_ci=1.172  p_edge=0.618  mc95_dd=0.0457  dsr=1.000  wfo=MODERATE
```

It clears **pf_ci_lower (1.172 ≥ 1.10)**, **DSR (1.000 ≥ 0.10)**, and **mc_95th_dd (4.57% ≤ 5%)**
after beta-sizing. It fails the core path on a **single criterion: `p_edge ≥ 0.95`** (0.618), and
the ALT path on `fixed_params_min_pf ≥ 1.20` (1.15) and `mc_95th_dd ≤ 4%` (4.57%).

## Problem 1 — `p_edge ≥ 0.95` is mis-calibrated for a low-frequency long-beta harvest

`p_edge` = fraction of OOS windows with PF > 1. The 0.95 bar was tuned for **hedged intraday-trend
WFO**, where each window aggregates many trades, so a genuine edge wins ~95% of windows. For a
**long-beta harvest** evaluated on annual windows, requiring 95% of *years* to be profitable is
requiring the strategy to **never have a down year** — which no long-only equity strategy does
(SPY itself is positive in ~70% of years). A coin with a real 60/40 edge wins ~60% of periods,
not 95%. So `p_edge ≥ 0.95` over coarse windows does not measure "is there an edge"; it measures
"is the edge nearly deterministic," which excludes every beta harvest by construction.

**Proposed beta-harvest variant** (a *strategy-class* tag, not a global threshold change — it can
only ever de-authorize less, never more, and applies only to strategies explicitly tagged
`beta_harvest`):
- Replace the `p_edge ≥ 0.95` core requirement with the **chronological stationarity guard**
  already used in this module: **both H1 and H2 PF > 1** (the ES-NQ non-stationarity test), which
  TOM passes (1.23 / 1.20), AND `p_edge ≥ 0.60` (clearly better than a coin over windows).
- Keep `pf_ci_lower ≥ 1.10`, `dsr ≥ 0.10`, and `mc_95th_dd ≤ 5%` unchanged (TOM clears all three).
- Rationale: a beta harvest's risk is drawdown, not win-rate; the DD ceiling + bootstrap PF CI +
  deflated Sharpe + cross-half stationarity are the right bar. This is reversible and tagged.

Under this variant, beta-sized TOM would PASS. **This is a gate-policy decision for Amo**, not one
JARVIS makes; the proposal is to review and either approve the tagged variant or keep TOM blocked.

## Problem 2 — the promotion gate has no path for a SYSTEMATIC strategy

`live_promotion_gate.evaluate_promotion` has an `ensemble_not_subneutral` pillar (live agent
ensemble Brier < 0.25). That assumes an **LLM-ensemble-driven** decision. TOM is **systematic** —
deterministic calendar rule, no agent ensemble — so the pillar does not apply. As wired, the
omitted pillar default-denies (correct fail-safe), so `turn_of_month_current_evidence()` is BLOCKED.

**Proposed**: add a `decision_mode: "systematic" | "ensemble"` field to promotion evidence. For
`systematic`, the ensemble pillar is N/A and is replaced by the **out-of-sample backtest power**
already required elsewhere (robust_edge + per-window adequacy). For `ensemble`, behavior is
unchanged. Again Tier-3, reversible, additive.

## What stays blocked regardless (correctly)

Even with both variants approved, TOM remains BLOCKED on:
- **`paper_shadow_passed`** — the forward paper-vs-backtest dry-run has not run. This is the next
  build once a candidate is worth monitoring (TOM now is); it would be the first real exercise of
  the promotion-gate rails.
- **`live_system_stable`** — engine on the Gemini fallback / unverified (Anthropic credit).

## Recommendation

1. Review the **beta-harvest gate variant** (Problem 1) — approving it makes beta-sized TOM the
   first gate-PASS candidate of the arc; declining keeps it blocked on a threshold I've argued is
   structurally wrong for this strategy class. Either is a legitimate Tier-3 call.
2. Review the **systematic-strategy promotion path** (Problem 2).
3. Independent of both: authorize building the **forward paper-shadow dry-run** for TOM — it's the
   honest next gate even if the variants are declined, and it's non-destructive (observe-only).
