# Session Report — Signal Confluence Audit Re-evaluation

**Date:** 2026-06-30
**Scope:** Re-examine the signal confluence audit's `AUCTION_EDGE_UNCONFIRMED` verdict on MES,
determine why it appeared to show "no edge," and give the auction/profile strategies a fair test.
**Outcome:** Audit demoted from a "verdict" to a "screen"; auction signals (composite/saty/tpo)
wired into the validated gate-v2 pipeline. Two PRs merged to `master` (#146, #152).

> **Fidelity note.** This is a faithful *reconstruction* of the session — every user request,
> decision, finding, PR, and command is captured — not a byte-exact raw transcript (per-tool-call
> JSON, CI payloads, and webhook events are summarized, not reproduced verbatim). No secrets,
> `.env` contents, or API-key values appeared in the session.

---

## 1. How the session started

The conversation opened on a prior thread: a `--test-end` flag had been added to
`engine/scripts/signal_confluence_audit.py` and merged (PR #123, on top of the original audit
orchestrator PR #108). The user's first message was a **gut-check**: "it's been a few days, double
check I should still do this [run the audit]."

Verification confirmed: the audit code was intact on `master`, the audit had **not** yet been run,
nothing superseded it, and MES was still the right target. Green light given, with one caveat: the
OOS window was hardcoded to end `2026-03-27` (the `--test-end` flag, from #123, lets it extend).

## 2. The audit was run — and the result looked damning

The user ran the audit and committed the result JSON. Verdict: **`AUCTION_EDGE_UNCONFIRMED`**.

Key numbers from that run (window 2024-06-01 → 2025-06-01 train, → 2026-03-27 test):

| Arm | OOS PF | OOS Sharpe | OOS trades | Note |
|---|---|---|---|---|
| atrtrail ("winner") | 0.40 | −5.44 | 105 | 68% max drawdown, −66% return |
| trend (baseline) | 0.22 | −9.97 | 10 | WFE 0.025 |
| composite | 0.00 | — | **0 OOS** | 21 train trades, 0 in OOS |
| tpo | — | — | `no_combos` | no tradeable combos |
| saty | ∞ | 22.0 | 2 | excluded (under-sampled) |

First read (later substantially corrected): everything underwater, "auction family shows no edge."

## 3. The user pushed back — and was right

The user challenged: *"I cannot imagine all these strategies that I know for a fact show promise in
everyday trading have absolutely zero edge."*

This triggered a step-back investigation (3 parallel Explore agents: data-loading, cost model,
champion-reconciliation). **Conclusion: the audit was not a fair test.** Three independent reasons:

### Root cause 1 — Methodology mismatch (primary)
The validated MES trend champion earned **p_edge 0.75** via a **rolling walk-forward** (18 windows,
6mo train / 1mo test / 1mo step), a **3-combo** grid, and a **bootstrap p_edge** — see
`engine/scripts/validate_strategy.py` + `engine/data/gate_v2_verdicts/`. The audit instead used
**one fixed train/test split + a 27-combo grid**. On a low-frequency strategy (~1 trade/month) that
combination overfits the train slice (train PF **8.7** on 9 trades) and collapses OOS — a textbook
small-sample / data-snooping artifact (`.claude/rules/ml-pitfalls-defense.md` #3/#4).

### Root cause 2 — The auction arms barely traded (the smoking gun)
`composite` fired **21 trades in train but 0 in the 10-month OOS window**; `tpo` produced
`no_combos`; `saty` only 2. The audit swallowed these into `no_combos`/`no_data`, so a **gating**
result looked like a **no-edge** result.
- Correction made mid-session: composite is **not** a missing-STC-column bug — `generate_composite_signals`
  computes STC internally (`composite_signals.py:116-141`). It went silent in OOS because of the
  **regime/ADX gate** (no entries in `VOLATILE` regime or when `ADX < 25`, `composite_signals.py:291-293`)
  in the 2025-26 market.
- The only arm that traded a lot (`atrtrail`, 237 trades) is an **ATR trailing-stop mechanic, not an
  auction/profile read** — so the "auction family" was effectively never measured.

### Root cause 3 — Costs are real but not the villain
Round-trip ≈ **$4.99/MES contract** (`contract_specs.py:47-51` + `config.py:189-191`), ≈ 1 index
point. Genuine trend edge (2-4 pt) survives — the champion stays profitable even at **8× costs**
(PF 1.16). Costs filter junk; they do not bury real edge. No cost-model change made.

### Bonus — reproducibility landmine
In CI / a fresh container, MES is on `POLYGON_FUTURES_BLOCKLIST` (`data/market_data.py:86-104`) and
the cache is empty, so `BacktestDataLoader.load()` returns `None` (`data_loader.py:264-270`). The
audit then emitted a normal `no_data` verdict — i.e. it could silently report "nothing found" when
nothing was tested.

## 4. What was built (3 phases)

A plan was approved (see `/root/.claude/plans/yes-absolutely-i-think-gleaming-mango.md` at session
time). Environment constraint throughout: **backtests cannot run in the cloud container** (no MES
data, MES blocklisted, no network) — all code is written + import/unit-tested here; numeric runs
happen on the operator's machine.

### Phase 1 + 3 — PR #146 `fix(analytics): make confluence audit a screen, add entry-funnel diagnostic`
- `--diagnose`: prints raw `ENTRY_NOW` counts per arm (train vs OOS) **before** the min-trade gate,
  plus a composite gate funnel (regime distribution / `ADX>=25` % / STC cross counts) — so a
  silent-zero arm is explainable instead of hidden.
- `NO_DATA_ABORT`: loud non-zero exit when the loader returns no bars (was: silent normal verdict).
- Demotion: docstring + verdict caveats now state the audit is a single-split **SCREEN, not a
  verdict**, must never be cited as evidence a strategy lacks edge, and point promotion-grade
  evaluation at `validate_strategy.py`.
- Tests: 16/16 (`tests/test_signal_confluence_audit.py`, `--noconftest`).
- **Merged** to master (squash `3d0a855`).

### Phase 2 — PR #152 `feat(analytics): evaluate auction signals via the gate-v2 pipeline`
The validation pipeline was already **signal-agnostic** (the 3 validators dispatch on `--family` and
import a `_run()` harness). Followed that convention rather than building new infrastructure:
- `engine/scripts/auction_search_common.py` — shared driver. Auction signals carry stops/targets, so
  they execute through the **real `Backtester`** (faithful exit logic), not an inline sim. Costs flow
  from the per-scenario `spec` via the Backtester's `commission_per_contract`/`slippage_ticks`
  overrides (`backtester.py:64-66`), with `spread_ticks=0` to match the trend research harness's
  commission+slippage cost model — so the **cost sweep actually scales** and the comparison stays
  apples-to-apples. Output matches the standard `_run` contract incl. the `999.0` no-loss PF sentinel.
- `engine/scripts/mes_composite_search.py` / `mes_saty_search.py` / `mes_tpo_search.py` — grid
  searches emitting `mes_<family>_search_results.json` with per-trade ledgers
  (`validate_strategy.py` reads `results[].trades[].pnl`). Composite sweeps `entry_threshold`/`band_mult`;
  saty `target_ratio`; tpo `enter`/`stop_mult`. **STC oversold/overbought NOT swept** — Tier-3 canonical.
- Dispatch + `--family` choices added to `rolling_wfo_validator.py`,
  `fixed_params_temporal_validator.py`, `cost_sensitivity_sweep.py`.
- Tests: 8/8 (`tests/test_auction_search.py`, `--noconftest`).
- **Merged** to master (squash `34a48c7`).

### Incidental — CI lint
PR #152's Engine Lint initially failed on a **pre-existing master breakage** (`I001` in
`tests/test_trader_vol_target_wiring.py`, from PR #116) — not my code. It was fixed independently on
master by **PR #153**; resolved by merging latest master into #152 (no redundant fix PR). Also note:
the original `--test-end` flag work was PR #123 (merged earlier).

## 5. Key technical decisions & rationale

- **Reuse over reinvent:** the gate-v2 battery (`validate_strategy.py` + rolling-WFO /
  fixed-params / cost-sweep validators + `monte_carlo.py` + `deflated_sharpe.py`) already existed and
  is signal-agnostic. Phase 2 added ~3-line dispatch clauses, not new stats code.
- **Backtester for auction, inline-sim for trend:** auction signals have stop/target/trailing columns
  the Backtester implements; reimplementing that risked a second subtly-wrong harness.
- **`spread_ticks=0`:** the trend champion was validated with a commission+slippage-only cost model;
  matching it keeps the auction-vs-trend gate-v2 comparison fair.
- **Tier-3 lock:** STC oversold/overbought (OS=15/OB=83) and ATR stop/target mults are never swept
  (`.claude/rules/backtest-signals.md`).
- **No safety files touched** anywhere in this work; no `[safety-review]` tag required. A gate-v2 PASS
  does **not** auto-promote — Tier 3 + the `engine/CLAUDE.md` "Flip-to-active" criteria still apply.
- **Stale-doc flag:** `.claude/rules/backtest-signals.md` still says "DO NOT TRADE: MES 0.09", which
  contradicts `engine/CLAUDE.md` (MES approved, p_edge 0.75). Surfaced to the user; not acted on.

## 6. The remaining step (operator's machine — needs MES data + venv)

```
cd engine
# Phase 1 — why arms go quiet (regime/ADX/STC funnel):
.venv/Scripts/python -m scripts.signal_confluence_audit --diagnose

# Phase 2 — rigorous gate-v2 verdict, per family (composite shown):
.venv/Scripts/python -m scripts.mes_composite_search --symbol MES
.venv/Scripts/python -m scripts.rolling_wfo_validator           --symbol MES --family composite --rank 1
.venv/Scripts/python -m scripts.fixed_params_temporal_validator --symbol MES --family composite --rank 1
.venv/Scripts/python -m scripts.cost_sensitivity_sweep          --symbol MES --family composite --rank 1
.venv/Scripts/python -m scripts.validate_strategy \
    --results-file scripts/mes_composite_search_results.json --rank 1 \
    --rolling-wfo validation_reports/MES_composite_rank1_rolling_wfo.json \
    --fixed-params validation_reports/MES_composite_fixed_params_temporal.json \
    --cost-sweep validation_reports/MES_composite_rank1_cost_sweep.json \
    --output validation_reports/MES_composite_rank1_report.json
```
Repeat with `--family saty` / `--family tpo`. Pair the gate-v2 verdict with `--diagnose`: if a
family FAILs, the funnel shows whether it's genuine no-edge vs. a regime/ADX gate zeroing it out.

## 7. PR ledger

| PR | Title | State |
|---|---|---|
| #108 | signal confluence audit orchestrator | merged (pre-session) |
| #123 | `--test-end` flag | merged (pre-session) |
| #146 | make confluence audit a screen + `--diagnose` + `NO_DATA_ABORT` | **merged** (`3d0a855`) |
| #152 | evaluate auction signals via the gate-v2 pipeline | **merged** (`34a48c7`) |
| #153 | fix I001 lint on master (by others) | merged |

## 8. Files added / changed by this session's PRs

**#146** — `engine/scripts/signal_confluence_audit.py`, `engine/tests/test_signal_confluence_audit.py`
**#152** — `engine/scripts/auction_search_common.py`, `engine/scripts/mes_composite_search.py`,
`engine/scripts/mes_saty_search.py`, `engine/scripts/mes_tpo_search.py`,
`engine/tests/test_auction_search.py`, and dispatch/choices edits in
`engine/scripts/rolling_wfo_validator.py`, `engine/scripts/fixed_params_temporal_validator.py`,
`engine/scripts/cost_sensitivity_sweep.py`.

## 9. Bottom line

The user's instinct was correct: the confluence audit never fairly tested the auction/profile
strategies. `master` now carries (a) a corrected diagnostic that can't be misread as "no edge" and
(b) an apples-to-apples evaluation path against the same yardstick that validated the trend champion.
The verdict on whether composite/saty/tpo carry real edge is now reproducible — pending the runs above.
