---
description: Read a jarvis instrument's TradingView chart via the tradingview MCP server — health check, set symbol/timeframe, pull OHLCV + on-chart studies + screenshot, and summarize structure. Read-only; never creates alerts or trades.
argument-hint: "<symbol> [timeframe]  e.g. MES 15m  |  MGC 1h  (default TF: 15m -> normalized to 15)"
allowed-tools: mcp__tradingview__tv_health_check, mcp__tradingview__tv_discover, mcp__tradingview__chart_set_symbol, mcp__tradingview__chart_set_timeframe, mcp__tradingview__chart_get_state, mcp__tradingview__data_get_ohlcv, mcp__tradingview__data_get_study_values, mcp__tradingview__data_get_pine_lines, mcp__tradingview__data_get_pine_labels, mcp__tradingview__capture_screenshot, Bash(bash scripts/tv-engine-crosscheck.sh:*)
---

<!-- allowed-tools is an explicit read-only allowlist: chart navigation + data reads, plus a
     single fixed engine entry point (scripts/tv-engine-crosscheck.sh) that GETs ONLY
     /prices/snapshot and /hidden-pivots/levels. Raw curl is deliberately NOT allowed here:
     a bare `curl`/`-X GET` grant would expose side-effecting GETs like /hidden-pivots/scan
     (fires WhatsApp via _notify_hp_signal, hidden_pivots_router.py:194,232) or POST routes,
     and inlining the key-load + curls in the command made the allowlist fragile (unmatchable
     `API_KEY=` line, YAML-breaking colons). The script hardcodes the two read-only URLs, so
     this command cannot mutate engine state or send alerts. The MCP account/session mutators
     (alert_create, alert_delete, pine_save, pine_set_source, draw_*, ui_*, batch_run,
     replay_trade) are omitted so a prompt/tool-output detour cannot reach them. Do not add raw
     curl or MCP mutators here — the read-only/no-alert contract depends on this allowlist. -->


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
| MGC    | `COMEX_MINI:MGC1!` | HALTED — read-only     |
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

The engine cross-check helper accepts `1m`/`5m`/`15m`/`1h`/`4h`/`1d` — each has a real
`get_bars` bar mapping (`market_data.py` IBKR `bar_size_map` and Polygon `tf_map`, both
including `1m`). Pass the matching engine alias, `1m` included. Inputs *outside* that set are
charted at their TV resolution but **substituted to the nearest supported alias for the
cross-check, flagged**: `30m`/`30`→`15m` or `1h`, `1w`/`W`→`1d`. (Note: the levels route's
`lookback_map` has no `1m` entry, so a `1m` cross-check defaults to a 200-day lookback — it
returns a real 1m ladder but is heavier; fine for a spot check.) If an input maps to neither
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

Run the fixed read-only helper — it is the **only** engine access this command allows. It loads
the key (exported `$JARVIS_API_KEY`, else `API_KEY` from `engine/.env`), exits 3 if no key is
found (skip the cross-check; do not report drift), and GETs exactly the two read-only routes.
Pass the **engine alias** for the timeframe (`15m`, not the TV `15` — right-hand column of the
table above):

```bash
bash scripts/tv-engine-crosscheck.sh <symbol> <eng_tf>   # e.g. MES 15m  |  MGC 1h
```

These routes are not in the middleware `EXEMPT_PATHS` (only health/docs/metrics are), so the
key is required or they 401. The helper hardcodes the two URLs, so no other engine route —
including side-effecting GETs like `/hidden-pivots/scan` (fires WhatsApp) — is reachable from
this command.

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
