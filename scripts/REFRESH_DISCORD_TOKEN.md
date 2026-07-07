# Refresh Discord Token — turnkey runbook (Task 2)

**Why:** `Jarvis-DiscordAutoImport` is Disabled and last failed `0x1` because the
`DISCORD_TOKEN` in `engine/.env` is invalid (revoked, likely by a Discord password
change). That import is the **sole** feed for `CoreyCommentaryProcessor`
(`social_analyst.py:347-356`), so futures sentiment (MES/MNQ/MCL/MGC) is frozen at
**2026-05-23**. This also unblocks the deferred Task 10 (channel_id migration).

**Preconditions (all verified 2026-06-04):** DCE installed; token at `.env:323`;
import script `scripts/discord-auto-import.ps1` intact (P1 channel = market-updates
`806343100435660801`).

All commands run in your interactive shell (prefix with `!` in Claude, or a normal
PowerShell window). The agent is gated from `.env`/token/scheduled-task writes.

---

## 1. Get a fresh Discord USER token
DCE needs a *user* token (not a bot token). Method (DCE wiki):
- Open Discord in a browser, log in.
- F12 -> Network tab -> filter `/api` -> click any request -> Headers ->
  copy the `authorization:` value. (Or DevTools console / localStorage method per
  https://github.com/Tyrrrz/DiscordChatExporter/wiki/Obtaining-Token)
- It's ~70 chars. Treat it like a password — never paste it into chat.

## 2. Write it into engine/.env (line 323) — encoding-safe, echoes only length
```powershell
$f='C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env'; $new='PASTE_NEW_TOKEN_HERE'; $enc=New-Object System.Text.UTF8Encoding($false); $l=[IO.File]::ReadAllLines($f); for($i=0;$i -lt $l.Count;$i++){ if($l[$i] -match '^DISCORD_TOKEN='){ $l[$i]="DISCORD_TOKEN=$new" } }; [IO.File]::WriteAllLines($f,$l,$enc); "DISCORD_TOKEN updated (len $($new.Length))"
```

## 3. TEST the token before re-enabling (single export, no DB write)
```powershell
$f='C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env'; $tok=((Select-String $f -Pattern '^DISCORD_TOKEN=' | Select-Object -First 1).Line -replace '^DISCORD_TOKEN=','').Trim(); $dce="$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Tyrrrz.DiscordChatExporter.CLI_Microsoft.Winget.Source_8wekyb3d8bbwe\DiscordChatExporter.Cli.exe"; & $dce export --channel 806343100435660801 --token $tok --format Json --output "$env:TEMP\dce-test" --after (Get-Date).AddDays(-2).ToString('yyyy-MM-dd'); "exit=$LASTEXITCODE (0 = token valid)"
```
- `exit=0` -> token works, proceed to step 4.
- non-zero / "Authentication token is invalid" -> token wrong; redo step 1.

## 4. Re-enable + run the task
```powershell
Enable-ScheduledTask -TaskName 'Jarvis-DiscordAutoImport'; Start-ScheduledTask -TaskName 'Jarvis-DiscordAutoImport'
```

## 5. Verify (give it ~2-3 min to export + import)
```powershell
"LastResult=0x{0:X}" -f (Get-ScheduledTaskInfo -TaskName 'Jarvis-DiscordAutoImport').LastTaskResult
$py='C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe'; & $py -c "import sqlite3; c=sqlite3.connect('file:C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/data/jarvis_trader.db?mode=ro',uri=True); print('latest commentary:', c.execute('SELECT MAX(timestamp) FROM discord_corey_commentary').fetchone()[0])"
```
- Want `LastResult=0x0` and `latest commentary` dated **today**.
- Then ping the agent — it'll confirm via the discord-jarvis MCP (`get_daily_sentiment`
  / `search_commentary`) that sentiment is flowing again, and re-arm Task 10.

## Security
Token is a personal credential; it stays only in `engine/.env` (project-scoped,
gitignored) — never home root, never chat. If you'd rather store it in 1Password,
say so and we'll wire `load-secrets.ps1` to inject it instead.
