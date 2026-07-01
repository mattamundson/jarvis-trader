# Bot vs Human Verdict Discipline Audit — All Branches

**Scan date:** 2026-06-30
**Scope:** All 231 remote branches (44 bot, 187 human)
**Data:** `discipline_audit.csv`, `discipline_audit.json`

## Headline

**Bot verdict discipline: 100%. Human discipline: 94%.**

The bots (Claude sessions, agent branches) have not committed a single instance of the "bad" pattern: bundling verdict-file changes with strategy-code changes in the same commit. All 4 verdict-bundling commits are yours.

## Discipline metrics across all 231 branches

| Metric | Bot (n=44) | Human (n=187) |
|---|---:|---:|
| Branches touching strategy code | 5 | 37 |
| Branches touching verdict files | **0** | 4 |
| Branches adding new runners | 5 | 26 |
| Branches modifying signal code | 3 | 20 |

### Commit-level discipline

| Pattern | Bot | Human |
|---|---:|---:|
| Total verdict-file changes | 0 | 22 |
| PASS verdicts committed | 0 | 2 |
| FAIL verdicts committed | 0 | 20 |
| PASS verdicts complete with PBO | 0 | 0 |
| PASS verdicts missing PBO | 0 | **2** |
| **Bundled commits (verdict + code)** | **0** | **4** |
| Verdict-only commits (good) | 0 | 3 |
| Code-only commits (good discipline) | 18 | 59 |

**Bot discipline score: 1.00**
**Human discipline score: 0.94**

## The 2 branches with discipline violations

Both are yours:

| Branch | Bundled commits | Author | Context |
|---|---:|---|---|
| `worktree-generation-engine` | 3 | Matt | Generation engine work; bundled verdict + engine code |
| `patch09-llm-fallback` | 1 | Matt | Backtest recommendations bundled with LLM patch |

Neither is a catastrophe — the "violation" is stylistic: the CI can't isolate verdict changes for independent review when they're mixed with code changes in the same commit. Split commits by concern going forward.

## The 2 PASS verdicts missing PBO metric

Both flagged by the earlier retroactive scan:

- `MES_trend_rv_filter_rank2.json` (from `feat/live-fills-observability`)
- `MGC_trend_adx_filter_rank1.json` (from `worktree-generation-engine`)

**Action:** re-run gate_v2 on these to backfill PBO, then commit the updated verdicts. Handles both the discipline gap and the CI warning gap.

## Why bots score higher than humans

Interpretation: bot workflows (Claude sessions) are stateless per-session. Each session sees the repo, does a bounded task, commits code only, and stops. They never need to say "and here's the verdict from what I just ran" because verdicts require a full backtest run that most bot sessions don't execute. This makes bots structurally disciplined **by not doing enough to be undisciplined.**

That's not the same as "bots are more careful" — it's "bots are more constrained." If bots were empowered to run full backtests and commit verdicts, they'd likely make the same bundling mistakes humans do.

Practical implication: **the discipline score isn't a merit ranking, it's a friction test.** The reason humans slip is that the friction between "I have working code" and "let me commit the verdict too" is low. A pre-commit hook that separates verdict commits from code commits would close the gap without requiring more human care.

## Recommended follow-up

1. **Backfill PBO on the 2 legacy verdicts** — one-off fix
2. **Pre-commit hook**: warn (not block) when a commit touches both `engine/data/gate_v2_verdicts/` and `engine/backtest/`, suggesting the user split the commit
3. **Commit template** in `.gitmessage` reminding authors to keep verdict changes atomic

None of these need to be in PR #219 — they're follow-ups that can each be a small PR of their own.
