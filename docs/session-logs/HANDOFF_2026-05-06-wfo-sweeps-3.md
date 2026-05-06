---
session: 2026-05-06 WFO Sweeps (Part 3 — MCL Hyp-E completion)
branch: feat/tradingview-mcp-gamma-kraken
head: a9c57b2
---

## Current State

- Engine: port 8010 (plain uvicorn), health presumed ok (not restarted this session)
- All WFO work committed, working tree has peer-session modifications only
- MES rank11 PASS active — paper trading wired (fast=60/slow=200/atr=2.0, expires ~2026-06-05)
- MCL: **PARKED** — 5 hypotheses exhausted (A/B/C mean-rev, D/E trend)
- MNQ: **PARKED** — trend family (rank1+2 signal too infrequent), breakout family exhausted

## Key Decisions Made

1. **MCL Hyp-E FAIL — MCL trend family PARKED definitively**
   - Daily SMA(10-20, 40-60) fires only ~3 crossovers/year on crude oil
   - 1-month OOS window hit rate: ~15-25% → 0/43 windows had OOS trades
   - Root cause: grid overfitting picks IS params that happened to cross in the 6-month IS period,
     but those params are so infrequent they miss the next 1-month window entirely
   - fixed_params_min_pf=0 (many combos entirely unprofitable on full 4-year dataset)
   - Best full-dataset combo (20,40,2.5) = PF 2.55 but only 7 trades/4yr
   - Hyp-D was a near-miss (pf_ci=7.14, dsr=0.286 just below 0.30 ALT floor)
   - Hyp-E confirms the near-miss was a fluke of 4 lucky OOS windows, not replicable

2. **rv_annual_factor parameter added to generate_sma_trend_signals()**
   - Was `_RV_ANNUAL_FACTOR = 252*24` hardcoded for 1h bars
   - Added `rv_annual_factor: int | None = None` param; defaults to existing value (backward-compatible)
   - Hyp-E passes `rv_annual_factor=252` for daily bars
   - Without this fix: daily bars annualize RV using 6048x factor (way too high), making all
     daily bars appear low-vol and silently disabling the rv gate

3. **fixed_contracts=1 needed for daily MCL**
   - Daily MCL ATR ~$1.50-5.00/barrel; at trail=1.5x = $225-750/contract
   - Risk-based sizing at 1% of $10K = $100 budget → floor(100/225) = 0 contracts
   - All windows silently produced 0 trades before this fix
   - Lesson: any backtest on daily futures with small capital needs `fixed_contracts=1` override

## Commits This Session (Post-Compact)

| Hash | Message |
|---|---|
| a9c57b2 | feat(wfo): MCL trend Hyp-E FAIL — daily SMA crossovers too infrequent |
| 1ff578c | feat(backtest): add rv_annual_factor param to generate_sma_trend_signals |

## Files Created / Modified

- `engine/backtest/trend_signals.py` — rv_annual_factor parameter (backward-compatible)
- `engine/backtest/run_mcl_hypothesis_e.py` — NEW: daily MCL SMA trend runner
- `engine/data/gate_v2_verdicts/MCL_trend_hyp_e.json` — FAIL verdict; 0 OOS trades
- `engine/logs/mcl_trend_hyp_e_full.log` — full sweep output (not committed)

## Blockers / Notes

- Peer session also committed `MCL_trend_hyp_d_rank2.json` (5c53348) — a 3-month OOS window
  variant of Hyp-D. Different approach, same conclusion (FAIL). No conflict.
- MES rank11 refresh needed before 2026-06-05 (30 days remaining as of today)

## TODO

**Priority 1 (time-sensitive, ~30 days):**
- MES rank11 refresh: run `engine/backtest/run_mes_trend_rank11.py` (or equivalent)
  with updated data through current date; gate v2 verdict expires ~2026-06-05

**Priority 2 (Amo-gated):**
- Phase 0 rotation: T2-T15 (14 services pending)
- D-drive large items: iCloud .Trash ~7GB, WindowsImageBackup ~23GB, GoPro ~17.9GB
- Engine .env update with rotated credentials

## Suggested Next Action

MES rank11 refresh. Find the existing rank11 runner script, update data range to include
recent 2026 bars, run sweep, compare gate v2 metrics to current verdict
(pf_ci=2.156, dsr=1.0, wfo=STRONG, mc_dd=0.81%). If metrics hold, write new verdict
with extended expiry.
