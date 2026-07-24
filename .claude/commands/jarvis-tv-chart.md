---
description: Read a jarvis instrument's TradingView chart via the tradingview MCP server — health check, set symbol/timeframe, pull OHLCV + on-chart studies + screenshot, and summarize structure. Read-only; never creates alerts or trades.
argument-hint: "<symbol> [timeframe]  e.g. MES 15m  |  MGC 1h  (default TF: 15m)"
---

# TV Chart Read — $ARGUMENTS

Quick, read-only TradingView Desktop chart read for a jarvis instrument. Wraps the
`tradingview` MCP server (see the `tradingview-mcp` skill for the full tool map and the hard
safety boundaries). This command never mutates the TV account — no alerts, no drawings, no
replay trades, no orders.

## Resolve the symbol

Map the jarvis symbol in `$ARGUMENTS` to the TradingView ticker:

| jarvis | TradingView        | status                 |
|--------|--------------------|------------------------|
| MES    | `CME_MINI:MES1!`   | active paper           |
| MGC    | `COMEX_MINI:MGC1!` | active paper           |
| MNQ    | `CME_MINI:MNQ1!`   | HALTED — read-only     |
| MCL    | `NYMEX:MCL1!`      | HALTED — read-only     |

Default timeframe if none given: `15m`.

## Steps

1. `mcp__tradingview__tv_health_check`. If `cdp_connected` is not true (or the tool is
   unreachable, e.g. a cloud session), **STOP** and report: TradingView Desktop / CDP is not
   up — point to `docs/tv-mcp-startup.md` (exit-code 2 = TV running without CDP). Do not
   invent chart values.
2. `mcp__tradingview__chart_set_symbol` → resolved ticker, then
   `mcp__tradingview__chart_set_timeframe` → requested TF.
3. `mcp__tradingview__data_get_ohlcv` for recent candles. If an indicator is already on the
   chart, `mcp__tradingview__data_get_study_values` for its latest values. Optionally
   `mcp__tradingview__data_get_pine_lines` / `_labels` for any Pine-drawn levels.
4. `mcp__tradingview__capture_screenshot` for a visual.
5. Summarize: last price, session range/structure, key levels visible, and any indicator
   read. Keep it factual — this feeds Matt's judgment, it does not gate any safety decision.

## Cross-check (numeric discipline)

If the engine is reachable, pull `/prices/snapshot` (or `/levels/{symbol}`) and compare the
last price / levels against what TradingView shows. Report any drift explicitly — a
mismatch between the TV feed and the engine feed is a bug to flag, not a rounding footnote.
Never present a TV number as canonical without this check when both sources are available.

## Hard constraints

- Read-only. Do NOT call `alert_create`, `alert_delete`, `draw_*`, `replay_trade`,
  `ui_click`, `ui_evaluate`, or `batch_run` from this command.
- This is not an execution path. Orders route only through engine → IB Gateway paper (4002)
  with human approval — never from a chart read.
