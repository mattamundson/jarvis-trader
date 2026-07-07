# Kraken — Install, Keys, Paper-First Workflow

> **Scope.** How to wire `krakenfx/kraken-cli` into jarvis-trader as the
> crypto backend, with paper-first discipline and live trading gated behind
> `KRAKEN_LIVE_ENABLED=True` plus WhatsApp approval.

## What this adds

Before: jarvis-trader's crypto module (`engine/markets/crypto/`) delegates
to a running Freqtrade instance. No orders placed directly from Python.

After: `CRYPTO_BACKEND=kraken` swaps the backend to a thin wrapper around
`kraken-cli` (Rust binary, 151 commands, built-in MCP server, paper engine
for spot AND futures). jarvis-trader's pipeline signals now submit real
orders — to Kraken's paper engine by default, to the live exchange only
when explicitly unlocked.

## Install the binary

### Option A — prebuilt release (recommended)

```powershell
# Download latest release artifact for your platform
Invoke-WebRequest `
  -Uri https://github.com/krakenfx/kraken-cli/releases/latest/download/kraken-cli-windows-x86_64.zip `
  -OutFile $env:TEMP\kraken-cli.zip
Expand-Archive $env:TEMP\kraken-cli.zip -DestinationPath C:\Users\mattm\bin -Force
# Ensure C:\Users\mattm\bin is on PATH (run `echo %PATH%` to verify)
kraken --version
```

### Option B — from source

```bash
cargo install --git https://github.com/krakenfx/kraken-cli
# Binary lands at ~/.cargo/bin/kraken — add to PATH if not already.
```

## Create Kraken API keys

Kraken requires **separate** API keys for spot vs futures. Both are optional
until you flip `KRAKEN_LIVE_ENABLED=True`.

1. **Spot keys** — `https://www.kraken.com/u/security/api` →
   *Generate new key*. Permissions: `Query Funds`, `Query Open Orders`,
   `Create & Modify Orders`, `Cancel/Close Orders`. **Do not** enable
   withdrawal permissions; jarvis-trader never needs them.
2. **Futures keys** — `https://futures.kraken.com/trade/settings/api`.
   Same least-privilege principle. Check `Read`, `Trade`.

Store both pairs in `.env` (never in git):

```dotenv
CRYPTO_BACKEND=kraken
KRAKEN_LIVE_ENABLED=False

KRAKEN_SPOT_API_KEY=
KRAKEN_SPOT_API_SECRET=
KRAKEN_FUTURES_API_KEY=
KRAKEN_FUTURES_API_SECRET=
```

## Initialize the paper engine

```bash
# Starts fresh with $10,000 simulated USD for spot + futures
kraken paper init --balance 10000
# Quick sanity check
kraken paper balance -o json
kraken paper buy BTCUSD 0.001 --type market -o json
kraken paper positions -o json
```

These commands require no API keys — kraken-cli's paper engine runs locally.

## Switch jarvis-trader to Kraken

```bash
# 1. Edit .env
echo "CRYPTO_BACKEND=kraken" >> /c/Users/mattm/ThinkorSwim/jarvis-trader/.env
# 2. Restart engine so the new config is picked up
cd /c/Users/mattm/ThinkorSwim/jarvis-trader
./restart_engine.ps1
# 3. Verify backend choice in logs
grep "Crypto backend" /c/Users/mattm/ThinkorSwim/jarvis-trader/logs/engine.log | tail -1
# Expected:  Crypto backend: kraken (paper)
```

## Register kraken-cli as an MCP server (optional but recommended)

`.mcp.json` ships with a `kraken` entry that starts kraken-cli's built-in
MCP server. This gives Claude Code sessions direct access to all 151 Kraken
commands without Python glue — parity with the `tradingview` MCP.

```json
{
  "mcpServers": {
    "tradingview": { "command": "node", "args": ["..."], "env": {} },
    "kraken":      { "command": "kraken", "args": ["mcp", "serve"], "env": {} }
  }
}
```

After editing `.mcp.json`, restart Claude Code so the MCP server is loaded.
Test with: `kraken:balance` inside a Claude Code session.

> **Note.** The `mcp serve` subcommand is described in the project's README
> but not demonstrated in the current release notes. If `kraken mcp --help`
> does not list a `serve` subcommand, drop the MCP entry and rely on the
> Python adapter only — the runtime pipeline does not need the MCP server.

## Go live

When you're ready to promote from paper to live:

1. **Verify paper performance.** At minimum: 30+ closed paper trades,
   positive net P&L, no stop-loss violations. Same bar as IBKR futures live.
2. **Wire WhatsApp approval.** Kraken orders must go through the same
   `openclaw_notifier.notify_approval_required()` gate used for futures.
   `CryptoMarketModule.execute_signal` submits via `kraken_adapter.submit_order`
   regardless — the approval gate is enforced one layer up.
3. **Flip the flag.**
   ```dotenv
   KRAKEN_LIVE_ENABLED=True
   ```
   Then `./restart_engine.ps1`. Logs should show:
   `Crypto backend: kraken (LIVE)`.

## Rate limits & failure modes

- **Public endpoints**: ~1 req/s. `KrakenAdapter` implements exponential
  backoff on 429 responses (`_MAX_RETRIES=3`, base 0.5s). Pipeline cadence
  (every 15 min per symbol) is far below this so you should never hit it
  organically — a burst of 429s usually means something is polling in a
  tight loop. Investigate before disabling the backoff.
- **Missing binary**: `KrakenAdapter.is_available()` caches False and all
  queries return None. The crypto module falls back to
  `MarketStatus.ERROR` — health-check shows `Kraken CLI` status.
- **JSON parse errors**: logged at DEBUG, method returns None or []. Never
  raises into the pipeline.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `kraken: command not found` | Add install location to PATH or use absolute path in `.mcp.json` |
| Engine logs show `Crypto backend: freqtrade` after setting `CRYPTO_BACKEND=kraken` | Engine wasn't restarted. `./restart_engine.ps1` |
| All `kraken paper` commands return permission errors | Paper engine may not be initialized. Run `kraken paper init --balance 10000` once |
| Live orders rejected silently | Check that both `KRAKEN_LIVE_ENABLED=True` AND the approval flow actually approved the signal — `openclaw_notifier` logs contain the decision |
| MCP server entry breaks Claude Code startup | `kraken mcp serve` subcommand may not exist in your release. Remove the entry from `.mcp.json` — the Python adapter works without it |

## Related files

- `engine/markets/crypto/kraken_adapter.py` — thin async wrapper
- `engine/markets/crypto/module.py` — backend selector, MarketModule surface
- `engine/execution/order_router.py` — `CRYPTO_SPOT_SYMBOLS` routing
- `engine/utils/position_sizing.py` — `calculate_crypto_position_size`
- `engine/config.py` — Kraken config fields
- `.mcp.json` — MCP server registration
