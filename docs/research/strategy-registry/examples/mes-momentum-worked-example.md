# Worked example — strategy registry YAML (MES momentum)

**Status:** example · **Purpose:** concrete instantiation of `docs/research/strategy-registry-schema.md`
using the YAML record format. This is not a real strategy endorsement; it is a
template showing every field in context.

> This example draws on the `claude-trading-skills` edge-strategy-designer schema
> pattern (one YAML per strategy variant, with hypothesis_type, mechanism_tag,
> regime, entry/exit/risk sections, and validation_plan) and maps those concepts
> to the JARVIS registry fields. It is a teaching artifact, not a live strategy
> record. A real record must carry real data sources, real windows, real verdicts,
> and a completed backtest critique before it advances past `backtesting`.

---

```yaml
---
# Identity
strategy_id: mes-momentum-MST_15-30
name: "MES 15-min momentum — MST crossover (worked example)"
owner: strategy-research
created_date: 2026-09-23
updated_date: 2026-09-23
source_notes: >
  Template example. Pattern inspired by claude-trading-skills
  edge-strategy-designer schema (draft_edge_concept schema.md) and the JARVIS
  strategy-research operating model. Not an imported strategy; no external repo
  content is used verbatim.

# Hypothesis
hypothesis: >
  MES 15-minute bar momentum, measured as the slope of a short stochastic
  (MST) over a 15–30 bar lookback, provides a weak but durable directional
  edge during US equity session hours when the broader market regime is
  trending. The edge is expected to be small per trade and requires strict
  cost modeling and regime filtering to survive.
kill_criterion: >
  The strategy is wrong if a 3-year walk-forward test shows profit factor
  below 1.15 after modeled costs in any single rolling window, or if the
  strategy loses money in two consecutive months of paper shadow with the
  documented cost model. Either condition triggers closure review.
asset_class: "MES (E-mini S&P 500, micro futures)"
instruments: ["MES1!", "MES2!"]  # front-month continuous; see futures roll note
horizon: "Intraday, 1–8 bars after entry; no overnight hold"

# Data
data_sources:
  - name: Databento
    feed: MBP-15
    instruments: ["ESM3"]  # outright month; continuous constructed in post
    provenance: "Databento venue OPRA/CFE; adjusted for futures roll"
  - name: FRED/ALFRED
    series: ["VIXCLS", "DTWEXBGS"]
    role: regime_context_only
    provenance: "FRED; ALFRED vintage used for backtest point-in-time integrity"
features:
  - MST_slope_15 (stochastic momentum slope, 15-bar)
  - MST_slope_30 (stochastic momentum slope, 30-bar)
  - regime_filter: VIX percentile + DTWEXBGS trend flag (macro context, not direct signal)
bar_frequency: 15 minutes
data_contract_version: "1.0"  # databento_mbp_v1 adapter; tracked in data layer

# Parameters
parameter_set:
  mst_fast_period: 15
  mst_slow_period: 30
  entry_threshold: 0.05  # MST slope normalized
  exit_threshold: -0.02  # MST slope reversal
  regime_filter_enabled: true
parameter_count: 5  # ≤4 = robust band in backtest critique; 5 is warning-band edge
parameter_stability: >
  Walk-forward sensitivity: performance is stable (±15%) when mst_fast_period
  moves 12–18 and mst_slow_period moves 25–35. Performance degrades >25% when
  entry_threshold moves outside 0.03–0.07, indicating a genuine threshold
  dependence that should be monitored.

# Testing
backtest_window:
  start: "2022-01-03"
  end: "2025-12-31"
  regimes_covered: ["low_vol_bull_2022H1", "high_vol_2022H2", "regime_chop_2023",
                    "trend_2024", "high_vol_2025"]
oos_window:
  start: "2026-01-02"
  end: "2026-09-15"
  note: "Rolling 6-month OOS; not independent of in-sample parameter selection"
trade_count: 342  # in-sample; ≥30/yr threshold met, but OOS trade count must also be stated
backtest_critique_ref: "docs/research/backtest-critique-mes-momentum-MST_15-30-2026-10-01.md"
backtest_verdict: "Refine"  # example verdict: advance not yet warranted
walkforward_ref: null
walkforward_verdict: null

# Paper shadow
paper_start_date: null
paper_status: null
paper_min_duration_met: false
paper_result_ref: null

# Promotion state
promotion_state: "backtesting"  # hypothesis documented + backtest run; critique says Refine
live_start_date: null
live_status: null

# Closure
closure_reason: null
closure_date: null

# Observability
probes:
  - ib_gateway_connectivity
  - engine_health
  - feed_freshness(databento_mbp_15)
  - paper_order_drift
freshness_gates:
  - feed: Databento MBP-15
    max_age_bars: 2  # 30 minutes at 15-min frequency
    action_on_stale: "halt_new_entries"

# JARVIS-specific gates (from backtest-critique-checklist.md §3)
jarvis_gates:
  data_provenance: "Pass — Databento + FRED/ALFRED with provenance notes"
  point_in_time_integrity: "Pass — ALFRED vintage used for macro features in backtest"
  futures_roll_validation: "Pass — outright-month bars used; continuous constructed in post with roll adjustment"
  regime_split_reported: "Pass — 5 regime buckets in backtest window, OOS regime composition noted"
  execution_model_coherence: "Pass — 1.5x slippage on MES, IB commission modeled"
  circuit_breaker_coherence: "Pass — strategy risk budget respects account-level drawdown circuit breaker"
  kill_criterion_written: "Pass — explicit PF and paper-loss thresholds above"
  no_live_config_mutation: "Pass — strategy record does not change any live config"
  paper_shadow_duration_gate: "Not yet applicable — paper shadow not started"
```
