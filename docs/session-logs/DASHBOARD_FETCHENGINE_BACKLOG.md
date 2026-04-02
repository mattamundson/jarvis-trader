# Dashboard: migrate bare `fetch` to `fetchEngine` / `postEngine`

Canonical rule: [dashboard/lib/api.ts](dashboard/lib/api.ts) — all engine traffic should use `fetchEngine` / `postEngine` (see [CLAUDE.md](../../CLAUDE.md)).

## Done in same-day bundle (2026-04-02)

- [dashboard/components/EngineAvailabilityHint.tsx](../../dashboard/components/EngineAvailabilityHint.tsx) — `/health` via `fetchEngine("/health")` (headers + timeout + retry).

## Inventory (grep `await fetch(` in `dashboard/components/*.tsx`)

The following components still call `fetch` directly (prioritize high-traffic / portfolio paths first):

- `AvgTradeTimeWidget.tsx`, `BacktestComparisonCard.tsx`, `BestWorstTradeWidget.tsx`, `BestWorstTradesWidget.tsx`
- `CurrentSignalWidget.tsx`, `DailyPnLCalendarWidget.tsx`, `DailyTradeCountWidget.tsx`, `DatabaseStatusWidget.tsx`
- `DecisionBreakdownCard.tsx`, `DecisionLogWidget.tsx`, `DrawdownChartWidget.tsx`, `EntryQualityWidget.tsx`
- `ExportDataWidget.tsx` (uses `/api/engine` — should use `fetchEngine` / shared helpers)
- `LongShortBreakdownWidget.tsx`, `MonthlyBreakdownWidget.tsx`, `MonthlyTargetCard.tsx`
- `PnLStreakWidget.tsx`, `RecentDecisionsWidget.tsx`, `RecentTradesTableWidget.tsx`
- `RegimePnLBreakdownWidget.tsx`, `RiskConfigDisplayWidget.tsx` (uses `/api/engine` pattern)
- `SignalAccuracyWidget.tsx`, `TodaySessionWidget.tsx`, `TopSymbolsWidget.tsx`
- `TradeCalendarWidget.tsx`, `TradeDurationWidget.tsx`, `TradeHourlyBreakdownWidget.tsx`
- `TradePnLHistogram.tsx`, `TradeRiskRewardWidget.tsx`, `TradingHoursWidget.tsx`
- `VIXRegimeCard.tsx` — `fetch('/notifications/vix-alert-check')` (may need `fetchEngine` if routed via rewrite)
- `WeeklyPerformanceWidget.tsx`, `WeeklyPnLCard.tsx`, `WinRateBySymbolWidget.tsx`, `WinStreakWidget.tsx`

## Next slice suggestion

Batch-migrate widgets that hit `/portfolio/*` or `/decisions/*` in one PR, then run `pnpm run build`.
