# Branch Divergence Analysis: feat/tradingview-mcp-gamma-kraken
**Session Date:** 2026-05-05  
**Analysis Type:** Pre-Phase 6 Reconciliation  
**Status:** Read-Only Analysis

## Executive Summary

| Metric | Count |
|--------|-------|
| **Incoming Commits** | 67 |
| **Outgoing Commits** | 48 |
| **Conflicting File Patterns** | 2 HIGH/MEDIUM |
| **Estimated Conflict Severity** | MEDIUM |
| **Recommended Strategy** | **REBASE** |

## Divergence Details

### Incoming Commits (67 total from origin/feat/tradingview-mcp-gamma-kraken)
- `f375e15` - chore: merge master into feat/tradingview-mcp-gamma-kraken
- `2c882ec` - feat(cohen-v3): EMA trend filter visualisation + /api/cohen_ema endpoint
- `121a3ea` - feat(phase4): Live gainers/macro wiring, MTF log, expiry tabs
- `c2eece9` - fix(ibkr): execution_log dry_run_passed=True at top level
- `2f6acf3` - feat(dashboard): Paper validation tracker + live migration checklist
- Plus 62 more (full list in commit log)

### Outgoing Commits (48 local-only)

#### **Session 5 Commits (HEAD~5..HEAD):**
1. `7b268f7` - docs: backfill plans + weekly review (Apr 22-26) + 2026-05-05 triage
2. `e9792b9` - build(deps): pin xgboost==3.2.0 and document pandas-ta Windows patch
3. `d525bac` - feat(brokers): surface blind-state on /brokers/positions reconciliation
4. `52f87f8` - feat(health): split ibkr_execution_connected vs ibkr_data_connected
5. `48330d5` - chore(gitignore): exclude broken venv backups and runtime morning_briefs

Plus 43 prior commits (HB-1 verification, PM2 monitoring, safety layers, etc.)

## Conflict Analysis

### **Intersecting Files** (by incoming commit patterns)

| File | Incoming | Ours | Severity | Resolution |
|------|----------|------|----------|-----------|
| `.gitignore` | 3 | 1 (48330d5) | **HIGH** | 3-way merge auto-resolves (non-overlapping sections) |
| `engine/requirements-core.txt` | 1 (0cb4d04) | 1 (e9792b9) | **MEDIUM** | Manual: preserve xgboost==3.2.0 + add CoT/FRED deps |
| `engine/main.py` | 9+ commits | 0 | **MEDIUM** | Context conflict around router wiring; no data loss |
| `dashboard/app/command-center/page.tsx` | 3 | 0 | LOW | Incoming only; auto-merges |
| All dashboard components | Incoming only | 0 | LOW | No conflicts |
| `engine/api/models.py` | 3 | 0 | LOW | No conflicts |

## Key Findings

1. **Total Incoming: 67 commits** (mostly Strategy C+ v3, JARVIS API bridge, dashboard v3)
2. **Total Outgoing: 48 commits** (HB-1 safety layer, PM2 monitoring, health splits)
3. **True Conflicts: 2** (.gitignore [HIGH], requirements-core.txt [MEDIUM])
4. **Context Conflicts: 2-3** (engine/main.py, dashboard routing)
5. **Estimated Resolution Time:** 15-30 min with rebase

## Recommended Strategy: REBASE

**Why Rebase:**
- Linear history for 48 local feature commits
- Minimal actual data conflicts (only 2 true conflicts)
- Both conflicts are additive/non-destructive
- Maintains narrative for Phase 6+ auditing

**Fallback:** Cherry-pick if rebase context conflicts exceed 5

## Phase 6 Action Plan

1. Create backup: `git branch backup/feat-tvm-gamma-kraken-2026-05-05`
2. Rebase: `git rebase origin/feat/tradingview-mcp-gamma-kraken`
3. Resolve `.gitignore` (accept both via `git add`)
4. Resolve `requirements-core.txt` (manual merge)
5. Resolve `engine/main.py` context (review + keep all wiring)
6. Continue: `git rebase --continue`
7. Test: `pytest engine/tests/` + `npm run build`
8. Verify: `git log --oneline | head -20` shows 115 total commits

---

**Report:** C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\session-logs\branch-divergence-analysis-2026-05-05.md  
**Generated:** 2026-05-05  
**Status:** Ready for Phase 6 Reconciliation
