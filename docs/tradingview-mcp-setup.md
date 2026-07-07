# TradingView MCP — Setup, Validation, and Gamma-Levels Overlay

> **Scope.** One-time setup of `tradesdontlie/tradingview-mcp` for this repo,
> validated via the canonical `tv_health_check` tool, plus the extra step for
> loading the "MY FREE GAMMA LEVELS" Pine Script so JARVIS can read its plotted
> levels.

## Background

JARVIS TRADER uses `tradesdontlie/tradingview-mcp` (Node.js, Chrome DevTools
Protocol) to read live indicator values from TradingView Desktop. The MCP is
already wired in `.mcp.json` and consumed by `engine/data/tv_indicator_bridge.py`,
which flattens 45+ Pine Script fields into `tv_*` keys that feed the 10-agent
pipeline.

Reference: Miles Deutscher's FULL GUIDE (2026-04-16) —
`https://x.com/milesdeutscher/status/2044536031991763414`.

## Prerequisites

| Dep | Required | Notes |
| --- | --- | --- |
| Claude Code Desktop | latest | already installed on this machine |
| Node.js | 18+ | the MCP server runtime |
| TradingView Desktop app | latest | download from `tradingview.com/desktop` |
| TradingView subscription | Pro or higher | needed for real-time data |
| Chrome launched with `--remote-debugging-port=9222` | yes | the MCP attaches to this port |

Missing Chrome debug port is the single most common cause of `tv_health_check`
failures. See `Troubleshooting` below.

## Install or reinstall

If this is a first-time install, or the clone at
`C:\Users\mattm\ThinkorSwim\jarvis-trader\tradingview-mcp\` is missing or
stale, paste this exact prompt into Claude Code (the canonical prompt from
Miles Deutscher's guide):

> Install the TradingView MCP server. Clone and explore
> `https://github.com/tradesdontlie/tradingview-mcp`, run `npm install`,
> add to my MCP config at `~/.claude/.mcp.json`, and launch TradingView with
> the debug port.

Claude will:

1. Clone the repo locally.
2. Run `npm install` (or `pnpm install`) inside it.
3. Add a `tradingview` entry to `.mcp.json`.
4. Print the command for starting Chrome with remote debugging.

`.mcp.json` should end up with an entry like:

```json
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["C:/Users/mattm/ThinkorSwim/jarvis-trader/tradingview-mcp/src/server.js"],
      "env": {}
    }
  }
}
```

After install, **restart Claude Code** so the MCP server is loaded.

## Validate

From Claude Code, invoke the `tv_health_check` tool. Expected response:

> Connection confirmed. Here's the health check result…

Other quick checks:

```bash
tv symbol ES1!                # switch chart to ES futures
tv data get-quote -s ES1!     # snapshot quote JSON
```

From Python side:

```bash
curl -H "X-API-Key: ${JARVIS_API_KEY}" \
  http://localhost:8010/tv/snapshot?symbol=MES
```

A healthy response returns 45+ `tv_*` fields. If you see
`"data_quality": "unavailable"`, re-check the Chrome debug port and
`tv_health_check`.

## Load JARVIS Pine Scripts on each chart

For the manifest pattern to work, `JARVIS_MCP_Manifest.pine` must be loaded
on the active chart for each symbol you want to read. Use the repo's
pre-flight loader:

```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
python scripts/tradingview/load_all_pine.py
```

Individual fallback works automatically if the manifest is not present.

## Load the gamma-levels indicator (new, 2026-04-16)

JARVIS now parses an additional Pine Script overlay: **"MY FREE GAMMA LEVELS"**
by `TheRealDrip2Rip`. Source is closed, so we read plotted labels instead of
computing the math ourselves.

One-time step per chart:

1. Open the chart in TradingView Desktop (e.g. `SPX`, `QQQ`, `ES1!`, `NQ1!`).
2. Open the **Indicators** dialog.
3. Search for `MY FREE GAMMA LEVELS` by `TheRealDrip2Rip`.
4. Add it to the chart. Keep its default settings.
5. Save the chart layout so the indicator persists across TradingView
   restarts.

After the indicator is loaded, JARVIS reads the 7 levels (GEX Flip, Call Wall,
Put Wall, HVL, Vol Trigger Up/Down, Max Pain) via
`tv data get-pine-labels --filter "MY FREE GAMMA LEVELS"` and exposes them as
`tv_gex_flip`, `tv_call_wall`, `tv_put_wall`, `tv_hvl`, `tv_vol_trigger_up`,
`tv_vol_trigger_down`, `tv_max_pain`.

If the indicator is not present on the chart, these fields are `None` and the
pipeline proceeds without gamma context — no failure mode.

## Troubleshooting

- **`tv_health_check` fails** → Confirm Chrome was started with
  `--remote-debugging-port=9222`. On Windows, the easiest path is to create a
  shortcut with target
  `"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222`
  and pin it to Startup.
- **`tv_health_check` hangs** → TradingView Desktop is not running or the CDP
  bridge is stuck. Quit TradingView, relaunch it, then re-run
  `tv_health_check`.
- **`data_quality=unavailable` from `/tv/snapshot`** → The `tv` CLI is not on
  `PATH` for the engine process. Confirm the engine was started from a shell
  that inherits the correct PATH, or add the CLI location to
  `engine/.env` via `TV_CLI_PATH` (future enhancement — file a follow-up).
- **Manifest returns no labels** → `JARVIS_MCP_Manifest.pine` is not loaded
  on the chart. Run `python scripts/tradingview/load_all_pine.py`.
- **Gamma fields are all `None`** → The "MY FREE GAMMA LEVELS" indicator is
  not on the chart for that symbol. Repeat the load step above.

## Related files

- `.mcp.json` — MCP server registration
- `engine/data/tv_indicator_bridge.py` — Python consumer, 60s TTL cache
- `engine/data/tradingview_feed.py` — flattens bridge output into `tv_*` dict
- `engine/routers/tradingview_router.py` — REST endpoint at `/tv/snapshot`
- `scripts/tradingview/pine/*.pine` — 20+ JARVIS Pine Script indicators
- `scripts/tradingview/load_all_pine.py` — bulk loader with color-namespace
  fixups
