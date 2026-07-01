---
name: jarvis-robust-strategy-funnel
description: "Use when the user wants to inventory, validate, rank, or kill trading strategies from the jarvis-trader repo and/or external sources (X bookmarks, articles, TOS scripts). Runs a 4-phase robust funnel (Inventory → Smoke Test → Robustness → Combinations) using Lopez de Prado methods (Deflated Sharpe, PBO, CPCV, permutation tests) layered on top of jarvis-trader's existing backtest primitives. Targets ES futures by default, moderately aggressive thresholds, produces Tier A/B/C ranking with documented kill reasons and improvement hypotheses. Includes a weekly OneDrive-synced tracker."
license: MIT
metadata:
  author: matt-amundson
  version: '1.0'
  target_repo: jarvis-trader
  default_instrument: ES
  default_timeframes: "5m, 30m, 1h"
---

# Jarvis Robust Strategy Funnel

A meta-orchestration layer over the jarvis-trader engine that turns scattered strategy ideas (repo code + X bookmarks + analysis docs) into a ranked, statistically defensible list of Tier A paper-trade candidates — without burning credits on combinatorial brute force.

## When to Use This Skill

Load this skill when Matt asks to:

- Inventory or audit trading strategies across the jarvis-trader repo + bookmarks
- Run the 4-phase robust strategy funnel (or any individual phase)
- Validate a new strategy idea against Lopez de Prado robustness criteria
- Generate or update the weekly strategy tracker dashboard
- Promote/demote strategies between Tier A (paper trade), Tier B (watch list), Tier C (killed)
- Map an X bookmark or external article to existing repo strategies (deduplicate hypotheses)
- Decide whether a backtest result is real edge or overfit noise

Do NOT load this skill for:
- Live trading execution decisions (use jarvis-trader's engine directly)
- One-off "should I buy X" market commentary
- Building new backtest primitives from scratch (they already exist in `engine/backtest/`)

## Core Principle: Funnel, Don't Brute-Force

The naive "test every strategy × instrument × timeframe × parameter combo" approach produces statistically meaningless results due to multiple-testing bias. See `references/lopez_de_prado_vs_brute_force.md` for the math.

This skill replaces 8M+ naive tests with a **~5,000–15,000 test funnel** that kills bad candidates cheaply and only spends compute on survivors.

```
Phase 1: Inventory & Hypothesis Extraction   →  60 cards → ~30 after dedup/rationale filter
Phase 2: Smoke Test (defaults, 1 timeframe)  →  ~30 → ~15 survivors
Phase 3: Robustness (WFO + PBO + DSR + regime) → ~15 → ~5 Tier A + ~3 Tier B
Phase 4: Combinations (low-corr ensembles only) → final portfolio recommendation
```

## Architecture: Thin Layer on Existing Primitives

This skill is intentionally a **thin orchestration layer**. It does NOT duplicate the heavy lifting already done in `engine/`. It calls:

| Need | Existing primitive | Skill's role |
|---|---|---|
| Bar data | `engine/data/bars_repository.py` | Just call it |
| Backtest engine | `engine/backtest/backtester.py` | Just call it |
| Walk-forward | `engine/backtest/walk_forward.py`, `wfo_primitives.py` | Just call it |
| CPCV | `engine/backtest/cpcv.py` | Just call it |
| Deflated Sharpe | `engine/backtest/deflated_sharpe.py` | Just call it |
| Monte Carlo | `engine/backtest/monte_carlo.py` | Just call it |
| Permutation test | `engine/analytics/permutation_test.py` | Just call it |
| FDR | `engine/backtest/family_fdr.py` | Just call it |
| Regime detection | `engine/analytics/regime_detector.py` | Just call it |
| **Funnel gate decision logic** | (none — owned by this skill) | `scripts/funnel_gate.py` |
| **Strategy card schema** | (none — owned by this skill) | `references/strategy_card_schema.md` |
| **Weekly tracker** | (none — owned by this skill) | `scripts/tracker.py` |

The funnel gate (`funnel_gate.py`) computes the Tier A/B/C decision **independently** from `engine/backtest/gate_v2_policy.py`. When they disagree, the disagreement is flagged for human review — neither is silently trusted.

## Workflow

### Step 0 — Orient

When invoked, first read these three references to load the decision framework into context:
1. `references/thresholds.md` — what makes a strategy Tier A vs B vs C
2. `references/strategy_card_schema.md` — the JSONL data model
3. `references/lopez_de_prado_vs_brute_force.md` — only if the user is questioning methodology

### Step 1 — Determine Phase & Inputs

Ask (or infer from context):
- Which phase: 1 (inventory), 2 (smoke), 3 (robust), 4 (combos), or "tracker" (weekly status)
- Inputs available: repo only? bookmarks too? specific strategy IDs?
- OneDrive bookmark file location, if applicable

### Step 2 — Execute Phase

All execution happens on Matt's local machine. This skill produces code, configs, and analysis — not runtime backtests in the sandbox.

For each phase, the standard pattern is:
1. Generate or update the relevant config / strategy-card JSONL
2. Tell Matt the exact local commands to run (e.g. `python -m jarvis_funnel.run --phase 2 --instrument ES`)
3. Wait for him to commit results to the `funnel-results` branch (or sync via OneDrive)
4. Read results, apply funnel gate logic, produce ranking + analysis docs

### Step 3 — Document Findings

Every phase output includes:
- **Survivors** with metrics
- **Killed** list with documented reasons (the kill reasons are as valuable as survivors — they prevent re-pitching dead ideas)
- **Improvement hypotheses** — for each Tier B strategy, 2–3 specific changes that could move it to Tier A
- **Anomalies / things to investigate** — disagreements between funnel_gate and gate_v2, suspicious metric combinations, etc.

## Phase Details

### Phase 1 — Inventory & Hypothesis Extraction

Run `scripts/phase1_inventory.py` against:
- Local clone of `jarvis-trader` repo (reads `engine/backtest/run_*.py`, `engine/strategies/`, `engine/strategy_lab/`, top-level `*.md` analysis docs, `*.pine` TOS scripts)
- Bookmark export from OneDrive (`bookmarks.html` or `.json`)

Output: `strategies_v1.jsonl` — one card per unique hypothesis with merged provenance.

The script does dedup by `hypothesis_id`: e.g., if `run_mes_orb_rank1.py` and an X bookmark both describe an opening-range breakout, they become a single card with both sources cited.

**Filter applied at end of Phase 1:** any card without a clear `economic_rationale` field is auto-marked `phase_1_status: NEEDS_RATIONALE` and excluded from Phase 2 until a rationale is added. This is the cheapest, most important filter — "RSI < 30 = buy" with no reason why dies here.

### Phase 2 — Smoke Test

For each Phase 1 survivor:
- Single instrument: ES (front month, continuous, from `engine/data/bars_repository.py`)
- Single timeframe: the one the hypothesis's `economic_rationale` supports (5m for intraday, 30m for swing, 1h for overnight/multi-day)
- Author's default parameters (no optimization yet)
- 24 months of data, simple in-sample/out-of-sample 70/30 split
- Realistic costs: $2.50/RT commission, 1 tick slippage assumed

Kill criteria (gate is loose at this stage):
- Sharpe < 0.5 before multiple-testing correction
- Profit factor < 1.1
- Max drawdown > 25% of starting equity
- < 20 total trades over 24 months
- Breaks under 2x slippage stress

Expected output: ~50% survival rate.

### Phase 3 — Robustness (the heavy lift)

For each Phase 2 survivor, run the full Lopez de Prado robustness battery via `engine/backtest/`:

1. **Walk-forward optimization** (`walk_forward.py`) — anchored & rolling, ≥10 OOS windows
2. **CPCV** (`cpcv.py`) — combinatorial purged cross-validation, 6 groups
3. **Deflated Sharpe** (`deflated_sharpe.py`) — corrected for # trials run on this strategy family
4. **PBO** — probability of backtest overfit via `family_fdr.py` + custom calc in `funnel_gate.py`
5. **Monte Carlo bootstrap** (`monte_carlo.py`) — 10,000 resamples for CI on PF, Sharpe, max DD
6. **Bar permutation test** (`bar_permute.py`) — does edge persist when bars shuffled? If yes, edge is fake.
7. **Regime conditioning** (`regime_detector.py` + `vix_percentile_regime.py`) — Sharpe per regime
8. **Multi-timeframe sensitivity** — re-test on 5m/30m/1h only if economic rationale supports it
9. **Slippage stress** — re-run at 2x and 3x assumed slippage
10. **Cross-instrument** — test ES survivors on MES (validation) and MGC/MNQ (generalization signal)

Apply `funnel_gate.py` logic → Tier A / Tier B / Tier C assignment.

### Phase 4 — Combinations

ONLY runs on Phase 3 Tier A survivors (typically 3–7 strategies).

1. Compute return correlation matrix across all Tier A strategies
2. Identify pairs/triples with |corr| < 0.30
3. For each low-corr group, test as:
   - Equal-weight ensemble
   - Vol-target ensemble (risk parity)
   - Vote ensemble (all must agree)
4. Compute incremental Sharpe contribution of each strategy in each combo
5. Recommend final 1–3 portfolios for paper trading

### Tracker Mode — Weekly Status

Run `scripts/tracker.py` (scheduled via cron, Mondays 6am Central):
- Reads `results/` directory from OneDrive sync folder (`OneDrive/jarvis-trader-handoff/results/`)
- Computes week-over-week movement: Tier B→A promotions, Tier A→C demotions, new strategies entering pipeline
- Identifies strategies "near threshold" (within 10% of next tier boundary on ≥2 metrics)
- Flags any anomalies (suspicious metric jumps, gate_v2 vs funnel_gate disagreements, contamination warnings)
- Outputs HTML tearsheet to `OneDrive/jarvis-trader-handoff/tracker/week_YYYY-WW.html`
- Sends in-app notification with summary + link

## Key References

Read these on-demand based on the task:

- `references/lopez_de_prado_vs_brute_force.md` — the methodology argument and math
- `references/thresholds.md` — Tier A/B/C cutoffs with rationale for each number
- `references/strategy_card_schema.md` — JSONL data model for strategy cards
- `references/bookmark_to_code_mapping.md` — how to merge X bookmark ideas with existing repo strategies

## Scripts (run locally by Matt, generated by this skill)

- `scripts/phase1_inventory.py` — repo + bookmark inventory pipeline
- `scripts/funnel_gate.py` — Tier A/B/C decision engine
- `scripts/tracker.py` — weekly status tracker
- `scripts/run_phase.py` — CLI orchestrator (`python -m jarvis_funnel.run --phase N`)

## Communication Style with Matt

- Matt is a principal-level operator — skip explanations of basic concepts (Sharpe, walk-forward, etc.)
- He wants brutal honesty on bad paths — flag overbuilt, underbuilt, or wrong-direction work directly
- Label `[Assumption]`, `[Inference]`, `[Unverified]` on load-bearing claims
- He runs PowerShell on Windows — give commands in PowerShell-compatible form when possible
- He cares about token cost — flag if a phase looks expensive before running it

## Decision Audit Trail

Every Tier assignment must be reproducible from:
1. The strategy card (`strategies_vN.jsonl`)
2. The raw backtest results (`results/{strategy_id}/`)
3. The funnel_gate version (git SHA of `funnel_gate.py` at time of decision)

This is enforced by writing all three references into each `verdict.json` produced by `funnel_gate.py`.
