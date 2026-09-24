# Reference repository mining — Wave 2

**Date:** 2026-09-12  
**Source:** GitHub estate audit JSON at `C:/Users/mattm/AppData/Local/Temp/github_repo_deep_dive/repos_raw_analysis.json`  
**Scope:** read-only mining of reference/vendor forks and trading-tool repos. No vendor code was vendored in this wave.

## Repositories reviewed

| Repo | Description | Primary language bytes | Detected useful assets |
|---|---|---|---|
| [`mattamundson/claude-trading-skills`](https://github.com/mattamundson/claude-trading-skills) | Claude Code skills for equity investors and traders — market analysis, technical charting, economic calendars, screeners, and trading strategy development. | Python=8725611, Go Template=21534, HTML=11724, Shell=5074 | executable code, trading strategies, data pipelines, agent/tooling, docs/content, dashboard/ui |
| [`mattamundson/awesome-quant`](https://github.com/mattamundson/awesome-quant) | A curated list of insanely awesome libraries, packages and resources for Quants (Quantitative Finance) | HTML=856107, Python=237940, CSS=18275, Jupyter Notebook=9854 | executable code, trading strategies, data pipelines, agent/tooling, docs/content |
| [`mattamundson/TradingAgents`](https://github.com/mattamundson/TradingAgents) | TradingAgents: Multi-Agents LLM Financial Trading Framework | Python=738784, Dockerfile=606 | executable code, trading strategies, agent/tooling, docs/content |
| [`mattamundson/Vibe-Trading`](https://github.com/mattamundson/Vibe-Trading) | "Vibe-Trading: Your Personal Trading Agent" | Python=6524320, TypeScript=521326, HTML=75191, JavaScript=34890 | executable code, trading strategies, data pipelines, agent/tooling, docs/content, dashboard/ui |
| [`mattamundson/tradingview-mcp`](https://github.com/mattamundson/tradingview-mcp) | AI-assisted TradingView chart analysis — connect Claude Code to your TradingView Desktop for personal workflow automation | JavaScript=390923, Shell=4059, Batchfile=2773, VBScript=302 | executable code, trading strategies, agent/tooling, docs/content, dashboard/ui |
| [`mattamundson/sunday-quant-scientist`](https://github.com/mattamundson/sunday-quant-scientist) | A Free Newsletter for Quantitative and Algorithmic Trading, Portfolio Analysis, and Investing | HTML=3974681, Python=124244, Shell=724 | executable code, trading strategies, data pipelines, agent/tooling, docs/content |
| [`mattamundson/fredapi`](https://github.com/mattamundson/fredapi) | Python API for FRED (Federal Reserve Economic Data) and ALFRED (Archival FRED) | Python=33539 | executable code, trading strategies, agent/tooling, docs/content |
| [`mattamundson/lightweight-charts`](https://github.com/mattamundson/lightweight-charts) | Performant financial charts built with HTML5 canvas | TypeScript=1619193, JavaScript=1025605, HTML=363479, MDX=290164 | executable code, trading strategies, agent/tooling, docs/content |
| [`mattamundson/LLM-Trading-Lab`](https://github.com/mattamundson/LLM-Trading-Lab) | This repo powers my experiment where ChatGPT manages a real-money micro-cap stock portfolio. | Python=160364, Makefile=965 | executable code, data pipelines, agent/tooling, docs/content |
| [`mattamundson/atlas-gic`](https://github.com/mattamundson/atlas-gic) | ATLAS by General Intelligence Capital — Self-improving AI trading agents using Karpathy-style autoresearch | Python=120381 | executable code, trading strategies, data pipelines, agent/tooling, docs/content, dashboard/ui |
| [`mattamundson/Polymarket-Trading-Bot`](https://github.com/mattamundson/Polymarket-Trading-Bot) | 🤖 The most advanced open-source Polymarket trading bot. 7 automated strategies (arbitrage, convergence, market making, momentum, AI forecast), whale tracker with copy-trade simulator, real-time dashboard, parallel market scanner, paper trading mode. 53K+ lines of TypeScript. Contact @DylanForexia on Telegram for custom bots. | TypeScript=1266127, JavaScript=5479, Just=1098, Dockerfile=873 | executable code, trading strategies, data pipelines, agent/tooling, docs/content, dashboard/ui |
| [`mattamundson/prediction-market-backtesting`](https://github.com/mattamundson/prediction-market-backtesting) | A fork of Nautilus Trader with custom Polymarket and Kalshi adapters for backtesting | Rust=28376649, Python=15133443, Cython=3737062, Shell=137098 | executable code, trading strategies, data pipelines, agent/tooling, docs/content, dashboard/ui |
| [`mattamundson/polybot`](https://github.com/mattamundson/polybot) | reverse-engineer every polymarket strategy and trade fast | Java=618797, Python=226303, Shell=7670 | executable code, trading strategies, agent/tooling, docs/content, dashboard/ui |

## Highest-value patterns to import into JARVIS

### 1. Research workflow discipline from `claude-trading-skills`

Use as process fuel, not source code. The high-value asset is a repeatable human+agent workflow: market review, technical charting, economic calendar checks, trade planning, journaling, and continuous improvement.

**JARVIS adaptation:** encode these as checked commands/runbooks:

- market brief
- pretrade check
- strategy review
- backtest critique
- trade journal entry
- post-trade/postmortem review

### 2. Quant library map from `awesome-quant`

Use as a curated discovery index. Candidate categories that map directly into JARVIS:

- backtesting engines and validation frameworks
- portfolio/risk analysis
- time-series/statistical tests
- factor analysis
- technical indicators
- alternative data and sentiment
- market data connectors

**JARVIS adaptation:** maintain a short allowlist of libraries with exact purpose and install status; do not add dependencies just because they appear in the awesome list.

### 3. Multi-agent financial analysis from `TradingAgents` / `Vibe-Trading`

Useful pattern: split market analysis into role-specific agents, but make them evidence producers rather than final decision makers.

**JARVIS adaptation:** analysts can produce structured evidence for the existing decision pipeline; promotion and safety gates stay deterministic.

### 4. Chart workflow from `tradingview-mcp` and `lightweight-charts`

Useful split:

- TradingView MCP: external chart capture, Pine development, replay practice, discretionary annotation.
- Lightweight Charts: native dashboard rendering, review panels, trade markers, signal overlays.

**JARVIS adaptation:** chart artifacts should write to the journal/evidence path, not directly influence execution.

### 5. Macro/regime context from `fredapi` and `sunday-quant-scientist`

FRED/macro context is valuable as a regime filter, briefing input, and explanatory feature.

**JARVIS adaptation:** macro series must have freshness, release-lag, revision, and timezone semantics. Macro context should not bypass backtest/paper promotion gates.

### 6. Prediction-market architecture from Polymarket/Kalshi repos

Useful patterns:

- scanner architecture
- order-book imbalance and probability normalization
- paper simulator separation
- market-making/arbitrage risk controls
- whale/copy-trade analogs as sentiment features

**JARVIS adaptation:** mine architecture and tests only. Venue-specific crypto/prediction-market execution should not enter futures execution.

## Next implementation candidates

1. `docs/research/backtest-critique-checklist.md` — standard review checklist for any strategy result.
2. `docs/research/chart-review-runbook.md` — TradingView/Lightweight Charts evidence workflow.
3. `docs/research/macro-regime-context-spec.md` — FRED/macro context data contract.
4. Strategy registry schema/document update tying source repo, hypothesis, evidence paths, and promotion status together.
