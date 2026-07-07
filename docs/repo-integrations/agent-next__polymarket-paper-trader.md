---
repo: agent-next/polymarket-paper-trader
url: https://github.com/agent-next/polymarket-paper-trader
stars: 249
language: Python
license: MIT
archived: false
pushed_at: 2026-03-02T05:24:25Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [engine-code, ops-messaging]
---

# agent-next/polymarket-paper-trader

## Core value proposition

Polymarket paper-trading simulator with MCP server support, real order-book execution model (level-by-level fills, slippage tracking, exact fee calculation), GTC/GTD limit-order state machine, multi-account A/B testing, and leaderboard APIs. Targets AI agents and binary prediction markets, not equities or futures. MIT license.

## Surface analysis

### 1. Engine code

**partial-integrate** — Order book execution model (level-by-level fills, slippage tracking) and limit-order state machine (GTC/GTD lifecycle) are novel patterns not present in jarvis-trader. However, jarvis-trader is futures-focused (MES, MCL, MNQ via IB Gateway) and polymarket-paper-trader is binary prediction markets (YES/NO binary outcomes). The architectures are fundamentally incompatible: polymarket uses real Polymarket order books (external data source), while jarvis-trader uses IB live feeds or backtested historical OHLC. Code reuse would require refactoring both the asset class (binary vs. continuous price) and the data pipeline. Limited surface fit.

**Existing in jarvis-trader**: `engine/execution/paper_trade_logger.py` (JSON audit), `engine/backtest/paper_tracker.py` (SQLite-backed tracking), `engine/database/_mixins_trades.py` (trade CRUD). Polymarket's fill algorithm (walk price levels) vs. jarvis-trader's market-fill assumptions (single midpoint) are orthogonal concerns. Would require a 4–6hr refactor to adapt.

### 2. Project rules

**no-fit** — Polymarket's paper-trading rules (binary prediction markets, GTC/GTD lifecycle, fee = `bps/10000 * min(price, 1-price) * shares`) do not generalize to futures or equities. Jarvis-trader's rules (market hours gates, kill thresholds, WFE validation) are specific to CME Globex and walk-forward testing.

### 3. Project skills

**no-fit** — Polymarket has no existing skill in jarvis-trader. A skill would be "polymarket-trader" to wrap the MCP server, but would only be useful if jarvis-trader actively traded Polymarket (out of scope per PRIMARY FOCUS DIRECTIVE: "futures, not binary prediction").

### 4. Slash commands

**no-fit** — Polymarket's CLI commands (`pm-trader buy/sell`, `pm-trader stats`, `pm-trader leaderboard`) are specific to binary prediction markets and do not map to jarvis-trader's `/pretrade-check`, `/regime`, `/engine-health` vocabulary.

### 5. Subagents

**no-fit** — Polymarket does not include agents for trading decision-making. It is a simulation harness, not an LLM-driven decision engine.

### 6. Docs

**dedup-docs** — `docs/strategy/`, `docs/runbooks/` already cover paper-trading setup, backtest harness, and kill thresholds. Polymarket's runbooks (market search, limit-order lifecycle) would duplicate existing docs without adding strategy clarity.

### 7. Dev tooling

**no-fit** — Polymarket uses `pytest`, `uv pip`, `npx clawhub`. Jarvis-trader uses `pnpm`, `.claude/hooks/`, PM2 ecosystem.config.js, and pre-commit. Different tech stacks; no transfer value.

### 8. Dashboard

**no-fit** — Polymarket does not include a dashboard. Jarvis-trader dashboard (`dashboard/components/`, `dashboard/lib/`) is built for MES/MCL/MNQ portfolio visualization and does not apply to binary prediction markets.

### 9. Ops / messaging

**partial-integrate** — Polymarket includes leaderboard generation (`leaderboard_card`, `leaderboard_entry`, `pk_battle` MCP tools) and shareable stats cards (`stats_card` tool). These could inspire ops messaging patterns for jarvis-trader's morning brief, but the implementation is Polymarket-specific (binary outcome resolution, prediction-market scoring). Jarvis-trader's message routes (WhatsApp via OpenClaw, Discord notifier) are already wired; polymarket's "share_content" tool (twitter/telegram/discord) would require integration with real Polymarket leaderboard APIs, which are out of scope.

## Integration plan

No direct integrations recommended. The order-book execution model (Surface 1) is the only novel technical pattern, but it requires:

1. Refactoring `engine/execution/order_router.py` to support multi-level fill logic (currently assumes single market-fill price).
2. Replacing IB Gateway feeds with external Polymarket API calls (data source change — architectural decision required).
3. Adapting paper-trade schema (polymarket uses binary YES/NO outcomes vs. jarvis-trader's continuous prices).

This is a **4–6 hour refactor** with low ROI given the PRIMARY FOCUS DIRECTIVE (futures only). Recommend deferring unless binary prediction markets become an explicit trading target.

**Alternative**: Extract the fill-level-by-level pattern as a generic `engine/execution/multi_level_fill.py` utility and document it in `docs/architecture/order-execution.md` for future reference (no code change required). This would preserve the intellectual pattern without Polymarket dependency.

## License & attribution

MIT. If any code is adapted in the future, credit the repo in file header: `# Adapted from agent-next/polymarket-paper-trader (MIT license)`.

## Effort estimate

- **No integration**: S (0 hr, archive this proposal)
- **Extract fill pattern as generic utility**: M (2–3 hr, docs only, no engine changes)
- **Full Polymarket integration**: XL (6+ hr, requires data pipeline refactor, out of scope)

## Red flags

1. **Binary prediction markets vs. futures**: Polymarket and jarvis-trader solve different problems. Polymarket prices are discrete (YES @ 0.55, NO @ 0.45). Futures have continuous price ticks. Integration would require dual asset-class support across the entire stack.
2. **Fundamental focus mismatch**: PRIMARY FOCUS DIRECTIVE says "futures, not binary prediction". Polymarket is binary prediction. This is a category error, not a bug.
3. **Architectural incompatibility**: IB Gateway (jarvis-trader's data source) has no Polymarket integration. Would require new data fetcher, new order router, new portfolio accounting.
4. **Low adoption likelihood**: If futures remain the only focus, polymarket-paper-trader code will bit-rot immediately after integration.
