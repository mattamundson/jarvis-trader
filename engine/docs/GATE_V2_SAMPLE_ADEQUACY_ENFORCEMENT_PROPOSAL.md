# Proposal: enforce gate-v2 sample adequacy (Tier-3 decision for Amo)

**Date:** 2026-06-23 · **Status:** PROPOSAL — awaiting Amo's Tier-3 decision (JARVIS does not flip
gate policy). Edge-validation top-10, Task 8. Evidence: Task 5 (`5868da5`), Task 1 audit.

## TL;DR

Two related tightenings, in order of safety:

1. **Immediate, zero-risk (Amo `.env` flip):** set `GATE_V2_ENFORCE_SAMPLE_ADEQUACY=1`. This
   enforces the **aggregate** 30-OOS-trade floor at the authorization layer. **Impact: exactly one
   strategy is de-authorized** — `MGC_trend_rv_filter_rank1` (26 trades, a known small-sample
   mirage). Nothing real is touched; the one genuine candidate (singlefinder, 381 trades) is
   unaffected. Fully reversible.
2. **Follow-on (code change, recommended):** add per-window-adequacy enforcement at the
   authorization layer. The aggregate flag does NOT catch `trend_rank4` / `trend_adx_filter_rank1`
   — both clear 30 aggregate trades yet are per-window-degenerate and remain gate-PASS on
   **tradeable MGC**. JARVIS can build this in shadow mode (no authorization change until Amo
   flips a second flag) on request.

## Part 1 — flip `GATE_V2_ENFORCE_SAMPLE_ADEQUACY=1`

Currently shadow mode (default `0`): runners record `total_oos_trades` / `sample_adequate` into
verdicts but the verdict itself is unchanged, so authorization is unaffected
(`_gate_v2_helpers.sample_adequacy_enforced()`). Setting the flag makes any strategy with
`< MIN_OOS_TRADES_TOTAL (30)` total OOS trades return `INSUFFICIENT_SAMPLE` → de-authorized
(gate_v2_policy default-deny).

**Full impact set** (all sequential verdicts with <30 total OOS trades; CPCV excluded):

| verdict file | current verdict | total OOS trades | effect of flip |
|---|---|---|---|
| **MGC_trend_rv_filter_rank1** | **PASS (core)** | **26** | **→ INSUFFICIENT_SAMPLE (de-authorized)** |
| MES_trend_rank11 | INSUFFICIENT_SAMPLE | 17 | none (already) |
| MES_trend_rv_filter_rank2 | INSUFFICIENT_SAMPLE | 16 | none |
| MGC_gapfinder_fill_rank1 | INSUFFICIENT_SAMPLE | 16 | none |
| MES_gapfinder_fill_rank1 | INSUFFICIENT_SAMPLE | 0 | none |
| M6B/M6E/ZN/ZB_trend_diversifier | INSUFFICIENT_SAMPLE | 6/6/20/23 | none |
| M2K/MCL_trend_adx_filter_rank1 | FAIL | 25/14 | none |
| MES_trend_adx_rv_filter_rank1 | FAIL | 6 | none |
| MES_trend_vix_rank1/2/3 | FAIL | 16/15/22 | none |

**Exactly one currently-authorizing (PASS) verdict flips: `MGC_trend_rv_filter_rank1`.** It is the
26-trade mirage — Task 1 showed 5 of its 7 windows are thin (2–4 trades) with PF inflated by
degenerate windows. De-authorizing it is correct.

**Safety:** the flip can only tighten (de-authorize), never authorize anything new. The one real
edge-validation candidate, `MGC_singlefinder_fill_rank1` (381 OOS trades), is far above the floor —
unaffected. Reversible via a one-line `.env` change.

**The change (Amo runs):**
```
# engine/.env
GATE_V2_ENFORCE_SAMPLE_ADEQUACY=1
```
Then re-evaluate verdicts (or restart the engine if it caches authorization). Verify
`MGC_trend_rv_filter_rank1` now reports `INSUFFICIENT_SAMPLE` and singlefinder is unchanged.

## Part 2 — per-window enforcement gap (the reason this isn't sufficient alone)

The aggregate-30 floor is **necessary but not sufficient** (the whole premise of Task 5). Two
gate-PASS strategies clear it on aggregate while being per-window-degenerate:

| strategy | verdict | aggregate OOS | median trades/window | thin windows | symbol tradeable? |
|---|---|---|---|---|---|
| `MGC_trend_rank4` | PASS | 67 | 4 | 14 of 19 | **YES (MGC)** |
| `MGC_trend_adx_filter_rank1` | PASS | 39 | 2 | 18 of 19 | **YES (MGC)** |

These remain **gate-PASS on a tradeable symbol** even with Part 1's flag on. My Task 5 per-window
signal blocks them in the family-FDR *campaign report* (`robust_edge`), but that is a research view
— it does **not** gate live authorization. So there is a latent risk: two per-window-degenerate
strategies could authorize MGC trend trades.

**Follow-on — NOW BUILT (shadow mode, commit `710784a`):** `GATE_V2_ENFORCE_PER_WINDOW` +
`per_window_sample_adequate()` are wired into `study_wfo_runner._compute_gate_v2`. A strategy whose
median window is below `MIN_OOS_TRADES_PER_WINDOW (5)` returns `INSUFFICIENT_SAMPLE` when the flag is
set. Shadow-default OFF (records `median_oos_trades_per_window` / `per_window_adequate` but does not
gate) — zero behavior change to existing verdicts until Amo flips it. 9 tests, ruff clean. Impact
preview if enforced (on re-run): `trend_rank4` / `trend_adx_filter_rank1` → INSUFFICIENT_SAMPLE;
singlefinder (median 60) unaffected.

**The change (Amo runs, after reviewing):**
```
# engine/.env
GATE_V2_ENFORCE_PER_WINDOW=1
```
Note: this gates at verdict-GENERATION time, so it affects strategies on their next WFO re-run; it
does not retroactively rewrite stored verdict JSONs.

## Recommendation

- **Approve Part 1 now** — it is strictly safe and removes one false-PASS mirage from the
  authorization path.
- **Part 2 is now BUILT** (shadow mode, `710784a`) — review the per-window impact set, then flip
  `GATE_V2_ENFORCE_PER_WINDOW=1` to also de-authorize the per-window mirages (`trend_rank4`,
  `trend_adx_filter`). Identical-shape, equally reversible.
