---
session: 2026-05-06 WFO Sweeps (Part 4 — M2K Trend Rank1+2 + MNQ ORB Rank1)
branch: feat/tradingview-mcp-gamma-kraken
head: 7cf5621
created: 2026-05-06T10:45:00Z
---

## 1. Current State

| Resource | Status |
|----------|--------|
| Engine (port 8010) | Not restarted this session — last verified HEALTHY in prior session; status unknown now |
| Branch | `feat/tradingview-mcp-gamma-kraken` — 5 commits ahead of `origin/`, not pushed |
| M2K trend family | **PARKED** — rank1 + rank2 both FAIL (committed 7cf5621) |
| MNQ ORB rank1 | **FAIL** — verdict JSON written by peer session, untracked, needs commit |
| MES rank11 | **PASS** (active) — expires 2026-06-05; paper trading authorized |
| MCL | **PARKED** — 5 hypotheses exhausted (A-E); daily/hourly SMA both structural FAIL |
| MNQ | **PARKED** (trend family); ORB rank1 also FAIL — needs rank2 redesign |

**Working tree at session close:**
```
Untracked (not committed, peer session artifacts):
  engine/data/gate_v2_verdicts/MNQ_orb_rank1.json
  engine/backtest/run_mnq_orb_rank1.py  (modified by peer session)
```

---

## 2. Session Accomplishments

### 2a. M2K Trend Rank1 — FAIL

**Commit:** `f9bb6eb`  
**Files:** `engine/backtest/run_m2k_trend_rank1.py`, `engine/data/gate_v2_verdicts/M2K_trend_rank1.json`

**Grid:** fast=[50,60,70] × slow=[190,200,210] × ATR=[1.5,2.0,2.5] = 27 combos  
**Motivation:** MES rank11 champion is (60,200,2.0); start from the same region and see if the edge transfers to Russell 2000.

**Gate v2 summary:**

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| pf_ci_lower | 0.4705 | ≥1.10 | FAIL |
| p_edge | 0.2727 | ≥0.95 | FAIL |
| mc_95th_dd | 1.19% | ≤7% ALT | PASS |
| dsr | 0.000 | ≥0.30 ALT | FAIL |
| wfo_consistency | WEAK | MODERATE/STRONG | FAIL |
| fixed_params_min_pf | 0.2161 | ≥1.20 | FAIL |
| cost_survives_through | catastrophic | ≥realistic | PASS |

**OOS window results (rank1):**

| Win | IS period | OOS period | IS champion | IS PF | OOS PF | OOS trades | OOS result |
|-----|-----------|------------|-------------|-------|--------|------------|------------|
| 1 | Apr-Oct 2024 | Oct-Nov 2024 | (50,200,2.5) | inf | inf | 1 | WINNER |
| 2 | May-Nov 2024 | Nov-Dec 2024 | (60,200,2.5) | inf | 0.00 | 0 | NO TRADE |
| 3 | Jun-Dec 2024 | Dec 2024-Jan 2025 | (60,200,2.5) | inf | 0.00 | 1 | LOSER |
| 4 | Jul 2024-Jan 2025 | Jan-Feb 2025 | (60,200,2.5) | inf | 0.00 | 0 | NO TRADE |
| 5 | Aug 2024-Feb 2025 | Feb-Mar 2025 | (50,190,2.5) | 5.53 | 0.00 | 0 | NO TRADE |
| 6 | Sep 2024-Mar 2025 | Mar-Apr 2025 | (50,190,2.5) | 7.16 | 0.00 | 1 | LOSER |
| 7 | Oct 2024-Apr 2025 | Apr-May 2025 | (60,210,2.0) | 5.31 | 0.00 | 0 | NO TRADE |
| 8 | Nov 2024-May 2025 | May-Jun 2025 | (60,210,2.0) | 3.50 | 0.00 | 1 | LOSER |
| 9 | Dec 2024-Jun 2025 | Jun-Jul 2025 | (70,190,1.5) | 1.81 | 0.00 | 1 | LOSER |
| 10 | Jan-Jul 2025 | Jul-Aug 2025 | (60,190,1.5) | 1.48 | 0.00 | 2 | LOSER (Sharpe -1141) |
| 11 | Feb-Aug 2025 | Aug-Sep 2025 | (60,190,1.5) | 1.41 | 0.00 | 0 | NO TRADE |
| 12 | Mar-Sep 2025 | Sep-Oct 2025 | (70,210,2.5) | inf | 0.00 | 1 | LOSER |
| 13 | Apr-Oct 2025 | Oct-Nov 2025 | (50,210,1.5) | 5.54 | inf | 2 | WINNER |
| 14 | May-Nov 2025 | Nov-Dec 2025 | (50,200,2.5) | 8.58 | 0.00 | 1 | LOSER |
| 15 | Jun-Dec 2025 | Dec 2025-Jan 2026 | (50,210,1.5) | 4.32 | 0.00 | 0 | NO TRADE |
| 16 | Jul 2025-Jan 2026 | Jan-Feb 2026 | (50,210,1.5) | 8.46 | 5.18 | 2 | WINNER |
| 17 | Aug 2025-Feb 2026 | Feb-Mar 2026 | (50,210,1.5) | 10.35 | 0.00 | 2 | LOSER |
| 18 | Sep 2025-Mar 2026 | Mar 2026 | (50,210,1.5) | 3.05 | 0.00 | 0 | NO TRADE |

**Observations:** 11/18 OOS windows had trades; 3/11 profitable (27% win rate). IS champion is highly unstable — 6 different param sets selected across 18 windows with no dominant choice until windows 13-18 where (50,210,1.5) stabilizes. The IS PF values are inflated (many `inf` = 0 losing trades in IS) because 27-combo grid on 6-month IS window rarely finds a combo that loses. When IS window shrinks or the regime changes, IS PF drops to 1.4-1.8 range and OOS degrades accordingly.

**Fixed-params sweep (full 2-year dataset, rank1):**

| Combo | PF | Trades |
|-------|----|--------|
| (50,210,1.5) | 1.9219 | 33 |
| (50,190,1.5) | 1.5895 | 38 |
| (50,210,2.0) | 1.5322 | 33 |
| (50,200,1.5) | 1.4597 | 35 |
| (50,190,2.0) | 1.2735 | 38 |
| All 60-series | PF < 1.20 | — |
| All 70-series | PF < 1.00 | — |

Pattern: fast=50 dominates; fast=60 (MES champion) mostly fails; fast=70 consistently loses. The MES edge at (60,200) doesn't map to M2K.

---

### 2b. M2K Trend Rank2 — FAIL

**Commit:** `7cf5621`  
**Files:** `engine/backtest/run_m2k_trend_rank2.py`, `engine/data/gate_v2_verdicts/M2K_trend_rank2.json`

**Grid:** fast=[20,30,40,50] × slow=[80,120,160,200] × ATR=[1.0,1.5,2.0] = 48 combos  
**Hypothesis:** Rank1 failure was partly due to insufficient OOS trades per 1-month window (~1.3/month). Shorter MAs fire 3-8 crossovers/month, giving the statistical metrics something to measure. Also added ATR=1.0 as shorter trail may suit M2K's volatility profile.

**Gate v2 summary:**

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| pf_ci_lower | 0.5176 | ≥1.10 | FAIL |
| p_edge | 0.3571 | ≥0.95 | FAIL |
| mc_95th_dd | 2.01% | ≤7% ALT | PASS |
| dsr | 0.000 | ≥0.30 ALT | FAIL |
| wfo_consistency | WEAK | MODERATE/STRONG | FAIL |
| fixed_params_min_pf | 0.1853 | ≥1.20 | FAIL |
| fixed_params_mean_pf | 0.9124 | — | (reference) |
| fixed_params_max_pf | 1.7557 | — | (reference) |
| cost_survives_through | catastrophic | ≥realistic | PASS |
| n_core_passed | 2/4 | 4/4 | FAIL |
| n_alt_passed | 2/5 | 5/5 | FAIL |

**OOS window results (rank2) — full detail:**

| Win | IS period | OOS period | IS champion | IS PF | IS trades | OOS PF | OOS DD | OOS trades | Result |
|-----|-----------|------------|-------------|-------|-----------|--------|--------|------------|--------|
| 1 | Apr-Oct 2024 | Oct-Nov 2024 | (20,200,1.5) | 2.101 | 14 | inf | 0.01% | 1 | WINNER |
| 2 | May-Nov 2024 | Nov-Dec 2024 | (20,200,1.5) | 3.889 | 15 | 0.00 | 0.00% | 0 | NO TRADE |
| 3 | Jun-Dec 2024 | Dec 2024-Jan 2025 | (40,200,1.0) | 6.775 | 7 | 0.00 | 0.98% | 1 | LOSER |
| 4 | Jul 2024-Jan 2025 | Jan-Feb 2025 | (30,200,2.0) | 41.214 | 8 | 0.00 | 0.98% | 1 | LOSER |
| 5 | Aug 2024-Feb 2025 | Feb-Mar 2025 | **(50,80,1.5)** | 6.450 | 17 | **9.474** | 0.05% | 2 | **WINNER** |
| 6 | Sep 2024-Mar 2025 | Mar-Apr 2025 | **(50,80,1.5)** | 12.752 | 16 | **1.793** | 1.30% | 4 | **WINNER** |
| 7 | Oct 2024-Apr 2025 | Apr-May 2025 | (30,160,2.0) | 13.100 | 10 | 0.00 | 0.00% | 0 | NO TRADE |
| 8 | Nov 2024-May 2025 | May-Jun 2025 | (30,160,2.0) | 10.847 | 9 | 0.00 | 0.15% | 1 | LOSER |
| 9 | Dec 2024-Jun 2025 | Jun-Jul 2025 | (20,120,1.5) | 8.194 | 15 | **1.132** | 0.98% | 3 | **WINNER** |
| 10 | Jan-Jul 2025 | Jul-Aug 2025 | (20,120,1.0) | 6.148 | 15 | **2.015** | 0.99% | 3 | **WINNER** |
| 11 | Feb-Aug 2025 | Aug-Sep 2025 | (20,120,1.0) | 3.796 | 16 | 0.756 | 2.01% | 3 | LOSER |
| 12 | Mar-Sep 2025 | Sep-Oct 2025 | (30,200,1.5) | 3.552 | 11 | 0.860 | 1.63% | 3 | LOSER |
| 13 | Apr-Oct 2025 | Oct-Nov 2025 | (20,160,1.5) | 3.391 | 15 | 0.00 | 1.22% | 2 | LOSER |
| 14 | May-Nov 2025 | Nov-Dec 2025 | (50,200,1.0) | 4.308 | 11 | 0.00 | 1.02% | 1 | LOSER |
| 15 | Jun-Dec 2025 | Dec 2025-Jan 2026 | (20,200,1.5) | 5.292 | 13 | 0.00 | 0.00% | 0 | NO TRADE |
| 16 | Jul 2025-Jan 2026 | Jan-Feb 2026 | (20,200,1.5) | 4.503 | 11 | 0.291 | 2.03% | 4 | LOSER |
| 17 | Aug 2025-Feb 2026 | Feb-Mar 2026 | (50,200,1.0) | 8.930 | 10 | 0.00 | 1.93% | 2 | LOSER (Sharpe -368!) |
| 18 | Sep 2025-Mar 2026 | Mar 2026 | (50,200,1.5) | 2.698 | 11 | 0.00 | 0.00% | 0 | NO TRADE |

**Profitable windows: 4 of 14 active = 28.6% win rate.** The 4 winners (W5, W6, W9, W10) cluster in two adjacent-period pairs:
- W5+W6: OOS Feb-Apr 2025 with IS champion (50,80,1.5) — a short-fast, short-slow combo that behaved like a momentum strategy catching the post-election Russell 2000 rally that continued into early 2025
- W9+W10: OOS Jun-Aug 2025 with IS champion ~(20,120) — summer 2025 period

Both clusters share a property: consecutive OOS months using the same regime. Then regime shifts and losses resume. This is not a stable recurring pattern — it's 2 lucky streaks in 18 months.

**Fixed-params sweep (full 2-year dataset, rank2) — all 48 combos:**

| Fast | Slow | ATR | PF | Trades | Notes |
|------|------|-----|----|--------|-------|
| 20 | 80 | 1.0 | 0.7039 | 7 | |
| 20 | 80 | 1.5 | **1.3553** | 96 | Highest trade count |
| 20 | 80 | 2.0 | 0.8842 | 65 | |
| 20 | 120 | 1.0 | **1.2989** | 60 | |
| 20 | 120 | 1.5 | 0.5256 | 25 | |
| 20 | 120 | 2.0 | **1.2338** | 68 | |
| 20 | 160 | 1.0 | **1.2538** | 56 | |
| 20 | 160 | 1.5 | 0.4933 | 17 | |
| 20 | 160 | 2.0 | 0.3014 | 15 | |
| 20 | 200 | 1.0 | 0.9992 | 34 | |
| 20 | 200 | 1.5 | **1.7557** | 50 | Highest PF, champion |
| 20 | 200 | 2.0 | 1.1369 | 36 | Just below threshold |
| 30 | 80 | 1.0 | 0.9404 | 26 | |
| 30 | 80 | 1.5 | **1.3001** | 84 | |
| 30 | 80 | 2.0 | 0.6690 | 29 | |
| 30 | 120 | 1.0 | 0.8589 | 16 | |
| 30 | 120 | 1.5 | 0.7732 | 16 | |
| 30 | 120 | 2.0 | 0.6044 | 16 | |
| 30 | 160 | 1.0 | **1.2453** | 48 | |
| 30 | 160 | 1.5 | 0.9547 | 45 | |
| 30 | 160 | 2.0 | 0.9406 | 40 | |
| 30 | 200 | 1.0 | 1.0753 | 37 | |
| 30 | 200 | 1.5 | 1.1814 | 45 | |
| 30 | 200 | 2.0 | 0.8339 | 33 | |
| 40 | 80 | 1.0 | 0.8249 | 9 | |
| 40 | 80 | 1.5 | 0.6933 | 18 | |
| 40 | 80 | 2.0 | 0.6554 | 23 | |
| 40 | 120 | 1.0 | 0.6087 | 17 | |
| 40 | 120 | 1.5 | **1.3302** | 55 | |
| 40 | 120 | 2.0 | 1.0310 | 55 | |
| 40 | 160 | 1.0 | 0.2609 | 10 | |
| 40 | 160 | 1.5 | **0.1853** | 10 | **Worst combo — sets min_pf** |
| 40 | 160 | 2.0 | 0.8717 | 32 | |
| 40 | 200 | 1.0 | 1.0670 | 33 | |
| 40 | 200 | 1.5 | 0.8800 | 40 | |
| 40 | 200 | 2.0 | 0.8336 | 40 | |
| 50 | 80 | 1.0 | 0.8309 | 10 | |
| 50 | 80 | 1.5 | 1.0007 | 15 | Barely break-even |
| 50 | 80 | 2.0 | 0.7464 | 11 | |
| 50 | 120 | 1.0 | 0.9045 | 55 | |
| 50 | 120 | 1.5 | 0.5058 | 17 | |
| 50 | 120 | 2.0 | 0.7482 | 43 | |
| 50 | 160 | 1.0 | **1.2206** | 43 | |
| 50 | 160 | 1.5 | **1.2822** | 43 | |
| 50 | 160 | 2.0 | 0.9770 | 43 | |
| 50 | 200 | 1.0 | 0.7710 | 23 | |
| 50 | 200 | 1.5 | **1.4597** | 35 | |
| 50 | 200 | 2.0 | 0.7886 | 21 | |

**Combos with full-dataset PF ≥ 1.20:** 9 of 48 (18.75%)  
**Combos with full-dataset PF ≥ 1.00:** 15 of 48 (31.25%)  
**Mean PF across all 48:** 0.9124  
**Note on fixed_params_min_pf gate design:** The gate uses the MINIMUM across all grid combos. A wide exploratory grid that includes bad combos will always fail this metric even if the best cluster is profitable. This is a gate design issue flagged in the recommendations section.

**ATR=1.5 dominance across both ranks:** Of the 9 full-dataset passing combos, 7 use ATR=1.5. ATR=1.0 passes for (20,120) and (20,160). ATR=2.0 passes for (20,120,2.0) but is borderline. The signal says: ATR=1.5 is the preferred exit width for M2K — tight enough to lock in profit quickly, not so tight it whipsaws on routine M2K volatility.

**IS champion instability (critical diagnostic):** Across 18 windows, rank2 selected 9 distinct parameter combinations as IS champion. No combo was selected more than 3 times. Compare MES rank11: (60,200,2.0) was the dominant IS champion across the majority of its windows. Champion stability is a leading indicator of how well the edge will generalize — M2K has none.

---

### 2c. Fixed NameError in run_m2k_trend_rank1.py
Minor fix in the FAIL branch of `main()`: added `n_combos = len(FAST_PERIOD_VALUES) * len(SLOW_PERIOD_VALUES) * len(ATR_TRAIL_MULT_VALUES)` before its use at line 681. The exception occurred after the verdict was already written, so no data was lost. The fixed line is in the committed version.

---

## 3. Peer Session Activity (This Branch, Not This Session)

| Commit | Summary | Status |
|--------|---------|--------|
| 804462d | `fix(backtest): MNQ ORB — UTC->Eastern timezone conversion for RTH bar detection` | Committed |
| d20c249 | `fix(discord): remove --overwrite flag, fix Export-Channel stdout capture` | Committed |
| 603d4f8 | `feat(backtest): MNQ ORB rank1 — gate v2 WFO for opening range breakout` | Committed |

**MNQ ORB rank1 untracked verdict** — `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` — exists on disk, not yet committed. Full analysis in Section 5 below.

---

## 4. Files Created or Modified

| File | Commit | Change |
|------|--------|--------|
| `engine/backtest/run_m2k_trend_rank1.py` | f9bb6eb | NEW — M2K trend rank1 WFO runner; 27-combo grid |
| `engine/data/gate_v2_verdicts/M2K_trend_rank1.json` | f9bb6eb | NEW — FAIL verdict, full window records |
| `engine/backtest/run_m2k_trend_rank2.py` | 7cf5621 | NEW — M2K trend rank2 WFO runner; 48-combo grid |
| `engine/data/gate_v2_verdicts/M2K_trend_rank2.json` | 7cf5621 | NEW — FAIL verdict, full window records |
| `docs/session-logs/HANDOFF_2026-05-06-wfo-sweeps-4.md` | 7cf5621 | NEW — this file |
| `engine/logs/m2k_trend_rank1_full.log` | NOT COMMITTED | gitignored; full rank1 sweep output |
| `engine/logs/m2k_trend_rank2_full.log` | NOT COMMITTED | gitignored; full rank2 sweep output |
| `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` | UNTRACKED | peer session artifact; needs commit |
| `engine/backtest/run_mnq_orb_rank1.py` | UNTRACKED | peer session modification; needs review + commit |

---

## 5. MNQ ORB Rank1 — Deep Analysis (Peer Session Verdict)

**Source:** `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` (untracked, read this session)  
**Verdict:** FAIL — 0/9 criteria passed (complete whiteout)

**Gate v2 summary:**

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| pf_ci_lower | 0.6186 | ≥1.10 | FAIL |
| p_edge | 0.1765 | ≥0.95 | FAIL |
| mc_95th_dd | **28.15%** | ≤5% core / ≤7% ALT | FAIL (4x worse than ALT ceiling) |
| dsr | 0.000 | ≥0.10 | FAIL |
| wfo_consistency | WEAK | MODERATE/STRONG | FAIL |
| fixed_params_min_pf | 0.7080 | ≥1.20 | FAIL |
| fixed_params_mean_pf | 0.7364 | — | (reference) |
| fixed_params_max_pf | 0.7680 | — | (reference) |
| cost_survives_through | **none** | ≥realistic | FAIL |
| n_core_passed | 0/4 | 4/4 | FAIL |
| n_alt_passed | 0/5 | 5/5 | FAIL |

**This is a categorically different failure from M2K trend.** Key red flags:

1. **All 16 combos have full-dataset PF < 0.80.** The maximum is 0.768. This means on the full 2-year dataset, every parameterization of this ORB strategy loses money — not just in OOS windows but in aggregate. The IS performance is also below 1.0 for most windows (IS PF max ~0.92). When you can't find IS profitability, you're not dealing with overfitting — the strategy's basic premise is wrong for this asset/timeframe.

2. **353 total OOS trades.** This isn't a signal scarcity problem (compare: MCL trend got 0 OOS trades, M2K rank1 got 15). With 353 trades the statistics are meaningful: the strategy is losing, not randomly noisy.

3. **mc_95th_dd = 28.15%.** A 28% worst-case drawdown on a $10K account is $2,800. This isn't a small overshoot; it's a structural risk problem indicating the ORB entries are often chasing post-breakout mean reversions on NQ.

4. **Cost sweep: even at optimistic (0.31 commission, 1-tick slippage) PF = 0.778 — below 1.0.** The strategy loses before accounting for realistic transaction costs. Reducing costs further doesn't help.

5. **Grid parameter insensitivity:** All 16 combos cluster between PF 0.708 and 0.768. The `min_or_range_pct` filter (0.0005 to 0.0015 = 0.05% to 0.15% of price) and the `volume_filter` and `regime_filter` flags produce negligible PF variance. This means these filters aren't providing any selection differentiation — the breakout definition itself is what's wrong.

**OOS window analysis — MNQ ORB:**

| Win | OOS period | IS PF | OOS PF | OOS DD | OOS trades | Result |
|-----|------------|-------|--------|--------|------------|--------|
| 1 | Oct-Nov 2024 | 0.923 | 0.688 | 7.57% | 22 | LOSER |
| 2 | Nov-Dec 2024 | 0.816 | 0.687 | 14.63% | 19 | LOSER |
| 3 | Dec 2024-Jan 2025 | 0.785 | 0.750 | 8.53% | 21 | LOSER |
| 4 | Jan-Feb 2025 | 0.728 | **1.677** | 5.30% | 24 | **WINNER** |
| 5 | Feb-Mar 2025 | 0.744 | 0.587 | **28.85%** | 21 | LOSER (worst DD) |
| 6 | Mar-Apr 2025 | 0.850 | 0.895 | 21.32% | 23 | LOSER (near-miss) |
| 7 | Apr-May 2025 | 0.914 | 0.755 | 15.20% | 23 | LOSER |
| 8 | May-Jun 2025 | 0.915 | 0.258 | **28.03%** | 25 | LOSER (catastrophic) |
| 9 | Jun-Jul 2025 | 0.793 | 0.653 | 8.16% | 17 | LOSER |
| 10 | Jul-Aug 2025 | 0.781 | 0.634 | 10.79% | 19 | LOSER |
| 11 | Aug-Sep 2025 | 0.698 | 0.481 | 13.69% | 20 | LOSER |
| 12 | Sep-Oct 2025 | 0.660 | **1.184** | 5.99% | 24 | **WINNER** |
| 13 | Oct-Nov 2025 | 0.632 | 0.593 | 23.40% | 23 | LOSER |
| 14 | Nov-Dec 2025 | 0.592 | 0.404 | 10.18% | 17 | LOSER |
| 15 | Dec 2025-Jan 2026 | 0.679 | 0.466 | 9.03% | 14 | LOSER |
| 16 | Jan-Feb 2026 | 0.654 | 0.776 | 13.14% | 20 | LOSER |
| 17 | Feb-Mar 2026 | 0.684 | **1.085** | 9.98% | 19 | **WINNER (barely)** |
| 18 | Mar 2026 | 0.773 | **99.0** | 0.00% | 2 | WINNER (2 trades, too sparse) |

Only 3 of 17 active windows are profitable (W4, W12, W17), plus W18 with just 2 trades. The IS PF trend is notable: it **monotonically decreases** from W1=0.923 through W14=0.592 then partially recovers to W18=0.773. This suggests the specific ORB parameters that historically worked are decaying over time — not just bad in OOS, but increasingly bad in IS. The ORB signal as parameterized is getting worse over the data period.

**Root cause hypothesis for MNQ ORB failure:**

The `run_mnq_orb_rank1.py` implementation (peer session) defines the opening range using `min_or_range_pct` (a percentage of price). On NQ at ~20,000 points, 0.0005 × 20000 = 10 pts minimum OR width, 0.0015 = 30 pts. These are very small; typical ORB strategies use time-based definitions (first 15/30/60 min after RTH open). The percentage-based OR filter may be selecting entries during low-volatility fakeout periods rather than true breakouts. Additionally, the UTC→Eastern timezone bug (fixed in commit 804462d) may have corrupted earlier test runs, though the final verdict uses the fixed code.

**The MNQ ORB rank2 redesign must change the breakout definition fundamentally** — consider time-based OR (first 30 min bar), add direction bias filter (long only above prior-day close, short only below), add ATR-based minimum OR width, and significantly tighten the MC drawdown target.

---

## 6. Cross-Asset Strategy Family Status

### SMA Trend Following — Full Landscape

| Symbol | Best Rank | Verdict | Key Metric | Notes |
|--------|-----------|---------|------------|-------|
| MES | rank11 | **PASS** (ALT) | dsr=1.0, wfo=STRONG, mc_dd=0.81% | Champion: (60,200,2.0); expires 2026-06-05 |
| MNQ | rank1-2 | PARKED | 0 OOS trades both ranks | SMA crossover too infrequent on NQ 1h |
| MCL | hyp A-E | PARKED | 0 OOS trades (daily) | Crude oil: fundamentals-driven reversals, SMA crossovers too infrequent |
| M2K | rank1-2 | PARKED | wfo=WEAK, dsr=0.0 | Russell 2000 chop 2024-2026; MES edge doesn't transfer |
| MGC | not started | — | — | Natural next candidate after M2K parked |

### Opening Range Breakout — Full Landscape

| Symbol | Best Rank | Verdict | Key Metric | Notes |
|--------|-----------|---------|------------|-------|
| MNQ | rank1 | FAIL | PF=0.708-0.768, mc_dd=28.15% | Implementation may need complete redesign |
| MES | not started | — | — | MES already covered by trend; ORB would be additive |
| M2K | not started | — | — | ORB is the recommended next M2K hypothesis |
| MGC | not started | — | — | Gold ORB has literature support |

### Breakout (Non-ORB) — Full Landscape

| Symbol | Best Rank | Verdict | Notes |
|--------|-----------|---------|-------|
| MNQ | rank1-7 | PARKED | 7 hypotheses exhausted; non-stationarity confirmed |

---

## 7. Structural Diagnosis — Why M2K Trend Fails Where MES Passes

This is the most important analytical finding of this WFO session. Understanding why the MES edge exists but doesn't transfer to M2K informs which hypotheses to test next.

**MES (S&P 500 micro) — why it works:**
The S&P 500 in 2024-2026 was driven by a concentrated AI/mega-cap technology narrative. The top 10 stocks in the index (NVDA, AAPL, MSFT, META, AMZN, GOOGL) accounted for 35%+ of SPX weight. When these companies trend, the entire index trends with low noise. SMA(60,200) crossovers on a 1h bar catch these multi-month trends and exit with minimal drawdown because the trend tends to be self-reinforcing.

**M2K (Russell 2000 micro) — why it fails:**
Russell 2000 contains 2,000 small-cap stocks with higher sector diversity and higher sensitivity to interest rates, credit conditions, and domestic economic news. In 2024-2026:
- The post-election "small-cap rotation" thesis generated a brief rally (late 2024, caught by W5/W6)
- High-for-longer interest rates hurt small-cap companies disproportionately (heavily floating-rate debt)
- The index spent extended periods range-bound or counter-trend relative to SPX
- When it did trend, the trends were shorter-duration and more frequently interrupted by macro news

The result: M2K generates ~16-33 SMA crossovers/year on the best 1h params vs ~6-10 for MES. More crossovers = more chances to enter in choppy conditions = lower per-trade win rate. And the crossovers that do work are regime-specific (works during clear risk-on/risk-off pivots) not persistent across all market conditions.

**Implication for future M2K hypotheses:** ORB is well-motivated because it doesn't rely on multi-month trends. It exploits the overnight information release into the RTH open — a structural feature of futures markets that exists regardless of trend regime. M2K's higher volatility relative to MES may actually be an advantage for ORB (larger range = larger breakout = easier to identify true directional moves).

---

## 8. Framework and Code Improvement Recommendations

These are issues discovered during this session that should be addressed to improve future sweep efficiency and verdict quality. Not urgent for trading but important for research velocity.

### 8a. `fixed_params_min_pf` gate uses MINIMUM — too punishing for wide grids

**Problem:** The gate requires `min(PF across all combos) ≥ 1.20`. When exploring a wide 48-combo grid designed for discovery (not exploitation), some combos will be structurally bad. The worst combo (40,160,1.5) with PF=0.1853 fails this metric even though 9 of 48 combos exceed 1.20 on the full dataset.

**Recommendation:** Add a companion metric `n_combos_pf_gt_1`: count of combos with full-dataset PF > 1.0. If the best combos form a coherent cluster (e.g., 9/48 passing, clustered around a parameter region), that's valuable signal even if the grid-wide minimum is poor. Consider changing the ALT gate criterion to `fixed_params_n_passing ≥ 3` or `fixed_params_median_pf ≥ 1.10` for exploratory ranks; reserve `min_pf ≥ 1.20` for exploitation ranks (rank2+ with tight grids).

**Where to change:** `engine/backtest/deflated_sharpe.py` or wherever gate v2 is evaluated; also the WFO runner template logic.

### 8b. IS PF early-abort: when max IS PF < 1.0 across all combos, abort sweep

**Problem:** MNQ ORB rank1 ran 18 windows × 16 combos despite the fact that window 1's best IS PF was 0.923. By window 2 it was 0.816. A sweep where IS PF never breaks 1.0 cannot produce valid OOS results — there's no edge to evaluate. The entire 353 OOS trades were generated from a strategy that couldn't even be profitable in-sample.

**Recommendation:** After completing IS grid search for each window, check if `best_is_pf < 0.95`. If every combo in the IS window has PF < 0.95 for 3+ consecutive windows, print an early-abort warning and optionally stop the sweep. This would save significant compute time (each ORB window with 16 combos × ~1,000 bars takes several seconds).

**Where to implement:** `_best_is_params()` function in WFO runner; add `if best_pf < IS_PF_ABORT_THRESHOLD: abort_count += 1; if abort_count >= 3: return early`.

### 8c. Print IS champion stability diagnostics at end of WFO loop

**Problem:** IS champion instability is a strong predictor of OOS failure but is currently invisible in the summary output. You have to manually count how many different champions appeared across windows.

**Recommendation:** After the WFO loop, compute and print:
```
IS champion stability: 3 distinct combos across 18 windows (dominant: (50,210,1.5) ×6)
```
Add `champion_stability_n_distinct` and `champion_mode_fraction` fields to the verdict JSON.

### 8d. Sharpe anomaly detection

**Problem:** Window 10 rank1 produced OOS Sharpe = -1141.20 and Window 17 rank2 produced -368.10. These are numerical artifacts from 2 losing trades with very small standard deviation of returns (near-zero variance denominator). The extreme values pollute the DSR calculation.

**Recommendation:** In `_compute_gate_v2()`, clip OOS Sharpe values to `[-50, 50]` before computing mean Sharpe for DSR input. Values outside that range are artifacts not signal. Add a warning print when clipping occurs.

### 8e. Gate v2 verdict JSON: add `n_combos_full_pf_gt_1` field

For future analysis, the verdict JSON should include a pre-computed count of how many grid combos had full-dataset PF > 1.0, > 1.2, and > 1.5. This lets downstream analysis quickly identify "cluster quality" without re-reading the full combo_results array.

---

## 9. Key Decisions Made

1. **M2K rank2 grid: shorter MAs (20-50 × 80-200) instead of tight grid around rank1 best (50,210).** Rationale: rank1 failure was structural — insufficient OOS trades per window (~1.3/month), not parameter misspecification. Shorter MAs fire 3-8 crossovers/month and give the statistical metrics (p_edge, DSR) real data to work with. Result: OOS trades improved from 15 to 31, but win rate stayed WEAK.

2. **ATR=[1.0,1.5,2.0] for rank2, adding 1.0.** Lower ATR trail keeps more M2K trades alive longer; on a more volatile asset, a tighter trail that exits quickly might outperform slow-exit SMA strategies that give back gains. Result: ATR=1.5 dominated the passing combos — confirms that 1.5 is the preferred exit width for M2K.

3. **M2K uses risk-based sizing, not fixed_contracts=1.** Unlike MCL daily ($10K × 1% = $100 budget vs $225-750/contract stop → 0 contracts), M2K 1h ATR is small relative to $50K capital. $50K × 1% = $500 budget, M2K 1h ATR ≈ $10-25/contract → floor(500/10) = 50 contracts minimum. Risk-based sizing works correctly here.

4. **M2K CAPITAL=$50,000 (ALT path).** Required because ALT gate (dsr≥0.30, wfo in MODERATE/STRONG, fixed_params≥1.20) is only available for $50K+ accounts per jarvis-trader rules.

5. **M2K trend family PARKED after 2 ranks.** Decision threshold: 2 ranks with fundamentally different parameter spaces (tight MES-derived vs wide short-period exploration) both failing with similar structural characteristics (IS champion instability, WEAK wfo, dsr=0.0) is sufficient evidence that the asset/methodology combination lacks edge in this data period. Unlike MNQ trend (0 OOS trades = structural impossibility), M2K trend has signal — it's just insufficient for gate v2.

6. **MNQ ORB rank2 needs complete redesign.** Rank1 shows all-combos PF < 0.78, cost_survives_through=none, mc_dd=28%. This isn't a "tighten the grid" failure — the opening range definition and entry logic need rethinking.

---

## 10. In-Progress Work

None from this session. All commits are clean.

**Peer session artifacts requiring action:**
- `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` — untracked, should be committed
- `engine/backtest/run_mnq_orb_rank1.py` — modified, should be reviewed and staged
- Suggested commit message: `feat(wfo): MNQ ORB rank1 FAIL — opening range parameterization needs redesign`

---

## 11. Blockers

| Blocker | Type | Required Action |
|---------|------|----------------|
| Phase 0 T2-T15 rotation | Amo-gated | 1Password manual rotation for 14 services |
| Engine .env update | Amo-gated | After Phase 0 rotation completes |
| MNQ ORB rank2 implementation | Design decision | Need to decide on new ORB definition before coding |
| M2K ORB — no implementation exists | Normal | Build `run_m2k_orb_rank1.py` |
| MES rank11 expiry | Time-sensitive (30 days) | Refresh by 2026-06-05 |

---

## 12. TODO List

### Priority 1 — Immediate / No Blockers

- [ ] Commit peer session MNQ ORB rank1 artifacts: `run_mnq_orb_rank1.py` + `MNQ_orb_rank1.json`
- [ ] Design MNQ ORB rank2: time-based OR definition (first 30-min bar), direction bias, ATR-based minimum OR size
- [ ] Build `run_m2k_orb_rank1.py` — M2K ORB rank1 baseline
  - Grid suggestions: or_minutes=[15,30,60], atr_mult=[0.5,1.0,1.5], direction=[long-only, both]
  - Similar structure to MNQ ORB runner but adapted for M2K contract specs
- [ ] Consider MGC (Micro Gold) as next SMA trend candidate — gold has strong long-term trend character; better candidate than M2K

### Priority 2 — Time-Sensitive (30 days)

- [ ] MES rank11 refresh — rerun `engine/backtest/run_mes_trend_rank11.py` before 2026-06-05
  - Current champion: (60,200,2.0), verdict expires 2026-06-05T02:39Z
  - Data range needs extending to 2026-04+ (current cache ends 2026-03-27)
  - If metrics hold (dsr≥0.9, wfo=STRONG), write new verdict with 30-day extension

### Priority 3 — Amo-Gated (Need Manual Action)

- [ ] Phase 0 rotation T2-T15: 14 services (OpenAI, Azure, Paradigm, Google API ×2, Render, SMTP ×3, Firecrawl, GitHub PAT, Service15 + web_admin)
- [ ] D-drive YELLOW items: confirm deletion of iCloud .Trash (~7GB), WindowsImageBackup (~23GB), GoPro (~17.9GB)
- [ ] Engine .env update with rotated credentials after Phase 0 completes
- [ ] career-ops: archive stale Evaluated entries (36+ apps past 14-day threshold)

### Framework Improvements (Low Priority, High Value)

- [ ] `fixed_params_min_pf` gate change: add `n_combos_pf_gt_1` companion field (Section 8a above)
- [ ] IS PF early-abort when grid-wide IS PF < 0.95 for 3+ consecutive windows (Section 8b)
- [ ] IS champion stability reporting: `n_distinct_champions`, `dominant_fraction` in verdict JSON (Section 8c)
- [ ] OOS Sharpe clipping to [-50, 50] before DSR computation (Section 8d)
- [ ] Verdict JSON: add `n_combos_full_pf_gt_1`, `n_combos_full_pf_gt_1_2`, `n_combos_full_pf_gt_1_5` (Section 8e)

---

## 13. Git State (at session close)

```
On branch feat/tradingview-mcp-gamma-kraken
Your branch is ahead of 'origin/feat/tradingview-mcp-gamma-kraken' by 5 commits.

Untracked files:
  engine/data/gate_v2_verdicts/MNQ_orb_rank1.json
  engine/backtest/run_mnq_orb_rank1.py
```

### git log --oneline -20
```
7cf5621 feat(wfo): M2K trend rank2 FAIL — M2K trend family parked (2 ranks exhausted)
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

---

## 14. Suggested Next Actions

**Action 1 (5 min):** Commit peer session MNQ ORB artifacts:
```bash
git add engine/backtest/run_mnq_orb_rank1.py engine/data/gate_v2_verdicts/MNQ_orb_rank1.json
git commit -m "feat(wfo): MNQ ORB rank1 FAIL — OR parameterization needs redesign; mc_dd=28%"
```

**Action 2 (research, 30-60 min):** Design MNQ ORB rank2 redesign. The current ORB implementation selects entries using a percentage-based OR filter which doesn't capture the structural opening range concept. Redesign options:
- **Time-based OR:** Define the OR as the high/low of the first N minutes after RTH open (e.g., first 30 min = first 2 bars on 15-min data or first 30 bars on 1-min). Entry when price breaks above OR high (long) or below OR low (short). 
- **ATR-based minimum OR width:** Only trade when OR range > X × ATR to avoid fakeout breakouts in low-vol opens.
- **Direction filter:** Long-only when opening above prior day's VWAP or prior day's close; short-only when opening below. Reduces adverse entries on gap-and-fade days.

**Action 3 (1-2h):** Build `run_m2k_orb_rank1.py`. M2K ORB is the leading remaining M2K hypothesis. Grid suggestion:
```python
OR_MINUTES = [15, 30, 60]           # opening range window
ATR_MULT_FOR_TARGET = [1.0, 2.0, 3.0]  # profit target as multiple of OR range
STOP_LOSS = "or_range"              # stop at other side of OR
DIRECTION = ["both", "with_trend"]  # both directions vs trend-filtered only
```

**Action 4 (30 min):** MGC (Micro Gold) SMA trend rank1. MGC has:
- Strong multi-month trending behavior historically
- $10/point multiplier, lower tick sensitivity than NQ/M2K
- Data cache exists: check `engine/backtest/cache/` for MGC_*_1h.csv
- Same runner structure as MES rank11 — low effort to adapt

Priority order: Action 1 (quick win) → Action 4 (MGC trend, low effort) → Action 2+3 (MNQ/M2K ORB redesign, higher research cost).
