# TradingView MCP Setup

## What It Does

Connects TradingView Desktop to Claude Code via 78 MCP tools — chart data, symbol info, indicators, drawing tools, Pine Script analysis, and more.

## Installed Location

```
jarvis-trader/tradingview-mcp/
```

Registered in `jarvis-trader/.mcp.json`.

## Step 1: Launch TradingView Desktop with Debug Port

**Windows** (use the `tv_launch` MCP tool after connection, or manually):
```
%LOCALAPPDATA%\TradingView\TradingView.exe --remote-debugging-port=9222
```

Or use the MCP tool `tv_launch` — it auto-detects TradingView on all platforms.

## Step 2: Restart Claude Code

After updating `.mcp.json`, restart Claude Code to load the MCP server.
The server auto-connects to TradingView Desktop on port 9222.

## Available Tools (78 total)

Key categories:
- **Chart control** — navigate symbols, change timeframes, set overlays
- **Data extraction** — OHLCV bars, indicator values, drawing objects
- **Pine Script** — analyze, run, and debug Pine scripts
- **Symbol info** — fundamentals, statistics, financial data
- **Alerts** — create and manage price alerts

## Verify Connection

Once Claude Code restarts, you can ask:
- "What's the current symbol on TradingView?"
- "Get me the last 50 bars of MES on TradingView"

## Troubleshooting

- TradingView Desktop must be the **Desktop app**, not the web browser version
- Port 9222 must be free (check: `netstat -an | grep 9222`)
- If connection fails, use `tv_launch` tool to auto-start TradingView with the debug port
