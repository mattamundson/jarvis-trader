# Verification Runbook — DCE Nightly Export + IB Gateway Paper Smoke

> Step-by-step runbook for activating two dormant-but-shipped deliverables. Execute the moment either external dependency becomes available.

---

## What this runbook is for

Two code paths were shipped and are waiting on user-side installs:

- **DCE nightly export**: PM2 cron `jarvis-discord-export` fires 02:00 CT nightly to export Discord channels via DiscordChatExporter.Cli, then ingest into `discord_corey_commentary`. Blocks on: Discord USER token file.
- **IB Gateway paper smoke** (commit `116be8e`): E2E round-trip script that places a BUY MKT → waits fill → SELL MKT → waits close fill in paper mode. Blocks on: IB Gateway running on port 4002.

Each side is independent — do either one without the other.

---

## Side A — DCE Nightly Export Activation

### Preconditions

1. DiscordChatExporter.Cli installed at `C:\Users\mattm\tools\DiscordChatExporter.Cli\DiscordChatExporter.Cli.exe`
   - Download: https://github.com/Tyrrrz/DiscordChatExporter/releases → `DiscordChatExporter.Cli.zip`
   - Alternative path accepted via env var `DCE_CLI_PATH`
2. Discord **user** token file present at `C:\Users\mattm\discord-export\.token`
   - Single line, no quotes, no trailing newline
   - Token format: user token (starts with `mfa.` or similar), NOT a bot token
   - Recommended local installer: `scripts\install-dce-user-token.ps1` prompts with masked input and writes the token file without printing it.
3. PM2 daemon running (`pm2 list` shows the tree)
4. Bandwidth acceptance: ~1.5 GB/week across exported channels — acknowledge before scheduling

### Activation steps

```bash
# 1. Verify DCE binary is executable
ls "C:/Users/mattm/tools/DiscordChatExporter.Cli/DiscordChatExporter.Cli.exe"

# 2. Install/replace the DCE user token safely (interactive masked prompt)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:/Users/mattm/ThinkorSwim/jarvis-trader/scripts/install-dce-user-token.ps1"

# 3. Verify token file exists and is non-empty; do not print contents
test -s "C:/Users/mattm/discord-export/.token" && echo DCE_TOKEN_FILE_OK

# 4. Sanity-run the export + ingest manually (bypasses cron, same script)
cd "C:/Users/mattm/ThinkorSwim/jarvis-trader"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:/Users/mattm/ThinkorSwim/jarvis-trader/scripts/dce-nightly.ps1"

# 5. Bring the PM2 entry online (idempotent)
pm2 start "C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/ecosystem.config.js" --only jarvis-discord-export

# 6. Confirm cron_restart is registered (should show every-day schedule)
pm2 describe jarvis-discord-export | grep -i "cron"

# 7. Save PM2 state so it persists across reboots
pm2 save
```

### Verification (run after the first successful scheduled fire)

```sql
-- Connect: sqlite3 engine/data/jarvis_trader.db

-- Count rows ingested in the last day
SELECT COUNT(*) AS new_rows
  FROM discord_corey_commentary
 WHERE created_at >= datetime('now', '-1 day');

-- Freshness — latest row should be within 24h
SELECT DATE(MAX(timestamp)) AS latest_row,
       julianday('now') - julianday(MAX(timestamp)) AS days_behind
  FROM discord_corey_commentary;

-- Sentiment ETL completion — daily aggregate should exist for yesterday
SELECT date, avg_sentiment, message_count
  FROM discord_daily_sentiment
 WHERE date >= date('now', '-2 days')
 ORDER BY date DESC;
```

### Interpreting results

| Observation                                    | Meaning                                        | Action                                            |
| ---------------------------------------------- | ---------------------------------------------- | ------------------------------------------------- |
| `new_rows > 0`, `days_behind < 1`              | ✓ healthy — cron fired and ingest completed    | None                                              |
| `new_rows = 0`, `days_behind < 1`              | cron fired but Discord had no new messages     | None (legitimate — low-activity night)            |
| `new_rows = 0`, `days_behind > 2`              | cron hasn't fired OR DCE export silently failed | `pm2 logs jarvis-discord-export --lines 100`      |
| `discord_daily_sentiment` empty for yesterday  | DCE completed but sentiment ETL did not run   | Check `[INFO] discord.sentiment_provider` in logs |

### Troubleshooting

| Exit code / error               | Cause                                     | Fix                                               |
| ------------------------------- | ----------------------------------------- | ------------------------------------------------- |
| DCE rc=2                        | `DiscordChatExporter.Cli.exe` not at expected path | Set `DCE_CLI_PATH` env var or install the binary  |
| DCE rc=3                        | `.token` file missing or empty            | Run `scripts\\install-dce-user-token.ps1`        |
| DCE rc=10 + `blocker=invalid_discord_token` | Discord rejected the user token | Rotate/rewrite `C:\\Users\\mattm\\discord-export\\.token`, then rerun `scripts\\dce-nightly.ps1` |
| PM2 entry keeps restarting      | Script exits non-zero on each cron fire   | `pm2 logs jarvis-discord-export --err --lines 50` |
| Rows present but `corey_session_bias` empty | Sentiment ETL failed after ingest   | Re-run `python -m discord.sentiment_provider`     |

### References

- Script: `scripts/dce-nightly.ps1` -> `scripts/dce_nightly_runner.py` (runner)
- PM2 entry: `engine/ecosystem.config.js` (`jarvis-discord-export`, calls `scripts/dce-nightly.ps1`)
- Known issues: `docs/incident-notes/2026-04-17-t2.1-discord-staleness.md`
- Channel IDs: 741484321142997086 (#general), 806343100435660801 (#market-updates)

---

## Side B — IB Gateway Paper Smoke Test

### Preconditions

1. IB Gateway (or TWS) installed and logged into paper account **DUP662235**
2. Gateway listening on port 4002 (`netstat -ano | grep ":4002 "` shows LISTENING)
3. API settings in the Gateway GUI:
   - ActiveX and Socket Clients: **Enabled**
   - Socket port: **4002**
   - Read-Only API: **UNCHECKED** (silent order rejection otherwise)
4. Client ID 7 is free (the smoke script uses 7 to avoid collision with the engine's default `client_id=1`)

### Activation steps

```bash
cd /c/Users/mattm/ThinkorSwim/jarvis-trader/engine

# 1. Confirm port 4002 is up
netstat -ano | grep ":4002 "   # expect LISTENING

# 2. Dry-connect first (connects, qualifies contract, disconnects — no order)
./.venv/Scripts/python -m scripts.smoke_ib_paper_order --dry-connect

# 3. If dry-connect succeeds and Amo explicitly authorizes an order smoke,
# run the full round-trip on MES only. MCL/MNQ/MGC/M2K are DO_NOT_TRADE_SYMBOLS.
./.venv/Scripts/python -m scripts.smoke_ib_paper_order --symbol MES

# 4. Optional: re-run MES only with explicit approval/scope
./.venv/Scripts/python -m scripts.smoke_ib_paper_order --symbol MES
```

### Success criteria

Exit code 0 and log line:

```
SMOKE TEST PASSED | symbol=MES qty=1 buy_id=<order_id> sell_id=<order_id>
```

Both legs must fill within 30 seconds (default timeout per leg).

### Troubleshooting

| Exit code | Meaning                            | Likely cause                                           | Fix                                                   |
| --------- | ---------------------------------- | ------------------------------------------------------ | ----------------------------------------------------- |
| 0         | Success                            | —                                                      | None                                                  |
| 2         | Gateway unreachable on port 4002  | Gateway not running, or different port                 | Launch Gateway, confirm socket port in Global Config  |
| 3         | Connect/auth failed                | Gateway running but didn't accept the session          | Client ID collision; wait 10s and retry               |
| 4         | Contract qualification failed      | Symbol not known or no active front-month              | Check `engine/execution/ib_gateway.py` contract map   |
| 5         | Order placement failed             | Likely Read-Only API is checked in GUI                 | Uncheck Read-Only API, restart Gateway                |
| 6         | Fill timeout on first leg          | Market closed, or liquidity issue                      | Retry MES only within authorized paper-smoke scope    |
| 7         | Round-trip close failed            | First leg filled but SELL did not fill in 30s          | Manually close the stuck position in Gateway UI       |

### References

- Script: `engine/scripts/smoke_ib_paper_order.py`
- IB Gateway connector: `engine/execution/ib_gateway.py`
- Paper trading guide: `engine/docs/PAPER_TRADING_GUIDE.md`
- Port conflict detection: `engine/scripts/port_guardian.py`
- Memory note: paper port is **4002** (live port **4001 is permanently blocked** by policy)

---

## Integration checkpoint (both sides active)

Once both DCE and IBG are live, the engine has its full data surface:

- Discord corey commentary fresh daily (feeds `CoreyAuctionAnalyst` agent via `corey_session_bias`)
- IB Gateway providing live market data (Tier 1 of the data waterfall in `MarketDataManager`)

Spot-check the engine sees both:

```bash
# 1. Corey bias fresh
curl -s http://localhost:8010/corey/bias/latest \
  -H "X-API-Key: $API_KEY" | head -c 300

# 2. IB data waterfall using Tier 1
curl -s "http://localhost:8010/market/price/MES?is_futures=true" \
  -H "X-API-Key: $API_KEY" | grep '"source"'
# Expect: "source":"ibkr"  (was "source":"polygon" or "cache" before)
```

If `"source":"ibkr"` appears and the Corey bias row is from today, both activations succeeded.
