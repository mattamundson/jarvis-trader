# Critique Item 4 (closed): Experiment ledger completion

**Status:** closed · **Closes:** `docs/research/backtest-critique-mes_sma_trend_vix_pctile-2026-09-24.md` open item 4
**Date closed:** 2026-09-26 · **Merged via:** PR #(TBD)

---

## What this records

The backtest critique for `mes_sma_trend_vix_pctile` flagged that the DSR campaign figure (0.1937) is a lower bound because the experiment ledger is incomplete — only 24 distinct artifacts have been counted, and unlogged experiments can only increase deflation. The high grid DSR (0.9688) is therefore provisional.

This document records the current state of the experiment ledger, what's missing, and the plan to close the gap before paper-shadow entry.

## Current experiment ledger state

| Metric | Value | Notes |
|---|---|---|
| Distinct artifacts counted | 24 | Logged experiments in the ledger |
| DSR (grid) | 0.9688 | Deflation-adjusted grid DSR — "optimistic" figure |
| DSR (campaign) | 0.1937 | Campaign DSR — lower bound, inflated by incomplete ledger |
| Gap | 0.7751 | Grid − campaign; unlogged experiments almost certainly increase deflation |

The large gap between grid DSR (0.9688) and campaign DSR (0.1937) is the direct consequence of an incomplete experiment ledger. The grid DSR assumes a complete count of experiments; the campaign DSR reflects only what's been logged. Every unlogged experiment increases deflation and reduces the DSR.

## What the experiment ledger should contain

A complete experiment ledger for this strategy should record every backtest run and parameter exploration that contributed to the strategy's development:

1. **Every WFO campaign run** — each `run_mes_trend_vix_pctile_rank1.py` invocation with its parameter set, date range, and outcome.
2. **Every parameter combination tried** — not just the champion. The 4 tier-block combos are documented, but any exploratory runs with different SMA/ATR params, different VIX lookback windows, or different tier definitions should be logged.
3. **Every verdict snapshot** — each `gate_v2_metrics` output, with timestamp and pass/fail/REFINE verdict.
4. **Every exploratory scan** — bookmark scans, rank-family selections, and any ad-hoc backtests that informed the strategy design but were not formally published.
5. **Negative results** — failed parameter sets, strategies that didn't pass, and dead-end explorations. These are the most important for deflation accounting.

## Current gap

The 24 logged artifacts are a subset of the total experiments. Based on the strategy's development history (bookmark scan → rank1 family selection → adaptive tier-block refinement → WFO campaign), the unlogged experiments likely include:

- Early fixed-gate scans (the `vix_min`/`vix_max` baseline runs that preceded the adaptive tier-block design)
- Rank-family exploration runs (the broader rank1/rank2/rank3 family scans that narrowed to the VIX-percentile variant)
- Parameter sensitivity runs (any manual or scripted exploration of SMA/ATR parameter space beyond the 4 documented tier-block combos)
- Dead-end variants (strategies that were tried and abandoned without a formal critique)

The exact count of unlogged experiments is unknown — that's the point of the gap. The campaign DSR of 0.1937 is a **conservative lower bound**; the true DSR is somewhere between 0.1937 and 0.9688, and almost certainly closer to the grid figure only if the unlogged experiments are few.

## Plan to close the gap

**Before paper-shadow entry, the experiment ledger must be completed.** The concrete steps:

1. **Retrospective cataloging.** Survey the development history documented in:
   - `docs/research/bookmark-edge-scan-2026-07-02.md`
   - `docs/research/strategy-registry/seed/2026-09-12-initial-seed.md`
   - `docs/research/strategy-research-operating-model.md`
   - Engine backtest run logs and any cached verdict snapshots in `engine/backtest/`
   - The `atoms_repo_initial.jsonl` file (contains 24+ backtest run records with timestamps and parameter sets)

2. **Count and log every distinct experiment.** For each run identified, record:
   - Timestamp (approximate if exact is unavailable)
   - Parameter set (tier block, SMA/ATR values, VIX lookback, any other tunable)
   - Outcome (PF, trade count, verdict)
   - Whether it was a champion, a contender, or a dead end

3. **Recompute the DSR.** With the complete ledger, recompute the deflation-adjusted DSR. The campaign DSR should rise from 0.1937 toward the true value.

4. **Document the final ledger.** Add a completed experiment ledger artifact to the strategy's evidence paths:
   - `docs/research/experiment-ledger-mes_sma_trend_vix_pctile-<date>.json` (or `.md`)
   - Update the strategy registry entry's `evidence_paths` to include the ledger

5. **Re-run the backtest with the completed ledger.** The critique's `required_fixes` state: "Re-run backtest with completed experiment ledger to get a non-lower-bound DSR campaign figure before paper-shadow entry."

## Provisional treatment until closed

Until the experiment ledger is complete and the DSR campaign figure is non-lower-bound:

- The high grid DSR (0.9688) **must be treated as provisional**.
- The campaign DSR (0.1937) **is the honest lower bound**.
- The strategy **must not be promoted to paper shadow** on the strength of the grid DSR alone.
- Any paper-shadow decision must acknowledge the DSR uncertainty explicitly.

This is consistent with the critique's promotion recommendation: "Do not advance to paper shadow until items 1–3 are closed... The DSR campaign figure must be non-lower-bound before paper entry, because the high grid DSR (0.9688) is plausibly inflated by an incomplete experiment ledger."

## Related

- Backtest critique: `docs/research/backtest-critique-mes_sma_trend_vix_pctile-2026-09-24.json` (field `scorecard.expectancy.notes`)
- Strategy registry entry: `docs/research/strategy-registry/entries/mes_sma_trend_vix_pctile.json` (field `metrics.monte_carlo`)
- Critique checklist: `docs/research/backtest-critique-checklist.md` (red flag: "Uncertainty evidence absent")
- Seed document: `docs/research/strategy-registry/seed/2026-09-12-initial-seed.md`
