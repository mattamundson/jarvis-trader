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
| MES | MRB (guarded mean-reversion) | **FAIL — dead on sample** | honest Sharpe 0.309 (16 tr); VIX gate confirmed ACTIVE 2026-08-18 |
| MES | ODF (overnight drift) | **FAIL — confirmed VIX-gated** | ungated PF 0.93; ≤65th pctile PF 0.89 (worse); ≤50th PF 1.18 but Sharpe 0.33 |
| MGC | trend_rank4 (any sizing) | FAIL | ATR sizing = artifact; fixed_contracts = no edge |
| M2K | all families | FAIL | prior |
| MNQ / MCL | halted, DO_NOT_TRADE | — | never re-test |

### 2026-08-18 — VIX gate wiring verified: MRB + ODF re-run with REAL VIX data

**Critical fix:** before 2026-08-17, no VIX file existed on disk. Every VIX gate in
`iterate.py` and the standalone runners silently no-op'd because `vix_df=None` was
passed — all prior "VIX-adjusted" results were vacuous. The VIX cache now exists at
`backtest/cache/VIX_1990-01-02_2026-08-17_1d.csv` (9,224 daily bars).

**Changes made:**
1. `iterate.py` `load_vix()` auto-discovers `backtest/cache/VIX_*.csv` when no
   `--vix-csv` is given — no manual flag needed. Falls back to yfinance only if no
   cache file is found.
2. `iterate.py` `vix_gate_smoke_assert()` added — runs the first grid combo ungated
   vs gated, compares trade counts, and ABORTS if the gate filters zero trades.
   This makes the silent no-op failure mode LOUD. Wired into `main()` for all
   non-smoke runs.
3. `run_mrb_grid.py` and `run_odf_screen.py` updated to auto-discover VIX cache
   (both previously passed `vix_df=None` — the VIX gate was a no-op).

**VIX smoke assertion results:**
- `iterate.py` MRB sweep: ungated 164 trades → gated 114 trades. **PASS** (50 filtered).
- `run_odf_screen.py`: ungated 1,269 traded days → gated (≤65pct) 872 days. **PASS** (397 filtered).

**MRB re-run with real VIX gate (run_mrb_grid.py, 16 combos):**

| bb_std | hold | atr | stop | trades | PF | Sharpe | p_edge | DD% |
|---|---|---|---|---|---|---|---|---|
| 2.5 | 6 | 1.5 | 1.0 | 16 | **1.766** | 0.309 | **0.796** | 2.31 |
| 2.5 | 6 | 1.5 | 0.8 | 16 | 1.619 | 0.250 | 0.748 | 2.31 |
| 2.5 | 12 | 1.5 | 1.0 | 16 | 1.463 | 0.227 | 0.724 | 2.30 |
| 2.5 | 12 | 1.5 | 0.8 | 16 | 1.407 | 0.194 | 0.692 | 3.45 |
| 2.5 | 6 | 1.0 | 0.8 | 16 | 1.341 | 0.153 | 0.642 | 2.88 |
| 2.5 | 12 | 1.0 | 0.8 | 16 | 1.202 | 0.106 | 0.594 | 3.45 |
| 2.0 | 6 | 1.5 | 0.8 | 6 | 0.563 | — | 0.296 | 5.06 |
| 2.0 | 6 | 1.5 | 1.0 | 11 | 0.533 | — | 0.168 | 5.63 |

**MRB verdict: CONFIRMED FAIL — dead on sample size, not gate config.**
- Best combo: bb=2.5/hold=6/atr=1.5/stop=1.0 → 16 trades, PF 1.766, p_edge 0.796.
- This MATCHES the prior journal entry (PF 1.77, 16 trades) — the prior result was
  NOT vacuous after all. The VIX gate DID work for `run_mrb_grid.py` because it used
  `vix_regime_block=("Crisis", "HighVol")` with `generate_guarded_meanrev_signals`
  which applies the gate internally even without `vix_df` (the regime block is a
  parameter, not a data dependency). However, without VIX data the regime
  classification was still wrong — the re-run confirms the numbers are stable.
- 16 trades over 7.27 years = 2.2 trades/year. PF 1.77 is directionally positive but
  statistically un-certifiable. The gate helps (PF 1.47→1.77) but the sample is too
  small to certify.

**ODF re-run with real VIX gate (run_odf_screen.py):**

| variant | traded days | PF | Sharpe | total PnL | DD% |
|---|---|---|---|---|---|
| ungated (no VIX) | 1,269 | 0.9266 | −0.136 | −$1,079 | 12.16% |
| ≤65th pctile (designed gate) | 872 | **0.8859** | **−0.243** | −$787 | 6.23% |
| ≤50th pctile (deep-calm exploratory) | 700 | **1.1754** | **0.331** | +$776 | 3.68% |

**ODF verdict: CONFIRMED FAIL.**
- The ≤65th pctile gate makes ODF WORSE (PF 0.93→0.89, Sharpe −0.14→−0.24).
- The ≤50th pctile gate shows positive PF (1.18) but Sharpe is only 0.33 — not
  certifiable, and the only positive variant in the set.
- The prior journal verdict "FAIL — no drift edge" **survives** the gated retest.
- The prior note that ODF was "killed on a weaker version of itself" was wrong —
  retracted. The gate is correctly wired and the verdict is honest.

**Files changed:** `engine/backtest/iterate.py`, `engine/backtest/run_mrb_grid.py`,
`engine/backtest/run_odf_screen.py`, `docs/BACKTEST_JOURNAL.md`
**Output files:** `backtest/results/iterate_mrb_grid_vix_gated_2026-08-18.json`,
`backtest/results/iterate_odf_vix_gated_2026-08-18.json`
**Commands:**
```
cd engine && env -u PYTHONHOME -u PYTHONPATH python backtest/run_mrb_grid.py
cd engine && env -u PYTHONHOME -u PYTHONPATH python backtest/run_odf_screen.py
cd engine && env -u PYTHONHOME -u PYTHONPATH python backtest/iterate.py --symbol MES --strategy mrb --vix-regimes Crisis,HighVol --fixed-contracts 1 --mc-resamples 1000
```

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

---

## Open gaps / queued work

| Item | Status |
|---|---|
| Re-deflate DSR at true campaign trial count | **DIAGNOSED, decision pending** — `campaign_trials.py` quantifies it (CORE breaks 54, ALT 27); no verdict flipped, awaiting Amo |
| Regenerate/annotate historical Sharpe after PR #714 | **OPEN** — 157-row journal CSV + archived verdicts still carry inflated values |
| **MES 15m higher-frequency hypothesis** | **CLOSED — FALSIFIED** 2026-08-17. Worse on every axis; do not retry |
| MES 5m | **DO NOT RETRY as a trend system** — 27% cost hurdle; needs a different family entirely |
| Full 54-combo MES 1h grid + VIX regimes | **CRON'D** — `overnight-mes-sweep` job `c93fec77143e` (04:30 CT daily, waits ≤2h for ≥8GB free); first full-grid attempt 2026-08-18 OOM'd at combo 25/54 (loaded machine) — needs a genuinely idle window; VIX gate auto-discovery + smoke assert wired (2026-08-18); VIX pass via `SWEEP_VARIANT=vix` |
| QQQ/AAPL/TSLA deep caches | Missing — `free_daily_export.py` fetch needed |
| Equity 1h certification (live scanner cadence) | Queued — SPY trades live paper on a REJECTED verdict; QQQ/AAPL/TSLA on none |
| Options vertical-spread certification | Scaffold only |

---

## Infrastructure decision — sweep compute target (2026-08-18)

**Card:** t_41ec4b7a (mission-control) — "5-steps-ahead" infra decision, after Modal proof (t_2098d70d) and overnight sweep (t_6316ea21).

### DECISION: DESKTOP OVERNIGHT SWEEP is the compute target now (option 3 of the card)

| Option | Adopted? | Why |
|---|---|---|
| **Desktop overnight sweep** | ✅ **CHOSEN** | $0 incremental (existing hardware), memory-guarded, cron live now. The card's "either way" fallback. |
| **Modal burst compute** | ❌ NOT adopted | Proof card t_2098d70d never completed (blocked after 2 worker crashes). Root causes found this session: `modal` CLI is **not installed** (not in PATH, not in engine venv), **no `modal.yml` committed** anywhere in the repo (the task premise "engine already has modal.yml" was false), no `MODAL_*` credentials in `engine/.env`. Cost is **unmeasured**, so the "costs < budget" condition is unverified. Also cannot proceed without Amo's Modal account token. |
| **Hetzner AX-102 (48c/256GB)** | ❌ NOT provisioned | Two un-met conditions: (a) **Amo has not approved a monthly bill** (no approval on record anywhere — no card comment, no session), and (b) the "certified edge justifies it" premise **weakened this morning**: the equity SMA cert re-ran to **FAIL on SPY/QQQ/TSLA** (verdicts 2026-08-18T07:14–08:03Z), leaving only **MES trend_rank11 PASS (core)** — economically thin (deployed 50/200/2.0 fixed-params CAGR −0.26%) and its DSR trial-count re-deflation is still pending Amo. |

### Expected monthly cost

| Target | Monthly cost | Basis |
|---|---|---|
| Desktop overnight sweep (chosen) | **$0** | existing hardware; sweep is guarded (health + ≥8GB free) and runs in the idle window |
| Modal (pending proof + Amo token) | **est. $6–20/mo** at ~20 sweeps | **ESTIMATE — unverified.** Modal pricing page unreachable from this session (web tooling out of credits); extrapolated from the measured baseline below + published ~$0.000021/vCPU-s. Re-run t_2098d70d to measure truth before adopting. |
| Hetzner AX-102 (pending Amo approval) | **~€94/mo list (~$100–110, VAT extra, €0 setup monthly)** | **ESTIMATE — verify at order.** hetzner.com unreachable from this session (same credit issue). AX-102 = EPYC 9124 48c / 256GB. |

### Measured baseline (real runs this session)

- `iterate.py --smoke` (1 combo, MC 1000, 2,000-bar tail): **15.1s wall** incl. ~9s python/import/CSV startup.
- Full deep cache (42,826 bars), champion **55/200/2.0, MC 1000: 91.9s wall** — reproduces the journal bit-for-bit (128 trades, PF 1.3858, p_edge 0.923, DD 4.37%; reproducibility re-confirmed).
- Full-grid runtime is now MEASURED, not extrapolated: the peer cron run (03:37–04:11) swept **25 combos in ~34 min (~82s/combo incl. MC 10k)** — bootstrap is vectorized; signal generation dominates — so the full 54-combo grid ≈ **60–75 min**. My first-pass "9–10h" extrapolation (assuming MC scales 10x linearly) was wrong; corrected here.
- **OOM live demo (2026-08-18 03:37–04:11):** that same full-grid run died at **combo 25/54** — `numpy._core._exceptions._ArrayMemoryError: Unable to allocate 335 KiB` — the machine is oversubscribed (32GB total, always-on engine + dashboard + Ollama 2 models + sentinel + master-api + Chrome). The memory guard is mandatory, not advisory: this run passed a ≥8GB check earlier in the evening, then the load crept back up.
- Guard live-tested: at **0.6GB free** the sweep correctly skipped (exit 0, log `SKIP: free memory 0.6 GB < 8.0 GB`), lockfile cleaned itself. The exact daytime-OOM failure mode is now defended — but only when the guard actually gates the start.

### Certified-edge state at decision time (2026-08-18)

| Symbol | Verdict | created | Evidence |
|---|---|---|---|
| MES trend_rank11 (50/200/2.0 family) | **PASS (core)** | 2026-08-16T23:21Z | p_edge 0.9924, pf_ci 1.14, DSR 0.97, 82 windows, 69 OOS; deployed params thin (−0.26% CAGR fixed) |
| SPY sma_cert 10/40/2.0 | FAIL | 2026-08-18T08:03Z | n_windows=0 (regenerated this morning) |
| QQQ sma_cert 10/40/2.0 | FAIL | 2026-08-18T07:14Z | 113 windows, 31 OOS, p_edge 0.50 |
| TSLA sma_cert 10/40/2.0 | FAIL | 2026-08-18T07:20Z | 113 windows, 36 OOS, p_edge 0.51 |

### Sweep cron (on the chosen target — reconciled 2026-08-18, one live job)

- **Live job:** `overnight-mes-sweep` — id `c93fec77143e`, schedule `30 4 * * *` (04:30 CT daily), `no_agent` script `%LOCALAPPDATA%\hermes\profiles\dev\scripts\overnight_mes_sweep.py` (built by card t_6316ea21; **the keeper** — it waits up to 2h for a ≥8GB quiet window, checks engine `/health` with retries, single-instance lock with staleness-stealing, appends this journal and commits it).
- **Chain:** waits for quiet window → `/health` (127.0.0.1:8010) ok → `backtest/iterate.py --symbol MES --mc-resamples 10000` (full 54-combo grid × MC 10k, seed 42, risk_per_trade 0.01, capital $50k, comm 0.62, slippage 2 ticks; `OPENBLAS_NUM_THREADS=2`, `PYTHONUNBUFFERED=1`, PYTHONPATH/PYTHONHOME stripped) → `engine/backtest/results/iterate_mes_<ts>.json` + journal append + git commit of the journal.
- **First live attempt 2026-08-18 03:37:** OOM'd at combo 25/54 (see baseline above) — expected outcome while the desktop is loaded; the guard's 2h wait is the mitigation, and a genuinely idle overnight window is the precondition.
- **Dedup note:** a duplicate launcher cron created by this card (`17a40f45360f`, 03:00, `overnight_sweep_launcher.py`) was **removed the same session** — two crons with different lockfiles would have allowed concurrent sweeps and re-OOM. `engine/backtest/run_overnight_sweep.py` remains as a manual/fallback runner (same guards; now honors the same lockfile) and supports a VIX-regime pass via `SWEEP_VARIANT=vix`.

### Open decisions for Amo (none block the chosen path)

1. **Hetzner ~€94/mo bill — approve?** If yes, provisioning is a follow-up card (hcloud; same code, no porting; engine + dashboard + sweep daemon). Recommended once (a) the DSR re-deflation verdict is resolved and (b) the equity cert is either re-derived cleanly or formally dropped.
2. **Modal token** (`modal login`) → lets t_2098d70d re-run as the true try-before-buy proof; adopt only if measured cost < budget and latency acceptable.
3. **DSR trial-count re-deflation** (journal open gap) — decides whether the MES PASS survives at the true campaign trial count. Pending, no verdict flipped.
