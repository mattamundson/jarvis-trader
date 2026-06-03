# Discord Token Refresh — Jarvis-DiscordAutoImport

`Jarvis-DiscordAutoImport` runs every 15 minutes and exports ~15 Discord channels (market-updates P1 + 14 secondary) to `discord-export/` using DiscordChatExporter (DCE). It authenticates with a user token stored in `engine/.env`. User tokens expire or get invalidated — this is the refresh procedure.

## When to use this

- Task last result is non-zero (FAIL) and DCE logs show "Authentication token is invalid"
- Scheduled task is Disabled with `FAIL(0x1)` and has not run recently
- You rotated your Discord password or Discord invalidated your session

---

## Step 1 — Obtain a fresh Discord user token

Discord user tokens are extracted from the browser network traffic while logged in.

1. Open **Chrome** (or Edge) and go to [discord.com](https://discord.com) — log in if needed.
2. Open DevTools: `F12` → **Network** tab.
3. Filter by `XHR` or `Fetch`.
4. Click on any channel or DM to trigger a request.
5. In the request list, click any request to `discord.com/api/` (e.g. `channels/...` or `users/@me`).
6. In the **Request Headers** panel, find the `Authorization` header.
7. Copy the value — it looks like `MTM...` or similar (a long alphanumeric string, NOT `Bot MTI...`).

**Security note:** This is your personal Discord user token. Treat it like a password — never commit it, never share it. It grants full account access.

---

## Step 2 — Update engine/.env

Open `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env` and find (or add) the line:

```
DISCORD_TOKEN=<paste-your-token-here>
```

Replace the existing value. The file is gitignored; no commit needed.

---

## Step 3 — Re-enable the scheduled task

```powershell
Enable-ScheduledTask -TaskName "Jarvis-DiscordAutoImport"
```

---

## Step 4 — Verify it works

Wait for the next 15-minute trigger (or run manually):

```powershell
# Manual run
Start-ScheduledTask -TaskName "Jarvis-DiscordAutoImport"
Start-Sleep 60

# Check last result
(Get-ScheduledTask -TaskName "Jarvis-DiscordAutoImport").LastTaskResult
# Expected: 0 (success)

# Tail the log
Get-Content "C:\Users\mattm\ThinkorSwim\jarvis-trader\logs\discord-auto-import.log" -Tail 30
# Expected: "DCE: N/15 channels exported successfully"
```

If DCE still reports "Authentication token is invalid" — the token was copied incorrectly or a `Bot ` prefix was accidentally included. Re-do Step 1.

---

## Channel reference

| Channel | ID | Priority |
|---|---|---|
| market-updates (Corey commentary) | `806343100435660801` | P1 — hard fail if missing |
| indicator-alerts | `1133508659993915492` | secondary |
| proton-bot-alerts | `1133171126751735879` | secondary |
| es | `1134346527096184914` | secondary |
| nq | `1134346568317808710` | secondary |
| gc | `1134346604225241158` | secondary |
| cl | `1134346687519936596` | secondary |
| ym | `1139200691949273138` | secondary |
| rty | `1139199780321509416` | secondary |
| eurusd | `1134346637993594890` | secondary |
| btc | `1280340964061216843` | secondary |
| spy | `1134346719690240052` | secondary |
| trade-alerts | `1130292150962245642` | secondary |
| general | `741484321142997086` | secondary |
| jarvis-trader bookmarks | `1490851279180660819` | secondary |

---

## Technical notes

- Worker script: `scripts/discord-auto-import.ps1`
- Token source: `engine/.env` → `DISCORD_TOKEN` (read at runtime, not cached)
- DCE exports last 2 days incrementally (`--after <date-2d>`)
- After export, runs `python -m engine.discord.cli --source discord-export/ --trigger-commentary`
- P1 (market-updates) failure → hard exit 1; secondary channel failures are logged but non-fatal
- DCE binary: resolved via WinGet install path → `winget list` → PATH
- Reference: [DiscordChatExporter — Obtaining Token](https://github.com/Tyrrrz/DiscordChatExporter/wiki/Obtaining-Token)
