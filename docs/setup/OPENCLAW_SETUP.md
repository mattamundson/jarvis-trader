# OpenClaw Manual Setup — 4 Steps

> No code changes needed. These are interactive auth flows you run once.

---

## Step 1: Google Workspace (`gog auth login`)

This connects OpenClaw to your Gmail, Calendar, and Drive.

### What happens

The `gog` CLI opens a browser for Google OAuth. You sign in with your Google account, grant permissions, and it stores a refresh token locally in WSL.

### Instructions

1. Open a WSL terminal (Windows Terminal → Ubuntu tab, or `wsl -d Ubuntu`)
2. Run:
   ```bash
   gog auth login
   ```
3. A URL will print in the terminal:
   ```
   https://accounts.google.com/o/oauth2/v2/auth?client_id=...&redirect_uri=...&scope=...
   ```
4. Copy that URL and paste it into Chrome on Windows. (WSL can't open a browser directly.)
5. Sign in with your Google account (the one with your IBKR emails).
6. Grant all requested permissions (Gmail, Calendar, Drive, Contacts) → click **Allow**.
7. Terminal confirms:
   ```
   ✓ Authenticated as matt@yourmail.com
   ```
8. Verify:
   ```bash
   gog gmail list --limit 5
   ```
   Should show your 5 most recent emails.

### If it fails

- **"Could not open browser"** → expected in WSL. Copy the URL manually.
- **"Port already in use"** → kill any process on the redirect port, retry.
- **"Access denied"** → run `gog auth --help` for the GCP OAuth client setup wizard.

### What this enables

- "Check my email for IBKR" → searches Gmail
- "What's on my calendar?" → reads Google Calendar
- "Find that PDF in Drive" → searches Google Drive

---

## Step 2: GitHub CLI (`gh auth login`)

This connects OpenClaw to your GitHub repos (jarvis-trader, etc.).

### Instructions

1. Open a WSL terminal and run:
   ```bash
   gh auth login
   ```
2. Walk through the interactive prompts:
   - **Account**: `GitHub.com`
   - **Protocol**: `HTTPS`
   - **Authenticate Git**: `Yes`
   - **Auth method**: `Login with a web browser`
3. It prints a one-time code like `A1B2-C3D4`. Copy it.
4. Open Chrome → go to `https://github.com/login/device`
5. Paste the code → click **Continue** → click **Authorize github**.
6. Terminal confirms:
   ```
   ✓ Authentication complete.
   ✓ Logged in as mattmorrison
   ```
7. Verify:
   ```bash
   gh auth status
   ```

### What this enables

- "Show open PRs on jarvis-trader" → GitHub PR list
- "Show open issues on jarvis-trader" → GitHub issues
- Auto-fetch issues and spawn agents to fix them

---

## Step 3: Alpaca API Keys

This connects the Alpaca MCP server for stock/crypto/options trading via natural language.

### Get your Alpaca keys

1. Go to `https://app.alpaca.markets/signup` (or log in if you have an account)
2. In the dashboard → **API Keys** → **Generate New Keys**
3. Copy both immediately — the **Secret Key is shown only once**:
   ```
   API Key ID:  PK1234ABCD5678EFGH
   Secret Key:  aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd
   ```

### Update the WSL config

4. Run in WSL, replacing the placeholder values with your real keys:
   ```bash
   python3 -c "
   import json
   with open('/root/.openclaw/openclaw.json') as f:
       d = json.load(f)
   d['mcp']['servers']['alpaca']['env']['ALPACA_API_KEY'] = 'PK1234ABCD5678EFGH'
   d['mcp']['servers']['alpaca']['env']['ALPACA_SECRET_KEY'] = 'aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd'
   with open('/root/.openclaw/openclaw.json', 'w') as f:
       json.dump(d, f, indent=2)
   print('Done')
   "
   ```
5. Restart the gateway:
   ```bash
   systemctl --user restart openclaw-gateway.service
   ```
6. Verify:
   ```bash
   openclaw mcp show alpaca
   ```
   Should show your real keys (not `YOUR_ALPACA_KEY_HERE`).

### Test it

- WhatsApp: **"What's AAPL trading at?"** → Alpaca fetches the live price
- WhatsApp: **"Show my Alpaca paper positions"** → account view

### What this enables

- Natural language stock/ETF/crypto/options queries via WhatsApp
- "Buy 10 shares of AAPL" (paper trading)
- "What's my Alpaca portfolio worth?"
- Options chain analysis, historical data, account info

---

## Step 4: Chrome Remote Debugging (CDP)

This lets OpenClaw take screenshots and control Chrome for ThinkorSwim chart capture.

### Option A: Create a dedicated debug Chrome shortcut (recommended)

1. Right-click Desktop → **New → Shortcut**
2. Paste as the location:
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\Users\mattm\chrome-debug-profile"
   ```
   The `--user-data-dir` keeps it isolated from your normal Chrome profile.
3. Name it **Chrome (Debug)** → click **Finish**.
4. Close all Chrome windows, then double-click the new shortcut.
5. Log into ThinkorSwim Web (`https://trade.thinkorswim.com`) in this Chrome instance.

### Option B: Add the flag to your existing Chrome shortcut

1. Right-click Chrome shortcut → **Properties**
2. In the **Target** field, add to the end (after the closing quote):
   ```
    --remote-debugging-port=9222
   ```
3. Click OK. **Close all Chrome windows**, then reopen.

> Chrome must be fully closed before relaunching with the flag. If any Chrome process is running, the flag is ignored.

### Verify CDP is working

4. Open Chrome (debug mode) → go to `http://localhost:9222/json`
5. Should show a JSON list of open tabs:
   ```json
   [
     {
       "id": "ABC123",
       "title": "Google",
       "url": "https://www.google.com/",
       "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/ABC123"
     }
   ]
   ```
6. Also verify from WSL:
   ```bash
   curl -s http://localhost:9222/json | python3 -m json.tool | head -20
   ```

### If WSL can't reach port 9222

Run in **PowerShell as Admin**:
```powershell
netsh interface portproxy add v4tov4 listenport=9222 listenaddress=0.0.0.0 connectport=9222 connectaddress=127.0.0.1
```

Or add to `%USERPROFILE%\.wslconfig`:
```ini
[wsl2]
networkingMode=mirrored
```
Then restart WSL: `wsl --shutdown` and reopen.

### What this enables

- "Take a screenshot of my browser" → captures current Chrome tab
- Future: auto-capture ThinkorSwim charts in morning briefs
- "What do you see on my screen?" → analyzes current tab content

---

## Quick Reference — After All 4 Steps

| Capability | Test (WhatsApp message) | Expected result |
|---|---|---|
| Gmail | "check my email for IBKR" | Gmail search results |
| Calendar | "what's on my calendar today?" | Google Calendar events |
| GitHub | "show open PRs on jarvis-trader" | PR list |
| Alpaca stocks | "what's AAPL trading at?" | Live price via Alpaca |
| Alpaca portfolio | "show my Alpaca positions" | Account positions |
| Chart capture | "take a screenshot of my browser" | Chart image captured |
