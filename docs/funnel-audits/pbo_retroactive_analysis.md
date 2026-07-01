# Retroactive PBO Gate Analysis — 230 Branches

**Scan date:** 2026-06-30
**Method:** custom scanner mirroring `scripts/ci/check_pbo_gate.py` from PR #216, run against all remote branches

## Headline

**The PBO gate as designed in PR #216 would BLOCK zero of your 230 branches and WARN on only 2.**

That's not a bug — the retroactive scan reveals that verdict-file modifications are far less common than expected in your dev flow. The finding **redirects the automation strategy**: expand risk coverage from verdicts to runner code (see the follow-on PR #217).

## Scan results

| Metric | Count |
|---|---:|
| Total branches scanned | 230 |
| Branches modifying verdict files | 4 |
| Branches with BLOCKING verdicts (PBO ≥ 0.40) | 0 |
| Branches with WARNING verdicts (0.30 ≤ PBO < 0.40) | 0 |
| Branches with PASS verdicts missing PBO | 2 |
| Branches touching strategy-adjacent code | 88 (38%) |
| — Bot-authored | 11 |
| — Human-authored | 77 |

### The 4 verdict-touching branches

| Branch | Verdicts | Outcome |
|---|---:|---|
| `worktree-generation-engine` | 19 | 1 missing-PBO warning on `MGC_trend_adx_filter_rank1` |
| `feat/live-fills-observability` | 1 | Missing-PBO warning on `MES_trend_rv_filter_rank2` |
| `feat/claude-on-vertex` | 1 | Verdict is not PASS — no gate action |
| `patch09-llm-fallback` | 1 | Verdict is not PASS — no gate action |

All 4 were authored by @mattamundson. No bot has ever committed a verdict file — bots correctly separate the "run experiment" step from the "publish verdict" step.

### The 88 strategy-touching branches (real risk surface)

The PBO gate's `paths:` filter watches 5 directories. The distribution of touches:

| Path | Branches touching |
|---|---:|
| `engine/backtest/` | 80 |
| `engine/analytics/` | 26 |
| `engine/data/gate_v2_verdicts/` | 5 |
| `engine/strategies/` | 2 |
| `tools/jarvis-funnel/` | 1 |

**80 branches modify `engine/backtest/` — the runner code where new strategies are born — but only 5 touch verdicts.** The gap between "strategy code changed" and "verdict published" is where the current PBO gate has a blind spot.

## Design implications for PR #217

The current PBO gate is fine but rarely-fired. The retroactive scan reveals two coverage gaps:

1. **Missing PBO backfill.** Two committed PASS verdicts lack the PBO metric. Re-run gate_v2 on them so the CI warnings are one-time cleanup, not permanent noise.

2. **Runner-code risk isn't checked.** 80 branches touched `engine/backtest/` without touching verdicts. That's where undocumented parameter-grid expansions or new strategy variants can slip in.

PR #217 addresses (2) with a broader risk-score check on new runner files: parameter grid × instruments × timeframes. High combinatorial breadth flags for review even before any backtest runs.

## Bot vs human insight

Surprising result: **the bots are cleaner about verdict discipline than the humans.** 11 bot branches touch strategy code, none touch verdicts. All 4 verdict-touchers are human commits. This suggests the bot workflows (Claude sessions) correctly treat verdicts as artifacts of a completed experiment, while human commits sometimes bundle in-progress verdict edits with code changes.

Not an immediate action item — just something to remember when deciding whether to trust bot-generated PRs (currently: as trustworthy as human ones, sometimes more).

## Full data

`branch_scan.csv` and `branch_scan.json` in `docs/funnel-audits/` contain per-branch details for anyone who wants to re-run the analysis.
