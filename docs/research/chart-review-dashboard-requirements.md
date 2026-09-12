# Chart-review dashboard requirements

Date: 2026-09-12
Wave: GitHub repo consolidation Wave 8
Source repos mined:

- `mattamundson/lightweight-charts` / upstream `tradingview/lightweight-charts`
- `mattamundson/tradingview-mcp` / upstream `tradesdontlie/tradingview-mcp`

Scope: dashboard/research requirements only. This document does not authorize or implement live trading, paper order routing, risk-limit changes, kill-switch changes, broker routing, `.env` edits, active instrument gate changes, PM2 changes, or order behavior changes.

## Source facts

### Lightweight Charts

- Purpose: TradingView's financial HTML5 charting library for interactive charts on web pages.
- Current package in `dashboard/package.json`: `lightweight-charts` `^5.1.0`; `recharts` also remains installed for non-financial charts.
- Upstream package inspected from `mattamundson/lightweight-charts`: package name `lightweight-charts`, version `5.1.0`, license `Apache-2.0`.
- Useful primitives for JARVIS: candlestick/line/area time-series, plugin architecture, small financial-chart payload, and native TradingView attribution via `attributionLogo` or an explicit TradingView link.
- Local JARVIS surfaces already using charting concepts include `dashboard/components/charts/LightweightSeriesChart.tsx`, `MarketChart.tsx`, `PriceChartPanel.tsx`, `/trades/[id]/review`, and `/journal-review`.

### TradingView MCP

- Purpose: local CDP bridge into TradingView Desktop for chart analysis, Pine development, replay practice, screenshots, and local monitoring.
- Upstream package inspected from `mattamundson/tradingview-mcp`: package name `tradingview-mcp`, CLI binary `tv`, dependencies `@modelcontextprotocol/sdk` and `chrome-remote-interface`.
- Safety boundary from upstream README: it connects only to a locally running TradingView Desktop instance via Chrome DevTools Protocol and does not execute real trades.
- Upstream research finding: compact-by-default output is the primary context-management control; raw chart state, Pine source, and OHLCV payloads can otherwise become too large for agent review.
- Useful JARVIS workflow split: use TradingView MCP for external capture/annotation/provenance; use native dashboard charts for engine-truth review and repeatable evidence.

## Product goal

Build a chart-review surface that lets Amo inspect SPY/QQQ/VIX options context and futures research evidence without letting visual discretion bypass deterministic JARVIS gates.

The dashboard should answer four questions per review:

1. What exact chart/data state was reviewed?
2. Which engine/journal/trade artifacts does that chart state explain?
3. What hypothesis or post-trade lesson came from the review?
4. What gate prevents the review from directly changing execution?

## Required surfaces

### CDR-1 — Native engine-truth chart panel

The dashboard must provide a native chart panel backed by JARVIS data, not screenshots, for repeatable review.

Minimum fields:

- symbol, asset class, timeframe, and session template
- data source name and freshness timestamp
- OHLCV bars or derived line series
- trade/order markers when linked to a trade review
- strategy/signal overlays when linked to a strategy report
- regime badges: VIX/macro/session context where available
- visible attribution for TradingView when rendered through Lightweight Charts

Acceptance check:

- A reviewer can determine whether the panel is showing engine data, imported TradingView capture data, or stale/unavailable data from the displayed provenance labels.

### CDR-2 — TradingView capture evidence record

TradingView MCP captures must be stored as evidence records, not treated as live market-data authority.

Required capture metadata:

- `capture_id`
- `captured_at_utc`
- `source = tradingview_mcp`
- CDP host/port health result when available
- symbol and venue as displayed by TradingView
- timeframe/resolution
- visible range start/end
- chart type
- indicator list and input settings when available
- screenshot path or artifact URI
- optional Pine source/hash/compile status when a script is part of the review
- reviewer prompt and model/tool path that produced the interpretation

Acceptance check:

- A capture can be replayed as an evidence pointer in a journal entry without requiring the dashboard to call TradingView again.

### CDR-3 — Journal and post-trade linkage

Every chart review must link to one of these durable outcomes:

- strategy hypothesis
- pretrade watchlist note
- post-trade explanation
- backtest critique
- invalidation note
- no-action observation

The chart-review record should include:

- `linked_trade_id` when reviewing a paper/live ledger record
- `linked_strategy_id` when tied to strategy-registry research
- `linked_backtest_artifact` when tied to a report/verdict
- `decision = hypothesis | journal_only | backtest_candidate | postmortem | no_action`
- `execution_authority = none`

Acceptance check:

- A review with no linked outcome remains searchable but cannot be mistaken for a trade authorization.

### CDR-4 — Discretion boundary and safety gates

Chart review may create evidence and hypotheses only.

Hard prohibitions:

- no order placement
- no paper/live routing change
- no kill-switch state change
- no risk-limit change
- no broker connection mutation
- no `.env` mutation
- no active instrument gate mutation
- no override of gate-v2 verdicts or strategy promotion states

Acceptance check:

- Any future implementation PR touching engine/risk/order/broker/config surfaces from chart review must be labeled `[safety-review]` and kept separate from this requirements lineage.

### CDR-5 — Agent-readable compact summary

Because TradingView MCP source notes identify context size as the primary constraint, each review should emit a compact JSON summary in addition to screenshots/markdown.

Recommended summary shape:

```json
{
  "chart_review_id": "cr_YYYYMMDD_symbol_timeframe_slug",
  "symbol": "SPY",
  "timeframe": "15m",
  "source": "jarvis_dashboard|tradingview_mcp",
  "captured_at_utc": "2026-09-12T00:00:00Z",
  "provenance": {
    "data_source": "engine_cache|tradingview_mcp|ibkr|unknown",
    "freshness_seconds": 0,
    "screenshot_path": null
  },
  "levels": [
    {"kind": "support", "price": 0.0, "source": "reviewer"}
  ],
  "bias": "bullish|bearish|neutral|mixed",
  "invalidation": "plain-language invalidation condition",
  "linked_artifacts": [],
  "execution_authority": "none"
}
```

Acceptance check:

- Agent summaries are bounded and evidence-linked; screenshot-only reviews are insufficient.

## Implementation guidance for a future PR

Recommended build sequence:

1. Extend or reuse `dashboard/components/charts/LightweightSeriesChart.tsx` for the engine-truth native chart, preserving `pnpm` and existing dashboard conventions.
2. Add a read-only review record schema in docs/tests before writing UI code.
3. Add a server/API boundary that reads existing evidence artifacts; do not make the dashboard depend on a live TradingView Desktop session for page load.
4. Add UI badges for `live`, `static`, `stale`, and `capture` provenance using existing dashboard badge variants only.
5. Add Playwright coverage that proves a stale capture and an engine-data chart render with distinct provenance labels.

## Verification checklist for future implementation

- `dashboard/package.json` dependency changes, if any, are intentional and use `pnpm`.
- `./node_modules/.bin/tsc --noEmit` passes in `dashboard/`.
- `pnpm run build` or `pnpm run build:clean` passes in `dashboard/`.
- Fresh-server Playwright route smoke covers the chart-review surface.
- Fixture-level test confirms `execution_authority = none` for every chart-review record.
- Secret scan confirms no TradingView/session/API credentials are embedded in capture artifacts.
- No files under `engine/config.py`, `engine/risk/`, `engine/.env`, `dashboard/.env.local`, broker routing, kill-switch code, or active instrument gates changed.

## Open questions

- Whether chart reviews live under the existing `/journal-review` route, `/trades/[id]/review`, or a new `/chart-review` route should be decided by the dashboard owner lane.
- Whether TradingView MCP capture artifacts should be stored under `docs/research/`, `docs/reports/`, or second-brain should be decided with the evidence schema owner.
- Options-specific overlays for SPY/QQQ/VIX need a separate options data contract; this document only defines chart-review evidence boundaries.
