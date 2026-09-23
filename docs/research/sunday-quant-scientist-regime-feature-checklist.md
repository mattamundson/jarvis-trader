# Sunday Quant Scientist regime-feature checklist

Date: 2026-09-13
Wave: GitHub repo consolidation Wave 17
Source repo mined: `mattamundson/sunday-quant-scientist`
Target repo: `mattamundson/jarvis-trader`

Status: docs-only research-control artifact. This document does not authorize or implement live trading, paper order routing, broker routing, risk-limit changes, kill-switch changes, `.env` edits, API-key handling, PM2 changes, active instrument gate changes, or order behavior changes.

## Source provenance

Fresh readback source paths and hashes from `mattamundson/sunday-quant-scientist` default branch `main`:

| Source path | Evidence used | Blob / hash / size |
|---|---|---:|
| repository tree | Recursive GitHub tree readback | tree `962c673138a6b38974db803fe7ceec1a2f19c52a`, `truncated=false` |
| `README.md` | Repository description | blob `ca8eb94873eb8061c5c1b38d4ef6ef175866ffb7`, 161 bytes |
| `QS026-markov/01_markov.py` | Hidden Markov regime-state example using SPY log returns + high-low range | blob `67d05b3c7bd57fc388552ff96d1a42d7400c48c1`, 1,693 bytes |
| `QS027-pcr/01_pcr.py` | Principal component / factor-model exposure example | blob `dd11d6d67359ac1b3cfef3506c910a83fb5a0237`, 1,807 bytes |
| `QS028-flow-effects/01_flow_effects.py` | Calendar-flow / month-turn signal sketch on TLT | blob `5baebad18928bd6687261a6efa1df1ed11a1ddd5`, 1,931 bytes |
| `QS031-kelly/01_kelly.py` | Rolling Kelly leverage example using annual S&P 500 returns | blob `21f3f80478bdc4b88142626130a17f0e412239e1`, 2,803 bytes |
| `QS034-optimize-exits/01_optimize_exits.py` | Exit optimization over stop-loss, trailing-stop, and take-profit grids | blob `58252ae598cae46c86f9d136207cfaf63241fe00`, 4,905 bytes |
| `QS035-autocorrelation/01_autocorrelation.py` | ACF/PACF lag-dependency example on monthly E-mini S&P futures returns | blob `59dc258888eddfa76fdc38530df6ac9e22335b53`, 1,737 bytes |
| `QS040-cvar/01_cvar.py` | VaR/CVaR tail-loss estimation over a portfolio return distribution | blob `7ffd05fb5eaa709950a5e08f90efc3072463a7c6`, 3,902 bytes |
| `QS041-hurst-exponent/01_husrt_exponent.py` | Hurst exponent / rolling-volatility persistence example | blob `4cc743214cf7b1330529a8a29a2212aa8789de75`, 1,851 bytes |
| `QS044-tail-ratio/01_tail_ratio.py` | 95th/5th percentile tail-ratio metric | blob `aef9a29757eb48ce7950d65d703295421e8229ff`, 2,871 bytes |
| `QS045-mean-reversion/01_mean_reversion.py` | Cross-sectional mean-reversion factor and rebalance pattern | blob `55462805d4c625b7d1aa56eaf1b036c1d5123ca9`, 4,507 bytes |
| `QS047-skew-kurtosis/01_skew_kurtosis.py` | Fat-tail diagnostics using skew and kurtosis | blob `f6bfe5608795d83a0d20f9029a0445dd74d82d03`, 2,613 bytes |

Local source manifest: `C:/Users/mattm/AppData/Local/Temp/repo_consolidation_sources/wave17_source/selected_files_manifest.json`.

## JARVIS adaptation principle

The repository is useful as a compact quant-feature idea catalog, not as production trading code. JARVIS should mine it into a feature qualification process that decides whether a regime signal, tail metric, or sizing idea deserves a backtest card.

Safe value:

1. Convert educational snippets into named feature candidates with deterministic formulas.
2. Require point-in-time data provenance before any backtest consumes a feature.
3. Treat all sizing and exit-optimization examples as research-only until JARVIS cost, slippage, WFO, DSR, CVaR, and ruin-risk gates pass.

Hard boundary: no source example from this repo can place orders, size positions, alter JARVIS risk limits, change allowed instruments, or override strategy-registry promotion gates.

## Candidate feature map

| Source concept | Candidate JARVIS use | Minimum transformation before testing | Primary failure risk |
|---|---|---|---|
| Hidden Markov states on returns + range | Regime label for trend/chop/vol-expansion context | Fix training window, feature scale, state labels, as-of timestamps, and retraining cadence | Regime labels silently relabel after refit, creating non-replayable history |
| Autocorrelation / PACF | Lag-dependency screen for trend vs mean-reversion family selection | Rolling ACF/PACF with confidence bands and multiple-testing control | Small-sample lag mining and horizon leakage |
| Hurst exponent | Persistence / anti-persistence regime feature | Rolling Hurst by instrument/timeframe with minimum bar count and stability band | Estimator instability; false precision around 0.5 |
| Skew / kurtosis | Fat-tail warning and stress-test selector | Rolling distribution diagnostics, robust winsorization policy, and sample-size floor | Tail metrics dominated by one stale/bad print |
| Tail ratio | Asymmetric payoff diagnostic | Compare upper/lower tail ratio net of costs across train/OOS splits | Upside tail overfit without downside path risk |
| VaR / CVaR | Research risk metric and dashboard risk-context field | Historical + bootstrap CVaR by instrument/regime; compare against drawdown and ruin metrics | Treating normal-ish VaR as sufficient in fat tails |
| Kelly fraction | Upper-bound sizing research, never direct sizing | Fractional Kelly cap, drawdown/ruin simulation, parameter uncertainty haircut | Extreme leverage from unstable mean/std estimates |
| Exit optimization | Candidate exit-family exploration | Nested train/OOS exit grid with param-stability penalty and cost model | Optimizing exits on the same sample as entries |
| Factor/PCR exposure | SPY/QQQ options context and broad-market factor hygiene | Immutable factor universe, aligned calendars, explained-variance threshold, no future constituents | Lookahead in factor membership/returns |
| Calendar-flow effect | Hypothesis template for turn-of-month / event-window research | Pre-registered calendar rule and holiday/session calendar source | Calendar anomaly decay and data-snooping |
| Cross-sectional mean reversion | Equities/options-underlying research idea only | Universe definition, borrow/shorting constraints, liquidity filter, transaction-cost model | Not directly portable to MES futures or options scanner |

## Feature qualification gate

A Sunday Quant Scientist-derived feature may enter a JARVIS research queue only if all gate fields are explicit:

| Gate | Required evidence | Pass condition |
|---|---|---|
| Formula identity | Human-readable formula and code hash | Same inputs always produce same feature vector |
| Source lineage | Source repo, tree SHA, source file, local manifest hash | Reviewer can trace the idea to immutable readback evidence |
| Data authority | Dataset path/provider, timestamp column, adjustment policy, timezone | Data is point-in-time safe and not sourced from an interactive chart surface |
| Instrument boundary | Allowed symbols and blocked symbols | No operational use of MCL or MNQ; halted symbols remain non-operational examples only |
| Window discipline | Train/test/OOS split, rolling window length, warmup bars | Feature is never fit using data after the decision timestamp |
| Multiple-testing control | Number of tested features/windows/parameter grids | DSR or equivalent correction uses true campaign trial count |
| Stability | Rolling hit rate, feature sign consistency, parameter sensitivity | Edge survives adjacent windows and reasonable parameter perturbation |
| Economic rationale | Mechanism linking the feature to payoff | No pure pattern-mining promotion without a plausible market mechanism |
| Cost/slippage | Futures/options cost model and fill assumption | Net edge survives realistic and pessimistic cost tiers |
| Tail risk | Max drawdown, CVaR, skew/kurtosis, tail ratio, ruin simulation | Tail loss is quantified before any promotion candidate is scored |
| Registry status | `research_only`, `backtest_candidate`, `failed`, or `promoted_candidate` | Missing evidence fails closed to `research_only` or `failed` |

## Regime feature run-card schema

Future implementation can store a docs/tests-only schema shaped like this:

```json
{
  "feature_run_id": "sq_YYYYMMDD_symbol_timeframe_feature",
  "created_at_utc": "2026-09-13T00:00:00Z",
  "source": {
    "repo": "mattamundson/sunday-quant-scientist",
    "default_branch": "main",
    "tree_sha": "962c673138a6b38974db803fe7ceec1a2f19c52a",
    "source_paths": [],
    "selected_files_manifest": "C:/Users/mattm/AppData/Local/Temp/repo_consolidation_sources/wave17_source/selected_files_manifest.json"
  },
  "feature": {
    "name": "hurst_persistence_regime",
    "category": "regime|tail_risk|sizing|exit|factor|calendar|cross_sectional",
    "formula_version": "v1",
    "input_columns": [],
    "parameters": {},
    "warmup_bars": null,
    "fit_scope": "rolling_train_only|expanding_train_only|fixed_pretrained|not_fit"
  },
  "data": {
    "instrument": "SPY",
    "timeframe": "1d",
    "provider": "databento|ibkr|yfinance|fred|csv|other",
    "dataset_path": null,
    "start_utc": null,
    "end_utc": null,
    "timezone": "UTC",
    "adjustment_policy": null,
    "point_in_time_safe": false
  },
  "validation": {
    "train_windows": [],
    "test_windows": [],
    "oos_windows": [],
    "n_trials_true_campaign": null,
    "cost_model": null,
    "slippage_model": null,
    "metrics": {
      "cagr": null,
      "profit_factor": null,
      "trade_count": null,
      "observed_trades_per_year": null,
      "sharpe_observed_frequency": null,
      "max_drawdown_pct": null,
      "cvar_95_pct": null,
      "tail_ratio": null,
      "skew": null,
      "kurtosis": null,
      "ruin_probability": null
    },
    "stability": {
      "parameter_sensitivity": null,
      "regime_split": null,
      "feature_sign_stability": null
    }
  },
  "decision": {
    "status": "research_only|backtest_candidate|failed|promoted_candidate",
    "blocked_reasons": [],
    "may_place_order": false,
    "may_change_risk": false,
    "may_change_gate": false,
    "requires_safety_review_pr": false
  }
}
```

## Metric-specific controls

### SQ-1 — Hidden Markov regimes are labels, not truth

The source HMM example fits three Gaussian hidden states from SPY log returns and daily range, then colors prices by predicted state. JARVIS can use the idea only as a regime-label candidate.

Required controls:

- Fit only on training data for each historical decision date.
- Persist model seed, feature scale, training range, and state-label mapping.
- Label states by observed training-window characteristics, e.g. `low_vol_grind`, `high_range_selloff`, `mixed_chop`, not by arbitrary integer state ids.
- Recompute out-of-sample states without refitting on the OOS window.
- Compare against simpler transparent baselines such as realized volatility percentile, VIX regime, ATR percentile, and trend slope.

Acceptance check:

- A reviewer can replay a specific historical date and recover the same state label without using future bars.

### SQ-2 — Autocorrelation/Hurst gates choose family, not trade direction

Autocorrelation and Hurst can help decide whether to test trend-following or mean-reversion, but they do not create an order by themselves.

Required controls:

- Compute rolling ACF/PACF and Hurst on returns, not raw prices unless the hypothesis explicitly justifies raw-price persistence.
- Use confidence intervals and minimum window sizes.
- Pre-register lag horizons before testing entry logic.
- Treat `H > 0.5` as persistence evidence and `H < 0.5` as anti-persistence evidence only when the estimate is stable across adjacent windows.
- Gate the result through normal JARVIS backtest validation before any strategy-registry promotion.

Acceptance check:

- A feature card with autocorrelation/Hurst but no entry/exit backtest remains `research_only`.

### SQ-3 — Tail diagnostics are mandatory on every candidate

CVaR, tail ratio, skew, and kurtosis are directly useful because existing JARVIS gates already emphasize drawdown, DSR, and true sample size.

Required controls:

- Report historical CVaR at 95% and 99% when the sample supports it.
- Report skew and excess kurtosis on the exact net-return series used for scoring.
- Report tail ratio as `abs(p95_return) / abs(p5_return)` and state whether returns are gross or net of costs.
- Compare CVaR to max drawdown and Monte Carlo ruin probability; do not let one tail metric override the others.
- Flag any sample where fewer than 20 observations fall into the relevant tail bucket.

Acceptance check:

- A candidate with positive PF/Sharpe but unreported CVaR/skew/kurtosis/tail ratio is incomplete, not promoted.

### SQ-4 — Kelly is a research upper bound, never an execution input

The source Kelly example optimizes expected log growth from rolling annual S&P 500 mean/std estimates and can produce leverage above 1. JARVIS must never translate that directly into paper/live size.

Required controls:

- Treat full Kelly as an unstable theoretical upper bound.
- Apply fractional Kelly only in research simulations, with a default cap of 0.25 Kelly for sensitivity, not deployment.
- Haircut expected return and inflate volatility before sizing simulation.
- Run sequence-risk and ruin-risk Monte Carlo under cost/slippage tiers.
- Require a `[safety-review]` PR before any sizing logic can affect runtime config, risk, or order behavior.

Acceptance check:

- Any PR that wires Kelly output to order size, max position, risk limit, or broker routing is blocked unless it is explicitly scoped as `[safety-review]` with human approval.

### SQ-5 — Exit optimization must be nested

The source exit-optimization example sweeps stop-loss, trailing-stop, and take-profit values. This is useful only if JARVIS keeps entry discovery and exit selection separate enough to avoid overfitting.

Required controls:

- Lock entry logic before sweeping exits.
- Use nested train/test/OOS windows: inner loop selects exit parameters, outer loop scores untouched OOS.
- Penalize parameter islands; prefer broad stable plateaus.
- Include actual contract tick value, commissions, slippage, and overnight/session behavior.
- Record all tested exit types and stop ranges in the run card.

Acceptance check:

- A best exit selected on the same data used for final scoring is a failed validation, even if PF improves.

### SQ-6 — Factor and calendar features need point-in-time universes

PCR/factor exposure and calendar-flow examples are most useful as context overlays for SPY/QQQ/VIX research, not as standalone MES execution signals.

Required controls:

- Freeze factor universe as of the test date or use investable ETFs with available point-in-time data.
- Align calendars before joining factors, futures bars, options data, and macro events.
- State whether the feature is causal, contemporaneous context, or post-hoc explanation.
- Avoid future constituent leakage from static lists.
- Compare calendar-flow signals against holiday/session calendar baselines and transaction costs.

Acceptance check:

- Factor or calendar features with unknown membership/calendar provenance remain dashboard context only.

### SQ-7 — Cross-sectional mean reversion is not portable by default

The source mean-reversion example ranks equities cross-sectionally and rebalances long/short baskets. JARVIS cannot assume this transfers to MES/MGC/MCL/MNQ futures or to options underlyings without an explicit product decision.

Required controls:

- Define universe, liquidity, shorting/borrow availability, rebalance time, and execution venue.
- Simulate turnover and costs before ranking by returns.
- For SPY/QQQ/AAPL/TSLA options-underlying research, separate underlying signal quality from options-chain execution and Greeks.
- For futures, require a different hypothesis if there is no cross-section.
- Treat halted symbols as examples only; no operational use of MCL or MNQ.

Acceptance check:

- Cross-sectional outputs cannot feed futures order routing. They may generate research questions or dashboard context.

## Dashboard/reporting implications

A future dashboard or report integration should display these features as research context with explicit provenance:

- feature name and category,
- source file and source tree SHA,
- data provider and data freshness,
- point-in-time status,
- train/OOS split,
- trial count,
- cost/slippage tier,
- tail-risk metrics,
- promotion status,
- `may_place_order=false`, `may_change_risk=false`, `may_change_gate=false`.

Dashboard display must not depend on the source repo, yfinance, OpenBB, Zipline, vectorbt, or any notebook environment being available at runtime. Runtime pages should read already-generated immutable artifacts only.

## Failure modes to test explicitly

| Failure mode | Control |
|---|---|
| HMM state ids change after refit and historical labels drift | Persist state-label mapping and fit window per run |
| Hurst/autocorrelation used as a standalone trading signal | Require entry/exit run card before promotion |
| Full Kelly creates leverage or position-size recommendations | Research-only cap; runtime sizing changes require `[safety-review]` |
| Exit grid overfits the OOS sample | Nested validation and parameter-plateau check |
| CVaR calculated on gross returns while PF uses net returns | Run card states gross/net series for every metric |
| Static factor universe includes future constituents | Point-in-time universe or investable ETF factor set |
| Calendar anomaly ignores holidays/session definitions | Calendar source and session policy required |
| Tail ratio hides path-dependent drawdown | Report drawdown and MC ruin beside tail ratio |
| Source examples with execution code are treated as JARVIS authority | Source repo classified as educational reference only |
| Halted symbols leak into operational examples | JARVIS instrument boundary overrides source examples |

## Verification checklist for future implementation PRs

Minimum gates before any Sunday Quant Scientist-derived feature implementation can merge:

1. `git diff --name-only` confirms no forbidden trading runtime/config files changed.
2. Feature formula and code hash are stored in a run card or fixture.
3. Data provenance includes provider, dataset path, timestamp column, timezone, and adjustment policy.
4. Point-in-time tests prove no future bars, future labels, or future factor-universe membership are used.
5. Multiple-testing metadata records the true campaign trial count.
6. Tail-risk metrics include CVaR, skew, kurtosis, and tail ratio on the same scored return series.
7. Kelly or sizing research is explicitly disconnected from runtime order size.
8. Exit optimization uses nested validation and reports all tested stops/exits.
9. Dashboard integration, if any, is read-only and renders stale/missing data as incomplete, not green.
10. Engine tests run with the project venv and `env -u PYTHONPATH` for any pydantic/FastAPI imports.

## Safe next PR candidates

1. Add a docs/tests-only `regime_feature_run_card` JSON schema and one fixture for Hurst or CVaR.
2. Add a research script that computes CVaR/skew/kurtosis/tail ratio from an existing backtest equity curve without touching order routing.
3. Add a read-only dashboard evidence card that displays feature provenance and `research_only` status.
4. Add point-in-time unit tests for rolling feature calculation windows.

Blocked without a dedicated `[safety-review]` PR and explicit human approval:

- wiring Kelly or any feature output into runtime position sizing,
- changing risk limits, kill-switch, order behavior, broker routes, `.env`, or PM2,
- changing allowed/blocked instruments or active instrument gates,
- treating yfinance/OpenBB examples as certified JARVIS market-data authority,
- promoting a feature to paper/live trading without JARVIS backtest, WFO, DSR, cost, and tail-risk gates.
