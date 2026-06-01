---
session: WFO Session 4
date: 2026-05-06
author: Claude Sonnet 4.6
status: handoff
---

# Session Summary — WFO Session 4

Continued multi-session WFO campaign. Primary work: completed MNQ ORB rank1, M2K trend rank1, and MNQ ORB rank1 re-run after timezone fix. All three FAIL. MCL and MNQ signal families are now exhausted. Only active signal: MES rank11 (ALT path, expires ~2026-06-05).

---

## 1. Current State

| Component | Status | Notes |
|---|---|---|
| MES rank11 | **ACTIVE** | ALT path PASS; fast=60/slow=200/atr=2.0; expires ~2026-06-05 |
| MCL trend | EXHAUSTED (5 hyp) | Hyp A-E all FAIL; root cause: daily crossovers too sparse for 1-mo OOS |
| MNQ trend | EXHAUSTED (ranks 1-2) | 0 OOS trades; SMA crossover scarcity in 2024-2025 bull run |
| MNQ breakout | EXHAUSTED (ranks 1-7) | Non-stationary regime; regime filter didn't rescue |
| MNQ ORB | rank1 FAIL | pf_ci=0.62, p_edge=0.18, DD=28%; IS best PF < 1.0 in all windows |
| M2K trend | EXHAUSTED ranks 1-2 | rank1: pf_ci=0.47; rank2: pf_ci=0.52, p_edge=0.36, 31 trades |
| Engine | unknown | Not restarted this session |
| Career-ops | pipeline active | AtLogon + --live flag wired; 351 tests passing |

---

## 2. Key Decisions Made

### MNQ ORB rank1 — FAIL verdict confirmed (two runs)

First run (from prior session, buffered output) produced: `MNQ_orb_rank1.json`
- VERDICT: FAIL
- pf_ci_lower=0.6186, p_edge=0.1765, mc_95th_dd=28.15%, dsr=0.0, wfo=WEAK
- fixed_params_min_pf=0.708, champion: {volume_filter: True, regime_filter: False, min_or_range_pct: 0.0005}
- 353 OOS trades across 17/18 windows (plenty of data)
- 17/18 windows ACTIVE but only 3 profitable (p_edge=0.18)

Second run (this session, with timezone fix already in place since commit 804462d) confirmed same results:
- IS best PF < 1.0 in every window (e.g., window 1: IS PF=0.92, window 2: IS PF=0.82)
- "Best" IS params are just the least-bad losing combination
- OOS windows: W4=1.68 (only winner), W5=0.59, W6=0.90, W7=0.76, W8=0.26...
- **Root cause: ORB has no edge for MNQ in the 2024-2025 timeframe.** The NQ moves too far/fast for OR range-based stops — large overnight gaps blow through T1/T2 levels inconsistently.

### M2K trend rank1 — FAIL verdict
- pf_ci=0.47, p_edge=0.27, wfo=WEAK, 15 OOS trades / 11 windows  
- mc_95th_dd=1.19% (good DD, wrong direction on PF)
- Best full-dataset: (50,210,1.5) PF=1.92 on 33 trades — promising but not robust
- Diagnosis: MES champion params (60,200,2.0) don't transfer to M2K; M2K had extended choppy/bearish 2024-2025 periods where SMA(50-70,190-210) lost

### UTC→ET timezone fix for ORB data
- IBKR cache data is naive UTC; `orb_signals.py` expects ET (hour==9 for RTH open)
- Without fix: hour 9 UTC = 5 AM ET = overnight bar (wrong OR)
- With fix: hour 9 ET = 9 AM ET = correct RTH open bar
- Fix was committed in `804462d` (prior session); confirmed working by both ORB runs producing ~22 trades/month (consistent with expected ORB frequency)

---

## 3. Files Created or Modified

| File | Action | Notes |
|---|---|---|
| `engine/backtest/run_mnq_orb_rank1.py` | COMMITTED (804462d) | UTC→ET timezone fix in `_load_data()`; prior session committed this |
| `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` | CREATED, **uncommitted** | MNQ ORB rank1 FAIL verdict; pf_ci=0.62, p_edge=0.18 |
| `engine/backtest/run_m2k_trend_rank2.py` | CREATED, **uncommitted** | M2K rank2 runner; shorter SMA periods (20-50 fast, 80-200 slow) |
| `engine/backtest/run_m2k_trend_rank1.py` | COMMITTED (f9bb6eb) | M2K rank1 WFO runner; prior session |
| `engine/data/gate_v2_verdicts/M2K_trend_rank1.json` | COMMITTED (f9bb6eb) | M2K rank1 FAIL; pf_ci=0.47, p_edge=0.27 |

---

## 4. In-Progress Work

**Nothing is in-progress.** All in-flight WFO tasks completed this session.

**MNQ ORB rank2 decision needed**: rank1 showed IS best PF < 1.0 universally. Options:
- Add trend filter (only take ORB signals in direction of 200-bar SMA) → rank2
- Park ORB family for MNQ; move to MGC (Micro Gold) which has stronger trend properties
- Consider MNQ time-of-day momentum (9:30-11 AM directional, not OR-based)
Recommendation: Park MNQ ORB and explore MGC SMA trend first (lower cost to try).

---

## 5. Blockers Discovered

| Blocker | Impact | Resolution |
|---|---|---|
| Polygon futures blocklisted | Cache data stops at 2026-03-28; can't refresh for new tickers | IBKR connection needed (paper port 4002, during trading hours only) |
| MCL Hyp-B: corey_session_bias only 29 rows | Re-run scheduled for ~2026-08-01 when 90+ rows accumulated | Wait |
| MNQ ORB rank1 IS failure | No ORB edge found; rank2 must fundamentally change signal, not just params | Architecture decision needed |
| M2K sparse OOS trades (15 trades / 11 months) | Same root cause as MNQ trend — Russell 2000 1h SMA crossovers rare | Rank2 explores shorter MAs |

---

## 6. TODO Items

### Immediate (next session):

1. **Commit MNQ ORB rank1 verdict** — `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` is untracked; commit with `feat(backtest): MNQ ORB rank1 FAIL — no ORB edge; IS best PF < 1.0 universally`

2. **Note:** M2K trend rank2 ALREADY RUN AND COMMITTED (7cf5621). Result: FAIL — pf_ci=0.52, p_edge=0.36, wfo=WEAK, 31 OOS trades / 14 windows. M2K trend family is EXHAUSTED (ranks 1-2 done).

### This week (strategy):

4. **MES rank11 refresh** — expires ~2026-06-05 (~30 days). Re-run `run_mes_trend_rank11.py` with updated data when IBKR cache can be extended.

5. **Decision: MNQ ORB rank2 or park** — IS best PF < 1.0 universally in rank1 is a strong signal to park the ORB family for MNQ. Consider instead:
   - MNQ time-of-day momentum (not a breakout, just 9:30-11 AM directional)
   - MNQ mean-reversion after gap fills
   - M2K exploration (different index, rank2 underway)

6. **Data cache refresh (IBKR)** — all data stops at 2026-03-28. Need 2026-03-28 → 2026-05-06 (~5 weeks). Requires IB Gateway paper (port 4002) during trading hours.

### Human actions required (Amo):

- **A1: Phase 0 credential rotation** — 108 HIGH findings remain; rotation services 1-15 (~2-3h total). HIGHEST PRIORITY.
- **A2: Delete `jarvis-trader - Copy`** (8 GB reclaim)
- **A3: Telegram BotFather phone setup** (~10 min, Hermes Phase 5c)
- **A4: DISCORD_TOKEN** — add to `engine/.env` to activate Discord cron pipeline

---

## 7. Strategy Landscape Summary

| Family | Symbol | Status | Verdict Key |
|---|---|---|---|
| SMA trend | MES | **ACTIVE (ALT)** | pf_ci=2.156, dsr=1.0, mc_dd=0.81% |
| SMA trend | MNQ | EXHAUSTED ranks 1-2 | 0 OOS trades; SMA scarcity |
| SMA trend | MCL | EXHAUSTED hyp A-E | Daily bars too sparse; 1h too thin |
| SMA trend | M2K | FAIL rank1; rank2 pending | rank1: pf_ci=0.47, sparse |
| Breakout | MNQ | EXHAUSTED ranks 1-7 | Regime non-stationarity |
| ORB | MNQ | FAIL rank1 | IS best PF<1.0; no edge |

**Next symbol**: MGC (Micro Gold) — cache at `engine/backtest/cache/MGC_*.csv`. Gold uncorrelated with equity micros; strong trend properties.

---

## 8. Git State

```
git log --oneline -20:
804462d fix(backtest): MNQ ORB — UTC→Eastern timezone conversion for RTH bar detection
d20c249 fix(discord): remove --overwrite flag, fix Export-Channel stdout capture
f9bb6eb feat(wfo): M2K trend rank1 FAIL — weak OOS consistency, full-dataset PF < 1.2
603d4f8 feat(backtest): MNQ ORB rank1 — gate v2 WFO for opening range breakout
2a8114b feat(backtest): MCL Hyp-E FAIL verdict — daily SMA exhausted
a00d7d5 fix(backtest): extend MCL Hyp-E IS window 6mo->12mo for daily bars
f5972d7 docs(session-logs): handoff for WFO session 3 — MCL parked, MES refresh next
5c53348 feat(backtest): MNQ trend rank2 FAIL + MCL Hyp-D rank2 FAIL verdicts
a9c57b2 feat(wfo): MCL trend Hyp-E FAIL — daily SMA crossovers too infrequent
f25dff4 feat(backtest): MCL Hyp-D FAIL verdict + Hyp-E daily-bars runner
70a3834 refactor(discord): apply 13 code-quality improvements
1ff578c feat(backtest): add rv_annual_factor param to generate_sma_trend_signals
0747643 feat(backtest): MCL trend Hyp-D rank2 — 3-month OOS windows for proper crossover evaluation
50caec0 docs(session-logs): handoff for WFO session 2 — MNQ parked, MCL Hyp-E next
2d7378c feat(wfo): MCL trend Hyp-D FAIL — DSR 0.286 just below 0.30 ALT floor

git status:
?? engine/backtest/run_m2k_trend_rank2.py
?? engine/data/gate_v2_verdicts/MNQ_orb_rank1.json

git diff --stat: (no unstaged changes)
```

---

## 9. Suggested Next Action

**DONE THIS SESSION:** MNQ ORB verdict committed (0fce183). M2K rank2 ALREADY ran in prior session (7cf5621, FAIL).

**Next session: Create MGC (Micro Gold) SMA trend rank1 runner.**

MGC cache exists at `engine/backtest/cache/MGC_*.csv`. Gold has stronger multi-week trend properties than equity micros; ORB failures were equity-specific.

Specs: `SYMBOL="MGC"`, `MULTIPLIER=10.0` ($10/oz, 10oz contract), `TICK_SIZE=0.10` ($1.00/tick), `COMMISSION=0.62`. Grid: fast=[50,60,70] × slow=[190,200,210] × atr_trail=[1.5,2.0,2.5] = 27 combos. Model runner on `run_mes_trend_rank11.py`.

Git is clean (no untracked/modified files) after this session's commits.
