# Volatility Options Next-Phase Plan — 2026-08-23

> **For Hermes:** Use `rules-jarvis-trader`, `volatility-options-research`, and `writing-plans` before implementing this plan task-by-task.

**Goal:** Convert JARVIS from a micro-futures price-strategy miner into a read-only SPY/QQQ/VIX volatility-regime research and opportunity-selection platform.

**Architecture:** Build a layered system: regime brain → historical validation → payoff math → option-chain snapshot ledger → opportunity board → paper shadow ledger. Do not automate orders or modify risk/live config in this phase.

**Tech Stack:** Python/Pandas/Pytest in `engine/analysis`, CLI scripts in `engine/scripts`, CSV/JSON artifacts in `engine/data/vol_regime`, existing options scaffolding in `engine/options` and `engine/backtest/options_backtester.py`.

---

## Executive recommendation

Proceed with a **two-track next phase**:

1. **Build the free-data Volatility Regime Brain now.** Use existing SPY/QQQ daily caches and free CBOE VIX/VIX3M histories. This is enough to test whether regimes separate future return/volatility distributions.
2. **Start real options-chain data collection in parallel.** For certification-grade research, synthetic Black-Scholes and delayed CBOE snapshots are insufficient. The best next paid service is **ThetaData Options Standard** or **ThetaData Options Pro** depending on whether we prioritize research-only or live-style replay.

Do **not** buy every provider up front. Buy the smallest service that removes the next blocker.

## Why this is the right next phase

The futures work produced a negative map:

- MGC: all tested deep families fail.
- MES 5m study families fail.
- MES trend exact config passes core but ±10% band collapses to `fixed_params_min_pf = 0.0319` and `cost_survives_through = none`.

The next edge must use dimensions not present in the old research class:

- implied vs realized volatility;
- skew;
- VIX term structure;
- event premium;
- defined-risk payoff geometry;
- real bid/ask/liquidity constraints.

## Provider / subscription recommendations

### Buy first if we want serious options research: ThetaData

**Recommendation:** buy **ThetaData Options Standard** first if available and budget-acceptable.

Why:

- Raw options data is the real certification bottleneck.
- Public pricing search shows ThetaData Options Standard around **$80/month**, with options history, tick-level data, option root snapshots, and historical access.
- Options Pro appears around **$160/month**, better if live-style quote replay/streaming becomes necessary.
- This is the best foundation for real-chain replay because it gives raw quote/trade data instead of only vendor-derived summaries.

Use case in JARVIS:

- Daily/intraday SPY/QQQ/VIX chain snapshots.
- Bid/ask/mid replay.
- Liquidity filters.
- Fill assumptions.
- Real Greeks/IV where available.
- Certification-grade payoff backtests.

### Buy second if we want proprietary volatility features: ORATS

**Recommendation:** consider **ORATS Delayed Data API** after the regime brain proves useful or if we want richer features immediately.

Why:

- ORATS has historical EOD options data back to 2007 and proprietary indicators: IV rank/percentiles, skew, kurtosis, smoothed market values, forecasts of implied volatility/slope.
- Public search shows individual delayed API pricing around **$99/month**.
- ORATS is better for high-level volatility features; ThetaData is better for raw replay.

Use case in JARVIS:

- IV rank / IV percentile.
- Skew and term structure from cleaned surfaces.
- Forecast HV/IV features.
- Faster signal research without building every volatility surface from raw quotes.

### Polygon / Massive Options Advanced

**Recommendation:** useful if the existing Polygon integration is restored and we want one provider for live-ish chain endpoints, but not my first pick for historical certification.

Why:

- Existing repo already has Polygon options hooks.
- Public search shows advanced options quote access around **$199/month** for real-time/all-history tiers.
- Current local memory says the Polygon key has returned 403 recently, so buying/upgrading only makes sense if we also fix key/account status.

Use case in JARVIS:

- Fast integration with existing code.
- Live chain snapshots.
- Supplemental provider, not necessarily the deepest research archive.

### CBOE DataShop

**Recommendation:** use selectively for VIX/SPX/VIX-options specialty data, not as the first broad provider.

Why:

- Strong for official CBOE products and VIX/SPX datasets.
- Likely à la carte / custom pricing.
- Best for specific VIX options/futures research once we know exactly what we need.

### Free data we should use immediately

- CBOE VIX history.
- CBOE VIX3M history.
- Existing SPY/QQQ daily caches.
- Existing CBOE delayed options snapshot code in `engine/analysis/options_implied.py` for current-market display, not certification.

## Phase 2 finish line

Phase 2 is complete when JARVIS can produce a **read-only Volatility Regime Research Report** with:

1. SPY/QQQ regime labels across full local history.
2. VIX/VIX3M context joined where available.
3. Forward 1d/3d/5d returns by regime.
4. Forward realized-vol expansion/contraction by regime.
5. Era splits: pre-COVID, COVID/stimulus, 2022 bear, high-rate era, recent era.
6. Bootstrap confidence intervals for regime forward returns and vol changes.
7. Explicit reject/accept decision for which regimes deserve payoff testing.
8. JSON/CSV artifacts under `engine/data/vol_regime/`.
9. Tests covering unit, fixture integration, CLI artifacts, and bootstrap math.

No execution. No routing. No live config changes.

---

# Implementation tasks

## Task 1: Finish CBOE VIX/VIX3M fetch support in regime study CLI

**Objective:** Allow `engine/scripts/vol_regime_study.py` to use free CBOE VIX/VIX3M history when local caches are missing.

**Files:**

- Modify: `engine/scripts/vol_regime_study.py`
- Test: `engine/tests/test_volatility_regime_exhaustive.py`

**Steps:**

1. Add `--fetch-cboe-vix` flag.
2. Implement safe fetch with timeout using stdlib or `httpx` if already available.
3. Parse CBOE CSV into date/close frame.
4. Cache fetched files under `engine/data/vol_regime/raw/`.
5. If fetch fails, continue with explicit `data_gaps` entry.
6. Add tests using monkeypatched fetch text, not network.

**Verification:**

```bash
cd engine
env -u PYTHONHOME PYTHONPATH=. C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe -m pytest tests/test_volatility_regime.py tests/test_volatility_regime_exhaustive.py -q
```

Expected: all tests pass.

## Task 2: Add historical era splits

**Objective:** Prevent one market era from dominating regime conclusions.

**Files:**

- Modify: `engine/analysis/volatility_regime.py`
- Modify: `engine/scripts/vol_regime_study.py`
- Test: `engine/tests/test_volatility_regime_exhaustive.py`

**Era buckets:**

- `pre_covid`: date < 2020-02-01
- `covid_stimulus`: 2020-02-01 through 2021-12-31
- `rate_hike_bear`: 2022-01-01 through 2022-12-31
- `high_rate_ai_cycle`: 2023-01-01 through 2024-12-31
- `recent`: date >= 2025-01-01

**Verification:**

- Synthetic fixture spanning era boundaries returns correct labels.
- Regime summary emits both all-history and per-era CSVs.

## Task 3: Add bootstrap confidence intervals

**Objective:** Attach statistical uncertainty to regime forward-return and forward-vol results.

**Files:**

- Modify: `engine/analysis/volatility_regime.py`
- Test: `engine/tests/test_volatility_regime_exhaustive.py`

**Implementation:**

- Bootstrap per regime / metric.
- Default `n_bootstrap=2000`, `seed=42`.
- Output mean, median, 5th/95th percentile for:
  - `fwd_return_1d`
  - `fwd_return_3d`
  - `fwd_return_5d`
  - `fwd_rv_5d_change`

**Acceptance:**

- Regime is considered worth payoff testing only if:
  - `n_days >= 100`, and
  - confidence interval does not collapse into pure noise, and
  - effect exists in at least two eras.

## Task 4: Add regime acceptance/rejection rules

**Objective:** Convert historical summaries into explicit research decisions.

**Files:**

- Modify: `engine/analysis/volatility_regime.py`
- Test: `engine/tests/test_volatility_regime_exhaustive.py`

**Rules:**

A regime can proceed to payoff testing only if at least one is true:

- Forward realized vol change is directionally stable by era.
- Forward return distribution is directionally stable by era.
- VIX/term structure state produces distinct outcomes vs baseline.

Reject when:

- sample size < 100 days;
- effect exists only in one era;
- forward return/vol effect has the wrong sign for proposed structures;
- result depends only on underlying trend and not volatility context.

## Task 5: Produce Phase 2 research report artifact

**Objective:** Generate a human-readable report from the study output.

**Files:**

- Create: `engine/scripts/vol_regime_report.py`
- Output: `engine/data/vol_regime/VOL_REGIME_RESEARCH_REPORT_<date>.md`
- Test: CLI artifact test.

**Report sections:**

1. Data sources and gaps.
2. Latest regime snapshot for SPY/QQQ.
3. Regime summary by all-history.
4. Regime summary by era.
5. Bootstrap confidence intervals.
6. Accepted regimes for payoff testing.
7. Rejected regimes and why.
8. Subscription/data blockers.

## Task 6: Start option-chain snapshot provider abstraction

**Objective:** Prepare for ThetaData/ORATS/Polygon without locking into one vendor.

**Files:**

- Create: `engine/options/snapshot_provider.py`
- Test: `engine/tests/test_options_snapshot_provider.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    underlying: str
    quote_ts: datetime
    expiry: date
    strike: float
    right: Literal["C", "P"]
    bid: float | None
    ask: float | None
    mid: float | None
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    open_interest: int | None
    volume: int | None
    provider: str
```

No live provider implementation required in this task. Just schema + validation + JSON/CSV serialization.

## Task 7: Add real-chain snapshot storage schema

**Objective:** Make future chain collection durable and audit-safe.

**Files:**

- Create: `engine/options/snapshot_store.py`
- Test: `engine/tests/test_options_snapshot_store.py`

**Storage:**

- SQLite first: `engine/data/options_chain_snapshots.db`.
- Tables:
  - `option_quotes`
  - `snapshot_runs`
  - `provider_health`

**Acceptance:**

- Insert a synthetic chain.
- Read it back exactly.
- Deduplicate by provider/quote_ts/contract.
- No secrets stored.

## Task 8: Build first payoff model tests

**Objective:** Verify defined-risk payoff math before strategy research.

**Files:**

- Create: `engine/analysis/options_payoffs.py`
- Test: `engine/tests/test_options_payoffs.py`

**Structures:**

- bull call debit spread;
- bear put debit spread;
- bull put credit spread;
- bear call credit spread;
- iron condor.

**Tests:**

- max profit;
- max loss;
- breakeven;
- expiry payoff at below/at/above strikes;
- invalid structure rejection.

## Task 9: Regime-conditioned payoff backtest skeleton

**Objective:** Connect accepted regimes to synthetic payoff tests, still marked exploratory.

**Files:**

- Create: `engine/backtest/vol_regime_payoff_backtest.py`
- Test: focused smoke test with synthetic data.

**Acceptance:**

- Only tests regimes accepted by Task 4.
- Outputs `synthetic_chain=true` warning.
- Refuses certification claims without real-chain data.

## Task 10: Dashboard opportunity-board plan, not implementation

**Objective:** Design the eventual read-only dashboard before coding UI.

**Files:**

- Create: `docs/roadmaps/VOL_OPTIONS_OPPORTUNITY_BOARD_SPEC_<date>.md`

**Columns:**

- symbol;
- regime;
- structure;
- EV / max loss;
- probability proxy;
- max loss;
- liquidity score;
- event-risk flag;
- recommendation: reject / watch / simulate.

No UI build until data outputs are stable.

---

## Verification commands for Phase 2

Focused tests:

```bash
cd C:/Users/mattm/ThinkorSwim/wt-vol-options-phase1/engine
env -u PYTHONHOME PYTHONPATH=. C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe -m pytest \
  tests/test_volatility_regime.py \
  tests/test_volatility_regime_exhaustive.py \
  tests/test_options_payoffs.py \
  tests/test_options_snapshot_provider.py \
  tests/test_options_snapshot_store.py \
  -q
```

Study run:

```bash
cd C:/Users/mattm/ThinkorSwim/wt-vol-options-phase1/engine
env -u PYTHONHOME PYTHONPATH=. C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe scripts/vol_regime_study.py --symbols SPY,QQQ --fetch-cboe-vix
```

Report run:

```bash
cd C:/Users/mattm/ThinkorSwim/wt-vol-options-phase1/engine
env -u PYTHONHOME PYTHONPATH=. C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe scripts/vol_regime_report.py
```

## Decision gates

### Gate A — regime brain useful

Proceed to payoff testing only if at least 2 regimes show stable forward-return or forward-vol separation across at least 2 eras.

### Gate B — synthetic payoff promising

Proceed to real-chain replay only if a defined-risk structure shows positive EV/max-loss under conservative synthetic assumptions and regime conditioning.

### Gate C — buy/activate provider

Buy/activate ThetaData or ORATS only when Gate A is passed or when we need real-chain snapshots for certification. If Amo wants maximum acceleration now, buy ThetaData first.

### Gate D — paper shadow ledger

No paper options execution until we have:

- real-chain snapshot storage;
- payoff model tests;
- candidate lifecycle ledger;
- 60+ trading days of simulated recommendations, or a historical real-chain replay strong enough to justify earlier paper simulation.

## Immediate next action

Complete Tasks 1-3 first:

1. Finish CBOE VIX/VIX3M fetch support.
2. Add era splits.
3. Add bootstrap confidence intervals.

This turns the current code from a regime-label generator into a research-grade regime evaluator.
