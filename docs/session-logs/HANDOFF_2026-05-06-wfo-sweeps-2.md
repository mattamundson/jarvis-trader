---
session: 2026-05-06 WFO Sweeps (Part 2 — continuation)
branch: feat/tradingview-mcp-gamma-kraken
head: 2d7378c
---

## Current State

- Engine: running port 8010 (plain uvicorn), health=ok, TV MCP healthy
- All committed, working tree has only `docs/session-logs/HANDOFF_2026-05-06-discord-pipeline-p2.md` modified (peer session file)
- MES rank11 PASS active — paper trading wired (fast=60/slow=200/atr=2.0, expires ~2026-06-05)
- MCL and MNQ: both in DO_NOT_TRADE_SYMBOLS pending gate v2 PASS

## Key Decisions Made

1. **MNQ trend family PARKED** — rank2 (fast=[20-30]/slow=[80-120]) confirmed same structural failure as rank1: best full-dataset combo (25,80,1.5) generates only 3 trades over 2 years. Signal too infrequent for 1h SMA crossover methodology. Both ranks committed to repo with FAIL verdicts. Park condition: 3 consecutive IS windows with IS_PF > 1.5 on any timeframe.

2. **MCL Hyp-D: near-miss, do NOT park** — pf_ci_lower=7.14 (way above 1.10), mc_dd=0.23%, wfo=STRONG, cost_robust=catastrophic. FAILS on: dsr=0.286 vs 0.30 (by 0.014), p_edge=0.75 vs 0.95 (only 4/18 OOS windows had trades), fixed_params_min_pf=0 (grid has genuine lossy combos). Root cause: 1-month OOS window too short for SMA(60,200) crossovers on 1h MCL.

3. **MCL Hyp-E direction: daily bars** — `MCL_2022-01-01_2026-03-28_1d.csv` exists in cache (4+ years). Daily SMA crossovers give more OOS trades/window, fix p_edge and DSR. This is the highest-probability next PASS candidate.

4. **gitignore extended** — added `!engine/data/gate_v2_verdicts/*_hyp_*.json` so hypothesis-named verdicts are kept alongside `*_rank*.json`.

## Commits This Session

| Hash | Message |
|---|---|
| 2d7378c | feat(wfo): MCL trend Hyp-D FAIL — DSR 0.286 just below 0.30 ALT floor (+ gitignore fix) |
| e6aa579 | feat(wfo): MNQ trend rank2 FAIL — signal too infrequent on 1h timeframe |
| 2b573bb | feat(backtest): add MNQ trend rank2 runner — shorter SMA periods |
| a56f177 | docs(session-logs): expand WFO sweeps handoff — deep analysis + recommendations |

## Blockers

- MCL Hyp-E not yet built or run. Runner needs: symbol=MCL, data=daily CSV, grid adjustment for daily bars (slower SMAs), `_RV_ANNUAL_FACTOR=252` instead of `252*24`.
- MES rank11 expires 2026-06-05 — needs refresh run before then.

## Files Created / Modified

- `engine/backtest/run_mnq_trend_rank2.py` — 729 lines, committed by peer session + confirmed
- `engine/data/gate_v2_verdicts/MNQ_trend_rank2.json` — FAIL verdict committed
- `engine/data/gate_v2_verdicts/MCL_trend_hyp_d.json` — FAIL near-miss, committed
- `.gitignore` — added `!*_hyp_*.json` exception
- `docs/session-logs/HANDOFF_2026-05-06-wfo-sweeps.md` — expanded from ~250 to ~700 lines

## TODO

**Priority 1 (autonomous, build + run):**
- Create `engine/backtest/run_mcl_hypothesis_e.py` — daily MCL SMA trend
  - Data: `MCL_2022-01-01_2026-03-28_1d.csv`
  - Grid: fast=[10,15,20], slow=[40,50,60], atr=[1.5,2.0,2.5], rv=[0.0,20.0]
    - Daily RV_ANNUAL_FACTOR=252 (not 252*24)
    - 3×3×3×2 = 54 combos
  - Output: `engine/data/gate_v2_verdicts/MCL_trend_hyp_e.json`
  - Key change from Hyp-D: `_RV_ANNUAL_FACTOR = 252` in the signal generator (daily bars)

**Priority 2 (time-sensitive):**
- MES rank11 refresh run before 2026-06-05

**Priority 3 (Amo-gated):**
- Phase 0 credential rotation (blocks cleanup, scan rerun, engine .env update)
- D-drive large items: iCloud .Trash ~7GB, WindowsImageBackup ~23GB, GoPro ~17.9GB

## Suggested Next Action

Build and run `run_mcl_hypothesis_e.py` with daily MCL data. The DSR near-miss (0.286 vs 0.30) with pf_ci=7.14 is the strongest signal in the pipeline after MES rank11. Daily bars should fix the OOS coverage gap.

**Critical implementation note for Hyp-E:** `generate_sma_trend_signals()` has `_RV_ANNUAL_FACTOR = 252 * 24` hardcoded for 1h bars. For daily bars, this must be `252`. The cleanest fix is to pass `rv_annual_factor` as a parameter to the signal generator, or override it in Hyp-E by patching the constant. Do not silently use the 1h factor on daily data — it would annualize RV at 6048x instead of 252x, making all bars appear extremely low-vol and the rv filter would disable itself.
