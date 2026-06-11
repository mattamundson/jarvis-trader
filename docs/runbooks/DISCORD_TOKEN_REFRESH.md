# Runbook — Refresh the Discord Token (futures-sentiment feed)

**When to run this:** `Jarvis-DiscordAutoImport` shows `LastTaskResult=1`, or DCE logs
`Authentication token is invalid`, or futures-sentiment commentary has gone stale
(no new `discord_corey_commentary` / `discord_daily_sentiment` rows).

## Why this matters (the blast radius)

`engine/.env → DISCORD_TOKEN` authenticates **DiscordChatExporter (DCE)**, which exports
the **#market-updates** channel (`806343100435660801`). That channel is the **sole feed**
for `CoreyCommentaryProcessor` (`engine/agents/social_analyst.py:347-356`) — the only
sanctioned source of MES/MNQ/MCL/MGC futures sentiment (no Reddit/Twitter/PRAW).

When the token is invalid:
- `scripts/discord-auto-import.ps1` hard-fails on the P1 channel → exits 1 → task result `1`.
- The commentary processor never runs → `corey_commentary` + `daily_sentiment` freeze.
- (As of the 2026-06-03 incident, frozen at 2026-05-23.)

The token usually dies because of a **Discord account password change** (which revokes all
existing user tokens) or Discord rotating the session.

## What kind of token this is

`DISCORD_TOKEN` is a **Discord USER token** (DCE uses it to read channels you, the user,
can see). A user token grants **full access to your Discord account** — treat it like a
password. Never commit it, never paste it into chat/logs. `engine/.env` is gitignored and
is the correct home.

> Bot-token alternative: if a bot account is ever added to Corey's server with read access,
> a **bot** token works too and doesn't expire on password changes. Until then, it's a user token.

## Step 1 — Obtain a fresh user token

Official method (Tyrrrz/DiscordChatExporter wiki):
https://github.com/Tyrrrz/DiscordChatExporter/wiki/Obtaining-Token%3A-User

1. Open **Discord in a web browser** (discord.com/app) and log in as yourself.
2. Open DevTools (**F12** or Ctrl+Shift+I) → **Network** tab.
3. In the filter box type `/api` and click any channel so requests appear.
4. Click any request to `discord.com/api/...` → **Headers** → request header
   **`authorization`**. Copy that value (it's the token — a long string, NOT your password).
5. Close DevTools. (Do not share or screenshot this value.)

> If you just changed your Discord password, do steps above **after** the change so you
> capture the new, valid token.

## Step 2 — Update `engine/.env`

Edit `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env`, line with `DISCORD_TOKEN=`:

```
DISCORD_TOKEN=<paste the new token, no quotes, no spaces>
```

Save. (No engine restart needed — the import script reads `engine/.env` fresh on each run.)

## Step 3 — Re-enable + verify the task

The task is currently **Disabled** (correctly, while the token was dead). Re-enable and
run it on demand:

```powershell
Enable-ScheduledTask -TaskName "Jarvis-DiscordAutoImport"
Start-ScheduledTask  -TaskName "Jarvis-DiscordAutoImport"
Start-Sleep -Seconds 90
(Get-ScheduledTask -TaskName "Jarvis-DiscordAutoImport" | Get-ScheduledTaskInfo).LastTaskResult
```

`LastTaskResult = 0` ⇒ success. Non-zero ⇒ check the log:
`C:\Users\mattm\ThinkorSwim\jarvis-trader\logs\discord-import-<yyyymmdd>.log`.

You can also run the importer directly to see live output:
```powershell
pwsh -NoProfile -File "C:\Users\mattm\ThinkorSwim\jarvis-trader\scripts\discord-auto-import.ps1"
```
Expect: `DCE: N/15 channels exported successfully` then the Python importer summary.

## Step 4 — Confirm sentiment actually refreshed

After a successful run, the commentary processor should have written fresh rows. Quick check:
```powershell
# newest corey commentary timestamp (should be today)
& "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe" -c "import sqlite3,os; os.chdir(r'C:\Users\mattm\ThinkorSwim\jarvis-trader'); c=sqlite3.connect('engine/data/jarvis_trader.db'); r=c.execute('select max(created_at) from discord_corey_commentary').fetchone(); print('latest corey_commentary:', r[0])"
```
If the timestamp is current, the feed is live again.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| DCE: `Authentication token is invalid` | token expired/revoked | redo Step 1 (fresh token) |
| `DiscordChatExporter.Cli.exe not found` | DCE uninstalled/moved | `winget install Tyrrrz.DiscordChatExporter.CLI` |
| P1 export fails, exit 1 | #market-updates unreachable / token lacks access | confirm you're still in Corey's server with that account |
| Task `0x800710E0` | battery gate | `pwsh -File ~/scripts/ensure-jarvis-task-battery-flags.ps1` |

## Security note

If the token ever leaks (committed, pasted, screenshotted): **change your Discord
password immediately** — that revokes the leaked token — then redo this runbook to get a
fresh one. A leaked user token = full account takeover.
