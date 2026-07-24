---
description: Read a jarvis instrument's TradingView chart via the tradingview MCP server — health check, set symbol/timeframe, pull OHLCV + on-chart studies + screenshot, and summarize structure. Read-only; never creates alerts or trades.
argument-hint: "<symbol> [timeframe]  e.g. MES 15m  |  MGC 1h  (default TF: 15m -> normalized to 15)"
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

### Normalize the timeframe before calling the tool

`mcp__tradingview__chart_set_timeframe` expects a **TradingView resolution string**
(`1`, `5`, `15`, `60`, `240`, `D`, `W`, `M`), not a `15m`/`1h` alias — passing an alias can
leave the chart on its previous resolution while OHLCV/screenshot are still summarized (a
silently-wrong read). Map the human alias to a resolution first:

| alias | resolution | | alias | resolution |
|-------|-----------|-|-------|-----------|
| `1m`  | `1`       | | `1h`  | `60`      |
| `5m`  | `5`       | | `4h`  | `240`     |
| `15m` | `15`      | | `1d` / `D` | `D`  |
| `30m` | `30`      | | `1w` / `W` | `W`  |

If already a bare resolution (`15`, `60`, `D`), pass it through unchanged. If the alias
doesn't map cleanly, report it and stop rather than guessing.

## Steps

1. `mcp__tradingview__tv_health_check`. If `cdp_connected` is not true (or the tool is
   unreachable, e.g. a cloud session), **STOP** and report: TradingView Desktop / CDP is not
   up — point to `docs/tv-mcp-startup.md` (exit-code 2 = TV running without CDP). Do not
   invent chart values.
2. `mcp__tradingview__chart_set_symbol` → resolved ticker, then
   `mcp__tradingview__chart_set_timeframe` → the **normalized** resolution (see table above).
   After the call, confirm the chart actually switched (`chart_get_state`) before trusting
   the read.
3. `mcp__tradingview__data_get_ohlcv` for recent candles. If an indicator is already on the
   chart, `mcp__tradingview__data_get_study_values` for its latest values. Optionally
   `mcp__tradingview__data_get_pine_lines` / `_labels` for any Pine-drawn levels.
4. `mcp__tradingview__capture_screenshot` for a visual.
5. Summarize: last price, session range/structure, key levels visible, and any indicator
   read. Keep it factual — this feeds Matt's judgment, it does not gate any safety decision.

## Cross-check (numeric discipline)

If the engine is reachable, cross-check the chart you just read — but **query the same symbol
and timeframe**, otherwise the check silently validates the wrong thing.

**Auth:** these engine routes are not in the middleware `EXEMPT_PATHS` (only health/docs/
metrics are), so a bare call returns 401. Send the key on every request, read at use time
(it rotates — do not hardcode), exactly as the other jarvis commands do:

```bash
API_KEY="${JARVIS_API_KEY}"
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/prices/snapshot?symbols=<symbol>"
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/hidden-pivots/levels/<symbol>?timeframe=<tf>"
```

- **Price:** `/prices/snapshot?symbols=<jarvis symbol>` — the endpoint defaults to
  `SPY,QQQ,MES,MNQ,MCL` (MGC is *not* in the default set), so always pass `?symbols=MGC`
  (or MES, etc.) explicitly or the snapshot won't include what you charted.
- **Levels:** `/hidden-pivots/levels/<symbol>?timeframe=<tf>` — this endpoint defaults to
  `timeframe=1d` and only supports `1d` / `1h` / `5m` (its `lookback_map`). Pass the value
  closest to the chart TF you read (`≤15m`→`5m`, `30m–1h`→`1h`, `≥1d`→`1d`); do not compare
  a daily level ladder against an intraday chart. If the chart TF has no exact levels match
  (e.g. 15m), say so — compare against the nearest supported and note the granularity gap.

Compare last price / levels against what TradingView shows and report any drift explicitly —
a mismatch between the TV feed and the engine feed is a bug to flag, not a rounding footnote.
Never present a TV number as canonical without this check when both sources are available.

## Hard constraints

- Read-only. Do NOT call `alert_create`, `alert_delete`, `draw_*`, `replay_trade`,
  `ui_click`, `ui_evaluate`, or `batch_run` from this command.
- This is not an execution path. Orders route only through engine → IB Gateway paper (4002)
  with human approval — never from a chart read.
