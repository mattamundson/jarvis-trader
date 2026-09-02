# Orphan Component Re-Triage — 2026-08-02 (Phase 12.6)

- **Agent:** agent-P12-6, wave 2 of `AGENT_TASK_QUEUE_2026-08-01.md`
- **Worktree:** `C:\Users\mattm\ThinkorSwim\wt-phase-drain\dashboard`
- **Prior count:** 69 (stale — cited in `docs/backlog/DASHBOARD_PUNCHLIST.md` row 12.6)
- **This count:** 69 true orphans (coincidental match on the raw number — see "What changed
  since the stale count" below; the *set* is not identical to whatever produced the original 69,
  since `MarketHealthGrid` (wave 1, P6-6) is now archived and therefore excluded from scope, and
  `SessionSummaryWidget` / `IBGatewayStatus` are confirmed live, not orphaned)
- **Archiving:** NOT done in this pass — triage only, per race-avoidance instruction (P6-1/P6-2
  are concurrently wiring components in this same worktree). Follow-up wave item.

## Method

1. Enumerated every `.tsx`/`.ts` file under `dashboard/components/` (251 files), excluding
   `components/_archive/`, `*.test.*`, and `*.stories.*`.
2. For each, raw-text-searched every `.ts`/`.tsx` file under `dashboard/app/`,
   `dashboard/components/`, `dashboard/hooks/`, `dashboard/lib/`, and `dashboard/tests/`
   (431 files) for the component's base filename (e.g. `KillSwitch` for `KillSwitch.tsx`),
   excluding the component's own file.
3. This is a **substring/raw-text match, not an AST import check** — deliberately looser than a
   real import graph, so it also catches `next/dynamic(() => import("@/components/X"))`,
   JSX usage without a matching import alias, and any hypothetical string-keyed registry. A
   confirmed no-op module search (`Glob **/lib/*{egistry,idget,anel}*.ts` → no matches; no
   `.storybook/` directory in the dashboard tree) rules out the two dynamic-reference mechanisms
   that would otherwise hide a false orphan. Because the match is a superset of real references,
   zero hits under this method means zero hits under a stricter one too — there is no
   false-orphan risk from under-matching.
4. Spot-checked the `next/dynamic` call sites that do exist (`app/discord/page.tsx`,
   `app/backtest/page.tsx`, `app/command-center/page.tsx` for `CandlestickChart`) — all use a
   literal string path matching the basename, so method step 2 already counts them; no distinct
   dynamic-reference category was needed for this codebase.
5. **69 files had zero hits.** All 69 were individually spot-checked for a second time via a
   fresh `Grep` pass (not the batch script) — same result. Classified as **true-dead**: zero
   references anywhere in `app/`, `components/`, `hooks/`, `lib/`, or `tests/`, including
   dynamic/string-based forms.
6. **Zero components were classified dynamically-referenced-only.** This codebase has no
   component registry, no Storybook, and its handful of `next/dynamic()` call sites all use
   literal basename-matching string paths — so no orphan candidate was hidden from the raw-text
   method by indirection.

## What changed since the stale count of 69

- `MarketHealthGrid.tsx` — archived by wave 1 (P6-6, commit `490d60e`); no longer in
  `components/` at all, so it's out of scope for this scan (not double-counted as newly "found").
- `SessionSummaryWidget.tsx` — confirmed **1 live reference** (`app/paper/page.tsx`); P6-1 is
  actively wiring it to `useHonestTrades()` in this same wave. Not an orphan.
- `IBGatewayStatus.tsx` — confirmed **3 live references** (`app/health/page.tsx`,
  `app/settings/page.tsx`, `lib/settings-api.ts`); P6-5 (wave 1, DONE) already mounted it on
  `/health`. Not an orphan.
- Net effect: the underlying set shifted (3 known components left the orphan pool), but 69 new
  true-dead components were independently confirmed today, landing on the same total by
  coincidence, not because nothing moved.

## Surprises worth flagging

- **`components/command-center/` has an entire unused composition layer.** `CommandCenterShell.tsx`,
  `HudBackground.tsx`, `ScanLineOverlay.tsx`, `DrawdownMini.tsx`, `EquityCurveMini.tsx`,
  `tabs/SystemsTab.tsx`, `charts/OptionsChainPanel.tsx`, `charts/RegimeTimeline.tsx`, and
  `charts/StcIndicatorPanel.tsx` (9 files) are all zero-reference. `app/command-center/page.tsx`
  exists and is live (it dynamically imports `charts/CandlestickChart`, which is NOT orphaned),
  but it implements the page inline rather than composing it from `CommandCenterShell` and its
  sibling parts. This reads as an abandoned shell-composition rewrite that lost to the inline
  version — one archival decision covering 9 files.
- **Two of P10-2's four "ambiguous, needs triage" widgets are unmounted.** P10-2 (this same
  wave) flagged `DailyTargetProgressWidget.tsx` and `MultiMarketPnLWidget.tsx` for a
  static-badge decision on their `?? <number>` fallbacks — but both are true orphans per this
  scan (zero mount sites anywhere). The badge question is moot until/unless one is mounted;
  worth noting back to whoever triages P10-2's punch list so it isn't fixed in place on a dead
  file. (The other two P10-2-flagged widgets, `TradingDaysCountdownCard.tsx` and
  `PaperBalanceWidget.tsx`, are both live — confirmed here.)
- **Duplicate/superseded-looking clusters** (same functional area, one live + one or more dead —
  plausible legacy leftovers, not confirmed intent):
  - Daily P&L: `DailyPnLChart.tsx` and `DailyPnlPanel.tsx` are dead; `DailyPnLCalendarWidget.tsx`
    (live, not in this list) covers the same ground.
  - Equity curve: `charts/EquityCurveChart.tsx` and `command-center/EquityCurveMini.tsx` are
    dead; `EquityCurveWidget.tsx` (live) covers the same ground.
  - Regime: `RegimeDisplay.tsx` and `RegimeHistoryWidget.tsx` are dead; `MarketRegimeWidget.tsx`,
    `regime/RegimeScoreHistoryChart.tsx`, `RegimeAttributionWidget.tsx`, and
    `RegimePnLBreakdownWidget.tsx` (all live, not in this list) cover regime display today.
  - Trade history: `TradeHistory.tsx` is dead; `RecentTradesTableWidget.tsx` (live) appears to
    be its replacement.

## Full triage table (69 true-dead, 0 dynamically-referenced)

All rows: **Classification = true-dead** (zero references in `app/`, `components/`, `hooks/`,
`lib/`, `tests/`, including dynamic/string forms). No archiving performed — see header.

| # | Component | Notes |
|---|---|---|
| 1 | `components/AlertHistoryLog.tsx` | Both alert-history variants (#1, #2) are dead; `AlertSummaryWidget.tsx` (live, not listed) may be the survivor. |
| 2 | `components/AlertHistoryWidget.tsx` | Dead alongside #1; `AlertSummaryWidget.tsx` is the live sibling. |
| 3 | `components/BacktestMetricsWidget.tsx` | `BacktestCompareWidget.tsx`, `BacktestComparisonCard.tsx`, `BacktestVsPaperWidget.tsx` are all live (not listed) — likely superseded. |
| 4 | `components/charts/EquityCurveChart.tsx` | See "duplicate clusters" above. |
| 5 | `components/command-center/charts/OptionsChainPanel.tsx` | Command-center unused-shell cluster (see above). |
| 6 | `components/command-center/charts/RegimeTimeline.tsx` | Command-center unused-shell cluster. |
| 7 | `components/command-center/charts/StcIndicatorPanel.tsx` | Command-center unused-shell cluster. |
| 8 | `components/command-center/CommandCenterShell.tsx` | Command-center unused-shell cluster — the shell itself. |
| 9 | `components/command-center/DrawdownMini.tsx` | Command-center unused-shell cluster. |
| 10 | `components/command-center/EquityCurveMini.tsx` | Command-center unused-shell cluster. |
| 11 | `components/command-center/HudBackground.tsx` | Command-center unused-shell cluster. |
| 12 | `components/command-center/ScanLineOverlay.tsx` | Command-center unused-shell cluster. |
| 13 | `components/command-center/tabs/SystemsTab.tsx` | Command-center unused-shell cluster; also matched inside archived `components/_archive/command-center/tabs/OverviewTab.tsx` (archive doesn't count as live). |
| 14 | `components/DailyPnLChart.tsx` | See "duplicate clusters" above. |
| 15 | `components/DailyPnlPanel.tsx` | See "duplicate clusters" above. |
| 16 | `components/DailyTargetProgressWidget.tsx` | Flagged ambiguous by P10-2 for a badge decision; actually unmounted — see "Surprises." |
| 17 | `components/DailyTradeCountWidget.tsx` | No mount site found. |
| 18 | `components/DatabaseStatusWidget.tsx` | `DatabaseStatsCard.tsx` (live, not listed) may be the survivor. |
| 19 | `components/DecisionLogWidget.tsx` | `RecentDecisionsWidget.tsx`, `DecisionBreakdownCard.tsx` (both live) cover this area. |
| 20 | `components/DualTFWidget.tsx` | `MTFConfirmationWidget.tsx` also dead (#37) — both multi-timeframe widgets unmounted. |
| 21 | `components/DurabilityWidget.tsx` | No mount site found. |
| 22 | `components/EngineConfigCard.tsx` | `EngineHealthWidget.tsx`, `EngineWidget.tsx`, `EngineUptimeCard.tsx` (all live) cover engine status. |
| 23 | `components/EnginePnlTruthCard.tsx` | `HonestPnlCard.tsx` (live) covers honest-P&L display. |
| 24 | `components/EODSummaryWidget.tsx` | `TodaySummaryWidget.tsx` (live) may be the survivor. |
| 25 | `components/EventsFeedWidget.tsx` | No mount site found. |
| 26 | `components/ExecutionCockpitWidget.tsx` | No mount site found. |
| 27 | `components/FeatureFlagsPanel.tsx` | No mount site found — candidate for `/settings` or similar if flags exist. |
| 28 | `components/InstitutionalProfileWidget.tsx` | No mount site found. |
| 29 | `components/JournalStatsWidget.tsx` | `TradeJournalWidget.tsx` also dead (#62). Both journal widgets unmounted. |
| 30 | `components/KairosStatusWidget.tsx` | `KairosObservationFeed.tsx` (live) covers Kairos display. |
| 31 | `components/learning/AgentWeightsPanel.tsx` | Sibling `learning/` components (`MemoryPanel`, `PatternCard`, `SuggestionPanel`, `TradeGradeTable`) are all live — this one alone is dead. |
| 32 | `components/LongShortBreakdownWidget.tsx` | `LongShortBalanceWidget.tsx` (live) may be the survivor. |
| 33 | `components/MacroRegimeBadge.tsx` | No mount site found. |
| 34 | `components/MarketSessionIndicator.tsx` | `MarketSessionWidget.tsx` also dead (#35); `MarketSessionStatusCard.tsx` (live) covers this area. |
| 35 | `components/MarketSessionWidget.tsx` | See #34. |
| 36 | `components/MESSprintGate.tsx` | No mount site found — check against `docs/plans/2026-04-25-mes-sprint-gate-*.md`, may be a deliberately shelved feature, not simple dead code. |
| 37 | `components/MTFConfirmationWidget.tsx` | See #20. |
| 38 | `components/MultiMarketPnLWidget.tsx` | Flagged ambiguous by P10-2 for a badge decision; actually unmounted — see "Surprises." |
| 39 | `components/OrderEntryPanel.tsx` | No mount site found — likely intentionally unshipped (manual order entry on a paper-trading dashboard is a safety-relevant surface). |
| 40 | `components/PhaseProgressWidget.tsx` | No mount site found. |
| 41 | `components/Pm2StabilityWidget.tsx` | No mount site found. |
| 42 | `components/PositionsPanel.tsx` | `OpenPositionsWidget.tsx`, `BrokerPositionsWidget.tsx` (both live) cover positions display. |
| 43 | `components/ProactiveValidationWidget.tsx` | `ValidationChecklist.tsx`, `ValidationCheckpointWidget.tsx` (both live) cover validation. |
| 44 | `components/RegimeDisplay.tsx` | See "duplicate clusters" above. |
| 45 | `components/RegimeHistoryWidget.tsx` | See "duplicate clusters" above. |
| 46 | `components/RiskConfigDisplayWidget.tsx` | `RiskSettingsWidget.tsx`, `RiskStatusWidget.tsx` (both live) cover risk display. |
| 47 | `components/RLStatusWidget.tsx` | No mount site found. |
| 48 | `components/SameDayPnLBadge.tsx` | No mount site found. |
| 49 | `components/SchwabStatusWidget.tsx` | No mount site found — Schwab may not be an active broker integration; verify before archiving. |
| 50 | `components/SentimentPanel.tsx` | Per `rules-jarvis-trader`, sentiment sourcing is Discord/Corey-only — this generic panel may predate that decision. |
| 51 | `components/ShadowPerformanceWidget.tsx` | `ForwardVsBacktestCard.tsx`, `BacktestVsPaperWidget.tsx` (both live) cover this comparison. |
| 52 | `components/SignalHistory.tsx` | `RecentSignalsWidget.tsx`, `SignalFeedWidget.tsx` (both live) cover signal history. |
| 53 | `components/SignalStatsCard.tsx` | `SignalAccuracyWidget.tsx` (live) may be the survivor. |
| 54 | `components/SoundControl.tsx` | Cross-reference `dashboard/ACCESSIBILITY_AND_SOUND_ALERTS.md` — may document intended-but-unshipped sound controls. |
| 55 | `components/StcStrategyExplainerCard.tsx` | Distinct from `command-center/charts/StcIndicatorPanel.tsx` (#7) — both STC-related components are dead. |
| 56 | `components/StrategyParamsPanel.tsx` | `StrategyParamsCard.tsx` (live) may be the survivor. |
| 57 | `components/SuperEngineStatusWidget.tsx` | `EngineHealthWidget.tsx`, `SystemLivenessCard.tsx` (both live) cover this. |
| 58 | `components/SymbolSignalWidget.tsx` | `SymbolPerformanceWidget.tsx` (live) is a different metric, not a clear duplicate — genuinely just unmounted. |
| 59 | `components/TiltIndicatorWidget.tsx` | No mount site found. |
| 60 | `components/TradeAnalyticsWidget.tsx` | Broad-scope name; several narrower live widgets (`TradeDurationWidget`, `HoldTimeWidget`, etc.) may have absorbed this. |
| 61 | `components/TradeHistory.tsx` | See "duplicate clusters" above. |
| 62 | `components/TradeJournalWidget.tsx` | See #29. |
| 63 | `components/TradeRiskRewardWidget.tsx` | `RiskRewardWidget.tsx` (live) may be the survivor. |
| 64 | `components/TradingHoursWidget.tsx` | `MarketSessionStatusCard.tsx`, `TradingScheduleCard.tsx` (both live) cover this. |
| 65 | `components/TVBridgeWidget.tsx` | TradingView bridge — verify against `rules-jarvis-trader`'s TV CDP launcher before archiving; may be a superseded integration path, not simple dead code. |
| 66 | `components/ValidationGatesWidget.tsx` | `ValidationGatesPanel.tsx` under `app/mission-control/components/` (live) may be the survivor. |
| 67 | `components/VolatilityWidget.tsx` | `VIXRegimeCard.tsx`, `VixPercentileRegimeCard.tsx` (both live) cover volatility. |
| 68 | `components/WeeklyPerformanceWidget.tsx` | `WeeklyStatsWidget.tsx`, `WeeklyPnLCard.tsx` (both live) cover weekly performance. |
| 69 | `components/WinStreakWidget.tsx` | `StreakTrackerWidget.tsx`, `StreakBadge.tsx`, `PnLStreakWidget.tsx` (all live) cover streak display. |

## Recommendation for the follow-up archiving wave

- The **command-center cluster (#5–13, 9 files)** is the single highest-confidence, highest-leverage
  archive: one coherent decision, no plausible live-usage argument (the page that would use it
  already ships an inline implementation).
- **`MESSprintGate.tsx` (#36), `TVBridgeWidget.tsx` (#65), `SchwabStatusWidget.tsx` (#49), and
  `SoundControl.tsx` (#54)** should get a human look before archiving — each has a plausible
  "deliberately shelved feature, not dead code" story (see per-row notes) that a pure
  reference-count scan can't distinguish from abandonment.
- The remaining ~56 read as ordinary superseded-by-a-newer-widget orphans, safe for the
  `components/_archive/` treatment once this wave's active edits (P6-1, P6-2) land and this file
  set stops moving.
