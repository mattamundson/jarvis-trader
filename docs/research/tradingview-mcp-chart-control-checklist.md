# TradingView MCP chart-control checklist

Date: 2026-09-13
Wave: GitHub repo consolidation Wave 16
Source repo mined: `mattamundson/tradingview-mcp` / upstream `tradesdontlie/tradingview-mcp`
Target repo: `mattamundson/jarvis-trader`

Scope: docs/research control checklist only. This document does not authorize or implement live trading, paper order routing, broker routing, risk-limit changes, kill-switch changes, `.env` edits, API-key handling, PM2 changes, active instrument gate changes, or order behavior changes.

## Source provenance

Readback source paths and hashes from `mattamundson/tradingview-mcp` default branch `main`:

| Source path | Evidence used | Hash / size |
|---|---|---:|
| repository tree | Recursive GitHub tree readback | tree `c05b8f5755ed8e64ea242de88ddbf46aa24d56a4`, `truncated=false` |
| `README.md` | Architecture, safety boundaries, command catalog, disclaimer | blob `7d5840b931a2056f2d0e05da8a1e4fc6a8ee2f34`, 18,364 bytes |
| `CLAUDE.md` | Agent decision tree and context-management rules | blob `9ca8e28230b59292116f16b4736eb444ed790cf3`, 6,973 bytes |
| `RESEARCH.md` | Research questions and findings | blob `acc05197bdf3211171221fd7b8ab182bd4a6d9bd`, 6,013 bytes |
| `skills/chart-analysis/SKILL.md` | Chart-review workflow | blob `72a9ecf52b8c0a9fd4c980f404b62664b14aaa68`, 2,078 bytes |
| `tests/sanitization.test.js` | CDP input/path validation patterns | blob `6bb15dfe96aebe5202ef7e61656db1a5fa3550ec`, 13,058 bytes |

Source facts mined:

- TradingView MCP connects to a locally running TradingView Desktop app through Chrome DevTools Protocol on `localhost:9222`.
- The debug port is disabled by default and requires explicit user launch with `--remote-debugging-port=9222`.
- The project explicitly says it does not connect to TradingView servers, bypass paywalls, redistribute market data, or execute real trades.
- It exposes granular chart tools for state, quote, OHLCV, Pine drawings/tables/labels/boxes, indicators, layouts, panes, tabs, screenshots, replay, alerts, and UI automation.
- Its own research notes identify context size, temporal consistency, tool granularity, failure transparency, and human-in-the-loop boundaries as the core research constraints.
- Its sanitization tests emphasize `safeString()`, finite numeric validation, no raw user-input interpolation in CDP `evaluate()` strings, and path-separator stripping for generated filenames.

## JARVIS adaptation principle

TradingView MCP should be treated as a read-only external chart-evidence capture surface for JARVIS, not as a market-data authority, strategy-promotion authority, or execution surface.

The safe JARVIS value is asymmetric:

1. High upside: capture discretionary chart context, Pine output, visual levels, and screenshots that explain a hypothesis or paper-trade review.
2. Controlled downside: require provenance, staleness labeling, input sanitization, and `execution_authority = none` so chart interaction cannot bypass engine gates.

## Mandatory boundaries

### TVC-1 — Execution authority is always none

Every TradingView MCP-derived artifact must carry:

```json
{
  "source": "tradingview_mcp",
  "execution_authority": "none",
  "may_place_order": false,
  "may_change_risk": false,
  "may_change_gate": false
}
```

Hard prohibitions for this lineage:

- no paper or live order placement
- no replay-trade output promoted as a real trade
- no broker connection mutation
- no kill-switch state mutation
- no risk-limit mutation
- no `.env` mutation
- no PM2 or service restart
- no active instrument gate mutation
- no strategy-registry promotion from chart evidence alone
- no automation path from `alert_create`, `replay_trade`, `ui_click`, or any chart tool to JARVIS order routing

Acceptance check:

- A grep across the implementation diff shows no changes under `engine/config.py`, `engine/risk/`, broker routing, `engine/.env`, `dashboard/.env.local`, active instrument gates, or PM2 files unless the PR is a separate `[safety-review]` PR.

### TVC-2 — TradingView terms and data-license guard

TradingView MCP's README warns that programmatic data consumption may conflict with TradingView terms and exchange data licenses.

JARVIS must therefore use it only for personal review artifacts, not for bulk historical data collection.

Allowed:

- screenshot of the currently visible chart
- compact current quote snapshot for context
- compact OHLCV summary when used to label a screenshot
- visible Pine levels/labels/tables/boxes for the current review
- Pine compile errors and static linting for user-owned scripts

Blocked without separate legal/operator review:

- continuous data scraping
- replaying exported data as backtest ground truth
- storing bulk OHLCV streams as a JARVIS research cache
- redistributing screenshots or market data externally
- using TradingView data as the canonical feed for strategy certification

Acceptance check:

- Any capture artifact with more than a compact summary must state why it is needed, where it is stored, and why it is not replacing Databento/IBKR/FRED/YFinance feed provenance.

### TVC-3 — Source-vs-engine truth split

TradingView chart state is a human-context artifact. JARVIS engine data remains the quantitative source of truth.

Required split:

| Question | Authority |
|---|---|
| What did Amo visually review? | TradingView MCP screenshot + chart metadata |
| What did the engine calculate? | JARVIS engine endpoint/report/verdict |
| What did the backtest prove? | Backtest artifact with data provenance and gate metrics |
| Can a strategy trade? | Strategy registry + gate-v2 + safety layer |
| Can an order route? | Paper/live execution policy, kill switch, and broker gates |

Acceptance check:

- Chart-review records must link to engine/backtest artifacts rather than copying unverified engine claims into free text.

## Recommended chart-review evidence schema

A future validator can enforce this shape before dashboard integration:

```json
{
  "chart_review_id": "tvc_YYYYMMDD_symbol_timeframe_slug",
  "created_at_utc": "2026-09-13T00:00:00Z",
  "reviewer": "agent|human|hybrid",
  "source": "tradingview_mcp",
  "source_repo": {
    "name": "mattamundson/tradingview-mcp",
    "tree_sha": "c05b8f5755ed8e64ea242de88ddbf46aa24d56a4"
  },
  "chart": {
    "symbol_displayed": "SPY",
    "asset_class": "equity|option|future|index|volatility|unknown",
    "timeframe": "15m",
    "chart_type": "Candles",
    "visible_range_start_utc": null,
    "visible_range_end_utc": null,
    "tradingview_layout": null
  },
  "cdp": {
    "host": "127.0.0.1",
    "port": 9222,
    "health_checked_at_utc": null,
    "health_status": "pass|fail|not_checked"
  },
  "compact_data": {
    "quote_snapshot": null,
    "ohlcv_summary": null,
    "indicator_values": [],
    "pine_lines": [],
    "pine_labels": [],
    "pine_tables": [],
    "pine_boxes": []
  },
  "artifacts": {
    "screenshot_uri": null,
    "pine_source_sha256": null,
    "pine_compile_status": "pass|fail|not_applicable"
  },
  "linked_jarvis_artifacts": {
    "trade_id": null,
    "strategy_id": null,
    "backtest_artifact": null,
    "journal_note": null
  },
  "review_output": {
    "hypothesis": null,
    "levels": [],
    "bias": "bullish|bearish|neutral|mixed|not_assessed",
    "invalidation": null,
    "decision": "journal_only|hypothesis|backtest_candidate|postmortem|no_action"
  },
  "safety": {
    "execution_authority": "none",
    "terms_data_license_review": "compact_personal_review_only",
    "gate_required_before_promotion": true
  }
}
```

## Capture workflow checklist

### Step 1 — Pre-capture declaration

Record before using any chart tool:

- target symbol and venue exactly as displayed
- intended use: `pretrade_watchlist`, `hypothesis`, `post_trade_review`, `backtest_critique`, `pine_dev`, or `no_action`
- expected linked artifact: trade ID, strategy ID, backtest report, or journal note
- statement that execution authority is none

Acceptance check:

- A reviewer can reject a capture with no purpose before it enters the journal.

### Step 2 — Minimal chart state pull

Use compact-first ordering adapted from the source repo:

1. chart state: symbol, timeframe, chart type, visible indicators, entity IDs
2. current quote snapshot only if needed for timestamped context
3. study values for visible indicators
4. Pine lines/labels/tables/boxes with `study_filter` when known
5. OHLCV with summary mode only unless a specific review requires bars
6. screenshot path

Acceptance check:

- The evidence record stores the tool sequence and payload size class: `compact`, `expanded`, or `screenshot_only`.

### Step 3 — Staleness and temporal consistency label

Market data changes faster than an LLM review can complete. Every review must state:

- quote timestamp or `unknown`
- capture timestamp
- response timestamp
- maximum age in seconds between capture and generated conclusion
- whether the conclusion is valid only for the captured screenshot or intended as a durable research hypothesis

Acceptance check:

- If age is unknown, the record label is `staleness_unknown`, not `fresh`.

### Step 4 — Visual interpretation discipline

A chart interpretation is allowed to produce:

- support/resistance candidate levels
- volatility/regime hypothesis
- options context question for SPY/QQQ/VIX
- Pine bug report or indicator-parity question
- post-trade explanation
- backtest candidate requiring data-source certification

A chart interpretation is not allowed to produce:

- order ticket
- position size
- live/paper routing instruction
- gate-v2 override
- risk-limit adjustment
- broker/kill-switch instruction

Acceptance check:

- Generated summaries must use one of the approved `decision` enum values and must not contain imperative broker/execution commands.

### Step 5 — Cross-check against JARVIS authority

Before a chart review becomes more than a journal note, cross-check:

- strategy exists in the registry or is explicitly a new hypothesis
- any metric claim is backed by an engine/backtest artifact
- any options claim has options-data provenance, not only equity-chart inference
- any future implementation PR labels chart evidence as supporting context, not proof

Acceptance check:

- `backtest_candidate` decisions must include a missing-evidence list before any coding starts.

## Pine development controls

TradingView MCP's strongest use case is Pine compile/error iteration. JARVIS should capture Pine output as a prototype artifact only.

Required controls:

- Store Pine source hash, not necessarily full source, unless the script is user-owned and intentionally versioned.
- If full Pine source is stored, scan for secrets, account IDs, webhook URLs, and proprietary third-party script content.
- Compile success is syntax evidence only; it is not statistical edge evidence.
- Pine strategy tester output is exploratory and cannot replace JARVIS backtest gates.
- Any indicator later ported into Python must pass parity testing with golden vectors and repainting checks.

Acceptance check:

- A Pine-to-JARVIS port ticket must cite an indicator parity test plan before any engine strategy implementation.

## UI automation and injection controls

Because the source repo exposes UI automation and CDP `evaluate()` paths, any JARVIS adapter must inherit a strict input-safety checklist:

- Every symbol, timeframe, indicator name, text annotation, alert condition, and UI selector is treated as untrusted input.
- Strings sent into CDP evaluation are JSON-escaped, not manually concatenated.
- Numeric coordinates/prices/timestamps must be finite numbers.
- Screenshot/capture filenames strip path separators.
- UI operations are allowlisted by intent: chart navigation, indicator visibility, drawing annotation, screenshot capture.
- The TradingView trading panel must not be opened by automation in this lineage.
- Source examples mentioning symbols outside JARVIS authorization are not operational instructions; MCL and MNQ remain DO_NOT_TRADE symbols.

Acceptance check:

- A future implementation includes a fixture-level test equivalent to `safeString()`, `requireFinite()`, no raw CDP interpolation, and filename path-sanitization coverage.

## Dashboard integration boundaries

A future dashboard PR should implement chart-review display as a read-only evidence browser:

- no dependency on TradingView Desktop being live for page load
- capture import reads immutable artifacts from disk or API
- provenance badges distinguish `engine_truth`, `tradingview_capture`, `stale_capture`, and `journal_only`
- screenshot is displayed beside the compact JSON summary
- linked JARVIS artifacts remain clickable but cannot be mutated from the chart-review page
- unavailable TradingView MCP is a warning state, not a dashboard outage

Acceptance check:

- Fresh-server Playwright must prove the page renders an old capture with `execution_authority = none` and an explicit stale/provenance badge.

## Failure modes to guard

| Failure mode | Control |
|---|---|
| Agent treats TradingView quote as canonical market data | Engine/backtest authority split; provenance badge required |
| Stale screenshot influences current-session decision | capture/response age label required |
| Pine compile success mistaken for strategy edge | compile status classified as syntax-only evidence |
| CDP string injection through symbol or annotation | JSON escaping + source audit test |
| Path traversal through screenshot filename | separator stripping test |
| TradingView terms violation via bulk data collection | compact personal-review-only policy |
| Chart automation opens trading panel | UI operation allowlist blocks trading-panel automation |
| Replay trade looks like a real JARVIS trade | replay artifacts carry `simulated_replay_only` and `execution_authority=none` |
| MCL/MNQ examples leak into operational commands | source examples treated as non-operational; JARVIS DO_NOT_TRADE remains authoritative |

## Verification checklist for future implementation PRs

Minimum gates before a chart-control implementation can merge:

1. `git diff --name-only` confirms no forbidden trading runtime/config files changed.
2. Schema fixture validates `execution_authority = none` for every TradingView MCP-derived record.
3. Secret scan over capture artifacts reports zero API keys, session tokens, webhooks, or account identifiers.
4. CDP input-safety tests cover strings, finite numbers, and filenames.
5. Dashboard typecheck passes.
6. Dashboard build passes using `pnpm`.
7. Fresh-server Playwright renders one engine-truth chart and one TradingView capture with distinct provenance labels.
8. Any generated chart conclusion with `backtest_candidate` includes a missing-evidence list and no order instruction.

## Safe next PR candidates

1. Add `chart_review_capture` JSON schema and fixtures under docs/tests only.
2. Add a static example capture for SPY/QQQ/VIX review with all provenance fields but no live data dependency.
3. Add a dashboard read-only capture browser after the schema exists.
4. Add Pine-to-Python indicator parity checklist for user-owned scripts.

Unsafe without `[safety-review]` PR:

- feeding TradingView MCP output into order routing
- changing allowed/blocked instruments
- changing risk or kill-switch parameters
- auto-opening broker/trading panels
- treating replay results as paper ledger records
