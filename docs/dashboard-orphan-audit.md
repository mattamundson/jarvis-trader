# Dashboard Orphan-Component Audit (roadmap 5.5)

_Generated 2026-07-21. Static reference audit of `dashboard/components/*.tsx`._

## What this is

Roadmap 5.5 asks that every component in `dashboard/components/` is either
imported from a route or archived. This is the **audit half** — the definitive
list of components with **zero non-self references** in any `.ts`/`.tsx` file
under `dashboard/`. It is a reconciliation artifact, **not** an archival action:
physically moving these files is a destructive batch that needs per-component
WIP-vs-dead triage and a green `pnpm run build`, so it is left for Amo to direct.

## Method (and why the first pass was wrong)

- A component is an **orphan** iff no `.ts`/`.tsx` file other than its own
  definition (`components/<Name>.tsx`) references its name as a whole word.
- The audit was run with a single directory-scoped `git grep -n -E '\b(<all
  200 names>)\b' -- dashboard`, then filtered to `.ts`/`.tsx` paths and
  self-references dropped.
- **A first attempt used a `dashboard/**/*.tsx` git pathspec and under-matched**
  (git `**` globbing did not reach nested route files), producing 82 false
  "orphans" — `RiskStatusWidget` was flagged despite being imported by
  `app/paper/page.tsx`. The directory-pathspec re-run is the reliable one and is
  what this list reflects.

## Caveats before archiving any of these

1. **WIP vs. dead:** several read as intentionally-unwired work-in-progress
   (e.g. `MESSprintGate`, `LiveReadinessWidget`, `ProactiveValidationWidget`,
   `ForwardTestPanel`), not retired code. Triage each before moving.
2. **Second-order orphans:** some components are referenced **only by other
   orphans** and so are not in this list yet — e.g. `PendingApprovals` is used
   only by `ExecutionCockpitWidget` (itself an orphan). Archiving an orphan can
   promote its dependencies to orphan status; re-run the audit after each batch.
3. **Doc/story-only references don't count as reached:** `KillSwitch` appears
   only in `dashboard/*.md`/`*.txt`, never in code — it is a true code orphan.
4. **Roadmap staleness found:** the roadmap listed `RiskStatusWidget` as
   "retired-per-comment"; it is in fact still referenced by `app/paper/page.tsx`
   and `MaxDrawdownTrackerWidget.tsx`, so it is **not** an orphan. (`EnginePnlTruthCard`,
   `CircuitBreakerPanel`, `ExecutionCockpitWidget` — the other three named — are
   confirmed orphans.)
5. **Archive, never delete:** move to `~/Archive/2026/dashboard-orphans/`, don't
   `rm`. Verify `pnpm run build` stays green (16/16 routes) after each batch.

## True orphans — 69 of 200 components (zero non-self code refs)

AgentFeed, AlertHistoryLog, AlertHistoryWidget, BacktestMetricsWidget,
BrokerPositionsWidget, CircuitBreakerPanel, ConfidenceGauge,
CumulativeTradingDaysWidget, DailyPnLChart, DailyPnlPanel,
DailyTargetProgressWidget, DailyTradeCountWidget, DatabaseStatusWidget,
DecisionLogWidget, DualTFWidget, DurabilityWidget, EODSummaryWidget,
EngineConfigCard, EnginePnlTruthCard, EventsFeedWidget, ExecutionCockpitWidget,
FeatureFlagsPanel, ForwardTestPanel, InstitutionalProfileWidget,
JournalStatsWidget, KairosStatusWidget, KillSwitch, LongShortBreakdownWidget,
MESSprintGate, MTFConfirmationWidget, MacroRegimeBadge, MarketHealthGrid,
MarketSessionIndicator, MarketSessionWidget, MultiMarketPnLWidget,
OrderEntryPanel, PerformancePanel, PhaseProgressWidget, Pm2StabilityWidget,
PositionsPanel, ProactiveValidationWidget, RLStatusWidget, RegimeDisplay,
RegimeHistoryWidget, RiskConfigDisplayWidget, RiskRewardWidget, SameDayPnLBadge,
SchwabStatusWidget, SentimentPanel, ShadowPerformanceWidget, SignalHistory,
SignalStatsCard, SoundControl, StcStrategyExplainerCard, StrategyParamsPanel,
SuperEngineStatusWidget, SymbolSignalWidget, TVBridgeWidget, TiltIndicatorWidget,
TradeAnalyticsWidget, TradeHistory, TradeJournalWidget, TradeRiskRewardWidget,
TradingHoursWidget, UnrealizedPnLWidget, ValidationGatesWidget, VolatilityWidget,
WeeklyPerformanceWidget, WinStreakWidget

## Suggested next action

Triage the 69 into `retire` vs `wire` vs `keep-as-WIP`; archive the `retire`
set to `~/Archive/2026/dashboard-orphans/` in small batches, re-running the audit
+ `pnpm run build` after each. That closes 5.5's archival half.
