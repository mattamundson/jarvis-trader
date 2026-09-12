# Trade-Level Diebold-Mariano Validation Loop Implementation Plan

> **For Hermes:** Execute this plan task-by-task with verification after every code/report change. Do not modify live trading, risk, kill-switch, broker execution, `.env`, or `paper_config.py`. Any such change requires a dedicated `[safety-review]` PR and explicit approval.

**Goal:** Build a complete research-only trade-level Diebold-Mariano (DM) validation loop for MES parameter-neighbor robustness: generate per-trade PnL sidecars, compare champion-vs-neighbor configurations statistically, document the preliminary local-cache result, and leave a clean PR/handoff/next-action queue.

**Architecture:** PR #805 merged the base DM screen and `iterate.py --trades-out` sidecar producer. This follow-on branch adds the missing consumer path: `dm_edge_screen.py --input-kind trades` reads sidecar trade PnL streams, aligns by trade index or exact exit timestamp, and reuses the same HLN-corrected DM test. The result is a no-runtime-impact research gate that can later run on restored deep MES data.

**Tech Stack:** Python stdlib + existing JARVIS engine venv; `engine/backtest/dm_edge_screen.py`; `engine/backtest/iterate.py`; JSON sidecars; `ruff`; GitHub PR via `gh`.

---

## Why we are accomplishing this goal

JARVIS currently has a known validation gap: window-level aggregate metrics can say one parameter set looks better, but they do not answer whether the improvement is statistically distinguishable at the actual trade/PnL sequence level. For MES trend_rank11, the parameter-neighbor question is load-bearing: 60/200/2.0 outperformed 55/200/2.0 and 50/200/2.0 in aggregate PF, but one weak neighbor can imply overfit sensitivity. Trade-level DM is the cheapest next hardening step before any further strategy promotion claims.

This accomplishes four things:

1. **Turns DM from a window-only audit into a trade-level audit.** The same statistical test can now compare actual per-trade PnL streams.
2. **Separates implementation from certification.** Local 2.37y cache results are useful for tool validation but explicitly not deep edge certification.
3. **Creates a repeatable research workflow.** Future strategies can emit sidecars with `iterate.py --trades-out` and run the same DM command.
4. **Reduces false confidence.** If champion-vs-neighbor trade-level DM is insignificant, the right conclusion is robustness uncertainty, not promotion.

## Final measurable finish line

The loop is complete when all are true:

- `dm_edge_screen.py` supports `--input-kind trades` with `--trade-metric pnl|pnl_pct` and `--trade-align index|exit_date`.
- Tests cover sidecar parsing, alignment, insufficient sample/no-overlap behavior, and existing verdict mode still passes.
- Sidecars exist/read back for MES 50/200/2.0, 55/200/2.0, and 60/200/2.0 on the current local cache.
- Trade-level DM results are run and documented for 60 vs 55 and 60 vs 50.
- Verification passes: `py_compile`, golden tests, `ruff check`, sidecar count readback, and CLI DM readback.
- A scoped commit is pushed to a new branch and a PR is opened/updated.
- `NEXT_TOP10_ROI_LOOP_LATEST.md` and a handoff reflect the new state and next recommendation.

## Step-by-step implementation

### Task 1 — Create a follow-on branch from merged PR #805 state

**Objective:** Preserve in-flight trade-mode changes after PR #805 merged and its branch was deleted.

**Files:** none.

**Command:**

```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-dm-edge-screen-20260911
git switch -c feat/trade-level-dm-consumer-20260911
git status --short --branch
```

**Expected:** new branch with modified `engine/backtest/dm_edge_screen.py` and `engine/backtest/tests_dm_edge_screen.py`.

### Task 2 — Add trade-sidecar input mode to DM screen

**Objective:** Make `dm_edge_screen.py` consume sidecar `trades` arrays as score streams.

**Files:**
- Modify: `engine/backtest/dm_edge_screen.py`

**Design:**
- Preserve default verdict behavior.
- Add CLI flags:
  - `--input-kind verdict|trades` default `verdict`
  - `--trade-metric pnl|pnl_pct` default `pnl`
  - `--trade-align index|exit_date` default `index`
- Implement `load_trade_series(path, metric, align)`:
  - parse JSON
  - read `trades` array
  - for `index`, use ordinal strings `0..n-1`
  - for `exit_date`, use exact `exit_date`
  - skip missing/non-finite values
- Reuse existing `align()` and `dm_test()`.

**Acceptance criteria:** running verdict-mode command still returns the same OOS PF result; running trade-mode command returns `input_kind=trades`, `metric=trade_pnl`, and an aligned `n`.

### Task 3 — Add golden tests for trade-sidecar loader

**Objective:** Prove trade-mode behavior without relying on large backtest files.

**Files:**
- Modify: `engine/backtest/tests_dm_edge_screen.py`

**Tests:**
1. Synthetic sidecar with 3 trades; `load_trade_series(..., align='index')` returns periods `["0", "1", "2"]` and PnLs.
2. Same sidecar with `align='exit_date'` returns exact timestamps and `pnl_pct` values.
3. `align()` with disjoint exit dates returns empty streams and `dm_test()` returns insufficient-sample guard.

**Acceptance criteria:** `tests_dm_edge_screen.py` passes with previous tests plus trade-sidecar tests.

### Task 4 — Generate sidecars for MES neighborhood

**Objective:** Produce the data required for champion-vs-neighbor trade-level DM.

**Files generated (gitignored results):**
- `engine/backtest/results/mes_50_200_2_20260911.json`
- `engine/backtest/results/mes_50_200_2_trades_20260911.json`
- `engine/backtest/results/mes_55_200_2_20260911.json`
- `engine/backtest/results/mes_55_200_2_trades_20260911.json`
- `engine/backtest/results/mes_60_200_2_20260911.json`
- `engine/backtest/results/mes_60_200_2_trades_20260911.json`

**Commands:** run `iterate.py` three times with one-combo grid JSON files and `--trades-out`.

**Acceptance criteria:** aggregate `total_trades` equals sidecar `n_trade_rows` for each combo.

### Task 5 — Run trade-level DM comparisons

**Objective:** Quantify whether champion 60/200/2.0 beats neighbors at trade level.

**Commands:**

```bash
python engine/backtest/dm_edge_screen.py \
  engine/backtest/results/mes_60_200_2_trades_20260911.json \
  engine/backtest/results/mes_55_200_2_trades_20260911.json \
  --input-kind trades --trade-metric pnl --trade-align index --power 1

python engine/backtest/dm_edge_screen.py \
  engine/backtest/results/mes_60_200_2_trades_20260911.json \
  engine/backtest/results/mes_50_200_2_trades_20260911.json \
  --input-kind trades --trade-metric pnl --trade-align index --power 1
```

**Acceptance criteria:** both commands return JSON with `n`, `dm_hln`, `p_two_sided`, and directionality. Interpret positive DM as A better than B because loss differential is `L_a - L_b` with loss=`-score`.

### Task 6 — Document results

**Objective:** Preserve the quantitative conclusion and the scope caveat.

**Files:**
- Create: `engine/data/gate_v2_verdicts/TRADE_LEVEL_DM_RESULTS_2026-09-11.md`

**Required content:**
- Cache path and span.
- Sidecar count table.
- DM result table for 60 vs 55 and 60 vs 50.
- Interpretation.
- Explicit caveat: local 2.37y cache only; deep cache needed for certification.
- Safety statement: no live/risk/routing changes.

### Task 7 — Verification bundle

**Objective:** Exercise every changed artifact.

**Commands:**

```bash
C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe -m py_compile \
  engine/backtest/dm_edge_screen.py \
  engine/backtest/tests_dm_edge_screen.py \
  engine/backtest/iterate.py \
  engine/backtest/tests_iterate_trade_capture.py

C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe engine/backtest/tests_dm_edge_screen.py
C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe engine/backtest/tests_iterate_trade_capture.py
ruff check engine/backtest/dm_edge_screen.py engine/backtest/tests_dm_edge_screen.py engine/backtest/iterate.py engine/backtest/tests_iterate_trade_capture.py
```

**Expected:** all pass.

### Task 8 — Commit/push/open PR

**Objective:** Land the work in a reviewable research-only PR.

**Files to commit:**
- `docs/plans/2026-09-11-trade-level-dm-validation-loop.md`
- `engine/backtest/dm_edge_screen.py`
- `engine/backtest/tests_dm_edge_screen.py`
- `engine/data/gate_v2_verdicts/TRADE_LEVEL_DM_RESULTS_2026-09-11.md`

**Commit message:**

```text
research: add trade-level DM validation loop
```

**PR title:**

```text
Research: add trade-level DM validation loop
```

**PR body:** include summary, safety statement, and exact verification commands/results.

### Task 9 — Refresh durable queue and handoff

**Objective:** Leave no state hidden in chat.

**Files:**
- Update: `C:/Users/mattm/master-jarvis/second-brain/reports/NEXT_TOP10_ROI_LOOP_LATEST.md`
- Create stamped queue report.
- Create/update handoff: `C:/Users/mattm/.Codex/handoffs/HANDOFF_2026-09-11_trade-level-dm-validation.md`

**Next recommendation after this loop:** restore/acquire ≥7y MES 1h cache, then rerun sidecar+trade-level DM on deep data.

## Safety boundaries

- Do not change `engine/config.py`, `engine/risk/`, kill-switch code, `.env`, broker/execution code, or `paper_config.py`.
- Do not trade or route any orders.
- Do not operate MCL or MNQ.
- Treat all local-cache results as preliminary until deep cache is restored.

## Definition of done

This plan is done when a PR exists with verified trade-level DM support, documented MES 60-vs-neighbor results, clean targeted tests/lint, and refreshed operational artifacts pointing to the deep-cache restoration as the next highest-ROI step.
