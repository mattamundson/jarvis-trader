# Jarvis-Trader Pipeline Adapter for Paperclip

Wraps the jarvis-trader FastAPI engine (localhost:8010) as a Paperclip agent adapter.
Each pipeline run becomes a Paperclip heartbeat. Token budgets enforced per agent.

## Architecture

server/execute.ts   -> spawns pipeline run via HTTP POST to localhost:8010
ui/build-config.ts  -> config form (symbol, timeframe, risk params)
cli/format-event.ts -> terminal output formatter

## Usage

1. Install Paperclip locally: pnpm paperclipai run
2. Register adapter: pnpm paperclipai adapter register ./adapter
3. Create agent using this adapter in Paperclip UI
4. Each agent run calls POST /api/pipeline/run on the trading engine
