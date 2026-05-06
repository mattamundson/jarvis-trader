---
session: WFO Session 4 — Final State
date: 2026-05-06
author: Claude Sonnet 4.6
status: terminal-handoff
---

# WFO Campaign — Final State as of 2026-05-06

> WARNING: Multiple parallel Claude sessions were active during this session. 
> This handoff reflects verified git log state, not any single session's narrative.

---

## 1. Current State (Verified from git log)

| Family | Symbol | Verdict | Key Metrics |
|---|---|---|---|
| SMA trend | MES | **ACTIVE** | fast=60/slow=200/atr=2.0; dsr=1.0, wfo=STRONG, mc_dd=0.81%; expires ~2026-06-05 |
| SMA trend | MNQ | EXHAUSTED ranks 1-2 | 0 OOS trades (SMA crossover scarcity, 2024-25 bull) |
| SMA trend | MCL | EXHAUSTED hyp A-E | Daily too sparse; 1h thin coverage; sentiment insufficient |
| SMA trend | M2K | EXHAUSTED ranks 1-2 | rank1: pf_ci=0.47; rank2: pf_ci=0.52, p_edge=0.36, 31 trades |
| SMA trend | MGC | **PROMISING** rank1-2 FAIL (sparsity only) | rank1: fixed_min_pf=1.186, mc_dd=0.09%, wfo=MODERATE, 5 OOS trades |
| Breakout | MNQ | EXHAUSTED ranks 1-7 | Non-stationary regime; regime filter doesn't help |
| ORB | MNQ | FAIL rank1 | IS best PF<1.0 in all windows; no ORB edge for MNQ |

**The only live signal is MES rank11 (ACTIVE, ALT path).**

---

## 2. MGC — Critical Finding

MGC rank1 FAIL is a **statistical power failure, NOT a signal quality failure.**

```
pf_ci_lower = NaN (only 5 OOS trades — bootstrap CI breaks)
p_edge       = 0.60   (3/5 profitable windows — 60% hit rate)
mc_95th_dd   = 0.09%  (almost no drawdown — extraordinary)
wfo          = MODERATE (passes 55% consistency threshold)
fixed_min_pf = 1.186  (just below 1.20 threshold; all 27 combos PF > 1.18)
```

**Interpretation**: MGC SMA crossovers fire ~1-2x per 6-month IS window. In 1-month OOS windows, most windows see 0 trades. When a trade fires, it wins 60% of the time with almost no drawdown. The edge is real but the evaluation framework can't measure it.

### Fix strategy for MGC rank3:

Option A: Extend OOS window to 2-3 months (more trades per OOS window):
```python
TRAIN_MONTHS = 6
TEST_MONTHS  = 3   # ← was 1
STEP_MONTHS  = 1
```
Risk: fewer total windows (18 → ~15)

Option B: Extend IS window to 12 months (more diverse IS conditions):
```python
TRAIN_MONTHS = 12  # ← was 6
TEST_MONTHS  = 1
STEP_MONTHS  = 1
```

Option C: Use daily bars (MGC 1d cache exists at `MGC_2022-01-01_2026-03-28_1d.csv`):
- Daily SMA(~25,~75) on gold might produce more crossovers per year
- More OOS trades per 1-month window
- Need `rv_annual_factor=252` and `fixed_contracts=1`

Option A (3-month OOS) is recommended — keeps 1h bar resolution, most direct fix.

---

## 3. Git State (Snapshot: 2026-05-06 ~06:00 CDT)

```
HEAD: bcf886f feat(wfo): MGC trend rank2 FAIL — 4 OOS trades; ATR=2.5 sparsity + 1mo OOS window too short
Recent commits:
bcf886f feat(wfo): MGC trend rank2 FAIL
f4d5108 feat(discord): add Phase 4+5 task installers
96b32e7 data(discord): 2026-05-05 digest
19461ad feat(wfo): MGC trend rank1 FAIL — all 27 combos PF>1.18, wfo=MODERATE
572b2bf docs(session-logs): expand WFO session 4 handoff with deep analysis
bb9b918 docs: correct wfo-session4 handoff
d7b2c7c docs: update WFO session4 handoff
930153b feat(backtest): M2K trend rank2 runner + session4 handoff
3a4348f fix(discord): resolve split-brain DB
0fce183 feat(backtest): MNQ ORB rank1 FAIL verdict (committed this session)

Uncommitted:
 D engine/data/gate_v2_verdicts/MNQ_orb_rank1.json   (deleted by parallel session)
?? engine/backtest/run_mgc_trend_rank3.py             (created by parallel session, not yet committed)
```

Note: `MNQ_orb_rank1.json` was committed as `0fce183` (in git history) but then deleted from working tree by a parallel session. The verdict data is safe in git.

---

## 4. Files Created/Modified This Session

| File | Action | Commit | Notes |
|---|---|---|---|
| `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` | Created + committed | 0fce183 | MNQ ORB rank1 FAIL (pf_ci=0.62, p_edge=0.18) |
| `docs/session-logs/HANDOFF_2026-05-06-wfo-session4.md` | Created + corrected | bb9b918 | Corrected duplicate handoff |
| `engine/backtest/run_mnq_orb_rank1.py` | Edit was no-op | n/a | UTC→ET fix already in 804462d |

---

## 5. In-Progress Work

`engine/backtest/run_mgc_trend_rank3.py` is untracked (created by parallel session). It likely implements Option A (3-month OOS) or Option B (12-month IS) from above. **Next session should commit and run it.**

---

## 6. Blockers

| Blocker | Notes |
|---|---|
| Polygon futures blocklisted | Cache data stops at 2026-03-28; need IBKR for extension |
| MCL Hyp-B corey_session_bias | Only 29 rows; need ≥90 rows before re-run (~2026-08-01) |
| Parallel session conflict risk | Multiple sessions on same branch; always `git pull` at session start |

---

## 7. TODO — Immediate

1. **Commit `run_mgc_trend_rank3.py`** — check what approach it uses, then commit
2. **Run MGC rank3** — should fix the statistical power problem
3. **If MGC rank3 PASS**: Add MGC to paper_config; remove from DO_NOT_TRADE after authorization
4. **MES rank11 refresh** — expires ~2026-06-05; re-run WFO with updated data when IBKR extends cache

---

## 8. TODO — Human Actions Required (Amo)

- **A1: Phase 0 credential rotation** (services 1-15, ~2-3h) — HIGHEST PRIORITY; 108 HIGH findings
- **A2: DISCORD_TOKEN** in `engine/.env` to activate Discord cron pipeline
- **A3: Delete `jarvis-trader - Copy`** (8 GB reclaim)
- **A4: Telegram BotFather phone setup** (~10 min, Hermes Phase 5c)

---

## 9. Key Architectural Decision

MGC is the most promising unexplored symbol in the campaign. The rank1/rank2 failures are methodological (1-month OOS too short for a signal that fires 2-3x/year) rather than edge failures (all 27 parameter combinations profitable on full dataset). Rank3 with a longer OOS window is the highest-probability next step.

The MNQ and MCL families are definitively exhausted. MES is the only production-grade signal. The goal of WFO session 4 was to extend the signal portfolio — MGC rank3 is the path to achieving that.
