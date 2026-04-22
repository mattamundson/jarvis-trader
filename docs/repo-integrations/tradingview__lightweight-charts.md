---
repo: tradingview/lightweight-charts
url: https://github.com/tradingview/lightweight-charts
stars: 15248
language: TypeScript
license: Apache License 2.0
archived: false
pushed_at: 2026-04-17T14:28:09Z
analyzed_at: 2026-04-18
recommendation: integrate-now
surfaces_with_value: [dashboard]
---

# tradingview/lightweight-charts

## Core value proposition

Lightweight Charts is TradingView's production financial HTML5 charting library — 40KB minified, optimized for OHLCV candlesticks, line series, and area charts on financial dashboards. Purpose-built for performance with time-series data; outperforms generic business chart libraries (recharts, chart.js) on rendering speed and bundle size.

## Surface analysis

### 1. Engine code
`no-fit` — No algorithmic or backtesting value; charting library only.

### 2. Project rules
`no-fit` — No coding discipline patterns applicable.

### 3. Project skills
`no-fit` — Charting infrastructure, not reusable skill.

### 4. Slash commands
`no-fit` — Not applicable.

### 5. Subagents
`no-fit` — Not applicable.

### 6. Docs
`no-fit` — No operational runbook or architecture patterns to reuse.

### 7. Dev tooling
`partial-integrate` — Plugin architecture (TypeScript plugin examples in `/plugin-examples/`) establishes a pattern for wrapping custom financial indicators as reusable chart extensions. Could inform future `dashboard/lib/chart-plugins/` pattern.

### 8. Dashboard
`integrate-now` — **Critical fit**. `dashboard/` (port 3010) currently uses recharts (^2.15.3) for all charts. Lightweight-charts is purpose-built for financial instruments (candlesticks, OHLCV bars, time-series) and delivers 3–5x smaller bundle + faster rendering than recharts on large datasets. Candidate replacements: any chart rendering OHLCV (futures prices), volume, or time-series indicators.

### 9. Ops / messaging
`no-fit` — Not applicable.

## Integration plan

### Dashboard: Chart component wrapper (S—2hr)

1. **Install dependency**:
   ```bash
   cd dashboard && npm install lightweight-charts
   ```

2. **Create wrapper component** at `dashboard/src/components/LightweightChart.tsx`:
   - Accept props: `{ data: [{ time, open, high, low, close, volume }], type: 'candlestick'|'line'|'area', height, width }`
   - Initialize chart via `createChart(container, { width, height })`, add series via `addCandlestickSeries()` or `addLineSeries()`
   - Handle data updates and resize events

3. **Migrate existing recharts instances**:
   - Identify all `<BarChart>`, `<LineChart>` components rendering OHLCV or time-series data
   - Replace with `<LightweightChart>` for financial data; keep recharts for non-financial (e.g., equity allocation pie charts)

4. **Attribution**: Add TradingView logo/link per Apache 2.0 NOTICE requirement (can use `attributionLogo` chart option)

### Dev tooling: Chart plugin pattern (optional follow-up)
Document a pattern in `dashboard/lib/chart-plugins/README.md` for wrapping custom indicators (e.g., Bollinger Bands, RSI overlays) as lightweight-charts plugins, enabling reuse across dashboard views.

## License & attribution

**Apache License 2.0** — Permissive; commercial use allowed.

**Attribution requirement**: Per NOTICE file, must credit TradingView as product creator and include link to https://www.tradingview.com/ on pages displaying the chart. Recommendation: use `attributionLogo` chart option (built-in) rather than manual HTML.

**File header**: Include Apache 2.0 license text + TradingView attribution in `dashboard/src/components/LightweightChart.tsx`.

## Effort estimate

**S** (2 hr) — Wrapper component + migrate 1–2 existing recharts instances. Bundle size savings are immediate (recharts ~40KB minified vs. lightweight-charts ~35KB + no tree-shake deps). Performance testing (large dataset rendering) should follow as separate task.

## Red flags

- **Attribution required**: TradingView link/logo must appear on chart. Minor UX concern if placed off-chart; `attributionLogo` option mitigates.
- **Ecosystem smaller than recharts**: Fewer third-party plugins. Mitigated by TradingView's own plugin examples and active community.
- **Type safety in React**: Library is vanilla TypeScript; integration into Next.js/React requires careful ref handling. See [React examples in docs](https://tradingview.github.io/lightweight-charts/).
- **Not a dedup**: Currently using recharts; lightweight-charts is a *replacement*, not duplication. Decision is whether to prioritize bundle size + performance (lightweight-charts) over UI customization flexibility (recharts).

## Decision gate

**Next step**: User approval to wire wrapper component into dashboard component library. Pair with a performance audit of existing recharts instances to identify quick wins (large time-series datasets that would benefit most from lightweight-charts rendering).
