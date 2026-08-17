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
- **Grid:** fast [50,100,200] × slow [200,400,800] × atr [2.0,2.5] (18 combos, periods
  scaled ~4x to keep comparable lookback in wall-clock terms)
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

---

## Open gaps / queued work

| Item | Status |
|---|---|
| Re-deflate DSR at true campaign trial count | **DIAGNOSED, decision pending** — `campaign_trials.py` quantifies it (CORE breaks 54, ALT 27); no verdict flipped, awaiting Amo |
| Regenerate/annotate historical Sharpe after PR #714 | **OPEN** — 157-row journal CSV + archived verdicts still carry inflated values |
| **MES 15m higher-frequency hypothesis** | **CLOSED — FALSIFIED** 2026-08-17. Worse on every axis; do not retry |
| MES 5m | **DO NOT RETRY as a trend system** — 27% cost hurdle; needs a different family entirely |
| Full 54-combo MES 1h grid + VIX regimes | Now unblocked (VIX cache exists) |
| QQQ/AAPL/TSLA deep caches | Missing — `free_daily_export.py` fetch needed |
| Equity 1h certification (live scanner cadence) | Queued — SPY trades live paper on a REJECTED verdict; QQQ/AAPL/TSLA on none |
| Options vertical-spread certification | Scaffold only |
