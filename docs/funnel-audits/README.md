# Funnel audits

Analysis outputs from the jarvis-robust-strategy-funnel skill. Each file is a
point-in-time forensic report; treat them as evidence, not policy.

## Contents

- **gate_v2_audit_mgc_evidence.md** — Deep dive on every MGC gate_v2 verdict.
  Documents the rank3 false-negative case (identical champion params to rank4
  which PASSED, but rank3 killed by fixed_params_min_pf penalty for wider
  parameter grid). Baseline evidence for why the new funnel_gate deviates
  from gate_v2 on this specific pattern.

- **gate_comparison_findings.md** — Expanded N=38 comparison of gate_v2 vs
  funnel_gate rejection rates with bootstrap CIs. Honest caveats: half the
  funnel's gates are running on proxied data because native per-regime DSR
  / perm-test / slippage-stress metrics don't exist in historical verdicts.
  Recommends completing a real Phase 3 run before committing to full inventory.

- **gate_comparison_v1.xlsx** — Four-sheet audit spreadsheet accompanying the
  findings doc (Summary, Family Breakdown, All Comparisons, Methodology).

- **strategy_c_audit.md** — Critical audit of the "Strategy C" dashboard
  numbers (Sharpe 2.13, 84.6% OOS retention). Concludes Sharpe is likely
  ~1.5-1.7 after de-biasing for daily-vs-weekly annualization, sibling
  selection bias, and 2017-2021 regime tailwinds. Would fail funnel gates
  1, 2, 3 due to unknown N-of-trials and no trade-level data.

## Regeneration

These docs were produced from repo verdict artifacts (engine/data/gate_v2_verdicts/,
engine/scripts/validation_reports/, engine/data/mgc_wfo_journal.csv). See each
file's methodology section for the exact source paths and dedup logic.
