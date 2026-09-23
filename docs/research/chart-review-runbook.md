# TradingView + Lightweight Charts Review Runbook

**Status:** draft · **Owner:** strategy-research + dashboard · **Audience:** discretionary reviewers, strategy researchers, postmortem authors  
**Scope:** capture a chart state for a strategy decision, review it in JARVIS Mission Control, and link the capture to the strategy record or journal entry.

> This runbook is a distillation of two reference repos: `tradingview-mcp` (personal AI assistant for the TradingView Desktop app via Chrome DevTools Protocol) and `lightweight-charts` (performant HTML5 canvas financial charts). It is not a replacement for either tool; it describes where each fits in a JARVIS review workflow.

---

## 1. Two-tool model

### TradingView MCP (chart capture / Pine prototyping)

Use when you need eyes on the live TradingView Desktop app: symbol/timeframe navigation, indicator reads, Pine Script write/compile/debug, annotations, replay.

- **What it does:** bridges Claude Code (or another MCP host) to a locally running TradingView Desktop instance via Chrome DevTools Protocol on `localhost:9222`.
- **What it does not do:** connect to TradingView servers, execute trades, bypass any paywall, or work without a valid TradingView Desktop subscription.
- **JARVIS relevance:** the discretionary chart-review step — visually confirm a pattern, read indicator values on the live chart, capture a screenshot for the journal, prototype a Pine Script before implementing the same logic in the engine.

**Start path:**

1. Launch TradingView Desktop with `--remote-debugging-port=9222`.
2. Install the MCP server: `git clone https://github.com/tradesdontlie/tradingview-mcp.git`, `npm install`, add the server entry to your MCP config.
3. Verify: `tv_health_check` from the Claude session.
4. Capture: `tv screenshot` for a journal artifact, or read indicator values with `data_get_study_values` before writing a strategy decision.

**JARVIS integration notes:**

- Treat the TradingView MCP capture as a **discretionary review artifact**, not a live signal source. The engine does not consume it automatically.
- If a Pine Script is prototyped here and later ported to the engine, record the original script and the port date in the strategy record provenance.
- Pin the TradingView Desktop version if chart-state stability matters for a review notebook — internal CDP interfaces can change without notice.

### Lightweight Charts (embedded review in Mission Control)

Use when you want an embedded, interactive chart inside JARVIS Mission Control or a research note without leaving the app.

- **What it does:** performant financial charts on HTML5 canvas, suitable for embedding in a dashboard or report page.
- **JARVIS relevance:** render a bars + indicator overlay from engine data inside Mission Control for a quick visual sanity check, or attach a lightweight-charts embed to a strategy record or postmortem.

**JARVIS integration notes:**

- Lightweight Charts is a charting library, not a data source. Feed it normalized bars from the JARVIS data layer.
- Keep the embed read-only for discretionary review unless you deliberately add a controlled interaction (zoom, symbol switch) behind the same auth gates as the rest of Mission Control.
- If a chart review becomes part of a promotion gate, snapshot the rendered state (or the underlying bars + indicator parameters) so the review is reproducible.

---

## 2. Review runbook

### Step 1 — Define the question

Before opening a chart, write the review question in the strategy record or journal:

- What am I trying to confirm? (pattern, level, indicator crossover, regime context)
- What would make me wrong? (kill criterion)
- What time horizon and symbol/contract am I reviewing?

This is the same discipline as the `claude-trading-skills` quant-strategy-framework kill rule: no chart review without a written thesis.

### Step 2 — Pull the data

- Prefer the JARVIS data layer first: normalized bars with provenance, freshness, and adjustment notes.
- Use TradingView MCP only when you need the live Desktop view, a screenshot, or a Pine prototype that the engine does not yet support.
- If using Lightweight Charts in Mission Control, feed it from the same data contract the strategy uses so the visual review matches the backtest reality.

### Step 3 — Review

- Read levels, indicator values, and context **on the same data the strategy will see in paper/live**.
- For discretionary confirmations, capture a screenshot or embed and attach it to the decision record.
- For Pine prototypes, note the script, the compilation result, and any differences from the eventual engine implementation.

### Step 4 — Record

- Link the chart artifact to the strategy record or journal entry.
- Record the review question, the answer, and whether the chart supported or contradicted the thesis.
- **Capture metadata:** every chart artifact must include the capture timestamp, venue/contract, session template, data source, indicator settings, and artifact path (or a link to `chart-review-dashboard-requirements.md` for the full structured evidence package). A screenshot alone is insufficient for a promotion decision or postmortem; the record must establish which bars and settings were reviewed.
- If the chart contradicted the thesis, that is a valid outcome — record it and let the kill criterion do its job.

### Step 5 — Close the loop

- If the review advanced a strategy toward promotion, update the strategy record with the chart reference and the decision.
- If the review blocked a promotion, record why and what would change the verdict.
- If the review was purely journaling, file it in `second-brain` with backlinks to the strategy or trade record.

---

## 3. Tool selection guide

| I want to… | Use | Why |
|---|---|---|
| Read the live chart from TradingView Desktop | TradingView MCP | Direct CDP bridge to the app you already use |
| Capture a screenshot for a journal entry | TradingView MCP (`tv screenshot`) | Artifact attached to the decision record |
| Prototype a Pine Script before engine port | TradingView MCP (`pine_*`) | Compile/debug the script in the real app |
| Embed an interactive chart in Mission Control | Lightweight Charts | In-app review without leaving JARVIS |
| Render a static chart for a report | Lightweight Charts (or capture) | Report artifact from engine data |
| Review strategy signals on the same data as the backtest | JARVIS data layer → Lightweight Charts | Consistency between review and backtest reality |

---

## 4. Safety and compliance notes

- TradingView MCP interacts with your locally running TradingView Desktop app via CDP. It does not connect to TradingView servers. You are responsible for compliance with TradingView's Terms of Use, including any restrictions on automated data collection or non-display usage.
- **Chart review is non-authoritative for execution.** A chart capture or Pine prototype does not become a live execution signal by virtue of having a promotion gate. The established boundary requires `execution_authority = none` for all chart-review artifacts — any promoted strategy must be a separately implemented, deterministic engine signal, not the discretionary artifact itself. The runbook ends at the decision record, not at the order.
- Do not embed live TradingView data into JARVIS without understanding the licensing terms of the underlying data. Use the JARVIS data layer's own provenance column to know what you are showing.
- Pin tool versions (TradingView Desktop build, lightweight-charts version) when a review must be reproducible.

---

## 5. Related

- Strategy registry schema: `docs/research/strategy-registry-schema.md`
- Backtest critique checklist: `docs/research/backtest-critique-checklist.md`
- Macro/FRED regime-context spec: `docs/research/macro-regime-context-spec.md`
- Source: `tradingview-mcp` — https://github.com/tradesdontlie/tradingview-mcp (personal AI assistant for TradingView Desktop via CDP; MIT)
- Source: `lightweight-charts` — https://github.com/tradingview/lightweight-charts (performant HTML5 canvas financial charts)

---

*This runbook is a distillation, not a fork. The upstream repos remain the canonical source for installation, CLI, and full tool reference.*
