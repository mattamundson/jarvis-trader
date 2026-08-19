# JARVIS Backtest Journal — LIVING DOCUMENT

> **Purpose:** one source of truth for every backtest, screen, sweep, and certification
> run in jarvis-trader — parameters, symbols, weights, data, verdicts, and the exact
> commands used. **Append after every run. Never overwrite or delete entries.**
> Machine-readable companion: `engine/data/gate_v2_verdicts/_journal.csv` (auto-updated
> by `python -m backtest.track_verdict_journal --include-archive`).

> ⚠️ **LOCATION NOTE (2026-08-17):** this file was twice destroyed in the main worktree by
> concurrent-session `git reset --hard origin/master` while untracked. It now lives on a
> branch and must be **committed**, not left untracked. Do not keep the only copy of a
> living document untracked in a shared worktree.

---

## How to append (STANDARD TEMPLATE)

```markdown
### YYYY-MM-DD — <short descriptor>
- **Harness/runner:** `backtest/iterate.py` | `backtest/run_mes_trend_rank11.py` | ...
- **Symbol / family:** MES trend | SPY sma12 | ...
- **Data:** `<cache file>` | rows / range
- **Parameters tested:** fast=..., slow=..., atr=..., min_rv=..., vix_min/max=..., vix_regime_block=...
- **Weights/sizing:** fixed_contracts=N | risk_per_trade=... | capital=... | commission=... | slippage=... ticks
- **MC:** resamples=..., seed=...
- **Results (best rows):** table of combo | trades | PF | Sharpe | p_edge | DD% | verdict
- **Verdict file(s) written:** `...`
- **Command used:** (exact)
- **Notes / what this killed or promoted:**
```

---

## Current certified state (do not re-test these as unknowns)

> ⚠️ **2026-08-17 AUDIT WARNING — every Sharpe recorded before PR #714 is inflated ~3.8x**
> (`ANNUALIZATION_TRADES_PER_YEAR=252` applied to per-trade returns). Convert with
> `honest = reported * sqrt(actual_trades_per_year / 252)`. PR #714 fixes this at source.
> DSR values deflate for only the single runner's grid size, not the true campaign trial
> count — **PASS verdicts below are UNCONFIRMED pending re-deflation.**

| Symbol | Family / params | Verdict | Evidence |
|---|---|---|---|
| MES | SMA trend, grid [50,55,60]×[200]×[2.0] | **PASS (core) — ⚠️ AUDIT-DISPUTED** | 82 windows, pf_ci 1.27, p_edge 0.997, DSR 0.986 **@ n_trials=3 only** |
| MES | SMA trend champion 50/200/2.0 | PASS (prior deep) — ⚠️ **−0.26% CAGR at fixed params** | 2026-08-16, pf_ci 1.14, DSR 0.97 |
| MES | trend rv_filter (min_rv 9%) | FAIL | filter degrades edge 0.992→0.551 |
| MES | donchian / mean_reversion / ORB / calendar | FAIL | deep data, all families |
| MES | TPV (EMA trend-pullback) | FAIL | 0/54 combos; best PF 0.83 |
| MES | MRB (guarded mean-reversion) | **FAIL — dead on sample** | honest Sharpe 0.246 (22 tr) / 0.309 VIX-gated (16 tr) |
| MES | ODF (overnight drift) | **FAIL — confirmed VIX-gated** | ungated PF 0.93; ≤65th pctile PF 0.89 (worse) |
| MGC | trend_rank4 (any sizing) | FAIL | ATR sizing = artifact; fixed_contracts = no edge |
| SPY/QQQ | options vertical on SMA-trend (10/40/2.0, 8/40/2.5) | FAIL | deep 2026-08-18: overlay does NOT rescue shares edge (26/27 OOS, pf_ci 1.06/0.56, 38.9% WR, ~$0 PnL) |
| M2K | all families | FAIL | prior |
| MNQ / MCL | halted, DO_NOT_TRADE | — | never re-test |

---

## Run history

### 2026-08-17 — MES 15m screen: higher frequency does NOT rescue the edge

First use of the 5y continuous 15m cache (previously untouched). Motivation: the 1h
campaign made only 17.6 trades/yr, too few for Sharpe to be informative. Hypothesis:
a finer timeframe yields enough trades to measure edge properly, and possibly a real
intraday edge.

- **Harness:** `backtest/iterate.py --cache <15m file> --grid-json grid_15m.json --mc-resamples 1000`
- **Data:** `MES_2021-08-01_2026-07-30_15m_cont.csv` — 118,027 bars, 4.99y, 23,635 bars/yr.
  Integrity clean: 0 dupes / 0 OHLC violations / 0 NaNs / 0 zero-vol / 8 holiday gaps.
- **Grid:** fast [50,100,200] × slow [200,400,800] × atr [2.0,2.5] = 18 points, of which
  **16 are meaningful**: `fast=200/slow=200` (2 points, both atr values) is degenerate —
  fast == slow can never cross, so both returned 0 trades. Grid-design error on my part;
  it wasted 2 runs but did not affect the conclusion. Periods scaled ~4x vs the 1h grid to
  hold lookback roughly constant in wall-clock terms.
- **Weights:** risk_per_trade=0.01, capital $50k, commission 0.62, slippage 2 ticks
- **Sharpe below is HONEST** (post-PR #714, annualized by observed trade frequency)

| combo | trades | t/yr | PF | p_edge | honest Sharpe | CAGR% | DD% |
|---|---|---|---|---|---|---|---|
| 200/800/2.0 | 41 | 8.2 | 1.2059 | 0.689 | **0.2217** | 0.61 | 5.72 |
| 50/400/2.5 | 46 | 9.2 | 1.1681 | 0.663 | 0.1794 | 0.46 | 5.18 |
| 100/800/2.0 | 51 | 10.2 | 1.1381 | 0.649 | 0.1707 | 0.45 | 5.80 |
| 50/800/2.5 | 42 | 8.4 | 1.1704 | 0.635 | 0.1764 | 0.39 | 5.15 |
| 100/400/2.5 | 67 | 13.4 | 1.1067 | 0.634 | 0.1552 | 0.54 | 5.20 |
| *1h 55/200/2.0 (baseline)* | *128* | *17.6* | *1.3858* | *0.923* | ***0.5516*** | *1.90* | *4.37* |

**VERDICT: the 15m hypothesis is FALSIFIED, and the falsification is clean.**

1. **Frequency went DOWN, not up.** Best 15m combos trade 8–13/yr vs the 1h champion's
   17.6/yr. Scaling MA periods to hold lookback constant means the signal fires no more
   often; the finer bars only tighten the ATR trail, which exits sooner and *reduces*
   trade count. The premise "more bars ⇒ more trades ⇒ measurable Sharpe" was wrong.
2. **Every metric is worse.** Best 15m honest Sharpe 0.22 vs 0.55 on 1h; best CAGR 0.61%
   vs 1.90%; drawdowns are larger (5.1–5.8% vs 4.37%).
3. **Costs bite as predicted.** Median 15m bar range is 19 ticks vs 40 on 1h, so the
   ~3-tick round trip is 16% of a bar instead of 7%. The scope note flagged this and the
   screen confirms it.

**Nothing promoted.** The certified 1h SMA-trend family remains the only MES edge, and it
is still economically thin (1.90% CAGR at best, and the *deployed* 50/200/2.0 is −0.26%).

**Do NOT re-run 5m on this hypothesis.** The cost hurdle there is 27% of a median bar —
strictly worse on the axis that already failed. A 5m attempt would need a genuinely
different strategy family (microstructure//order-flow), not a rescaled trend system.

### 2026-08-17 — DSR campaign trial accounting (`backtest/campaign_trials.py`)

Runners deflate DSR using their OWN grid size — `run_mes_trend_rank11.py` passes
`n_grid_combos = 3`. A campaign against one cache spans far more trials.

Measured on the real 55/200/2.0 series (128 trades, empirical DSR, 2000 permutations):

| n_trials | DSR | CORE ≥0.1 | ALT ≥0.3 |
|---|---|---|---|
| 3 (as certified) | 0.8000 | PASS | PASS |
| 9 | 0.5210 | PASS | PASS |
| 27 | 0.1430 | PASS | **FAIL** |
| 54 | 0.0165 | **FAIL** | FAIL |
| 82 | 0.0020 | FAIL | FAIL |
| 150 | 0.0000 | FAIL | FAIL |

`count_journaled_trials("MES")` currently returns **9** — and that is only a lower bound
(journaled verdicts, not screening combos). CORE breaks at 54, ALT at 27.

**Deliberately NON-BREAKING:** no verdict is altered. Flipping a live PASS to FAIL is a
trading-authorization decision for Amo, not a library default. The module exposes
`dsr_campaign_diagnostic()` so a verdict can carry proof of its own selection-bias
exposure at read time.


### 2026-08-17 — ⚠️ INDEPENDENT VERIFICATION AUDIT

Re-derived every headline number from raw per-trade PnL using code independent of
`metrics.py` / `monte_carlo.py`. Trade-level evidence archived at
`C:/Users/mattm/Archive/2026/jarvis-audit-2026-08-17/_audit_trades_2026-08-17.json`.

**Reproducibility: PASS.** trades/PF/DD/p_edge reproduce bit-for-bit (85/0.9306,
128/1.3858, 7/0.0341; p_edge 0.9349 @20k resamples vs 0.923 @1k — within MC error;
seed-stable ±0.006). Cache clean: 0 dupes, 0 OHLC violations, 0 NaNs, 11 gaps all real
CME holidays. Prior session's *execution* was honest; the defects are in the metrics.

**1. SHARPE INFLATED ~3.8x — FIXED in PR #714.**
`metrics.py` applied `ANNUALIZATION_TRADES_PER_YEAR = 252` to PER-TRADE returns,
assuming ~252 trades/yr.

| config | engine | trades/yr | HONEST | inflation |
|---|---|---|---|---|
| 55/200/2.0 | 2.0878 | 17.60 | **0.5516** | 3.78x |
| 50/200/2.0 (live champion) | −0.4621 | 11.68 | −0.0995 | 4.64x |
| 55/200/2.2 | −27.8513 | 0.96 | −1.7207 | 16.18x |
| MRB best | 2.2458 | 3.02 | **0.2460** | 9.13x |

Worse the fewer trades a strategy makes. **No MES config has ever had a true Sharpe > 1;
the "Sharpe > 2" brief was never met.** PR #714 annualizes by observed frequency.

**2. NEGATIVE CAGR ON THE LIVE CHAMPION.** No return figure was ever computed in the
campaign. Over the full 7.27y at fixed params: 55/200/2.0 = +14.64% total = **+1.90%
CAGR**; **50/200/2.0 (deployed) = −1.86% total = −0.26% CAGR.** Gate-v2 PASS certifies
the WFO re-optimization procedure, NOT the fixed deployed parameters.

**3. DSR TRIAL-COUNT UNDER-DEFLATION (severity corrected — see below).**
`run_mes_trend_rank11.py:445` passes `n_grid_combos` (=3) as `n_trials`.

> ⚠️ **SELF-CORRECTION, same day.** My first pass tested the CLOSED-FORM
> `deflated_sharpe_ratio`, which is **not** what the gate calls. The gate calls
> `trade_level_dsr` → `deflated_sharpe_empirical` (MC-calibrated null, PR #595, merged
> 2026-08-04 after PR #594 proved the closed form degenerately rejects everything).
> The cliff I first reported (PASS@3 → 0.023@9 → 0.000@27) was measured on the WRONG
> function and **overstated the severity.**

Re-measured against the REAL gate function (55/200/2.0, n=128, 2000 permutations):

| n_trials | DSR | core (≥0.1) | alt (≥0.3) |
|---|---|---|---|
| 3 (as certified) | 0.8000 | PASS | PASS |
| 9 | 0.5210 | PASS | PASS |
| 27 | 0.1430 | PASS | **FAIL** |
| 54 | 0.0165 | **FAIL** | FAIL |
| 82+ | ≤0.0020 | FAIL | FAIL |

The empirical DSR degrades **gracefully**, not as a cliff — it is a real selection-bias
correction calibrated to the actual payoff shape. **The finding still holds
directionally:** trial count = one runner's grid (3), true campaign count is 100s, CORE
breaks between 27 and 54 trials, ALT breaks by 27. Re-deflation at the true count would
still flip the verdict — but honest headroom is ~27 trials, not ~9.
History: PR #594 (closed, audit-only) proved the closed-form defect; PR #595 (merged)
shipped the empirical fix. **Trial-count accounting was not part of that fix and is open.**

**4. CACHE FILENAME LIES.** `MES_2015-01-01_*` actually starts **2019-05-05** (7.27y, not
11.6y). Analyses quoted 7.3y correctly, so no result was corrupted.

**Concentration check (good news):** 55/200/2.0 is not one-trade luck — best trade is
4.6% of gross profit; PF holds 1.3220 with the best trade removed.

### 2026-08-17 — VIX cache fetched + VIX gates tested for the FIRST time
- **Blocker removed:** no VIX file existed on disk, so every "VIX-adjusted" result in the
  campaign was vacuous (gates silently no-op'd).
- **Fetched:** `backtest/cache/VIX_1990-01-02_2026-08-17_1d.csv` — 9,224 daily bars via
  yfinance `^VIX` (min 9.14 / max 82.69 COVID spike). NOTE: `free_daily_export --symbols
  ^VIX` fetches fine but the filename contract rejects `^`; written as `VIX`.
- **MRB with its DESIGNED gate (blocks Crisis+HighVol):** 22 → **16 trades**, PF 1.4672 →
  **1.7663**, honest Sharpe 0.246 → **0.309**. Gate helps directionally but 16 trades is
  *less* certifiable than 22. **MRB is dead on sample size, not gate config.** The prior
  plan to "relax a gate to reach 60+ trades" would relax the only thing helping.
- **ODF with its DESIGNED ≤65th pctile gate:** PF 0.9266 → **0.8859 (WORSE)**, honest
  Sharpe −0.113 → **−0.168**. The journaled "FAIL — no drift edge" verdict **survives**
  the gated retest. (My earlier criticism that ODF was "killed on a weaker version of
  itself" was wrong — retracted.)
- **ODF ≤50th pctile (exploratory):** PF **1.1754**, +$775.94, DD 3.68%, 700 traded days,
  honest Sharpe **0.204**. Only positive-PF ODF variant found — deep-calm-only drift.
  NOT a candidate (Sharpe 0.2), but the one honest signal in the composite set, with a
  real sample (700 days vs MRB's 16).

### 2026-08-17 — Composite strategies v1: TPV / MRB / ODF (deep screens)
- **Harness:** `backtest/iterate.py --strategy tpv|mrb` + `run_mrb_grid.py` + `run_odf_screen.py`
- **Module:** `backtest/composite_strategies.py`
- **Data:** `MES_2015-01-01_2026-08-16_1h.csv`, 42,826 bars
- **Weights:** risk_per_trade=0.01, capital $50k, commission 0.62, slippage 2 ticks; MC 1000, seed 42
- **TPV:** 0/54 combos survive. Best fast=65 atr=2.5 → PF 0.83, 39 trades. **FAIL.**
- **MRB:** default 1:1 design silently rejected by the Backtester R:R≥1.2 gate (0 trades);
  fixed with stop 0.8×ATR (rr=1.25). Grid best bb=2.5 hold=6 atr=1.5 stop=1.0 → PF 1.47,
  22 trades. **Insufficient sample.**
- **ODF:** PF 0.93, win 28%, 1,269 traded days. **FAIL.**
- **Verdict:** none promoted.
- **Lesson (mechanical):** `backtester.py:1018` silently drops entries with R:R < 1.2.
  0 trades with no error usually means this, not a signal bug.

### 2026-08-17 — MES champion-neighborhood screen (iterate.py v1)
- **Data:** deep cache, 42,826 bars. Grid fast [45,50,55] × slow [200] × atr [1.8,2.0,2.2]
- **Best:** 55/200/2.0 → 128 trades, PF 1.386, p_edge 0.923, DD 4.37%
- **Output:** `backtest/results/iterate_mes_neighborhood_2026-08-17.json`
- **Notes:** Screening signal only — NOT a gate verdict.

### 2026-08-17 — MES WFO certification: fast=45/atr=1.8 candidate
- **Verdict: FAIL** — pf_ci 0.3975, p_edge 0.284, MC DD 10.72%, DSR 0.288, WFO WEAK
- **Notes:** Screening PF 1.294 did NOT survive walk-forward. Killed honestly.

### 2026-08-17 — MES rank11 WFO refresh (grid covers fast=55)
- **Verdict: PASS (core)** — pf_ci 1.2714, p_edge 0.9968, DSR 0.9861, MC DD 4.39%,
  WFO MODERATE, cost catastrophic, 69 OOS trades, **n_windows=82 verified in JSON**
- **IS-champion params:** fast=60 (WFO per-window optimizer preferred 60, not 55)
- ⚠️ See audit finding 3 — DSR deflated for 3 trials only.

### 2026-08-16 — Deep revalidation wave (all MES/MGC families)
- trend_rank11 PASS; rv_filter FAIL; donchian FAIL; mean_reversion FAIL; turn_of_month
  FAIL; pre_fomc INSUFFICIENT_SAMPLE; orb FAIL; MGC trend_rank4 FAIL.
- **Notes:** Established the deep-data standard. Only MES trend survives full history.

### 2026-08-18 — E3: MGC_trend_rank4 2829% DD anomaly — RESOLVED (sizing artifact, verdict corrected)
- **Harness/runner:** `engine/backtest/run_mgc_trend_rank4.py` (8-combo tight grid, gate v2)
- **Symbol / family:** MGC trend, rank 4
- **Data:** `MGC_2015-01-01_2026-08-16_1h.csv` | 40,575 rows | 2015-01-01 → 2026-08-14
  (price-sane: min 1042.10 / max 5587.00, 0 dupes / zeros / negatives / NaNs)
- **Parameters tested:** fast=[40,50] × slow=[80,120] × atr_trail=[1.5,2.0] (8 combos),
  train 6mo / test 2mo / step 1mo, min_rv=0.0
- **Weights/sizing:** **fixed_contracts=1 (equal-weight WFO basis)** — replaces the ATR
  `risk_per_trade=0.01` sizing that CAUSED the 2829% artifact (low-ATR gold → 2-13
  contracts in low-vol regimes → gap-stop amplification). capital=$50K,
  commission=0.85/ct, slippage=2.0 ticks
- **MC:** trade-level bootstrap (per `_gate_v2_trade_metrics`), n_grid=8
- **Results:** FAIL (via NONE) — pf_ci_lower=0.9263 (need ≥1.1), p_edge=0.9478 (need ≥0.95),
  mc_95th_dd=3.8855% (core ≤5 / alt ≤4 ✓), dsr=0.6314 (≥0.1 ✓ / ≥0.3 ✓), wfo=WEAK,
  fixed_params_min_pf=0.5104 (need ≥1.2), cost_survives=catastrophic (✓)
- **Window DD distribution:** 134 windows, 129 with trades, 345 OOS trades;
  max window DD 1.85%, p95 0.58%, **0/134 windows >100%** (was 7/134 in the ATR run)
- **Verdict file(s) written:** `engine/data/gate_v2_verdicts/MGC_trend_rank4.json`
  (production, replaced shallow-contaminated 23-window verdict — original archived to
  `engine/data/gate_v2_verdicts/archive/MGC_trend_rank4_shallow-contaminated-2026-08-18.json`)
- **Command used:** `env -u PYTHONPATH -u PYTHONHOME C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe engine/backtest/run_mgc_trend_rank4.py`
  (runner patched with `fixed_contracts=1` in throwaway worktree wt-mgc-fixedcontracts-e3)
- **Notes / what this killed or promoted:** Root cause CONFIRMED = ATR sizing artifact, NOT
  a cache defect (cache scan clean). Equal-weight sizing → sane 3.89% MC DD, but every gate
  fails on 345 OOS trades → **MGC trend_rank4 is genuinely dead**. ATR-sized paper profit
  (+$3,906) was a sizing artifact. MGC stays halted / DO_NOT_TRADE; no promote. Reproducible:
  two independent runs (run-10 crashed attempt + this one) produced byte-identical metrics.
  NOTE: 08-17 skill doc recorded p_edge=0.3984/dd=6.91%/361 trades from an earlier cache
  state; current cache (08-16) yields p_edge=0.9478/dd=3.89%/345 trades — verdict direction
  unchanged (FAIL).
  ⚠️ E7 CORRECTION (2026-08-18): the "cache scan clean" claim above covered price-sanity
  only (range/dupes/zeros). A temporal-completeness scan (`backtest/cache_completeness.py`,
  the engine's own data-trust gate) FAILS this file: `trustworthy=False`, 1,711 suspicious
  gaps incl. dozens of multi-day full-weekday holes (e.g. 2017-10-11→29 18d, 2022-10-07→24
  16d, 2015-10-08→22 14d, 2017-12-08→22 14d, 2017-08-11→23 12d). Both Databento pulls
  (08-04 + 08-16) share the holes → systematic pull defect, not local corruption. The E3
  run consumed this holed cache (E3 worktree had deleted the only clean 1h candidate,
  `MGC_2024-03-04_2026-07-24_1h.csv`, so `find_trustworthy_cache` fell back to the holed
  deep file). p_edge 0.9478 sits 0.002 under the 0.95 bar and has already proven
  cache-state-dependent (0.3984 vs 0.9478) → FAIL direction is probable but NOT
  promotion-grade trustworthy until re-run on a complete cache. See E7 section below.

### 2026-08-18 — E7: MGC deep-cache decision + candidate ideas logged
- **DECISION (a): MGC deep cache REQUIRES a Databento rebuild before ANY future MGC
  revalidation.** The canonical completeness gate (`python -m backtest.cache_completeness
  backtest/cache/MGC_2015-01-01_2026-08-16_1h.csv`) reports `trustworthy=False`,
  `suspicious_gaps=1711` — the 11.6y "deep" cache is holed across 2015-2023 (multi-day
  full-weekday holes; Oct-heavy pattern suggests pull-window/roll gaps in the Databento
  fetch, not exchange closures). `find_trustworthy_cache("MGC","_1h.csv")` rejects it and
  would pick `MGC_2024-03-04_2026-07-24_1h.csv` (2.4y, 0 full-day gaps) whenever it exists.
- **Why now:** no MGC revalidation is queued (FAIL family, no new hypothesis) → do NOT
  spend pull/backtest compute today. Rebuild is the PRECONDITION for t_041ebc0b GAP-A
  ("deep-run MGC_trend_rank4") and for any future MGC hypothesis. Rebuild card created:
  see E7 kanban follow-up.
- **Rebuild spec (for the follow-up task):** re-pull MGC 1h via Databento (DATABENTO_API_KEY
  present in engine/.env; adapter is documented-but-unexercised — verify response shape
  first), span 2015-01-01 → present, then require `cache_completeness` → 0 full-day gaps
  BEFORE any MGC gate-v2 run. Delete/quarantine holed 2015 files only after the new pull
  passes. Do NOT trust row-count/price-range checks alone — E3 and E5 both "validated" the
  holed cache that way.
- **CANDIDATE IDEAS (b) — logged for deep validation, EQUAL priority with futures per
  operating rules** (`docs/plans/2026-07-31-dashboard-autonomy-hardening-plan.md`: options
  and futures receive equal priority in roadmap and UI):
  1. **Equity options SPY/QQQ edge scans** — debit vertical spreads on the CERTIFIED
     SPY/QQQ SMA-trend signals (SPY PASS 10/40/2.0+2.5, QQQ PASS 8/40/2.5; gate-v2 ALT
     alignment per `run_spy_options_baseline.py` B6: ±5 strikes, 7-30 DTE, hold-to-expiry
     intrinsic, half-spread + 5bps). Currently scaffold-only.
  2. **SPY/QQQ variance-risk-premium harvest** — delta-hedged short premium
     (links `delta_hedged_short_straddle_vrp` card from the 07-02 edge scan; needs the
     options pipeline + strict tail sizing).
  3. **SPY/QQQ dealer-gamma regime** — DATA-GATED: needs a GEX feed (flagged in the 07-02
     scan; do not start until the feed decision lands).
  Structured cards written to `docs/research/edge-roadmap-candidates-2026-08-18.cards.jsonl`
  (funnel-schema compatible with `bookmark-edge-scan-2026-07-02.cards.jsonl`).

### 2026-08-18 — E7-FOLLOWUP: SPY/QQQ equity options deep validation (candidate 1 FAIL; candidates 2-3 gated)
- **Harness/runner:** `backtest/run_spy_qqq_options_vertical.py` (new gate-v2-wired driver,
  ALT battery) + `backtest/run_spy_options_baseline.py` (B6 Black-Scholes helpers).
- **Symbol / family:** SPY + QQQ `options_vertical_sma_trend` — debit bull-call verticals on the
  CERTIFIED SMA-trend entries (SPY fast=10/slow=40/atr=2.0, QQQ fast=8/slow=40/atr=2.5 — the same
  ENTRY_NOW events the shares strategy trades).
- **Data (deep-data standard — verified FIRST, before any compute):**
  `backtest/cache/SPY_2015-01-01_2026-08-17_1d.csv` + `QQQ_..._1d.csv` — 2,922 bars each,
  2015-01-02 → 2026-08-17. `backtest.cache_completeness.inspect_cache_file` →
  `trustworthy=True`, `suspicious_gaps=0` for BOTH. Independent NYSE cross-check (every missing
  weekday in each cache vs the closure calendar): all 110 missing weekdays per symbol are
  whitelist-covered holidays/early closes — **zero genuine holes**. `US_MARKET_HOLIDAYS` extended
  back to 2015 (verified 1:1 vs the NYSE reference calendar incl. 2018-12-05 Day of Mourning);
  evidence script `engine/e7f_verify_caches.py`. VIX: `engine/data/vix_daily.csv` (2,923 closes,
  2015-01-02 → 2026-08-17) for the IV proxy.
- **Parameters tested:** 30-delta long leg, 5-strike width, 30 DTE tenor, 1 spread/signal,
  IV proxy = max(20d realized vol, VIX/100 [SPY], 1.10×VIX/100 [QQQ]) — no historical IV surface
  exists, VIX is the documented point-in-time proxy; slippage half-spread (max $0.05, 1% of mid)
  + 5bps per leg entry-only; hold-to-expiry intrinsic settlement; $50K capital.
- **Weights/sizing:** 1 contract per signal, capital $50K, no leverage.
- **MC:** seeded (`_MC_SEED`) — deterministic; full re-runs reproduce bit-identical metrics.
- **Results (WFO 24mo train / 3mo test / 1mo step, 113 windows, unique OOS attribution):**

  | Symbol | params | trades | OOS | pf_ci_lower | p_edge | DSR | MC DD% | win_rate | total PnL | verdict |
  |---|---|---|---|---|---|---|---|---|---|---|
  | SPY | 10/40/2.0 | 36 | 26 | 1.0604 | 0.8972 | 0.884 | 0.02 | 38.9% | $7.73 | **FAIL** |
  | QQQ | 8/40/2.5 | 36 | 27 | 0.5554 | 0.7240 | 0.724 | 0.02 | 38.9% | $8.05 | **FAIL** |

  FAIL reasons: OOS trades 26/27 < 30 (both); pf_ci_lower 1.0604 / 0.5554 < 1.2 (both).
  WFO consistency WEAK both; QQQ stationarity inconsistent. Per-window median PF 0.0, mean PF
  0.53 (SPY) / 0.44 (QQQ).
- **Verdict file(s) written:** `engine/data/gate_v2_verdicts/SPY_options_vertical_sma_10_40_2.0.json`,
  `engine/data/gate_v2_verdicts/QQQ_options_vertical_sma_8_40_2.5.json` (gitignored runtime state,
  standard schema incl. `data_quality.cache_completeness`); trades CSVs in
  `engine/data/options_backtests/`; `_journal.csv` rows appended.
- **Command used:** `OPT_SYMBOL=SPY|QQQ env -u PYTHONPATH .venv/Scripts/python
  backtest/run_spy_qqq_options_vertical.py` (from engine/).
- **Notes / polarity finding:** the CERTIFIED shares edge does **NOT** survive the debit-vertical
  options overlay on deep data. Only ~36 entries in 11.6y (~3/yr) → 26-27 OOS trades, below the
  30-trade minimum even at best. Win rate 38.9% sits far below the ~55-60% breakeven a
  30-delta/5-wide debit spread needs to overcome theta bleed + half-spread slippage; total PnL
  $7.73 / $8.05 over 11.6y on $50K ≈ zero (frictions ~fully consume the signal). DSR (0.88/0.72)
  is misleadingly high — tiny PnL variance vs capital inflates it; PF + trade count are the binding
  gates. **Candidate 1 verdict: FAIL both symbols — NOT promoted, no paper/live routing
  (research-only).**
- **Candidate 2 (`spy_qqq_vrp_premium_harvest`): NOT RUN** — gated on candidate 1 PASS per task
  spec ("if candidate 1 passes, run candidate 2"); additionally still needs a real IV-history
  surface beyond the VIX proxy to be meaningfully testable. Status: `not_run`, Tier B.
- **Candidate 3 (`spy_qqq_dealer_gamma_regime`): DATA-GATED** — GEX feed decision pending; not
  started, per spec (record-only).

---

## Open gaps / queued work

| Item | Status |
|---|---|
| Re-deflate DSR at true campaign trial count | **DIAGNOSED, decision pending** — `campaign_trials.py` quantifies it (CORE breaks 54, ALT 27); no verdict flipped, awaiting Amo |
| Regenerate/annotate historical Sharpe after PR #714 | **OPEN** — 157-row journal CSV + archived verdicts still carry inflated values |
| **MES 15m higher-frequency hypothesis** | **CLOSED — FALSIFIED** 2026-08-17. Worse on every axis; do not retry |
| MES 5m | **DO NOT RETRY as a trend system** — 27% cost hurdle; needs a different family entirely |
| Full 54-combo MES 1h grid + VIX regimes | Now unblocked (VIX cache exists) |
| QQQ/AAPL/TSLA deep caches | QQQ 1d exists (2015-01-01_2026-08-17); AAPL/TSLA still missing — `free_daily_export.py` fetch needed |
| Equity 1h certification (live scanner cadence) | Queued — SPY trades live paper on a REJECTED verdict; QQQ/AAPL/TSLA on none |
| Options vertical-spread certification | **DONE 2026-08-18 — FAIL (both SPY & QQQ)** — deep gate-v2; overlay does not rescue the shares edge. See E7-FOLLOWUP entry + `run_spy_qqq_options_vertical.py` |
| **MGC deep cache rebuild (Databento 1h re-pull)** | **REQUIRED before any future MGC revalidation** — `MGC_2015-01-01_2026-08-16_1h.csv` fails the completeness gate (1,711 suspicious gaps; multi-day holes 2015-2023). See E7 2026-08-18 entry + kanban follow-up card |
| **Equity options SPY/QQQ edge scans** | **DONE 2026-08-18** — cand 1 `spy_qqq_vertical_spread_sma_trend` FAIL (deep gate-v2, both symbols); cand 2 VRP not_run (gated on cand 1 PASS + needs IV history); cand 3 dealer-gamma DATA-GATED on GEX feed. Cards updated in `docs/research/edge-roadmap-candidates-2026-08-18.cards.jsonl` |
