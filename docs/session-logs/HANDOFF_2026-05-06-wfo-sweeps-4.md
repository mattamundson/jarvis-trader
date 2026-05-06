---
session: 2026-05-06 WFO Sweeps (Part 4 — M2K Trend Rank1+2)
branch: feat/tradingview-mcp-gamma-kraken
head: 5e9f7de
---

## Current State

- Engine: port 8010 (plain uvicorn), not restarted this session — status unknown
- Branch: `feat/tradingview-mcp-gamma-kraken` — 4 commits ahead of origin (2 this session, 2 from peer session)
- **M2K trend family PARKED** — rank1 + rank2 both FAIL, committed 5e9f7de
- **Untracked file** (peer session artifact, not committed by this session):
  - `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` — MNQ ORB verdict

## Session Accomplishments (This Session)

### 1. M2K Trend Rank1 — FAIL (committed f9bb6eb)
- Runner: `engine/backtest/run_m2k_trend_rank1.py`
- Verdict: `engine/data/gate_v2_verdicts/M2K_trend_rank1.json`
- Grid: fast=[50,60,70] × slow=[190,200,210] × ATR=[1.5,2.0,2.5] = 27 combos
- Result: wfo_consistency=WEAK, dsr=0.0, fixed_params_min_pf=0.22, p_edge=0.27
- 11/18 OOS windows had trades (15 total) — signal exists but OOS win rate terrible (3/11 profitable)
- Root cause: MES champion params (60,200) don't transfer to M2K; most 2025 windows are lossy
- Best full-dataset combo: (50,210,1.5) PF=1.92, 33 trades — points to shorter/asymmetric params

### 2. M2K Trend Rank2 — FAIL (committed 5e9f7de)
- Runner: `engine/backtest/run_m2k_trend_rank2.py`
- Verdict: `engine/data/gate_v2_verdicts/M2K_trend_rank2.json`
- Grid: fast=[20,30,40,50] × slow=[80,120,160,200] × ATR=[1.0,1.5,2.0] = 48 combos
- Result: wfo_consistency=WEAK, dsr=0.0, fixed_params_min_pf=0.19, p_edge=0.36
- 14/18 OOS windows had trades (31 total, up from rank1's 15) — signal volume improved but win rate still 35.7%
- IS champion: (20,200,1.5) most-selected but no stable dominant combo across windows
- Full-dataset combos > PF 1.2: (20,80,1.5)=1.36, (20,200,1.5)=1.76, (30,80,1.5)=1.30, (40,120,1.5)=1.33, (50,160,1.5)=1.28, (50,200,1.5)=1.46 — but fixed_params_min_pf is the MINIMUM (0.19), failing the gate
- Conclusion: M2K SMA trend family definitively PARKED — Russell 2000 (2024-2026) lacks clean trend structure

### 3. Fixed NameError in run_m2k_trend_rank1.py
- Added `n_combos = len(FAST_PERIOD_VALUES) * ...` before reference at line 675
- Was a trailing exception after successful verdict write (no data loss)

## Files Created or Modified

| File | Status | Change |
|------|--------|--------|
| `engine/backtest/run_m2k_trend_rank1.py` | COMMITTED (f9bb6eb) | NEW — M2K trend rank1 WFO runner |
| `engine/data/gate_v2_verdicts/M2K_trend_rank1.json` | COMMITTED (f9bb6eb) | NEW — FAIL verdict |
| `engine/backtest/run_m2k_trend_rank2.py` | COMMITTED (5e9f7de) | NEW — M2K trend rank2 runner |
| `engine/data/gate_v2_verdicts/M2K_trend_rank2.json` | COMMITTED (5e9f7de) | NEW — FAIL verdict |
| `engine/logs/m2k_trend_rank1_full.log` | NOT COMMITTED (gitignored) | Full rank1 sweep output |
| `engine/logs/m2k_trend_rank2_full.log` | NOT COMMITTED (gitignored) | Rank2 log — being written |

## Peer Session Activity (This Branch, Not This Session)

| Commit | Summary |
|--------|---------|
| 804462d | `fix(backtest): MNQ ORB — UTC→Eastern timezone conversion for RTH bar detection` |
| d20c249 | `fix(discord): remove --overwrite flag, fix Export-Channel stdout capture` |
| 603d4f8 | `feat(backtest): MNQ ORB rank1 — gate v2 WFO for opening range breakout` |

Untracked from peer: `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` — verdict from the MNQ ORB sweep. Next session should check if this should be committed or if peer session will handle it.

## Key Decisions Made

1. **M2K rank2 grid design:** Expanded to shorter MA periods (fast 20-50, slow 80-200) rather than a tighter grid around rank1 best (50,210). Rationale: the rank1 failure was structural — not enough OOS trades per 1-month window, not just parameter misspecification. Shorter MAs generate more crossovers which gives the statistical gate (p_edge, DSR) something to work with.

2. **ATR=[1.0,1.5,2.0] for rank2:** Added 1.0 (was 1.5-2.5 in rank1). Lower ATR trail keeps more trades alive longer on the more volatile M2K, potentially improving per-trade PF.

3. **M2K uses risk-based sizing (no fixed_contracts override):** Unlike MCL daily (where ATR-based sizing → 0 contracts on $10K), M2K 1h ATR is small relative to $50K capital. $50K × 1% = $500 budget, M2K 1h ATR ≈ $10-25/contract → floor(500/10) = 50 contracts minimum. Risk-based sizing works fine.

4. **M2K CAPITAL=$50_000 (ALT path):** Same as MES rank11. M2K needs $50K+ for ALT gate (dsr≥0.30, wfo in MODERATE/STRONG, fixed_params_min_pf≥1.20, mc_dd≤7%).

## In-Progress Work

None. All work committed as of 5e9f7de.

## Blockers Discovered

None new this session.

## M2K Rank1 Full Results Reference

```
Window  IS champion         OOS PF   OOS trades
1       (50,200,2.5)        inf      1   WINNER
2       (60,200,2.5)        0.00     0
3       (60,200,2.5)        0.00     1
4       (60,200,2.5)        0.00     0
5       (50,190,2.5)        0.00     0
6       (50,190,2.5)        0.00     1
7       (60,210,2.0)        0.00     0
8       (60,210,2.0)        0.00     1
9       (70,190,1.5)        0.00     1
10      (60,190,1.5)        0.00     2   (Sharpe=-1141!)
11      (60,190,1.5)        0.00     0
12      (70,210,2.5)        0.00     1
13      (50,210,1.5)        inf      2   WINNER
14      (50,200,2.5)        0.00     1
15      (50,210,1.5)        0.00     0
16      (50,210,1.5)        5.18     2   WINNER
17      (50,210,1.5)        0.00     2
18      (50,210,1.5)        0.00     0
```

Fixed-params sweep best (full dataset, 2 years):
- (50,210,1.5): PF=1.9219, 33 trades
- (50,190,1.5): PF=1.5895, 38 trades  
- (50,210,2.0): PF=1.5322, 33 trades
- (50,200,1.5): PF=1.4597, 35 trades

## TODO

**Immediate:**
1. Check `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` (peer session, untracked) — read verdict and commit if peer hasn't
2. Next M2K hypothesis: **M2K ORB rank1** (opening range breakout) — trend family parked

**Time-sensitive (30 days):**
- MES rank11 refresh by 2026-06-05 — already done 2026-05-06T02:39; no action until ~June 4

**Amo-gated:**
- Phase 0 rotation T2-T15 (14 services: OpenAI/Azure/Paradigm/Google etc. — needs 1Password)
- D-drive YELLOW: iCloud .Trash ~7GB, WindowsImageBackup ~23GB, GoPro ~17.9GB
- Engine .env update with rotated credentials
- career-ops: archive stale Evaluated entries

**MNQ ORB rank1 (peer session):**
- Verdict JSON exists untracked: `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json`
- `engine/backtest/run_mnq_orb_rank1.py` appears to be modified (shows in `git status`)
- Next session: check MNQ ORB verdict result and commit if peer session hasn't

## Git State (at session close)

```
On branch feat/tradingview-mcp-gamma-kraken
Your branch is ahead of 'origin/feat/tradingview-mcp-gamma-kraken' by 5 commits.

Untracked files:
  engine/data/gate_v2_verdicts/MNQ_orb_rank1.json  (peer session artifact)
  engine/backtest/run_mnq_orb_rank1.py              (peer session modification)

nothing added to commit but untracked files present
```

### git log --oneline -20
```
5e9f7de feat(wfo): M2K trend rank2 FAIL — M2K trend family parked (2 ranks exhausted)
804462d fix(backtest): MNQ ORB — UTC->Eastern timezone conversion for RTH bar detection
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
0747643 feat(backtest): MCL trend Hyp-D rank2 — 3-month OOS windows
50caec0 docs(session-logs): handoff for WFO session 2 — MNQ parked, MCL Hyp-E next
2d7378c feat(wfo): MCL trend Hyp-D FAIL — DSR 0.286 just below 0.30 ALT floor
d393b6b feat(verdicts): MCL trend Hyp-D FAIL — 1mo OOS too narrow; rank2 needed
2770304 fix(backtest): add jarvis_trader.db as primary candidate in _find_sentiment_db
f203826 feat(backtest): add MCL Hypothesis D — SMA trend-following runner
2e5885d docs(session-logs): expand discord/career-ops/WFO handoff + archive stale verdicts
```

## Suggested Next Action

1. Read `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` to see MNQ ORB rank1 result
2. If that verdict is PASS: wire to engine + paper trading authorization
3. If FAIL: build MNQ ORB rank2 (tighter grid around rank1's best combo)
4. Parallel path: build `run_m2k_orb_rank1.py` — M2K ORB is now the leading M2K hypothesis

## M2K Rank2 Full OOS Window Results Reference

```
W5  (50,80,1.5):    OOS PF=9.47  trades=2   WINNER
W6  (50,80,1.5):    OOS PF=1.79  trades=4   WINNER
W9  (20,120,1.5):   OOS PF=1.13  trades=3   WINNER
W10 (20,120,1.0):   OOS PF=2.01  trades=3   WINNER
All other active windows: PF < 1.0 (losers)
```

Best full-dataset fixed-params (rank2):
- (20,200,1.5): PF=1.7557, 50 trades — champion
- (20,80,1.5):  PF=1.3553, 96 trades — highest frequency
- (30,80,1.5):  PF=1.3001, 84 trades
- (40,120,1.5): PF=1.3302, 55 trades

Interesting: all best combos share atr_trail_mult=1.5. The ATR trail value may matter more than MA periods. Possible rank3 direction: fix atr=1.5, grid-search fast/slow more densely in the (20-50, 80-200) space. But given 4 straight FAILs on M2K trend, recommend ORB first.
