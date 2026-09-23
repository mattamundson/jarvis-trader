# Lightweight Charts dashboard integration contract

Date: 2026-09-13
Wave: GitHub repo consolidation Wave 18
Source repo mined: `mattamundson/lightweight-charts` / upstream `tradingview/lightweight-charts`
Target repo: `mattamundson/jarvis-trader`

Scope: docs/research integration contract only. This document does not authorize or implement live trading, paper order routing, broker routing, risk-limit changes, kill-switch changes, `.env` edits, API-key handling, PM2 changes, active instrument gate changes, strategy promotion, or order behavior changes.

## Why this pass is non-duplicative

Wave 8 defined what chart review must prove: provenance, linked outcomes, and `execution_authority = none`.
Wave 16 defined how TradingView MCP captures should be bounded: compact external evidence, not market-data authority.
Wave 18 defines the native dashboard renderer contract for Lightweight Charts: what data shape, render behavior, performance guard, interaction contract, and visual-regression evidence must exist before JARVIS relies on native chart panels for SPY/QQQ/VIX options context or MES paper-review evidence.

The immediate value is asymmetric: JARVIS already depends on `lightweight-charts` `^5.1.0` in `dashboard/package.json`, and `dashboard/components/charts/LightweightSeriesChart.tsx` already wraps line/area/histogram rendering. A contract can harden future dashboard work without touching engine/risk/order surfaces.

## Source provenance

Fresh readback source paths from `mattamundson/lightweight-charts` default branch `master`:

| Source path | Evidence used | Hash / size |
|---|---|---:|
| repository tree | Recursive GitHub tree readback | tree `3a0157201f9ea24fe6b82fdbc98a83d58adfb12e`, `truncated=false` |
| `README.md` | purpose, small/fast HTML5 financial charts, plugin architecture, attribution requirement | blob `41e75eb420b1b0e0b626ad920bd48a3f6983ce73`, 6,601 bytes |
| `package.json` | package metadata, version, module export, dependency profile | blob `eed4e3024644b714fd1b853f7134713b7abda133`, 5,546 bytes |
| `website/docs/intro.mdx` | client-side/ES2020 boundary, TypeScript declarations, `setData` vs `update`, attribution | blob `a0b85baaba87160f2651d86152b1b2f5f4f287bf`, 7,420 bytes |
| `website/docs/chart-types.mdx` | standard time chart, yield-curve chart, options chart, custom horizontal scale | blob `772849a5f5fa5e2f69f71fe674d8c00be1f81089`, 6,561 bytes |
| `website/docs/time-scale.md` | visible range, logical range, `fitContent`, right offset and bar spacing controls | blob `79566bd0b3692c94250fdfe48017d6d802eafb53`, 5,718 bytes |
| `website/docs/panes.md` | pane separation, volume/regime panes, pane lifecycle controls | blob `340fc28b71c267147ba5d444895124ad8401e55f`, 1,816 bytes |
| `website/docs/plugins/intro.md` | custom series, series primitives, pane primitives | blob `8deb84f1976f86aefb29b6d05a1a3343031f0246`, 4,204 bytes |
| `website/tutorials/how_to/series-markers.mdx` | event markers attached by time, not free-floating claims | blob `bacfb6591ff4e6dcae8461d2ca08fe789d5ef000`, 2,333 bytes |
| `website/tutorials/how_to/price-line.mdx` | horizontal price lines for deterministic levels | blob `24324a059828e244de0e82fdd328c61816821c43`, 1,767 bytes |
| `website/tutorials/how_to/tooltips.mdx` | crosshair subscriptions and tooltip data lookup | blob `0d8a0b46c26f0cf560a6cecd347715ab062509ef`, 4,934 bytes |
| `website/tutorials/how_to/set-crosshair-position.mdx` | synchronized crosshair for multi-chart review | blob `92b6d4a98755c9a9c6aa41aac66eabb32ebfd64e`, 2,003 bytes |
| `website/tutorials/demos/realtime-updates.mdx` | `series.update(...)` for latest-bar updates and `scrollToRealtime` | blob `824d5e21c02a7c40cffe55a9c496764fc102def6`, 1,175 bytes |
| `website/tutorials/demos/infinite-history.mdx` | `subscribeVisibleLogicalRangeChange` for lazy historical loading | blob `babd4e8a6322477ed7519855f3c8b33a49d9e7db`, 1,505 bytes |
| `tests/e2e/graphics/test-cases/series/price-lines.js` | visual E2E coverage pattern for price-line rendering | blob `20b1e9f0b1a4603dd962eb1a694e668a274e4b64`, 1,219 bytes |
| `tests/e2e/graphics/test-cases/time-scale/updates-shift-the-timescale.js` | visual E2E coverage pattern for update/scroll behavior | blob `413edf6129d2033d81550fdef5a53b61c9f7c49b`, 1,475 bytes |
| `tests/e2e/interactions/test-cases/markers/hit-test-after-timescale-change.js` | interaction E2E coverage pattern for marker hit tests after scale changes | blob `c1bad98827fd19e7695b97e4bd3ef97558679f5a`, 2,123 bytes |

Source facts mined:

- Lightweight Charts is a client-side financial HTML5 charting library optimized for small, fast interactive web charts.
- The package is TypeScript-native, exports ES modules, targets modern browsers/ES2020, and is not designed for server-side rendering execution.
- JARVIS dashboard already has `lightweight-charts` `^5.1.0` installed and a client-only wrapper at `dashboard/components/charts/LightweightSeriesChart.tsx`.
- `setData` replaces the complete series and is appropriate for initial/full fixture loads; `update` changes the latest point or appends one point and is the preferred path for realtime refreshes.
- Time scale visible ranges can be controlled by data range or logical range; logical range supports margin/edge control and preloading triggers.
- Price lines and series markers are deterministic chart annotations when derived from engine/journal artifacts.
- Tooltips are custom DOM attached to crosshair events; tooltip values must be read from series data, not recomputed ad hoc in the UI.
- Plugin primitives and panes can express custom overlays, but they introduce a rendering lifecycle that needs visual E2E coverage.
- The license requires TradingView attribution or the `attributionLogo` chart option / explicit TradingView link.

## JARVIS adaptation principle

Native dashboard charts are renderer surfaces for already-certified JARVIS data. They must never become a new data source, strategy authority, or execution path.

The allowed flow is:

```text
engine/report/evidence artifact -> typed chart view model -> Lightweight Charts renderer -> chart-review record/journal link
```

The blocked flow is:

```text
chart interaction -> signal/risk/order mutation
```

A chart can make evidence easier to inspect. It cannot make a trade eligible.

## Required dashboard chart contract

### LWC-1 — Client-only renderer boundary

Lightweight Charts code must remain inside client components or browser-only dynamic imports.

Required checks:

- No direct `createChart(...)` calls in server components, route handlers, or Node-only scripts.
- A chart component handles `ResizeObserver` lifecycle and `chart.remove()` cleanup.
- Server-rendered pages pass plain serializable view models into chart clients; no DOM/window access before hydration.
- A missing container, empty data set, or unavailable source renders a labeled empty state rather than throwing.

Acceptance check:

- `dashboard` typecheck/build succeeds, and an SSR route containing chart metadata can render without importing the browser renderer server-side.

### LWC-2 — Typed view-model data contract

Every native chart panel must consume a typed view model rather than raw endpoint payloads.

Minimum shape:

```json
{
  "chart_id": "jarvis_chart_spy_15m_options_context",
  "created_at_utc": "2026-09-13T00:00:00Z",
  "symbol": "SPY",
  "asset_class": "equity|option|future|index|volatility|macro|unknown",
  "timeframe": "15m",
  "data_source": "engine_cache|ibkr|databento|yfinance|fred|journal_artifact|fixture",
  "freshness_seconds": 0,
  "series": [
    {
      "id": "price",
      "kind": "candlestick|line|area|histogram|baseline|custom",
      "price_format": "price|dollar|percent|integer",
      "pane": "main",
      "points": []
    }
  ],
  "annotations": {
    "price_lines": [],
    "markers": [],
    "bands": []
  },
  "linked_artifacts": [],
  "safety": {
    "execution_authority": "none",
    "may_place_order": false,
    "may_change_risk": false,
    "may_change_gate": false
  }
}
```

Required validation:

- Points are sorted by time and have no duplicate timestamps within a series.
- Candlestick points satisfy `high >= max(open, close)` and `low <= min(open, close)`.
- Line/area/histogram values are finite numbers.
- Annotation prices are finite numbers and tick-rounded where the linked instrument has a tick size.
- Every rendered chart carries `data_source`, `freshness_seconds`, and a linked artifact or fixture ID.

Acceptance check:

- Unit tests reject malformed OHLC, duplicate timestamps, NaN/Infinity values, and missing provenance before data reaches the renderer.

### LWC-3 — Deterministic annotation contract

Price lines, markers, and bands must be derived from named artifacts, not typed directly into JSX as untraceable numbers.

Allowed annotation sources:

- paper trade/order ledger records
- strategy-registry/backtest artifacts
- chart-review evidence records
- known session levels from a cited research report
- options chain snapshot artifacts for SPY/QQQ/VIX
- explicit manual journal level with author, timestamp, and invalidation text

Required fields for each annotation:

```json
{
  "annotation_id": "level_prior_high_20260913",
  "kind": "price_line|series_marker|band|range|watermark",
  "source_artifact": "docs/reports/...json",
  "source_field": "levels.prior_high",
  "created_at_utc": "2026-09-13T00:00:00Z",
  "label": "Prior high",
  "price": 0.0,
  "time": null,
  "confidence": "measured|manual|derived|unknown",
  "execution_authority": "none"
}
```

Acceptance check:

- A reviewer can click or inspect an annotation and identify the exact artifact/field that created it.

### LWC-4 — Performance and update contract

The chart should use full replacements only when the full series changes, and incremental updates only when appending/updating the latest bar.

Rules:

- Initial load / fixture swap / symbol change: `series.setData(...)` is allowed.
- Polling or websocket latest-bar refresh: prefer `series.update(...)` for the affected latest point.
- Historical scrollback: use a logical-range trigger to request older data; do not pre-render deep caches by default.
- Avoid calling `fitContent()` after every polling update if the operator has manually scrolled away from realtime.
- Preserve a visible `Go to realtime` affordance when the user has scrolled left and fresh data arrives.
- Cap default render windows by route purpose: compact card <= 250 points; review page <= 2,000 points; expanded research view may lazy-load more.

Acceptance check:

- A Playwright test or node-level adapter test proves latest-bar updates do not replace the whole view model unless the chart identity changes.

### LWC-5 — Multi-pane options/futures review contract

Use panes when mixing unlike units; do not compress price, volume, volatility, and probability into one y-axis.

Recommended pane split:

| Pane | Series/annotations | Required provenance |
|---|---|---|
| Main | price candles/line, paper trade markers, deterministic price lines | engine/market-data source and linked ledger/report IDs |
| Volume/open interest | volume histogram, option OI when available | feed snapshot and freshness |
| Volatility/probability | VIX line, IV rank, touch/close probability bands | model/report artifact and timestamp |
| Regime/context | macro/FRED features, session labels, event flags | feature snapshot ID |

Acceptance check:

- Each pane declares its unit and source; the UI never plots options probability and underlying price on the same unlabeled price scale.

### LWC-6 — Interaction and crosshair contract

Crosshair, tooltip, and synchronized-chart interactions are inspection tools only.

Rules:

- Tooltip content must be read from the series point / chart view model and formatted consistently with the source unit.
- Crosshair sync between SPY/QQQ/VIX or price/options panels must use the chart time/point mapping only for inspection.
- No tooltip/crosshair event can call an engine mutation endpoint, order route, risk route, `.env` path, or gate update path.
- If an interaction creates a journal note, it must create `decision = journal_only | hypothesis | backtest_candidate | postmortem | no_action` and `execution_authority = none`.

Acceptance check:

- Static or test guard proves chart interaction handlers import no order/risk/broker/gate mutation clients.

### LWC-7 — Attribution and license guard

Any public/user-facing route using Lightweight Charts must visibly satisfy the TradingView attribution requirement.

Allowed approaches:

- `attributionLogo` enabled where visually compatible.
- Explicit visible TradingView attribution/link near the chart component.
- A route-level footer/link if the chart is within a constrained card where logo overlay harms readability.

Acceptance check:

- A dashboard smoke test or DOM assertion finds `TradingView` attribution/link on routes rendering Lightweight Charts.

### LWC-8 — Visual regression and hit-test evidence

Because charts can be numerically right but visually misleading, the verification layer must include rendered-output checks.

Minimum future implementation tests:

- Chart renders a known fixture with expected price line labels and marker labels.
- Hit testing still finds markers after time-scale changes.
- Latest-bar `update(...)` keeps realtime-scroll behavior distinct from manual-scroll behavior.
- Stale/unavailable data shows provenance badges rather than a blank chart.
- Screenshot or DOM snapshot evidence is retained for chart-review routes.

Acceptance check:

- Fresh-server Playwright runs against a fixture route, not a reused production server, and stores a trace/screenshot on failure.

## Options-specific leverage for SPY/QQQ/VIX

Lightweight Charts adds the most JARVIS leverage when it renders option context as an evidence object rather than a screenshot.

High-value native panels:

1. SPY/QQQ underlying price with option-entry windows, expected-move bands, and touch/close probability bands.
2. VIX term/regime line with labels for options-plan invalidation.
3. Strike ladder or `createOptionsChart`-style price-horizontal view for expiration-specific chain context.
4. Post-trade review overlay: entry marker, max favorable/adverse excursion, exit marker, thesis/invalidation label.
5. Backtest report overlay: in-sample/out-of-sample window shading and strategy-registry verdict markers.

Required boundary:

- These panels may inform discretionary/manual review. They do not change `paper_config.py`, live risk, broker routing, kill-switch state, or active instrument gates.

## Future implementation sequence

1. Add a pure TypeScript chart view-model validator and fixtures.
2. Extend `LightweightSeriesChart.tsx` or create a richer `FinancialReviewChart.tsx` client component with candlestick, marker, price-line, pane, tooltip, and attribution support.
3. Add a fixture route under dashboard test scope only; verify render, provenance, attribution, marker/price-line labels, and stale state.
4. Add SPY/QQQ/VIX options context panels only after the options snapshot contract is certified.
5. Link chart-review records to second-brain/journal artifacts without allowing UI interactions to mutate execution state.

## Verification checklist for future implementation PRs

- `dashboard/package.json` still uses `pnpm`; no npm lockfile churn is introduced.
- `./node_modules/.bin/tsc --noEmit` passes in `dashboard/`.
- `pnpm run build:clean` passes in `dashboard/` or the PR explains why build cannot run in the environment.
- Fresh-server Playwright route smoke covers at least one chart with provenance, attribution, price line, marker, and stale-data state.
- Unit tests validate chart view-model ordering, OHLC invariants, finite values, and `execution_authority = none`.
- Secret scan confirms no TradingView/session/API credentials are embedded in chart fixtures or captured artifacts.
- No files under `engine/config.py`, `engine/risk/`, broker routing, `engine/.env`, `dashboard/.env.local`, PM2 configs, active instrument gates, or order behavior changed unless this is a separate `[safety-review]` PR.

## Blocked without separate review

- Using Lightweight Charts as a source of market data.
- Scraping chart output into backtest caches.
- Letting chart clicks create orders, risk changes, or strategy promotions.
- Bulk-rendering deep caches in default dashboard routes without explicit performance budget and lazy-loading design.
- Hiding TradingView attribution on user-facing routes.
