# Jarvis Trader Dev — AgentCompany Package

AgentCompanies/v1 package for the Jarvis autonomous trading system.

## Quick import

```bash
pnpm paperclipai import ./jarvis-trader-dev.agentcompany
```

## What this package encodes

- 10 specialized LLM pipeline agents (TechnicalAnalyst → Trader)
- P0/P1 task backlog aligned to paper trading validation goal
- Per-agent Anthropic token budgets (prevents runaway costs)
- Tier 3 governance for live trading enablement
- Atomic task checkout pattern for parallel Claude Code dev sessions

## Current goal

Paper trading validation:
- 30-day minimum run
- Sharpe ratio > 1.0
- Max drawdown < 15%
- Win rate > 52%

## After validation

Run `pnpm paperclipai approve P1-002` to enable live trading (requires Tier 3 approval).

## Adapter

Uses `jarvis-trading-pipeline` adapter — see `../adapter/` for implementation.
