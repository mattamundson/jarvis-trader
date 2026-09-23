# POLL_INTERVAL Sub-Drain Queue (Phase 6.4 prep — P6-4-DISCOVERY)

Discovery/classification pass only. **Nothing in this document has been fixed.** No polling
interval value was changed while producing this catalog. This is the literal input for a future
dedicated multi-wave sub-drain that adopts `dashboard/lib/polling-config.ts` tiers everywhere.

- **Anchor file:** `dashboard/lib/polling-config.ts` — confirmed imported by exactly 4 files today
  (`hooks/useLLMHealth.ts`, `hooks/useIBDataHealth.ts`, `hooks/useEngineStatus.ts`,
  `app/components/TokenProxyMetricsWidget.tsx`) plus the guard script and a `public/` static HTML
  asset that references the string but isn't a real consumer — matches the plan's "imported by only
  4 files" finding.
- **Total real in-scope sites catalogued:** 251 (129 literal SWR `refreshInterval` + 82 named-constant
  SWR `refreshInterval` usages, backed by 68 unique constant definitions + 44 literal `setInterval`
  data-polls + 9 consumers of one dynamic/computed pattern). Plus 11 cosmetic UI-clock `setInterval`
  calls (not data fetches — separately bucketed) and 13 `setInterval` calls in a static `public/`
  HTML asset (out of scope, flagged, not counted in the 251).
- **This is roughly 2x the plan's "~150" estimate** — see Critical Finding #2 below for why.
- **Tier breakdown of the 251 in-scope sites** (by target bucket, counting each definition once for
  the named-constant group rather than every call-site):
  - `market-data` (must end ≤300s / `MARKET_DATA_MAX`): **74**
  - `operator-state`: **62**
  - `reference`: **34**
  - `research`: **72**
  - dynamic/computed (needs a design decision, not a literal swap): **9** (1 pattern, 4 files)
- **State:** all rows below are `QUEUED`. This doc does not track its own completion — a future
  wave's queue file should.

---

## CRITICAL FINDINGS — read before dispatching the actual sub-drain

### 1. LIVE CI GUARD VIOLATION — `hardcoded-refresh-interval` is failing right now

`dashboard/scripts/check-guards.mjs` (GUARD 4, lines 177-211) already implements almost exactly the
regex the plan proposes for Phase 1.4 (`/refreshInterval:\s*[0-9]/`), as a **ratchet**, not a hard
gate: `REFRESH_INTERVAL_CEILING = 128`, comment "Measured on master: 128 hardcoded call-sites".

Running it now (`node scripts/check-guards.mjs` in this worktree):

```
FAIL hardcoded-refresh-interval (129 > ceiling 128)
1 guard(s) failed: hardcoded-refresh-interval
```

**This worktree is 1 over the ratchet ceiling and the guard script exits 1.** Root-caused via
`git diff origin/master...HEAD -- dashboard/app dashboard/components dashboard/hooks dashboard/lib`:
exactly one new `refreshInterval:\s*[0-9]` line was added on this branch, zero were removed. It's
`dashboard/components/SessionSummaryWidget.tsx:47` —
`{ refreshInterval: 60_000, shouldRetryOnError: false, errorRetryCount: 0 },` — added by **P6-1**
(wave 2, commit 9cd6df9, wiring `SessionSummaryWidget` to `useHonestTrades()`). P6-1's own task spec
didn't mention the ratchet (it predates this discovery pass), so this isn't a P6-1 mistake — it's the
ratchet doing exactly its job of catching net-new hardcoding. **Two options for whoever picks this
up first:** (a) fold this one site into whatever lands first — trivial, it's a `NORMAL`/`SLOW`-tier
site (`useHonestTrades` polling cadence) — or (b) bump `REFRESH_INTERVAL_CEILING` to 129 with a
comment pointing at this doc, if the fix is deferred to the real sub-drain. Flagging for Amo/PR #572
review either way; **not fixed by this discovery pass** per its own no-code-edit rule.

### 2. The plan's own CI-guard regex has a total blind spot for named constants — true count is ~2x

The proposed/implemented regex (`refreshInterval:\s*[0-9]`) only catches **literal number** call
sites. It catches **zero** of the 82 call sites (backed by 68 distinct `const REFRESH_MS = <literal>`
/ `POLL_MS` / `POLLING_INTERVAL_MS` / `REFRESH_INTERVAL_MS`-style per-file constant declarations) —
these are just as hardcoded (one file, one frozen number) but indirected through a local name, so the
literal-value regex walks right past them. It also catches **zero** raw `setInterval(fn, <literal>)`
call sites (44 real data-polling ones found, on top of the SWR-`refreshInterval` ones) — those aren't
`refreshInterval:` at all. **Net effect: the "~150 sites" estimate in the plan was built by running
(or eyeballing) the literal-only regex; the actual hardcoded-interval surface is closer to 250.** A
future sub-drain's own tracking/ceiling math should use 251, not ~150, or it will declare victory
after clearing only the fraction the current guard can even see.

### 3. No live `MARKET_DATA_MAX` (>300s) violations found among market-data-tagged sites

Every `market-data`-classified site tops out at exactly `300_000`ms (5 min) — several sit right at
that ceiling (`hooks/useOptionsChain.ts:17` options-chain poll, `dashboard/components/BarDepthCard.tsx:46`,
`app/signals/page.tsx:155`, `app/hidden-pivots/page.tsx:31` `PRICE_COVERAGE_REFRESH_MS`) — none
exceed it. The memory item `feedback_futures_sentiment_source`-adjacent plan note about
`amo-commodities` "600s violating the ≤5min rule" is confirmed **already a non-issue in current
code**: `app/trust-pane/page.tsx:269` is `refreshInterval: 300_000` (exactly 300s, and it's an
id→symbol lookup map per the plan's own audit, correctly classified `reference` not `market-data`
below). See the "MARKET_DATA_MAX boundary watch-list" at the bottom for the sites worth tightening
below 300s as a quality improvement, even though none are currently *violating* the rule.

---

## Table 1 — Named-constant SWR `refreshInterval` (PRIMARY fix point; 68 definitions, ~82 call sites)

Fixing the constant's declaration fixes every consumer in that file — these are the actual fix
points, not the (unlisted) individual `{ refreshInterval: REFRESH_MS }` call sites that reference
them.

| File:Line | Constant | Current value | Target tier |
|---|---|---|---|
| app/components/TokenProxyMetricsWidget.tsx:21 | POLL_INTERVAL_MS | 5000 | operator-state |
| app/framing-brief/page.tsx:8 | REFRESH_MS | 300000 (5*60_000) | reference |
| app/crypto/page.tsx:8 | REFRESH_MS | 5000 | market-data |
| app/jarvis/page.tsx:32 | HERO_REFRESH_MS | 30000 | operator-state |
| app/jarvis/page.tsx:33 | BRIEFING_REFRESH_MS | 300000 | reference |
| app/jarvis/page.tsx:34 | BOOKMARKS_REFRESH_MS | 300000 | reference |
| app/journal/page.tsx:14 | REFRESH_MS | 30000 | research |
| app/hidden-pivots/page.tsx:25 | REFRESH_MS | 60000 | market-data |
| app/hidden-pivots/page.tsx:28 | PRICE_REFRESH_MS | 15000 | market-data |
| app/hidden-pivots/page.tsx:31 | PRICE_COVERAGE_REFRESH_MS | 300000 | market-data (at ceiling) |
| app/options/page.tsx:7 | REFRESH_MS | 5000 | market-data |
| components/AnomalySentinelStrip.tsx:41 | POLL_MS | 15000 | operator-state |
| components/ActionableBoardWidget.tsx:13 | REFRESH_MS | 60000 | operator-state |
| components/BacktestComparisonCard.tsx:54 | REFRESH_INTERVAL_MS | 120000 | research |
| components/AuctionBiasCard.tsx:11 | REFRESH_MS | 60000 | market-data |
| app/watchlist/page.tsx:428 | PRICE_REFRESH_MS | 15000 | market-data |
| app/watchlist/page.tsx:429 | SIGNAL_REFRESH_MS | 60000 | market-data |
| app/validation/page.tsx:80 | REFRESH_MS | 30000 | research (ties to P8-7 WFE reconciliation) |
| app/portfolio/page.tsx:8 | REFRESH_MS | 5000 | market-data |
| app/regime/page.tsx:26 | REFRESH_MS | 30000 | market-data |
| app/polymarket/page.tsx:8 | REFRESH_MS | 5000 | market-data |
| app/trading-eligibility/page.tsx:19 | REFRESH_MS | 30000 | operator-state |
| app/signal-outcomes/page.tsx:17 | REFRESH_MS | 120000 | research |
| app/signals/page.tsx:20 | REFRESH_MS | 30000 | operator-state (only consumer is `/approvals/pending`) |
| components/CumulativeTradingDaysWidget.tsx:11 | REFRESH_MS | 120000 | reference |
| components/DailyPnlPanel.tsx:11 | REFRESH_MS | 30000 | market-data |
| components/DualTFWidget.tsx:7 | REFRESH_MS | 60000 | market-data |
| components/DrawdownChartWidget.tsx:14 | REFRESH_INTERVAL_MS | 120000 | research |
| components/discord/signal-feed.tsx:8 | REFRESH_MS | 10000 | reference (Corey-Discord sentiment source, not price) |
| components/discord/DiscordStats.tsx:6 | REFRESH_MS | 30000 | reference |
| components/discord/corey-feed.tsx:7 | REFRESH_MS | 15000 | reference |
| components/discord/DiscordWinRateChart.tsx:16 | REFRESH_MS | 30000 | research |
| app/trades/pending-approvals/page.tsx:22 | REFRESH_MS | 20000 | operator-state (safety-critical) |
| components/EODSummaryWidget.tsx:10 | POLLING_INTERVAL_MS | 30000 | research |
| components/discord/import-stats.tsx:7 | REFRESH_MS | 30000 | reference |
| components/discord/ib-report-card.tsx:7 | REFRESH_MS | 15000 | reference |
| components/ForwardVsBacktestCard.tsx:13 | REFRESH_MS | 60000 | research |
| components/ForwardTestPanel.tsx:18 | POLL_MS | 60000 | research — comment says "verdict changes at most daily; 60s is plenty"; candidate for the plan's new `DAILY_ISH` tier, currently over-polled relative to its own stated cadence |
| components/discord/DiscordSignalTable.tsx:7 | REFRESH_MS | 10000 | reference |
| app/today/page.tsx:28 | REFRESH_MS | 30000 | operator-state (`/health` is its only confirmed consumer) |
| app/scorecard/page.tsx:65 | REFRESH_MS | 60000 | research |
| components/learning/AgentWeightsPanel.tsx:8 | REFRESH_MS | 30000 | research |
| components/learning/PatternCard.tsx:8 | REFRESH_MS | 60000 | research |
| components/learning/TradeGradeTable.tsx:7 | REFRESH_MS | 30000 | research |
| components/learning/MemoryPanel.tsx:8 | REFRESH_MS | 30000 | research |
| components/learning/SuggestionPanel.tsx:7 | REFRESH_MS | 60000 | research |
| components/MESForwardRecorderPanel.tsx:10 | REFRESH_MS | 60000 | research |
| components/MESRevalidationTracker.tsx:12 | REFRESH_MS | 120000 | research |
| components/MESSprintGate.tsx:9 | POLL_MS | 60000 | operator-state (safety gate) |
| components/OptionsSignalsPanel.tsx:19 | REFRESH_MS | 60000 | market-data |
| components/PaperBalanceWidget.tsx:12 | REFRESH_MS | 120000 | operator-state (P10-2 already badged its fallback figure) |
| components/PaperTradingPanel.tsx:11 | POLL_MS | 30000 | operator-state |
| components/PipelineRunHistory.tsx:10 | REFRESH_MS | 30000 | research |
| components/Pm2StabilityWidget.tsx:14 | POLL_MS | 30000 | operator-state (infra/pm2 process monitoring) |
| components/PortfolioCorrelationWidget.tsx:8 | REFRESH_MS | 30000 | market-data |
| components/PortfolioPLChart.tsx:9 | REFRESH_MS | 60000 | market-data |
| components/PostTradeExecutionWidget.tsx:15 | REFRESH_MS | 120000 | research |
| components/RegimeDisplay.tsx:7 | REFRESH_MS | 60000 | market-data |
| components/RegimeAttributionWidget.tsx:7 | REFRESH_MS | 120000 | research |
| components/RiskAttributionPanel.tsx:28 | REFRESH_MS | 300000 (5*60_000) | research |
| components/RollingWFEWidget.tsx:10 | POLLING_INTERVAL_MS | 60000 | research (ties to P8-7) |
| components/SameDayPnLBadge.tsx:14 | REFRESH_MS | 15000 | market-data |
| components/SessionBriefPanel.tsx:21 | REFRESH_MS | 30000 | reference |
| components/SignalHistory.tsx:9 | REFRESH_MS | 30000 | research |
| components/SystemLivenessCard.tsx:13 | REFRESH_MS | 15000 | operator-state |
| components/TradeHistory.tsx:21 | REFRESH_MS | 30000 | research |
| components/WatchlistBar.tsx:16 | POLL_MS | 10000 | market-data |
| components/ValidationGatesWidget.tsx:10 | POLLING_INTERVAL_MS | 30000 | research |
| components/ValidationChecklist.tsx:15 | REFRESH_MS | 300000 | research |
| components/VixPercentileRegimeCard.tsx:10 | POLLING_INTERVAL_MS | 60000 | market-data — comment says "VIX regime moves on daily bars", candidate `DAILY_ISH`/`REFERENCE`, currently over-polled relative to its own stated cadence |

## Table 2 — Literal-number SWR `refreshInterval` (129 occurrences, clustered per file)

| File | Line(s) | Value(s) (ms) | Target tier | Note |
|---|---|---|---|---|
| app/data-integrity/page.tsx | 49 | 2000 | market-data | |
| app/command-center/page.tsx | 322 | 60000 | market-data | per-instrument regime pulse |
| app/command-center/page.tsx | 378 | 60000 | market-data | live price chart bars |
| app/command-center/page.tsx | 410 | 120000 | reference | macro snapshot |
| app/command-center/page.tsx | 417 | 120000 | operator-state | paper-status |
| app/command-center/page.tsx | 429 | 60000 | research | journal stats |
| app/command-center/page.tsx | 438 | 300000 | research | honest-trades dedup set |
| app/command-center/page.tsx | 371 + 6 consumers | 30000/300000 dynamic | see Table 5 | NOT caught by the literal regex — see dynamic pattern below |
| app/health/page.tsx | 472 | 15000 | operator-state | |
| app/jarvis/page.tsx | 253 | 60000 | operator-state | |
| app/kairos/page.tsx | 301 | 30000 | operator-state | kairos status |
| app/kairos/page.tsx | 307 | 30000 | operator-state | watchers |
| app/kairos/page.tsx | 318 | 300000 | reference | |
| app/backtest/page.tsx | 447 | 60000 | research | |
| app/master/page.tsx | 13 | 15000 | operator-state | |
| components/BarDepthCard.tsx | 46 | 300000 | market-data (at ceiling) | |
| app/mission-control/components/ValidationGatesPanel.tsx | 54 | 60000 | research | comment: "heavier endpoint, 8 live checks" |
| app/mission-control/components/ValidationGatesPanel.tsx | 110 | 60000 | research | strategy ledger |
| components/ApprovalPanel.tsx | 156 | 5000 | operator-state | safety-critical approvals |
| app/master/finances/page.tsx | 31 | 60000 | operator-state | |
| app/validation/page.tsx | 277 | 60000 | research | `ANALYTICS_SWR` const; ties to P8-7 |
| app/settings/page.tsx | 618, 636 | 5000 | operator-state | |
| app/settings/page.tsx | 624 | 60000 | reference | |
| app/settings/page.tsx | 630 | 10000 | operator-state | |
| app/mission-control/components/PositionsPerformancePanel.tsx | 44, 52 | 15000 | market-data | live P&L/positions |
| app/mission-control/components/SignalsPipelinePanel.tsx | 80, 86, 91 | 15000 | market-data | pipeline status/decisions |
| app/mission-control/components/RiskSafetyPanel.tsx | 55, 57, 62 | 15000 | operator-state | safety/health status |
| app/mission-control/components/EngineDataPanel.tsx | 51 | 15000 | operator-state | |
| app/mission-control/components/EngineDataPanel.tsx | 56 | 30000 | operator-state | |
| components/DailyTargetProgressWidget.tsx | 37 | 5000 | operator-state | flagged unmounted by P12-6; ambiguous fallback badge by P10-2 |
| components/AlertHistoryWidget.tsx | 81 | 30000 | operator-state | |
| app/mission-control/components/EnvironmentFleetPanel.tsx | 57 | 15000 | operator-state | |
| app/trust-pane/page.tsx | 253 | 15000 | operator-state | |
| app/trust-pane/page.tsx | 256 | 15000 | market-data | `/brokers/positions` |
| app/trust-pane/page.tsx | 258, 259 | 30000 | research | attr-daily, trade journal |
| app/trust-pane/page.tsx | 261 | 60000 | reference | bar-quality analytics (168h window) |
| app/trust-pane/page.tsx | 264 | 120000 | reference | edge-ledger reports |
| app/trust-pane/page.tsx | 266 | 30000 | operator-state | amo-health |
| app/trust-pane/page.tsx | 267 | 60000 | research | amo-edge-verdict |
| app/trust-pane/page.tsx | 269 | 300000 | reference | `amo-commodities` — id→symbol lookup, confirmed non-market-data (plan's own false-positive resolution) |
| app/trust-pane/page.tsx | 271, 274 | 120000 | research | amo-signal-outcomes, amo-scoreboard |
| app/trust-pane/page.tsx | 277 | 60000 | research | amo-actionable |
| app/master/trading/page.tsx | 22 | 60000 | operator-state | |
| components/CircuitBreakerPanel.tsx | 88 | 10000 | operator-state | safety-critical |
| app/parallel-paper/page.tsx | 104, 280, 285 | 60000 | operator-state | |
| app/parallel-paper/page.tsx | 293 | 300000 | research | |
| app/portfolio/page.tsx | 224 | 30000 | market-data | capital allocation |
| components/ConfidenceGauge.tsx | 18 | 60000 | research | |
| app/polymarket/page.tsx | 69, 72 | 30000 | market-data | |
| app/options/page.tsx | 75 | 30000 | market-data | options scan |
| app/trades/[id]/review/page.tsx | 73 | 30000 | research | |
| app/trades/[id]/review/page.tsx | 84 | 60000 | research | |
| app/signals/page.tsx | 155 | 300000 | market-data (at ceiling) | |
| app/paper/page.tsx | 40, 380, 676 | 30000 | operator-state | |
| app/paper/page.tsx | 47 | 120000 | operator-state | paper-status |
| app/paper/page.tsx | 535 | 60000 | operator-state | |
| app/strategy-ledger/page.tsx | 42 | 60000 | research | |
| app/trades/page.tsx | 63 | 30000 | operator-state | |
| app/trades/page.tsx | 69 | 15000 | operator-state | |
| app/trades/pending-approvals/page.tsx | 64 | 60000 | operator-state | inconsistent w/ `ApprovalPanel.tsx`'s 5s for the same safety-critical class — worth reconciling in the real drain |
| components/charts/PriceTerrain3D.tsx | 171 | 120000 | market-data | |
| components/BrokerPositionsWidget.tsx | 99 | 10000 | market-data | |
| components/BrokerPositionsWidget.tsx | 106 | 5000 | market-data | |
| components/BookmarkThemesPanel.tsx | 69 | 1800000 (30 min) | reference | |
| components/charts/PriceChartPanel.tsx | 51 | 60000 | market-data | |
| components/HonestPnlCard.tsx | 40 | 60000 | operator-state | |
| components/EnginePnlTruthCard.tsx | 27 | 60000 | operator-state | |
| components/MultiMarketPnLWidget.tsx | 41 | 5000 | market-data | flagged unmounted by P12-6; ambiguous fallback badge by P10-2 |
| components/ExcursionPanel.tsx | 53 | 60000 | research | |
| components/ReconciliationWidget.tsx | 153 | 60000 | operator-state | |
| components/DiscordIntelligenceWidget.tsx | 108 | 30000 | reference | |
| components/DurabilityWidget.tsx | 23 | 60000 | research | |
| components/EntryTimingScenarios.tsx | 46 | 60000 | research | |
| components/_archive/MarketHealthGrid.tsx | 133 | 5000 | **ARCHIVED — exclude** | moved to `_archive/` by P6-6, dead code, do not include in the real sub-drain |
| components/EventsFeedWidget.tsx | 11 | 5000 | operator-state | |
| components/HoldTimeWidget.tsx | 27 | 60000 | research | |
| components/LiveTradeReasoningWidget.tsx | 360 | 30000 | research | |
| components/MacroRegimeBadge.tsx | 33 | 300000 | reference | |
| components/ReadinessCheckWidget.tsx | 39 | 120000 | operator-state | |
| components/master/SchedulerPanel.tsx | 34, 39 | 15000 | operator-state | |
| components/KairosStatusWidget.tsx | 50 | 30000 | operator-state | |
| components/PerformancePanel.tsx | 43 | 30000 | research | |
| components/KairosObservationFeed.tsx | 91 | 15000 | operator-state | |
| components/PostTradeSnippet.tsx | 53, 58 | 60000 | research | |
| components/StrategyParamsPanel.tsx | 41 | 30000 | reference | |
| components/KnowledgeContextWidget.tsx | 85 | 300000 | reference | |
| components/WinRateByHourWidget.tsx | 58 | 60000 | research | |
| components/ProdGateScorecard.tsx | 35 | 60000 | research | |
| components/ProactiveValidationWidget.tsx | 129 | 60000 | research | |
| components/SchwabStatusWidget.tsx | 45 | 5000 | operator-state | broker status |
| components/PaperApprovedValidationWidget.tsx | 97 | 60000 | research | |
| components/PendingApprovals.tsx | 25 | 3000 | operator-state | safety-critical |
| components/StrategyDiscoveryBrowser.tsx | 99 | 30000 | reference | |
| components/RLStatusWidget.tsx | 95 | 30000 | research | |
| components/ShadowPerformanceWidget.tsx | 12 | 10000 | research | |
| components/SessionSummaryWidget.tsx | 47 | 60000 | operator-state | **the site that broke the CI ratchet — see Critical Finding #1** |
| components/SignalFeedWidget.tsx | 215 | 30000 | market-data | |
| components/SignalStatsCard.tsx | 45 | 60000 | research | |
| components/TiltIndicatorWidget.tsx | 94 | 10000 | research | |
| components/TradeReviewPanel.tsx | 83 | 15000 | research | |
| components/ValidationCheckpointWidget.tsx | 11 | 60000 | research | |
| components/widgets/SignalFlowWidget.tsx | 283 | 30000 | market-data | |
| components/widgets/SignalFlowWidget.tsx | 289 | 15000 | market-data | |
| components/WFEMonitorWidget.tsx | 68 | 60000 | research | ties to P8-7 |
| components/StreakTrackerWidget.tsx | 65 | 60000 | research | |
| components/StrategyResearchPanel.tsx | 120 | 300000 | research | |
| components/UnrealizedPnLWidget.tsx | 117 | 10000 | market-data | |
| components/TradeJournalWidget.tsx | 41 | 60000 | research | |
| hooks/useOptionsChain.ts | 17 | 300000 | market-data (at ceiling) | |
| hooks/useOptionsChain.ts | 28 | 60000 | market-data | |
| hooks/useChartData.ts | 41, 75 | 60000 | market-data | |
| hooks/useChartData.ts | 57, 67 | 120000 | market-data | |
| hooks/useChartData.ts | 83 | 30000 | market-data | |

## Table 3 — Literal `setInterval(fn, <number>)` real data-polling sites (44)

Not `refreshInterval` at all — a parallel hardcoding mechanism the plan's regex cannot see.

| File:Line | Value (ms) | Target tier |
|---|---|---|
| components/AlertHistoryLog.tsx:53 | 60000 | operator-state |
| components/AlertSummaryWidget.tsx:109 | 60000 | operator-state |
| components/BacktestMetricsWidget.tsx:228 | 60000 | research |
| components/BacktestVsPaperWidget.tsx:101 | 300000 | research |
| components/CommissionTrackerWidget.tsx:37 | 300000 | reference |
| app/watchlist/page.tsx:100 | 300000 | market-data |
| app/watchlist/page.tsx:221 | 300000 | market-data |
| app/strategies/page.tsx:1984 | 3000 | market-data |
| components/CurrentSignalWidget.tsx:95 | 120000 | market-data |
| components/DailyPnLChart.tsx:25 | 30000 | market-data |
| components/ConnectionHealthCard.tsx:79 | 30000 | operator-state |
| components/DatabaseStatsCard.tsx:137 | 300000 | reference |
| components/DecisionLogWidget.tsx:206 | 15000 | market-data |
| components/DecisionBreakdownCard.tsx:118 | 300000 | research |
| components/DatabaseStatusWidget.tsx:150 | 60000 | reference |
| components/EngineHealthWidget.tsx:74 | 15000 | operator-state |
| components/DrawdownChart.tsx:35 | 60000 | research |
| components/EntryQualityWidget.tsx:127 | 60000 | research |
| components/EngineUptimeCard.tsx:64 | 30000 | operator-state |
| components/ExecutionCockpitWidget.tsx:82 | 15000 | operator-state |
| components/IBGatewayStatus.tsx:71 | 10000 | operator-state (just mounted on /health by P6-5) |
| components/InstitutionalProfileWidget.tsx:59 | 30000 | reference |
| components/MarketSessionWidget.tsx:353 | 30000 | operator-state |
| components/IbGatewayDetailCard.tsx:88 | 30000 | operator-state |
| components/MTFConfirmationWidget.tsx:76 | 300000 | research |
| components/OpenPositionsWidget.tsx:201 | 15000 | market-data |
| components/MarketSessionIndicator.tsx:54 | 60000 | reference |
| components/RegimeHistoryWidget.tsx:195 | 30000 | research |
| components/RecentSignalsWidget.tsx:99 | 30000 | market-data |
| components/ProfitFactorWidget.tsx:80 | 30000 | research |
| components/RecentDecisionsWidget.tsx:96 | 60000 | market-data |
| components/MarketSessionStatusCard.tsx:204 | 60000 | reference |
| components/SignalQueueWidget.tsx:138 | 30000 | market-data |
| components/RiskStatusWidget.tsx:110 | 30000 | operator-state |
| components/SymbolSignalWidget.tsx:271 | 15000 | market-data |
| components/PreFlightWidget.tsx:54 | 120000 | operator-state |
| components/PositionSizingWidget.tsx:170 | 300000 | operator-state |
| components/SuperEngineStatusWidget.tsx:26 | 30000 | operator-state |
| components/SystemMetricsPanel.tsx:125 | 60000 | operator-state |
| components/TodaySummaryWidget.tsx:65 | 120000 | operator-state |
| components/WatchlistScanWidget.tsx:58 | 300000 | market-data |
| components/WhatsAppStatusCard.tsx:104 | 120000 | operator-state |
| components/VolatilityWidget.tsx:101 | 30000 | market-data |
| components/VIXRegimeCard.tsx:129 | 300000 | market-data |
| components/command-center/CommandCenterShell.tsx | see Table 5 | — |

## Table 4 — Cosmetic UI-clock `setInterval` calls (11) — low priority, not a data fetch

These update a local `Date.now()`/tick state for a visual clock or staleness re-render, not an API
call. Technically hardcoded intervals, but fixing them is cosmetic (they'd map to `POLL_INTERVAL`
tiers awkwardly since they're not fetch cadences). Listed for completeness; recommend the real
sub-drain deprioritizes these below the 251 real data-poll sites above.

| File:Line | Value (ms) |
|---|---|
| app/command-center/page.tsx:367 | 1000 |
| lib/useProvenance.ts:26 | 1000 |
| components/EngineOfflineBanner.tsx:16 | 5000 |
| components/IBDataDegradedBanner.tsx:24 | 5000 |
| components/MarketSessionWidget.tsx:335 | 10000 |
| components/RegimeHistoryWidget.tsx:202 | 30000 |
| components/SymbolSignalWidget.tsx:277 | 1000 |
| components/MarketSessionStatusCard.tsx:203 | 1000 |
| components/ui/staleness-indicator.tsx:42 | 1000 |
| components/WatchlistBar.tsx:36 | 1000 |
| components/command-center/CommandCenterShell.tsx:37 | 1000 |

## Table 5 — Dynamic/computed `refreshInterval` pattern (9 consumer sites, needs a design decision)

`app/command-center/page.tsx:371`: `const refreshInterval = session.isActive ? 30_000 : 5 * 60_000;`
— NOT a literal, NOT a named module-level constant, so caught by neither of the plan's proposed
regexes. Threaded as a shorthand object property into 6 `useSWR` calls in the same file (`/health`
line 387, `/safety/status` line 390, `/portfolio` line 393, `/decisions/recent` line 397,
`/scheduler/status` line 403, `/portfolio/history/trades` line 420 — all `operator-state`/`market-data`
mix, session-adaptive), then further threaded as a **prop** into `EngineWidget.tsx:17`,
`components/command-center/CommandCenterShell.tsx:16`, and
`components/command-center/tabs/SystemsTab.tsx:452` (which itself re-threads it into a
`SystemMetricsTable` prop at line 545). This is a legitimately different pattern from a frozen
literal — it already *adapts* to market session — so a mechanical "replace N with POLL_INTERVAL.X"
edit doesn't fit. **Recommend the real sub-drain treat this as its own item**: decide whether
`POLL_INTERVAL` should gain a session-aware helper (e.g. `POLL_INTERVAL.marketAware(tier)`) rather
than force this into a static tier constant.

## Table 6 — Out of scope: `public/strategy-c-command-center.html` (13 sites, flagged only)

A static vanilla-JS HTML asset served from `public/`, not part of the Next.js/React app — different
tech entirely (no SWR, no TypeScript, no `POLL_INTERVAL` import path even possible without a script
tag rewrite). 13 raw `setInterval(fn, N)` calls at lines 5809, 5843, 6656, 6721, 6733, 6788, 7114,
8479, 8746, 8747 (named-const `POLL_INTERVAL`, locally declared in the HTML's own `<script>`, not
`lib/polling-config.ts`), 8910, 8911, 8912 (named-const), 9055, 9263. **Needs a scoping decision from
Amo** before any sub-drain touches it: is this page still served/linked anywhere, or is it a dead
static artifact that should move to `_archive/` instead (same question Phase 12.6's orphan sweep
raises for components)? Not catalogued as an actionable site above pending that decision.

---

## MARKET_DATA_MAX boundary watch-list (no violations, but these sit exactly at 300s)

Not a rule violation (≤300s satisfies the rule) but worth tightening in the real sub-drain since
300s is the loosest the rule allows for genuinely live data: `hooks/useOptionsChain.ts:17` (options
chain), `components/BarDepthCard.tsx:46`, `app/signals/page.tsx:155`,
`app/hidden-pivots/page.tsx:31` (`PRICE_COVERAGE_REFRESH_MS`).

## Recommended next-wave shape

Given 251 real sites across ~140 distinct files, a single dedicated wave is still too large (this
was explicitly the reason for this discovery-only pass). Suggest splitting the eventual fix wave by
Table (1 → 2 → 3 → 5) and within Table 2/3 by tier, since `market-data` sites are the safety-relevant
ones (`MARKET_DATA_MAX` enforcement) and should land first, with a `tsc --noEmit` + build + E2E gate
between each batch per the plan's own Phase 6.4 guidance.
