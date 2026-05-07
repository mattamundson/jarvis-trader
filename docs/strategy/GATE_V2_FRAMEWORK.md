# Gate v2 Framework — JARVIS TRADER Strategy Validation

**Status:** ACTIVE — `GATE_V2_ENFORCE_ROUTING=1` in `engine/.env`
**Activated:** 2026-04-21 (Phase 3-FULL, commit `33c9ff2`)
**Source:** `engine/backtest/_gate_v2_helpers.py`, `engine/backtest/deflated_sharpe.py`
**Decision record:** `docs/decisions/gate_v2_phase3_full.md`

---

## Overview

Gate v2 is a multi-criteria statistical validation framework that every strategy must pass before it is authorized for paper or live trading. It replaces the ad-hoc "looks profitable" check with a systematic, auditable, machine-enforced decision.

**Why it exists:** Without a formal gate, a profitable-in-IS (in-sample) strategy can trade live while carrying selection bias, overfitting, and fragility to costs. Gate v2 enforces four primary protections:

1. **Selection bias correction** — the Deflated Sharpe Ratio penalizes grid-searched strategies.
2. **Out-of-sample robustness** — Walk-Forward Optimization (WFO) splits data into many non-overlapping IS/OOS windows; the gate evaluates OOS-only.
3. **Tail risk bound** — Monte Carlo 95th-percentile drawdown must stay below a regime-appropriate ceiling.
4. **Bootstrap confidence** — the profit-factor lower-bound (5th percentile of the bootstrap distribution) filters lucky runs from genuine edge.

**Scope:** Applies to all symbols routed by `generate_instrument_signals()`. When `GATE_V2_ENFORCE_ROUTING=1`, a missing or non-PASS verdict causes the signal to be overridden to `NO_TRADE` at the routing layer. `DO_NOT_TRADE_SYMBOLS` takes precedence over all gate logic.

---

## The 7 PASS Criteria

Gate v2 has two verdict pathways: **CORE** and **ALT**. A strategy needs to pass either one — not both.

### CORE path (4 criteria, all must pass)

| # | Criterion | Threshold | Field | Description |
|---|-----------|-----------|-------|-------------|
| C1 | Bootstrap PF CI lower | ≥ 1.10 | `pf_ci_lower` | 5th percentile of bootstrap distribution of mean OOS PF |
| C2 | Probability of edge | ≥ 0.95 | `p_edge` | Fraction of OOS windows where PF > 1.0 |
| C3 | Monte Carlo 95th-pct DD | ≤ 5% | `mc_95th_dd_pct` | 95th-pct drawdown across OOS windows |
| C4 | Deflated Sharpe Ratio | ≥ 0.10 | `dsr` | Multiple-testing-corrected Sharpe p-value |

### ALT path (5 criteria, all must pass)

The ALT path was designed for strategies with STRONG/MODERATE WFO consistency and low drawdown that cannot clear the CORE `p_edge ≥ 0.95` hurdle (which requires ≥19/20 winning OOS windows). Both active strategies (MES R11, MGC R4) pass via ALT.

| # | Criterion | Threshold | Field | Description |
|---|-----------|-----------|-------|-------------|
| A1 | Deflated Sharpe Ratio | ≥ 0.30 | `dsr` | Looser DSR floor than CORE (0.30 vs 0.10) |
| A2 | WFO consistency | MODERATE or STRONG | `wfo_consistency` | % profitable OOS windows (≥55% = MODERATE, ≥75% = STRONG) |
| A3 | Fixed-params min PF | ≥ 1.20 | `fixed_params_min_pf` | Worst PF across all grid combos on the FULL dataset |
| A4 | Cost survivability | ≥ "realistic" | `cost_survives_through` | Highest cost tier at which champion params remain PF > 1.0 |
| A5 | Monte Carlo 95th-pct DD | ≤ 7% | `mc_95th_dd_pct` | Wider DD ceiling (7% vs 5%) — requires $50K+ account sizing |

### Thresholds quick reference

```
GATE_PF_CI_LOWER        = 1.10
GATE_P_EDGE             = 0.95
GATE_MC_DD_CORE         = 0.05   (5%)
GATE_MC_DD_ALT          = 0.07   (7%)
GATE_DSR                = 0.10   (CORE floor)
GATE_DSR_ALT            = 0.30   (ALT floor)
GATE_FIXED_PARAMS_MIN_PF = 1.20
GATE_WFO_CONSISTENCY_VALUES = ["MODERATE", "STRONG"]
COST_SURVIVES_MIN       = "realistic"
```

All constants live in individual runner files. See T15 (QUEUED) for the planned extraction to `engine/backtest/_constants.py`.

---

## Verdict States

| Verdict | `passed_via` | Meaning |
|---------|--------------|---------|
| `PASS` | `"core"` | All 4 CORE criteria met |
| `PASS` | `"alt"` | All 5 ALT criteria met; CORE not required |
| `FAIL` | `null` | Neither CORE nor ALT passed |
| `NO_TRADE` | — | Runtime enforcement state: verdict is missing, stale, or FAIL |

**`NO_TRADE` is the fail-safe default.** When `GATE_V2_ENFORCE_ROUTING=1`, any symbol that cannot produce a fresh PASS verdict gets its signal overridden to `entry_signal=NO_TRADE, exit_signal=NO_EXIT` inside `generate_instrument_signals()`.

**Staleness:** Verdicts older than 30 days (`VERDICT_TTL_DAYS`) are treated as missing → NO_TRADE. The live_readiness gate (C6) surfaces stale verdicts ≥7 days before expiry.

---

## Math

### Bootstrap PF CI Lower (`pf_ci_lower`)

The core concern: a strategy may have a high mean OOS profit factor simply by luck — a few lucky windows inflate the mean. Bootstrap confidence intervals reveal the 5th-percentile scenario.

**Algorithm** (see `engine/backtest/_gate_v2_helpers.py:bootstrap_pf_ci_lower`):

```python
def bootstrap_pf_ci_lower(oos_pfs: list[float], n: int = 5000) -> float:
    # 1. Cap inf/-inf before bootstrapping.
    #    WHY: np.percentile interpolates between values. If any PF is inf,
    #    the interpolation step computes inf - inf = NaN, corrupting the result.
    #    Cap at 5.0 (represents "very profitable") to keep the distribution finite.
    capped = [min(max(pf, 0.0), 5.0) if not (pf == inf or pf == -inf)
              else (5.0 if pf == inf else 0.0)
              for pf in oos_pfs]

    # 2. Draw 5,000 bootstrap samples (with replacement), each the same size as
    #    the original OOS window list. Compute the mean PF of each sample.
    rng = np.random.default_rng(42)          # fixed seed for reproducibility
    arr = np.array(capped, dtype=float)
    boot_means = [rng.choice(arr, size=len(arr), replace=True).mean()
                  for _ in range(n)]

    # 3. Return the 5th percentile of the bootstrap mean distribution.
    #    This is the lower bound of a 90% confidence interval for the true mean PF.
    return float(np.percentile(boot_means, 5.0))
```

**Inf-cap rationale:** `np.percentile` uses linear interpolation between adjacent elements. If any element is `inf`, the interpolation computes `inf + weight*(inf - inf)` = `inf + weight*NaN` = `NaN`. Before the inf-cap fix (`d1d70d2`, 2026-05-07), a single winning window with zero losses (PF = inf) silently produced `pf_ci_lower = NaN`, which failed the `>= 1.10` check and wrongly suppressed a PASS verdict. The cap at 5.0 is conservative: a real PF > 5.0 is treated as 5.0, slightly undervaluing exceptional windows but never producing NaN.

**Gate threshold:** `pf_ci_lower >= 1.10` means "even in the worst 5% of bootstrap scenarios, the strategy is expected to be profitable (PF > 1.0) with 10% margin."

---

### Deflated Sharpe Ratio (`dsr`)

Source: Bailey, Borwein, López de Prado, Zhu (2014). Full implementation: `engine/backtest/deflated_sharpe.py`.

**Problem it solves:** If you test N parameter combinations and report the best Sharpe, the naive p-value is biased upward. The more combinations you test, the higher the expected maximum Sharpe under the null (random strategies). DSR corrects for this by comparing the observed Sharpe to the expected maximum Sharpe across N zero-skill trials.

**Formula:**

```
DSR = Φ((SR_observed - E[max SR | N, null]) / σ_SR)

where:
    E[max SR | N, null] = (1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e))
    σ_SR   = sqrt((1 - γ₃·SR + ((γ₄-1)/4)·SR²) / (T-1))
    γ      = Euler-Mascheroni constant ≈ 0.5772
    γ₃     = skewness of returns
    γ₄     = raw kurtosis of returns (Gaussian = 3, not excess kurtosis)
    T      = sample size (trades or bars)
    N      = number of grid combinations tested
    Φ      = standard normal CDF
```

**Interpretation:**
- `dsr < 0.05` → FAIL: SR indistinguishable from luck at 5% significance given N trials
- `dsr < 0.10` → Marginal
- `dsr ≥ 0.10` → CORE PASS: genuine edge survives the selection-bias penalty
- `dsr ≥ 0.30` → ALT PASS floor (looser, but combined with WFO + fixed-params evidence)
- `dsr = 1.0` → Overwhelming evidence of edge (observed SR is many σ above the null maximum)

**Runner usage:** Each runner passes `n_trials=n_grid_combos` (the number of IS/OOS grid searches performed) and `n_obs=max(total_oos_trades, 30)`. The mean OOS Sharpe across windows is used as `sharpe`.

---

### Probability of Edge (`p_edge`)

Fraction of OOS windows where the strategy achieved PF > 1.0 (profitable):

```python
p_edge = sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs))
```

**CORE threshold:** `p_edge >= 0.95` means ≥95% of OOS windows were profitable. For 18 windows, this requires ≥17/18 profitable. This is intentionally strict — a strategy that fails in 2+ out of 18 windows is not considered robustly edge-bearing for CORE.

**ALT path does not directly gate on `p_edge`.** Instead, `wfo_consistency` (MODERATE/STRONG) provides a softer proxy: STRONG = ≥75% profitable windows, MODERATE = ≥55%.

---

### Monte Carlo 95th-percentile Drawdown (`mc_95th_dd`)

```python
mc_95th_dd = float(np.percentile(oos_dds, 95.0))
```

Where `oos_dds` is the list of max drawdown percentages from each OOS window's backtest result. This is NOT a simulated Monte Carlo — it uses the empirical distribution of actual OOS drawdowns across all walk-forward windows as a proxy for tail-risk.

**CORE ceiling:** ≤ 5% (requires $10K+ account; typical JARVIS account is $50K)
**ALT ceiling:** ≤ 7% (explicitly requires $50K+ account sizing, enforced by `initial_capital=50_000.0` in paper config)

---

### WFO Consistency (`wfo_consistency`)

Classified in `_gate_v2_helpers.py:classify_wfo_consistency`:

```python
pct_profitable = sum(1 for pf in oos_pfs if pf > 1.0) / len(oos_pfs)
if pct_profitable >= 0.75: return "STRONG"
if pct_profitable >= 0.55: return "MODERATE"
return "WEAK"
```

ALT path accepts MODERATE or STRONG. WEAK is a structural FAIL on the ALT path.

---

### Fixed-Params Min PF (`fixed_params_min_pf`)

All grid combinations are run on the **full dataset** (no IS/OOS split) with each combo's fixed parameters. The minimum PF across all combos must be ≥ 1.20.

**Purpose:** Tests whether any combo in the grid is unprofitable on the full data. A grid with one "dud" combo drags the floor below 1.20 and fails this criterion. The fix from rank10→rank11 for MES was removing slow=190 from the grid: the (55,190) and (50,190) combos dragged `fixed_params_min_pf` from 1.5237 down to 1.1098, which failed the 1.20 ALT floor.

---

### Cost Survivability (`cost_survives_through`)

Champion parameters are tested at 4 cost tiers on the full dataset:

| Tier | Commission | Slippage |
|------|-----------|---------|
| `optimistic` | $0.31/contract | 1 tick |
| `realistic` | $0.62/contract | 2 ticks |
| `pessimistic` | $1.24/contract | 3 ticks |
| `catastrophic` | $2.48/contract | 4 ticks |

ALT path requires `cost_survives_through >= "realistic"`. A strategy that breaks at realistic costs is not tradeable. Both active strategies survive through `catastrophic`.

---

## WFO Configuration

Standard configuration used across all trend runners:

```python
TRAIN_MONTHS = 6    # IS window length
TEST_MONTHS  = 1    # OOS window length (MES trend) / 2 (MGC trend, mean-rev)
STEP_MONTHS  = 1    # Walk step (overlapping IS windows, non-overlapping OOS)
N_WINDOWS    = 18   # Target; actual is data-limited
```

**Window generation:** Starting from the first bar, each window shifts by `STEP_MONTHS`. IS is the preceding `TRAIN_MONTHS` of data; OOS is the next `TEST_MONTHS`. Windows with fewer than 30 bars in either split are skipped.

**OOS purity:** IS data is used only for grid-search parameter selection (best IS PF). The selected params are then applied to OOS data without lookahead. The OOS result is the one counted for gate v2 metrics.

**Minimum OOS trades:** `MIN_OOS_TRADES_PER_WINDOW = 1` (lowered from 5 — SMA trend generates 1-3 trades per window; sparse windows still carry signal).

---

## DO_NOT_TRADE_SYMBOLS Frozenset

**Definition** (`engine/backtest/signals.py:113`):

```python
DO_NOT_TRADE_SYMBOLS = frozenset({"MCL", "MNQ", "M2K"})
```

**Current contents:**
- `MCL` — 5 hypotheses exhausted (A=chop filter, B=no sentiment, C=rv-band, D=SMA 1h, E=SMA 1d); parked 2026-05-06
- `MNQ` — SMA Trend ranks 1-2 + Breakout ranks 1-7 + ORB rank 1 all FAIL gate v2; 0 OOS trades on daily; parked 2026-05-06
- `M2K` — SMA Trend ranks 1-2 + ORB rank 1 all FAIL gate v2; parked 2026-05-06

**Runtime enforcement:** `DO_NOT_TRADE_SYMBOLS` is checked BEFORE gate v2 in `generate_instrument_signals()`. A symbol in this set is force-blocked to `NO_TRADE` regardless of whether a PASS verdict exists. This provides a belt-and-suspenders layer: even if a new verdict were mistakenly written for MCL, it would not route until MCL is explicitly removed from the frozenset.

**Sync requirement:** C7 of the live-readiness gate verifies that:
- Every FAIL-only symbol is in `DO_NOT_TRADE_SYMBOLS`
- Every PASS symbol is NOT in `DO_NOT_TRADE_SYMBOLS`

See `engine/backtest/live_readiness.py:check_c7_do_not_trade_symbols`.

---

## Routing Layer

### GATE_V2_ENFORCE_ROUTING

Environment variable in `engine/.env`:
```
GATE_V2_ENFORCE_ROUTING=1
```

When `1`, `generate_instrument_signals()` reads the verdict JSON for each symbol before signal generation. Signal-generation output is unchanged only when `verdict == "PASS"` and the verdict is not stale. Otherwise, signals are overridden to `NO_TRADE`.

**Rollback:** Set to `0` and restart engine. Time-to-rollback: < 3 minutes. Verdicts persist (no state to undo).

### ALT Routing and $50K+ Accounts

The ALT verdict path explicitly requires `initial_capital = 50_000.0` in the paper config. This is not a guideline — it's a technical constraint. The ALT path's 7% MC DD ceiling is only acceptable when the account is large enough that a 7% drawdown does not trigger margin calls or forced exits.

Paper configs that use ALT routing (`MES_TREND_PAPER_CONFIG`, `MGC_PAPER_CONFIG`) both have `initial_capital=50_000.0`.

---

## Verdict JSON Schema

Each runner writes a verdict to `engine/data/gate_v2_verdicts/<SYMBOL>_<family>_rank<N>.json`. Key fields:

```json
{
  "symbol": "MES",
  "family": "trend",
  "rank": 11,
  "verdict": "PASS",
  "passed_via": "alt",
  "core_verdict": "FAIL",
  "alt_verdict": "PASS",
  "created_at": "2026-05-07T00:35:00+00:00",
  "gate_v2_metrics": {
    "pf_ci_lower": 2.4942,
    "p_edge": 0.75,
    "mc_95th_dd": 0.008055,
    "mc_95th_dd_pct": 0.8055,
    "dsr": 1.0,
    "wfo_consistency": "STRONG",
    "fixed_params_min_pf": 1.5237,
    "fixed_params_mean_pf": 1.9476,
    "fixed_params_max_pf": 2.156,
    "cost_survives_through": "catastrophic"
  },
  "wfo_config": {
    "train_months": 6,
    "test_months": 1,
    "step_months": 1,
    "n_oos_windows": 16,
    "n_oos_windows_with_trades": 16,
    "total_oos_trades": 35,
    "grid_combos": 3
  }
}
```

Archive copies of previous verdicts are stored at `engine/data/gate_v2_verdicts/archive/<SYMBOL>_<family>_rank<N>_pre-refresh-<YYYY-MM-DD>.json`. See `docs/strategy/VERDICT_LIFECYCLE.md` for the archive-refresh-compare sequence.

---

## Concrete Examples

### MES trend rank11 — PASS via ALT (2026-05-07 refresh)

**Instrument:** MES (Micro E-mini S&P 500), 1h bars, SMA(60,200,atr=2.0)
**WFO:** 16 windows (6-month IS, 1-month OOS, 1-month step)

```
Metric              Value    Threshold   Status
-----------         ------   ----------  ------
pf_ci_lower         2.4942   ≥ 1.10      CORE PASS (but p_edge FAILS CORE)
p_edge              0.7500   ≥ 0.95      CORE FAIL
mc_95th_dd_pct      0.8055%  ≤ 5%        CORE PASS
dsr                 1.0000   ≥ 0.10      CORE PASS

-- ALT path --
dsr                 1.0000   ≥ 0.30      ALT PASS
wfo_consistency     STRONG   MODERATE+   ALT PASS
fixed_params_min_pf 1.5237   ≥ 1.20      ALT PASS
cost_survives       catastrophic ≥ realist ALT PASS
mc_95th_dd_pct      0.8055%  ≤ 7%        ALT PASS

VERDICT: PASS (via alt)
```

**Paper config:** `MES_TREND_PAPER_CONFIG` — enabled, `$50K initial_capital`.
**Next refresh due:** ~2026-06-06 (30 days from 2026-05-07).

---

### MGC trend rank4 — PASS via ALT (2026-05-07 refresh)

**Instrument:** MGC (Micro Gold), 1h bars, SMA(50,120,atr=2.0)
**WFO:** 19 windows (6-month IS, 2-month OOS, 1-month step), 8-combo grid

```
Metric              Value    Threshold   Status
-----------         ------   ----------  ------
pf_ci_lower         NaN      ≥ 1.10      (NaN due to all-winning OOS — see note)
p_edge              0.6842   ≥ 0.95      CORE FAIL
mc_95th_dd_pct      1.2386%  ≤ 5%        CORE PASS
dsr                 1.0000   ≥ 0.10      CORE PASS

-- ALT path --
dsr                 1.0000   ≥ 0.30      ALT PASS
wfo_consistency     MODERATE MODERATE+   ALT PASS  ← softened from STRONG (2026-05-06 → 2026-05-07)
fixed_params_min_pf 1.3574   ≥ 1.20      ALT PASS
cost_survives       catastrophic ≥ realist ALT PASS
mc_95th_dd_pct      1.2386%  ≤ 7%        ALT PASS

VERDICT: PASS (via alt)
```

**Note on `pf_ci_lower = NaN`:** MGC's OOS PFs include windows where no losing trades occurred (PF = inf). The inf-cap in `bootstrap_pf_ci_lower` should prevent NaN, but if an older verdict was computed before commit `d1d70d2`, the NaN is a pre-fix artifact. The ALT path does not gate on `pf_ci_lower` directly, so this does not affect the verdict. Future refreshes on updated code will resolve to a finite number.

**Watch flag:** WFO softening (STRONG → MODERATE) between 2026-05-06 and 2026-05-07 refreshes. Still passes ALT; monitoring at next refresh (~2026-06-07).

**Paper config:** `MGC_PAPER_CONFIG` — enabled, `$50K initial_capital`, SMA(50,120,atr=2.0).

---

### MCL family — FAIL (exhausted)

**Instrument:** MCL (Micro Crude Oil), multiple strategy families
**Status:** `DO_NOT_TRADE_SYMBOLS` member

| Hypothesis | Strategy | Result | Key failure |
|-----------|----------|--------|------------|
| A | STC chop filter | FAIL | p_edge=0.18 |
| B | No sentiment overlay | FAIL | PF net-negative |
| C | RV-band gate | FAIL | pf_ci_lower=0.284, p_edge=0.000 |
| D | SMA Trend (1h) | FAIL | 4/18 OOS windows had trades; p_edge=0.75 |
| E | SMA Trend (1d) | FAIL | 0 OOS trades (daily crossovers too infrequent in 6-mo IS) |

5 hypotheses exhausted as of 2026-05-06. MCL is structurally unsuitable for the current strategies in the 2024-2026 regime. Any new hypothesis (e.g., macro/OPEC data) requires Amo authorization before a runner is written.

**MES mean-rev rank1 — FAIL (414 OOS trades, structural family FAIL):**
Mean-reversion on MES fights against the strong 2024-2025 trending-bull regime that powers the MES trend strategy. 9-combo Bollinger+RSI grid failed all 4 CORE and 5 ALT criteria. Mean-rev family on MES is parked in the current regime.

---

## Failure Modes

| Scenario | Runtime behavior | Alert |
|----------|------------------|-------|
| Verdict file missing | `NO_TRADE` for the symbol | Log `[GateV2Policy] eligible=False` — no verdict |
| Verdict stale (> 30 days) | `NO_TRADE` for the symbol | C6 check surfaces this in live_readiness |
| Verdict parse error (JSON corrupt) | `NO_TRADE` fail-safe; parser exception logged | C6 check fails |
| PASS → FAIL transition on refresh | Previous verdict archived; new FAIL blocks trading | Alert on verdict transition |
| `GATE_V2_ENFORCE_ROUTING=0` | Gate disabled; all signals pass through | No protection — DO_NOT_TRADE_SYMBOLS still enforced |
| `DO_NOT_TRADE_SYMBOLS` miss-set | PASS symbol in frozenset → blocked; FAIL symbol not in frozenset → unprotected | C7 check surfaces both cases |
| APScheduler cron stall | Verdicts age; stale in ≤ 30 days | Task 12 worklist: poll `created_at` ages daily, alert at 10 days |
| Bootstrap inf → NaN (pre-fix) | Spurious FAIL verdict written | Fixed in `d1d70d2` (2026-05-07): inf capped at 5.0 |

---

## Related Files

| File | Role |
|------|------|
| `engine/backtest/_gate_v2_helpers.py` | Shared helpers: `bootstrap_pf_ci_lower`, `classify_wfo_consistency`, `_find_latest_cache` |
| `engine/backtest/deflated_sharpe.py` | DSR implementation (Bailey-López de Prado 2014) |
| `engine/backtest/paper_config.py` | Paper trading configs; `initial_capital` enforces ALT routing requirement |
| `engine/backtest/signals.py` | `DO_NOT_TRADE_SYMBOLS` frozenset; `GATE_V2_ENFORCE_ROUTING` env check |
| `engine/backtest/live_readiness.py` | 7 live-readiness criteria; C6 (verdict staleness) + C7 (DO_NOT_TRADE sync) |
| `engine/backtest/run_mes_trend_rank11.py` | MES PASS-alt runner (reference implementation) |
| `engine/backtest/run_mgc_trend_rank4.py` | MGC PASS-alt runner |
| `engine/data/gate_v2_verdicts/` | Verdict JSON store (one file per active strategy) |
| `engine/data/gate_v2_verdicts/archive/` | Pre-refresh snapshots for audit trail |
| `docs/decisions/gate_v2_phase3_full.md` | Phase 3-FULL activation decision memo |
| `docs/strategy/VERDICT_LIFECYCLE.md` | Archive → WFO → compare → commit sequence |
| `docs/strategy/CACHE_FILENAME_CONTRACT.md` | Cache filename format required by `_find_latest_cache` |

---

## Glossary

| Term | Definition |
|------|-----------|
| **PF** | Profit Factor — ratio of gross winning PnL to gross losing PnL; PF > 1.0 is net-profitable |
| **CI** | Confidence Interval — range within which the true parameter falls with given probability |
| **OOS** | Out-of-Sample — data held back from the IS optimization window; the honest performance estimate |
| **IS** | In-Sample — data used for parameter selection (grid-search); not used for gate v2 metrics |
| **WFO** | Walk-Forward Optimization — rolling IS/OOS split technique that tests parameter robustness across time |
| **DSR** | Deflated Sharpe Ratio — Bailey et al. 2014 multiple-testing correction; p-value that the Sharpe survives N trial inflation |
| **mc_dd** | Monte Carlo 95th-percentile drawdown — empirical tail drawdown across OOS windows |
| **p_edge** | Probability of positive edge — fraction of OOS windows with PF > 1.0 |
| **ALT** | Alternative routing path — relaxed gate for strategies with strong WFO consistency but insufficient p_edge for CORE |
| **inf-cap** | The 5.0 ceiling applied to PF values before bootstrapping; prevents NaN from `inf - inf` interpolation |
| **fixed_min_pf** | Minimum PF across all grid combos on the full dataset; a floor test for parameter fragility |

---

## Commit History

| Commit | Date | Description |
|--------|------|-------------|
| `c8f4610` | 2026-04-21 | Gate v2 Phase 1 — dual-pathway validator |
| `3198364` | 2026-04-21 | Phase 2 + Phase 3-LIGHT (advisory mode) |
| `33c9ff2` | 2026-04-21 | Phase 3-FULL — `GATE_V2_ENFORCE_ROUTING` hard enforcement |
| `d1d70d2` | 2026-05-07 | Extract gate v2 helpers to `_gate_v2_helpers.py`; **inf-cap=5.0** NaN fix |
| `55739db` | 2026-05-07 | `_find_latest_cache` replaces hardcoded cache paths in both runners |
| (verdict) | 2026-05-07 | MES R11 + MGC R4 refreshed against bars through 2026-05-07 |

---

*Resolves recommendation 11G.1 from `HANDOFF_2026-05-07_validation_remediation_complete.md`.*
