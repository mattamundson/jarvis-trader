---
repo: ChromeDevTools/chrome-devtools-mcp
url: https://github.com/ChromeDevTools/chrome-devtools-mcp
stars: 2600
language: TypeScript
license: Apache 2.0
archived: false
pushed_at: 2026-04-10
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [dev-tooling, engine-code]
---

# ChromeDevTools/chrome-devtools-mcp

## Core value proposition

Chrome DevTools MCP provides Model Context Protocol access to the Chrome DevTools Protocol, allowing Claude agents to control live Chrome instances, capture screenshots, analyze network requests, and extract performance traces. The server uses Puppeteer for reliable automation and exposes full browser inspection via MCP tools (navigate, click, wait, capture, etc.), enabling agents to interact with and analyze web UIs programmatically.

## Surface analysis

### 1. Engine code

**partial-integrate** — `engine/agents/pattern_vision_analyst.py` (new, planned) requires chart-capture capability. Chrome DevTools MCP is ALREADY CONFIGURED in `.mcp.json:13-17` and wired into project `.claude/settings.local.json`. The MCP server can be invoked to take screenshots and record performance traces of TradingView charts or internal dashboards. Current blockers are purely at the agent integration layer (schema definition, vision API wiring, token budgeting), not the MCP availability.

### 2. Project rules

**no-fit** — Chrome DevTools MCP is purely a tool/infrastructure enabler, not a coding discipline, safety pattern, or testing convention. It has no philosophy to absorb into `.claude/rules/*.md`.

### 3. Project skills

**no-fit** — The MCP itself does not provide skills. However, its tool surface maps well to potential future skills for automated chart analysis (e.g., `/chart-pattern-scan`), UI regression testing, or performance profiling. For now, the MCP tools are used raw by `pattern_vision_analyst.py`; a skill wrapper is deferred.

### 4. Slash commands

**no-fit** — No new commands are triggered by the Chrome DevTools MCP. The MCP is invoked from agent code only (e.g., `pattern_vision_analyst.py` calling screenshot tool), not from interactive commands.

### 5. Subagents

**no-fit** — Chrome DevTools MCP is infrastructure, not a specialized analyzer. However, a future **Pattern Vision Agent** subagent (currently blocked) would depend on this MCP for its chart-capture pipeline.

### 6. Docs

**integrate-now** — Surface the MCP wiring and chart-capture prerequisites in `docs/architecture/` or `docs/roadmap/`. Specifically, update the Pattern Vision Agent blocker doc (`docs/digest/ml-ai-synthesis.md` line ~31) to link to this analysis and confirm MCP is "ready for wiring, blocker is agent-side only."

### 7. Dev tooling

**dedup-surface-7** — Chrome DevTools MCP is ALREADY ADDED (commit d99fad4 per MEMORY.md). Configuration is at `.mcp.json:13-17` with args `["-y", "chrome-devtools-mcp@latest", "--no-usage-statistics"]`. MCP server starts automatically when Claude Code launches, ready to serve tools. No additional wiring required on the dev-tooling surface.

### 8. Dashboard

**no-fit** — Chrome DevTools MCP does not provide React components, Tailwind patterns, or chart widgets. Its utility is strictly in *capturing* UI state, not rendering it. Dashboard integration would be a future skill-layer feature (e.g., a `/chart-screenshot` endpoint that calls the MCP and returns the image).

### 9. Ops / messaging

**no-fit** — Chrome DevTools MCP has no notification, cron, or messaging integration. It is a synchronous tool server; agents call it on-demand during analysis, not scheduled.

## Integration plan

No new integrations needed at this moment — the MCP is already configured and operational. However, to **unblock the Pattern Vision Agent**, complete the following in `engine/agents/pattern_vision_analyst.py`:

1. **Define the Pattern Agent interface** (input: price chart data, output: pattern classification + confidence).
2. **Implement chart-capture hook** — call `screenshot` tool from Chrome DevTools MCP to grab TradingView or internal chart.
3. **Encode screenshot to PNG/base64** — feed to Claude vision API (Claude Opus) for pattern matching.
4. **Cache via TokenProxy** — reuse `engine/utils/token_proxy.py` (300s TTL) to avoid re-capturing the same chart multiple times within a 5min window.
5. **Wire into `pipeline.py`** — add pattern_analyst as 6th analyst in the async 5-analyst debate loop.
6. **Tests** — `engine/tests/test_pattern_vision_analyst.py` with 30 historical MCL 1h setups; compare vision-only vs (Hidden Pivots + vision) combined verdict on realized 2h forward pnl.

## License & attribution

Apache 2.0. Attribution: Chrome DevTools MCP is maintained by Google. File header in `engine/agents/pattern_vision_analyst.py` (or wherever the tool is invoked) should note "Uses Chrome DevTools MCP (Google, Apache 2.0) for browser control and screenshot capture."

## Effort estimate

**S** (under 2hr) to confirm MCP is operational and unblock the Pattern Agent docs. **M** (2-8hr) to implement the full pattern_vision_analyst.py + wiring + tests (not part of this analysis; see roadmap-2026-04-15.md T2.2).

## Red flags

**None.** MCP is already in place, actively maintained by Google, and properly licensed. The only "blocker" is the agent-side pattern-matching implementation, which is out of scope for the MCP itself. Recommendation: mark the MCP as **ready for use** in the Pattern Vision roadmap.

