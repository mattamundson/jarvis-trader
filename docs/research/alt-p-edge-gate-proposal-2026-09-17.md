# Proposal: enforce the documented `p_edge` bar on the gate-v2 ALT path

Date: 2026-09-17
Author: unattended strategy-validation loop (`Jarvis-Strategy-Validation-Loop`)
Status: **PROPOSAL — needs Amo's decision. Not wired, not merged by the loop.**
Related: PR #862 (tz fix), PR #863 (economics + family hardening)

## The gap

`engine/CLAUDE.md` documents the promotion criterion as:

> Flip-to-active criteria … 1. `p_positive_edge >= 0.6` on a fresh rolling walk-forward
> run (ALT path)

No runner enforces it. The ALT conjunction inlined across the research runners is:

```
dsr >= GATE_DSR_ALT(0.30)
and wfo_consistency in {MODERATE, STRONG}
and fixed_params_min_pf >= 1.20
and cost_passes
and mc_95th_dd <= GATE_MC_DD_ALT(0.04)
```

`p_edge` appears only in the CORE conjunction (`>= GATE_P_EDGE = 0.95`). So a verdict
can print **"PASS via alt"** while `p_edge` sits below the documented activation bar.

Observed on 2026-09-17: `MES_trend_vix_pctile_rank1` reported PASS via alt at
`p_edge = 0.5926` — and 29 of its 32 "profitable" windows were single-trade windows
(PF = `inf`), so the multi-trade subset was 3/25 = **0.12** (see
`docs/research/mes-vix-pctile-champion-economics.md` §4).

## Proposed change

Add `GATE_P_EDGE_ALT = 0.60` (done in this PR, **unwired**) and add
`and p_edge >= GATE_P_EDGE_ALT` to every inline ALT conjunction.

## Impact analysis (measured, not estimated)

Scanned every verdict JSON on disk — canonical `engine/data/gate_v2_verdicts/`, its
`archive/`, and the 2026-09-17 worktree (80 verdict JSONs):

| quantity | count |
|---|---|
| verdict JSONs scanned | 80 |
| ALT-path PASS verdicts | 9 |
| **would flip to FAIL under `p_edge >= 0.60`** | **1** |
| ALT PASS with no recorded `p_edge` | 1 (`archive/MES_trend_rank7.json`) |

The single flip is `MES_trend_vix_pctile_rank1.json` (`p_edge = 0.5926`) — the verdict
produced on 2026-09-17, already independently judged **not promotion evidence**. The next
closest recorded ALT passes are `0.625` (three archived MGC RV-filter verdicts) and
`0.6842`, comfortably clear of the bar.

So the change is **behaviourally inert for 8 of 9 recorded ALT passes** and moves the gate
in the fail-closed direction. It would not have retroactively invalidated any strategy that
is currently treated as validated.

## What the loop did NOT do, and why

The conjunction is inlined in **62 consumer modules**, so wiring it is a repo-wide change
to how every future verdict is classified. The loop wrote the constant, the doc-consistency
test, and this analysis, then stopped. A 62-file behavioural gate change is exactly the
kind of edit that should carry a human decision, and doing it unattended would have put the
`grep`-visible artifact ahead of the review it needs.

## Decision requested

1. **Wire it** — apply `and p_edge >= GATE_P_EDGE_ALT` to all 62 consumers in one reviewed
   PR (the doc-consistency test already fails on a partial wiring, so it cannot be done
   half-way). Expected effect: 1 recorded verdict reclassifies; future weak-distribution
   candidates can no longer print "PASS via alt".
2. **Reject it** — keep the ALT path as-is and instead relax the documented criterion in
   `engine/CLAUDE.md` to match the code, so docs and behaviour agree. The doc-consistency
   test enforces that the two stay in sync either way.
3. **Third option worth considering:** fix the `p_edge` *definition* first. Counting
   single-trade windows (PF = `inf`) as "profitable" is what put this candidate at 0.5926
   instead of 0.12. A denominator/window-quality rule may matter more than the threshold.

## Verification in this PR

- `pytest tests/test_gate_p_edge_alt_doc_consistency.py` → 3 passed (constant agrees with
  the documented criterion; ALT bar is laxer than CORE; no partial wiring exists).
- `ruff check` on the changed files → All checks passed.
- Impact analysis above is a read-only scan of on-disk verdict JSONs; script inline in the
  PR body.
