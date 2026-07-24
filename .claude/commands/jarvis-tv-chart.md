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

### Resolve the timeframe into TWO forms before making any call

The chart tool and the engine want **different** timeframe encodings, so keep both — do not
pass one where the other belongs:

- `mcp__tradingview__chart_set_timeframe` wants a **TradingView resolution** (`1`/`5`/`15`/
  `60`/`240`/`D`/`W`) — an unrecognized value can leave the chart on its prior resolution.
- the engine cross-check (`get_bars` via `/hidden-pivots/levels`, `/prices/snapshot`) wants an
  **engine alias** (`5m`/`15m`/`1h`/`4h`/`1d`) — a bare `15`/`60`/`D` is unknown to its
  IB/Polygon maps and silently falls back to 5m bars (the wrong ladder).

Map the input (a human alias *or* a bare TV resolution) to both columns:

| input        | TV resolution (chart) | engine alias (cross-check) |
|--------------|-----------------------|----------------------------|
| `1m` / `1`   | `1`                   | `1m`                       |
| `5m` / `5`   | `5`                   | `5m`                       |
| `15m` / `15` | `15`                  | `15m`                      |
| `1h` / `60`  | `60`                  | `1h`                       |
| `4h` / `240` | `240`                 | `4h`                       |
| `1d` / `D`   | `D`                   | `1d`                       |
| `1w` / `W`   | `W`                   | `1d` (no intraday; flag)   |

`30m`/`30` (TV `30`) has no engine bar mapping — chart it, but for the cross-check use the
nearest engine alias (`15m` or `1h`) and flag the substitution. If an input maps to neither
column cleanly, report it and stop rather than guessing.

## Steps

1. `mcp__tradingview__tv_health_check`. If `cdp_connected` is not true (or the tool is
   unreachable, e.g. a cloud session), **STOP** and report: TradingView Desktop / CDP is not
   up — point to `docs/tv-mcp-startup.md` (exit-code 2 = TV running without CDP). Do not
   invent chart values.
2. `mcp__tradingview__chart_set_symbol` → resolved ticker, then
   `mcp__tradingview__chart_set_timeframe` → the **TV resolution** (chart column of the table
   above). After the call, confirm the chart actually switched (`chart_get_state`) before
   trusting the read.
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

Use the **engine alias** (`<eng_tf>` — the right-hand column of the timeframe table, e.g. `15m`,
not the TV `15`) for these calls:

```bash
# Prefer an exported JARVIS_API_KEY; otherwise read API_KEY from engine/.env
# (AGENTS.md: the local dev key lives there as API_KEY=...).
API_KEY="${JARVIS_API_KEY:-$(grep -E '^API_KEY=' engine/.env | cut -d= -f2- | tr -d '\"'\''')}"
[ -z "$API_KEY" ] && echo "no engine API key found — skip cross-check, do not report drift" && exit 0
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/prices/snapshot?symbols=<symbol>"
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/hidden-pivots/levels/<symbol>?timeframe=<eng_tf>"
```

- **Price:** `/prices/snapshot?symbols=<jarvis symbol>` — the endpoint defaults to
  `SPY,QQQ,MES,MNQ,MCL` (MGC is *not* in the default set), so always pass `?symbols=MGC`
  (or MES, etc.) explicitly or the snapshot won't include what you charted.
- **Levels:** `/hidden-pivots/levels/<symbol>?timeframe=<eng_tf>` — pass the **engine alias for
  the same timeframe you charted** (`15m`, not the TV `15`). The endpoint forwards `timeframe`
  straight to `MarketDataManager.get_bars`, which maps `5m`/`15m`/`1h`/`4h`/`1d` directly, so
  `?timeframe=15m` returns a 15m ladder — don't downshift it, and don't send a bare TV
  resolution (`15`/`60`/`D`), which its maps don't recognize and silently degrade to 5m bars.
  (The route's `lookback_map` only sets lookback *days* — an unlisted key just falls back to a
  200-day lookback, it does not change the bar size.) Only if the call errors or returns empty
  for that timeframe, retry with the nearest supported alias and note the substitution. Never
  compare a daily ladder against an intraday chart.

Compare last price / levels against what TradingView shows and report any drift explicitly —
a mismatch between the TV feed and the engine feed is a bug to flag, not a rounding footnote.
Never present a TV number as canonical without this check when both sources are available.

## Hard constraints

- Read-only. Do NOT call `alert_create`, `alert_delete`, `draw_*`, `replay_trade`,
  `ui_click`, `ui_evaluate`, or `batch_run` from this command.
- This is not an execution path. Orders route only through engine → IB Gateway paper (4002)
  with human approval — never from a chart read.
