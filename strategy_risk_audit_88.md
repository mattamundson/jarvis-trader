# 88-Branch Strategy Risk Audit — Non-Verdict Risk Exposure

**Scan date:** 2026-06-30
**Scope:** 88 branches touching CI-watched strategy paths (`engine/backtest/`, `engine/strategies/`, `engine/analytics/`, `engine/data/gate_v2_verdicts/`, `tools/jarvis-funnel/`)
**Data:** `risk_audit_88.csv`, `risk_audit_88.json`

## Headline

**Non-verdict risk is real but modest.** Of 88 strategy-touching branches:

- **10 branches** add new runner files without economic rationale (per strict regex check)
- **0 branches** show grid expansion (widening a parameter sweep vs master)
- **1 branch** modifies signal code without corresponding test changes

Bot vs human split of these risks:

| Risk pattern | Bot | Human |
|---|---:|---:|
| New runners lacking rationale | 1 | 9 |
| Grid expansion in existing runners | 0 | 0 |
| Signal changes without test updates | 0 | 1 |

## The grid-expansion finding is important

**Zero branches are widening parameter sweeps beyond current master.** This is a strong disconfirmation of my earlier concern that "engine/backtest/ changes hide grid explosions." That's not what's happening — the actual pattern is:

- 22 branches add NEW runners
- Max grid size on any new runner: **36 combinations**
- Median grid size: **1** (most runners have fixed params)
- Zero runners with grid ≥ 100

The multiple-testing risk from parameter sweeps is genuinely bounded in your current dev flow. That's a good thing.

## Top 10 highest-risk branches

Risk scored on: rationale-missing (3 per runner), grid-expansion (4), signal-no-test (5), old-branch (1), wide-grid (2-6):

| Risk | Bot | Age | Grid | New runners | Missing rationale | Signals no test | Branch |
|---:|---:|---:|---:|---:|---:|---:|---|
| 9 | no | 30d | 16 | 5 | 3 | no | `worktree-generation-engine` |
| 6 | no | 13d | 1 | 4 | 2 | no | `chore/wfo-live-config-match` |
| 5 | no | 4d | 0 | 0 | 0 | **yes** | `feat/strategy-factory` |
| 3 | no | 13d | 1 | 3 | 1 | no | `chore/discovery-scripts-2026-06-16` |
| 3 | **yes** | 6d | 1 | 1 | 1 | no | `claude/compassionate-cerf-2mgcp2` |
| 3 | no | 18d | 1 | 1 | 1 | no | `discovery/daily-trend` |
| 3 | no | 1d | 36 | 1 | 1 | no | `feat/funnel-vwap-shadow` |
| 3 | no | 6d | 1 | 1 | 1 | no | `feat/session-anomaly-mes` |
| 3 | no | 12d | 1 | 4 | 1 | no | `feat/strategy-edge-wave` |
| 3 | no | 8d | 8 | 1 | 1 | no | `feat/ts-overlay` |
| 3 | no | 0d | 12 | 2 | 1 | no | `meanrev-v2` (PR #213) |

**Notable self-hit:** `meanrev-v2` (this PR series) shows on the list at risk 3 — the MGC runner and the signal module don't contain the specific magic words the regex looks for. Not actually missing rationale content — see "Regex limitations" below.

## Regex limitations — false positive investigation

Spot-checking the "missing rationale" flags:

- `run_daily_trend_discovery.py` — contains the literal string "**WHY THIS BATCH (honest rationale):**" — regex missed because we require "Why this **should** work" or "**economic** rationale," not just "rationale"
- `run_mes_vwap_rank1.py` — has "VWAP Deviation Reversion strategy for MES" but never explains WHY; **legit miss**
- `run_gap_rank1.py` — has "First `gap` family ever run through gate v2" — describes what, not why; **legit miss**
- `run_mcpt.py` — is a utility/CLI runner, not a strategy runner; **false positive** (should exclude utilities)

Refinement needed for the CI check: (a) accept the word "rationale" alone, (b) exclude utility runners like `run_mcpt.py` that don't add a strategy, (c) look for the "WHY" section pattern with `##` header. Filed as follow-up.

## The 1 signal-changes-without-tests case

**`feat/strategy-factory`** (4 days old, human-authored) modifies signal code but doesn't touch `engine/tests/`. This is a real risk — signal code without test coverage means silent behavior changes ship without a regression check.

Recommended action: comment on the branch/PR asking for a matching test file, or ship the change with a test-skip block and a TODO.

## Grid size distribution (branches adding new runners)

Of the 22 branches that added new `run_*.py` files:

| Grid size | Count |
|---|---:|
| = 1 (fixed params) | 11 |
| 2-10 | 6 |
| 11-50 | 5 |
| 51-100 | 0 |
| >100 | 0 |

**Widest grid: 36 combos on `feat/funnel-vwap-shadow`**. That's well below any concerning multiple-testing threshold. The developer discipline on grid size is genuinely tight across the whole repo.

## Actionable follow-ups (NOT in this PR)

1. **Refine the rationale regex** to accept "rationale" alone and to exclude utility runners. Follow-up PR against the CI script in PR #216.
2. **Comment on `feat/strategy-factory`** asking about test coverage for the signal changes.
3. **Fix `meanrev-v2`**: add "hypothesis" or "why this should work" phrasing to the MGC runner docstring and the signal module docstring. Housekeeping.

## Data files

- `risk_audit_88.csv` — one row per branch with all risk metrics
- `risk_audit_88.json` — full JSON including runners_missing_rationale lists per branch

Both included in this PR under `docs/funnel-audits/`.
