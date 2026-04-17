---
repo: Algoman123/Dashboard123
url: https://github.com/Algoman123/Dashboard123
stars: 81
language: Python
license: MIT
archived: false
pushed_at: 2026-04-10T08:21:39Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [8]
---

# Algoman123/Dashboard123

## Core value proposition

Dashboard123 is a Streamlit-based desktop dashboard for real-time monitoring of Portfolio123 investment strategies, screens, and ranking systems. It provides multi-panel views of holdings, macro indicators (FRED), sector rotation, technical analysis, sentiment, and news aggregation—with a rebalance workflow for trade execution. The codebase architecture (modular services, component-driven UI, configuration persistence) demonstrates dashboard patterns applicable to strategy monitoring UIs.

## Surface analysis

### 1. Engine code
`no-fit` — Dashboard123 is a standalone portfolio monitoring tool with no trading algorithm, signal generation, backtest harness, or risk engine. It depends on Portfolio123 API, yfinance, and FRED—none of which are jarvis-trader engine signals or data sources.

### 2. Project rules
`no-fit` — No coding discipline, safety invariant, or testing patterns specific to trading logic apply. Streamlit conventions differ fundamentally from jarvis-trader's Python agent architecture.

### 3. Project skills
`no-fit` — Dashboard123 has no reusable workflows that generalize to jarvis-trader's model-centric or trading-centric skill categories.

### 4. Slash commands
`no-fit` — Streamlit UI patterns do not translate to CLI command workflows.

### 5. Subagents
`no-fit` — No specialized reviewer, analyzer, or autonomous agent patterns.

### 6. Docs
`no-fit` — Installation, configuration, and known limitations are specific to Portfolio123 API and Streamlit. No strategy, architecture, or operational runbook value.

### 7. Dev tooling
`no-fit` — Streamlit-based (no Next.js, PM2, or CI/GitHub Actions). Architecture diverges completely from jarvis-trader's DevOps and automation patterns.

### 8. Dashboard
`partial-integrate` — Dashboard123 demonstrates concrete UI patterns relevant to jarvis-trader's dashboard (port 3010, Next.js):
  - **Ranking radar charts** (SVG-rendered spider/radar visualizations for composite score analysis). Jarvis-trader has `RegimeAttributionWidget` and `AuditTab.tsx` with Recharts radar, but Dashboard123's approach to mapping node-level composite scores → visual hierarchy is portable.
  - **Real-time monitoring layout** (sidebar groups, auto-refresh intervals, sparkline mini-charts for index performance). Jarvis-trader uses SWR polling at 30-60s intervals; Dashboard123's configurable refresh patterns (drag-and-drop group ordering, per-group column indicators) could inform dashboard sidebar UX upgrades.
  - **Top movers / performance ranking tables** (ranked ticker lists with relative performance). Jarvis-trader's `BestWorstTradesWidget` and `BacktestMetricsWidget` cover trade-level rankings, but cross-instrument live "top gainers" feeds are absent.
  - **Macro overview bar** (yield curve, GDP, CPI via FRED API). Jarvis-trader uses regime filters and VIX sizing; Dashboard123's FRED integration pattern (API key management, caching, sparkline mini-charts) could inspire a "macro regime widget" combining regime bands + macro data.
  - **Ticker-scoped detail panels** (news, fundamentals, technical scores per ticker). Jarvis-trader's instrument dashboards are backtest- and trade-centric; a "live macro + news + sentiment per instrument" panel would complement agent decision transparency.

Integration constraints:
  - Dashboard123 is Streamlit (Python); jarvis-trader dashboard is Next.js (TypeScript). Code copy is impossible.
  - No direct API compatibility—Portfolio123 API calls would need replacement with jarvis-trader's `/portfolio/*` and `/backtest/*` endpoints.
  - TradingView embed is Portfolio123-specific; jarvis-trader uses lightweight-charts + Recharts.
  - Styling: Streamlit CSS differs radically from Tailwind + Radix UI.

Value extraction path: Read Dashboard123's UI/UX patterns (component grouping, radar score visualization, refresh polling, settings dialog for state persistence) and adapt to Next.js components using jarvis-trader's design rules.

### 9. Ops / messaging
`no-fit` — Streamlit-based dashboard has no notification, cron, or messaging patterns. Jarvis-trader's OpenClaw, WhatsApp, and Discord integrations are separate from UI concerns.

## Integration plan

**Partial integration on Surface 8 only.**

No copy-paste code. Recommended next steps for dashboard enrichment:

1. **Ranking Radar Enhancement** (M, 4-6 hours):
   - Study Dashboard123's `components/radar_chart.py` (SVG rendering, node-score mapping).
   - Create `dashboard/components/StrategyRankingRadar.tsx` (Recharts RadarChart) to visualize composite trade scores (e.g., WFE × Sharpe × PF per instrument) as radar polygons.
   - Hook to `/portfolio/instruments` endpoint to fetch live scores.
   - Adapt design rule: badge variants only (no arbitrary colors for chart nodes).

2. **Live Top Movers Panel** (S, 2-3 hours):
   - Dashboard123 pattern: filter tickers by 24h return percentile, rank by return.
   - Create `dashboard/components/TopMoversWidget.tsx` (table with sort, instrument badge color-coding by regime).
   - Hook to `/backtest/paper-status` and `/health` endpoints for live P&L deltas.

3. **Macro Regime Bar** (M, 6-8 hours):
   - Dashboard123 pattern: FRED API calls cached hourly; sparkline mini-charts per macro series.
   - Replace FRED with jarvis-trader's internal macro signals (regime classification, VIX band, confluence multiplier).
   - Create `dashboard/components/MacroRegimeBar.tsx` (horizontal band showing regime state, VIX level, confluence score).
   - Reference: existing `RegimeDisplay.tsx`, `MarketRegimeWidget.tsx`.

4. **Per-Instrument Detail Sidebar** (L, 8-12 hours):
   - Dashboard123 pattern: click ticker → modal with news, fundamentals, technical scores, notes.
   - Create `dashboard/components/InstrumentDetailPanel.tsx` (collapsible side panel or modal).
   - Include: daily P&L chart, entry/exit rationale (from trade notes), regime at entry, recent alerts.
   - Hook to `/portfolio/trades/<instrument>` and `/alerts/*` endpoints.

None of these require licensing concern (MIT Dashboard123 reference is for pattern inspiration only, not code reuse).

## License & attribution

Dashboard123: **MIT License**. No code is copied; reference is for UI/UX pattern study only. Attribution in commit message if any Dashboard123 radar/refresh pattern is adapted: "Inspired by Algoman123/Dashboard123 radar chart and refresh interval patterns."

## Effort estimate

**Effort breakdown** (if all four enhancements are pursued):
- Ranking Radar: M (4-6 hr)
- Top Movers: S (2-3 hr)
- Macro Regime Bar: M (6-8 hr)
- Instrument Detail Panel: L (8-12 hr)
- **Total: 2-5 days** (sequential) or **20-29 hr** (if parallelized as 2 concurrent tracks)

**Recommended start**: Top Movers (quick win) + Ranking Radar (demonstrates score visualization). Defer Macro Bar and Detail Panel to follow-up session pending user feedback on dashboard priorities.

## Red flags

- **Streamlit vs. Next.js architecture mismatch** — Dashboard123 uses Streamlit's reactive widget model, jarvis-trader uses Server/Client Components with SWR. No code is portable; pattern extraction only.
- **Portfolio123 API dependency** — Dashboard123's core value is Portfolio123 integration; jarvis-trader has no such dependency. All integrations must map to engine endpoints.
- **Unfinished TradingView embed limitation** — Dashboard123's README flags that TradingView embed does not support OSL (Oslo Exchange). Jarvis-trader uses lightweight-charts, so this is not applicable.
- **Performance at scale** — Dashboard123 caches rankings data to disk to manage Portfolio123 API credit limits. Jarvis-trader's trade/backtest tables may grow large; SWR polling intervals should be tuned to avoid frontend lag.

## Notes for next session

- If user prioritizes "live instrument monitoring with macro context," start with Top Movers (2-3 hr quick win) to validate dashboard layout assumptions.
- If user wants "transparent agent decision factors," start with Instrument Detail Panel (12 hr) to expose trade rationale alongside live P&L.
- Ask user: "Which monitoring pattern is most useful: live top performers, ranking quality (radar), macro context, or per-trade decision transparency?" — answer determines which of the four integrations to green-light.
