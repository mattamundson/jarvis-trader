# JARVIS Morning Alpha Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a research-grade Morning Alpha subsystem that uses the same deterministic strategy logic for historical backtests and live scans, persists every candidate and outcome, audits MFE/MAE and R-multiples, controls small-account risk and portfolio heat, and promotes only empirically validated setup families through the existing JARVIS Gate-v2 lifecycle.

**Architecture:** Add an isolated `engine/morning_alpha/` package with explicit provider, domain-model, setup, risk, portfolio, audit, research, and reporting boundaries. Live Alpaca data and historical Parquet/DuckDB data feed the same `SetupDetector` and `TradeConstructor` interfaces; PostgreSQL stores the operational signal journal while DuckDB/Parquet stores research-scale history. Existing `engine/backtest` indicators, WFO utilities, and canonical Gate-v2 logic remain the validation source of truth.

**Tech Stack:** Python 3.12 runtime baseline (repo supports >=3.10), pandas, numpy, pydantic v2, alpaca-py, psycopg2, DuckDB/Parquet (new dependency if not already transitive), pytest, existing JARVIS `engine/backtest` validation utilities.

**Spec:** `docs/superpowers/specs/2026-09-15-morning-alpha-engine-design.md`

## Global Constraints

- Historical and live modes MUST execute the same setup qualification and trade-construction code.
- Every market/catalyst object MUST include an `as_of` timestamp plus provider/source lineage.
- Historical evaluation MUST NOT use information published after the decision timestamp.
- Strategy changes create a new immutable `strategy_id` + semantic `version`; historical results are never overwritten.
- `NO_TRADE` is a valid result; the scanner must never manufacture a setup to satisfy a quota.
- Default account risk is 0.5% of equity; hard v1 per-trade ceiling is 1.0%.
- New long setups require at least 2.0R credible reward after nearby structural obstacles are accounted for.
- Portfolio heat and correlated factor exposure are hard gates, not report-only annotations.
- LLM/news narrative cannot override deterministic liquidity, risk, R:R, or validation gates.
- Options remain disabled unless executable bid/ask, IV, skew, OI/liquidity, and realistic fill quality are all available and pass explicit asymmetry rules.
- Gate-v2 integration MUST call the canonical validation path in `engine/backtest/wfo_lifecycle.py`; do not duplicate Gate-v2 formulas in `morning_alpha`.
- No autonomous live order submission is added in v1. Paper/live eligibility is a state, not execution authorization.
- All new unit tests run under the repo default pytest selection without requiring IB Gateway, live brokerage credentials, or network access.

---

## File Structure

```text
engine/morning_alpha/
    __init__.py
    config.py
    models.py
    clock.py
    providers/
        __init__.py
        protocols.py
        alpaca_market_data.py
        historical_parquet.py
        fake.py
    universe/
        __init__.py
        eligibility.py
    regime/
        __init__.py
        engine.py
    sectors/
        __init__.py
        rotation.py
    setups/
        __init__.py
        base.py
        relative_strength_breakout.py
        momentum_breakout.py
        pullback_continuation.py
        post_earnings_drift.py
        sector_rotation.py
        gap_continuation.py
    risk/
        __init__.py
        trade_constructor.py
    portfolio/
        __init__.py
        heat.py
    journal/
        __init__.py
        repository.py
        postgres.py
        schema.sql
    audit/
        __init__.py
        outcome.py
        scorecard.py
    research/
        __init__.py
        simulator.py
        trigger_lab.py
        metrics.py
        gate_v2_adapter.py
    reporting/
        __init__.py
        morning_report.py
    service.py
    cli.py

tests/morning_alpha/
    test_models.py
    test_universe.py
    test_regime.py
    test_sector_rotation.py
    test_setup_detectors.py
    test_trade_constructor.py
    test_portfolio_heat.py
    test_journal_repository.py
    test_outcome_audit.py
    test_trigger_lab.py
    test_gate_v2_adapter.py
    test_service_parity.py
    test_reporting.py
```

---

### Task 1: Canonical domain models, configuration, and deterministic clock

**Files:**
- Create: `engine/morning_alpha/__init__.py`
- Create: `engine/morning_alpha/models.py`
- Create: `engine/morning_alpha/config.py`
- Create: `engine/morning_alpha/clock.py`
- Test: `engine/tests/morning_alpha/test_models.py`

**Interfaces:**
- Produces: `MarketBar`, `InstrumentSnapshot`, `SectorSnapshot`, `MarketRegime`, `CatalystSnapshot`, `SetupCandidate`, `TradePlan`, `SignalOutcome`, `StrategyKey`, `Clock`, `SystemClock`, `FrozenClock`, `MorningAlphaConfig`.
- Consumed by every later task.

- [ ] **Step 1: Write failing model invariants tests**

```python
from datetime import UTC, datetime

import pytest

from morning_alpha.models import StrategyKey, TradePlan


def test_strategy_key_is_versioned():
    key = StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0")
    assert key.canonical == "relative_strength_breakout@1.0.0"


def test_trade_plan_rejects_less_than_two_r():
    with pytest.raises(ValueError, match="minimum 2.0R"):
        TradePlan(
            symbol="XYZ",
            strategy=StrategyKey(strategy_id="rs", version="1.0.0"),
            as_of=datetime(2026, 9, 15, 13, 0, tzinfo=UTC),
            side="long",
            entry=100.0,
            stop=98.0,
            targets=(102.0, 103.0),
            risk_per_share=2.0,
            account_equity=3000.0,
            risk_fraction=0.005,
            shares=7,
            max_dollar_risk=14.0,
            expected_r=1.5,
        )
```

- [ ] **Step 2: Run the failing tests**

Run: `cd engine && pytest tests/morning_alpha/test_models.py -v`

Expected: FAIL because `morning_alpha.models` does not exist.

- [ ] **Step 3: Implement immutable Pydantic models and clock abstraction**

Use frozen `BaseModel` classes. Minimum `TradePlan` validator rules:

```python
if self.risk_fraction <= 0 or self.risk_fraction > 0.01:
    raise ValueError("risk_fraction must be > 0 and <= 0.01")
if self.expected_r < 2.0:
    raise ValueError("trade plan requires minimum 2.0R expected reward")
if self.side == "long" and not self.stop < self.entry:
    raise ValueError("long stop must be below entry")
```

`FrozenClock.now()` must return a supplied timezone-aware timestamp; reject naive datetimes.

- [ ] **Step 4: Implement config defaults from the approved spec**

```python
class MorningAlphaConfig(BaseModel):
    account_equity: float = 3000.0
    default_risk_fraction: float = 0.005
    max_risk_fraction: float = 0.01
    min_expected_r: float = 2.0
    min_price: float = 10.0
    min_avg_daily_shares: int = 750_000
    min_avg_dollar_volume_20d: float = 50_000_000.0
    max_initial_portfolio_heat: float = 0.0125
    max_theme_heat: float = 0.01
```

- [ ] **Step 5: Run tests and static checks**

Run:

```bash
cd engine
pytest tests/morning_alpha/test_models.py -v
ruff check morning_alpha/models.py morning_alpha/config.py morning_alpha/clock.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/morning_alpha engine/tests/morning_alpha/test_models.py
git commit -m "feat(morning-alpha): add canonical domain models"
```

---

### Task 2: Provider protocols and deterministic fake provider

**Files:**
- Create: `engine/morning_alpha/providers/__init__.py`
- Create: `engine/morning_alpha/providers/protocols.py`
- Create: `engine/morning_alpha/providers/fake.py`
- Test: `engine/tests/morning_alpha/test_provider_protocols.py`

**Interfaces:**
- Produces: `MarketDataProvider`, `NewsProvider`, `OptionsProvider`, `FundamentalProvider`, `MacroDataProvider`, `HistoricalProvider`, `FakeMarketDataProvider`.
- All provider methods take explicit `as_of` or start/end timestamps; no hidden `datetime.now()` calls.

- [ ] **Step 1: Write protocol-shape and point-in-time tests**

```python
from datetime import UTC, datetime

from morning_alpha.providers.fake import FakeMarketDataProvider


def test_fake_provider_never_returns_future_bars():
    as_of = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)
    provider = FakeMarketDataProvider.from_rows(
        "XYZ",
        [
            (datetime(2026, 9, 15, 13, 59, tzinfo=UTC), 100, 101, 99, 100, 1000),
            (datetime(2026, 9, 15, 14, 1, tzinfo=UTC), 100, 102, 99, 101, 1200),
        ],
    )
    bars = provider.bars("XYZ", as_of=as_of, limit=100)
    assert all(bar.timestamp <= as_of for bar in bars)
```

- [ ] **Step 2: Run test to confirm failure**

Run: `cd engine && pytest tests/morning_alpha/test_provider_protocols.py -v`

- [ ] **Step 3: Implement protocols**

Required core signature:

```python
class MarketDataProvider(Protocol):
    def instrument_snapshot(self, symbol: str, *, as_of: datetime) -> InstrumentSnapshot: ...
    def bars(self, symbol: str, *, as_of: datetime, limit: int, timeframe: str = "1Day") -> list[MarketBar]: ...
    def batch_snapshots(self, symbols: Sequence[str], *, as_of: datetime) -> dict[str, InstrumentSnapshot]: ...
```

- [ ] **Step 4: Implement fake provider with future-data guard**

A provider request must raise `PointInTimeViolation` if fixture lineage includes data stamped after `as_of` and the caller asks to expose it explicitly.

- [ ] **Step 5: Run tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_provider_protocols.py -v
ruff check morning_alpha/providers
git add engine/morning_alpha/providers engine/tests/morning_alpha/test_provider_protocols.py
git commit -m "feat(morning-alpha): define provider contracts"
```

---

### Task 3: Alpaca live adapter and historical Parquet adapter

**Files:**
- Create: `engine/morning_alpha/providers/alpaca_market_data.py`
- Create: `engine/morning_alpha/providers/historical_parquet.py`
- Modify: `engine/requirements.txt`
- Modify: `engine/.env.example`
- Test: `engine/tests/morning_alpha/test_alpaca_adapter.py`
- Test: `engine/tests/morning_alpha/test_historical_parquet.py`

**Interfaces:**
- Produces: `AlpacaMarketDataProvider`, `ParquetHistoricalProvider` implementing Task 2 contracts.
- Consumes: models from Task 1.

- [ ] **Step 1: Add local dependencies and environment contract**

Add explicit dependencies if absent:

```text
duckdb>=1.1.0
pyarrow>=17.0.0
```

Add environment variables:

```text
MORNING_ALPHA_ALPACA_API_KEY=
MORNING_ALPHA_ALPACA_SECRET_KEY=
MORNING_ALPHA_ALPACA_FEED=sip
MORNING_ALPHA_DATA_DIR=./data/morning_alpha
```

- [ ] **Step 2: Write adapter tests with monkeypatched Alpaca clients**

Test that timestamps are UTC, premarket bars retain session classification, and `as_of` filtering occurs after vendor response normalization.

- [ ] **Step 3: Implement Alpaca adapter**

Use `alpaca-py` stock historical/snapshot clients already pinned in `engine/requirements.txt`. Do not put API keys in constructors by default; load through `pydantic-settings` configuration.

- [ ] **Step 4: Implement Parquet adapter using DuckDB predicate pushdown**

The adapter query must include `timestamp <= ?` in SQL rather than loading all history and filtering in Python.

- [ ] **Step 5: Run isolated tests**

```bash
cd engine
pytest tests/morning_alpha/test_alpaca_adapter.py tests/morning_alpha/test_historical_parquet.py -v
```

- [ ] **Step 6: Commit**

```bash
git add engine/requirements.txt engine/.env.example engine/morning_alpha/providers engine/tests/morning_alpha
git commit -m "feat(morning-alpha): add live and historical data adapters"
```

---

### Task 4: Point-in-time universe and liquidity eligibility

**Files:**
- Create: `engine/morning_alpha/universe/__init__.py`
- Create: `engine/morning_alpha/universe/eligibility.py`
- Test: `engine/tests/morning_alpha/test_universe.py`

**Interfaces:**
- Produces: `UniverseEligibility`, `EligibilityDecision`, `eligible_universe(...)`.
- Consumes: historical instrument metadata and config.

- [ ] **Step 1: Write eligibility tests**

Cover price floor, ADV floor, 20-day dollar-volume floor, leveraged ETF exclusion, stale data rejection, and historical membership `effective_from <= as_of < effective_to`.

- [ ] **Step 2: Implement explicit rejection reasons**

```python
class EligibilityReason(StrEnum):
    ELIGIBLE = "eligible"
    PRICE_TOO_LOW = "price_too_low"
    ADV_TOO_LOW = "adv_too_low"
    DOLLAR_VOLUME_TOO_LOW = "dollar_volume_too_low"
    LEVERAGED_ETF = "leveraged_etf"
    STALE = "stale"
    NOT_ACTIVE_AS_OF = "not_active_as_of"
```

Every rejected candidate is persisted later; never return only a bool.

- [ ] **Step 3: Run tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_universe.py -v
git add engine/morning_alpha/universe engine/tests/morning_alpha/test_universe.py
git commit -m "feat(morning-alpha): add point-in-time universe gate"
```

---

### Task 5: Market regime and 11-sector rotation engines

**Files:**
- Create: `engine/morning_alpha/regime/__init__.py`
- Create: `engine/morning_alpha/regime/engine.py`
- Create: `engine/morning_alpha/sectors/__init__.py`
- Create: `engine/morning_alpha/sectors/rotation.py`
- Test: `engine/tests/morning_alpha/test_regime.py`
- Test: `engine/tests/morning_alpha/test_sector_rotation.py`

**Interfaces:**
- Produces: `MarketRegimeEngine.evaluate(...) -> MarketRegime`, `SectorRotationEngine.rank(...) -> list[SectorScore]`.
- Uses existing JARVIS indicator implementations where semantics match rather than reimplementing EMA/ATR functions.

- [ ] **Step 1: Write deterministic regime tests**

Fixture examples must assert `TRENDING_BULL`, `TRENDING_BEAR`, `RISK_OFF`, `VOLATILE`, and `EVENT_RISK` flags from synthetic SPY/QQQ/IWM/VIX/yield/oil inputs.

- [ ] **Step 2: Implement regime feature extraction**

Required v1 fields:

```text
spy_trend
qqq_trend
iwm_relative_strength
vix_bucket
breadth_score
ten_year_yield_trend
crude_trend
scheduled_event_risk
risk_state
```

- [ ] **Step 3: Write sector ranking tests using all 11 canonical ETFs**

Expected list:

```python
SECTOR_ETFS = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLC", "XLB", "XLU", "XLRE")
```

- [ ] **Step 4: Implement normalized sector score**

Use deterministic weighted components stored separately in `SectorScore` so later research can recompute alternative weights without losing raw features. Initial score may combine percentile ranks of 5d/20d/50d relative return, trend quality, 52-week proximity, and volume acceleration. Do not claim those weights are validated; mark version `sector_rotation_score@0.1.0-research`.

- [ ] **Step 5: Run tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_regime.py tests/morning_alpha/test_sector_rotation.py -v
git add engine/morning_alpha/regime engine/morning_alpha/sectors engine/tests/morning_alpha
git commit -m "feat(morning-alpha): add regime and sector rotation context"
```

---

### Task 6: Setup detector contract and six independent v1 families

**Files:**
- Create: `engine/morning_alpha/setups/base.py`
- Create: `engine/morning_alpha/setups/relative_strength_breakout.py`
- Create: `engine/morning_alpha/setups/momentum_breakout.py`
- Create: `engine/morning_alpha/setups/pullback_continuation.py`
- Create: `engine/morning_alpha/setups/post_earnings_drift.py`
- Create: `engine/morning_alpha/setups/sector_rotation.py`
- Create: `engine/morning_alpha/setups/gap_continuation.py`
- Create: `engine/morning_alpha/setups/__init__.py`
- Test: `engine/tests/morning_alpha/test_setup_detectors.py`

**Interfaces:**
- Produces: `SetupDetector.evaluate(snapshot, context) -> SetupCandidate | None` and six versioned implementations.
- A detector identifies a setup and proposed structural levels only; it does not size the position or approve portfolio heat.

- [ ] **Step 1: Write a shared detector contract test**

Each detector must expose `strategy: StrategyKey`, deterministic `evaluate`, `explain_features`, and never use network calls directly.

- [ ] **Step 2: Implement RelativeStrengthBreakout v1**

Research rule set:

```text
price >= 98% of 252-session high
20d return > SPY 20d return
20d return > sector ETF 20d return
price > 20d SMA > 50d SMA
candidate trigger = prior session high + max($0.01, 0.03 * ATR14)
```

Store each condition and value in `candidate.features`; do not hide rejected subconditions.

- [ ] **Step 3: Implement MomentumBreakout v1**

Research rule set:

```text
20d return percentile >= 80 within eligible universe
price > 20d and 50d SMA
relative volume >= 1.5 when intraday volume projection is available
trigger above 20-session high
```

- [ ] **Step 4: Implement PullbackContinuation v1**

Require established uptrend, controlled pullback toward 8/21 EMA region, no close below 50d SMA, and reclaim trigger above prior bar high.

- [ ] **Step 5: Implement PostEarningsDrift v1**

Require point-in-time earnings event, positive surprise fields when verified, positive gap, gap retention, elevated volume, and no use of guidance/news published after `as_of`.

- [ ] **Step 6: Implement SectorRotation v1**

Require sector rank in top quartile plus instrument RS above its sector benchmark and SPY.

- [ ] **Step 7: Implement GapContinuation v1**

Require qualifying gap, liquidity, acceptance/retention condition, and explicit gap-fill invalidation area.

- [ ] **Step 8: Run tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_setup_detectors.py -v
git add engine/morning_alpha/setups engine/tests/morning_alpha/test_setup_detectors.py
git commit -m "feat(morning-alpha): add independent setup families"
```

---

### Task 7: Risk construction and small-account position sizing

**Files:**
- Create: `engine/morning_alpha/risk/__init__.py`
- Create: `engine/morning_alpha/risk/trade_constructor.py`
- Test: `engine/tests/morning_alpha/test_trade_constructor.py`

**Interfaces:**
- Produces: `TradeConstructor.build(candidate, account, obstacles) -> TradePlan | Rejection`.
- Enforces risk, minimum 2R, integer shares, capital usage, and structural-stop semantics.

- [ ] **Step 1: Write exact sizing tests**

```python
def test_3000_account_at_half_percent_risk_sizes_integer_shares():
    # entry 100, stop 98 => $2/share risk; $15 budget => floor(7.5) = 7 shares
    result = constructor.build(candidate(entry=100, stop=98), account_equity=3000)
    assert result.shares == 7
    assert result.max_dollar_risk == 14.0
```

Also test 1% hard ceiling, zero-share rejection, gap-destroyed R:R rejection, and nearby resistance reducing credible reward below 2R.

- [ ] **Step 2: Implement deterministic sizing**

Formula:

```python
risk_budget = account_equity * min(requested_risk_fraction, config.max_risk_fraction)
risk_per_share = abs(entry - stop)
shares = floor(risk_budget / risk_per_share)
max_dollar_risk = shares * risk_per_share
```

- [ ] **Step 3: Implement R ladder and credible-upside gate**

Targets are `entry + R * risk_per_share` for longs (inverse for shorts), but `expected_r` is capped by the nearest verified structural obstacle unless price discovery removes the obstacle. Reject if credible expected reward < 2.0R.

- [ ] **Step 4: Run tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_trade_constructor.py -v
git add engine/morning_alpha/risk engine/tests/morning_alpha/test_trade_constructor.py
git commit -m "feat(morning-alpha): add strict trade construction"
```

---

### Task 8: Portfolio heat and correlation/theme gate

**Files:**
- Create: `engine/morning_alpha/portfolio/__init__.py`
- Create: `engine/morning_alpha/portfolio/heat.py`
- Test: `engine/tests/morning_alpha/test_portfolio_heat.py`

**Interfaces:**
- Produces: `PortfolioHeatGate.evaluate(existing, proposed) -> PortfolioDecision`.
- Consumes `TradePlan` plus sector/theme/factor tags.

- [ ] **Step 1: Write correlation-bucket tests**

Test that HPE + NVDA + SMH are treated as correlated AI/semiconductor-infrastructure exposure even if GICS sectors differ; XLE + CVX count toward one energy bucket; CNC + XLE remain largely independent.

- [ ] **Step 2: Implement hard v1 limits**

```text
initial total heat <= 1.25% default
single trade <= 1.00%
correlated theme heat <= 1.00%
```

Limits remain configuration and later validation may create a new policy version.

- [ ] **Step 3: Add empirical rolling-correlation hook**

If 60-session correlation data is available, record it as evidence, but do not let missing correlation silently bypass manually tagged theme limits.

- [ ] **Step 4: Run tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_portfolio_heat.py -v
git add engine/morning_alpha/portfolio engine/tests/morning_alpha/test_portfolio_heat.py
git commit -m "feat(morning-alpha): enforce portfolio heat gates"
```

---

### Task 9: Immutable signal journal with PostgreSQL implementation

**Files:**
- Create: `engine/morning_alpha/journal/__init__.py`
- Create: `engine/morning_alpha/journal/repository.py`
- Create: `engine/morning_alpha/journal/postgres.py`
- Create: `engine/morning_alpha/journal/schema.sql`
- Test: `engine/tests/morning_alpha/test_journal_repository.py`

**Interfaces:**
- Produces: `SignalJournal` protocol, `InMemorySignalJournal`, `PostgresSignalJournal`.
- Persists candidates, rejections, plans, outcomes, provider lineage, and strategy versions.

- [ ] **Step 1: Define schema with append-only research lineage**

Core tables:

```sql
CREATE TABLE strategy_versions (... UNIQUE(strategy_id, version));
CREATE TABLE signal_candidates (... candidate_id UUID PRIMARY KEY, as_of TIMESTAMPTZ NOT NULL, features JSONB NOT NULL);
CREATE TABLE trade_plans (... candidate_id UUID NOT NULL REFERENCES signal_candidates(candidate_id));
CREATE TABLE signal_outcomes (... candidate_id UUID NOT NULL, audit_as_of TIMESTAMPTZ NOT NULL, classification TEXT NOT NULL);
```

Never update a historical candidate to change its strategy version or original levels; later observations append outcome/audit rows.

- [ ] **Step 2: Write repository contract tests using InMemorySignalJournal**

Tests must prove a candidate can be retrieved exactly as originally recorded and an outcome cannot retroactively alter entry/stop/targets.

- [ ] **Step 3: Implement psycopg2 Postgres adapter**

Use explicit transactions and JSON serialization. No ORM dependency is required for v1.

- [ ] **Step 4: Run unit tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_journal_repository.py -v
git add engine/morning_alpha/journal engine/tests/morning_alpha/test_journal_repository.py
git commit -m "feat(morning-alpha): add immutable signal journal"
```

---

### Task 10: Outcome auditor, MFE/MAE, R sequencing, and rolling scorecard

**Files:**
- Create: `engine/morning_alpha/audit/__init__.py`
- Create: `engine/morning_alpha/audit/outcome.py`
- Create: `engine/morning_alpha/audit/scorecard.py`
- Test: `engine/tests/morning_alpha/test_outcome_audit.py`

**Interfaces:**
- Produces: `OutcomeAuditor.audit(plan, bars) -> SignalOutcome`, `ScorecardBuilder.build(outcomes) -> SignalScorecard`.

- [ ] **Step 1: Write sequencing tests**

Cover:
- trigger never fires then price falls => `FILTERED_LOSER`
- trigger never fires then price rallies => `FILTERED_WINNER`
- trigger fires, stop hits before 1R => `LOSS`
- trigger fires, reaches 2R without stop => `WIN`
- same bar contains both stop and target with unknown tick ordering => `UNVERIFIED`
- triggered trade closes positive below 1R => `OPEN_OR_UNFINISHED` for swing horizon or marked close-R for daily audit.

- [ ] **Step 2: Implement entry-time slicing**

MFE/MAE MUST use only bars at or after the actual trigger timestamp. Never use session high/low before entry.

- [ ] **Step 3: Implement conservative ambiguous-bar rule**

If OHLC data cannot establish whether stop or target happened first on the same bar, return `UNVERIFIED` unless higher-resolution bars are available. Never infer favorable sequencing.

- [ ] **Step 4: Implement scorecard fields**

```text
total_candidates
triggers_fired
wins
losses
open_or_unfinished
filtered_losers
filtered_winners
unverified
cumulative_r
average_mfe_r
average_mae_r
trigger_rate
filter_protection_rate
missed_opportunity_rate
```

- [ ] **Step 5: Run tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_outcome_audit.py -v
git add engine/morning_alpha/audit engine/tests/morning_alpha/test_outcome_audit.py
git commit -m "feat(morning-alpha): add outcome audit and scorecard"
```

---

### Task 11: Historical event simulator and trigger laboratory

**Files:**
- Create: `engine/morning_alpha/research/__init__.py`
- Create: `engine/morning_alpha/research/simulator.py`
- Create: `engine/morning_alpha/research/trigger_lab.py`
- Create: `engine/morning_alpha/research/metrics.py`
- Test: `engine/tests/morning_alpha/test_trigger_lab.py`

**Interfaces:**
- Produces: `HistoricalSimulator`, `TriggerDefinition`, `TriggerLab`, `StrategyMetrics`.
- Executes the exact same setup detector and trade constructor used live.

- [ ] **Step 1: Define trigger variants**

Implement versioned research triggers:

```text
market_open
prior_day_high
premarket_high
orb_5m
orb_15m
orb_30m
breakout_retest
vwap_reclaim
```

- [ ] **Step 2: Write anti-lookahead tests**

Create a fixture where tomorrow's high would make a candidate look attractive. Assert today's detector result remains unchanged when future rows are added to the data store.

- [ ] **Step 3: Implement event-driven simulator**

For each historical decision timestamp:
1. build point-in-time snapshot,
2. run universe + regime + sector + detector,
3. construct plan,
4. simulate trigger and outcome on subsequent bars,
5. persist research record.

- [ ] **Step 4: Implement metrics**

At minimum: N, expectancy R, median R, win rate, profit factor, average/median MFE, average/median MAE, filtered-loser rate, filtered-winner rate, turnover proxy, and cost sensitivity.

- [ ] **Step 5: Run tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_trigger_lab.py -v
git add engine/morning_alpha/research engine/tests/morning_alpha/test_trigger_lab.py
git commit -m "feat(morning-alpha): add historical simulator and trigger lab"
```

---

### Task 12: Gate-v2 adapter and promotion lifecycle

**Files:**
- Create: `engine/morning_alpha/research/gate_v2_adapter.py`
- Test: `engine/tests/morning_alpha/test_gate_v2_adapter.py`
- Modify: `engine/data/gate_v2_verdicts/README.md` only if a Morning Alpha verdict naming convention must be documented.

**Interfaces:**
- Produces: `MorningAlphaGateV2.evaluate(research_run) -> PromotionVerdict`.
- Calls canonical `backtest.wfo_lifecycle.compute_gate_v2`; does not copy its formulas.

- [ ] **Step 1: Write adapter test using monkeypatched canonical gate**

Assert the adapter passes actual per-trade R return series, OOS windows, grid-trial count, fixed-param metrics, and cost metrics to the canonical function.

- [ ] **Step 2: Implement lifecycle states**

```python
class PromotionState(StrEnum):
    IDEA = "idea"
    BACKTESTED = "backtested"
    WFO_VALIDATED = "wfo_validated"
    GATE_V2_PASSED = "gate_v2_passed"
    PAPER = "paper"
    FORWARD_VALIDATED = "forward_validated"
    LIVE_ELIGIBLE = "live_eligible"
    DEGRADED = "degraded"
    RETIRED = "retired"
```

Gate-v2 PASS alone may move to `GATE_V2_PASSED`; it MUST NOT imply `LIVE_ELIGIBLE`.

- [ ] **Step 3: Add promotion minimums around Gate-v2**

Before invoking Gate-v2, require at least 200 total historical trades for normal setup families unless an explicitly documented sparse-strategy path is approved by the existing Gate-v2 architecture. Require OOS and cost/slippage runs to exist.

- [ ] **Step 4: Run tests and integrity checker**

```bash
cd engine
pytest tests/morning_alpha/test_gate_v2_adapter.py -v
python scripts/check_gate_v2_integrity.py
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/morning_alpha/research/gate_v2_adapter.py engine/tests/morning_alpha/test_gate_v2_adapter.py engine/data/gate_v2_verdicts/README.md
git commit -m "feat(morning-alpha): integrate canonical gate v2"
```

---

### Task 13: End-to-end Morning Alpha service and live/backtest parity test

**Files:**
- Create: `engine/morning_alpha/service.py`
- Test: `engine/tests/morning_alpha/test_service_parity.py`

**Interfaces:**
- Produces: `MorningAlphaService.scan(as_of) -> ScanResult`.
- Orchestrates providers -> context -> universe -> setup detectors -> trade constructor -> edge eligibility -> portfolio heat -> persistence.

- [ ] **Step 1: Write parity test**

Feed identical bars through `FakeMarketDataProvider` and `ParquetHistoricalProvider`; assert serialized `SetupCandidate` and `TradePlan` outputs are identical for the same `as_of` timestamp.

- [ ] **Step 2: Implement orchestration without hidden side effects**

The service returns a structured `ScanResult` containing:

```text
as_of
regime
sector_scores
eligible_count
candidate_count
rejections
qualified_plans
portfolio_decision
```

Persistence is invoked through the `SignalJournal` interface after deterministic evaluation.

- [ ] **Step 3: Enforce no-trade semantics**

If no plan survives, `qualified_plans=()` and report status=`NO_TRADE`; this is success, not an exception.

- [ ] **Step 4: Run tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_service_parity.py -v
git add engine/morning_alpha/service.py engine/tests/morning_alpha/test_service_parity.py
git commit -m "feat(morning-alpha): add deterministic scan service"
```

---

### Task 14: Morning report, prior-run audit, and CLI

**Files:**
- Create: `engine/morning_alpha/reporting/__init__.py`
- Create: `engine/morning_alpha/reporting/morning_report.py`
- Create: `engine/morning_alpha/cli.py`
- Test: `engine/tests/morning_alpha/test_reporting.py`

**Interfaces:**
- Produces: `render_morning_report(scan, prior_audit, scorecard) -> str`, CLI commands `scan`, `audit`, `research-trigger-lab`.

- [ ] **Step 1: Write snapshot-style report tests**

Require sections in this order when at least one setup qualifies:

```text
PRIOR RUN AUDIT
ROLLING SIGNAL SCORECARD
MARKET REGIME
QUALIFYING SETUPS
PORTFOLIO HEAT
UNVERIFIED / INFERRED NOTES
```

When no setup qualifies, CLI exits 0 with machine-readable `NO_TRADE`; notification integrations may suppress delivery.

- [ ] **Step 2: Implement report language rules**

Verified source-derived fields and inferred technical levels must be separately labeled. Never say an untriggered setup “won” or “lost.”

- [ ] **Step 3: Implement CLI**

Example:

```bash
python -m morning_alpha.cli scan --as-of 2026-09-15T13:00:00Z --provider alpaca
python -m morning_alpha.cli audit --session 2026-09-15
python -m morning_alpha.cli research-trigger-lab --strategy relative_strength_breakout@1.0.0
```

- [ ] **Step 4: Run tests and commit**

```bash
cd engine
pytest tests/morning_alpha/test_reporting.py -v
git add engine/morning_alpha/reporting engine/morning_alpha/cli.py engine/tests/morning_alpha/test_reporting.py
git commit -m "feat(morning-alpha): add report and cli"
```

---

### Task 15: Full regression suite, observability, documentation, and paper-only activation

**Files:**
- Modify: `engine/.env.example`
- Create: `engine/docs/MORNING_ALPHA_RUNBOOK.md`
- Create: `engine/docs/MORNING_ALPHA_RESEARCH_PROTOCOL.md`
- Add or modify targeted Prometheus metrics module under `engine/morning_alpha/` if existing monitoring conventions require it after repo inspection.
- Test: all Morning Alpha tests plus existing Gate-v2 integrity checks.

**Interfaces:**
- Produces operational runbook and research protocol; no live order routing.

- [ ] **Step 1: Add health metrics**

Track:

```text
morning_alpha_scan_duration_seconds
morning_alpha_provider_staleness_seconds
morning_alpha_candidates_total
morning_alpha_qualified_total
morning_alpha_no_trade_total
morning_alpha_point_in_time_violations_total
morning_alpha_audit_unverified_total
```

- [ ] **Step 2: Write runbook**

Document local setup, Alpaca credentials, PostgreSQL schema bootstrap, historical data path, scan/audit commands, no-trade behavior, provider failure behavior, and rollback/disable procedure.

- [ ] **Step 3: Write research protocol**

Document pre-registration, immutable strategy versions, development/OOS/WFO splits, trial-count accounting for DSR, cost/slippage stress, Monte Carlo, regime segmentation, trigger-lab anti-overfit rules, and promotion states.

- [ ] **Step 4: Run complete verification**

```bash
cd engine
pytest tests/morning_alpha -v
python scripts/check_gate_v2_integrity.py
ruff check morning_alpha tests/morning_alpha
```

Then run the repository's documented safe non-IB CI subset. Do NOT run `integration_ib` or `manual` markers.

- [ ] **Step 5: Perform an offline golden-session replay**

Use a fixed historical session fixture and assert:
1. candidate set is deterministic,
2. live-adapter-normalized fixture and historical adapter produce identical plans,
3. outcome audit reproduces expected MFE/MAE/R,
4. no future-data access occurs.

- [ ] **Step 6: Commit**

```bash
git add engine/morning_alpha engine/docs/MORNING_ALPHA_RUNBOOK.md engine/docs/MORNING_ALPHA_RESEARCH_PROTOCOL.md engine/.env.example
git commit -m "docs(morning-alpha): add runbook and research protocol"
```

---

## Implementation Order and Review Gates

1. **Tasks 1–4 — Research-safe foundation.** Review before strategy logic begins.
2. **Tasks 5–8 — Context, setups, and risk.** Review the deterministic candidate/trade contract before persistence.
3. **Tasks 9–10 — Journal and daily audit.** Verify immutable lineage and ambiguous-bar handling.
4. **Tasks 11–12 — Backtesting and Gate-v2.** No paper scanning until these are working.
5. **Tasks 13–15 — Operational service/reporting.** Activate paper observation only after parity and integrity tests pass.

## Initial Research Campaign After Code Completion

Do not optimize all rules simultaneously. Pre-register and run independent families in this order:

1. `relative_strength_breakout@1.0.0`
2. `sector_rotation@1.0.0`
3. `post_earnings_drift@1.0.0`
4. `momentum_breakout@1.0.0`
5. `pullback_continuation@1.0.0`
6. `gap_continuation@1.0.0`

For each family:

- freeze v1 rules before seeing final OOS results;
- run raw setup test;
- run trigger-lab variants independently;
- evaluate transaction-cost tiers (0, 2, 5, 10, 20 bps) plus slippage shocks;
- perform chronological OOS and rolling WFO;
- calculate Gate-v2 with honest trial counts;
- preserve failures in the strategy registry;
- only Gate-v2-passed candidates enter paper-forward observation.

## Definition of Done for v1

Morning Alpha v1 is complete only when all statements are true:

- Historical and live adapters produce identical strategy decisions from identical point-in-time data.
- The six setup families are independently versioned and backtestable.
- The system produces zero setups when hard gates fail.
- Risk sizing enforces 0.5% default and 1.0% hard ceiling for the $3,000 reference account.
- Portfolio heat rejects correlated overexposure.
- Every candidate/rejection/plan is journaled immutably.
- The next-session auditor correctly distinguishes WIN, LOSS, OPEN/UNFINISHED, FILTERED_WINNER, FILTERED_LOSER, and UNVERIFIED.
- MFE/MAE begins at actual entry time, not session open.
- Trigger lab compares all eight predefined trigger variants without lookahead.
- Gate-v2 uses the canonical repository implementation and honest trial accounting.
- Full Morning Alpha tests and Gate-v2 integrity checks pass.
- No broker mutation/live order code is introduced.
- Paper-forward operation can be disabled with configuration without code changes.
