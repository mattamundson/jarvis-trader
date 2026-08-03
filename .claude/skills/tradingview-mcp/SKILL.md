---
name: tradingview-mcp
description: Drive the TradingView Desktop MCP server (tradesdontlie/tradingview-mcp, 78 tools over Chrome DevTools Protocol on port 9222) for jarvis-trader chart analysis, level extraction, screenshots, and Pine Script development on MES/MGC. Use when the user says "read the chart", "what's on the ES chart", "screenshot the MGC chart", "pull OHLCV from TradingView", "extract levels from TV", "check the STC Pine script", "set the chart to <symbol>/<timeframe>", "tv health check", or before a market-framing brief when live TradingView structure is wanted. Read/analysis and Pine-dev only — this server is NOT a trade-execution path.
---

# tradingview-mcp

Wraps the `tradingview` MCP server already registered in `.mcp.json` (source:
[tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp), MIT).
The server bridges to a **locally running TradingView Desktop** on Matt's Windows box via
Chrome DevTools Protocol (port 9222). It exposes 78 `mcp__tradingview__*` tools.

## Environment reality check (read first)

- The MCP server runs on **Matt's local Windows machine**, not the cloud engine and not this
  container. It needs TradingView Desktop launched with `--remote-debugging-port=9222`
  (persistence is handled by `scripts/launch-tv-with-cdp.ps1` + the `JARVIS-TV-CDP-AtLogon`
  scheduled task — see `docs/tv-mcp-startup.md`).
- If you are in a cloud/CI session, these tools are **not reachable**. Say so plainly and
  route the user to run the check locally — do not fabricate chart values.
- **Always start with `mcp__tradingview__tv_health_check`.** If it fails, stop and point at
  `docs/tv-mcp-startup.md` (exit-code 2 = TV running without CDP; kill and re-run the task).

## Hard boundaries (non-negotiable)

- **This is NOT an execution path.** The only order route in jarvis-trader is
  engine → IB Gateway **paper** (port 4002, DUP662235) with `REQUIRE_HUMAN_APPROVAL = True`.
  This MCP cannot and must not be used to place broker trades. `replay_trade` is
  **practice/replay only** — it touches nothing real.
- **`alert_create` writes a REAL alert into Matt's TradingView account.** Never create,
  edit, or delete alerts without an explicit, in-the-moment instruction naming symbol, price,
  and condition. Default to read-only. The existing signal path is the webhook flow in
  `scripts/tradingview/TRADINGVIEW_SETUP.md`, not ad-hoc alerts.
- **No LLM-driven safety or trade decisions.** Chart reads inform Matt; they never gate the
  kill switch, position sizing, or approval. Those stay in hardcoded `engine/risk/`.
- **Do not auto-execute on any crypto exchange.** (See "Rejected integration" below.)
- The only active paper instrument is **MES**. **MGC, MNQ, and MCL are HALTED**
  (`DO_NOT_TRADE_SYMBOLS`, `engine/backtest/signals.py`) — MGC was halted 2026-07-31 when the
  DSR correction collapsed its earlier Tier-3 PASS (`engine/CLAUDE.md`). You may *read* their
  charts for context, never wire any of them to a signal or alert.

## TradingView ↔ jarvis symbol map

| jarvis | TradingView symbol   |
|--------|----------------------|
| MES    | `CME_MINI:MES1!`     |
| MGC    | `COMEX_MINI:MGC1!` (read-only — HALTED) |
| MNQ    | `CME_MINI:MNQ1!` (read-only — HALTED) |
| MCL    | `NYMEX:MCL1!` (read-only — HALTED)    |

## Tool cheat-sheet (by workflow)

**Read / analyze (primary, always safe):**
- `tv_health_check`, `tv_discover` — connection + what's open
- `chart_get_state`, `quote_get`, `symbol_info`, `symbol_search`
- `data_get_ohlcv` — raw candles (compute your own indicators/levels from these)
- `data_get_study_values` — values off an indicator already on the chart
- `data_get_pine_lines` / `_labels` / `_tables` / `_boxes` — read Pine-drawn levels
- `capture_screenshot` — visual for a brief or a bug report

**Chart control (transient view only, safe):**
- `chart_set_symbol`, `chart_set_timeframe`, `chart_set_type`, `chart_scroll_to_date`,
  `chart_set_visible_range`
- Read-only workspace queries: `pane_list`, `pane_focus`, `tab_list`, `tab_switch`,
  `watchlist_get`, `layout_list`
- NOT safe — these persist/alter Matt's workspace or saved chart setup and are confirmation-gated
  below, so do not treat `tab_*`/`watchlist_*`/`layout_*`/`pane_*`/indicator tools as blanket-safe:
  `chart_manage_indicator`, `indicator_set_inputs` (add/remove indicators and change their
  settings), `watchlist_add`, `tab_new`, `tab_close`, `layout_switch`, `pane_set_layout`,
  `pane_set_symbol`. To read an indicator, use `data_get_study_values` on one already on the chart.
- **`chart_set_timeframe` takes a TradingView resolution** (`1`, `5`, `15`, `60`, `240`,
  `D`, `W`, `M`), not a `15m`/`1h` alias. Normalize aliases before the call (`15m`→`15`,
  `1h`→`60`, `4h`→`240`, `1d`→`D`) and confirm the switch with `chart_get_state` — an
  unrecognized value can silently leave the chart on its prior resolution.

**Pine Script dev — read/compile only (safe):**
- `pine_get_source`, `pine_smart_compile`, `pine_check`, `pine_get_errors`,
  `pine_get_console`, `pine_analyze`, `pine_list_scripts`
- Use to lint/compile the STC + ATR strategy before wiring alerts (PF 5.27 / Sharpe 4.16
  on 1h per the setup doc). Backtest claims still go through the engine, not TV's tester.
- Note: `pine_set_source` replaces the editor buffer and `pine_new`/`pine_open` change which
  script is open — read `pine_get_source` first and treat these as edits, not reads.

**Replay (practice only):** `replay_start/step/autoplay/trade/status/stop`

**Confirmation-gated (real side effects):** `pine_save` (persists/overwrites Matt's saved
Pine script — never save while merely linting/compiling), `pine_set_source`,
`chart_manage_indicator`, `indicator_set_inputs`, `watchlist_add`, `tab_new`, `tab_close`,
`layout_switch`, `pane_set_layout`, `pane_set_symbol`, `alert_create`, `alert_delete`,
`draw_shape`, `draw_remove_one`, `draw_clear`, `ui_click`, `ui_evaluate`, `batch_run` — these
mutate Matt's TV session/account/workspace/chart setup. Read the current
state first, state what you'll change, and only proceed on an explicit instruction.

## Standard chart-read flow

1. `tv_health_check` → confirm `cdp_connected: true`. If not, stop → `docs/tv-mcp-startup.md`.
2. `chart_set_symbol` + `chart_set_timeframe` to the jarvis symbol/TF you were asked about.
3. `data_get_ohlcv` (+ `data_get_study_values` if an indicator is on the chart).
4. `capture_screenshot` if a visual helps.
5. Summarize levels/structure. **Cross-check any price against the engine feed** for the same
   symbol/timeframe you charted, via the fixed read-only helper:
   `bash scripts/tv-engine-crosscheck.sh <symbol> <engine_tf>`. It loads the key (exported
   `$JARVIS_API_KEY`, else `API_KEY` from `engine/.env`; exits 3 to skip if neither resolves —
   don't report bogus drift), sends `X-API-Key`, and GETs only `/prices/snapshot` (its default
   set omits MGC) and `/hidden-pivots/levels` — no side-effecting routes. Mind the two timeframe
   encodings: the chart is set with a **TradingView resolution** (`15`/`60`/`D`) but the helper
   wants the **engine alias** (`1m`/`5m`/`15m`/`1h`/`4h`/`1d`, e.g. `60`→`1h`, `D`→`1d`; `1m` is a
   real bar — `market_data.py` maps it for IBKR and Polygon) — a bare TV resolution reaching
   `get_bars` silently degrades to 5m bars (`market_data.py` bar maps).
   Round-trip drift is a bug, not cosmetic (see CLAUDE.md numeric-accuracy discipline). Never
   present a TV number as canonical without that check.

## Rejected integration (documented on purpose)

The companion repo
[jackson-video-resources/claude-tradingview-mcp-trading](https://github.com/jackson-video-resources/claude-tradingview-mcp-trading)
is an **autonomous crypto-exchange execution bot** (BitGet/Binance/Bybit/… live API keys,
LLM one-shot prompt that places real orders). It is **not integrated** and must not be —
it violates the non-negotiables: paper-only, IB-futures-only, human-approval-required, and
"safety layer is hardcoded, never LLM-driven". Its only safe idea (extracting a strategy
spec from a trader's transcript into a rules file) is orthogonal to execution and would go
through the engine's normal backtest/paper gates if ever wanted — not through an exchange
bot. Do not add exchange API keys or any auto-execution path to this repo.

## Related

- `.mcp.json` — the `tradingview` server registration
- `docs/tv-mcp-startup.md` — CDP startup persistence + troubleshooting
- `scripts/tradingview/TRADINGVIEW_SETUP.md` — Pine webhook → engine signal flow
- `docs/tradingview-kraken-integration-2026-04-16.md` — activation history
- `/jarvis-tv-chart` — slash command for the quick read flow above
