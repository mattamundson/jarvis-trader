# Schwab API — OAuth Setup Guide

JARVIS Trader uses the `schwab-py` library for equity and options execution (Phase 3).
Schwab **cannot** execute futures orders — IB Gateway handles those.

---

## Step 1 — Create a Schwab Developer App

1. Go to **https://developer.schwab.com** and sign in with your Schwab account.
2. Click **"My Apps"** → **"Create App"**.
3. Fill in:
   - **App Name**: `JARVIS Trader` (or any name)
   - **Callback URL**: `https://127.0.0.1`  ← exact match required
   - **Description**: anything you like
4. Submit and wait for approval (usually instant for personal apps).
5. Once approved, copy your **App Key** and **App Secret** from the app detail page.

---

## Step 2 — Add Keys to engine/.env

Open `engine/.env` and fill in the Schwab section near the bottom:

```
SCHWAB_APP_KEY=<your App Key here>
SCHWAB_APP_SECRET=<your App Secret here>
SCHWAB_CALLBACK_URL=https://127.0.0.1
SCHWAB_READY=False          # keep False until token is generated
```

**Never commit .env to git** — it is already in .gitignore.

---

## Step 3 — Generate the OAuth Token (PowerShell)

Run this from the `engine/` directory using the project's virtual environment Python:

```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine

.venv\Scripts\python.exe -c "
import schwab
schwab.auth.easy_client(
    api_key='<SCHWAB_APP_KEY>',
    app_secret='<SCHWAB_APP_SECRET>',
    callback_url='https://127.0.0.1',
    token_path='.schwab_token.json'
)
"
```

Replace `<SCHWAB_APP_KEY>` and `<SCHWAB_APP_SECRET>` with your actual values.

**What happens:**
1. A browser window opens to the Schwab OAuth login page.
2. Log in and authorize the app.
3. Schwab redirects to `https://127.0.0.1/?code=...` (the page will fail to load — that's fine).
4. Copy the **full redirect URL** from your browser address bar.
5. Paste it into the terminal prompt when asked.
6. The token is saved to `engine/.schwab_token.json`.

---

## Step 4 — Activate Schwab

Once the token file exists and keys are in `.env`, set:

```
SCHWAB_READY=True
```

Then restart the JARVIS engine:

```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8010 --reload
```

On startup you should see:
```
✅ SchwabConnector initialized and wired into OrderRouter
✅ Schwab wired into MarketDataManager as Tier 2 price source
```

---

## Step 5 — Token Refresh Schedule

Schwab OAuth tokens expire every **7 days**.

To re-authenticate, re-run the PowerShell command from Step 3.
The new token overwrites `.schwab_token.json` automatically.

**JARVIS will warn you at startup** if the token expires in less than 2 days:
```
WARNING - SchwabConnector: token expires in N day(s) — re-auth required soon
```

Set a recurring calendar reminder every 6 days to stay ahead of expiry.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `SCHWAB_READY gate not enabled` | Set `SCHWAB_READY=True` in `.env` |
| `token not found at .schwab_token.json` | Run Step 3 to generate token |
| `SCHWAB_APP_KEY/SECRET not set` | Fill in `.env` from Step 2 |
| `HTTP 401` on startup | Token expired — run Step 3 again |
| Browser redirect to `https://127.0.0.1` shows error | Normal — copy the URL and paste it |

---

## File Locations

| File | Purpose |
|---|---|
| `engine/.env` | API keys and config (never commit) |
| `engine/.schwab_token.json` | OAuth token (never commit, expires 7 days) |
| `engine/execution/schwab_connector.py` | Connector implementation |
| `engine/routers/schwab_router.py` | FastAPI endpoints for Schwab |
