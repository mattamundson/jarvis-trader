# JARVIS Morning Alpha Engine — Architecture Design Specification

**Version:** 1.0  
**Date:** 2026-09-15  
**Status:** Approved design direction; implementation planning pending written-spec review  
**Repository:** `mattamundson/jarvis-trader`

## 1. Objective

Turn the existing Morning Trade Setups workflow into a reproducible, auditable, research-grade subsystem inside JARVIS that uses the same deterministic strategy logic in both historical backtests and live scans. The system must discover high-quality U.S. equity/ETF setups, construct strict-risk trade plans, persist every surfaced and rejected candidate, audit outcomes using MFE/MAE and R-multiples, validate setup families with out-of-sample/walk-forward/cost/Monte-Carlo tests, and only promote empirically validated strategies to paper/live eligibility through the existing JARVIS Gate-v2 discipline.

## 2. Design Principles

1. **One strategy implementation for historical and live use.** No separate backtest-only strategy logic.
2. **Deterministic qualification before LLM commentary.** Python decides whether a setup qualifies; an LLM may explain catalysts/risks but cannot override hard gates.
3. **Point-in-time correctness.** Universe membership, earnings dates, sector mappings, prices, and catalysts must be evaluated using data available at the historical decision timestamp.
4. **Immutable research lineage.** Strategy changes create new version IDs; prior results are never silently overwritten.
5. **No forced trades.** If nothing clears all gates, the correct output is no trade/no notification.
6. **Small-account-first risk.** Default risk unit is approximately 0.5% of account equity; hard per-trade ceiling approximately 1.0% unless a future validated policy explicitly changes it.
7. **Portfolio heat is a first-class constraint.** Sector, factor, theme, and broad-market correlation must be considered before simultaneous positions are approved.
8. **Evidence before promotion.** Setup families must survive backtest, OOS, rolling WFO, cost/slippage stress, Monte Carlo, regime analysis, Gate-v2, and paper-forward observation before live eligibility.
9. **Failure is preserved.** Failed strategies, over-conservative triggers, filtered winners, and false positives remain in the research database.
10. **Provider independence.** Data, options, news, and brokerage adapters are interfaces, not strategy dependencies.

## 3. Recommended Architecture

### 3.1 New subsystem

Create a bounded subsystem under:

```text
engine/morning_alpha/
    models/
    providers/
    universe/
    regime/
    sectors/
    setups/
    catalysts/
    risk/
    portfolio/
    audit/
    research/
    reporting/
    cli/
```

Reuse existing `engine/backtest` indicators, validation utilities, Gate-v2 logic, and research conventions where compatible.

### 3.2 Core flow

```text
Providers
  -> PointInTimeSnapshot
  -> MarketRegimeEngine
  -> SectorRotationEngine
  -> Universe/LiquidityGate
  -> SetupDetectors
  -> CatalystEnrichment
  -> TradeConstruction
  -> HistoricalEdgeGate
  -> PortfolioHeatGate
  -> RankedTradePlans
  -> MorningReport
  -> SignalJournal
  -> OutcomeAudit
  -> ResearchMetrics
  -> PromotionGate
```

## 4. Provider Layer

Define protocol-style interfaces:

```python
class MarketDataProvider(Protocol): ...
class OptionsProvider(Protocol): ...
class NewsProvider(Protocol): ...
class BrokerProvider(Protocol): ...
class FundamentalProvider(Protocol): ...
class MacroDataProvider(Protocol): ...
```

### Initial provider mapping

- Market data: Alpaca Algo Trader Plus
- Options: Alpaca
- Broker/paper execution: Alpaca
- News/catalyst: Alpaca plus pluggable web/news provider
- Historical research store: Parquet/DuckDB
- Operational journal: PostgreSQL

### Later optional upgrade

Massive/Polygon-compatible adapter for all-market snapshots, richer premarket scanning, and deeper options data without changing strategy code.

## 5. Point-in-Time Data Model

Every scan must carry an `as_of` timestamp and source lineage.

Minimum objects:

```text
MarketSnapshot
SectorSnapshot
InstrumentSnapshot
CatalystSnapshot
MacroSnapshot
OptionChainSnapshot
```

Required metadata:

- source/provider
- ingestion timestamp
- market timestamp
- adjusted/unadjusted status
- session classification (premarket/RTH/after-hours)
- corporate-action handling
- data quality flags
- staleness

Historical runs must not use information published after the historical scan timestamp.

## 6. Universe and Liquidity Gate

Default research universe:

- U.S. common stocks and selected unlevered ETFs
- price >= $10
- average daily shares >= 750,000
- 20-day average dollar volume >= $50 million
- exclude OTC/penny stocks
- exclude securities failing spread/liquidity quality thresholds
- maintain historical/point-in-time universe eligibility

Thresholds are configuration, not embedded constants.

## 7. Market Regime Engine

Features should include:

- SPY/QQQ/IWM trend and relative leadership
- 8/21/34 EMA ribbon state where appropriate
- VIX/volatility regime
- ATR/range-consumption state
- market breadth
- Treasury-yield trend
- crude/commodity regime
- risk-on/risk-off classification
- major scheduled event flags (CPI, PPI, payrolls, FOMC, major option-expiry events)
- optional TRIN and credit-risk internals

Output is structured context, not a discretionary narrative.

## 8. Sector Rotation Engine

Track the 11 major sector ETFs:

`XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLC, XLB, XLU, XLRE`

Features:

- 1d/5d/20d/50d returns
- relative return vs SPY
- distance from 52-week high
- trend state
- volume acceleration
- breadth within sector
- optional industry subgroup strength

Output:

```python
SectorScore(
    sector,
    rank,
    relative_strength,
    trend_quality,
    rotation_state,
    confidence,
)
```

## 9. Setup Families v1

Each detector implements a common interface and returns a candidate without portfolio sizing.

```python
class SetupDetector(Protocol):
    setup_id: str
    version: str
    def evaluate(self, snapshot, context) -> SetupCandidate | None: ...
```

Initial independent setup families:

1. `RelativeStrengthBreakout`
2. `MomentumBreakout`
3. `PullbackContinuation`
4. `PostEarningsDrift`
5. `SectorRotation`
6. `GapContinuation`

Do not blend these initially. Measure each family separately before considering composites.

## 10. Catalyst Engine

Structured catalyst classes:

- earnings surprise
- guidance raise/cut
- revenue/ARR/bookings surprise
- analyst action
- M&A
- index inclusion/removal
- FDA/clinical event
- government/defense contract
- commodity/supply shock
- regulatory event
- macro event
- no verified catalyst

Catalysts must retain source URL, timestamp, and confidence. Unverified catalysts cannot be promoted to verified fields.

## 11. Trigger Laboratory

For every historical setup candidate, simulate alternative entry methods from the same pre-entry information set:

- market open
- prior-day-high/low break
- premarket-high/low break
- 5-minute ORB
- 15-minute ORB
- 30-minute ORB
- breakout + retest
- VWAP reclaim/rejection

The laboratory measures whether confirmation protects against losers or filters too many winners.

Metrics per trigger:

- N
- trigger rate
- expectancy
- median R
- win rate
- profit factor
- average MFE
- average MAE
- filtered-loser rate
- filtered-winner rate
- trigger efficiency
- cost sensitivity

No trigger may be selected merely because it maximizes in-sample performance.

## 12. Trade Construction Engine

A `TradePlan` must contain:

```text
symbol
strategy_id
strategy_version
setup_type
scan_timestamp
entry_trigger
stop
risk_per_share
account_equity
risk_pct
position_size
capital_required
target_1r
target_2r
target_3r
target_4r
nearest_obstacle
credible_max_reward_r
catalyst_context
regime_context
sector_context
correlation_tags
```

### Hard rules v1

- preferred risk: 0.5% account equity
- max risk: 1.0% account equity
- minimum credible reward: 2R
- no widening stops after entry merely to avoid a loss
- gap beyond trigger must be re-underwritten from the new structure; do not chase using stale R geometry

## 13. Portfolio Heat Engine

Model both nominal and effective risk.

Correlation dimensions:

- GICS sector
- industry
- broad factor (growth/value/small-cap)
- AI/data-center theme
- energy/oil theme
- biotech/event theme
- index beta
- rolling empirical correlation where sufficient history exists

Outputs:

```text
nominal_heat_pct
effective_heat_pct
capital_utilization_pct
sector_heat
factor_heat
correlation_penalties
approved_trade_subset
```

The optimizer should prefer diversified expectancy rather than simply the highest individual ranks.

## 14. Signal Journal and Daily Audit

Every surfaced candidate is persisted, including candidates that never trigger.

Outcome classification:

- `WIN`
- `LOSS`
- `OPEN_UNFINISHED`
- `FILTERED_WINNER`
- `FILTERED_LOSER`
- `UNVERIFIED`

Audit fields:

- trigger fired
- trigger timestamp
- assumed executable entry under configured slippage
- stop hit and timestamp
- session high/low after entry
- MFE dollars/R
- MAE dollars/R
- 1R/2R/3R/4R reached and timestamps
- close price and close-R
- realized R under exit policy
- rejection reason
- data-quality notes

Never count an untriggered setup as a win/loss.

## 15. Research Store

### DuckDB + Parquet

Use for large historical feature matrices, bars, event windows, and repeatable research datasets.

### PostgreSQL

Use for operational/audit state.

Recommended tables:

```text
strategy_versions
market_snapshots
sector_snapshots
signal_candidates
trade_plans
signal_outcomes
signal_excursions
portfolio_snapshots
backtest_runs
walk_forward_runs
gate_v2_results
paper_trades
live_trades
research_experiments
```

## 16. Backtest Engine Requirements

Historical and live paths must invoke the same detector and trade-construction functions.

Backtester must support:

- point-in-time universe
- premarket/RTH session boundaries
- trigger ordering from intraday bars
- configurable slippage
- commissions/fees
- gap-through-stop handling
- partial exits
- trailing exits
- close-based exits
- multi-day holds
- simultaneous-position capital constraints
- portfolio heat

## 17. Exit Policy Research

Compare independently by setup family:

- full exit at 1R
- full exit at 2R
- full exit at 3R
- 50% at 1R + trail
- 50% at 2R + trail
- ATR trail
- session close
- 2-day hold
- 5-day hold

No universal 2R-4R policy should be assumed optimal before validation.

## 18. Validation Framework

Required hierarchy:

```text
Hypothesis
 -> In-Sample Research
 -> Frozen Parameters
 -> Out-of-Sample
 -> Rolling Walk-Forward
 -> Transaction-Cost Stress
 -> Slippage Stress
 -> Monte Carlo
 -> Regime Stability
 -> Gate-v2
 -> Paper Forward Test
 -> Live Eligibility
```

Minimum reported metrics:

- trade count
- expectancy/trade
- median R
- win rate
- average winner/loser
- profit factor
- Sharpe
- Sortino
- Calmar
- max drawdown
- longest losing streak
- MFE/MAE
- MFE capture ratio
- trigger efficiency
- filtered winner/loser rates
- turnover
- exposure
- cost sensitivity
- risk of ruin / Monte Carlo DD distribution

Gate thresholds should reuse canonical JARVIS Gate-v2 where applicable rather than inventing a weaker parallel certification standard.

## 19. Strategy Registry and Versioning

Each strategy is machine-readable and immutable by version.

Example ID:

```text
relative_strength_breakout_v1
relative_strength_breakout_v2
```

Configuration should include universe, factors, thresholds, trigger, risk, exit policy, data dependencies, and validation status.

Never retroactively edit a certified version's parameters.

## 20. LLM Boundary

Python determines:

- qualification
- ranking inputs
- trigger
- stop
- R geometry
- size
- heat
- historical expectancy
- validation status

LLM may:

- summarize verified catalyst text
- identify qualitative risks for analyst review
- explain the setup
- produce the morning report narrative

LLM may not:

- override a hard reject
- fabricate missing catalyst data
- alter stops/targets after seeing outcomes
- promote an uncertified strategy

## 21. Promotion States

```text
IDEA
HYPOTHESIS
BACKTESTED
OOS_VALIDATED
WFO_VALIDATED
GATE_V2_CANDIDATE
PAPER
FORWARD_VALIDATED
LIVE_ELIGIBLE
MONITORED
DEGRADED
RETIRED
```

Transitions are explicit and auditable.

## 22. Morning Report Contract

If no candidate clears all required gates: no trade alert.

Otherwise report:

1. prior-run audit
2. rolling signal-quality scorecard
3. macro/regime state
4. sector rotation table
5. qualifying setups
6. entry/stop/size/targets/R
7. historical edge metrics for each strategy version
8. portfolio heat and correlation conflicts
9. verified catalyst context
10. unverified/inferred labels

## 23. Initial Implementation Sequence

1. provider interfaces + Alpaca adapter
2. canonical models and strategy-version registry
3. point-in-time universe/liquidity gate
4. signal journal PostgreSQL schema
5. historical Parquet/DuckDB loader
6. regime and sector engines
7. first five setup detectors independently
8. trade construction and risk sizing
9. deterministic outcome auditor (MFE/MAE/R)
10. backtest event simulator
11. trigger laboratory
12. portfolio heat engine
13. validation/Gate-v2 adapter
14. morning report generator
15. scheduler/CLI
16. paper execution integration only after validated strategies exist

## 24. Explicit Non-Goals for v1

- autonomous live brokerage execution
- reinforcement learning
- contextual bandits
- self-modifying strategy parameters
- LLM-generated trade qualification
- options strategies without reliable executable chain data
- optimizing dozens of thresholds simultaneously

These can be reconsidered only after the deterministic research foundation has sufficient observations.

## 25. Acceptance Criteria

The subsystem is considered research-ready when:

1. one strategy implementation runs unchanged against historical and live providers;
2. a historical run reproduces deterministic outputs from fixed input data;
3. every recommendation is journaled with immutable strategy/version lineage;
4. next-session audit calculates trigger status, MFE, MAE, target/stop sequence, and R classification;
5. trigger alternatives can be compared on the same historical candidate set;
6. portfolio simulation enforces capital and heat constraints;
7. OOS/WFO/cost/slippage/Monte-Carlo results are reproducible;
8. Gate-v2 can consume Morning Alpha research results;
9. the live morning report cannot surface strategies that lack the configured eligibility state;
10. no-trade is a valid and tested output.

## 26. Recommended Decision

Proceed with this subsystem as **Approach C**: a new `engine/morning_alpha/` package that reuses JARVIS validation infrastructure, starts Alpaca-first behind provider protocols, persists operational state in PostgreSQL and research data in DuckDB/Parquet, keeps strategy qualification deterministic, and treats the LLM strictly as a research/narrative layer.

This is the recommended architecture because it maximizes auditability, backtest/live parity, provider flexibility, and scientific falsifiability while minimizing the risk of building a visually impressive but statistically ungrounded trading system.
