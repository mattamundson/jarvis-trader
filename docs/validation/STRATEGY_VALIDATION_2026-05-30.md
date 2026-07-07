# JARVIS Trader — Live Paper Book Re-Validation

**Date:** 2026-05-30
**Scope:** MES (SMA trend, fast=60/slow=200/atr_trail=2.0) and MGC (SMA trend, fast=50/slow=120/atr_trail=2.0) — the two LIVE paper strategies, both previously gate-v2 ALT PASS, Tier-3 authorized 2026-05-24.
**Mode:** Decision-support only. Read + backtest review. No config, strategy, risk, or engine state was changed. Gated DO_NOT_TRADE instruments (MCL, MNQ, M2K) were not validated.

---

## Bottom line

Both verdicts are **PASS via the ALT path** and both **CORE-FAIL on `p_positive_edge`** (MES 0.75, MGC 0.6842 — both far below the 0.95 core bar). The entire live authorization rests on the ALT lane, which is itself standing on three metrics that the refutation/critic rounds showed are **mislabeled or not actually computed**: `mc_95th_dd` is an empirical OOS-window percentile, **not** a Monte Carlo permutation; `dsr=1.0` is a binary selection-bias pass-flag, **not** a Deflated Sharpe Ratio; and the cost sweep is **non-monotonic** for both symbols, which proves the cost model re-runs the whole backtest per tier rather than re-pricing a fixed trade list.

The refuter successfully defended the *gate-design intent* (ALT is meant to clear moderate-edge, rolling-WFO-stable, cost-robust strategies) and corrected one real skeptic error (MGC champion IS PF is 3.18, not 1.357). But the refuter did **not** rehabilitate the underlying metric validity — it reinterpreted the labels rather than producing the missing computations. Net: the edge is **plausible but unproven by the metrics the gate claims to use.**

- **MES → EDGE_FRAGILE.** Core fail survives; ALT pass rests on a metric (`mc_95th_dd`) that is sparsity-dominated (16 OOS trades / 19 windows, ~0.84/window, 0-trades in recent windows 15–19) and not a true MC. Under an actual permutation the 5x DD margin plausibly collapses toward 2x.
- **MGC → CONCERN_REVIEW.** Better trade density (67 OOS trades, ~3.5/window) and IS PF=3.18 give it more substance, but it passes rolling WFO only at **MODERATE**, shows a documented bimodal IS/OOS regime split (early windows OOS PF 0.02–0.75, late windows extreme), `fixed_params_min_pf=1.357` sits near the 1.2 ALT floor, and its cost sweep is the more egregiously non-monotonic of the two.

Neither earns HOLD_EDGE_CONFIRMED: in both cases a core fail survived refutation, and the completeness critic surfaced fatal-tier blind spots (true MC never run, DSR never computed, cost monotonicity never verified deterministically, live fill-slippage never tested).

---

## Per-strategy verdict

### MES — `MES_trend_rank11.json` (created 2026-05-30T09:01:12Z, ~1 day old, non-stale)

**ADJUDICATED: EDGE_FRAGILE**

| Gate-v2 metric | Value | Bar | Pass? |
|---|---|---|---|
| Core `p_positive_edge` | 0.75 | ≥ 0.95 | **FAIL** |
| `pf_ci_lower` | 2.50 | ≥ 1.10 | pass |
| `mc_95th_dd_pct` | 0.81% | ≤ 4% ALT | pass* |
| `dsr` | 1.0 | ≥ 0.30 ALT | pass* |
| `rolling_wfo` | STRONG | ≥ MODERATE | pass |
| `fixed_params_min_pf` | 1.524 | ≥ 1.2 ALT | pass |
| `cost_survives_through` | catastrophic | ≥ realistic | pass* |
| **Net verdict** | **PASS via ALT** (core FAIL) | | |

\* asterisked passes are the ones refutation/critic showed are mislabeled or non-deterministic — see "Blind spots."

Combo grid (fast=[50,55,60]×slow=[200]×trail=[2.0]): fast=50 PF=1.524 (36t); fast=55 PF=1.840 (36t); **fast=60 PF=2.160 (30t) champion**. Champion appears in 10/19 windows.

### MGC — `MGC_trend_rank4.json` (created 2026-05-29T09:00:44Z, ~2 days old, non-stale)

**ADJUDICATED: CONCERN_REVIEW**

| Gate-v2 metric | Value | Bar | Pass? |
|---|---|---|---|
| Core `p_positive_edge` | 0.6842 | ≥ 0.95 | **FAIL** |
| `pf_ci_lower` | 2.597 | ≥ 1.10 | pass |
| `mc_95th_dd_pct` | 1.24% | ≤ 4% ALT | pass* |
| `dsr` | 1.0 | ≥ 0.30 ALT | pass* |
| `rolling_wfo` | MODERATE | ≥ MODERATE | pass (at floor) |
| `fixed_params_min_pf` | 1.357 | ≥ 1.2 ALT | pass (near floor) |
| `cost_survives_through` | catastrophic | ≥ realistic | pass* |
| **Net verdict** | **PASS via ALT** (core FAIL) | | |

Combo grid (fast=[40,50]×slow=[80,120]×trail=[1.5,2.0], 8 combos all PF>1.35): **fast=50/slow=120/trail=2.0 PF=3.180 (50t) champion**, highest IS PF in the grid. 67 OOS trades across 19 windows.

Note: RV filter (`min_rv_annualized`, recommended 9%) was CORE-validated 2026-05-24 but is **NOT enabled** in `paper_config.py` (passes 0.0). Enabling it would further reduce trade count — i.e. it would worsen the sparsity that is the core weakness here. Treat the live config as running *without* that filter.

---

## Axis table

| Axis | MES holds_up | MES upheld by refuter? | MGC holds_up | MGC upheld by refuter? | Key evidence |
|---|---|---|---|---|---|
| Walk-forward | concern | **No (overturned)** | fail | **No (overturned)** | Refuter corrected the core skeptic error: MGC champion IS PF = 3.18 (highest in grid), not 1.357 (that's the min combo). Param drift fast=60→50 is normal per-window retraining; rolling_wfo verdict (STRONG/MODERATE) is the actual robustness test and it passed. MES OOS sparsity (16 trades/19 windows) and recent-window 0-trade behavior remain real but are not, by themselves, a gate violation. |
| Monte-Carlo DD | concern | **No (overturned)** | pass | **Yes (upheld)** | Refuter exposed that `mc_95th_dd` is `np.percentile([oos_window_dd], 95)` — an empirical OOS-window percentile, NOT a permutation MC. MES sparsity makes its 0.81% figure outlier-dominated (windows 8, 17); a true 500-shuffle MC plausibly yields 1.5–2.5%, eroding the 5x margin to ~2x. MGC's 67-trade density makes its 1.24% defensible (~1.6x margin under true MC). |
| Cost / slippage | pass | **No (overturned)** | concern | **No (overturned)** | Refuter showed BOTH sweeps are non-monotonic (MES optimistic→realistic +0.017 PF despite commission doubling; MGC realistic→pessimistic +0.022 PF). Root cause: the sweep re-runs full signal+execution per tier, mutating the trade list, rather than re-pricing a fixed list. PF levels (MES 2.15, MGC 3.17 at catastrophic) may be fine, but the *sweep as a boundary* is an artifact, not a validated cost curve. |
| Overfitting / DSR | concern | partial | concern | partial | Refuter's strongest point: `dsr=1.0` is a binary selection-bias pass-flag (`dsr ≥ 0.30`), NOT a Bailey/López-de-Prado Deflated Sharpe. So the skeptic's "DSR artificially high masks overfit" is wrong — but so is any claim that overfitting was *screened*. No actual DSR is computed; max-Sharpe-over-N-candidates inflation (MES N=3, MGC N=8) is uncorrected. MGC's bimodal IS/OOS split is real and only honestly priced by rolling_wfo=MODERATE. |

**Reading the table:** Of 4 axes, the refuter overturned the skeptic on 3 for MES and 3 for MGC — but "overturned the skeptic" here mostly means "the skeptic's *mechanism* was wrong," not "the metric is sound." Only **MGC Monte-Carlo DD** was cleanly upheld as pass-and-survived. That is a single clean axis per the HOLD bar's "multiple axes pass AND survived refutation" requirement — insufficient for HOLD on either symbol.

---

## Refutations that landed

1. **MGC IS-PF reversal (decisive).** The skeptic claimed the MGC champion had the *lowest* IS PF (1.357) — the overfitting smoking gun. The refuter is correct: 1.357 is `fixed_params_min_pf` (worst combo); the champion's IS PF is 3.18, the *highest* in the grid. This removes the cleanest overfitting accusation against MGC.
2. **`dsr` is not DSR.** Both sides were partly wrong about DSR; the refuter correctly identified it as a binary selection-bias gate, not a deflated Sharpe. This neutralizes the skeptic's "DSR=1.0 masks overfit" but does NOT establish that overfitting was tested.
3. **Parameter drift is expected.** fast=60→50 across rolling windows is per-window retraining, not instability. Legitimate correction.
4. **Infinity/0 PF in 1–2 trade windows are real small-sample outcomes**, not "margin artifacts." Legitimate — though they also can't carry the verdict.

## Refutations that did NOT land (skeptic concerns that survived)

1. **`mc_95th_dd` is not a Monte Carlo.** The refuter conceded this outright. The headline DD safety number is an empirical percentile, and for MES it is sparsity-dominated. This is the single biggest surfaced risk.
2. **Cost-sweep non-monotonicity stands for BOTH symbols.** The refuter's own analysis confirms the sweep mutates the trade list per tier. `cost_survives_through=catastrophic` is therefore a soft claim, not a hard boundary.
3. **Core fail survives on both.** `p_positive_edge` 0.75 / 0.6842 vs 0.95 — the strategies do not clear the primary edge-probability bar. Live status depends entirely on the ALT lane, which is built on the two compromised metrics above.

---

## Blind spots (from completeness critic)

Fatal-tier (could each independently invalidate the live authorization):

1. **True MC permutation never run.** `mc_95th_dd` is empirical, not shuffled. No 500+ sign-shuffle of the 16 (MES) / 67 (MGC) trades exists. The DD ceiling claim is unproven.
2. **Deflated Sharpe never computed.** No `deflated_sharpe` module confirmed; `dsr=1.0` is a flag. Multiple-testing inflation (N=3 / N=8 grids) uncorrected.
3. **Cost monotonicity never verified deterministically.** No test re-prices a fixed trade list. Non-monotonic results prove the sweep is not a clean cost curve.
4. **Live IB fill-quality vs backtested 2-tick slippage untested.** Backtest fills on CLOSE; IB fills on order submission + latency. Tight ATR trails (2.0×ATR) trigger immediately if fills land 1–2 bars late or 5+ ticks worse. No fill-latency test in the suite.

High-severity:

5. **No PurgedKFold / embargo** on WFO train/test boundaries (SMA slow=200 lookback can leak across boundaries).
6. **MES recent-window degradation** (windows 15–19: 0 OOS trades in 3–4 of 5) is unverified as "no signal" vs "edge decay" — no 2026-04→05 forward test confirms the edge still fires.
7. **RV filter validated but not enabled**; **VIX filter present but never backtested**; **gap-through-stop** and **session-aware slippage** untested.
8. **$50K dual-position margin interaction** (both MES and MGC live simultaneously) untested.

---

## What to run for a definitive answer (exact commands — recommend, do not auto-run)

Offline backtests only, via the engine venv, from `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine`. None of these touch the live engine on port 8010.

```bash
# 1. Reproduce both verdicts; check cost-tier PF determinism / non-monotonicity
.venv\Scripts\python.exe backtest\run_mes_trend_rank11.py
.venv\Scripts\python.exe backtest\run_mgc_trend_rank4.py

# 2. Confirm DSR is not actually implemented (expect ImportError)
.venv\Scripts\python.exe -c "import backtest.deflated_sharpe as ds; print('DSR module exists')"

# 3. Search for any data-leakage / embargo defense (expect none)
#    (use Grep tool: pattern 'PurgedKFold|embargo|data.*leak' over engine/**/*.py)

# 4. Check whether live fill-slippage / latency is tested anywhere
.venv\Scripts\python.exe -m pytest tests/ -k "slippage or cost or fill" -v

# 5. Confirm gate v2 enforcement blocks MCL/MNQ/M2K and approves MES/MGC
.venv\Scripts\python.exe backtest\gate_v2_policy.py MES
.venv\Scripts\python.exe backtest\gate_v2_policy.py MGC
```

Decisive additions not yet scripted (would require a new backtest script — propose before writing):

- **True MC permutation**: 500+ sign-shuffles of each strategy's OOS trade list; report the actual 95th-percentile DD and re-test against the 4% ALT ceiling. This is the single most important missing computation.
- **Deterministic cost re-pricing**: hold the champion trade list fixed, apply the 4 cost tiers post-hoc, confirm strict monotonicity.
- **Real Deflated Sharpe** (Bailey/López-de-Prado) correcting for N grid candidates.

---

## Recommendation (decision-support only — nothing changed)

Do **not** treat the current PASS-via-ALT as a confirmed edge for either symbol. Paper trading can continue (it is the right venue to gather live evidence), but the live authorization should be read as **provisional pending**: (a) a true MC DD permutation, and (b) a live-slippage check after the first ~50 paper fills per symbol. MES is the weaker of the two (sparsity + fragile DD margin); MGC has more substance but sits at the rolling-WFO MODERATE floor with near-floor `fixed_params_min_pf`. If a real MC pushes MES `mc_95th_dd` above ~2% or live slippage averages >2.5 ticks, MES should be re-gated. No promotion to live capital or larger sizing is warranted on the present evidence.
