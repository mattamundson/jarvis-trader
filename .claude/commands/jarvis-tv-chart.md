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
| MGC    | `COMEX_MINI:MGC1!` | active paper (re-auth 2026-08-04) |
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
| `30m` / `30` | `30`                  | `none` (price-only; levels skipped) |
| `1h` / `60`  | `60`                  | `1h`                       |
| `4h` / `240` | `240`                 | `4h`                       |
| `1d` / `D`   | `D`                   | `1d`                       |
| `1w` / `W`   | `W`                   | `none` (price-only; levels skipped) |

The engine cross-check helper accepts `1m`/`5m`/`15m`/`1h`/`4h`/`1d` — each has a real
`get_bars` bar mapping (`market_data.py` IBKR `bar_size_map` and Polygon `tf_map`, both
including `1m`). When the charted TF has an **exact** engine alias (the six above), pass it and
cross-check both price and levels. When it does **not** (`30m`/`30`, `1w`/`W`): call the helper in
**price-only mode** — `bash scripts/tv-engine-crosscheck.sh <symbol> none` — which checks the
timeframe-independent price snapshot and **skips levels**. The HP ladder is timeframe-dependent,
so comparing a 30m/weekly chart against a substituted `15m`/`1h`/`1d` ladder would manufacture
false drift; `none` avoids that. If an input maps to neither column cleanly, report it and stop
rather than guessing.

**Levels lookback caveat:** the levels route's `lookback_map` only bounds `1d`/`1h`/`5m`; any
other alias (`1m`/`15m`/`4h`) falls back to a **200-day** lookback, which at small bar sizes is
an oversized IBKR request that can come back empty (and futures don't fall back to Polygon) →
a 404. That is handled safely, not silently: the helper uses `curl -f`, so an empty/404 levels
response makes it **exit 4** ("unreachable, not drift"), not fabricate a ladder. When levels are
unavailable for the charted TF, fall back to the **price-snapshot** drift check alone and say
levels were unavailable — never report a levels comparison you didn't get. (A future engine
change could add bounded `1m`/`15m`/`4h` entries to that `lookback_map`; out of scope here.)

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
  200-day lookback, it does not change the bar size.) If the call errors or returns empty for
  that timeframe, **report levels unavailable and keep the successful price check** — do NOT
  retry a different alias (a substituted ladder is timeframe-mismatched and would manufacture
  false drift, same reason the 30m/1w path is price-only). Never compare a daily ladder against
  an intraday chart.

**Provenance is required — a cross-check is only independent if the engine value came from a
different feed than TradingView**, because the engine waterfalls to TV itself when the broker
feeds are down.

- **Price (`/prices/snapshot`)** returns a `source` field and has a "Tier 2.5 TradingView"
  fallback. Check it: only `ibkr` / `schwab` / `polygon` / `db` is an **independent** validation.
  `source: tradingview` means the engine agreed with TV because it *is* TV → report the price as
  **unverified (same-source)**, not confirmed.
  ⚠️ **`source: ibkr` may be DELAYED, not real-time.** The IB paper account lacks a futures
  real-time subscription, so the connector defaults to `reqMarketDataType(3)` = delayed
  (~15 min), and `as_of` is the *fetch* time, not the *quote* time (`market_data.py`,
  `prices_router.py`). So a `source: ibkr` value can be quarter-hour-stale yet look fresh. Trust
  the response's live/static/stale badge (or `IB_MARKET_DATA_TYPE`): only a **LIVE** (type-1) IB
  quote is a fresh independent feed; a delayed/frozen one (type 3/4) is **unverified** — do not
  flag its gap vs TV as drift, and don't present it as confirmation.
- **Levels (`/hidden-pivots/levels`)** returns only symbol/timeframe/ladder/swing — **no `source`
  field** — and its bars waterfall `TradingView → IBKR → Polygon → CSV` *independently* of the
  snapshot. You therefore **cannot** establish the ladder's provenance from the response, and must
  not borrow the snapshot's `source` for it. Treat every levels-ladder comparison as
  **provenance-unverified**: report drift if you see it, but never call the ladder engine-confirmed.
  (Exposing bar `source` on that endpoint is an out-of-scope engine change.)
- **Continuous vs dated contract.** TradingView `MES1!`/`MGC1!` is a *continuous* (stitched,
  back-adjusted) contract, but the engine resolves the bare symbol to a *dated front month*
  (`MarketDataManager._resolve_front_month`). Near a futures rollover the roll/back-adjustment
  basis can legitimately exceed the tick/staleness tolerance — that's a contract-basis
  difference, **not feed drift**. Either chart the same dated contract the engine resolved, or
  label a continuous-vs-dated gap as basis (unverified), never a bug.

**Account for staleness and tolerance before calling a mismatch drift.** `/prices/snapshot` is
cached with a **60-second TTL** (`price_cache.py`), so an engine price can be up to ~60s behind a
just-captured TV read — in a moving market that difference is ordinary movement, not a feed bug.
Before flagging, **always apply a contract-aware tick tolerance** (a few ticks for MES/MGC) —
even a fresh feed differs by a tick or two from ordinary quote timing / adjacent trades.
Freshness only sets the *additional* movement allowance on top of that tolerance: use the
response's `as_of`/freshness if present (else assume up to 60s old), and add the amount price
could plausibly move over that age. A mismatch is real drift **only if it exceeds tick tolerance
+ staleness allowance** (staleness allowance is ~zero for a fresh feed); anything within that is
ordinary quote timing, not a bug. Never present a TV number as canonical without an
independent-source check.

## Hard constraints

- Read-only. Do NOT call `alert_create`, `alert_delete`, `draw_*`, `replay_trade`,
  `ui_click`, `ui_evaluate`, or `batch_run` from this command.
- This is not an execution path. Orders route only through engine → IB Gateway paper (4002)
  with human approval — never from a chart read.
