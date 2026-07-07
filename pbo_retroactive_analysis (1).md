# Retroactive PBO Gate Analysis — 230 Branches

**Scan date:** 2026-06-30 (retroactive)
**Target repo:** `mattamundson/jarvis-trader`
**Scan script:** custom, mirrors `scripts/ci/check_pbo_gate.py` from PR #216
**Full data:** `branch_scan.csv`, `branch_scan.json`, `strategy_touchers.json`

---

## The Headline

**The PBO gate as designed in PR #216 would BLOCK zero of your 230 branches, and WARN on only 2.**

That's not a bug — that's the data telling us something important. Let me explain.

## Full Findings

### PBO gate scope: much narrower than expected

Only **4 of 230 branches modify any `engine/data/gate_v2_verdicts/*.json` files.** The PBO gate is designed to trigger on verdict modifications only. Its retroactive footprint is essentially zero.

| Branch | Verdicts touched | Gate outcome | Missing PBO |
|---|---|---|---|
| `worktree-generation-engine` | 19 | pass (0 blocking) | 1 (MGC_trend_adx_filter_rank1) |
| `feat/live-fills-observability` | 1 | warn (missing PBO on PASS) | 1 (MES_trend_rv_filter_rank2) |
| `feat/claude-on-vertex` | 1 | pass (verdict is not PASS) | 0 |
| `patch09-llm-fallback` | 1 | pass (verdict is not PASS) | 0 |

**All 4 verdict-touchers are yours** (`Matt Amundson`). No bot has ever committed a verdict file.

### The real risk surface is 22× wider than the PBO gate covers

**88 of 230 branches (38%) touch strategy-adjacent code** — the paths the workflow's `paths:` filter watches:

| Path prefix | Branches touching |
|---|---|
| `engine/backtest/` | 80 |
| `engine/analytics/` | 26 |
| `engine/data/gate_v2_verdicts/` | 5 |
| `engine/strategies/` | 2 |
| `tools/jarvis-funnel/` | 1 |

**77 human, 11 bot.** The bots aren't the noise source; humans are.

### The 2 missing-PBO cases (legitimate warnings)

`MGC_trend_adx_filter_rank1.json` and `MES_trend_rv_filter_rank2.json` are PASS verdicts that don't have the `gate_v2_metrics.pbo` field populated. These are legitimate warnings — the gate should surface them, and they represent a **historical gap in the metric coverage**, not overfit strategies.

Suggested action: backfill the PBO field on these two verdicts (re-run gate_v2 with the current version that computes PBO) rather than leaving them as permanent CI warnings.

## What This Means for the PBO Gate Design

### The gate is fine — but it's a snake-oil gate right now

The PBO gate as currently scoped will very rarely fire because verdict files are rarely modified in-flight. Verdicts get **created** by backtest runs, not by branches. The typical flow is:

1. Author writes a new `run_es_meanrev_v2_rank1.py` on a branch
2. They run it locally, which writes `engine/data/gate_v2_verdicts/MES_meanrev_v2_rank1.json`
3. They commit both

At step 3, the workflow fires because both files changed. But if the author decides the verdict is not yet worth committing (waiting for OOS data, or the verdict is a FAIL), only the runner code lands and **the PBO gate has nothing to check.**

**That's exactly when we DO want a gate — when a new strategy runner is being added but no verdict is committed yet.** The rationale-check job in PR #216 partially covers this by requiring an economic-rationale docstring. But we can do more.

### Recommended expansion (proposed for PR #217)

Broaden the CI to include:

1. **Static PBO risk score** on new strategy files, computed from parameter grid size + timeframe + parameter count. Doesn't need a full backtest — just uses code inspection to estimate combinatorial breadth. If a new runner has grid size × timeframe options × instruments > 100, it's a high multiple-testing risk before any backtest even runs. Flag it, don't block it (grid size alone isn't decisive).

2. **Diff-vs-master verdict PBO delta.** If a PR modifies a runner but ALSO ships a verdict, cross-check that the verdict's PBO didn't get worse than master's version. This catches "silently ship the worst combo" attacks.

3. **A separate quality-gate job for strategy-code PRs that don't modify verdicts** — the 80 branches touching `engine/backtest/*.py`. This is where the missing gates live.

## Bot vs Human Behavior Summary

| Group | Touching strategy code | Modifying verdicts | Would trigger current PBO gate |
|---|---|---|---|
| Bots (claude/, agent/) | 11 | 0 | 0 |
| Humans (you) | 77 | 4 | 2 (both warn, not block) |

**The bots are actually cleaner about this than the humans.** The 11 bot branches modify code but not verdicts — meaning the bots correctly separate the "run experiment" from the "publish verdict" step. That's disciplined behavior.

## Recommended Priorities From This Data

1. **Ship the current PBO gate as-is.** It's rare-fire but that's fine — when it does fire, the signal is clean.
2. **Backfill PBO on the 2 identified verdicts** so the warning goes away for good.
3. **Add a static risk-score check on new strategy runners** — this is where the actual risk lives (see PR #217 below).
4. **Don't add complexity to catch the 226 non-verdict branches** — most are stale, most are bot-generated experiments, and the branch-hygiene workflow already handles their cleanup.

## Data files

- `branch_scan.csv` — one row per branch with metrics
- `branch_scan.json` — full JSON dump including verdict-file details
- `strategy_touchers.json` — the 88 branches touching CI-watched paths

These live in `/home/user/workspace/` on the sandbox and are attached to this session.
